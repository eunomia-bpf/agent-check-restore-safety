#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
case_name="${OLD_DRAIN_CASE:-}"
if [[ "$case_name" != h0 && "$case_name" != h1 ]]; then
  echo "OLD_DRAIN_CASE must be h0 or h1" >&2
  exit 64
fi
if [[ "${SKIP_BUILD:-0}" != 1 || -z "${HARNESS_BUILD_ENV:-}" || ! -f "$HARNESS_BUILD_ENV" ]]; then
  echo "old-drain requires SKIP_BUILD=1 and an existing HARNESS_BUILD_ENV" >&2
  exit 64
fi

for command in cmp curl date docker find git jq realpath seq sha256sum sort timeout; do
  command -v "$command" >/dev/null || {
    echo "required command not found: $command" >&2
    exit 1
  }
done

if [[ -n "${TEMPORAL_OLD_DRAIN_STATE_ROOT:-}" ]]; then
  case_root="$(realpath -m "$TEMPORAL_OLD_DRAIN_STATE_ROOT")"
  if [[ -d "$case_root" && -n "$(find "$case_root" -mindepth 1 -print -quit)" ]]; then
    echo "TEMPORAL_OLD_DRAIN_STATE_ROOT must be absent or empty" >&2
    exit 64
  fi
  mkdir -p "$case_root"
else
  case_root="$(mktemp -d "/tmp/safe-change-temporal-old-drain-${case_name}.XXXXXX")"
fi
results_dir="$case_root/results"
temporal_state_dir="$case_root/temporal"
payment_state_dir="$case_root/payment"
completion_state_dir="$case_root/completion"
mkdir -p "$results_dir" "$temporal_state_dir" "$payment_state_dir" "$completion_state_dir"
chmod 700 "$case_root" "$results_dir" "$temporal_state_dir" "$payment_state_dir" "$completion_state_dir"

build_env="$(realpath "$HARNESS_BUILD_ENV")"
cp "$build_env" "$results_dir/build.env"
cp "$script_dir/versions.env" "$results_dir/versions.env"
cp "$script_dir/old-drain.env" "$results_dir/old-drain.env"
cp "$script_dir/run-old-drain-case.sh" "$results_dir/runner.sh"
cp "$script_dir/compose.yaml" "$results_dir/base-compose.yaml"
cp "$script_dir/compose-old-drain.yaml" "$results_dir/compose-old-drain.yaml"
cp "$script_dir/app/internal/workerapp/variant_v1.go" "$results_dir/source-variant-v1.go"
cp "$script_dir/app/internal/workerapp/activities.go" "$results_dir/source-activities.go"
cp "$script_dir/app/internal/workerapp/workflows.go" "$results_dir/source-workflows.go"
cp "$script_dir/app/internal/harness/types.go" "$results_dir/source-types.go"
cp "$script_dir/app/cmd/starter/main.go" "$results_dir/source-starter.go"

set -a
# shellcheck source=versions.env
source "$script_dir/versions.env"
# shellcheck source=old-drain.env
source "$script_dir/old-drain.env"
# shellcheck source=/dev/null
source "$build_env"
TEMPORAL_STATE_DIR="$temporal_state_dir"
PAYMENT_STATE_DIR="$payment_state_dir"
COMPLETION_STATE_DIR="$completion_state_dir"
PAYMENT_HOLD_BEFORE_COMMIT=false
PAYMENT_HOLD_AFTER_COMMIT=false
DEMO_UID="$(id -u)"
DEMO_GID="$(id -g)"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-safe-change-temporal-old-drain-${case_name}-$$}"
set +a

if [[ "$SOURCE_SHA256" != 877a7a5b71b24e3dc309af5cd23bebe77c40dab6b8aec659ef929f1dc771aade ||
      "$RUNTIME_SOURCE_SHA256" != e95760a49a36fa0dbf8136589545b5499a99e353baabae44c6c11e37ed581059 ||
      "$WORKER_V1_ID" != sha256:8a236550df67fe5cd334fd05bd092ff6457daf80ba7fd0077f1a98a6bdcd919f ||
      "$WORKER_V1_BINARY_SHA256" != 98a12265e86a04c3cf384ab36c05f55973f1751914c66d51c89da5b1cd1deac3 ||
      "$STARTER_ID" != sha256:a754ee9e7301a3c22d36ac93175efae634f9224f5e2a9032b22632f6793b2feb ||
      "$EFFECTS_ID" != sha256:7c81b969bae3fd7372a91620854974834b27d58d9ec9f3887e90d9a553746b7f ]]; then
  echo "HARNESS_BUILD_ENV is not the frozen compatible build" >&2
  exit 64
