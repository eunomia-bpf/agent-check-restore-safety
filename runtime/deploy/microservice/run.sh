#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
compose_file="$script_dir/compose.yaml"
created_state=0
if [[ -z "${DEMO_STATE_DIR:-}" ]]; then
  DEMO_STATE_DIR="$(mktemp -d /tmp/safe-change-microservice.XXXXXX)"
  created_state=1
fi
DEMO_STATE_DIR="$(realpath "$DEMO_STATE_DIR")"
mkdir -p "$DEMO_STATE_DIR/payment" "$DEMO_STATE_DIR/control" \
  "$DEMO_STATE_DIR/anchor" "$DEMO_STATE_DIR/order-config" "$DEMO_STATE_DIR/results"
chmod 700 "$DEMO_STATE_DIR" "$DEMO_STATE_DIR/payment" "$DEMO_STATE_DIR/control" \
  "$DEMO_STATE_DIR/anchor" "$DEMO_STATE_DIR/order-config" "$DEMO_STATE_DIR/results"

free_port() {
  python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()'
}

CONTROL_PORT="${CONTROL_PORT:-$(free_port)}"
ORDER_PORT="${ORDER_PORT:-$(free_port)}"
while [[ "$ORDER_PORT" == "$CONTROL_PORT" ]]; do ORDER_PORT="$(free_port)"; done
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-safe-change-$$}"
RUNTIME_IMAGE="${RUNTIME_IMAGE:-safe-change-runtime:local}"
DEMO_UID="$(id -u)"
DEMO_GID="$(id -g)"
export DEMO_STATE_DIR CONTROL_PORT ORDER_PORT COMPOSE_PROJECT_NAME RUNTIME_IMAGE DEMO_UID DEMO_GID
compose=(docker compose -f "$compose_file")

cleanup() {
  status=$?
  if [[ $status -ne 0 ]]; then
    "${compose[@]}" logs --no-color >&2 || true
  fi
  if [[ "${KEEP_DEMO:-0}" != "1" ]]; then
    "${compose[@]}" down --remove-orphans >/dev/null 2>&1 || true
    if [[ $created_state -eq 1 && "${KEEP_STATE:-0}" != "1" ]]; then
      rm -rf -- "$DEMO_STATE_DIR"
    fi
  fi
  exit "$status"
}
trap cleanup EXIT

write_release() {
  local version=$1 kind=$2 target=$3
  jq -cn --arg version "$version" --arg kind "$kind" --arg target "$target" \
    '{version:$version,kind:$kind,target:$target}' > "$DEMO_STATE_DIR/order-config/order.json.next"
  chmod 600 "$DEMO_STATE_DIR/order-config/order.json.next"
  mv "$DEMO_STATE_DIR/order-config/order.json.next" "$DEMO_STATE_DIR/order-config/order.json"
}

wait_url() {
  local url=$1
  for _ in $(seq 1 60); do
    if curl -fsS "$url" >/dev/null; then return 0; fi
    sleep 1
  done
  echo "timed out waiting for $url" >&2
  return 1
}

admin_post() {
  local path=$1 input=$2 output=$3
  curl -fsS -H "Authorization: Bearer $admin_token" -H 'Content-Type: application/json' \
    --data-binary "@$input" "$control_url$path" > "$output"
}

submit_order() {
  local order_id=$1 amount=$2 output=$3 expected=$4
  local payload status
  payload="$(jq -cn --arg order_id "$order_id" --argjson amount "$amount" '{order_id:$order_id,amount:$amount}')"
  status="$(curl -sS -o "$output" -w '%{http_code}' -H 'Content-Type: application/json' \
    --data-binary "$payload" "$order_url/v1/orders")"
  if [[ "$status" != "$expected" ]]; then
    echo "order $order_id returned HTTP $status, expected $expected" >&2
    jq . "$output" >&2 || true
    return 1
  fi
}

payment_v1='http://payment:8081/v1/charge'
payment_v2='http://payment:8081/v2/charge'
write_release v1 charge-v1 "$payment_v1"

"${compose[@]}" build control
"${compose[@]}" up -d payment control order ingress
control_url="http://127.0.0.1:$CONTROL_PORT"
order_url="http://127.0.0.1:$ORDER_PORT"
wait_url "$control_url/healthz"
wait_url "$order_url/healthz"
admin_token="$(tr -d '\r\n' < "$DEMO_STATE_DIR/control/admin-token")"

jq -cn --arg target "$payment_v1" '{
  id:"orders-v1",results:{paid:1},capacities:{charge:1},kinds:{
    "charge-v1":{costs:{charge:1},produces:{paid:1},retry_safe:true,
      queryable:false,target:$target,method:"POST",response_classifier:"operation-receipt-v1"}
  }
}' > "$DEMO_STATE_DIR/results/requirement-v1.json"
admin_post /v1/compile "$DEMO_STATE_DIR/results/requirement-v1.json" "$DEMO_STATE_DIR/results/certificate-v1.json"
jq -e '.decision == "activate" and .rule != null' "$DEMO_STATE_DIR/results/certificate-v1.json" >/dev/null
admin_post /v1/activate "$DEMO_STATE_DIR/results/certificate-v1.json" "$DEMO_STATE_DIR/results/active-v1.json"

old_order_container="$("${compose[@]}" ps -q order)"
submit_order A-17 42 "$DEMO_STATE_DIR/results/first-order.json" 409
jq -e '.release_version == "v1" and .runtime.outcome.phase == "unknown"' \
  "$DEMO_STATE_DIR/results/first-order.json" >/dev/null

