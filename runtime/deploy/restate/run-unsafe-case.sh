#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
method="${UNSAFE_METHOD:-}"
if [[ "$method" != proposed && "$method" != native ]]; then
  echo "UNSAFE_METHOD must be proposed or native" >&2
  exit 64
fi
if [[ -z "${UNSAFE_STATE_DIR:-}" ]]; then
  UNSAFE_STATE_DIR="$(mktemp -d "/tmp/safe-change-unsafe-$method.XXXXXX")"
elif [[ -e "$UNSAFE_STATE_DIR" ]]; then
  if [[ ! -d "$UNSAFE_STATE_DIR" || -n "$(find "$UNSAFE_STATE_DIR" -mindepth 1 -print -quit)" ]]; then
    echo "UNSAFE_STATE_DIR must be absent or empty" >&2
    exit 64
  fi
else
  mkdir -p "$UNSAFE_STATE_DIR"
fi
UNSAFE_STATE_DIR="$(realpath "$UNSAFE_STATE_DIR")"
results_dir="$UNSAFE_STATE_DIR/results"
mkdir -p "$results_dir"
chmod 700 "$UNSAFE_STATE_DIR" "$results_dir"

for command in cmp curl date docker find go jq python3 realpath sed seq sha256sum sort tr wc; do
  command -v "$command" >/dev/null || { echo "required command not found: $command" >&2; exit 1; }
done

build_env="${HARNESS_BUILD_ENV:-$UNSAFE_STATE_DIR/build.env}"
if [[ "${SKIP_BUILD:-0}" != 1 ]]; then
  "$script_dir/build.sh" "$build_env" >"$results_dir/build.stdout" 2>"$results_dir/build.stderr"
elif [[ ! -f "$build_env" ]]; then
  echo "SKIP_BUILD=1 requires HARNESS_BUILD_ENV" >&2
  exit 64
fi
set -a
# shellcheck source=/dev/null
source "$script_dir/versions.env"
# shellcheck source=/dev/null
source "$script_dir/images.env"
# shellcheck source=/dev/null
source "$build_env"
set +a
for required in ORDER_V1_IMAGE ORDER_UNSAFE_V2_IMAGE NATIVE_ORDER_V1_IMAGE \
  NATIVE_ORDER_UNSAFE_V2_IMAGE SAFE_CHANGE_RUNTIME_IMAGE \
  UNSAFE_V2_PATCH_SHA256 NATIVE_UNSAFE_V2_PATCH_SHA256 \
  UNSAFE_V2_CONTEXT_SHA256 NATIVE_UNSAFE_V2_CONTEXT_SHA256 \
  UNSAFE_V2_WORKFLOW_SHA256 UNSAFE_V2_COMPILED_SHA256 \
  NATIVE_UNSAFE_V2_COMPILED_SHA256; do
  [[ -n "${!required:-}" ]] || { echo "build metadata omitted $required" >&2; exit 1; }
done
if [[ "$UNSAFE_V2_COMPILED_SHA256" != "$NATIVE_UNSAFE_V2_COMPILED_SHA256" ]]; then
  echo "unsafe target workflow bytes differ between lanes" >&2
  exit 1
fi
if [[ "$method" == proposed ]]; then
  source_image="$ORDER_V1_IMAGE"
  target_image="$ORDER_UNSAFE_V2_IMAGE"
  overlay="$script_dir/compose-unsafe-proposed.yaml"
  patch_file="$script_dir/patches/unsafe-completion-v2.patch"
  compose_files=(--file "$script_dir/compose.yaml" --file "$overlay")
else
  source_image="$NATIVE_ORDER_V1_IMAGE"
  target_image="$NATIVE_ORDER_UNSAFE_V2_IMAGE"
  overlay="$script_dir/compose-unsafe-native.yaml"
  patch_file="$script_dir/patches/unsafe-completion-direct-v2.patch"
  compose_files=(--file "$script_dir/compose.yaml" --file "$script_dir/compose-native.yaml" --file "$overlay")
fi

cp "$build_env" "$results_dir/build.env"
cp "$script_dir/versions.env" "$results_dir/versions.env"
cp "$script_dir/images.env" "$results_dir/images.env"
cp "$script_dir/Dockerfile.worker" "$results_dir/Dockerfile.worker"
cp "$script_dir/compose.yaml" "$results_dir/compose.base.yaml"
cp "$overlay" "$results_dir/compose.unsafe.yaml"
cp "$patch_file" "$results_dir/unsafe-target.patch"
if [[ "$method" == native ]]; then cp "$script_dir/compose-native.yaml" "$results_dir/compose.native.yaml"; fi
sha256sum "$script_dir/run-unsafe-case.sh" >"$results_dir/runner.sha256"
chmod 600 "$results_dir/build.env"