fi

compose=(
  docker compose --project-name "$COMPOSE_PROJECT_NAME"
  --file "$script_dir/compose.yaml"
  --file "$script_dir/compose-old-drain.yaml"
)
docker_events_pid=""
stop_docker_events() {
  if [[ -n "$docker_events_pid" ]]; then
    kill -TERM "$docker_events_pid" >/dev/null 2>&1 || true
    wait "$docker_events_pid" >/dev/null 2>&1 || true
    docker_events_pid=""
  fi
}
cleanup() {
  local status=$?
  stop_docker_events
  printf '%s\n' "$status" >"$results_dir/exit-status.txt"
  "${compose[@]}" ps --all >"$results_dir/compose-ps.txt" 2>&1 || true
  "${compose[@]}" logs --no-color >"$results_dir/compose.log" 2>&1 || true
  (
    cd "$results_dir"
    while IFS= read -r -d '' artifact; do
      sha256sum "$artifact"
    done < <(find . -maxdepth 1 -type f ! -name SHA256SUMS -print0 | sort -z)
  ) >"$results_dir/SHA256SUMS" 2>/dev/null || true
  if [[ "${KEEP_HARNESS:-0}" != 1 ]]; then
    "${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
  fi
  echo "Temporal old-drain $case_name evidence: $case_root" >&2
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

temporal_json() {
  local output=$1
  shift
  "${compose[@]}" exec -T temporal temporal "$@" \
    --output json --time-format iso >"$output"
}

wait_poller() {
  local queue_type=$1 output=$2
  for _ in $(seq 1 90); do
    if temporal_json "$output" task-queue describe \
      --task-queue safe-change-food-orders \
      --legacy-mode --task-queue-type-legacy "$queue_type" 2>/dev/null &&
      jq -e '
        ([.pollers[]? | select(
          .identity == "safe-change-food-order-v1-worker" and
          .worker_version_capabilities.build_id == "food-order-v1" and
          .worker_version_capabilities.use_versioning == true and
          .deployment_options.deployment_name == "safe-change-food-order-worker" and
          .deployment_options.build_id == "food-order-v1"
        )] | length) == 1
      ' "$output" >/dev/null; then
      return 0
    fi
    sleep 1
  done
  echo "timed out waiting for v1 $queue_type poller" >&2
  return 1
}

provider_stats() {
  local service=$1 output=$2
  timeout 15 "${compose[@]}" exec -T "$service" \
    wget -T 5 -qO- http://127.0.0.1:8081/v1/stats >"$output"
}

workflow_show() {
  temporal_json "$1" workflow show --workflow-id "$workflow_id" --run-id "$run_id"
}

workflow_describe() {
  temporal_json "$1" workflow describe --workflow-id "$workflow_id" --run-id "$run_id" --raw
}

workflow_query() {
  temporal_json "$1" workflow query \
    --workflow-id "$workflow_id" --run-id "$run_id" --type status
}

signal_business_stages() {
  local identity=$1
  temporal_json "$results_dir/signal-preparation-finished.json" workflow signal \
    --workflow-id "$workflow_id" --run-id "$run_id" \
    --name preparation_finished --identity "$identity"
  temporal_json "$results_dir/signal-driver-selected.json" workflow signal \
    --workflow-id "$workflow_id" --run-id "$run_id" \
    --name driver_selected --identity "$identity" \
    --input '{"delivery_id":"delivery-order-1","driver_id":"driver-1"}'
  temporal_json "$results_dir/signal-driver-at-restaurant.json" workflow signal \
    --workflow-id "$workflow_id" --run-id "$run_id" \
    --name driver_at_restaurant --identity "$identity"
  temporal_json "$results_dir/signal-delivery-finished.json" workflow signal \
    --workflow-id "$workflow_id" --run-id "$run_id" \
    --name delivery_finished --identity "$identity"
}

proxy_api=""
proxy_request() {
  local output=$1 method=$2 path=$3
  shift 3
  curl --fail-with-body --silent --show-error --connect-timeout 3 --max-time 15 \
    --request "$method" "$@" "$proxy_api$path" >"$output"
}

"${compose[@]}" config >"$results_dir/compose-config.yaml"
docker image inspect "$WORKER_V1_ID" >"$results_dir/v1-image-inspect.json"
docker image inspect "$STARTER_ID" >"$results_dir/starter-image-inspect.json"
docker image inspect "$EFFECTS_ID" >"$results_dir/effects-image-inspect.json"

date --utc --iso-8601=ns >"$results_dir/docker-events-since-at.txt"
date +%s%N >"$results_dir/docker-events-since-epoch-ns.txt"
docker events \
  --since "$(<"$results_dir/docker-events-since-at.txt")" \
  --filter "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME" \
  --format '{{json .}}' >"$results_dir/docker-events.jsonl" &
docker_events_pid=$!
"${compose[@]}" up --detach --wait --wait-timeout 120 \
  temporal payment completion payment-proxy worker-v1
docker image inspect "$TOXIPROXY_IMAGE" >"$results_dir/toxiproxy-image-inspect.json"
proxy_container="$("${compose[@]}" ps --quiet payment-proxy)"
proxy_ip="$(docker inspect "$proxy_container" | jq -er '
  select(length == 1) | .[0].NetworkSettings.Networks | to_entries |
  select(length == 1) | .[0].value.IPAddress |
  select(test("^([0-9]{1,3}\\.){3}[0-9]{1,3}$"))
')"
if [[ -z "$proxy_ip" ]]; then
  echo "Toxiproxy has no unique project-network address" >&2
  exit 1
fi
proxy_endpoint="$proxy_ip:8474"
proxy_api="http://$proxy_endpoint"
for _ in $(seq 1 60); do
  if proxy_request "$results_dir/toxiproxy-version.json" GET /version 2>/dev/null; then
    break
  fi
  sleep 1
done
proxy_request "$results_dir/toxiproxy-version.json" GET /version

jq -n --arg name "$TOXIPROXY_PROXY_NAME" --argjson port "$TOXIPROXY_LISTEN_PORT" '{
  name:$name,listen:("0.0.0.0:" + ($port|tostring)),upstream:"payment:8081",enabled:true
}' >"$results_dir/proxy-create-request.json"
proxy_request "$results_dir/proxy-create-response.json" POST /proxies \
  --header 'Content-Type: application/json' \
  --data-binary "@$results_dir/proxy-create-request.json"

