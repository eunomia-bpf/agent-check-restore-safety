#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
method="${COMPATIBLE_METHOD:-}"
if [[ "$method" != proposed && "$method" != native ]]; then
  echo "COMPATIBLE_METHOD must be proposed or native" >&2
  exit 2
fi
if [[ -z "${COMPATIBLE_STATE_DIR:-}" ]]; then
  COMPATIBLE_STATE_DIR="$(mktemp -d "/tmp/safe-change-compatible-$method.XXXXXX")"
elif [[ -e "$COMPATIBLE_STATE_DIR" ]]; then
  if [[ ! -d "$COMPATIBLE_STATE_DIR" || -n "$(find "$COMPATIBLE_STATE_DIR" -mindepth 1 -print -quit)" ]]; then
    echo "COMPATIBLE_STATE_DIR must be absent or an empty directory" >&2
    exit 2
  fi
else
  mkdir -p "$COMPATIBLE_STATE_DIR"
fi
COMPATIBLE_STATE_DIR="$(realpath "$COMPATIBLE_STATE_DIR")"
results_dir="$COMPATIBLE_STATE_DIR/results"
mkdir -p "$results_dir"
chmod 700 "$COMPATIBLE_STATE_DIR" "$results_dir"

for command in cmp curl date docker find go jq python3 realpath sed seq sha256sum sort tr wc; do
  command -v "$command" >/dev/null || {
    echo "required command not found: $command" >&2
    exit 1
  }
done

build_env="${HARNESS_BUILD_ENV:-$COMPATIBLE_STATE_DIR/build.env}"
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
for required in ORDER_COMPATIBLE_V2_IMAGE NATIVE_ORDER_COMPATIBLE_V2_IMAGE \
  COMPATIBLE_V2_CONTEXT_SHA256 NATIVE_COMPATIBLE_V2_CONTEXT_SHA256 \
  COMPATIBLE_V2_WORKFLOW_SHA256 COMPATIBLE_V2_COMPILED_SHA256 \
  NATIVE_COMPATIBLE_V2_COMPILED_SHA256; do
  [[ -n "${!required:-}" ]] || {
    echo "build metadata omitted $required" >&2
    exit 1
  }
done

if [[ "$method" == proposed ]]; then
  target_image="$ORDER_COMPATIBLE_V2_IMAGE"
  source_image="$ORDER_V1_IMAGE"
  ORDER_V2_IMAGE="$target_image"
  export ORDER_V2_IMAGE
  compose_files=(--file "$script_dir/compose.yaml")
else
  target_image="$NATIVE_ORDER_COMPATIBLE_V2_IMAGE"
  source_image="$NATIVE_ORDER_V1_IMAGE"
  NATIVE_ORDER_V2_IMAGE="$target_image"
  export NATIVE_ORDER_V2_IMAGE
  compose_files=(--file "$script_dir/compose.yaml" --file "$script_dir/compose-native.yaml")
fi
cp "$build_env" "$results_dir/build.env"
cp "$script_dir/versions.env" "$results_dir/versions.env"
cp "$script_dir/images.env" "$results_dir/images.env"
sha256sum "$script_dir/run-compatible-case.sh" >"$results_dir/runner.sha256"
chmod 600 "$results_dir/build.env"

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
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-safe-change-compatible-$method-$$}"
PAYMENT_HOLD_BEFORE_COMMIT=false
PAYMENT_HOLD_AFTER_COMMIT=false
export RESTATE_INGRESS_PORT RESTATE_ADMIN_PORT CONTROL_PORT JAEGER_PORT WEBUI_PORT
export COMPOSE_PROJECT_NAME PAYMENT_HOLD_BEFORE_COMMIT PAYMENT_HOLD_AFTER_COMMIT

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
  echo "compatible $method evidence: $COMPATIBLE_STATE_DIR" >&2
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