read -r ingress_port admin_port control_port jaeger_port webui_port < <(python3 - <<'PY'
import socket
sockets=[]
try:
    for _ in range(5):
        item=socket.socket(); item.bind(("127.0.0.1",0)); sockets.append(item)
    print(*(item.getsockname()[1] for item in sockets))
finally:
    for item in sockets: item.close()
PY
)
RESTATE_INGRESS_PORT="${RESTATE_INGRESS_PORT:-$ingress_port}"
RESTATE_ADMIN_PORT="${RESTATE_ADMIN_PORT:-$admin_port}"
CONTROL_PORT="${CONTROL_PORT:-$control_port}"
JAEGER_PORT="${JAEGER_PORT:-$jaeger_port}"
WEBUI_PORT="${WEBUI_PORT:-$webui_port}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-safe-change-unsafe-$method-$$}"
PAYMENT_HOLD_BEFORE_COMMIT=false
PAYMENT_HOLD_AFTER_COMMIT=false
UNSAFE_TARGET_IMAGE="$target_image"
export RESTATE_INGRESS_PORT RESTATE_ADMIN_PORT CONTROL_PORT JAEGER_PORT WEBUI_PORT
export COMPOSE_PROJECT_NAME PAYMENT_HOLD_BEFORE_COMMIT PAYMENT_HOLD_AFTER_COMMIT
export UNSAFE_TARGET_IMAGE

compose=(docker compose --project-name "$COMPOSE_PROJECT_NAME" "${compose_files[@]}")
compose_all=(docker compose --project-name "$COMPOSE_PROJECT_NAME" "${compose_files[@]}" --profile target)
cleanup() {
  local status=$?
  printf '%s\n' "$status" >"$results_dir/exit-status.txt"
  "${compose_all[@]}" ps --all >"$results_dir/compose-ps.txt" 2>&1 || true
  "${compose_all[@]}" logs --no-color >"$results_dir/compose.log" 2>&1 || true
  if [[ "${KEEP_HARNESS:-0}" != 1 ]]; then
    "${compose_all[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
  fi
  echo "Restate unsafe $method evidence: $UNSAFE_STATE_DIR" >&2
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

admin_url="http://127.0.0.1:$RESTATE_ADMIN_PORT"
ingress_url="http://127.0.0.1:$RESTATE_INGRESS_PORT"
control_url="http://127.0.0.1:$CONTROL_PORT"
network="${COMPOSE_PROJECT_NAME}_application"
curl_args=(--fail --silent --show-error --connect-timeout 5 --max-time 120)
admin_token=""

set_source_inputs() {
  local image=$1 payment_kind=$2 payment_target=$3 finish_kind=$4 finish_target=$5
  UNSAFE_SOURCE_IMAGE="$image"
  UNSAFE_SOURCE_PAYMENT_KIND="$payment_kind"
  UNSAFE_SOURCE_PAYMENT_TARGET="$payment_target"
  UNSAFE_SOURCE_FINISH_KIND="$finish_kind"
  UNSAFE_SOURCE_FINISH_TARGET="$finish_target"
  export UNSAFE_SOURCE_IMAGE UNSAFE_SOURCE_PAYMENT_KIND UNSAFE_SOURCE_PAYMENT_TARGET
  export UNSAFE_SOURCE_FINISH_KIND UNSAFE_SOURCE_FINISH_TARGET
}

wait_url() {
  local url=$1 attempts=${2:-180}
  for _ in $(seq 1 "$attempts"); do
    if curl --fail --silent --connect-timeout 2 --max-time 3 "$url" >/dev/null 2>&1; then return 0; fi
    sleep 1
  done
  echo "timed out waiting for $url" >&2
  return 1
}

wait_service_healthy() {
  local service=$1 container health
  for _ in $(seq 1 180); do
    container="$("${compose_all[@]}" ps --quiet "$service")"
    if [[ -n "$container" ]]; then
      health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$container")"
      [[ "$health" == healthy ]] && return 0
    fi
    sleep 1
  done
  echo "timed out waiting for service $service" >&2
  return 1
}

raw_query() {
  local query=$1 output=$2
  jq -n --arg query "$query" '{query:$query}' |
    curl "${curl_args[@]}" --header 'Accept: application/json' \
      --header 'Content-Type: application/json' --data-binary @- "$admin_url/query" >"$output"
  jq -e 'keys == ["rows"] and (.rows | type == "array")' "$output" >/dev/null
}

restate_cli() {
  docker run --rm --network "$network" --env RESTATE_HOST=restate "$RESTATE_CLI_IMAGE" "$@"
}

control_post() {
  local path=$1 input=$2 output=$3
  curl "${curl_args[@]}" --header "Authorization: Bearer $admin_token" \
    --header 'Content-Type: application/json' --data-binary "@$input" "$control_url$path" >"$output"
}

control_get() {
  local path=$1 output=$2
  curl "${curl_args[@]}" --header "Authorization: Bearer $admin_token" "$control_url$path" >"$output"
}

provider_stats() {
  local service=$1 output=$2
  "${compose_all[@]}" exec -T "$service" wget -qO- -T 5 http://127.0.0.1:8081/v1/stats >"$output"
}

register_deployment() {
  local variant=$1 uri=$2 output=$3
  jq -n --arg uri "$uri" --arg variant "$variant" --arg commit "$RESTATE_EXAMPLES_COMMIT" --arg method "$method" \
    '{uri:$uri,force:false,breaking:false,metadata:{variant:$variant,upstream_commit:$commit,method:$method}}' |
    curl "${curl_args[@]}" --request POST --header 'Content-Type: application/json' \
      --data-binary @- "$admin_url/deployments" >"$output"
  jq -e '(.services | length) == 6 and (.id | type) == "string"' "$output" >/dev/null
}

create_subscription() {
  local prefix=$1
  jq -n '{source:"kafka://my-cluster/driver-updates",sink:"service://driver-digital-twin/handleDriverLocationUpdateEvent"}' \
    >"$results_dir/$prefix-subscription-request.json"
  curl "${curl_args[@]}" --request POST --header 'Content-Type: application/json' \
    --data-binary "@$results_dir/$prefix-subscription-request.json" "$admin_url/subscriptions" \
    >"$results_dir/$prefix-subscription.json"
}

start_drivers() {
  local prefix=$1
  for driver in driver-01 driver-02; do
    curl "${curl_args[@]}" --request POST --header 'Content-Type: application/json' --data '{}' \
      "$ingress_url/driver-mobile-app/$driver/startDriver/send" >"$results_dir/$prefix-$driver.json"
  done
}

write_order() {
  local order_id=$1 delay=$2 output=$3
  jq -n --arg id "$order_id" --argjson delay "$delay" '{
    id:$id,restaurantId:"restaurant-01",
    products:[{productId:"pizza-01",description:"Pizza",quantity:1}],
    totalCost:42,deliveryDelay:$delay
  }' >"$output"
}