toxic_stream=upstream
if [[ "$case_name" == h1 ]]; then
  toxic_stream=downstream
fi
jq -n --arg stream "$toxic_stream" --argjson latency "$TOXIPROXY_LATENCY_MS" '{
  name:"history-cut",type:"latency",stream:$stream,toxicity:1,
  attributes:{latency:$latency,jitter:0}
}' >"$results_dir/toxic-create-request.json"
proxy_request "$results_dir/toxic-create-response.json" POST \
  "/proxies/$TOXIPROXY_PROXY_NAME/toxics" \
  --header 'Content-Type: application/json' \
  --data-binary "@$results_dir/toxic-create-request.json"
date --utc --iso-8601=ns >"$results_dir/toxic-created-at.txt"
date +%s%N >"$results_dir/toxic-created-epoch-ns.txt"

wait_poller workflow "$results_dir/v1-workflow-pollers.json"
wait_poller activity "$results_dir/v1-activity-pollers.json"
temporal_json "$results_dir/deployment-before-current.json" worker deployment describe \
  --name safe-change-food-order-worker
temporal_json "$results_dir/version-v1.json" worker deployment describe-version \
  --deployment-name safe-change-food-order-worker --build-id food-order-v1
temporal_json "$results_dir/set-current-v1.json" worker deployment set-current-version \
  --deployment-name safe-change-food-order-worker --build-id food-order-v1 --yes
temporal_json "$results_dir/deployment-v1-current.json" worker deployment describe \
  --name safe-change-food-order-worker
jq -e '
  .routingConfig.currentVersionDeploymentName == "safe-change-food-order-worker" and
  .routingConfig.currentVersionBuildID == "food-order-v1"
' "$results_dir/deployment-v1-current.json" >/dev/null