wait_url() {
  local url=$1 attempts=${2:-180}
  for _ in $(seq 1 "$attempts"); do
    if curl --fail --silent --show-error --connect-timeout 2 --max-time 3 "$url" >/dev/null 2>&1; then
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
control_url="http://127.0.0.1:$CONTROL_PORT"
application_network="${COMPOSE_PROJECT_NAME}_application"
curl_args=(--fail --silent --show-error --connect-timeout 5 --max-time 120)

raw_query() {
  local query=$1 output=$2
  jq -n --arg query "$query" '{query:$query}' |
    curl "${curl_args[@]}" --header 'Accept: application/json' --header 'Content-Type: application/json' \
      --data-binary @- "$restate_admin_url/query" >"$output"
  jq -e 'keys == ["rows"] and (.rows | type == "array")' "$output" >/dev/null
}

restate_cli() {
  docker run --rm --network "$application_network" --env RESTATE_HOST=restate \
    "$RESTATE_CLI_IMAGE" "$@"
}

register_deployment() {
  local variant=$1 uri=$2 output=$3
  jq -n --arg uri "$uri" --arg variant "$variant" --arg commit "$RESTATE_EXAMPLES_COMMIT" --arg method "$method" \
    '{uri:$uri,force:false,breaking:false,metadata:{variant:$variant,upstream_commit:$commit,method:$method}}' |
    curl "${curl_args[@]}" --request POST --header 'Content-Type: application/json' \
      --data-binary @- "$restate_admin_url/deployments" >"$output"
  jq -e '(.services | length) == 6 and .id != null' "$output" >/dev/null
}

provider_stats() {
  local service=$1 output=$2
  "${compose_all[@]}" exec -T "$service" wget -qO- -T 5 http://127.0.0.1:8081/v1/stats >"$output"
}

"${compose[@]}" config --quiet
"${compose_all[@]}" config >"$results_dir/compose-config.yaml"
"${compose[@]}" up --detach
wait_url "$restate_admin_url/health"
wait_url "http://127.0.0.1:$WEBUI_PORT" 240

if [[ "$method" == proposed ]]; then
  wait_url "$control_url/healthz"
  admin_token="$("${compose[@]}" exec -T control cat /state/admin-token | tr -d '\r\n')"
  if [[ ${#admin_token} -lt 32 ]]; then
    echo "control did not create a valid admin token" >&2
    exit 1
  fi
  control_post() {
    local path=$1 input=$2 output=$3
    curl "${curl_args[@]}" --header "Authorization: Bearer $admin_token" \
      --header 'Content-Type: application/json' --data-binary "@$input" \
      "$control_url$path" >"$output"
  }
  control_get() {
    local path=$1 output=$2
    curl "${curl_args[@]}" --header "Authorization: Bearer $admin_token" "$control_url$path" >"$output"
  }
else
  if [[ -n "$("${compose_all[@]}" ps --quiet control)" ]]; then
    echo "native compatible lane unexpectedly started proposed control" >&2
    exit 1
  fi
fi

register_deployment "$method-v1" http://order-v1:9080 "$results_dir/deployment-v1.json"
v1_deployment_id="$(jq -r '.id' "$results_dir/deployment-v1.json")"
curl "${curl_args[@]}" "$restate_admin_url/services" >"$results_dir/services-v1.json"
jq -n '{source:"kafka://my-cluster/driver-updates",sink:"service://driver-digital-twin/handleDriverLocationUpdateEvent"}' \
  >"$results_dir/subscription-request.json"
curl "${curl_args[@]}" --request POST --header 'Content-Type: application/json' \
  --data-binary "@$results_dir/subscription-request.json" \
  "$restate_admin_url/subscriptions" >"$results_dir/subscription.json"

payment_target='http://payment:8081/v1/charge'
payment_query='http://payment:8081/v1/query'
finish_target='http://completion:8081/v1/complete'
jq -n --arg payment "$payment_target" --arg query "$payment_query" --arg finish "$finish_target" '{
  id:"food-ordering-v1",results:{paid:1,delivered:1},capacities:{charge:1},
  kinds:{
    "charge-v1":{costs:{charge:1},produces:{paid:1},retry_safe:false,queryable:true,
      target:$payment,method:"POST",response_classifier:"operation-receipt-v1",
      query_target:$query,query_method:"POST",query_classifier:"operation-observation-v1"},
    finish:{costs:{},produces:{delivered:1},retry_safe:true,queryable:false,
      target:$finish,method:"POST",response_classifier:"operation-receipt-v1"}
  }
}' >"$results_dir/requirement-source.json"
cp "$results_dir/requirement-source.json" "$results_dir/requirement-target.json"
cmp "$results_dir/requirement-source.json" "$results_dir/requirement-target.json"

if [[ "$method" == proposed ]]; then
  control_post /v1/compile "$results_dir/requirement-source.json" "$results_dir/certificate-v1.json"
  jq -e '.decision == "activate" and (.rule.allow | sort) == ["charge-v1","finish"]' \
    "$results_dir/certificate-v1.json" >/dev/null
  control_post /v1/activate "$results_dir/certificate-v1.json" "$results_dir/active-v1.json"
  jq -e --slurpfile certificate "$results_dir/certificate-v1.json" '
    $certificate[0] as $expected |
    .rule == $expected.rule and .requirement == $expected.requirement and
    (.history.sequence | type) == "number" and
    .history.sequence == ($expected.history.sequence + 1)
  ' "$results_dir/active-v1.json" >/dev/null
fi

order_id="${ORDER_ID:-compatible-$method-$(date +%s)-$$}"
if [[ ! "$order_id" =~ ^[A-Za-z0-9._-]{1,128}$ ]]; then
  echo "ORDER_ID contains unsupported characters" >&2
  exit 1
fi
delivery_delay="${COMPATIBLE_DELIVERY_DELAY_MS:-15000}"
if [[ ! "$delivery_delay" =~ ^[0-9]+$ || "$delivery_delay" -lt 10000 || "$delivery_delay" -gt 60000 ]]; then
  echo "COMPATIBLE_DELIVERY_DELAY_MS must be an integer in [10000,60000]" >&2
  exit 1
fi
read -r runner_sha256 _ <"$results_dir/runner.sha256"
jq -n \
  --arg recorded_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg method "$method" --arg state_dir "$COMPATIBLE_STATE_DIR" \
  --arg order_id "$order_id" --argjson delivery_delay_ms "$delivery_delay" \
  --arg source_image "$source_image" --arg target_image "$target_image" \
  --arg restate_cli_image "$RESTATE_CLI_IMAGE" --arg restate_server_image "$RESTATE_SERVER_IMAGE" \
  --arg runner_sha256 "$runner_sha256" --arg build_env "$(realpath "$build_env")" \
  --argjson skip_build "${SKIP_BUILD:-0}" '{
    schema:1,recorded_at:$recorded_at,method:$method,state_dir:$state_dir,
    order_id:$order_id,delivery_delay_ms:$delivery_delay_ms,
    source_image:$source_image,target_image:$target_image,
    restate_cli_image:$restate_cli_image,restate_server_image:$restate_server_image,
    runner_sha256:$runner_sha256,build_env:$build_env,skip_build:($skip_build == 1),
    effective_invocation:{
      COMPATIBLE_METHOD:$method,COMPATIBLE_STATE_DIR:$state_dir,ORDER_ID:$order_id,
      COMPATIBLE_DELIVERY_DELAY_MS:$delivery_delay_ms,SKIP_BUILD:$skip_build,
      HARNESS_BUILD_ENV:$build_env,script:"runtime/deploy/restate/run-compatible-case.sh"
    }
  }' >"$results_dir/run-metadata.json"
jq -n --arg id "$order_id" --argjson delay "$delivery_delay" '{
  id:$id,restaurantId:"restaurant-01",
  products:[{productId:"pizza-01",description:"Pizza",quantity:1}],
  totalCost:42,deliveryDelay:$delay
}' >"$results_dir/order.json"
sha256sum "$results_dir/order.json" >"$results_dir/order.sha256"
curl "${curl_args[@]}" --request POST --header 'Content-Type: application/json' \
  --data-binary "@$results_dir/order.json" \
  "$restate_ingress_url/order-workflow/$order_id/run/send" >"$results_dir/source-submit.json"

source_lookup_sql="SELECT id,target,status,pinned_deployment_id,pinned_service_protocol_version,last_attempt_deployment_id,retry_count,next_retry_at,journal_size,created_at,modified_at FROM sys_invocation WHERE target_service_name = 'order-workflow' AND target_service_key = '$order_id' AND target_handler_name = 'run' ORDER BY id"
source_workflow_state_sql="SELECT service_name,service_key,key,value,value_utf8,value_length FROM state WHERE service_name = 'order-workflow' AND service_key = '$order_id' ORDER BY key"

cut_reached=0
for _ in $(seq 1 120); do
  raw_query "$source_lookup_sql" "$results_dir/source-before-pause.json"
  candidate_invocation_id="$(jq -r 'if (.rows | length) == 1 then .rows[0].id else "" end' "$results_dir/source-before-pause.json")"
  if [[ -n "$candidate_invocation_id" ]]; then
    raw_query "SELECT index,version,entry_type,name,COALESCE(completed,false) AS completed,raw,raw_length,entry_lite_json FROM sys_journal WHERE id = '$candidate_invocation_id' ORDER BY index" "$results_dir/journal-before-pause.json"
  else
    jq -n '{rows:[]}' >"$results_dir/journal-before-pause.json"
  fi
  raw_query "$source_workflow_state_sql" "$results_dir/workflow-before-pause.json"
  provider_stats payment "$results_dir/payment-before-pause.json"
  provider_stats completion "$results_dir/completion-before-pause.json"
  control_ready=true
  if [[ "$method" == proposed ]]; then
    control_get /v1/state "$results_dir/control-before-pause.json"
    if ! jq -e '([.operations[] | select(.kind == "charge-v1" and .phase == "succeeded")] | length) == 1 and ([.operations[] | select(.kind == "finish")] | length) == 0' \
      "$results_dir/control-before-pause.json" >/dev/null; then
      control_ready=false
    fi
  fi
  if jq -e '
      ([.rows[] | select(.entry_type == "Command: Run" and .name == "payment")] | length) == 1 and
      ([.rows[] | select(.entry_type == "Notification: Run")] | length) == 1 and
      .rows[-1].entry_type == "Command: Sleep" and .rows[-1].completed == false
    ' "$results_dir/journal-before-pause.json" >/dev/null \
    && jq -e --arg order "$order_id" '([.rows[] | select(.service_key == $order and .key == "status" and .value_utf8 == "\"SCHEDULED\"")] | length) == 1' "$results_dir/workflow-before-pause.json" >/dev/null \
    && jq -e '.deliveries == 1 and .commits == 1 and .paths["/v1/charge"] == 1' "$results_dir/payment-before-pause.json" >/dev/null \
    && jq -e '.deliveries == 0 and .commits == 0 and .paths == {}' "$results_dir/completion-before-pause.json" >/dev/null \
    && [[ "$control_ready" == true ]]; then
    cut_reached=1
    break
  fi
  sleep 1
done
if [[ $cut_reached -ne 1 ]]; then
  echo "workflow did not reach the compatible future-only cut" >&2
  exit 1
fi
jq -e '(.rows | length) == 1' "$results_dir/source-before-pause.json" >/dev/null
source_invocation_id="$(jq -r '.rows[0].id' "$results_dir/source-before-pause.json")"
source_created_at="$(jq -r '.rows[0].created_at' "$results_dir/source-before-pause.json")"

restate_cli --yes invocations pause "$source_invocation_id" \
  >"$results_dir/source-pause.stdout" 2>"$results_dir/source-pause.stderr"
paused=0
for _ in $(seq 1 120); do
  raw_query "$source_lookup_sql" "$results_dir/cut-status.json"
  if jq -e --arg id "$source_invocation_id" --arg deployment "$v1_deployment_id" '
    (.rows | length) == 1 and .rows[0].id == $id and .rows[0].status == "paused" and
    .rows[0].pinned_deployment_id == $deployment
  ' "$results_dir/cut-status.json" >/dev/null; then
    paused=1
    break
  fi
  sleep 1
done
if [[ $paused -ne 1 ]]; then
  echo "compatible source invocation did not pause" >&2
  exit 1
fi
source_status_sql="SELECT id,target,status,pinned_deployment_id,pinned_service_protocol_version,last_attempt_deployment_id,retry_count,next_retry_at,journal_size,created_at,modified_at FROM sys_invocation WHERE id = '$source_invocation_id'"
source_journal_sql="SELECT index,version,entry_type,name,COALESCE(completed,false) AS completed,raw,raw_length,entry_lite_json FROM sys_journal WHERE id = '$source_invocation_id' ORDER BY index"
raw_query "$source_journal_sql" "$results_dir/cut-journal.json"
raw_query "$source_workflow_state_sql" "$results_dir/cut-workflow-state.json"
provider_stats payment "$results_dir/payment-at-cut.json"
provider_stats completion "$results_dir/completion-at-cut.json"

source_container="$("${compose[@]}" ps --quiet order-v1)"
docker inspect "$source_container" >"$results_dir/source-container-before-removal.json"
if ! jq -e --arg image "$source_image" '
  length == 1 and .[0].Image == $image and .[0].State.Running == true
' "$results_dir/source-container-before-removal.json" >/dev/null; then
  echo "compatible source container does not match the immutable v1 image" >&2
  exit 1
fi
docker logs "$source_container" >"$results_dir/source-v1.log" 2>&1
payment_token="$(
  sed -nE "s/.*\\[$order_id\\] Executing payment with token ([^ ]+) for.*/\\1/p" \
    "$results_dir/source-v1.log" | tail -n 1
)"
if [[ ! "$payment_token" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]]; then
  echo "could not recover compatible payment token" >&2
  exit 1
