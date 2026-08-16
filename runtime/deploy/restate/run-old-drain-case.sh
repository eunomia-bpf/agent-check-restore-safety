#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
case_name="${OLD_DRAIN_CASE:-}"
if [[ "$case_name" != h0 && "$case_name" != h1 ]]; then
  echo "OLD_DRAIN_CASE must be h0 or h1" >&2
  exit 64
fi
if [[ -z "${OLD_DRAIN_STATE_DIR:-}" ]]; then
  OLD_DRAIN_STATE_DIR="$(mktemp -d "/tmp/safe-change-old-drain-$case_name.XXXXXX")"
elif [[ -e "$OLD_DRAIN_STATE_DIR" ]]; then
  if [[ ! -d "$OLD_DRAIN_STATE_DIR" || -n "$(find "$OLD_DRAIN_STATE_DIR" -mindepth 1 -print -quit)" ]]; then
    echo "OLD_DRAIN_STATE_DIR must be absent or empty" >&2
    exit 64
  fi
else
  mkdir -p "$OLD_DRAIN_STATE_DIR"
fi
OLD_DRAIN_STATE_DIR="$(realpath "$OLD_DRAIN_STATE_DIR")"
results_dir="$OLD_DRAIN_STATE_DIR/results"
mkdir -p "$results_dir"
chmod 700 "$OLD_DRAIN_STATE_DIR" "$results_dir"

for command in cmp curl date docker find grep jq python3 realpath sed seq sha256sum sort tr wc; do
  command -v "$command" >/dev/null || {
    echo "required command not found: $command" >&2
    exit 1
  }
done

build_env="${HARNESS_BUILD_ENV:-$OLD_DRAIN_STATE_DIR/build.env}"
if [[ "${SKIP_BUILD:-0}" != 1 ]]; then
  "$script_dir/build.sh" "$build_env" >"$results_dir/build.log"
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
for required in NATIVE_ORDER_V1_IMAGE NATIVE_V1_CONTEXT_SHA256 \
  NATIVE_V1_COMPILED_SHA256 PROVIDER_DIRECT_PATCH_SHA256 SAFE_CHANGE_RUNTIME_IMAGE; do
  [[ -n "${!required:-}" ]] || {
    echo "build metadata omitted $required" >&2
    exit 1
  }
done
cp "$build_env" "$results_dir/build.env"
cp "$script_dir/versions.env" "$results_dir/versions.env"
cp "$script_dir/images.env" "$results_dir/images.env"
sha256sum "$script_dir/run-old-drain-case.sh" >"$results_dir/runner.sha256"

read -r ingress_port admin_port jaeger_port webui_port < <(python3 - <<'PY'
import socket
sockets=[]
try:
    for _ in range(4):
        item=socket.socket(); item.bind(("127.0.0.1",0)); sockets.append(item)
    print(*(item.getsockname()[1] for item in sockets))
finally:
    for item in sockets: item.close()
PY
)
RESTATE_INGRESS_PORT="${RESTATE_INGRESS_PORT:-$ingress_port}"
RESTATE_ADMIN_PORT="${RESTATE_ADMIN_PORT:-$admin_port}"
JAEGER_PORT="${JAEGER_PORT:-$jaeger_port}"
WEBUI_PORT="${WEBUI_PORT:-$webui_port}"
CONTROL_PORT="${CONTROL_PORT:-1}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-safe-change-old-drain-$case_name-$$}"
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
  if [[ "${KEEP_HARNESS:-0}" != 1 ]]; then
    "${compose_all[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
  fi
  echo "Restate old-drain $case_name evidence: $OLD_DRAIN_STATE_DIR" >&2
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

curl_args=(--fail --silent --show-error --connect-timeout 5 --max-time 120)
admin_url="http://127.0.0.1:$RESTATE_ADMIN_PORT"
ingress_url="http://127.0.0.1:$RESTATE_INGRESS_PORT"
network="${COMPOSE_PROJECT_NAME}_application"

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
  for _ in $(seq 1 120); do
    container="$("${compose_all[@]}" ps --quiet "$service")"
    if [[ -n "$container" ]]; then
      health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$container")"
      [[ "$health" == healthy ]] && return 0
    fi
    sleep 1
  done
  echo "timed out waiting for $service" >&2
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