workflow_id="temporal-old-drain-order-1"
order_id="order-1"
restaurant_id="restaurant-1"
product_id="pizza-1"
product_description="Margherita Pizza"
product_quantity=2
delivery_delay_millis=25
payment_token="payment-token-1"
amount_cents=4200
jq -n \
  --arg recorded_at "$(date --utc --iso-8601=seconds)" \
  --arg case "$case_name" --arg state_root "$case_root" \
  --arg workflow_id "$workflow_id" --arg order_id "$order_id" \
  --arg restaurant_id "$restaurant_id" --arg product_id "$product_id" \
  --arg product_description "$product_description" \
  --arg payment_token "$payment_token" --arg stream "$toxic_stream" \
  --arg build_env "$build_env" --arg proxy_endpoint "$proxy_endpoint" \
  --argjson product_quantity "$product_quantity" \
  --argjson delivery_delay_millis "$delivery_delay_millis" \
  --argjson amount_cents "$amount_cents" --argjson latency_ms "$TOXIPROXY_LATENCY_MS" '{
    schema:1,recorded_at:$recorded_at,cell:"old-drain",system:"temporal-pinned",
    case:$case,state_root:$state_root,workflow_id:$workflow_id,order_id:$order_id,
    restaurant_id:$restaurant_id,
    products:[{product_id:$product_id,description:$product_description,quantity:$product_quantity}],
    delivery_delay_millis:$delivery_delay_millis,
    payment_token:$payment_token,amount_cents:$amount_cents,
    fault:{tool:"toxiproxy",toxic:"latency",stream:$stream,latency_ms:$latency_ms,jitter_ms:0},
    build_env:$build_env,proxy_endpoint:$proxy_endpoint,
    effective_invocation:{OLD_DRAIN_CASE:$case,TEMPORAL_OLD_DRAIN_STATE_ROOT:$state_root,
      SKIP_BUILD:1,HARNESS_BUILD_ENV:$build_env,script:"runtime/deploy/temporal/run-old-drain-case.sh"}
  }' >"$results_dir/run-metadata.json"

"${compose[@]}" run --rm -T starter \
  -behavior=pinned \
  -workflow-id="$workflow_id" \
  -order-id="$order_id" \
  -restaurant-id="$restaurant_id" \
  -product-id="$product_id" \
  -product-description="$product_description" \
  -product-quantity="$product_quantity" \
  -delivery-delay-millis="$delivery_delay_millis" \
  -payment-token="$payment_token" \
  -amount-cents="$amount_cents" >"$results_dir/start.json"
run_id="$(jq -er '
  select(.schema == 1 and .behavior == "pinned" and .workflow_id == "temporal-old-drain-order-1") |
  .run_id | select(type == "string" and length > 0)
' "$results_dir/start.json")"

cut_reached=0
for _ in $(seq 1 20); do
  provider_stats payment "$results_dir/payment-cut-stats.json"
  provider_stats completion "$results_dir/completion-cut-stats.json"
  workflow_describe "$results_dir/cut-describe-poll.json"
  if jq -e --arg case "$case_name" '
      .deliveries == (if $case == "h0" then 0 else 1 end) and
      .commits == (if $case == "h0" then 0 else 1 end) and
      .paths == (if $case == "h0" then {} else {"/v1/charge":1} end)
    ' "$results_dir/payment-cut-stats.json" >/dev/null &&
    jq -e '.deliveries == 0 and .commits == 0 and .paths == {}' \
      "$results_dir/completion-cut-stats.json" >/dev/null &&
    jq -e '
      .workflowExecutionInfo.status == "WORKFLOW_EXECUTION_STATUS_RUNNING" and
      .workflowExecutionInfo.versioningInfo.behavior == "VERSIONING_BEHAVIOR_PINNED" and
      .workflowExecutionInfo.versioningInfo.deploymentVersion ==
        {buildId:"food-order-v1",deploymentName:"safe-change-food-order-worker"} and
      (.pendingActivities | length) == 1 and
      .pendingActivities[0].activityType.name == "ChargePayment" and
      .pendingActivities[0].state == "PENDING_ACTIVITY_STATE_STARTED" and
      .pendingActivities[0].lastWorkerIdentity == "safe-change-food-order-v1-worker"
    ' "$results_dir/cut-describe-poll.json" >/dev/null; then
    cut_reached=1
    break
  fi
  sleep 1