fi

payment_container="$("${compose_all[@]}" ps --quiet payment)"
completion_container="$("${compose_all[@]}" ps --quiet completion)"
docker cp "$payment_container:/state/payment.history" "$results_dir/payment-at-cut.history"
docker cp "$completion_container:/state/completion.history" "$results_dir/completion-at-cut.history"
[[ "$(wc -l <"$results_dir/payment-at-cut.history")" -eq 1 ]]
[[ "$(wc -c <"$results_dir/completion-at-cut.history")" -eq 0 ]]

stability_seconds="$((delivery_delay / 1000 + 3))"
sleep "$stability_seconds"
raw_query "$source_status_sql" "$results_dir/cut-status-after-window.json"
raw_query "$source_journal_sql" "$results_dir/cut-journal-after-window.json"
raw_query "$source_workflow_state_sql" "$results_dir/cut-workflow-state-after-window.json"
provider_stats payment "$results_dir/payment-after-cut-window.json"
provider_stats completion "$results_dir/completion-after-cut-window.json"
docker cp "$payment_container:/state/payment.history" "$results_dir/payment-after-cut-window.history"
docker cp "$completion_container:/state/completion.history" "$results_dir/completion-after-cut-window.history"
if ! jq -e -s '
  .[0].rows as $before_status | .[1].rows as $after_status |
  .[2].rows as $before_journal | .[3].rows as $after_journal |
  ($before_journal[-1].entry_lite_json | fromjson) as $sleep_entry |
  $sleep_entry.Command.Sleep.completion_id as $sleep_id |
  {Notification:{ty:{Completion:"Sleep"},id:{CompletionId:$sleep_id},result:"Void"}} as $notification |
  ($before_status | length) == 1 and ($after_status | length) == 1 and
  $before_status[0].status == "paused" and $after_status[0].status == "paused" and
  ($before_status[0].modified_at | type) == "string" and
  ($after_status[0].modified_at | type) == "string" and
  ($sleep_entry | keys) == ["Command"] and ($sleep_entry.Command | keys) == ["Sleep"] and
  ($sleep_entry.Command.Sleep | keys) == ["completion_id","wake_up_time"] and
  ($sleep_entry.Command.Sleep.wake_up_time | type) == "number" and
  $sleep_id == 2 and
  $before_journal[-1].entry_type == "Command: Sleep" and
  $before_status[0].journal_size == ($before_journal | length) and
  $after_status[0].journal_size == ($after_journal | length) and
  $after_status[0].journal_size == ($before_status[0].journal_size + 1) and
  $after_status[0].modified_at > $before_status[0].modified_at and
  (($after_status[0] | del(.journal_size, .modified_at)) ==
   ($before_status[0] | del(.journal_size, .modified_at))) and
  ($after_journal | length) == (($before_journal | length) + 1) and
  $after_journal[0:($before_journal | length)] == $before_journal and
  $after_journal[-1] == {
    index:($before_journal[-1].index + 1),
    version:$before_journal[-1].version,
    entry_type:"Notification: Sleep",
    completed:false,
    raw:"08022200",
    raw_length:4,
    entry_lite_json:($notification | tojson)
  }
