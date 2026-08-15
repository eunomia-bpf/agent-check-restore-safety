#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
compose_file="$script_dir/compose.yaml"
if [[ -z "${HARNESS_STATE_DIR:-}" ]]; then
  HARNESS_STATE_DIR="$(mktemp -d /tmp/safe-change-restate-run.XXXXXX)"
fi
HARNESS_STATE_DIR="$(realpath "$HARNESS_STATE_DIR")"
results_dir="$HARNESS_STATE_DIR/results"
mkdir -p "$results_dir"
chmod 700 "$HARNESS_STATE_DIR" "$results_dir"

for command in curl docker jq python3; do
  command -v "$command" >/dev/null || {
    echo "required command not found: $command" >&2
    exit 1
  }
done

build_env="${HARNESS_BUILD_ENV:-$HARNESS_STATE_DIR/build.env}"
if [[ "${SKIP_BUILD:-0}" != "1" ]]; then
  "$script_dir/build.sh" "$build_env" | tee "$results_dir/build.log"
elif [[ ! -f "$build_env" ]]; then
  echo "SKIP_BUILD=1 requires HARNESS_BUILD_ENV to name an existing file" >&2
  exit 1
fi

set -a
# shellcheck source=/dev/null
source "$script_dir/versions.env"
# shellcheck source=/dev/null
source "$script_dir/images.env"
# shellcheck source=/dev/null
source "$build_env"
set +a

read -r default_ingress_port default_admin_port default_control_port default_jaeger_port default_webui_port \
  < <(python3 - <<'PY'
import socket

sockets = []
try:
    for _ in range(5):
        item = socket.socket()
        item.bind(("127.0.0.1", 0))
        sockets.append(item)
    print(*(item.getsockname()[1] for item in sockets))
finally:
    for item in sockets:
        item.close()
PY
)
RESTATE_INGRESS_PORT="${RESTATE_INGRESS_PORT:-$default_ingress_port}"
RESTATE_ADMIN_PORT="${RESTATE_ADMIN_PORT:-$default_admin_port}"
CONTROL_PORT="${CONTROL_PORT:-$default_control_port}"
JAEGER_PORT="${JAEGER_PORT:-$default_jaeger_port}"
WEBUI_PORT="${WEBUI_PORT:-$default_webui_port}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-safe-change-restate-$$}"
export RESTATE_INGRESS_PORT RESTATE_ADMIN_PORT CONTROL_PORT JAEGER_PORT WEBUI_PORT COMPOSE_PROJECT_NAME