provider_stats() {
  local service=$1 output=$2
  "${compose_all[@]}" exec -T "$service" wget -qO- -T 5 http://127.0.0.1:8081/v1/stats >"$output"
}

"${compose[@]}" config --quiet
"${compose_all[@]}" config >"$results_dir/compose-config.yaml"
"${compose[@]}" up --detach
wait_url "$admin_url/health"
wait_url "http://127.0.0.1:$WEBUI_PORT" 240
if [[ -n "$("${compose_all[@]}" ps --all --quiet control)" ]]; then
  echo "old-drain baseline unexpectedly started proposed control" >&2
  exit 1
fi

jq -n --arg uri http://order-v1:9080 --arg commit "$RESTATE_EXAMPLES_COMMIT" \
  '{uri:$uri,force:false,breaking:false,metadata:{variant:"native-v1",upstream_commit:$commit,method:"old-drain"}}' |
  curl "${curl_args[@]}" --request POST --header 'Content-Type: application/json' \
    --data-binary @- "$admin_url/deployments" >"$results_dir/deployment-v1.json"
jq -e '(.services | length) == 6 and (.id | type) == "string"' "$results_dir/deployment-v1.json" >/dev/null
deployment_id="$(jq -er .id "$results_dir/deployment-v1.json")"
curl "${curl_args[@]}" "$admin_url/deployments" >"$results_dir/deployments-at-cut.json"

order_id="${ORDER_ID:-old-drain-$case_name-$(date +%s)-$$}"
[[ "$order_id" =~ ^[A-Za-z0-9._-]{1,128}$ ]] || {
  echo "ORDER_ID contains unsupported characters" >&2
  exit 64
}
observation_seconds="${OLD_DRAIN_OBSERVATION_SECONDS:-20}"
if [[ ! "$observation_seconds" =~ ^[0-9]+$ || "$observation_seconds" -lt 5 || "$observation_seconds" -gt 120 ]]; then
  echo "OLD_DRAIN_OBSERVATION_SECONDS must be in [5,120]" >&2
  exit 64
fi
terminal_seconds="${OLD_DRAIN_TERMINAL_SECONDS:-120}"
if [[ ! "$terminal_seconds" =~ ^[0-9]+$ || "$terminal_seconds" -lt 20 || "$terminal_seconds" -gt 300 ]]; then
  echo "OLD_DRAIN_TERMINAL_SECONDS must be in [20,300]" >&2
  exit 64
fi
read -r runner_sha256 _ <"$results_dir/runner.sha256"
jq -n \
  --arg recorded_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg case "$case_name" --arg state_dir "$OLD_DRAIN_STATE_DIR" \
  --arg order_id "$order_id" --argjson observation_seconds "$observation_seconds" \
  --argjson terminal_seconds "$terminal_seconds" \
  --arg source_image "$NATIVE_ORDER_V1_IMAGE" \
  --arg restate_cli_image "$RESTATE_CLI_IMAGE" --arg restate_server_image "$RESTATE_SERVER_IMAGE" \
  --arg runner_sha256 "$runner_sha256" --arg build_env "$(realpath "$build_env")" \
  --argjson skip_build "${SKIP_BUILD:-0}" '{
    schema:1,recorded_at:$recorded_at,cell:"old-drain",system:"native-restate",
    case:$case,state_dir:$state_dir,order_id:$order_id,
    observation_seconds:$observation_seconds,terminal_seconds:$terminal_seconds,source_image:$source_image,
    restate_cli_image:$restate_cli_image,restate_server_image:$restate_server_image,
    runner_sha256:$runner_sha256,build_env:$build_env,skip_build:($skip_build == 1),
    effective_invocation:{
      OLD_DRAIN_CASE:$case,OLD_DRAIN_STATE_DIR:$state_dir,ORDER_ID:$order_id,
      OLD_DRAIN_OBSERVATION_SECONDS:$observation_seconds,OLD_DRAIN_TERMINAL_SECONDS:$terminal_seconds,
      SKIP_BUILD:$skip_build,
      HARNESS_BUILD_ENV:$build_env,script:"runtime/deploy/restate/run-old-drain-case.sh"
    }
  }' >"$results_dir/run-metadata.json"