' "$results_dir/cut-status.json" "$results_dir/cut-status-after-window.json" \
  "$results_dir/cut-journal.json" "$results_dir/cut-journal-after-window.json" >/dev/null; then
  echo "compatible cut changed by more than the matching durable Sleep notification" >&2
  exit 1
fi
if ! jq -e -s '
  .[0] == .[1] and
  ([.[1].rows[] | select(.key == "status" and .value_utf8 == "\"SCHEDULED\"")] | length) == 1
' "$results_dir/cut-workflow-state.json" "$results_dir/cut-workflow-state-after-window.json" >/dev/null; then
  echo "compatible workflow state changed while paused" >&2
  exit 1
fi
if ! jq -e -s '
  .[0] == .[1] and .[1].deliveries == 1 and .[1].commits == 1 and
  .[1].paths == {"/v1/charge":1}
' "$results_dir/payment-at-cut.json" "$results_dir/payment-after-cut-window.json" >/dev/null; then
  echo "payment facts changed while the compatible invocation was paused" >&2
  exit 1
fi
if ! jq -e -s '
  .[0] == .[1] and .[1].deliveries == 0 and .[1].commits == 0 and .[1].paths == {}
' "$results_dir/completion-at-cut.json" "$results_dir/completion-after-cut-window.json" >/dev/null; then
  echo "completion was invoked before the compatible target started" >&2
  exit 1