compose=(docker compose --project-name "$COMPOSE_PROJECT_NAME" --file "$compose_file")
compose_all=(docker compose --project-name "$COMPOSE_PROJECT_NAME" --file "$compose_file" --profile target)
cleanup() {
  local status=$?
  printf '%s\n' "$status" >"$results_dir/exit-status.txt"
  "${compose_all[@]}" ps --all >"$results_dir/compose-ps.txt" 2>&1 || true
  "${compose_all[@]}" logs --no-color >"$results_dir/compose.log" 2>&1 || true
  if [[ "${KEEP_HARNESS:-0}" != "1" ]]; then
    "${compose_all[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
  fi
  echo "Restate harness evidence: $HARNESS_STATE_DIR" >&2
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

wait_url() {
  local url=$1 attempts=${2:-180}
  for _ in $(seq 1 "$attempts"); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  echo "timed out waiting for $url" >&2
  return 1
}

wait_service_healthy() {
  local service=$1 attempts=${2:-120} container health
  for _ in $(seq 1 "$attempts"); do
    container="$("${compose_all[@]}" ps --quiet "$service")"
    if [[ -n "$container" ]]; then
      health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$container")"
      if [[ "$health" == "healthy" ]]; then
        return 0
      fi
    fi
    sleep 1
  done
  echo "timed out waiting for service $service to become healthy" >&2
  return 1
}

control_url="http://127.0.0.1:$CONTROL_PORT"
restate_admin_url="http://127.0.0.1:$RESTATE_ADMIN_PORT"
restate_ingress_url="http://127.0.0.1:$RESTATE_INGRESS_PORT"
webui_url="http://127.0.0.1:$WEBUI_PORT"

"${compose[@]}" config --quiet
"${compose[@]}" up --detach
wait_url "$control_url/healthz"
wait_url "$restate_admin_url/health"
wait_url "$webui_url" 240

admin_token="$("${compose[@]}" exec -T control cat /state/admin-token | tr -d '\r\n')"
if [[ ${#admin_token} -lt 32 ]]; then
  echo "control did not create a valid admin token" >&2
  exit 1
fi

control_post() {
  local path=$1 input=$2 output=$3
  curl -fsS --header "Authorization: Bearer $admin_token" \
    --header 'Content-Type: application/json' --data-binary "@$input" \
    "$control_url$path" >"$output"
}

register_deployment() {
  local variant=$1 uri=$2 output=$3
  jq -n --arg uri "$uri" --arg variant "$variant" --arg commit "$RESTATE_EXAMPLES_COMMIT" \
    '{uri:$uri,force:false,breaking:false,metadata:{variant:$variant,upstream_commit:$commit}}' |
    curl -fsS --request POST --header 'Content-Type: application/json' \
      --data-binary @- "$restate_admin_url/deployments" >"$output"
  jq -e --arg variant "$variant" '
    (.services | length) == 6 and .services != null and .id != null
  ' "$output" >/dev/null
}

register_deployment v1 http://order-v1:9080 "$results_dir/deployment-v1.json"
curl -fsS "$restate_admin_url/services" >"$results_dir/services-v1.json"
expected_services='["delivery-manager","driver-delivery-matcher","driver-digital-twin","driver-mobile-app","order-status","order-workflow"]'
jq -e --argjson expected "$expected_services" \
  '([.services[].name] | sort) == $expected' "$results_dir/services-v1.json" >/dev/null

jq -n '{
  source:"kafka://my-cluster/driver-updates",
  sink:"service://driver-digital-twin/handleDriverLocationUpdateEvent"
}' >"$results_dir/subscription-request.json"
curl -fsS --request POST --header 'Content-Type: application/json' \
  --data-binary "@$results_dir/subscription-request.json" \
  "$restate_admin_url/subscriptions" >"$results_dir/subscription.json"

payment_target='http://payment:8081/v1/charge'
payment_query='http://payment:8081/v1/query'
finish_target='http://completion:8081/v1/complete'
jq -n --arg payment "$payment_target" --arg query "$payment_query" --arg finish "$finish_target" '{
  id:"food-ordering-v1",
  results:{paid:1,delivered:1},
  capacities:{charge:1},
  kinds:{
    "charge-v1":{
      costs:{charge:1},produces:{paid:1},retry_safe:false,queryable:true,
      target:$payment,method:"POST",response_classifier:"operation-receipt-v1",
      query_target:$query,query_method:"POST",query_classifier:"operation-observation-v1"
    },
    finish:{
      costs:{},produces:{delivered:1},retry_safe:true,queryable:false,
      target:$finish,method:"POST",response_classifier:"operation-receipt-v1"
    }
  }
}' >"$results_dir/requirement-v1.json"
jq -n --arg finish "$finish_target" '{
  id:"food-ordering-v2",
  results:{paid:1,delivered:1},
  capacities:{charge:1},
  kinds:{
    "charge-v1":{
      costs:{charge:1},produces:{paid:1},retry_safe:false,queryable:false
    },
    finish:{
      costs:{},produces:{delivered:1},retry_safe:true,queryable:false,
      target:$finish,method:"POST",response_classifier:"operation-receipt-v1"
    }
  }
}' >"$results_dir/requirement-v2.json"
jq -e -s '.[0].results == .[1].results and .[0].capacities == .[1].capacities' \
  "$results_dir/requirement-v1.json" "$results_dir/requirement-v2.json" >/dev/null

control_post /v1/compile "$results_dir/requirement-v1.json" "$results_dir/certificate-v1.json"
jq -e '
  .decision == "activate" and .rule != null and
  ((.rule.allow | sort) == ["charge-v1","finish"])
' "$results_dir/certificate-v1.json" >/dev/null
control_post /v1/activate "$results_dir/certificate-v1.json" "$results_dir/active-v1.json"

for driver in driver-01 driver-02; do
  curl -fsS --request POST --header 'Content-Type: application/json' --data '{}' \
    "$restate_ingress_url/driver-mobile-app/$driver/startDriver/send" \
    >"$results_dir/$driver.json"
done

order_id="smoke-order-$(date +%s)-$$"
jq -n --arg id "$order_id" '{
  id:$id,restaurantId:"restaurant-01",
  products:[{productId:"pizza-01",description:"Pizza",quantity:1}],
  totalCost:42,deliveryDelay:0
}' >"$results_dir/order.json"
curl -fsS --request POST --header 'Content-Type: application/json' \
  --data-binary "@$results_dir/order.json" \
  "$restate_ingress_url/order-workflow/$order_id/run/send" >"$results_dir/order-submit.json"

