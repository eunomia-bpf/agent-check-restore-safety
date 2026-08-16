#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
case_name="${NATIVE_CASE:-}"
if [[ "$case_name" != h0 && "$case_name" != h1 ]]; then
  echo "NATIVE_CASE must be h0 or h1" >&2
  exit 2
fi
if [[ -z "${NATIVE_STATE_DIR:-}" ]]; then
  NATIVE_STATE_DIR="$(mktemp -d "/tmp/safe-change-native-$case_name.XXXXXX")"
fi
NATIVE_STATE_DIR="$(realpath "$NATIVE_STATE_DIR")"
results_dir="$NATIVE_STATE_DIR/results"
mkdir -p "$results_dir"
chmod 700 "$NATIVE_STATE_DIR" "$results_dir"

for command in curl date docker jq python3 realpath sed seq sha256sum sort tr wc; do
  command -v "$command" >/dev/null || {
    echo "required command not found: $command" >&2
    exit 1
  }
done

build_env="${HARNESS_BUILD_ENV:-$NATIVE_STATE_DIR/build.env}"
if [[ "${SKIP_BUILD:-0}" != "1" ]]; then
  "$script_dir/build.sh" "$build_env" >"$results_dir/build.log"
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
for required in NATIVE_ORDER_V1_IMAGE NATIVE_ORDER_V2_IMAGE NATIVE_V1_CONTEXT_SHA256 \
  NATIVE_V2_CONTEXT_SHA256 NATIVE_V1_COMPILED_SHA256 NATIVE_V2_COMPILED_SHA256 \
  PROVIDER_DIRECT_PATCH_SHA256; do
  [[ -n "${!required:-}" ]] || {
    echo "build metadata omitted $required" >&2
    exit 1
  }
done
cp "$build_env" "$results_dir/build.env"
chmod 600 "$results_dir/build.env"