fi
if ! cmp "$results_dir/payment-at-cut.history" "$results_dir/payment-after-cut-window.history" >/dev/null ||
   ! cmp "$results_dir/completion-at-cut.history" "$results_dir/completion-after-cut-window.history" >/dev/null; then
  echo "durable provider history changed while the compatible invocation was paused" >&2
  exit 1
fi

docker rm --force "$source_container" >"$results_dir/source-container-removal.txt"
set +e
docker inspect "$source_container" >"$results_dir/source-container-after-removal.json" 2>"$results_dir/source-container-after-removal.stderr"
source_inspect_exit=$?
set -e
if [[ $source_inspect_exit -ne 1 || -n "$("${compose_all[@]}" ps --all --quiet order-v1)" ]]; then
  echo "source v1 was not cleanly removed after the compatible cut" >&2
  exit 1
fi
printf '%s\n' "$source_inspect_exit" >"$results_dir/source-container-after-removal.exit-status.txt"

if [[ -n "$("${compose_all[@]}" ps --all --quiet order-v2)" ]]; then
  echo "compatible target existed before activation or registration" >&2
  exit 1
fi

if [[ "$method" == proposed ]]; then
  control_get /v1/state "$results_dir/control-at-cut.json"
  control_get /v1/history "$results_dir/control-history-at-cut.json"
  control_post /v1/compile "$results_dir/requirement-target.json" "$results_dir/certificate-compatible.json"
  jq -e '.decision == "activate" and .rule.allow == ["finish"]' "$results_dir/certificate-compatible.json" >/dev/null
  control_post /v1/certificate-state "$results_dir/certificate-compatible.json" "$results_dir/certificate-compatible-state.json"
  (
    cd "$script_dir/../.."
    go run ./cmd/check-certificate \
      -state "$results_dir/certificate-compatible-state.json" \
      -certificate "$results_dir/certificate-compatible.json"
  ) >"$results_dir/certificate-compatible-verdict.json"
  jq -e '.valid == true and .decision == "activate"' "$results_dir/certificate-compatible-verdict.json" >/dev/null
  control_post /v1/activate "$results_dir/certificate-compatible.json" "$results_dir/active-compatible.json"
  if ! jq -e --slurpfile certificate "$results_dir/certificate-compatible.json" '
    $certificate[0] as $expected |
    .rule == $expected.rule and .requirement == $expected.requirement and
    (.history.sequence | type) == "number" and
    .history.sequence == ($expected.history.sequence + 1)
  ' "$results_dir/active-compatible.json" >/dev/null; then
    echo "compatible Rule activation response did not match its Certificate" >&2
    exit 1
  fi
  activation_sequence="$(jq -er '.history.sequence | select(type == "number")' "$results_dir/active-compatible.json")"
