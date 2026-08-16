#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
for command in cmp docker find git jq realpath seq sha256sum sort timeout; do
  command -v "$command" >/dev/null || {
    echo "required command not found: $command" >&2
    exit 1
  }
done

if [[ -n "${TEMPORAL_STATE_ROOT:-}" ]]; then
  case_root="$(realpath -m "$TEMPORAL_STATE_ROOT")"
  if [[ -d "$case_root" && -n "$(find "$case_root" -mindepth 1 -print -quit)" ]]; then
    echo "TEMPORAL_STATE_ROOT must be absent or empty" >&2
    exit 64
  fi
  mkdir -p "$case_root"
else
  case_root="$(mktemp -d /tmp/safe-change-temporal-compatible.XXXXXX)"
fi
results_dir="$case_root/results"
temporal_state_dir="$case_root/temporal"
payment_state_dir="$case_root/payment"
completion_state_dir="$case_root/completion"
mkdir -p "$results_dir" "$temporal_state_dir" "$payment_state_dir" "$completion_state_dir"
chmod 700 "$case_root" "$results_dir" "$temporal_state_dir" "$payment_state_dir" "$completion_state_dir"

build_env="${HARNESS_BUILD_ENV:-$case_root/build.env}"
if [[ "${SKIP_BUILD:-0}" == 1 ]]; then
  if [[ ! -f "$build_env" ]]; then
    echo "SKIP_BUILD=1 requires HARNESS_BUILD_ENV to name an existing file" >&2
    exit 64
  fi
  : >"$results_dir/build.log"
else
  "$script_dir/build-images.sh" >"$build_env" 2>"$results_dir/build.log"
fi
cp "$build_env" "$results_dir/build.env"
cp "$script_dir/versions.env" "$results_dir/versions.env"
cp "$script_dir/app/internal/workerapp/variant_v1.go" "$results_dir/source-variant-v1.go"
cp "$script_dir/app/internal/workerapp/variant_compatible_v2.go" "$results_dir/source-variant-compatible-v2.go"
cp "$script_dir/app/internal/workerapp/activities.go" "$results_dir/source-activities.go"
cp "$script_dir/app/internal/workerapp/workflows.go" "$results_dir/source-workflows.go"
cp "$script_dir/app/internal/harness/types.go" "$results_dir/source-types.go"
cp "$script_dir/app/cmd/starter/main.go" "$results_dir/source-starter.go"
cp "$script_dir/run-compatible.sh" "$results_dir/runner.sh"

set -a
# shellcheck source=versions.env
source "$script_dir/versions.env"
# shellcheck source=/dev/null
source "$build_env"
TEMPORAL_STATE_DIR="$temporal_state_dir"
PAYMENT_STATE_DIR="$payment_state_dir"
COMPLETION_STATE_DIR="$completion_state_dir"
DEMO_UID="$(id -u)"
DEMO_GID="$(id -g)"
PAYMENT_HOLD_BEFORE_COMMIT=false
PAYMENT_HOLD_AFTER_COMMIT=false
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-safe-change-temporal-compatible-$$}"
set +a