submit_order() {
  local order=$1 output=$2 order_id
  order_id="$(jq -er .id "$order")"
  curl "${curl_args[@]}" --request POST --header 'Content-Type: application/json' \
    --data-binary "@$order" "$ingress_url/order-workflow/$order_id/run/send" >"$output"
}

query_sql_for() {
  local order_id=$1
  lookup_sql="SELECT id,target,status,pinned_deployment_id,pinned_service_protocol_version,last_attempt_deployment_id,retry_count,next_retry_at,journal_size,created_at,modified_at FROM sys_invocation WHERE target_service_name = 'order-workflow' AND target_service_key = '$order_id' AND target_handler_name = 'run' ORDER BY id"
  state_sql="SELECT service_name,service_key,key,value,value_utf8,value_length FROM state WHERE service_name = 'order-workflow' AND service_key = '$order_id' ORDER BY key"
}

write_requirements() {
  local prefix=$1 payment='http://payment:8081/v1/charge' query='http://payment:8081/v1/query' finish='http://completion:8081/v1/complete'
  jq -n --arg payment "$payment" --arg query "$query" --arg finish "$finish" '{
    id:"food-ordering-unsafe-source-v1",results:{paid:1,delivered:1},capacities:{approval:1},
    kinds:{
      "charge-v1":{costs:{approval:1},produces:{paid:1},retry_safe:false,queryable:true,
        target:$payment,method:"POST",response_classifier:"operation-receipt-v1",
        query_target:$query,query_method:"POST",query_classifier:"operation-observation-v1"},
      "finish-v1":{costs:{},produces:{delivered:1},retry_safe:true,queryable:false,
        target:$finish,method:"POST",response_classifier:"operation-receipt-v1"}
    }
  }' >"$results_dir/$prefix-requirement-source.json"
  jq -n --arg query "$query" --arg finish "$finish" '{
    id:"food-ordering-unsafe-target-v2",results:{paid:1,delivered:1},capacities:{approval:1},
    kinds:{
      "charge-v1":{costs:{approval:1},produces:{paid:1},retry_safe:false,queryable:false},
      "finish-v1":{costs:{},produces:{delivered:1},retry_safe:false,queryable:false},
      "charge-v2":{costs:{},produces:{paid:1},retry_safe:false,queryable:true,
        target:"http://payment:8081/v2/charge",method:"POST",response_classifier:"operation-receipt-v1",
        query_target:$query,query_method:"POST",query_classifier:"operation-observation-v1"},
      "finish-v2":{costs:{approval:1},produces:{delivered:1},retry_safe:true,queryable:false,
        target:$finish,method:"POST",response_classifier:"operation-receipt-v1"}
    }
  }' >"$results_dir/$prefix-requirement-target.json"
}