completed=0
for _ in $(seq 1 300); do
  curl -fsS --header "Authorization: Bearer $admin_token" "$control_url/v1/state" \
    >"$results_dir/control-state.json"
  if jq -e '
    ([.operations[] | select(.kind == "charge-v1" and .phase == "succeeded")] | length) == 1 and
    ([.operations[] | select(.kind == "finish" and .phase == "succeeded")] | length) == 1
  ' "$results_dir/control-state.json" >/dev/null; then
    status="$(curl -fsS --request POST --header 'Content-Type: application/json' --data '{}' \
      "$restate_ingress_url/order-workflow/$order_id/getStatus" 2>/dev/null || true)"
    if [[ "$status" == '"DELIVERED"' ]]; then
      printf '%s\n' "$status" >"$results_dir/order-status.json"
      completed=1
      break
    fi
  fi
  sleep 1
done
if [[ $completed -ne 1 ]]; then
  echo "official food-ordering workflow did not reach DELIVERED" >&2
  exit 1
fi

"${compose[@]}" exec -T control wget -qO- http://payment:8081/v1/stats \
  >"$results_dir/payment-stats.json"
"${compose[@]}" exec -T control wget -qO- http://completion:8081/v1/stats \
  >"$results_dir/completion-stats.json"
jq -e '.deliveries == 1 and .commits == 1 and .paths["/v1/charge"] == 1' \
  "$results_dir/payment-stats.json" >/dev/null
jq -e '.deliveries == 1 and .commits == 1 and .paths["/v1/complete"] == 1' \
  "$results_dir/completion-stats.json" >/dev/null

# Compile and activate the target edit before making v2 the latest Restate
# deployment. The business Results and Capacities remain byte-for-byte equal;
# only the target catalog disables future charge executions.
control_post /v1/compile "$results_dir/requirement-v2.json" "$results_dir/certificate-v2.json"
jq -e '.decision == "activate" and .rule != null' "$results_dir/certificate-v2.json" >/dev/null
if [[ -n "$("${compose_all[@]}" ps --quiet order-v2)" ]]; then
  echo "target worker was running before target Rule activation" >&2
  exit 1
fi
printf 'absent\n' >"$results_dir/target-before-activation.txt"
control_post /v1/activate "$results_dir/certificate-v2.json" "$results_dir/active-v2.json"
"${compose_all[@]}" up --detach order-v2
wait_service_healthy order-v2
target_container="$("${compose_all[@]}" ps --quiet order-v2)"
jq -n \
  --arg started_at "$(docker inspect --format '{{.State.StartedAt}}' "$target_container")" \
  --argjson activated "$(cat "$results_dir/active-v2.json")" \
  '{target_started_at:$started_at,activated_history:$activated.history}' \
  >"$results_dir/target-start-order.json"
register_deployment v2 http://order-v2:9080 "$results_dir/deployment-v2.json"
curl -fsS "$restate_admin_url/deployments" >"$results_dir/deployments.json"
curl -fsS "$restate_admin_url/services" >"$results_dir/services-v2.json"
curl -fsS --header "Authorization: Bearer $admin_token" "$control_url/v1/state" \
  >"$results_dir/control-state.json"
curl -fsS --header "Authorization: Bearer $admin_token" "$control_url/v1/history" \
  >"$results_dir/control-history.json"
jq -e '
  ([.deployments[].uri] | sort) == ["http://order-v1:9080/","http://order-v2:9080/"]