jq -n --arg id "$order_id" '{
  id:$id,restaurantId:"restaurant-01",
  products:[{productId:"pizza-01",description:"Pizza",quantity:1}],
  totalCost:42,deliveryDelay:0
}' >"$results_dir/order.json"
sha256sum "$results_dir/order.json" >"$results_dir/order.sha256"
curl "${curl_args[@]}" --request POST --header 'Content-Type: application/json' \
  --data-binary "@$results_dir/order.json" \
  "$ingress_url/order-workflow/$order_id/run/send" >"$results_dir/source-submit.json"

lookup_sql="SELECT id,target,status,pinned_deployment_id,pinned_service_protocol_version,last_attempt_deployment_id,retry_count,next_retry_at,journal_size,created_at,modified_at FROM sys_invocation WHERE target_service_name = 'order-workflow' AND target_service_key = '$order_id' AND target_handler_name = 'run' ORDER BY id"
state_sql="SELECT service_name,service_key,key,value,value_utf8,value_length FROM state WHERE service_name = 'order-workflow' AND service_key = '$order_id' ORDER BY key"
fault_reached=0
for _ in $(seq 1 180); do
  provider_stats payment "$results_dir/payment-before-pause.json"
  raw_query "$lookup_sql" "$results_dir/status-before-pause.json"
  if jq -e --arg case "$case_name" '
      .deliveries == 1 and .paths == {"/v1/charge":1} and
      .commits == (if $case == "h0" then 0 else 1 end)
    ' "$results_dir/payment-before-pause.json" >/dev/null &&
    jq -e --arg deployment "$deployment_id" '
      (.rows | length) == 1 and .rows[0].status == "running" and
      .rows[0].pinned_deployment_id == $deployment and .rows[0].journal_size == 3
    ' "$results_dir/status-before-pause.json" >/dev/null; then
    fault_reached=1
    break
  fi
  sleep 1
done
if [[ $fault_reached -ne 1 ]]; then
  echo "old-drain did not reach the unknown-payment cut" >&2
  exit 1
fi
invocation_id="$(jq -er '.rows[0].id' "$results_dir/status-before-pause.json")"
created_at="$(jq -er '.rows[0].created_at' "$results_dir/status-before-pause.json")"
status_sql="SELECT id,target,status,pinned_deployment_id,pinned_service_protocol_version,last_attempt_deployment_id,retry_count,next_retry_at,journal_size,created_at,modified_at FROM sys_invocation WHERE id = '$invocation_id'"
journal_sql="SELECT index,version,entry_type,name,COALESCE(completed,false) AS completed,raw,raw_length,entry_lite_json FROM sys_journal WHERE id = '$invocation_id' ORDER BY index"

restate_cli --yes invocations pause "$invocation_id" \
  >"$results_dir/pause.stdout" 2>"$results_dir/pause.stderr"
source_before="$("${compose[@]}" ps --quiet order-v1)"
docker inspect "$source_before" >"$results_dir/source-before-crash.json"
docker logs "$source_before" >"$results_dir/source-before-crash.log" 2>&1
payment_token="$(sed -nE "s/.*\\[$order_id\\] Executing payment with token ([^ ]+) for.*/\\1/p" \
  "$results_dir/source-before-crash.log" | tail -n 1)"
[[ "$payment_token" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]] || {
  echo "old-drain source log omitted the stable payment token" >&2
  exit 1
}
docker kill "$source_before" >"$results_dir/source-crash.txt"
paused=0
for _ in $(seq 1 180); do
  raw_query "$status_sql" "$results_dir/paused-poll.json"
  if jq -e --arg id "$invocation_id" --arg deployment "$deployment_id" '
    (.rows | length) == 1 and .rows[0].id == $id and .rows[0].status == "paused" and
    .rows[0].pinned_deployment_id == $deployment and .rows[0].journal_size == 3
  ' "$results_dir/paused-poll.json" >/dev/null; then paused=1; break; fi
  sleep 1
