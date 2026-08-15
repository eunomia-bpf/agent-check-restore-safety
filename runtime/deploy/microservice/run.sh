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
  "$DEMO_STATE_DIR/anchor" "$DEMO_STATE_DIR/credentials" \
  "$DEMO_STATE_DIR/order-config" "$DEMO_STATE_DIR/proxy-config" "$DEMO_STATE_DIR/results"
chmod 700 "$DEMO_STATE_DIR" "$DEMO_STATE_DIR/payment" "$DEMO_STATE_DIR/control" \
  "$DEMO_STATE_DIR/anchor" "$DEMO_STATE_DIR/credentials" \
  "$DEMO_STATE_DIR/order-config" "$DEMO_STATE_DIR/proxy-config" "$DEMO_STATE_DIR/results"

operation_token_path="$DEMO_STATE_DIR/credentials/operation-token"
if [[ -L "$operation_token_path" || ( -e "$operation_token_path" && ! -f "$operation_token_path" ) ]]; then
  echo "unsafe adapter token path: $operation_token_path" >&2
  exit 1
fi
if [[ ! -e "$operation_token_path" ]]; then
  (umask 077; python3 -c 'import secrets; print(secrets.token_hex(32))' > "$operation_token_path")
fi
chmod 600 "$operation_token_path"

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
  local version=$1
  jq -cn --arg version "$version" \
    '{version:$version,effect_proxy_url:"http://effect-proxy:8788",effect_route:"payment"}' \
    > "$DEMO_STATE_DIR/order-config/order.json.next"
  chmod 600 "$DEMO_STATE_DIR/order-config/order.json.next"
  mv "$DEMO_STATE_DIR/order-config/order.json.next" "$DEMO_STATE_DIR/order-config/order.json"
}

write_proxy_routes() {
  local kind=$1 target=$2
  jq -cn --arg kind "$kind" --arg target "$target" '{
    schema:1,routes:[{
      name:"payment",kind:$kind,method:"POST",url:$target,
      content_types:["application/json"]
    }]
  }' > "$DEMO_STATE_DIR/proxy-config/routes.json.next"
  chmod 600 "$DEMO_STATE_DIR/proxy-config/routes.json.next"
  mv "$DEMO_STATE_DIR/proxy-config/routes.json.next" "$DEMO_STATE_DIR/proxy-config/routes.json"
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

wait_service_healthy() {
  local service=$1 container status
  for _ in $(seq 1 60); do
    container="$("${compose[@]}" ps -q "$service")"
    if [[ -n "$container" ]]; then
      status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$container")"
      if [[ "$status" == healthy ]]; then return 0; fi
    fi
    sleep 1
  done
  echo "timed out waiting for service $service" >&2
  return 1
}