else
  activation_sequence=0
fi

"${compose_all[@]}" up --detach --no-deps order-v2
wait_service_healthy order-v2
target_container="$("${compose_all[@]}" ps --quiet order-v2)"
docker inspect "$target_container" >"$results_dir/target-container.json"
if ! jq -e --arg image "$target_image" '
  length == 1 and .[0].Image == $image and .[0].State.Running == true
' "$results_dir/target-container.json" >/dev/null; then
  echo "compatible target container does not match the immutable v2 image" >&2
  exit 1
fi
jq -n --arg id "$target_container" --arg started_at "$(docker inspect --format '{{.State.StartedAt}}' "$target_container")" --argjson activation "$activation_sequence" \
  '{container_id:$id,started_at:$started_at,after_history_sequence:$activation}' >"$results_dir/target-start.json"
register_deployment "$method-compatible-v2" http://order-v2:9080 "$results_dir/deployment-compatible.json"
target_deployment_id="$(jq -r '.id' "$results_dir/deployment-compatible.json")"
curl "${curl_args[@]}" "$restate_admin_url/deployments" >"$results_dir/deployments.json"

for driver in driver-01 driver-02; do
  curl "${curl_args[@]}" --request POST --header 'Content-Type: application/json' --data '{}' \
    "$restate_ingress_url/driver-mobile-app/$driver/startDriver/send" >"$results_dir/$driver.json"
done

set +e
restate_cli --yes invocations resume "$source_invocation_id" --deployment "$target_deployment_id" \
  >"$results_dir/resume.stdout" 2>"$results_dir/resume.stderr"
resume_exit=$?
set -e
printf '%s\n' "$resume_exit" >"$results_dir/resume-exit-status.txt"

