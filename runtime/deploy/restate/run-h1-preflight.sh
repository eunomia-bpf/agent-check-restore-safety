#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
preflight_case="${PREFLIGHT_CASE:-h1}"
if [[ "$preflight_case" != h0 && "$preflight_case" != h1 ]]; then
  echo "PREFLIGHT_CASE must be h0 or h1" >&2
  exit 1
fi
compose_file="$script_dir/compose.yaml"
if [[ -z "${H1_STATE_DIR:-}" ]]; then
  H1_STATE_DIR="$(mktemp -d "/tmp/safe-change-restate-$preflight_case.XXXXXX")"
fi
H1_STATE_DIR="$(realpath "$H1_STATE_DIR")"
results_dir="$H1_STATE_DIR/results"
mkdir -p "$results_dir"
chmod 700 "$H1_STATE_DIR" "$results_dir"

for command in awk cmp curl date docker go jq python3 realpath sed seq sha256sum sort tail tr wc; do
  command -v "$command" >/dev/null || {
    echo "required command not found: $command" >&2
    exit 1
  }
done

build_env="${HARNESS_BUILD_ENV:-$H1_STATE_DIR/build.env}"
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
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-safe-change-restate-$preflight_case-$$}"
if [[ "$preflight_case" == h0 ]]; then
  PAYMENT_HOLD_BEFORE_COMMIT=true
  PAYMENT_HOLD_AFTER_COMMIT=false
else
  PAYMENT_HOLD_BEFORE_COMMIT=false
  PAYMENT_HOLD_AFTER_COMMIT=true
fi
export RESTATE_INGRESS_PORT RESTATE_ADMIN_PORT CONTROL_PORT JAEGER_PORT WEBUI_PORT
export COMPOSE_PROJECT_NAME PAYMENT_HOLD_BEFORE_COMMIT PAYMENT_HOLD_AFTER_COMMIT