safe_change() {
  docker run --rm \
    --network "$control_network" \
    --user "$DEMO_UID:$DEMO_GID" \
    --read-only \
    --cap-drop ALL \
    --security-opt no-new-privileges:true \
    --mount "type=bind,src=$DEMO_STATE_DIR/control/admin-token,dst=/credentials/admin-token,readonly" \
    --mount "type=bind,src=$DEMO_STATE_DIR/results,dst=/evidence" \
    "$RUNTIME_IMAGE" \
    safe-change "$@" \
    -control http://control:8787 \
    -admin-token-file /credentials/admin-token
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
write_release v1
write_proxy_routes charge-v1 "$payment_v1"

"${compose[@]}" build control
"${compose[@]}" up -d payment control effect-proxy order control-ingress order-ingress
control_url="http://127.0.0.1:$CONTROL_PORT"
order_url="http://127.0.0.1:$ORDER_PORT"
wait_url "$control_url/healthz"
wait_url "$order_url/healthz"
mapfile -t control_networks < <(docker network ls \
  --filter "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME" \
  --filter 'label=com.docker.compose.network=control' \
  --format '{{.Name}}')
if [[ ${#control_networks[@]} -ne 1 ]]; then
  echo "could not resolve the one Compose control network" >&2
  exit 1
fi
control_network="${control_networks[0]}"

jq -cn --arg target "$payment_v1" '{
  id:"orders-v1",results:{paid:1},capacities:{charge:1},kinds:{
    "charge-v1":{costs:{charge:1},produces:{paid:1},retry_safe:true,
      queryable:false,target:$target,method:"POST",response_classifier:"operation-receipt-v1"}
  }
}' > "$DEMO_STATE_DIR/results/requirement-v1.json"
safe_change plan \
  -requirement /evidence/requirement-v1.json \
  -out /evidence/certificate-v1.json \
  > "$DEMO_STATE_DIR/results/plan-v1.json"
jq -e '.decision == "activate" and .rule_version == 1' "$DEMO_STATE_DIR/results/plan-v1.json" >/dev/null
safe_change apply \
  -certificate /evidence/certificate-v1.json \
  > "$DEMO_STATE_DIR/results/active-v1.json"
jq -e '.decision == "activate" and .rule_version == 1' "$DEMO_STATE_DIR/results/active-v1.json" >/dev/null

old_order_container="$("${compose[@]}" ps -q order)"
submit_order A-17 42 "$DEMO_STATE_DIR/results/first-order.json" 409
jq -e '.release_version == "v1" and .proxy == true and
  .requested_route == "payment" and .runtime.phase == "unknown"' \
  "$DEMO_STATE_DIR/results/first-order.json" >/dev/null

jq -cn --arg target "$payment_v2" '{
  id:"orders-v2",results:{paid:2},capacities:{charge:2},kinds:{
    "charge-v2":{costs:{charge:1},produces:{paid:1},retry_safe:true,
      queryable:false,target:$target,method:"POST",response_classifier:"operation-receipt-v1"}
  }
}' > "$DEMO_STATE_DIR/results/requirement-v2.json"
safe_change plan \
  -requirement /evidence/requirement-v2.json \
  -out /evidence/certificate-v2.json \
  > "$DEMO_STATE_DIR/results/plan-v2.json"
jq -e '.decision == "activate" and .rule_version == 2' "$DEMO_STATE_DIR/results/plan-v2.json" >/dev/null
safe_change apply \
  -certificate /evidence/certificate-v2.json \
  > "$DEMO_STATE_DIR/results/active-v2.json"
jq -e '.decision == "activate" and .rule_version == 2' "$DEMO_STATE_DIR/results/active-v2.json" >/dev/null

old_proxy_container="$("${compose[@]}" ps -q effect-proxy)"
write_proxy_routes charge-v2 "$payment_v2"
"${compose[@]}" up -d --force-recreate --no-deps effect-proxy
wait_service_healthy effect-proxy
new_proxy_container="$("${compose[@]}" ps -q effect-proxy)"
[[ "$old_proxy_container" != "$new_proxy_container" ]]

write_release v2
"${compose[@]}" up -d --force-recreate --no-deps order
wait_url "$order_url/healthz"
new_order_container="$("${compose[@]}" ps -q order)"
[[ "$old_order_container" != "$new_order_container" ]]
jq -e '.version == "v2" and .proxy == true and .requested_route == "payment"' \
  < <(curl -fsS "$order_url/healthz") >/dev/null

control_container="$("${compose[@]}" ps -q control)"
control_pid_before="$(docker inspect -f '{{.State.Pid}}' "$control_container")"
"${compose[@]}" restart control >/dev/null
wait_url "$control_url/healthz"
control_pid_after="$(docker inspect -f '{{.State.Pid}}' "$control_container")"
[[ "$control_pid_before" != "$control_pid_after" ]]

submit_order A-17 42 "$DEMO_STATE_DIR/results/retried-order.json" 200
jq -e '.release_version == "v2" and .proxy == true and
  .requested_route == "payment" and .runtime.outcome == "succeeded"' \
  "$DEMO_STATE_DIR/results/retried-order.json" >/dev/null
submit_order B-18 7 "$DEMO_STATE_DIR/results/new-order.json" 200
jq -e '.release_version == "v2" and .proxy == true and
  .requested_route == "payment" and .runtime.outcome == "succeeded"' \
  "$DEMO_STATE_DIR/results/new-order.json" >/dev/null

if "${compose[@]}" exec -T order wget -T 2 -qO- http://payment:8081/v1/stats >/dev/null 2>&1; then
  echo "order container unexpectedly reached the payment service directly" >&2
  exit 1
fi
if "${compose[@]}" exec -T order wget -T 2 -qO- http://control:8787/healthz >/dev/null 2>&1; then
  echo "order container unexpectedly reached the control service directly" >&2
  exit 1
fi
"${compose[@]}" exec -T order wget -qO- http://effect-proxy:8788/healthz >/dev/null
if "${compose[@]}" exec -T effect-proxy wget -T 2 -qO- http://payment:8081/v1/stats >/dev/null 2>&1; then
  echo "effect proxy unexpectedly reached the payment service directly" >&2
  exit 1
fi
"${compose[@]}" exec -T effect-proxy wget -qO- http://control:8787/healthz >/dev/null
payment_stats="$("${compose[@]}" exec -T control wget -qO- http://payment:8081/v1/stats)"
jq -e '.deliveries == 3 and .commits == 2 and .paths["/v1/charge"] == 2 and .paths["/v2/charge"] == 1' \
  <<<"$payment_stats" >/dev/null

safe_change state > "$DEMO_STATE_DIR/results/final-state.json"
jq -e --arg v1 "$payment_v1" --arg v2 "$payment_v2" '
  .requirement.id == "orders-v2" and
  ([.operations[] | select(.kind == "charge-v1" and .target == $v1 and .phase == "succeeded")] | length == 1) and
  ([.operations[] | select(.kind == "charge-v2" and .target == $v2 and .phase == "succeeded")] | length == 1)
' "$DEMO_STATE_DIR/results/final-state.json" >/dev/null

order_networks="$(docker inspect "$new_order_container" | jq -c '.[0].NetworkSettings.Networks | keys')"
control_networks="$(docker inspect "$control_container" | jq -c '.[0].NetworkSettings.Networks | keys')"
payment_container="$("${compose[@]}" ps -q payment)"
payment_networks="$(docker inspect "$payment_container" | jq -c '.[0].NetworkSettings.Networks | keys')"
proxy_networks="$(docker inspect "$new_proxy_container" | jq -c '.[0].NetworkSettings.Networks | keys')"
jq -en \
  --argjson order "$order_networks" \
  --argjson proxy "$proxy_networks" \
  --argjson control "$control_networks" \
  --argjson payment "$payment_networks" '
  ($order | length) == 1 and ($proxy | length) == 2 and
  ($control | length) == 2 and ($payment | length) == 1 and
  ([$order[] as $name | $payment[] | select(. == $name)] | length) == 0 and
  ([$order[] as $name | $control[] | select(. == $name)] | length) == 0 and
  ([$order[] as $name | $proxy[] | select(. == $name)] | length) == 1 and
  ([$proxy[] as $name | $payment[] | select(. == $name)] | length) == 0 and
  ([$proxy[] as $name | $control[] | select(. == $name)] | length) == 1 and
  ([$payment[] as $name | $control[] | select(. == $name)] | length) == 1
' >/dev/null

order_mounts="$(docker inspect "$new_order_container" | jq -c '.[0].Mounts | map(.Destination) | sort')"
jq -en --argjson mounts "$order_mounts" '$mounts == ["/config"]' >/dev/null
if docker inspect "$new_order_container" | jq -er '
  (.[0].Config.Cmd | join("\u0000")) as $command |
  ($command | contains("operation-token")) or
  ($command | contains("payment:8081")) or
  ($command | contains("control:8787"))
' >/dev/null; then
  echo "order command contains protected authority" >&2
  exit 1
fi
jq -e 'keys == ["effect_proxy_url","effect_route","version"] and
  .effect_proxy_url == "http://effect-proxy:8788" and .effect_route == "payment"' \
  "$DEMO_STATE_DIR/order-config/order.json" >/dev/null

jq -n \
  --argjson order "$order_networks" \
  --argjson proxy "$proxy_networks" \
  --argjson control "$control_networks" \
  --argjson payment "$payment_networks" \
  --argjson mounts "$order_mounts" '
  def shared($left; $right):
    [$left[] as $name | $right[] | select(. == $name)] | length;
  {
    schema:1,
    protected_role_network_counts:{
      order:($order | length),
      effect_proxy:($proxy | length),
      control:($control | length),
      payment:($payment | length)
    },
    network_intersections:{
      order_payment:{count:shared($order; $payment),passes:(shared($order; $payment) == 0)},
      order_control:{count:shared($order; $control),passes:(shared($order; $control) == 0)},
      order_effect_proxy:{count:shared($order; $proxy),passes:(shared($order; $proxy) == 1)},
      effect_proxy_payment:{count:shared($proxy; $payment),passes:(shared($proxy; $payment) == 0)},
      effect_proxy_control:{count:shared($proxy; $control),passes:(shared($proxy; $control) == 1)},
      payment_control:{count:shared($payment; $control),passes:(shared($payment; $control) == 1)}
    },
    probes:{
      order_to_payment_blocked:true,
      order_to_control_blocked:true,
      order_to_effect_proxy_reachable:true,
      effect_proxy_to_payment_blocked:true,
      effect_proxy_to_control_reachable:true
    },
    order_authority:{
      mounts:$mounts,
      adapter_token_present:false,
      physical_effect_target_present:false
    }
  }' > "$DEMO_STATE_DIR/results/isolation.json.next"
mv "$DEMO_STATE_DIR/results/isolation.json.next" "$DEMO_STATE_DIR/results/isolation.json"

history_sequence="$(jq -r '.history.sequence' "$DEMO_STATE_DIR/results/final-state.json")"
old_runtime_kind="$(jq -r '[.operations[] | select(.target == "http://payment:8081/v1/charge")][0].kind' \
  "$DEMO_STATE_DIR/results/final-state.json")"
jq -n \
  --arg first_network_result unknown \
  --arg changed_release v2 \
  --arg old_runtime_kind "$old_runtime_kind" \
  --arg direct_payment_from_order blocked \
  --arg direct_control_from_order blocked \
  --argjson payment "$payment_stats" \
  --argjson history_sequence "$history_sequence" \
  '{
    first_network_result:$first_network_result,
    order_process_replaced:true,
    changed_release:$changed_release,
    control_process_restarted:true,
    effect_proxy_replaced:true,
    safe_change_cli_used:true,
    old_order_completed_under_frozen_operation:($old_runtime_kind == "charge-v1"),
    new_order_used_v2:true,
    direct_payment_from_order:$direct_payment_from_order,
    direct_control_from_order:$direct_control_from_order,
    workload_has_adapter_token:false,
    workload_has_physical_effect_target:false,
    remote_deliveries:$payment.deliveries,
    remote_commits:$payment.commits,
    delivery_paths:$payment.paths,
    history_sequence:$history_sequence
  }' | tee "$DEMO_STATE_DIR/results/summary.json"

manifest_tmp="$DEMO_STATE_DIR/.SHA256SUMS.$$"
(
  cd "$DEMO_STATE_DIR/results"
  while IFS= read -r -d '' evidence_file; do
    sha256sum -- "$evidence_file"
  done < <(find . -maxdepth 1 -type f ! -name SHA256SUMS -printf '%P\0' | LC_ALL=C sort -z)
) > "$manifest_tmp"
mv "$manifest_tmp" "$DEMO_STATE_DIR/results/SHA256SUMS"

if [[ "${KEEP_DEMO:-0}" == "1" || "${KEEP_STATE:-0}" == "1" ]]; then
  echo "evidence directory: $DEMO_STATE_DIR" >&2
fi