compose=(
  docker compose --project-name "$COMPOSE_PROJECT_NAME"
  --file "$script_dir/compose.yaml" --file "$script_dir/compose-compatible.yaml"
)
probe_containers=()
cleanup() {
  local status=$?
  printf '%s\n' "$status" >"$results_dir/exit-status.txt"
  "${compose[@]}" ps --all >"$results_dir/compose-ps.txt" 2>&1 || true
  "${compose[@]}" logs --no-color >"$results_dir/compose.log" 2>&1 || true
  if ((${#probe_containers[@]})); then
    docker container rm --force "${probe_containers[@]}" >/dev/null 2>&1 || true
  fi
  (
    cd "$results_dir"
    while IFS= read -r -d '' artifact; do
      sha256sum "$artifact"
    done < <(find . -maxdepth 1 -type f ! -name SHA256SUMS -print0 | sort -z)
  ) >"$results_dir/SHA256SUMS" 2>/dev/null || true
  if [[ "${KEEP_HARNESS:-0}" != 1 ]]; then
    "${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
  fi
  echo "Temporal AutoUpgrade compatible evidence: $case_root" >&2
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

temporal_json() {
  local output=$1
  shift
  timeout 30 "${compose[@]}" exec -T temporal temporal "$@" \
    --output json --time-format iso >"$output"
}

wait_poller() {
  local queue_type=$1 build_id=$2 output=$3
  for _ in $(seq 1 90); do
    if temporal_json "$output" task-queue describe \
      --task-queue safe-change-food-orders \
      --legacy-mode --task-queue-type-legacy "$queue_type" 2>/dev/null &&
      jq -e --arg build "$build_id" '
        ([.pollers[]? | select(
          .worker_version_capabilities.build_id == $build and
          .worker_version_capabilities.use_versioning == true and
          .worker_version_capabilities.deployment_series_name == "safe-change-food-order-worker" and
          .deployment_options.deployment_name == "safe-change-food-order-worker" and
          .deployment_options.build_id == $build
        )] | length) >= 1
      ' "$output" >/dev/null; then
      return 0
    fi
    sleep 1
  done
  echo "timed out waiting for $queue_type poller $build_id" >&2
  return 1
}

wait_deployment_version_task_queues() {
  local deployment=$1 build_id=$2 task_queue=$3 output=$4
  local attempts="${DEPLOYMENT_VERSION_WAIT_ATTEMPTS:-90}"
  local interval_seconds="${DEPLOYMENT_VERSION_WAIT_INTERVAL_SECONDS:-1}"
  for _ in $(seq 1 "$attempts"); do
    if temporal_json "$output" worker deployment describe-version \
      --deployment-name "$deployment" --build-id "$build_id" 2>/dev/null &&
      jq -e --arg deployment "$deployment" \
        --arg build "$build_id" --arg queue "$task_queue" '
        .deploymentName == $deployment and
        .BuildID == $build and
        (.taskQueuesInfos | type) == "array" and
        (.taskQueuesInfos | sort_by(.type)) == [
          {"name": $queue, "type": "activity"},
          {"name": $queue, "type": "workflow"}
        ]
      ' "$output" >/dev/null; then
      return 0
    fi
    sleep "$interval_seconds"
  done
  echo "timed out waiting for deployment version $build_id task queues" >&2
  return 1
}

provider_stats() {
  local service=$1 output=$2
  timeout 15 "${compose[@]}" exec -T "$service" wget -T 5 -qO- http://127.0.0.1:8081/v1/stats >"$output"
}

image_binary_sha256() {
  local image=$1 destination=$2 output_name=$3 container_id digest
  container_id="$(docker container create "$image")"
  probe_containers+=("$container_id")
  docker container cp "$container_id:/usr/local/bin/worker" "$destination"
  docker container rm "$container_id" >/dev/null
  digest="$(sha256sum "$destination" | awk '{print $1}')"
  printf -v "$output_name" '%s' "$digest"
}

workflow_show() {
  local output=$1
  temporal_json "$output" workflow show --workflow-id "$workflow_id" --run-id "$run_id"
}

workflow_describe() {
  local output=$1
  temporal_json "$output" workflow describe --workflow-id "$workflow_id" --run-id "$run_id" --raw
}

workflow_query() {
  local output=$1
  temporal_json "$output" workflow query \
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

workflow_id="temporal-compatible-order-1"
order_id="order-1"
restaurant_id="restaurant-1"
product_id="pizza-1"
product_description="Margherita Pizza"
product_quantity=2
delivery_delay_millis=25
payment_token="payment-token-1"
amount_cents=4200

jq -n \
  --arg workflow_id "$workflow_id" --arg order_id "$order_id" \
  --arg restaurant_id "$restaurant_id" --arg product_id "$product_id" \
  --arg product_description "$product_description" --arg payment_token "$payment_token" \
  --argjson product_quantity "$product_quantity" \
  --argjson delivery_delay_millis "$delivery_delay_millis" \
  --argjson amount_cents "$amount_cents" \
  '{schema:1,cell:"compatible",mode:"auto_upgrade",workflow_id:$workflow_id,
    order_id:$order_id,restaurant_id:$restaurant_id,
    products:[{product_id:$product_id,description:$product_description,quantity:$product_quantity}],
    delivery_delay_millis:$delivery_delay_millis,
    payment_token:$payment_token,amount_cents:$amount_cents,
    source_build:"food-order-v1",target_build:"food-order-compatible-v2",
    deployment:"safe-change-food-order-worker"}' >"$results_dir/invocation.json"
"${compose[@]}" config >"$results_dir/compose-config.yaml"
docker image inspect "$WORKER_V1_ID" >"$results_dir/v1-image-inspect.json"
docker image inspect "$WORKER_COMPATIBLE_V2_ID" >"$results_dir/compatible-image-inspect.json"
docker image inspect "$STARTER_ID" >"$results_dir/starter-image-inspect.json"
docker image inspect "$EFFECTS_ID" >"$results_dir/effects-image-inspect.json"
binary_probe_dir="$case_root/binary-probe"
mkdir -p "$binary_probe_dir"
image_binary_sha256 "$WORKER_V1_ID" "$binary_probe_dir/worker-v1" v1_binary_sha256
image_binary_sha256 "$WORKER_COMPATIBLE_V2_ID" "$binary_probe_dir/worker-compatible-v2" target_binary_sha256
find "$binary_probe_dir" -depth -delete
printf 'WORKER_V1_BINARY_SHA256=%s\nWORKER_COMPATIBLE_V2_BINARY_SHA256=%s\n' \
  "$v1_binary_sha256" "$target_binary_sha256" >"$results_dir/binary-verification.env"
if [[ "$v1_binary_sha256" != "$WORKER_V1_BINARY_SHA256" || \
      "$target_binary_sha256" != "$WORKER_COMPATIBLE_V2_BINARY_SHA256" ]]; then
  echo "worker binary digest does not match the immutable image" >&2
  exit 1
fi

"${compose[@]}" up --detach --wait --wait-timeout 120 temporal payment completion worker-v1
wait_poller workflow food-order-v1 "$results_dir/v1-workflow-pollers.json"
wait_poller activity food-order-v1 "$results_dir/v1-activity-pollers.json"
temporal_json "$results_dir/deployment-before-current.json" worker deployment describe \
  --name safe-change-food-order-worker
wait_deployment_version_task_queues \
  safe-change-food-order-worker food-order-v1 safe-change-food-orders \
  "$results_dir/version-v1.json"
temporal_json "$results_dir/set-current-v1.json" worker deployment set-current-version \
  --deployment-name safe-change-food-order-worker --build-id food-order-v1 --yes
temporal_json "$results_dir/deployment-v1-current.json" worker deployment describe \
  --name safe-change-food-order-worker
jq -e '
  .routingConfig.currentVersionDeploymentName == "safe-change-food-order-worker" and
  .routingConfig.currentVersionBuildID == "food-order-v1"
' "$results_dir/deployment-v1-current.json" >/dev/null

"${compose[@]}" run --rm -T starter \
  -behavior=autoupgrade \
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
  select(.schema == 1 and .behavior == "autoupgrade" and .workflow_id == "temporal-compatible-order-1") |
  .run_id | select(type == "string" and length > 0)
' "$results_dir/start.json")"

for _ in $(seq 1 45); do
  provider_stats payment "$results_dir/payment-cut-stats.json"
  provider_stats completion "$results_dir/completion-cut-stats.json"
  if jq -e '.deliveries == 1 and .commits == 1 and .paths == {"/v1/charge":1}' \
      "$results_dir/payment-cut-stats.json" >/dev/null &&
    jq -e '.deliveries == 0 and .commits == 0 and .paths == {}' \
      "$results_dir/completion-cut-stats.json" >/dev/null; then
    if workflow_query "$results_dir/cut-query.json" 2>/dev/null &&
      jq -e '.queryResult == [{schema:1,order_id:"order-1",restaurant_id:"restaurant-1",
        product_count:2,worker_build:"food-order-v1",phase:"IN_PREPARATION",
        delivery_id:"",driver_id:"",stages:["RESTAURANT_SELECTED","CREATED","PAYMENT_PENDING",
          "PAYMENT_COMMITTED","SCHEDULED","IN_PREPARATION"]}]' \
        "$results_dir/cut-query.json" >/dev/null; then
      break
    fi
  fi
  sleep 1
done
jq -e '.deliveries == 1 and .commits == 1 and .paths == {"/v1/charge":1}' \
  "$results_dir/payment-cut-stats.json" >/dev/null
jq -e '.deliveries == 0 and .commits == 0 and .paths == {}' \
  "$results_dir/completion-cut-stats.json" >/dev/null
jq -e '.queryResult == [{schema:1,order_id:"order-1",restaurant_id:"restaurant-1",
  product_count:2,worker_build:"food-order-v1",phase:"IN_PREPARATION",
  delivery_id:"",driver_id:"",stages:["RESTAURANT_SELECTED","CREATED","PAYMENT_PENDING",
    "PAYMENT_COMMITTED","SCHEDULED","IN_PREPARATION"]}]' \
  "$results_dir/cut-query.json" >/dev/null