compose=(docker compose --project-name "$COMPOSE_PROJECT_NAME" --file "$compose_file")
compose_h1=(docker compose --project-name "$COMPOSE_PROJECT_NAME" --file "$compose_file" --profile h1)
compose_all=(docker compose --project-name "$COMPOSE_PROJECT_NAME" --file "$compose_file" --profile h1 --profile target)
cleanup() {
  local status=$?
  printf '%s\n' "$status" >"$results_dir/exit-status.txt"
  "${compose_all[@]}" ps --all >"$results_dir/compose-ps.txt" 2>&1 || true
  "${compose_all[@]}" logs --no-color >"$results_dir/compose.log" 2>&1 || true
  if [[ "${KEEP_HARNESS:-0}" != "1" ]]; then
    "${compose_all[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
  fi
  echo "Restate ${preflight_case^^} preflight evidence: $H1_STATE_DIR" >&2
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
application_network="${COMPOSE_PROJECT_NAME}_application"

"${compose[@]}" config --quiet
"${compose_all[@]}" config >"$results_dir/compose-config.yaml"
if [[ "$preflight_case" == h0 ]]; then
  "${compose[@]}" up --detach
else
  "${compose_h1[@]}" up --detach
fi
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

control_get() {
  local path=$1 output=$2
  curl -fsS --header "Authorization: Bearer $admin_token" \
    "$control_url$path" >"$output"
}

raw_query() {
  local query=$1 output=$2
  jq -n --arg query "$query" '{query:$query}' |
    curl -fsS --header 'Accept: application/json' \
      --header 'Content-Type: application/json' --data-binary @- \
      "$restate_admin_url/query" >"$output"
  jq -e 'keys == ["rows"] and (.rows | type == "array")' \
    "$output" >/dev/null
}

restate_cli() {
  docker run --rm --network "$application_network" \
    --env RESTATE_HOST=restate "$RESTATE_CLI_IMAGE" "$@"
}

register_deployment() {
  local variant=$1 uri=$2 output=$3
  jq -n --arg uri "$uri" --arg variant "$variant" --arg commit "$RESTATE_EXAMPLES_COMMIT" \
    '{uri:$uri,force:false,breaking:false,metadata:{variant:$variant,upstream_commit:$commit}}' |
    curl -fsS --request POST --header 'Content-Type: application/json' \
      --data-binary @- "$restate_admin_url/deployments" >"$output"
  jq -e '(.services | length) == 6 and .id != null' "$output" >/dev/null
}

provider_stats() {
  local service=$1 output=$2
  "${compose[@]}" exec -T control wget -qO- "http://$service:8081/v1/stats" >"$output"
}

wait_control_phase() {
  local kind=$1 phase=$2 output=$3
  for _ in $(seq 1 120); do
    control_get /v1/state "$output"
    if jq -e --arg kind "$kind" --arg phase "$phase" '
      ([.operations[] | select(.kind == $kind and .phase == $phase)] | length) == 1
    ' "$output" >/dev/null; then
      return 0
    fi
    sleep 1
  done
  echo "control Operation $kind did not reach $phase" >&2
  return 1
}

capture_project_containers() {
  local activation_sequence=$1
  local raw="$results_dir/containers.raw.json"
  local normalized="$results_dir/containers.json"
  local -a container_ids=()

  mapfile -t container_ids < <(
    docker ps --all --quiet \
      --filter "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME" | sort
  )
  if [[ ${#container_ids[@]} -eq 0 ]]; then
    echo "Compose project has no containers to inspect" >&2
    return 1
  fi
  docker inspect "${container_ids[@]}" >"$raw"
  jq -e --arg project "$COMPOSE_PROJECT_NAME" '
    type == "array" and length > 0 and
    all(.[];
      .Config.Labels["com.docker.compose.project"] == $project and
      ((.Config.Labels["com.docker.compose.service"] // "") | length) > 0
    )
  ' "$raw" >/dev/null

  if [[ "$preflight_case" == h0 ]]; then
    jq -e '
      ([.[] | select(
        .Config.Labels["com.docker.compose.service"] == "order-v1"
      )] | length) == 0 and
      ([.[] | select(
        .Config.Labels["com.docker.compose.service"] == "order-v2"
      )] | length) == 0
    ' "$raw" >/dev/null
  else
    jq -e --arg image "$ORDER_V2_IMAGE" '
      ([.[] | select(
        .Config.Labels["com.docker.compose.service"] == "order-v1"
      )] | length) == 0 and
      ([.[] | select(
        .Config.Labels["com.docker.compose.service"] == "order-v2" and
        .State.Running == true and .Image == $image
      )] | length) == 1 and
      ([.[] | select(
        .Config.Labels["com.docker.compose.service"] == "order-v2"
      )] | length) == 1
    ' "$raw" >/dev/null
  fi

  jq -S --argjson activation "$activation_sequence" '{
    schema:1,
    items:(
      [.[] |
        select(.State.Running == true) |
        (.Config.Labels["com.docker.compose.service"] // "") as $service |
        {
          role:(
            if $service == "order-v1" then "source-v1"
            elif $service == "order-v2" then "target-v2"
            else $service
            end
          ),
          name:(.Name | ltrimstr("/")),
          image_id:.Image,
          running:.State.Running,
          networks:((.NetworkSettings.Networks // {}) | keys | sort)
        } |
        if $service == "order-v2" then
          . + {started_after_history_sequence:$activation}
        else
          .
        end
      ] | sort_by(.role)
    )
  }' "$raw" >"$normalized"

  if [[ "$preflight_case" == h0 ]]; then
    jq -e '
      .schema == 1 and
      ([.items[] | select(.role == "restate")] | length) == 1 and
      ([.items[] | select(.role == "control")] | length) == 1 and
      ([.items[] | select(.role == "source-v1")] | length) == 0 and
      ([.items[] | select(.role == "target-v2")] | length) == 0 and
      all(.items[]; .running == true)
    ' "$normalized" >/dev/null
  else
    jq -e --arg image "$ORDER_V2_IMAGE" --argjson activation "$activation_sequence" '
      .schema == 1 and
      ([.items[] | select(.role == "restate")] | length) == 1 and
      ([.items[] | select(.role == "control")] | length) == 1 and
      ([.items[] | select(.role == "source-v1")] | length) == 0 and
      ([.items[] | select(
        .role == "target-v2" and .image_id == $image and
        .running == true and
        .started_after_history_sequence == $activation
      )] | length) == 1 and
      all(.items[]; .running == true)
    ' "$normalized" >/dev/null
  fi
}

register_deployment v1 http://order-v1:9080 "$results_dir/deployment-v1.json"
v1_deployment_id="$(jq -r '.id' "$results_dir/deployment-v1.json")"
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
jq -e -s '
  .[0].results == .[1].results and .[0].capacities == .[1].capacities
' "$results_dir/requirement-v1.json" "$results_dir/requirement-v2.json" >/dev/null

control_post /v1/compile "$results_dir/requirement-v1.json" "$results_dir/certificate-v1.json"
jq -e '
  .decision == "activate" and .rule != null and
  ((.rule.allow | sort) == ["charge-v1","finish"])
' "$results_dir/certificate-v1.json" >/dev/null
control_post /v1/certificate-state "$results_dir/certificate-v1.json" \
  "$results_dir/certificate-state-v1.json"
(
  cd "$script_dir/../.."
  go run ./cmd/check-certificate \
    -state "$results_dir/certificate-state-v1.json" \
    -certificate "$results_dir/certificate-v1.json"
) >"$results_dir/certificate-verdict-v1.json"
control_post /v1/activate "$results_dir/certificate-v1.json" "$results_dir/active-v1.json"

order_id="${ORDER_ID:-$preflight_case-order-$(date +%s)-$$}"
if [[ ! "$order_id" =~ ^[A-Za-z0-9._-]{1,128}$ ]]; then
  echo "ORDER_ID must contain only letters, digits, dot, underscore, or hyphen" >&2
  exit 1
fi
jq -n --arg id "$order_id" '{
  id:$id,restaurantId:"restaurant-01",
  products:[{productId:"pizza-01",description:"Pizza",quantity:1}],
  totalCost:42,deliveryDelay:0
}' >"$results_dir/order.json"
order_input_sha256="$(sha256sum "$results_dir/order.json" | awk '{print $1}')"
curl -fsS --request POST --header 'Content-Type: application/json' \
  --data-binary "@$results_dir/order.json" \
  "$restate_ingress_url/order-workflow/$order_id/run/send" \
  >"$results_dir/source-submit.json"

fault_reached=0
for _ in $(seq 1 180); do
  provider_stats payment "$results_dir/payment-at-commit.json"
  if [[ "$preflight_case" == h0 ]]; then
    if jq -e '
      .deliveries == 1 and .commits == 0 and .paths["/v1/charge"] == 1
    ' "$results_dir/payment-at-commit.json" >/dev/null; then
      fault_reached=1
      break
    fi
  else
    if jq -e '
      .deliveries == 1 and .commits == 1 and .paths["/v1/charge"] == 1
    ' "$results_dir/payment-at-commit.json" >/dev/null; then
      fault_reached=1
      break
    fi
  fi
  sleep 1
done
if [[ $fault_reached -ne 1 ]]; then
  echo "payment did not reach the injected $preflight_case hold" >&2
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
jq -e '(.rows | length) == 1 and .rows[0].status == "running"' \
  "$results_dir/source-running.json" >/dev/null
source_invocation_id="$(jq -r '.rows[0].id' "$results_dir/source-running.json")"

restate_cli --yes invocations pause "$source_invocation_id" \
  >"$results_dir/source-pause.txt" 2>"$results_dir/source-pause.stderr"
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
  echo "source invocation did not reach exact paused state" >&2
  exit 1
fi

source_container="$("${compose[@]}" ps --quiet order-v1)"
[[ -n "$source_container" ]]
if [[ ! "$source_container" =~ ^[0-9a-f]{64}$ ]]; then
  echo "Compose did not resolve source v1 to an exact container ID" >&2
  exit 1
fi
docker inspect "$source_container" >"$results_dir/source-container-before-kill.json"
docker kill "$source_container" >"$results_dir/source-container-kill.txt"
docker logs "$source_container" >"$results_dir/source-v1.log" 2>&1
payment_token="$(
  sed -nE "s/.*\\[$order_id\\] Executing payment with token ([^ ]+) for.*/\\1/p" \
    "$results_dir/source-v1.log" | tail -n 1
)"
if [[ ! "$payment_token" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]]; then
  echo "could not recover the workflow's stable payment token from v1 logs" >&2
  exit 1
fi
set +e
docker rm "$source_container" >"$results_dir/source-container-rm.txt" \
  2>"$results_dir/source-container-rm.stderr"
source_remove_exit_code=$?
set -e
if [[ $source_remove_exit_code -ne 0 ]]; then
  echo "source v1 container removal failed" >&2
  exit 1
fi
set +e
docker inspect "$source_container" >"$results_dir/source-container-after-rm.json" \
  2>"$results_dir/source-container-after-rm.stderr"
source_inspect_exit_code=$?
set -e
if [[ $source_inspect_exit_code -eq 0 ]]; then
  echo "source v1 container still exists after removal" >&2
  exit 1
fi

wait_control_phase charge-v1 unknown "$results_dir/control-unknown.json"
payment_operation_id="$(
  jq -r '.operations[] | select(.kind == "charge-v1" and .phase == "unknown") | .id' \
    "$results_dir/control-unknown.json"
)"
expected_payment_operation_id="op-$(
  printf 'operation-id-v1\0restate-order-workflow\0%s' "$payment_token" | sha256sum | awk '{print $1}'
)"
if [[ "$payment_operation_id" != "$expected_payment_operation_id" ]]; then
  echo "payment token does not derive the recorded Operation identity" >&2
  exit 1
fi

jq -n \
  --arg compose_service order-v1 \
  --arg container_id "$source_container" \
  --argjson remove_exit_code "$source_remove_exit_code" \
  --argjson inspect_exit_code "$source_inspect_exit_code" \
  --arg stderr "$(cat "$results_dir/source-container-after-rm.stderr")" \
  --argjson fenced_before_history_sequence "$(jq -r '.history.sequence' "$results_dir/control-unknown.json")" \
  '{schema:1,compose_service:$compose_service,container_id:$container_id,remove_exit_code:$remove_exit_code,inspect_exit_code:$inspect_exit_code,stderr:$stderr,fenced_before_history_sequence:$fenced_before_history_sequence}' \
  >"$results_dir/source-v1-removal.json"
jq -e --arg container "$source_container" '
  .compose_service == "order-v1" and .container_id == $container and
  .remove_exit_code == 0 and .inspect_exit_code != 0 and
  (.stderr | contains($container))
' "$results_dir/source-v1-removal.json" >/dev/null

source_status_sql="SELECT id,target,status,pinned_deployment_id,pinned_service_protocol_version,last_attempt_deployment_id,retry_count,next_retry_at,journal_size,created_at,modified_at FROM sys_invocation WHERE id = '$source_invocation_id'"
source_journal_sql="SELECT index,version,entry_type,name,COALESCE(completed,false) AS completed,raw,raw_length,entry_lite_json FROM sys_journal WHERE id = '$source_invocation_id' ORDER BY index"
source_workflow_state_sql="SELECT service_name,service_key,key,value,value_utf8,value_length FROM state WHERE service_name = 'order-workflow' AND service_key = '$order_id' ORDER BY key"
raw_query "$source_status_sql" "$results_dir/source-cut-status.json"
raw_query "$source_journal_sql" "$results_dir/source-cut-journal.json"
raw_query "$source_workflow_state_sql" "$results_dir/source-cut-workflow-state.json"
jq -e --arg invocation "$source_invocation_id" --arg deployment "$v1_deployment_id" '
  (.rows | length) == 1 and .rows[0].id == $invocation and
  .rows[0].status == "paused" and .rows[0].pinned_deployment_id == $deployment
' "$results_dir/source-cut-status.json" >/dev/null
jq -e '
  (.rows | length) >= 1 and
  ([.rows[] | select(.entry_type == "Command: Run" and .name == "payment")] | length) == 1 and
  .rows[-1].entry_type == "Command: Run" and .rows[-1].name == "payment" and
  .rows[-1].completed == false and
  ([.rows[] | select(.entry_type | startswith("Notification:"))] | length) == 0
' "$results_dir/source-cut-journal.json" >/dev/null

cut_next_retry_at="$(jq -r '.rows[0].next_retry_at // empty' "$results_dir/source-cut-status.json")"
if [[ -n "$cut_next_retry_at" ]]; then
  retry_epoch="$(date -d "$cut_next_retry_at" +%s)"
  while (( $(date +%s) <= retry_epoch )); do
    sleep 1
  done
else
  sleep 5
fi
raw_query "$source_status_sql" "$results_dir/source-cut-status-after-window.json"
raw_query "$source_journal_sql" "$results_dir/source-cut-journal-after-window.json"
raw_query "$source_workflow_state_sql" "$results_dir/source-cut-workflow-state-after-window.json"
jq -e -s '.[0] == .[1]' \
  "$results_dir/source-cut-status.json" \
  "$results_dir/source-cut-status-after-window.json" >/dev/null
jq -e -s '.[0] == .[1]' \
  "$results_dir/source-cut-journal.json" \
  "$results_dir/source-cut-journal-after-window.json" >/dev/null
jq -e -s '.[0] == .[1]' \
  "$results_dir/source-cut-workflow-state.json" \
  "$results_dir/source-cut-workflow-state-after-window.json" >/dev/null
jq -n --arg next_retry_at "$cut_next_retry_at" \
  --argjson observed_at_epoch "$(date +%s)" \
  '{stable:true,next_retry_at:($next_retry_at | if length == 0 then null else . end),observed_at_epoch:$observed_at_epoch}' \
  >"$results_dir/source-cut-stability.json"

if [[ "$preflight_case" == h0 ]]; then
  provider_stats payment "$results_dir/payment-before-query.json"
  jq -e '
    .deliveries == 1 and .commits == 0 and .paths["/v1/charge"] == 1
  ' "$results_dir/payment-before-query.json" >/dev/null
  control_get /v1/history "$results_dir/control-history-before-query.json"
  jq -S . "$results_dir/control-unknown.json" \
    >"$results_dir/control-state-before-query.normalized.json"
  jq -S . "$results_dir/control-history-before-query.json" \
    >"$results_dir/control-history-before-query.normalized.json"

  set +e
  recovery_http_status="$(
    curl -sS --output "$results_dir/payment-recovery.json" \
      --write-out '%{http_code}' --request POST \
      --header "Authorization: Bearer $admin_token" \
      "$control_url/v1/operations/$payment_operation_id/recover"
  )"
  recovery_curl_exit=$?
  set -e
  if [[ $recovery_curl_exit -ne 0 || "$recovery_http_status" != 409 ]]; then
    echo "H0 query recovery did not fail closed with HTTP 409" >&2
    exit 1
  fi
  printf '%s\n' "$recovery_http_status" \
    >"$results_dir/payment-recovery.http-status.txt"
  jq -e --arg operation "$payment_operation_id" '
    keys == ["error","outcome"] and
    .outcome == {
      operation_id:$operation,
      phase:"unknown",
      result_hash:"",
      reused:false,
      recovered_by_query:false
    } and
    .error == (
      "external operation outcome is unknown: query operation \"" +
      $operation + "\" was inconclusive"
    )
  ' "$results_dir/payment-recovery.json" >/dev/null

  control_get /v1/state "$results_dir/control-after-query.json"
  control_get /v1/history "$results_dir/control-history-after-query.json"
  jq -S . "$results_dir/control-after-query.json" \
    >"$results_dir/control-state-after-query.normalized.json"
  jq -S . "$results_dir/control-history-after-query.json" \
    >"$results_dir/control-history-after-query.normalized.json"
  cmp "$results_dir/control-state-before-query.normalized.json" \
    "$results_dir/control-state-after-query.normalized.json"
  cmp "$results_dir/control-history-before-query.normalized.json" \
    "$results_dir/control-history-after-query.normalized.json"
  provider_stats payment "$results_dir/payment-after-recovery.json"
  jq -e '
    .deliveries == 1 and .commits == 0 and .paths["/v1/charge"] == 1
  ' "$results_dir/payment-after-recovery.json" >/dev/null

  control_post /v1/compile "$results_dir/requirement-v2.json" \
    "$results_dir/certificate-v2.json"
  jq -e '
    .decision == "impossible" and .rule == null and .witness != null
  ' "$results_dir/certificate-v2.json" >/dev/null
  control_post /v1/certificate-state "$results_dir/certificate-v2.json" \
    "$results_dir/certificate-state-v2.json"
  (
    cd "$script_dir/../.."
    go run ./cmd/check-certificate \
      -state "$results_dir/certificate-state-v2.json" \
      -certificate "$results_dir/certificate-v2.json"
  ) >"$results_dir/certificate-verdict-v2.json"
  jq -e '.valid == true and .decision == "impossible"' \
    "$results_dir/certificate-verdict-v2.json" >/dev/null

  if [[ -n "$("${compose_all[@]}" ps --all --quiet order-v2)" ]]; then
    echo "H0 created a refused target v2 container" >&2
    exit 1
  fi
  jq -n '{present:false}' >"$results_dir/target-final.json"
  curl -fsS "$restate_admin_url/deployments" >"$results_dir/deployments.json"
  jq -e '
    (.deployments | length) == 1 and
    .deployments[0].uri == "http://order-v1:9080/"
  ' "$results_dir/deployments.json" >/dev/null
  curl -fsS "$restate_admin_url/services" >"$results_dir/services-final.json"
  jq -e --argjson expected "$expected_services" '
    ([.services[].name] | sort) == $expected and
    ([.services[].revision] | unique) == [1]
  ' "$results_dir/services-final.json" >/dev/null

  raw_query "SELECT id,target,status FROM sys_invocation WHERE target_service_name IN ('driver-mobile-app','driver-digital-twin','driver-delivery-matcher','delivery-manager') ORDER BY id" \
    "$results_dir/driver-invocations.json"
  jq -e '.rows == []' "$results_dir/driver-invocations.json" >/dev/null
  provider_stats completion "$results_dir/final-completion-stats.json"
  jq -e '.deliveries == 0 and .commits == 0 and .paths == {}' \
    "$results_dir/final-completion-stats.json" >/dev/null
  raw_query "$source_status_sql" "$results_dir/source-final-status.json"
  jq -e --arg invocation "$source_invocation_id" '
    (.rows | length) == 1 and .rows[0].id == $invocation and
    .rows[0].status == "paused"
  ' "$results_dir/source-final-status.json" >/dev/null
  raw_query "$source_lookup_sql" \
    "$results_dir/source-final-whole-key-invocations.json"
  jq -e -s \
    --arg invocation "$source_invocation_id" \
    --arg deployment "$v1_deployment_id" \
    --arg target "order-workflow/$order_id/run" '
      (.[0].rows | length) == 1 and
      .[0].rows[0] == .[1].rows[0] and
      .[0].rows[0].id == $invocation and
      .[0].rows[0].target == $target and
      .[0].rows[0].status == "paused" and
      .[0].rows[0].pinned_deployment_id == $deployment and
      (.[0].rows[0].pinned_service_protocol_version | type) == "number" and
      (.[0].rows[0].journal_size | type) == "number"
    ' "$results_dir/source-final-whole-key-invocations.json" \
      "$results_dir/source-cut-status.json" >/dev/null
  source_inbox_sql="SELECT service_name,service_key,id,sequence_number,created_at FROM sys_inbox WHERE service_name = 'order-workflow' AND service_key = '$order_id' ORDER BY sequence_number,id"
  raw_query "$source_inbox_sql" "$results_dir/source-final-inbox.json"
  jq -e '.rows == []' "$results_dir/source-final-inbox.json" >/dev/null
  control_get /v1/state "$results_dir/final-control-state.json"
  jq -e --arg operation "$payment_operation_id" '
    .requirement.id == "food-ordering-v1" and
    ([.operations[] | select(
      .id == $operation and .kind == "charge-v1" and .phase == "unknown"
    )] | length) == 1 and
    ([.operations[] | select(.kind == "finish")] | length) == 0
  ' "$results_dir/final-control-state.json" >/dev/null
  control_get /v1/history "$results_dir/final-control-history.json"

  capture_project_containers 0

  control_container="$("${compose_all[@]}" ps --quiet control)"
  payment_container="$("${compose_all[@]}" ps --quiet payment)"
  completion_container="$("${compose_all[@]}" ps --quiet completion)"
  docker cp "$control_container:/state/runtime.history" "$results_dir/runtime.history"
  docker cp "$control_container:/anchor/runtime.head" "$results_dir/runtime.head"
  docker cp "$payment_container:/state/payment.history" "$results_dir/payment.history"
  docker cp "$completion_container:/state/completion.history" "$results_dir/completion.history"
  [[ "$(wc -c <"$results_dir/payment.history")" -eq 0 ]]
  [[ "$(wc -c <"$results_dir/completion.history")" -eq 0 ]]

  jq -n \
    --arg upstream_commit "$RESTATE_EXAMPLES_COMMIT" \
    --arg upstream_archive_sha256 "$UPSTREAM_ARCHIVE_SHA256" \
    --arg restate_image "$RESTATE_SERVER_IMAGE" \
    --arg order_id "$order_id" \
    --arg order_input_sha256 "$order_input_sha256" \
    --arg payment_token "$payment_token" \
    --arg payment_operation_id "$payment_operation_id" \
    --arg source_invocation_id "$source_invocation_id" \
    --arg source_created_at "$(jq -r '.rows[0].created_at' "$results_dir/source-cut-status.json")" \
    --arg v1_deployment_id "$v1_deployment_id" \
    --arg v1_image "$ORDER_V1_IMAGE" \
    --arg planned_v2_image "$ORDER_V2_IMAGE" \
    --arg recovery_http_status "$recovery_http_status" \
    --argjson cut_status "$(cat "$results_dir/source-cut-status.json")" \
    --argjson cut_journal "$(cat "$results_dir/source-cut-journal.json")" \
    --argjson cut_workflow_state "$(cat "$results_dir/source-cut-workflow-state.json")" \
    --argjson recovery "$(cat "$results_dir/payment-recovery.json")" \
    --argjson certificate "$(cat "$results_dir/certificate-v2.json")" \
    --argjson payment "$(cat "$results_dir/payment-after-recovery.json")" \
    --argjson completion "$(cat "$results_dir/final-completion-stats.json")" '{
      case:"h0",
      upstream:{commit:$upstream_commit,archive_sha256:$upstream_archive_sha256},
      restate:{image:$restate_image},
      order:{id:$order_id,input_sha256:$order_input_sha256,status:"CREATED"},
      payment:{
        token:$payment_token,operation_id:$payment_operation_id,
        provider:$payment,
        recovery:{http_status:($recovery_http_status | tonumber),body:$recovery}
      },
      source:{
        invocation_id:$source_invocation_id,created_at:$source_created_at,
        deployment_id:$v1_deployment_id,image_id:$v1_image,
        cut_status:$cut_status,cut_journal:$cut_journal,
        cut_workflow_state:$cut_workflow_state,
        fenced_and_removed:true,final_status:"paused"
      },
      target:{
        planned_image_id:$planned_v2_image,certificate:$certificate,
        container_present:false,deployment_present:false,
        drivers_started:false,completion_started:false,
        continuation_started:false
      },
      providers:{payment:$payment,completion:$completion},
      invariants:{
        source_paused_with_incomplete_payment_run:true,
        source_cut_stable_after_retry_window:true,
        query_recovery_inconclusive:true,
        query_recovery_changed_operation:false,
        target_decision_impossible:true,
        target_side_activity_absent:true
      }
    }' >"$results_dir/summary.json"

  cat "$results_dir/summary.json"
  exit 0
fi

curl -fsS --request POST --header "Authorization: Bearer $admin_token" \
  "$control_url/v1/operations/$payment_operation_id/recover" \
  >"$results_dir/payment-recovery.json"
jq -e --arg operation "$payment_operation_id" '
  .operation_id == $operation and .phase == "succeeded" and
  .recovered_by_query == true and .reused == false
' "$results_dir/payment-recovery.json" >/dev/null
wait_control_phase charge-v1 succeeded "$results_dir/control-recovered.json"
jq -e --arg operation "$payment_operation_id" '
  ([.operations[] | select(
    .id == $operation and .phase == "succeeded" and .settlement == "query"
  )] | length) == 1
' "$results_dir/control-recovered.json" >/dev/null
provider_stats payment "$results_dir/payment-after-recovery.json"
jq -e '
  .deliveries == 1 and .commits == 1 and .paths["/v1/charge"] == 1
' "$results_dir/payment-after-recovery.json" >/dev/null

control_post /v1/compile "$results_dir/requirement-v2.json" "$results_dir/certificate-v2.json"
jq -e '
  .decision == "activate" and .rule != null and .rule.allow == ["finish"]
' "$results_dir/certificate-v2.json" >/dev/null
control_post /v1/certificate-state "$results_dir/certificate-v2.json" \
  "$results_dir/certificate-state-v2.json"
(
  cd "$script_dir/../.."
  go run ./cmd/check-certificate \
    -state "$results_dir/certificate-state-v2.json" \
    -certificate "$results_dir/certificate-v2.json"
) >"$results_dir/certificate-verdict-v2.json"
if [[ -n "$("${compose_all[@]}" ps --quiet order-v2)" ]]; then
  echo "target worker was running before target Rule activation" >&2
  exit 1
fi
jq -n '{present:false}' >"$results_dir/target-before-activation.json"
control_post /v1/activate "$results_dir/certificate-v2.json" "$results_dir/active-v2.json"
activation_sequence="$(jq -r '.history.sequence' "$results_dir/active-v2.json")"

jq -e --arg container "$source_container" --argjson activation "$activation_sequence" '
  .compose_service == "order-v1" and .container_id == $container and
  .remove_exit_code == 0 and .inspect_exit_code != 0 and
  (.stderr | contains($container)) and
  .fenced_before_history_sequence <= $activation
' "$results_dir/source-v1-removal.json" >/dev/null

"${compose_all[@]}" up --detach --no-deps order-v2
wait_service_healthy order-v2
target_container="$("${compose_all[@]}" ps --quiet order-v2)"
jq -n \
  --arg container "$target_container" \
  --arg started_at "$(docker inspect --format '{{.State.StartedAt}}' "$target_container")" \
  --argjson started_after_history_sequence "$activation_sequence" \
  '{container:$container,started_at:$started_at,started_after_history_sequence:$started_after_history_sequence}' \
  >"$results_dir/target-start-order.json"
register_deployment v2 http://order-v2:9080 "$results_dir/deployment-v2.json"
v2_deployment_id="$(jq -r '.id' "$results_dir/deployment-v2.json")"
curl -fsS "$restate_admin_url/deployments" >"$results_dir/deployments.json"
jq -e '
  ([.deployments[].uri] | sort) == ["http://order-v1:9080/","http://order-v2:9080/"]
' "$results_dir/deployments.json" >/dev/null

restate_cli --yes invocations kill "$source_invocation_id" \
  >"$results_dir/source-invocation-kill.txt" 2>"$results_dir/source-invocation-kill.stderr"
source_completed=0
for _ in $(seq 1 120); do
  raw_query "$source_status_sql" "$results_dir/source-after-kill.json"
  if jq -e '
    (.rows | length) == 1 and .rows[0].status == "completed"
  ' "$results_dir/source-after-kill.json" >/dev/null; then
    source_completed=1
    break
  fi
  sleep 1
done
if [[ $source_completed -ne 1 ]]; then
  echo "source invocation did not become completed after hard kill" >&2
  exit 1
fi
restate_cli --yes invocations purge "$source_invocation_id" \
  >"$results_dir/source-invocation-purge.txt" 2>"$results_dir/source-invocation-purge.stderr"
source_absent=0
for _ in $(seq 1 120); do
  raw_query "$source_status_sql" "$results_dir/source-after-purge.json"
  if jq -e '.rows == []' "$results_dir/source-after-purge.json" >/dev/null; then
    source_absent=1
    break
  fi
  sleep 1
done
if [[ $source_absent -ne 1 ]]; then
  echo "source invocation was not purged" >&2
  exit 1
fi

# Do not create target-side driver state until v2 is registered and the source
# invocation is gone. This keeps every business action after the edit on the
# target deployment rather than relying on a v1-pinned virtual object.
for driver in driver-01 driver-02; do
  curl -fsS --request POST --header 'Content-Type: application/json' --data '{}' \
    "$restate_ingress_url/driver-mobile-app/$driver/startDriver/send" \
    >"$results_dir/$driver.json"
done

# Re-enter through v2 with the exact same workflow key and exact same input
# bytes. This is a new Restate generation of the same business order, not a
# different order used to borrow the old payment result.
curl -fsS --request POST --header 'Content-Type: application/json' \
  --data-binary "@$results_dir/order.json" \
  "$restate_ingress_url/order-workflow/$order_id/run/send" \
  >"$results_dir/continuation-submit.json"

delivered=0
for _ in $(seq 1 300); do
  status="$(
    curl -fsS --request POST --header 'Content-Type: application/json' --data '{}' \
      "$restate_ingress_url/order-workflow/$order_id/getStatus" 2>/dev/null || true
  )"
  printf '%s\n' "$status" >"$results_dir/continuation-order-status.json"
  if [[ "$status" == '"DELIVERED"' ]]; then
    delivered=1
    break
  fi
  sleep 1
done
if [[ $delivered -ne 1 ]]; then
  echo "same business order did not complete through v2" >&2
  exit 1
fi

raw_query "$source_lookup_sql" "$results_dir/continuation-invocation.json"
jq -e --arg deployment "$v2_deployment_id" '
  (.rows | length) == 1 and .rows[0].status == "completed" and
  .rows[0].pinned_deployment_id == $deployment
' "$results_dir/continuation-invocation.json" >/dev/null
source_created_at="$(jq -r '.rows[0].created_at' "$results_dir/source-cut-status.json")"
continuation_created_at="$(jq -r '.rows[0].created_at' "$results_dir/continuation-invocation.json")"
if [[ "$source_created_at" == "$continuation_created_at" ]]; then
  echo "same-key continuation did not create a new Restate generation" >&2
  exit 1
fi
continuation_invocation_id="$(jq -r '.rows[0].id' "$results_dir/continuation-invocation.json")"
continuation_journal_sql="SELECT index,version,entry_type,name,COALESCE(completed,false) AS completed,raw,raw_length,entry_lite_json FROM sys_journal WHERE id = '$continuation_invocation_id' ORDER BY index"
raw_query "$continuation_journal_sql" "$results_dir/continuation-journal.json"
jq -e '
  ([.rows[] | select(.entry_type == "Command: Run" and .name == "payment")] | length) == 0 and
  ([.rows[] | select(.entry_type == "Command: Run" and .name == "completion") |
    (.entry_lite_json | fromjson).Command.Run.completion_id] | first) as $completion_id |
  ($completion_id | type) == "number" and
  ([.rows[] | select(.entry_type == "Notification: Run") |
    (.entry_lite_json | fromjson) |
    select(.Notification.id.CompletionId == $completion_id)] | length) == 1
' "$results_dir/continuation-journal.json" >/dev/null

control_get /v1/state "$results_dir/final-control-state.json"
control_get /v1/history "$results_dir/final-control-history.json"
completion_operation_id="op-$(
  printf 'operation-id-v1\0restate-order-workflow\0order/%s/completion' "$order_id" |
    sha256sum | awk '{print $1}'
)"
jq -e --arg payment "$payment_operation_id" --arg completion "$completion_operation_id" '
  ([.operations[] | select(
    .id == $payment and .kind == "charge-v1" and
    .phase == "succeeded" and .settlement == "query"
  )] | length) == 1 and
  ([.operations[] | select(
    .id == $completion and .kind == "finish" and .phase == "succeeded"
  )] | length) == 1