done
[[ $paused -eq 1 ]] || { echo "old-drain invocation did not pause" >&2; exit 1; }

"${compose[@]}" up --detach --no-deps order-v1
wait_service_healthy order-v1
source_retained="$("${compose[@]}" ps --quiet order-v1)"
docker inspect "$source_retained" >"$results_dir/source-retained.json"
jq -e --arg image "$NATIVE_ORDER_V1_IMAGE" '
  length == 1 and .[0].Image == $image and .[0].State.Running == true
' "$results_dir/source-retained.json" >/dev/null
if [[ -n "$("${compose_all[@]}" ps --all --quiet order-v2)" ]]; then
  echo "old-drain unexpectedly created a target worker" >&2
  exit 1
fi

raw_query "$status_sql" "$results_dir/cut-status.json"
raw_query "$journal_sql" "$results_dir/cut-journal.json"
raw_query "$state_sql" "$results_dir/cut-workflow-state.json"
provider_stats payment "$results_dir/payment-at-cut.json"
provider_stats completion "$results_dir/completion-at-cut.json"
payment_container="$("${compose_all[@]}" ps --quiet payment)"
completion_container="$("${compose_all[@]}" ps --quiet completion)"
docker cp "$payment_container:/state/payment.history" "$results_dir/payment-at-cut.history"
docker cp "$completion_container:/state/completion.history" "$results_dir/completion-at-cut.history"

sleep "$observation_seconds"
raw_query "$status_sql" "$results_dir/paused-status-after-window.json"
raw_query "$journal_sql" "$results_dir/paused-journal-after-window.json"
raw_query "$state_sql" "$results_dir/paused-workflow-state-after-window.json"
provider_stats payment "$results_dir/payment-after-cut-window.json"
provider_stats completion "$results_dir/completion-after-cut-window.json"
docker cp "$payment_container:/state/payment.history" "$results_dir/payment-after-cut-window.history"
docker cp "$completion_container:/state/completion.history" "$results_dir/completion-after-cut-window.history"

cmp "$results_dir/cut-status.json" "$results_dir/paused-status-after-window.json"
cmp "$results_dir/cut-journal.json" "$results_dir/paused-journal-after-window.json"
cmp "$results_dir/cut-workflow-state.json" "$results_dir/paused-workflow-state-after-window.json"
cmp "$results_dir/payment-at-cut.json" "$results_dir/payment-after-cut-window.json"
cmp "$results_dir/completion-at-cut.json" "$results_dir/completion-after-cut-window.json"
cmp "$results_dir/payment-at-cut.history" "$results_dir/payment-after-cut-window.history"
cmp "$results_dir/completion-at-cut.history" "$results_dir/completion-after-cut-window.history"

# The deterministic cut provider holds every request.  Recreate only that
# external provider with both holds disabled, preserving its durable volume.
# This releases the fault identically for H0 and H1 without changing Restate,
# the invocation, the pinned deployment, the request, or the retained v1 code.
docker inspect "$payment_container" >"$results_dir/payment-held-container.json"
docker logs "$payment_container" >"$results_dir/payment-held.log" 2>&1
PAYMENT_HOLD_BEFORE_COMMIT=false PAYMENT_HOLD_AFTER_COMMIT=false \
  "${compose[@]}" up --detach --force-recreate --no-deps payment \
  >"$results_dir/payment-recreate.stdout" 2>"$results_dir/payment-recreate.stderr"
wait_service_healthy payment
payment_recovered_container="$("${compose_all[@]}" ps --quiet payment)"
[[ "$payment_recovered_container" != "$payment_container" ]] || {
  echo "old-drain payment provider was not recreated for recovery" >&2
  exit 1
}
docker inspect "$payment_recovered_container" >"$results_dir/payment-recovered-container.json"
jq -e '
  length == 1 and .[0].State.Running == true and
  (.[0].Config.Cmd | index("-hold-before-commit=false")) != null and
  (.[0].Config.Cmd | index("-hold-after-commit=false")) != null and
  (.[0].Config.Cmd | index("-non-idempotent=true")) != null