done
if [[ "$cut_reached" != 1 ]]; then
  echo "old-drain did not reach the pending payment cut" >&2
  exit 1
fi

workflow_show "$results_dir/cut-history-before.json"
workflow_describe "$results_dir/cut-describe.json"
workflow_show "$results_dir/cut-history-after.json"
cmp "$results_dir/cut-history-before.json" "$results_dir/cut-history-after.json"
jq -e '
  ([.events[] | select(.eventType == "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED" and
    .activityTaskScheduledEventAttributes.activityType.name == "ChargePayment")] | length) == 1 and
  ([.events[] | select(.eventType | test("EVENT_TYPE_ACTIVITY_TASK_(COMPLETED|FAILED|TIMED_OUT|CANCELED)$"))] | length) == 0 and
  ([.events[] | select(.eventType | test("EVENT_TYPE_WORKFLOW_EXECUTION_(COMPLETED|FAILED|CANCELED|TERMINATED|TIMED_OUT)$"))] | length) == 0
' "$results_dir/cut-history-before.json" >/dev/null
cp "$payment_state_dir/payment.history" "$results_dir/payment-cut.history"
cp "$completion_state_dir/completion.history" "$results_dir/completion-cut.history"
proxy_request "$results_dir/proxy-at-cut.json" GET "/proxies/$TOXIPROXY_PROXY_NAME"

v1_container="$("${compose[@]}" ps --quiet worker-v1)"
docker inspect "$v1_container" >"$results_dir/v1-cut-inspect.json"
jq -e --arg image "$WORKER_V1_ID" '
  length == 1 and .[0].State.Running == true and .[0].Image == $image
' "$results_dir/v1-cut-inspect.json" >/dev/null
mapfile -t cut_containers < <(docker ps --all --quiet \
  --filter "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME" | sort)