read -r default_ingress_port default_admin_port default_jaeger_port default_webui_port \
  < <(python3 - <<'PY'
import socket

sockets = []
try:
    for _ in range(4):
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
JAEGER_PORT="${JAEGER_PORT:-$default_jaeger_port}"
WEBUI_PORT="${WEBUI_PORT:-$default_webui_port}"
CONTROL_PORT="${CONTROL_PORT:-1}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-safe-change-native-$case_name-$$}"
if [[ "$case_name" == h0 ]]; then
  PAYMENT_HOLD_BEFORE_COMMIT=true
  PAYMENT_HOLD_AFTER_COMMIT=false
else
  PAYMENT_HOLD_BEFORE_COMMIT=false
  PAYMENT_HOLD_AFTER_COMMIT=true
fi
export RESTATE_INGRESS_PORT RESTATE_ADMIN_PORT JAEGER_PORT WEBUI_PORT CONTROL_PORT
export COMPOSE_PROJECT_NAME PAYMENT_HOLD_BEFORE_COMMIT PAYMENT_HOLD_AFTER_COMMIT

compose_files=(--file "$script_dir/compose.yaml" --file "$script_dir/compose-native.yaml")
compose=(docker compose --project-name "$COMPOSE_PROJECT_NAME" "${compose_files[@]}")
compose_all=(docker compose --project-name "$COMPOSE_PROJECT_NAME" "${compose_files[@]}" --profile target)
cleanup() {
  local status=$?
  printf '%s\n' "$status" >"$results_dir/exit-status.txt"
  "${compose_all[@]}" ps --all >"$results_dir/compose-ps.txt" 2>&1 || true
  "${compose_all[@]}" logs --no-color >"$results_dir/compose.log" 2>&1 || true
  if [[ "${KEEP_HARNESS:-0}" != "1" ]]; then
    "${compose_all[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
  fi
  echo "native Restate $case_name evidence: $NATIVE_STATE_DIR" >&2
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
      if [[ "$health" == healthy ]]; then
        return 0
      fi
    fi
    sleep 1
  done
  echo "timed out waiting for service $service" >&2
  return 1
}

restate_admin_url="http://127.0.0.1:$RESTATE_ADMIN_PORT"
restate_ingress_url="http://127.0.0.1:$RESTATE_INGRESS_PORT"
webui_url="http://127.0.0.1:$WEBUI_PORT"
application_network="${COMPOSE_PROJECT_NAME}_application"

raw_query() {
  local query=$1 output=$2
  jq -n --arg query "$query" '{query:$query}' |
    curl -fsS --header 'Accept: application/json' \
      --header 'Content-Type: application/json' --data-binary @- \
      "$restate_admin_url/query" >"$output"
  jq -e 'keys == ["rows"] and (.rows | type == "array")' "$output" >/dev/null
}

restate_cli() {
  docker run --rm --network "$application_network" \
    --env RESTATE_HOST=restate "$RESTATE_CLI_IMAGE" "$@"
}

register_deployment() {
  local variant=$1 uri=$2 output=$3
  jq -n --arg uri "$uri" --arg variant "$variant" --arg commit "$RESTATE_EXAMPLES_COMMIT" \
    '{uri:$uri,force:false,breaking:false,metadata:{variant:$variant,upstream_commit:$commit,method:"native-restate"}}' |
    curl -fsS --request POST --header 'Content-Type: application/json' \
      --data-binary @- "$restate_admin_url/deployments" >"$output"
  jq -e '(.services | length) == 6 and .id != null' "$output" >/dev/null
}

provider_stats() {
  local service=$1 output=$2
  "${compose_all[@]}" exec -T "$service" wget -qO- http://127.0.0.1:8081/v1/stats >"$output"
}

post_cut_action() {
  printf '%s\n' "$1" >>"$results_dir/post-cut-command.log"
}

: >"$results_dir/post-cut-command.log"
"${compose[@]}" config --quiet
"${compose_all[@]}" config >"$results_dir/compose-config.yaml"
"${compose[@]}" up --detach
wait_url "$restate_admin_url/health"
wait_url "$webui_url" 240
if [[ -n "$("${compose_all[@]}" ps --quiet control)" ]]; then
  echo "native baseline unexpectedly started the proposed control" >&2
  exit 1
fi

register_deployment native-v1 http://order-v1:9080 "$results_dir/deployment-v1.json"
v1_deployment_id="$(jq -r '.id' "$results_dir/deployment-v1.json")"
curl -fsS "$restate_admin_url/services" >"$results_dir/services-v1.json"
expected_services='["delivery-manager","driver-delivery-matcher","driver-digital-twin","driver-mobile-app","order-status","order-workflow"]'
jq -e --argjson expected "$expected_services" '([.services[].name] | sort) == $expected' \
  "$results_dir/services-v1.json" >/dev/null

jq -n '{source:"kafka://my-cluster/driver-updates",sink:"service://driver-digital-twin/handleDriverLocationUpdateEvent"}' \
  >"$results_dir/subscription-request.json"
curl -fsS --request POST --header 'Content-Type: application/json' \
  --data-binary "@$results_dir/subscription-request.json" \
  "$restate_admin_url/subscriptions" >"$results_dir/subscription.json"

order_id="${ORDER_ID:-native-order-$(date +%s)-$$}"
if [[ ! "$order_id" =~ ^[A-Za-z0-9._-]{1,128}$ ]]; then
  echo "ORDER_ID must contain only letters, digits, dot, underscore, or hyphen" >&2
  exit 1
fi
jq -n --arg id "$order_id" '{
  id:$id,restaurantId:"restaurant-01",
  products:[{productId:"pizza-01",description:"Pizza",quantity:1}],
  totalCost:42,deliveryDelay:0
}' >"$results_dir/order.json"
sha256sum "$results_dir/order.json" >"$results_dir/order.sha256"
curl -fsS --request POST --header 'Content-Type: application/json' \
  --data-binary "@$results_dir/order.json" \
  "$restate_ingress_url/order-workflow/$order_id/run/send" >"$results_dir/source-submit.json"

fault_reached=0
for _ in $(seq 1 180); do
  provider_stats payment "$results_dir/payment-at-cut.json"
  if [[ "$case_name" == h0 ]]; then
    if jq -e '.deliveries == 1 and .commits == 0 and .paths["/v1/charge"] == 1' \
      "$results_dir/payment-at-cut.json" >/dev/null; then
      fault_reached=1
      break
    fi
  elif jq -e '.deliveries == 1 and .commits == 1 and .paths["/v1/charge"] == 1' \
    "$results_dir/payment-at-cut.json" >/dev/null; then
    fault_reached=1
    break
  fi
  sleep 1