' "$results_dir/payment-recovered-container.json" >/dev/null
provider_stats payment "$results_dir/payment-after-recovery.json"
docker cp "$payment_recovered_container:/state/payment.history" "$results_dir/payment-after-recovery.history"
cmp "$results_dir/payment-at-cut.history" "$results_dir/payment-after-recovery.history"
jq -e --arg case "$case_name" '
  .deliveries == 0 and .paths == {} and
  .commits == (if $case == "h0" then 0 else 1 end)
' "$results_dir/payment-after-recovery.json" >/dev/null

# Keep the source deployment and its restarted v1 worker available, then use
# only Restate's official ingress and invocation-resume interfaces.  The two
# driver invocations are identical in H0 and H1 and let the official food-order
# workflow traverse its remaining preparation and delivery stages.
curl "${curl_args[@]}" --request POST --header 'Content-Type: application/json' --data '{}' \
  "$ingress_url/driver-mobile-app/driver-01/startDriver/send" >"$results_dir/driver-01.json"
curl "${curl_args[@]}" --request POST --header 'Content-Type: application/json' --data '{}' \
  "$ingress_url/driver-mobile-app/driver-02/startDriver/send" >"$results_dir/driver-02.json"
restate_cli --yes invocations resume "$invocation_id" \
  >"$results_dir/resume.stdout" 2>"$results_dir/resume.stderr"

terminal=0
for _ in $(seq 1 "$terminal_seconds"); do
  raw_query "$status_sql" "$results_dir/terminal-poll.json"
  if jq -e --arg id "$invocation_id" --arg created "$created_at" --arg deployment "$deployment_id" '
    (.rows | length) == 1 and .rows[0].id == $id and .rows[0].created_at == $created and
    .rows[0].status == "completed" and .rows[0].pinned_deployment_id == $deployment and
    .rows[0].journal_size == 27
  ' "$results_dir/terminal-poll.json" >/dev/null; then
    terminal=1
    break
  fi
  sleep 1
done

raw_query "$status_sql" "$results_dir/final-status.json"
raw_query "$lookup_sql" "$results_dir/final-invocations.json"
raw_query "$journal_sql" "$results_dir/final-journal.json"
raw_query "$state_sql" "$results_dir/final-workflow-state.json"
provider_stats payment "$results_dir/final-payment-stats.json"
provider_stats completion "$results_dir/final-completion-stats.json"
docker cp "$payment_recovered_container:/state/payment.history" "$results_dir/payment.history"
docker cp "$completion_container:/state/completion.history" "$results_dir/completion.history"
docker logs "$source_retained" >"$results_dir/final-source-retained.log" 2>&1
docker inspect "$source_retained" >"$results_dir/final-source-retained.json"
curl "${curl_args[@]}" "$admin_url/deployments" >"$results_dir/final-deployments.json"
mapfile -t containers < <(docker ps --all --quiet --filter "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME" | sort)
docker inspect "${containers[@]}" >"$results_dir/containers.raw.json"

cmp "$results_dir/final-status.json" "$results_dir/final-invocations.json"
cmp "$results_dir/deployments-at-cut.json" "$results_dir/final-deployments.json"
jq -e --arg id "$invocation_id" --arg created "$created_at" --arg deployment "$deployment_id" '
  (.rows | length) == 1 and .rows[0].id == $id and .rows[0].created_at == $created and
  (.rows[0].status == "running" or .rows[0].status == "completed") and
  .rows[0].pinned_deployment_id == $deployment and .rows[0].journal_size >= 3
' "$results_dir/final-status.json" >/dev/null
jq -e 'keys == ["rows"] and (.rows | type == "array") and length >= 0' \
  "$results_dir/final-journal.json" >/dev/null
jq -e 'keys == ["rows"] and (.rows | type == "array")' \
  "$results_dir/final-workflow-state.json" >/dev/null