if [[ ${#cut_containers[@]} -ne 5 ]]; then
  echo "old-drain cut must contain Temporal, two providers, proxy, and v1" >&2
  exit 1
fi
docker inspect "${cut_containers[@]}" >"$results_dir/containers-cut.json"
"${compose[@]}" ps --all --quiet worker-v2 >"$results_dir/v2-containers-at-cut.txt"
if [[ -s "$results_dir/v2-containers-at-cut.txt" ]]; then
  echo "old-drain unexpectedly created v2 before release" >&2
  exit 1
fi
date --utc --iso-8601=ns >"$results_dir/cut-recorded-at.txt"
date +%s%N >"$results_dir/cut-epoch-ns.txt"

date --utc --iso-8601=ns >"$results_dir/release-requested-at.txt"
date +%s%N >"$results_dir/release-requested-epoch-ns.txt"
curl --fail-with-body --silent --show-error --connect-timeout 3 --max-time 15 \
  --request DELETE \
  --dump-header "$results_dir/toxic-delete-headers.txt" \
  --output "$results_dir/toxic-delete-body.txt" \
  --write-out '%{http_code}\n' \
  "$proxy_api/proxies/$TOXIPROXY_PROXY_NAME/toxics/history-cut" \
  >"$results_dir/toxic-delete-status.txt"
date --utc --iso-8601=ns >"$results_dir/release-confirmed-at.txt"
date +%s%N >"$results_dir/release-confirmed-epoch-ns.txt"
if [[ "$(<"$results_dir/toxic-delete-status.txt")" != 204 || -s "$results_dir/toxic-delete-body.txt" ]]; then
  echo "Toxiproxy did not confirm latency removal" >&2
  exit 1
fi
proxy_request "$results_dir/proxy-after-release.json" GET "/proxies/$TOXIPROXY_PROXY_NAME"

settled=0
for _ in $(seq 1 30); do
  provider_stats payment "$results_dir/payment-settled-stats.json"
  provider_stats completion "$results_dir/completion-settled-stats.json"
  workflow_show "$results_dir/settled-history.json"
  workflow_describe "$results_dir/settled-describe.json"
  if workflow_query "$results_dir/settled-query.json" 2>/dev/null &&
    jq -e '.deliveries == 1 and .commits == 1 and .paths == {"/v1/charge":1}' \
      "$results_dir/payment-settled-stats.json" >/dev/null &&
    jq -e '.deliveries == 0 and .commits == 0 and .paths == {}' \
      "$results_dir/completion-settled-stats.json" >/dev/null &&
    jq -e '.queryResult == [{schema:1,order_id:"order-1",restaurant_id:"restaurant-1",
      product_count:2,worker_build:"food-order-v1",phase:"IN_PREPARATION",
      delivery_id:"",driver_id:"",stages:["RESTAURANT_SELECTED","CREATED","PAYMENT_PENDING",
        "PAYMENT_COMMITTED","SCHEDULED","IN_PREPARATION"]}]' \
      "$results_dir/settled-query.json" >/dev/null; then
    settled=1
    break
  fi
  sleep 1
done
if [[ "$settled" != 1 ]]; then
  echo "v1 did not settle the delayed payment" >&2
  exit 1
fi
workflow_show "$results_dir/settled-history.json"
workflow_describe "$results_dir/settled-describe.json"
workflow_query "$results_dir/settled-query.json"
jq -e '
  ([.events[] | select(.eventType == "EVENT_TYPE_ACTIVITY_TASK_COMPLETED" and
    .activityTaskCompletedEventAttributes.scheduledEventId == "5")] | length) == 1 and
  ([.events[] | select(.eventType == "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED" and
    .activityTaskScheduledEventAttributes.activityType.name == "PrepareFood")] | length) == 1 and
  ([.events[] | select(.eventType == "EVENT_TYPE_ACTIVITY_TASK_COMPLETED")] | length) == 2 and
  ([.events[] | select(.eventType == "EVENT_TYPE_WORKFLOW_TASK_FAILED")] | length) == 0 and
  ([.events[] | select(.eventType | test("EVENT_TYPE_WORKFLOW_EXECUTION_(COMPLETED|FAILED|CANCELED|TERMINATED|TIMED_OUT)$"))] | length) == 0
' "$results_dir/settled-history.json" >/dev/null
cp "$payment_state_dir/payment.history" "$results_dir/payment-settled.history"
cp "$completion_state_dir/completion.history" "$results_dir/completion-settled.history"

signal_business_stages safe-change-old-drain-harness
completed=0
for _ in $(seq 1 60); do
  workflow_show "$results_dir/final-history.json"
  workflow_describe "$results_dir/final-describe.json"
  if jq -e '.workflowExecutionInfo.status == "WORKFLOW_EXECUTION_STATUS_COMPLETED"' \
      "$results_dir/final-describe.json" >/dev/null; then
    completed=1
    break
  fi
  sleep 1
done
if [[ "$completed" != 1 ]]; then
  echo "retained v1 did not complete the pinned workflow" >&2
  exit 1
fi
workflow_show "$results_dir/final-history.json"
workflow_describe "$results_dir/final-describe.json"
workflow_query "$results_dir/final-query.json"
provider_stats payment "$results_dir/payment-final-stats.json"
provider_stats completion "$results_dir/completion-final-stats.json"
cp "$payment_state_dir/payment.history" "$results_dir/payment-final.history"
cp "$completion_state_dir/completion.history" "$results_dir/completion-final.history"
jq -e '.deliveries == 1 and .commits == 1 and .paths == {"/v1/charge":1}' \
  "$results_dir/payment-final-stats.json" >/dev/null
jq -e '.deliveries == 1 and .commits == 1 and .paths == {"/v1/complete":1}' \
  "$results_dir/completion-final-stats.json" >/dev/null
jq -e '.queryResult == [{schema:1,order_id:"order-1",restaurant_id:"restaurant-1",
  product_count:2,worker_build:"food-order-v1",phase:"DELIVERED",
  delivery_id:"delivery-order-1",driver_id:"driver-1",
  stages:["RESTAURANT_SELECTED","CREATED","PAYMENT_PENDING","PAYMENT_COMMITTED","SCHEDULED",
    "IN_PREPARATION","SCHEDULING_DELIVERY","WAITING_FOR_DRIVER","IN_DELIVERY","DELIVERED"]}]' \
  "$results_dir/final-query.json" >/dev/null