workflow_show "$results_dir/cut-history-before.json"
workflow_describe "$results_dir/cut-describe.json"
workflow_show "$results_dir/cut-history-after.json"
cmp "$results_dir/cut-history-before.json" "$results_dir/cut-history-after.json"
jq -e '
  ([.events[] | select(.eventType == "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED" and
    .activityTaskScheduledEventAttributes.activityType.name == "ChargePayment")] | length) == 1 and
  ([.events[] | select(.eventType == "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED" and
    .activityTaskScheduledEventAttributes.activityType.name == "PrepareFood")] | length) == 1 and
  ([.events[] | select(.eventType == "EVENT_TYPE_ACTIVITY_TASK_COMPLETED")] | length) == 2 and
  ([.events[] | select(.eventType == "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED" and
    .activityTaskScheduledEventAttributes.activityType.name == "CompleteOrder")] | length) == 0 and
  ([.events[] | select(.eventType | test("EVENT_TYPE_WORKFLOW_EXECUTION_(COMPLETED|FAILED|CANCELED|TERMINATED|TIMED_OUT)$"))] | length) == 0
' "$results_dir/cut-history-before.json" >/dev/null
jq -e --arg workflow "$workflow_id" --arg run "$run_id" '
  .workflowExecutionInfo.execution == {workflowId:$workflow,runId:$run} and
  .workflowExecutionInfo.status == "WORKFLOW_EXECUTION_STATUS_RUNNING" and
  .workflowExecutionInfo.mostRecentWorkerVersionStamp == {buildId:"food-order-v1",useVersioning:true} and
  .workflowExecutionInfo.versioningInfo.behavior == "VERSIONING_BEHAVIOR_AUTO_UPGRADE" and
  (.pendingActivities | length) == 0