jq -cn --arg target "$payment_v2" '{
  id:"orders-v2",results:{paid:2},capacities:{charge:2},kinds:{
    "charge-v2":{costs:{charge:1},produces:{paid:1},retry_safe:true,
      queryable:false,target:$target,method:"POST",response_classifier:"operation-receipt-v1"}
  }
}' > "$DEMO_STATE_DIR/results/requirement-v2.json"
admin_post /v1/compile "$DEMO_STATE_DIR/results/requirement-v2.json" "$DEMO_STATE_DIR/results/certificate-v2.json"
jq -e '.decision == "activate" and .rule != null' "$DEMO_STATE_DIR/results/certificate-v2.json" >/dev/null
admin_post /v1/activate "$DEMO_STATE_DIR/results/certificate-v2.json" "$DEMO_STATE_DIR/results/active-v2.json"

write_release v2 charge-v2 "$payment_v2"
"${compose[@]}" up -d --force-recreate --no-deps order
wait_url "$order_url/healthz"
new_order_container="$("${compose[@]}" ps -q order)"
[[ "$old_order_container" != "$new_order_container" ]]
jq -e '.version == "v2" and .kind == "charge-v2"' < <(curl -fsS "$order_url/healthz") >/dev/null

control_container="$("${compose[@]}" ps -q control)"
control_pid_before="$(docker inspect -f '{{.State.Pid}}' "$control_container")"
"${compose[@]}" restart control >/dev/null
wait_url "$control_url/healthz"
control_pid_after="$(docker inspect -f '{{.State.Pid}}' "$control_container")"
[[ "$control_pid_before" != "$control_pid_after" ]]

submit_order A-17 42 "$DEMO_STATE_DIR/results/retried-order.json" 200
jq -e '.release_version == "v2" and .requested_kind == "charge-v2" and .runtime.phase == "succeeded"' \
  "$DEMO_STATE_DIR/results/retried-order.json" >/dev/null
submit_order B-18 7 "$DEMO_STATE_DIR/results/new-order.json" 200
jq -e '.release_version == "v2" and .runtime.phase == "succeeded"' \
  "$DEMO_STATE_DIR/results/new-order.json" >/dev/null

if "${compose[@]}" exec -T order wget -T 2 -qO- http://payment:8081/v1/stats >/dev/null 2>&1; then
  echo "order container unexpectedly reached the payment service directly" >&2
  exit 1
fi
payment_stats="$("${compose[@]}" exec -T control wget -qO- http://payment:8081/v1/stats)"
jq -e '.deliveries == 3 and .commits == 2 and .paths["/v1/charge"] == 2 and .paths["/v2/charge"] == 1' \
  <<<"$payment_stats" >/dev/null

curl -fsS -H "Authorization: Bearer $admin_token" "$control_url/v1/state" \
  > "$DEMO_STATE_DIR/results/final-state.json"
jq -e --arg v1 "$payment_v1" --arg v2 "$payment_v2" '
  .requirement.id == "orders-v2" and
  ([.operations[] | select(.kind == "charge-v1" and .target == $v1 and .phase == "succeeded")] | length == 1) and
  ([.operations[] | select(.kind == "charge-v2" and .target == $v2 and .phase == "succeeded")] | length == 1)
' "$DEMO_STATE_DIR/results/final-state.json" >/dev/null

order_networks="$(docker inspect "$new_order_container" | jq -c '.[0].NetworkSettings.Networks | keys')"
control_networks="$(docker inspect "$control_container" | jq -c '.[0].NetworkSettings.Networks | keys')"
payment_container="$("${compose[@]}" ps -q payment)"
payment_networks="$(docker inspect "$payment_container" | jq -c '.[0].NetworkSettings.Networks | keys')"
jq -en --argjson order "$order_networks" --argjson control "$control_networks" --argjson payment "$payment_networks" '
  ([$order[] as $name | $payment[] | select(. == $name)] | length) == 0 and
  ([$order[] as $name | $control[] | select(. == $name)] | length) == 1 and
  ([$payment[] as $name | $control[] | select(. == $name)] | length) == 1
' >/dev/null

history_sequence="$(jq -r '.history.sequence' "$DEMO_STATE_DIR/results/final-state.json")"
old_runtime_kind="$(jq -r '[.operations[] | select(.target == "http://payment:8081/v1/charge")][0].kind' \
  "$DEMO_STATE_DIR/results/final-state.json")"
jq -n \
  --arg first_network_result unknown \
  --arg changed_release v2 \
  --arg old_runtime_kind "$old_runtime_kind" \
  --arg direct_payment_from_order blocked \
  --argjson payment "$payment_stats" \
  --argjson history_sequence "$history_sequence" \
  '{
    first_network_result:$first_network_result,
    order_process_replaced:true,
    changed_release:$changed_release,
    control_process_restarted:true,
    old_order_completed_under_frozen_operation:($old_runtime_kind == "charge-v1"),
    new_order_used_v2:true,
    direct_payment_from_order:$direct_payment_from_order,
    remote_deliveries:$payment.deliveries,
    remote_commits:$payment.commits,
    delivery_paths:$payment.paths,
    history_sequence:$history_sequence
  }'

if [[ "${KEEP_DEMO:-0}" == "1" || "${KEEP_STATE:-0}" == "1" ]]; then
  echo "evidence directory: $DEMO_STATE_DIR" >&2
fi