done
if [[ $fault_reached -ne 1 ]]; then
  echo "native payment did not reach the injected $case_name hold" >&2
  exit 1
fi

source_lookup_sql="SELECT id,target,status,pinned_deployment_id,pinned_service_protocol_version,last_attempt_deployment_id,retry_count,next_retry_at,journal_size,created_at,modified_at FROM sys_invocation WHERE target_service_name = 'order-workflow' AND target_service_key = '$order_id' AND target_handler_name = 'run' ORDER BY id"
for _ in $(seq 1 120); do
  raw_query "$source_lookup_sql" "$results_dir/source-running.json"
  if jq -e --arg deployment "$v1_deployment_id" '
    (.rows | length) == 1 and .rows[0].status == "running" and
    .rows[0].pinned_deployment_id == $deployment
  ' "$results_dir/source-running.json" >/dev/null; then
    break
  fi
  sleep 1
done
jq -e '(.rows | length) == 1 and .rows[0].status == "running"' "$results_dir/source-running.json" >/dev/null
source_invocation_id="$(jq -r '.rows[0].id' "$results_dir/source-running.json")"
source_created_at="$(jq -r '.rows[0].created_at' "$results_dir/source-running.json")"

restate_cli --yes invocations pause "$source_invocation_id" \
  >"$results_dir/source-pause.stdout" 2>"$results_dir/source-pause.stderr"

# Native user code is blocked in a direct Axios request and does not observe
# Restate's pause until that attempt ends.  Hard-stopping only the worker
# process is the response-loss fault: it severs the provider connection but
# does not kill, purge, resubmit, or replace the Restate invocation.
source_container_before_crash="$("${compose[@]}" ps --quiet order-v1)"
docker inspect "$source_container_before_crash" >"$results_dir/source-container-before-crash.json"
docker logs "$source_container_before_crash" >"$results_dir/source-v1-before-crash.log" 2>&1
payment_token="$(
  sed -nE "s/.*\\[$order_id\\] Executing payment with token ([^ ]+) for.*/\\1/p" \
    "$results_dir/source-v1-before-crash.log" | tail -n 1
)"
if [[ ! "$payment_token" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]]; then
  echo "native worker log did not retain the stable payment token" >&2
  exit 1
fi
payment_operation_id="op-$(
  printf 'operation-id-v1\0restate-order-workflow\0%s' "$payment_token" | sha256sum | awk '{print $1}'
)"
docker kill "$source_container_before_crash" >"$results_dir/source-worker-crash.txt"

paused=0
for _ in $(seq 1 180); do
  raw_query "$source_lookup_sql" "$results_dir/source-paused-poll.json"
  if jq -e --arg invocation "$source_invocation_id" --arg deployment "$v1_deployment_id" '
    (.rows | length) == 1 and .rows[0].id == $invocation and
    .rows[0].status == "paused" and .rows[0].pinned_deployment_id == $deployment
  ' "$results_dir/source-paused-poll.json" >/dev/null; then
    paused=1
    break
  fi
  sleep 1
done
if [[ $paused -ne 1 ]]; then
  echo "native source invocation did not pause" >&2
  exit 1
fi

# Keep the immutable v1 deployment available after the crash.  The invocation
# is paused, so restarting the worker cannot redispatch payment.
"${compose[@]}" up --detach --no-deps order-v1
wait_service_healthy order-v1
source_container="$("${compose[@]}" ps --quiet order-v1)"
docker inspect "$source_container" >"$results_dir/source-container-retained.json"

source_status_sql="SELECT id,target,status,pinned_deployment_id,pinned_service_protocol_version,last_attempt_deployment_id,retry_count,next_retry_at,journal_size,created_at,modified_at FROM sys_invocation WHERE id = '$source_invocation_id'"
source_journal_sql="SELECT index,version,entry_type,name,COALESCE(completed,false) AS completed,raw,raw_length,entry_lite_json FROM sys_journal WHERE id = '$source_invocation_id' ORDER BY index"
source_workflow_state_sql="SELECT service_name,service_key,key,value,value_utf8,value_length FROM state WHERE service_name = 'order-workflow' AND service_key = '$order_id' ORDER BY key"
raw_query "$source_status_sql" "$results_dir/cut-status.json"
raw_query "$source_journal_sql" "$results_dir/cut-journal.json"
raw_query "$source_workflow_state_sql" "$results_dir/cut-workflow-state.json"
jq -e --arg invocation "$source_invocation_id" --arg deployment "$v1_deployment_id" '
  (.rows | length) == 1 and .rows[0].id == $invocation and .rows[0].status == "paused" and
  .rows[0].pinned_deployment_id == $deployment and .rows[0].journal_size == 3