' "$results_dir/cut-describe.json" >/dev/null
cp "$payment_state_dir/payment.history" "$results_dir/payment-cut.history"
cp "$completion_state_dir/completion.history" "$results_dir/completion-cut.history"

v1_container="$("${compose[@]}" ps --quiet worker-v1)"
docker inspect "$v1_container" >"$results_dir/v1-running-inspect.json"
mapfile -t cut_containers < <(docker ps --all --quiet \
  --filter "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME" | sort)
if [[ ${#cut_containers[@]} -ne 4 ]]; then
  echo "cut project must contain exactly Temporal, two providers, and v1" >&2
  exit 1
fi
docker inspect "${cut_containers[@]}" >"$results_dir/containers-cut.json"
"${compose[@]}" logs --no-color worker-v1 >"$results_dir/v1.log" 2>&1
jq -e --arg image "$WORKER_V1_ID" '
  length == 1 and .[0].State.Running == true and .[0].Image == $image
' "$results_dir/v1-running-inspect.json" >/dev/null
"${compose[@]}" rm --stop --force worker-v1 >"$results_dir/remove-v1.txt"
set +e
docker inspect "$v1_container" >"$results_dir/v1-removed-inspect.json" 2>"$results_dir/v1-removed-inspect.stderr"
v1_removed_status=$?
set -e
printf '%s\n' "$v1_removed_status" >"$results_dir/v1-removed-inspect-status.txt"
if [[ "$v1_removed_status" -eq 0 ]]; then
  echo "v1 worker container still exists after removal" >&2
  exit 1
fi
"${compose[@]}" ps --all --quiet worker-v1 >"$results_dir/v1-after-remove.txt"
if [[ -s "$results_dir/v1-after-remove.txt" ]]; then
  echo "Compose still resolves a v1 worker container after removal" >&2
  exit 1
fi
mapfile -t before_target_containers < <(docker ps --all --quiet \
  --filter "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME" | sort)
if [[ ${#before_target_containers[@]} -ne 3 ]]; then
  echo "pre-target project must contain exactly Temporal and the two providers" >&2
  exit 1
fi
docker inspect "${before_target_containers[@]}" >"$results_dir/containers-before-target.json"

"${compose[@]}" up --detach worker-compatible-v2
wait_poller workflow food-order-compatible-v2 "$results_dir/compatible-workflow-pollers.json"
wait_poller activity food-order-compatible-v2 "$results_dir/compatible-activity-pollers.json"
wait_deployment_version_task_queues \
  safe-change-food-order-worker food-order-compatible-v2 safe-change-food-orders \
  "$results_dir/version-compatible-before-current.json"
temporal_json "$results_dir/set-current-compatible.json" worker deployment set-current-version \
  --deployment-name safe-change-food-order-worker --build-id food-order-compatible-v2 --yes
temporal_json "$results_dir/deployment-compatible-current.json" worker deployment describe \
  --name safe-change-food-order-worker
jq -e '
  .routingConfig.currentVersionDeploymentName == "safe-change-food-order-worker" and
  .routingConfig.currentVersionBuildID == "food-order-compatible-v2"
' "$results_dir/deployment-compatible-current.json" >/dev/null

signal_business_stages safe-change-compatible-harness
for _ in $(seq 1 45); do
  workflow_show "$results_dir/final-history.json"
  workflow_describe "$results_dir/final-describe.json"
  if jq -e '.workflowExecutionInfo.status == "WORKFLOW_EXECUTION_STATUS_COMPLETED"' \
      "$results_dir/final-describe.json" >/dev/null; then
    break
  fi
  sleep 1
done
workflow_show "$results_dir/final-history.json"
workflow_describe "$results_dir/final-describe.json"
workflow_query "$results_dir/final-query.json"
jq -e '.workflowExecutionInfo.status == "WORKFLOW_EXECUTION_STATUS_COMPLETED" and
  .workflowExecutionInfo.execution.workflowId == "temporal-compatible-order-1"' \
  "$results_dir/final-describe.json" >/dev/null
jq -e '.queryResult == [{schema:1,order_id:"order-1",restaurant_id:"restaurant-1",
  product_count:2,worker_build:"food-order-compatible-v2",phase:"DELIVERED",
  delivery_id:"delivery-order-1",driver_id:"driver-1",
  stages:["RESTAURANT_SELECTED","CREATED","PAYMENT_PENDING","PAYMENT_COMMITTED","SCHEDULED",
    "IN_PREPARATION","SCHEDULING_DELIVERY","WAITING_FOR_DRIVER","IN_DELIVERY","DELIVERED"]}]' \
  "$results_dir/final-query.json" >/dev/null
jq -e '
  ([.events[] | select(.eventType == "EVENT_TYPE_WORKFLOW_TASK_FAILED")] | length) == 0 and
  ([.events[] | select(.eventType == "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED" and
    .activityTaskScheduledEventAttributes.activityType.name == "ChargePayment")] | length) == 1 and
  ([.events[] | select(.eventType == "EVENT_TYPE_ACTIVITY_TASK_COMPLETED" and
    .activityTaskCompletedEventAttributes.scheduledEventId == "5")] | length) == 1 and
  ([.events[] | select(.eventType == "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED" and
    .activityTaskScheduledEventAttributes.activityType.name == "PrepareFood")] | length) == 1 and
  ([.events[] | select(.eventType == "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED" and
    .activityTaskScheduledEventAttributes.activityType.name == "ScheduleDelivery")] | length) == 1 and
  ([.events[] | select(.eventType == "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED" and
    .activityTaskScheduledEventAttributes.activityType.name == "CompleteOrder")] | length) == 1 and
  ([.events[] | select(.eventType == "EVENT_TYPE_ACTIVITY_TASK_COMPLETED" and
    .activityTaskCompletedEventAttributes.identity == "safe-change-food-order-compatible-v2-worker")] | length) == 2 and
  ([.events[] | select(.eventType == "EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED")] | length) == 1
' "$results_dir/final-history.json" >/dev/null

provider_stats payment "$results_dir/payment-final-stats.json"
provider_stats completion "$results_dir/completion-final-stats.json"
cp "$payment_state_dir/payment.history" "$results_dir/payment-final.history"
cp "$completion_state_dir/completion.history" "$results_dir/completion-final.history"
jq -e '.deliveries == 1 and .commits == 1 and .paths == {"/v1/charge":1}' \
  "$results_dir/payment-final-stats.json" >/dev/null
jq -e '.deliveries == 1 and .commits == 1 and .paths == {"/v1/complete":1}' \
  "$results_dir/completion-final-stats.json" >/dev/null
cmp "$results_dir/payment-cut.history" "$results_dir/payment-final.history"

compatible_container="$("${compose[@]}" ps --quiet worker-compatible-v2)"
docker inspect "$compatible_container" >"$results_dir/compatible-running-inspect.json"
"${compose[@]}" logs --no-color worker-compatible-v2 >"$results_dir/compatible.log" 2>&1
jq -e --arg image "$WORKER_COMPATIBLE_V2_ID" '
  length == 1 and .[0].State.Running == true and .[0].Image == $image
' "$results_dir/compatible-running-inspect.json" >/dev/null
temporal_json "$results_dir/version-compatible-current.json" worker deployment describe-version \
  --deployment-name safe-change-food-order-worker --build-id food-order-compatible-v2
temporal_json "$results_dir/deployment-final.json" worker deployment describe \
  --name safe-change-food-order-worker

mapfile -t project_containers < <(docker ps --all --quiet \
  --filter "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME" | sort)
if [[ ${#project_containers[@]} -ne 4 ]]; then
  echo "compatible project must contain exactly Temporal, two providers, and compatible v2" >&2
  exit 1
fi
docker inspect "${project_containers[@]}" >"$results_dir/containers-final.json"

jq -n \
  --arg workflow_id "$workflow_id" --arg run_id "$run_id" \
  --arg status "$(jq -r .workflowExecutionInfo.status "$results_dir/final-describe.json")" \
  --argjson payment "$(<"$results_dir/payment-final-stats.json")" \
  --argjson completion "$(<"$results_dir/completion-final-stats.json")" \
  '{schema:1,cell:"compatible",mode:"auto_upgrade",workflow_id:$workflow_id,run_id:$run_id,
    final_status:$status,closure_version:"compatible-v2",payment:$payment,completion:$completion}' \
  >"$results_dir/observed.json"

cat "$results_dir/observed.json"