' "$results_dir/final-control-state.json" >/dev/null
provider_stats payment "$results_dir/final-payment-stats.json"
provider_stats completion "$results_dir/final-completion-stats.json"
jq -e '
  .deliveries == 1 and .commits == 1 and .paths["/v1/charge"] == 1
' "$results_dir/final-payment-stats.json" >/dev/null
jq -e '
  .deliveries == 1 and .commits == 1 and .paths["/v1/complete"] == 1
' "$results_dir/final-completion-stats.json" >/dev/null

# An isolated control condition deliberately retries the same external request
# without History or query recovery. The independent non-idempotent provider
# must commit twice, demonstrating that the headline provider's 1/1 result was
# not supplied by provider idempotency.
naive_operation_id="op-$(
  printf 'naive-retry-control-v1\0%s' "$order_id" | sha256sum | awk '{print $1}'
)"
jq -nc --arg order_id "$order_id" '{order_id:$order_id,amount:42}' \
  >"$results_dir/naive-payment-body.json"
for attempt in 1 2; do
  "${compose[@]}" exec -T control wget -qO- \
    --header="X-Operation-ID: $naive_operation_id" \
    --header="Idempotency-Key: $naive_operation_id" \
    --header='Content-Type: application/json' \
    --post-file=/dev/stdin http://naive-payment:8081/v1/charge \
    <"$results_dir/naive-payment-body.json" \
    >"$results_dir/naive-payment-response-$attempt.json"