' "$results_dir/deployments.json" >/dev/null
jq -e --argjson expected "$expected_services" \
  '([.services[].name] | sort) == $expected' "$results_dir/services-v2.json" >/dev/null

order_v1_container="$("${compose[@]}" ps --quiet order-v1)"
order_v2_container="$("${compose_all[@]}" ps --quiet order-v2)"
payment_container="$("${compose[@]}" ps --quiet payment)"
completion_container="$("${compose[@]}" ps --quiet completion)"
for pair in \
  "$order_v1_container $ORDER_V1_IMAGE" \
  "$order_v2_container $ORDER_V2_IMAGE"; do
  read -r container expected_image <<<"$pair"
  actual_image="$(docker inspect --format '{{.Image}}' "$container")"
  [[ "$actual_image" == "$expected_image" ]]
done

mount_targets() {
  docker inspect "$1" | jq -c '.[0].Mounts | map(.Destination) | sort'
}
order_v1_mounts="$(mount_targets "$order_v1_container")"
order_v2_mounts="$(mount_targets "$order_v2_container")"
jq -en --argjson v1 "$order_v1_mounts" --argjson v2 "$order_v2_mounts" '
  $v1 == ["/operation-token"] and $v2 == ["/operation-token"]
' >/dev/null
jq -n --argjson v1 "$order_v1_mounts" --argjson v2 "$order_v2_mounts" \
  '{v1:$v1,v2:$v2}' >"$results_dir/worker-mounts.json"

networks_of() {
  docker inspect "$1" | jq -c '.[0].NetworkSettings.Networks | keys'
}
order_v1_networks="$(networks_of "$order_v1_container")"
order_v2_networks="$(networks_of "$order_v2_container")"
payment_networks="$(networks_of "$payment_container")"
completion_networks="$(networks_of "$completion_container")"
jq -en \
  --argjson v1 "$order_v1_networks" --argjson v2 "$order_v2_networks" \
  --argjson payment "$payment_networks" --argjson completion "$completion_networks" '
    ([$v1[] as $left | $payment[] | select(. == $left)] | length) == 0 and
    ([$v2[] as $left | $payment[] | select(. == $left)] | length) == 0 and
    ([$v1[] as $left | $completion[] | select(. == $left)] | length) == 0 and
    ([$v2[] as $left | $completion[] | select(. == $left)] | length) == 0
  ' >/dev/null

jq -n \
  --arg upstream_commit "$RESTATE_EXAMPLES_COMMIT" \
  --arg upstream_archive_sha256 "$UPSTREAM_ARCHIVE_SHA256" \
  --arg worker_v1_image "$ORDER_V1_IMAGE" --arg worker_v2_image "$ORDER_V2_IMAGE" \
  --arg worker_v1_context_sha256 "$V1_CONTEXT_SHA256" \
  --arg worker_v2_context_sha256 "$V2_CONTEXT_SHA256" \
  --arg order_id "$order_id" \
  --argjson services "$expected_services" \
  --argjson payment "$(cat "$results_dir/payment-stats.json")" \
  --argjson completion "$(cat "$results_dir/completion-stats.json")" \
  --argjson state "$(cat "$results_dir/control-state.json")" \
  --argjson history "$(cat "$results_dir/control-history.json")" '{
    upstream:{commit:$upstream_commit,archive_sha256:$upstream_archive_sha256},
    workers:{
      v1:{image:$worker_v1_image,context_sha256:$worker_v1_context_sha256},
      v2:{image:$worker_v2_image,context_sha256:$worker_v2_context_sha256},
      exact_delta_verified:true
    },
    official_services:$services,
    order:{id:$order_id,status:"DELIVERED"},
    providers:{payment:$payment,completion:$completion},
    control:{
      history:$state.history,
      history_event_count:($history | length),
      operation_kinds:([$state.operations[].kind] | sort),
      operation_phases:([$state.operations[].phase] | sort),
      target_requirement:$state.requirement.id
    },
    deployments:["http://order-v1:9080/","http://order-v2:9080/"],
    target_started_after_activation:true,
    restaurant_image_contains_order_worker:false,
    workers_mount_only_operation_token:true,
    direct_worker_effect_network:false
  }' >"$results_dir/summary.json"

cat "$results_dir/summary.json"