terminal_observed=0
for second in $(seq 0 180); do
  raw_query "$source_status_sql" "$results_dir/observation-$second.json"
  if jq -e '(.rows | length) == 1 and (.rows[0].status == "completed" or .rows[0].status == "failed" or .rows[0].status == "killed" or .rows[0].status == "cancelled")' \
    "$results_dir/observation-$second.json" >/dev/null; then
    terminal_observed=1
    break
  fi
  if [[ $second -lt 180 ]]; then sleep 1; fi
done
printf '%s\n' "$terminal_observed" >"$results_dir/terminal-observed.txt"

raw_query "$source_lookup_sql" "$results_dir/final-invocations.json"
raw_query "$source_status_sql" "$results_dir/final-status.json"
raw_query "$source_journal_sql" "$results_dir/final-journal.json"
raw_query "$source_workflow_state_sql" "$results_dir/final-workflow-state.json"
provider_stats payment "$results_dir/final-payment-stats.json"
provider_stats completion "$results_dir/final-completion-stats.json"
docker cp "$payment_container:/state/payment.history" "$results_dir/payment.history"
docker cp "$completion_container:/state/completion.history" "$results_dir/completion.history"
docker logs "$target_container" >"$results_dir/target-v2.log" 2>&1
docker inspect "$target_container" >"$results_dir/final-target-container.json"
if [[ "$method" == proposed ]]; then
  control_get /v1/state "$results_dir/final-control-state.json"
  control_get /v1/history "$results_dir/final-control-history.json"
fi
mapfile -t container_ids < <(
  docker ps --all --quiet --filter "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME" | sort
)
docker inspect "${container_ids[@]}" >"$results_dir/containers.raw.json"

python3 - "$order_id" >"$results_dir/expected-completion.json" <<'PY'
import base64
import hashlib
import json
import sys

order_id = sys.argv[1]
body = json.dumps(
    {
        "order_id": order_id,
        "status": "DELIVERED",
        "closure_version": "compatible-v2",
    },
    separators=(",", ":"),
).encode()
domain = "restate-order-workflow"

def operation_id(call_id: str) -> str:
    payload = b"operation-id-v1\0" + domain.encode() + b"\0" + call_id.encode()
    return "op-" + hashlib.sha256(payload).hexdigest()

completion_operation_id = operation_id(f"order/{order_id}/completion")
payment_operation_id = None
provider_hash = hashlib.sha256(b"POST\0/v1/complete\0" + body).hexdigest()
control_hash = hashlib.sha256()
control_hash.update(b"POST\0http://completion:8081/v1/complete\0")
for name, value in sorted(
    {
        "User-Agent": "safe-change-runtime/1",
        "Accept-Encoding": "identity",
        "Idempotency-Key": completion_operation_id,
        "X-Operation-ID": completion_operation_id,
    }.items(),
    key=lambda item: item[0].lower(),
):
    control_hash.update(name.lower().encode() + b":" + value.encode() + b"\0")
control_hash.update(body)
json.dump(
    {
        "schema": 1,
        "body_base64": base64.b64encode(body).decode(),
        "provider_request_hash": provider_hash,
        "control_request_hash": control_hash.hexdigest(),
        "completion_operation_id": completion_operation_id,
    },
    sys.stdout,
    sort_keys=True,
)
sys.stdout.write("\n")
PY
payment_operation_id="$(python3 - "$payment_token" <<'PY'
import hashlib
import sys
payload = b"operation-id-v1\0restate-order-workflow\0" + sys.argv[1].encode()
print("op-" + hashlib.sha256(payload).hexdigest())
PY
)"
completion_operation_id="$(jq -er '.completion_operation_id' "$results_dir/expected-completion.json")"
completion_provider_hash="$(jq -er '.provider_request_hash' "$results_dir/expected-completion.json")"
completion_control_hash="$(jq -er '.control_request_hash' "$results_dir/expected-completion.json")"
completion_body_base64="$(jq -er '.body_base64' "$results_dir/expected-completion.json")"

if [[ $resume_exit -ne 0 || $terminal_observed -ne 1 ]]; then
  echo "compatible invocation did not resume to a terminal state" >&2
  exit 1
fi
if ! jq -e --arg id "$source_invocation_id" --arg created "$source_created_at" --arg deployment "$target_deployment_id" '
  (.rows | length) == 1 and .rows[0].id == $id and .rows[0].created_at == $created and
  .rows[0].status == "completed" and .rows[0].pinned_deployment_id == $deployment