jq -e '
  ([.events[] | select(.eventType == "EVENT_TYPE_WORKFLOW_TASK_FAILED")] | length) == 0 and
  ([.events[] | select(.eventType == "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED" and
    .activityTaskScheduledEventAttributes.activityType.name == "ChargePayment")] | length) == 1 and
  ([.events[] | select(.eventType == "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED" and
    .activityTaskScheduledEventAttributes.activityType.name == "PrepareFood")] | length) == 1 and
  ([.events[] | select(.eventType == "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED" and
    .activityTaskScheduledEventAttributes.activityType.name == "ScheduleDelivery")] | length) == 1 and
  ([.events[] | select(.eventType == "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED" and
    .activityTaskScheduledEventAttributes.activityType.name == "CompleteOrder")] | length) == 1 and
  ([.events[] | select(.eventType == "EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED")] | length) == 1
' "$results_dir/final-history.json" >/dev/null

wait_poller workflow "$results_dir/v1-final-workflow-pollers.json"
wait_poller activity "$results_dir/v1-final-activity-pollers.json"
temporal_json "$results_dir/deployment-final.json" worker deployment describe \
  --name safe-change-food-order-worker
temporal_json "$results_dir/version-v1-final.json" worker deployment describe-version \
  --deployment-name safe-change-food-order-worker --build-id food-order-v1
docker inspect "$v1_container" >"$results_dir/v1-final-inspect.json"
jq -e --arg image "$WORKER_V1_ID" --arg id "$v1_container" '
  length == 1 and .[0].Id == $id and .[0].State.Running == true and .[0].Image == $image
' "$results_dir/v1-final-inspect.json" >/dev/null
"${compose[@]}" ps --all --quiet worker-v2 >"$results_dir/v2-containers-final.txt"
if [[ -s "$results_dir/v2-containers-final.txt" ]]; then
  echo "old-drain unexpectedly created v2" >&2
  exit 1
fi
mapfile -t final_containers < <(docker ps --all --quiet \
  --filter "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME" | sort)
if [[ ${#final_containers[@]} -ne 5 ]]; then
  echo "old-drain final container set differs" >&2
  exit 1
fi
docker inspect "${final_containers[@]}" >"$results_dir/containers-final.json"
"${compose[@]}" logs --no-color worker-v1 >"$results_dir/v1.log" 2>&1
date --utc --iso-8601=ns >"$results_dir/final-recorded-at.txt"
date +%s%N >"$results_dir/final-epoch-ns.txt"
docker_events_until_epoch="$(( $(date +%s) + 1 ))"
printf '%s\n' "$docker_events_until_epoch" >"$results_dir/docker-events-until-epoch.txt"
stop_docker_events
jq -s -e '
  all(.[];
    (.Actor.Attributes["com.docker.compose.service"] // "") as $service |
    ($service != "worker-v2" and $service != "worker-compatible-v2")
  ) and
  ([.[] | select(.Type == "container" and .Action == "start") |
    .Actor.Attributes["com.docker.compose.service"]] | unique) as $started |
  all(["temporal","payment","completion","payment-proxy","worker-v1","starter"][];
    . as $service | $started | index($service) != null
  )
' "$results_dir/docker-events.jsonl" >/dev/null

cut_ns="$(<"$results_dir/cut-epoch-ns.txt")"
final_ns="$(<"$results_dir/final-epoch-ns.txt")"
retained_ns=$((final_ns - cut_ns))
jq -n \
  --arg case "$case_name" --arg workflow_id "$workflow_id" --arg run_id "$run_id" \
  --arg stream "$toxic_stream" --arg v1_container_id "$v1_container" \
  --argjson retained_worker_ns "$retained_ns" \
  --argjson payment_cut "$(<"$results_dir/payment-cut-stats.json")" \
  --argjson payment_final "$(<"$results_dir/payment-final-stats.json")" \
  --argjson completion_final "$(<"$results_dir/completion-final-stats.json")" '{
    schema:1,cell:"old-drain",system:"temporal-pinned",case:$case,
    workflow_id:$workflow_id,run_id:$run_id,decision:"retain-v1",
    toxic_stream:$stream,toxic_deleted:true,source_build:"food-order-v1",
    target_started:false,old_code_required:true,availability_preserved:true,
    v1_container_id:$v1_container_id,v1_running_at_cut:true,v1_running_at_completion:true,
    retained_worker_ns:$retained_worker_ns,payment_at_cut:$payment_cut,
    payment_final:$payment_final,completion_final:$completion_final,
    final_status:"WORKFLOW_EXECUTION_STATUS_COMPLETED",duplicate_external_effect:false
  }' >"$results_dir/observed.json"

cat "$results_dir/observed.json"