' "$results_dir/cut-status.json" >/dev/null
jq -e '
  [.rows[] | {index,entry_type,name,completed}] == [
    {index:0,entry_type:"Command: Input",name:"",completed:false},
    {index:1,entry_type:"Command: SetState",name:"",completed:false},
    {index:2,entry_type:"Command: Run",name:"payment",completed:false}
  ]
' "$results_dir/cut-journal.json" >/dev/null
jq -e --arg order "$order_id" '
  .rows == [{service_name:"order-workflow",service_key:$order,key:"status",value:"224352454154454422",value_utf8:"\"CREATED\"",value_length:9}]
' "$results_dir/cut-workflow-state.json" >/dev/null

sleep 5
raw_query "$source_status_sql" "$results_dir/cut-status-after-window.json"
raw_query "$source_journal_sql" "$results_dir/cut-journal-after-window.json"
raw_query "$source_workflow_state_sql" "$results_dir/cut-workflow-state-after-window.json"
jq -e -s '.[0] == .[1]' "$results_dir/cut-status.json" "$results_dir/cut-status-after-window.json" >/dev/null
jq -e -s '.[0] == .[1]' "$results_dir/cut-journal.json" "$results_dir/cut-journal-after-window.json" >/dev/null
jq -e -s '.[0] == .[1]' "$results_dir/cut-workflow-state.json" "$results_dir/cut-workflow-state-after-window.json" >/dev/null
provider_stats payment "$results_dir/payment-after-cut-window.json"
jq -e -s '.[0] == .[1]' "$results_dir/payment-at-cut.json" "$results_dir/payment-after-cut-window.json" >/dev/null
provider_stats completion "$results_dir/completion-at-cut.json"
jq -e '.deliveries == 0 and .commits == 0 and .paths == {}' "$results_dir/completion-at-cut.json" >/dev/null
payment_container_at_cut="$("${compose_all[@]}" ps --quiet payment)"
completion_container_at_cut="$("${compose_all[@]}" ps --quiet completion)"
docker cp "$payment_container_at_cut:/state/payment.history" "$results_dir/payment-at-cut.history"
docker cp "$completion_container_at_cut:/state/completion.history" "$results_dir/completion-at-cut.history"
if [[ "$case_name" == h0 ]]; then
  [[ "$(wc -c <"$results_dir/payment-at-cut.history")" -eq 0 ]]
else
  [[ "$(wc -l <"$results_dir/payment-at-cut.history")" -eq 1 ]]
fi
[[ "$(wc -c <"$results_dir/completion-at-cut.history")" -eq 0 ]]

post_cut_action start-target-v2
"${compose_all[@]}" up --detach --no-deps order-v2
wait_service_healthy order-v2
target_container="$("${compose_all[@]}" ps --quiet order-v2)"
docker inspect "$target_container" >"$results_dir/target-container.json"

post_cut_action register-target-v2
register_deployment native-v2 http://order-v2:9080 "$results_dir/deployment-v2.json"
v2_deployment_id="$(jq -r '.id' "$results_dir/deployment-v2.json")"
curl -fsS "$restate_admin_url/deployments" >"$results_dir/deployments.json"

post_cut_action start-driver-01
curl -fsS --request POST --header 'Content-Type: application/json' --data '{}' \
  "$restate_ingress_url/driver-mobile-app/driver-01/startDriver/send" >"$results_dir/driver-01.json"
post_cut_action start-driver-02
curl -fsS --request POST --header 'Content-Type: application/json' --data '{}' \
  "$restate_ingress_url/driver-mobile-app/driver-02/startDriver/send" >"$results_dir/driver-02.json"

post_cut_action resume-source-on-target
set +e
restate_cli --yes invocations resume "$source_invocation_id" --deployment "$v2_deployment_id" \
  >"$results_dir/resume.stdout" 2>"$results_dir/resume.stderr"