done
provider_stats naive-payment "$results_dir/naive-payment-stats.json"
jq -e '
  .deliveries == 2 and .commits == 2 and .paths["/v1/charge"] == 2
' "$results_dir/naive-payment-stats.json" >/dev/null

control_container="$("${compose_all[@]}" ps --quiet control)"
payment_container="$("${compose_all[@]}" ps --quiet payment)"
completion_container="$("${compose_all[@]}" ps --quiet completion)"
naive_payment_container="$("${compose_all[@]}" ps --quiet naive-payment)"
docker cp "$control_container:/state/runtime.history" "$results_dir/runtime.history"
docker cp "$control_container:/anchor/runtime.head" "$results_dir/runtime.head"
docker cp "$payment_container:/state/payment.history" "$results_dir/payment.history"
docker cp "$completion_container:/state/completion.history" "$results_dir/completion.history"
docker cp "$naive_payment_container:/state/naive-payment.history" "$results_dir/naive-payment.history"
[[ "$(wc -l <"$results_dir/payment.history")" -eq 1 ]]
[[ "$(wc -l <"$results_dir/completion.history")" -eq 1 ]]
[[ "$(wc -l <"$results_dir/naive-payment.history")" -eq 2 ]]

curl -fsS "$restate_admin_url/services" >"$results_dir/services-v2.json"
jq -e --argjson expected "$expected_services" \
  '([.services[].name] | sort) == $expected' "$results_dir/services-v2.json" >/dev/null