' "$results_dir/final-status.json" >/dev/null; then
  echo "compatible invocation did not complete under the target deployment" >&2
  exit 1
fi
if ! cmp "$results_dir/final-invocations.json" "$results_dir/final-status.json" >/dev/null; then
  echo "compatible run has an unexpected invocation lineage" >&2
  exit 1
fi
if ! jq -e --arg order "$order_id" '
  (.rows | length) == 1 and .rows[0].service_key == $order and
  .rows[0].key == "status" and .rows[0].value_utf8 == "\"DELIVERED\""
' "$results_dir/final-workflow-state.json" >/dev/null; then
  echo "compatible workflow did not reach DELIVERED" >&2
  exit 1
fi
if ! jq -e '.deliveries == 1 and .commits == 1 and .paths == {"/v1/charge":1}' \
  "$results_dir/final-payment-stats.json" >/dev/null ||
   ! jq -e '.deliveries == 1 and .commits == 1 and .paths == {"/v1/complete":1}' \
  "$results_dir/final-completion-stats.json" >/dev/null; then
  echo "compatible run did not produce exactly one payment and one completion" >&2
  exit 1
fi
if [[ "$(wc -l <"$results_dir/payment.history")" -ne 1 ||
      "$(wc -l <"$results_dir/completion.history")" -ne 1 ]]; then
  echo "compatible durable provider history contains duplicate records" >&2
  exit 1
fi
if ! jq -e --arg operation "$payment_operation_id" '
  keys == ["operation_id","path","remote_reference","request_hash","result_hash"] and
  .operation_id == $operation and .path == "/v1/charge" and
  (.request_hash | test("^[0-9a-f]{64}$")) and (.result_hash | test("^[0-9a-f]{64}$"))
' "$results_dir/payment.history" >/dev/null ||
   ! jq -e --arg operation "$completion_operation_id" --arg request_hash "$completion_provider_hash" '
  keys == ["operation_id","path","remote_reference","request_hash","result_hash"] and
  .operation_id == $operation and .path == "/v1/complete" and
  .request_hash == $request_hash and (.result_hash | test("^[0-9a-f]{64}$"))
' "$results_dir/completion.history" >/dev/null; then
  echo "compatible durable provider record does not match the executed Operations" >&2
  exit 1
fi
if ! jq -e --arg image "$target_image" '
  length == 1 and .[0].Image == $image and .[0].State.Running == true
' "$results_dir/final-target-container.json" >/dev/null; then
  echo "compatible target was not the expected running immutable image at completion" >&2
  exit 1
fi
if [[ "$method" == proposed ]]; then
  if ! jq -e --arg operation "$completion_operation_id" --arg request_hash "$completion_control_hash" \
    --arg body "$completion_body_base64" '
    .rule.version == 2 and .rule.allow == ["finish"] and
    (.operations | length) == 2 and
    .operations[$operation].kind == "finish" and
    .operations[$operation].rule_version == 2 and
    .operations[$operation].phase == "succeeded" and
    .operations[$operation].request_hash == $request_hash and
    .operations[$operation].request_body == $body
  ' "$results_dir/final-control-state.json" >/dev/null; then
    echo "compatible completion did not execute under the activated finish Rule" >&2
    exit 1
  fi
fi

jq -n --arg method "$method" --arg order_id "$order_id" \
  --arg source_invocation_id "$source_invocation_id" --arg source_created_at "$source_created_at" \
  --arg source_deployment_id "$v1_deployment_id" --arg target_deployment_id "$target_deployment_id" \
  --arg target_image "$target_image" --arg payment_token "$payment_token" \
  --argjson resume_exit "$resume_exit" --argjson terminal_observed "$terminal_observed" \
  --argjson final_status "$(cat "$results_dir/final-status.json")" \
  --argjson final_workflow "$(cat "$results_dir/final-workflow-state.json")" \
  --argjson payment "$(cat "$results_dir/final-payment-stats.json")" \
  --argjson completion "$(cat "$results_dir/final-completion-stats.json")" '{
    schema:1,cell:"compatible",method:$method,order_id:$order_id,
    source:{invocation_id:$source_invocation_id,created_at:$source_created_at,deployment_id:$source_deployment_id},
    target:{deployment_id:$target_deployment_id,image:$target_image},payment_token:$payment_token,
    resume_exit:$resume_exit,terminal_observed:($terminal_observed == 1),
    final:{status:$final_status,workflow:$final_workflow,payment:$payment,completion:$completion}
  }' >"$results_dir/observed.json"

cat "$results_dir/observed.json"