jq -e '
  keys == ["commits","deliveries","paths"] and
  (.deliveries | type == "number") and .deliveries >= 1 and
  (.commits | type == "number") and .commits >= 1 and
  .paths == {"/v1/charge":.deliveries}
' "$results_dir/final-payment-stats.json" >/dev/null
jq -e '
  keys == ["commits","deliveries","paths"] and
  (.deliveries | type == "number") and (.commits | type == "number") and
  .deliveries >= .commits and .commits >= 0 and
  .paths == (if .deliveries == 0 then {} else {"/v1/complete":.deliveries} end)
' "$results_dir/final-completion-stats.json" >/dev/null
jq -e '(.deployments | length) == 1' "$results_dir/final-deployments.json" >/dev/null
[[ "$(wc -l <"$results_dir/payment.history")" -eq "$(jq -er .commits "$results_dir/final-payment-stats.json")" ]]
[[ "$(wc -l <"$results_dir/completion.history")" -eq "$(jq -er .commits "$results_dir/final-completion-stats.json")" ]]
if [[ -n "$("${compose_all[@]}" ps --all --quiet order-v2)" ]]; then
  echo "old-drain unexpectedly created a target worker" >&2
  exit 1
fi

final_status="$(jq -er '.rows[0].status' "$results_dir/final-status.json")"
final_business_status="$(jq -r '[.rows[] | select(.key == "status") | .value_utf8][0] // "null"' \
  "$results_dir/final-workflow-state.json" | tr -d '"')"
payment_total_commits="$(jq -er .commits "$results_dir/final-payment-stats.json")"
completion_total_commits="$(jq -er .commits "$results_dir/final-completion-stats.json")"
payment_log_count="$(grep -Fc -- \
  "[$order_id] Executing payment with token $payment_token for \$42" \
  "$results_dir/final-source-retained.log" || true)"
[[ "$payment_log_count" -ge 2 ]] || {
  echo "retained v1 did not re-enter the direct payment closure after resume" >&2
  exit 1
}

jq -n --arg case "$case_name" --arg order_id "$order_id" \
  --arg invocation_id "$invocation_id" --arg deployment_id "$deployment_id" \
  --arg payment_token "$payment_token" --arg status "$final_status" \
  --arg business_status "$final_business_status" \
  --argjson terminal_observed "$terminal" --argjson observation_seconds "$observation_seconds" \
  --argjson terminal_seconds "$terminal_seconds" \
  --argjson payment_log_count "$payment_log_count" \
  --argjson payment_total_commits "$payment_total_commits" \
  --argjson completion_total_commits "$completion_total_commits" \
  --argjson payment_at_cut "$(<"$results_dir/payment-at-cut.json")" \
  --argjson payment_after_recovery "$(<"$results_dir/final-payment-stats.json")" \
  --argjson completion "$(<"$results_dir/final-completion-stats.json")" '{
    schema:1,cell:"old-drain",system:"native-restate",case:$case,
    order_id:$order_id,invocation_id:$invocation_id,deployment_id:$deployment_id,
    payment_token:$payment_token,observation_seconds:$observation_seconds,
    terminal_seconds:$terminal_seconds,
    decision:"retain-v1",status:$status,business_status:$business_status,
    terminal_observed:($terminal_observed == 1),old_code_required:true,
    availability_preserved:($status == "completed"),v1_engaged:($payment_log_count >= 2),
    fault_release:"compose-recreate-preserve-volume",
    target_started:false,resubmitted:false,payment_at_cut:$payment_at_cut,
    payment_after_recovery:$payment_after_recovery,
    payment_total_deliveries:($payment_at_cut.deliveries + $payment_after_recovery.deliveries),
    payment_total_commits:$payment_total_commits,
    completion_total_deliveries:$completion.deliveries,
    completion_total_commits:$completion_total_commits,
    requirement_satisfied:($status == "completed" and $business_status == "DELIVERED" and
      $payment_total_commits == 1 and $completion_total_commits == 1),
    duplicate_external_effect:($payment_total_commits > 1),completion:$completion
  }' >"$results_dir/observed.json"
cat "$results_dir/observed.json"