docker inspect "$target_container" >"$results_dir/target-container.json"
capture_project_containers "$activation_sequence"

jq -n \
  --arg upstream_commit "$RESTATE_EXAMPLES_COMMIT" \
  --arg upstream_archive_sha256 "$UPSTREAM_ARCHIVE_SHA256" \
  --arg restate_image "$RESTATE_SERVER_IMAGE" \
  --arg order_id "$order_id" \
  --arg order_input_sha256 "$order_input_sha256" \
  --arg payment_token "$payment_token" \
  --arg payment_operation_id "$payment_operation_id" \
  --arg naive_operation_id "$naive_operation_id" \
  --arg source_invocation_id "$source_invocation_id" \
  --arg continuation_invocation_id "$continuation_invocation_id" \
  --arg source_created_at "$source_created_at" \
  --arg continuation_created_at "$continuation_created_at" \
  --arg v1_deployment_id "$v1_deployment_id" \
  --arg v2_deployment_id "$v2_deployment_id" \
  --arg v1_image "$ORDER_V1_IMAGE" \
  --arg v2_image "$ORDER_V2_IMAGE" \
  --argjson cut_status "$(cat "$results_dir/source-cut-status.json")" \
  --argjson cut_journal "$(cat "$results_dir/source-cut-journal.json")" \
  --argjson recovery "$(cat "$results_dir/payment-recovery.json")" \
  --argjson activation "$(cat "$results_dir/active-v2.json")" \
  --argjson continuation "$(cat "$results_dir/continuation-invocation.json")" \
  --argjson payment "$(cat "$results_dir/final-payment-stats.json")" \
  --argjson completion "$(cat "$results_dir/final-completion-stats.json")" '{
    upstream:{commit:$upstream_commit,archive_sha256:$upstream_archive_sha256},
    restate:{image:$restate_image},
    order:{
      id:$order_id,input_sha256:$order_input_sha256,
      same_business_id:true,same_input_bytes:true,status:"DELIVERED"
    },
    payment:{
      token:$payment_token,operation_id:$payment_operation_id,
      provider:$payment,recovery:$recovery
    },
    source:{
      invocation_id:$source_invocation_id,created_at:$source_created_at,
      deployment_id:$v1_deployment_id,image_id:$v1_image,
      cut_status:$cut_status,cut_journal:$cut_journal,
      fenced_and_removed:true,purged:true
    },
    target:{
      invocation_id:$continuation_invocation_id,created_at:$continuation_created_at,
      same_restate_invocation_id:($source_invocation_id == $continuation_invocation_id),
      new_generation:($source_created_at != $continuation_created_at),
      deployment_id:$v2_deployment_id,image_id:$v2_image,
      activated_before_start:true,activation:$activation,
      invocation:$continuation,completion_provider:$completion
    },
    invariants:{
      source_paused_with_incomplete_payment_run:true,
      source_cut_stable_after_retry_window:true,
      payment_query_settled:true,
      payment_redispatched:false,
      target_contains_no_payment_run:true,
      target_completed_same_business_order:true
    },
    naive_retry_control:{
      isolated_provider:true,operation_id:$naive_operation_id,
      deliveries:2,commits:2
    }
  }' >"$results_dir/summary.json"

cat "$results_dir/summary.json"