resume_exit=$?
set -e
printf '%s\n' "$resume_exit" >"$results_dir/resume-exit-status.txt"

post_cut_action fixed-observation-window
observation_seconds="${NATIVE_OBSERVATION_SECONDS:-30}"
if [[ ! "$observation_seconds" =~ ^[0-9]+$ || "$observation_seconds" -lt 1 || "$observation_seconds" -gt 120 ]]; then
  echo "NATIVE_OBSERVATION_SECONDS must be an integer in [1,120]" >&2
  exit 1
fi
for second in $(seq 0 "$observation_seconds"); do
  raw_query "$source_status_sql" "$results_dir/observation-$second.json"
  if [[ $second -lt $observation_seconds ]]; then
    sleep 1
  fi
done

post_cut_action capture-final-evidence
raw_query "$source_lookup_sql" "$results_dir/final-invocations.json"
raw_query "$source_status_sql" "$results_dir/final-status.json"
raw_query "$source_journal_sql" "$results_dir/final-journal.json"
raw_query "$source_workflow_state_sql" "$results_dir/final-workflow-state.json"
provider_stats payment "$results_dir/final-payment-stats.json"
provider_stats completion "$results_dir/final-completion-stats.json"
docker logs "$source_container" >"$results_dir/final-v1.log" 2>&1
docker logs "$target_container" >"$results_dir/final-v2.log" 2>&1
docker inspect "$source_container" >"$results_dir/final-source-container.json"
docker inspect "$target_container" >"$results_dir/final-target-container.json"

payment_container="$("${compose_all[@]}" ps --quiet payment)"
completion_container="$("${compose_all[@]}" ps --quiet completion)"
docker cp "$payment_container:/state/payment.history" "$results_dir/payment.history"
docker cp "$completion_container:/state/completion.history" "$results_dir/completion.history"
mapfile -t container_ids < <(
  docker ps --all --quiet --filter "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME" | sort
)
docker inspect "${container_ids[@]}" >"$results_dir/containers.raw.json"

final_status="$(jq -r '.rows[0].status // "absent"' "$results_dir/final-status.json")"
final_pinned="$(jq -r '.rows[0].pinned_deployment_id // ""' "$results_dir/final-status.json")"
final_last_attempt="$(jq -r '.rows[0].last_attempt_deployment_id // ""' "$results_dir/final-status.json")"
final_order_status="$(jq -r '[.rows[] | select(.key == "status") | .value_utf8][0] // "null"' "$results_dir/final-workflow-state.json")"
jq -n \
  --arg case "$case_name" --arg order_id "$order_id" \
  --arg source_invocation_id "$source_invocation_id" --arg source_created_at "$source_created_at" \
  --arg v1_deployment_id "$v1_deployment_id" --arg v2_deployment_id "$v2_deployment_id" \
  --arg payment_token "$payment_token" --arg payment_operation_id "$payment_operation_id" \
  --arg final_status "$final_status" --arg final_pinned "$final_pinned" \
  --arg final_last_attempt "$final_last_attempt" --arg final_order_status "$final_order_status" \
  --argjson resume_exit "$resume_exit" --argjson observation_seconds "$observation_seconds" \
  --argjson payment_at_cut "$(cat "$results_dir/payment-at-cut.json")" \
  --argjson final_payment "$(cat "$results_dir/final-payment-stats.json")" \
  --argjson final_completion "$(cat "$results_dir/final-completion-stats.json")" '{
    schema:1,method:"native-restate",case:$case,order_id:$order_id,
    source:{invocation_id:$source_invocation_id,created_at:$source_created_at,deployment_id:$v1_deployment_id},
    target:{deployment_id:$v2_deployment_id},
    payment:{token:$payment_token,operation_id:$payment_operation_id,at_cut:$payment_at_cut,final:$final_payment},
    completion:$final_completion,
    repin:{cli_exit:$resume_exit,final_pinned_deployment_id:$final_pinned,last_attempt_deployment_id:$final_last_attempt},
    execution:{status:$final_status,order_status:$final_order_status,observation_seconds:$observation_seconds},
    invariants:{single_submit:true,same_invocation_observed:true,proposed_control_absent:true,source_retained:true}
  }' >"$results_dir/observed.json"

cat "$results_dir/observed.json"