check_certificate() {
  local state=$1 certificate=$2 output=$3
  (cd "$script_dir/../.." && go run ./cmd/check-certificate -state "$state" -certificate "$certificate") >"$output"
}

capture_provider_files() {
  local prefix=$1 payment_container completion_container
  payment_container="$("${compose_all[@]}" ps --quiet payment)"
  completion_container="$("${compose_all[@]}" ps --quiet completion)"
  docker cp "$payment_container:/state/payment.history" "$results_dir/$prefix-payment.history"
  docker cp "$completion_container:/state/completion.history" "$results_dir/$prefix-completion.history"
}

capture_all_containers() {
  local output=$1
  mapfile -t ids < <(docker ps --all --quiet --filter "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME" | sort)
  [[ ${#ids[@]} -gt 0 ]] || { echo "compose project has no containers" >&2; return 1; }
  docker inspect "${ids[@]}" >"$output"
}

wait_terminal() {
  local sql=$1 output_prefix=$2
  terminal_status=""
  for second in $(seq 0 180); do
    raw_query "$sql" "$results_dir/$output_prefix-observation-$second.json"
    terminal_status="$(jq -r 'if (.rows|length)==1 then .rows[0].status else "" end' "$results_dir/$output_prefix-observation-$second.json")"
    case "$terminal_status" in completed|failed|killed|cancelled) return 0;; esac
    [[ $second -eq 180 ]] || sleep 1
  done
  return 1
}

write_expected_completion() {
  local order_id=$1 closure=$2 output=$3
  python3 - "$order_id" "$closure" >"$output" <<'PY'
import base64, hashlib, json, sys
order, closure = sys.argv[1:]
body = {"order_id": order, "status": "DELIVERED"}
if closure:
    body["closure_version"] = closure
encoded = json.dumps(body, separators=(",", ":")).encode()
provider_hash = hashlib.sha256(b"POST\0/v1/complete\0" + encoded).hexdigest()
print(json.dumps({"body_base64":base64.b64encode(encoded).decode(),"provider_request_hash":provider_hash}, sort_keys=True, separators=(",", ":")))
PY
}

# Phase A: run the exact target image and resolved target environment on fresh
# Restate, provider, and control volumes.  This is a real target-feasibility
# control, not a model-only compilation.
clean_order_id="${UNSAFE_CLEAN_ORDER_ID:-unsafe-clean-$method-$(date +%s)-$$}"
main_order_id="${ORDER_ID:-unsafe-main-$method-$(date +%s)-$$}"
for value in "$clean_order_id" "$main_order_id"; do
  [[ "$value" =~ ^[A-Za-z0-9._-]{1,128}$ ]] || { echo "order identity contains unsupported characters" >&2; exit 64; }
done
[[ "$clean_order_id" != "$main_order_id" ]] || { echo "clean and main order identities must differ" >&2; exit 64; }
write_requirements clean

set_source_inputs "$target_image" charge-v2 http://payment:8081/v2/charge finish-v2 http://completion:8081/v1/complete
"${compose[@]}" config --quiet
"${compose_all[@]}" config >"$results_dir/clean-compose-config.yaml"
"${compose[@]}" up --detach
wait_url "$admin_url/health"
wait_url "http://127.0.0.1:$WEBUI_PORT" 240
if [[ "$method" == proposed ]]; then
  wait_url "$control_url/healthz"
  admin_token="$("${compose[@]}" exec -T control cat /state/admin-token | tr -d '\r\n')"
  [[ ${#admin_token} -ge 32 ]] || { echo "clean control token is invalid" >&2; exit 1; }
  control_post /v1/compile "$results_dir/clean-requirement-target.json" "$results_dir/clean-certificate-target.json"
  jq -e '.decision == "activate" and .rule.allow == ["charge-v2","finish-v2"]' "$results_dir/clean-certificate-target.json" >/dev/null
  control_post /v1/certificate-state "$results_dir/clean-certificate-target.json" "$results_dir/clean-certificate-target-state.json"
  check_certificate "$results_dir/clean-certificate-target-state.json" "$results_dir/clean-certificate-target.json" "$results_dir/clean-certificate-target-verdict.json"
  jq -e '.valid == true and .decision == "activate" and .history_sequence == 0' "$results_dir/clean-certificate-target-verdict.json" >/dev/null
  control_post /v1/activate "$results_dir/clean-certificate-target.json" "$results_dir/clean-active-target.json"
else
  if [[ -n "$("${compose_all[@]}" ps --all --quiet control)" ]]; then echo "native clean control unexpectedly started" >&2; exit 1; fi
fi
register_deployment "$method-unsafe-clean" http://order-v1:9080 "$results_dir/clean-deployment-target.json"
create_subscription clean
start_drivers clean
write_order "$clean_order_id" 0 "$results_dir/clean-order.json"
sha256sum "$results_dir/clean-order.json" >"$results_dir/clean-order.sha256"
submit_order "$results_dir/clean-order.json" "$results_dir/clean-submit.json"
query_sql_for "$clean_order_id"
clean_invocation_id="$(jq -er .invocationId "$results_dir/clean-submit.json")"
clean_status_sql="SELECT id,target,status,pinned_deployment_id,pinned_service_protocol_version,last_attempt_deployment_id,retry_count,next_retry_at,journal_size,created_at,modified_at FROM sys_invocation WHERE id = '$clean_invocation_id'"
wait_terminal "$clean_status_sql" clean || { echo "clean target order did not terminate" >&2; exit 1; }
[[ "$terminal_status" == completed ]] || { echo "clean target order ended as $terminal_status" >&2; exit 1; }
raw_query "$clean_status_sql" "$results_dir/clean-final-status.json"
raw_query "SELECT index,version,entry_type,name,COALESCE(completed,false) AS completed,raw,raw_length,entry_lite_json FROM sys_journal WHERE id = '$clean_invocation_id' ORDER BY index" "$results_dir/clean-final-journal.json"
raw_query "$state_sql" "$results_dir/clean-final-workflow-state.json"
provider_stats payment "$results_dir/clean-final-payment-stats.json"
provider_stats completion "$results_dir/clean-final-completion-stats.json"
capture_provider_files clean
clean_container="$("${compose[@]}" ps --quiet order-v1)"
docker inspect "$clean_container" >"$results_dir/clean-target-container.json"
docker logs "$clean_container" >"$results_dir/clean-target.log" 2>&1
curl "${curl_args[@]}" "$admin_url/deployments" >"$results_dir/clean-deployments.json"
capture_all_containers "$results_dir/clean-containers.raw.json"
if [[ "$method" == proposed ]]; then
  control_get /v1/state "$results_dir/clean-final-control-state.json"
  control_get /v1/history "$results_dir/clean-final-control-history.json"
  clean_control="$("${compose_all[@]}" ps --quiet control)"
  docker cp "$clean_control:/state/runtime.history" "$results_dir/clean-runtime.history"
  docker cp "$clean_control:/anchor/runtime.head" "$results_dir/clean-runtime.head"
fi
write_expected_completion "$clean_order_id" unsafe-v2 "$results_dir/clean-expected-completion.json"
jq -e '.deliveries == 1 and .commits == 1 and .paths == {"/v2/charge":1}' "$results_dir/clean-final-payment-stats.json" >/dev/null
jq -e '.deliveries == 1 and .commits == 1 and .paths == {"/v1/complete":1}' "$results_dir/clean-final-completion-stats.json" >/dev/null
[[ "$(wc -l <"$results_dir/clean-payment.history")" -eq 1 && "$(wc -l <"$results_dir/clean-completion.history")" -eq 1 ]]
clean_completion_hash="$(jq -er .provider_request_hash "$results_dir/clean-expected-completion.json")"
jq -e --arg hash "$clean_completion_hash" '.path == "/v1/complete" and .request_hash == $hash' "$results_dir/clean-completion.history" >/dev/null

"${compose_all[@]}" down --volumes --remove-orphans >"$results_dir/clean-down.stdout" 2>"$results_dir/clean-down.stderr"
if [[ -n "$(docker ps --all --quiet --filter "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME")" ]]; then
  echo "clean target phase left containers behind" >&2
  exit 1
fi

# Phase B: rebuild fresh source state, stop after the v1 payment has succeeded,
# and apply the unsafe edit decision to that specific History.
set_source_inputs "$source_image" charge-v1 http://payment:8081/v1/charge finish-v1 http://completion:8081/v1/complete
"${compose[@]}" config --quiet
"${compose_all[@]}" config >"$results_dir/main-compose-config.yaml"
"${compose[@]}" up --detach
wait_url "$admin_url/health"
wait_url "http://127.0.0.1:$WEBUI_PORT" 240
if [[ "$method" == proposed ]]; then
  wait_url "$control_url/healthz"
  admin_token="$("${compose[@]}" exec -T control cat /state/admin-token | tr -d '\r\n')"
  [[ ${#admin_token} -ge 32 ]] || { echo "main control token is invalid" >&2; exit 1; }
  control_post /v1/compile "$results_dir/clean-requirement-source.json" "$results_dir/main-certificate-source.json"
  jq -e '.decision == "activate" and .rule.allow == ["charge-v1","finish-v1"]' "$results_dir/main-certificate-source.json" >/dev/null
  control_post /v1/activate "$results_dir/main-certificate-source.json" "$results_dir/main-active-source.json"
else
  if [[ -n "$("${compose_all[@]}" ps --all --quiet control)" ]]; then echo "native main control unexpectedly started" >&2; exit 1; fi
fi
register_deployment "$method-v1" http://order-v1:9080 "$results_dir/main-deployment-source.json"
source_deployment_id="$(jq -er .id "$results_dir/main-deployment-source.json")"
create_subscription main
write_order "$main_order_id" 30000 "$results_dir/main-order.json"
sha256sum "$results_dir/main-order.json" >"$results_dir/main-order.sha256"
submit_order "$results_dir/main-order.json" "$results_dir/main-submit.json"
query_sql_for "$main_order_id"
source_invocation_id="$(jq -er .invocationId "$results_dir/main-submit.json")"
source_status_sql="SELECT id,target,status,pinned_deployment_id,pinned_service_protocol_version,last_attempt_deployment_id,retry_count,next_retry_at,journal_size,created_at,modified_at FROM sys_invocation WHERE id = '$source_invocation_id'"
source_journal_sql="SELECT index,version,entry_type,name,COALESCE(completed,false) AS completed,raw,raw_length,entry_lite_json FROM sys_journal WHERE id = '$source_invocation_id' ORDER BY index"
cut_reached=0
for _ in $(seq 1 180); do
  raw_query "$source_status_sql" "$results_dir/main-status-before-pause.json"
  raw_query "$source_journal_sql" "$results_dir/main-journal-before-pause.json"
  provider_stats payment "$results_dir/main-payment-before-pause.json"
  provider_stats completion "$results_dir/main-completion-before-pause.json"
  control_ready=true
  if [[ "$method" == proposed ]]; then
    control_get /v1/state "$results_dir/main-control-before-pause.json"
    jq -e '([.operations[] | select(.kind == "charge-v1" and .phase == "succeeded")] | length) == 1 and ([.operations[] | select(.kind == "finish-v1")] | length) == 0' "$results_dir/main-control-before-pause.json" >/dev/null || control_ready=false
  fi
  if jq -e '([.rows[] | select(.entry_type == "Command: Run" and .name == "payment")] | length) == 1 and ([.rows[] | select(.entry_type == "Notification: Run")] | length) == 1 and .rows[-1].entry_type == "Command: Sleep" and .rows[-1].completed == false' "$results_dir/main-journal-before-pause.json" >/dev/null \
    && jq -e '.deliveries == 1 and .commits == 1 and .paths == {"/v1/charge":1}' "$results_dir/main-payment-before-pause.json" >/dev/null \
    && jq -e '.deliveries == 0 and .commits == 0 and .paths == {}' "$results_dir/main-completion-before-pause.json" >/dev/null \
    && [[ "$control_ready" == true ]]; then cut_reached=1; break; fi
  sleep 1
done
[[ $cut_reached -eq 1 ]] || { echo "main source did not reach the paid future-only cut" >&2; exit 1; }

restate_cli --yes invocations pause "$source_invocation_id" >"$results_dir/main-pause.stdout" 2>"$results_dir/main-pause.stderr"
paused=0
for _ in $(seq 1 120); do
  raw_query "$source_status_sql" "$results_dir/main-cut-status.json"
  if jq -e --arg id "$source_invocation_id" --arg deployment "$source_deployment_id" '(.rows|length)==1 and .rows[0].id==$id and .rows[0].status=="paused" and .rows[0].pinned_deployment_id==$deployment' "$results_dir/main-cut-status.json" >/dev/null; then paused=1; break; fi
  sleep 1
done
[[ $paused -eq 1 ]] || { echo "main source did not pause" >&2; exit 1; }
raw_query "$source_journal_sql" "$results_dir/main-cut-journal.json"
raw_query "$state_sql" "$results_dir/main-cut-workflow-state.json"
provider_stats payment "$results_dir/main-payment-at-cut.json"
provider_stats completion "$results_dir/main-completion-at-cut.json"
capture_provider_files main-at-cut
source_container="$("${compose[@]}" ps --quiet order-v1)"
docker inspect "$source_container" >"$results_dir/main-source-container-at-cut.json"
docker logs "$source_container" >"$results_dir/main-source.log" 2>&1
capture_all_containers "$results_dir/main-containers-before-decision.raw.json"
if [[ -n "$("${compose_all[@]}" ps --all --quiet order-v2)" ]]; then echo "unsafe target existed before the decision" >&2; exit 1; fi

sleep 33
raw_query "$source_status_sql" "$results_dir/main-cut-status-after-window.json"
raw_query "$source_journal_sql" "$results_dir/main-cut-journal-after-window.json"
raw_query "$state_sql" "$results_dir/main-cut-workflow-state-after-window.json"
provider_stats payment "$results_dir/main-payment-after-window.json"
provider_stats completion "$results_dir/main-completion-after-window.json"
cmp "$results_dir/main-cut-workflow-state.json" "$results_dir/main-cut-workflow-state-after-window.json"
cmp "$results_dir/main-payment-at-cut.json" "$results_dir/main-payment-after-window.json"
cmp "$results_dir/main-completion-at-cut.json" "$results_dir/main-completion-after-window.json"
jq -e -s '.[0].rows as $a | .[1].rows as $b | ($b|length)==($a|length)+1 and $b[0:($a|length)]==$a and $b[-1].entry_type=="Notification: Sleep"' "$results_dir/main-cut-journal.json" "$results_dir/main-cut-journal-after-window.json" >/dev/null

target_deployment_id=""
if [[ "$method" == proposed ]]; then
  control_get /v1/state "$results_dir/main-control-at-cut.json"
  control_get /v1/history "$results_dir/main-control-history-at-cut.json"
  control_post /v1/compile "$results_dir/clean-requirement-target.json" "$results_dir/main-certificate-unsafe.json"
  jq -e '.decision == "impossible" and .rule == null and .witness.reason == "no completion fits the remaining resources for delivered:1"' "$results_dir/main-certificate-unsafe.json" >/dev/null
  control_post /v1/certificate-state "$results_dir/main-certificate-unsafe.json" "$results_dir/main-certificate-unsafe-state.json"
  check_certificate "$results_dir/main-certificate-unsafe-state.json" "$results_dir/main-certificate-unsafe.json" "$results_dir/main-certificate-unsafe-verdict.json"
  jq -e '.valid == true and .decision == "impossible"' "$results_dir/main-certificate-unsafe-verdict.json" >/dev/null
  control_get /v1/state "$results_dir/main-control-after-refusal.json"
  control_get /v1/history "$results_dir/main-control-history-after-refusal.json"
  cmp "$results_dir/main-control-at-cut.json" "$results_dir/main-control-after-refusal.json"
  cmp "$results_dir/main-control-history-at-cut.json" "$results_dir/main-control-history-after-refusal.json"
  jq -e '.rule.version == 1 and .rule.allow == ["finish-v1"] and .requirement.id == "food-ordering-unsafe-source-v1"' "$results_dir/main-control-after-refusal.json" >/dev/null
  set +e
  restate_cli --yes invocations resume "$source_invocation_id" --deployment "$source_deployment_id" >"$results_dir/main-resume.stdout" 2>"$results_dir/main-resume.stderr"
  resume_status=$?
  set -e
else
  docker rm --force "$source_container" >"$results_dir/main-source-removal.txt"
  set +e
  docker inspect "$source_container" >"$results_dir/main-source-after-removal.json" 2>"$results_dir/main-source-after-removal.stderr"
  removal_inspect_status=$?
  set -e
  printf '%s\n' "$removal_inspect_status" >"$results_dir/main-source-after-removal.exit-status.txt"
  [[ $removal_inspect_status -eq 1 && -z "$("${compose_all[@]}" ps --all --quiet order-v1)" ]] || { echo "native source was not removed" >&2; exit 1; }
  "${compose_all[@]}" up --detach --no-deps order-v2
  wait_service_healthy order-v2
  target_container="$("${compose_all[@]}" ps --quiet order-v2)"
  docker inspect "$target_container" >"$results_dir/main-target-container.json"
  register_deployment native-unsafe-v2 http://order-v2:9080 "$results_dir/main-deployment-target.json"
  target_deployment_id="$(jq -er .id "$results_dir/main-deployment-target.json")"
  set +e
  restate_cli --yes invocations resume "$source_invocation_id" --deployment "$target_deployment_id" >"$results_dir/main-resume.stdout" 2>"$results_dir/main-resume.stderr"
  resume_status=$?
  set -e
fi
printf '%s\n' "$resume_status" >"$results_dir/main-resume.exit-status.txt"
[[ $resume_status -eq 0 ]] || { echo "official Restate resume failed" >&2; exit 1; }
start_drivers main
wait_terminal "$source_status_sql" main || { echo "main invocation did not terminate" >&2; exit 1; }
[[ "$terminal_status" == completed ]] || { echo "main invocation ended as $terminal_status" >&2; exit 1; }

raw_query "$lookup_sql" "$results_dir/main-final-invocations.json"
raw_query "$source_status_sql" "$results_dir/main-final-status.json"
raw_query "$source_journal_sql" "$results_dir/main-final-journal.json"
raw_query "$state_sql" "$results_dir/main-final-workflow-state.json"
provider_stats payment "$results_dir/main-final-payment-stats.json"
provider_stats completion "$results_dir/main-final-completion-stats.json"
capture_provider_files main
curl "${curl_args[@]}" "$admin_url/deployments" >"$results_dir/main-deployments.json"
capture_all_containers "$results_dir/main-containers.raw.json"
if [[ "$method" == proposed ]]; then
  docker inspect "$source_container" >"$results_dir/main-final-source-container.json"
  control_get /v1/state "$results_dir/main-final-control-state.json"
  control_get /v1/history "$results_dir/main-final-control-history.json"
  control_container="$("${compose_all[@]}" ps --quiet control)"
  docker cp "$control_container:/state/runtime.history" "$results_dir/main-runtime.history"
  docker cp "$control_container:/anchor/runtime.head" "$results_dir/main-runtime.head"
  if [[ -n "$("${compose_all[@]}" ps --all --quiet order-v2)" ]]; then echo "refused target was started" >&2; exit 1; fi
  write_expected_completion "$main_order_id" '' "$results_dir/main-expected-completion.json"
else
  docker logs "$target_container" >"$results_dir/main-target.log" 2>&1
  docker inspect "$target_container" >"$results_dir/main-final-target-container.json"
  write_expected_completion "$main_order_id" unsafe-v2 "$results_dir/main-expected-completion.json"
fi
jq -e '.deliveries == 1 and .commits == 1 and .paths == {"/v1/charge":1}' "$results_dir/main-final-payment-stats.json" >/dev/null
jq -e '.deliveries == 1 and .commits == 1 and .paths == {"/v1/complete":1}' "$results_dir/main-final-completion-stats.json" >/dev/null
jq -e --arg order "$main_order_id" '(.rows|length)==1 and .rows[0].service_key==$order and .rows[0].key=="status" and .rows[0].value_utf8=="\"DELIVERED\""' "$results_dir/main-final-workflow-state.json" >/dev/null
[[ "$(wc -l <"$results_dir/main-payment.history")" -eq 1 && "$(wc -l <"$results_dir/main-completion.history")" -eq 1 ]]
main_completion_hash="$(jq -er .provider_request_hash "$results_dir/main-expected-completion.json")"
jq -e --arg hash "$main_completion_hash" '.path == "/v1/complete" and .request_hash == $hash' "$results_dir/main-completion.history" >/dev/null

read -r runner_hash _ <"$results_dir/runner.sha256"
jq -n --arg method "$method" --arg state_dir "$UNSAFE_STATE_DIR" \
  --arg clean_order_id "$clean_order_id" --arg main_order_id "$main_order_id" \
  --arg source_image "$source_image" --arg target_image "$target_image" \
  --arg build_env "$(realpath "$build_env")" --arg runner_hash "$runner_hash" \
  --arg target_requirement_sha256 "$(sha256sum "$results_dir/clean-requirement-target.json" | sed 's/ .*//')" \
  --arg target_patch_sha256 "$(sha256sum "$results_dir/unsafe-target.patch" | sed 's/ .*//')" \
  --arg target_dockerfile_sha256 "$(sha256sum "$results_dir/Dockerfile.worker" | sed 's/ .*//')" \
  --arg target_overlay_sha256 "$(sha256sum "$results_dir/compose.unsafe.yaml" | sed 's/ .*//')" \
  --argjson skip_build "${SKIP_BUILD:-0}" '{
    schema:1,cell:"history-dependent-unsafe-edit",method:$method,state_dir:$state_dir,
    clean_order_id:$clean_order_id,main_order_id:$main_order_id,
    source_image:$source_image,target_image:$target_image,build_env:$build_env,
    runner_sha256:$runner_hash,skip_build:($skip_build==1),
    target_binding:{requirement_sha256:$target_requirement_sha256,patch_sha256:$target_patch_sha256,
      dockerfile_sha256:$target_dockerfile_sha256,overlay_sha256:$target_overlay_sha256}
  }' >"$results_dir/run-metadata.json"

jq -n --arg method "$method" --arg clean "$clean_order_id" --arg main "$main_order_id" \
  --arg target "$target_image" --arg target_deployment "$target_deployment_id" '{
    schema:1,method:$method,clean_order_id:$clean,main_order_id:$main,target_image:$target,
    clean_target_completed:true,main_completed:true,
    proposed_refused_before_target:($method=="proposed"),
    native_completed_without_requirement_enforcement:($method=="native"),
    target_deployment_id:(if $target_deployment=="" then null else $target_deployment end)
  }' >"$results_dir/observed.json"
cat "$results_dir/observed.json"
