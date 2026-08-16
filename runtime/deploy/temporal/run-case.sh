#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
case_name="${CASE:-}"
mode="${MODE:-}"
if [[ "$case_name" != h0 && "$case_name" != h1 ]]; then
  echo "CASE must be h0 or h1" >&2
  exit 64
fi
if [[ "$mode" != auto_upgrade && "$mode" != pinned && "$mode" != manual_branch ]]; then
  echo "MODE must be auto_upgrade, pinned, or manual_branch" >&2
  exit 64
fi

for command in cmp docker find git jq realpath seq sha256sum sort; do
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
  case_root="$(mktemp -d "/tmp/safe-change-temporal-${mode}-${case_name}.XXXXXX")"
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
else
  "$script_dir/build-images.sh" >"$build_env" 2>"$results_dir/build.log"
fi
cp "$build_env" "$results_dir/build.env"
cp "$script_dir/versions.env" "$results_dir/versions.env"

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
if [[ "$case_name" == h0 ]]; then
  PAYMENT_HOLD_BEFORE_COMMIT=true
  PAYMENT_HOLD_AFTER_COMMIT=false
else
  PAYMENT_HOLD_BEFORE_COMMIT=false
  PAYMENT_HOLD_AFTER_COMMIT=true
fi
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-safe-change-temporal-${mode//_/-}-${case_name}-$$}"
set +a

compose=(docker compose --project-name "$COMPOSE_PROJECT_NAME" --file "$script_dir/compose.yaml")
cleanup() {
  local status=$?
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
  echo "Temporal $mode/$case_name evidence: $case_root" >&2
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
  "${compose[@]}" exec -T "$service" wget -qO- http://127.0.0.1:8081/v1/stats >"$output"
}

workflow_show() {
  local output=$1
  temporal_json "$output" workflow show --workflow-id "$workflow_id" --run-id "$run_id"
}

workflow_describe() {
  local output=$1
  temporal_json "$output" workflow describe --workflow-id "$workflow_id" --run-id "$run_id" --raw
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

workflow_id="temporal-matched-order-1"
order_id="order-1"
restaurant_id="restaurant-1"
product_id="pizza-1"
product_description="Margherita Pizza"
product_quantity=2
delivery_delay_millis=25
payment_token="payment-token-1"
amount_cents=4200
starter_behavior=pinned
if [[ "$mode" == auto_upgrade ]]; then
  starter_behavior=autoupgrade
elif [[ "$mode" == manual_branch ]]; then
  starter_behavior=manual
fi

"${compose[@]}" config >"$results_dir/compose-config.yaml"
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
  -behavior="$starter_behavior" \
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
  select(.schema == 1 and .workflow_id == "temporal-matched-order-1") | .run_id |
  select(type == "string" and length > 0)
' "$results_dir/start.json")"

for _ in $(seq 1 30); do
  provider_stats payment "$results_dir/payment-cut-stats.json"
  if jq -e --arg case "$case_name" '
    .deliveries == 1 and .paths["/v1/charge"] == 1 and
    .commits == (if $case == "h0" then 0 else 1 end)
  ' "$results_dir/payment-cut-stats.json" >/dev/null; then
    break
  fi
  sleep 1
done
jq -e --arg case "$case_name" '
  .deliveries == 1 and .paths["/v1/charge"] == 1 and
  .commits == (if $case == "h0" then 0 else 1 end)
' "$results_dir/payment-cut-stats.json" >/dev/null

workflow_show "$results_dir/cut-show-before.json"
workflow_describe "$results_dir/cut-describe.json"
workflow_show "$results_dir/cut-show-after.json"
cmp "$results_dir/cut-show-before.json" "$results_dir/cut-show-after.json"
jq -e '
  ([.events[] | select(.eventType == "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED")] | length) == 1 and
  ([.events[] | select(.eventType | test("EVENT_TYPE_ACTIVITY_TASK_(COMPLETED|FAILED|TIMED_OUT|CANCELED)$"))] | length) == 0 and
  ([.events[] | select(.eventType | test("EVENT_TYPE_WORKFLOW_EXECUTION_(COMPLETED|FAILED|CANCELED|TERMINATED|TIMED_OUT)$"))] | length) == 0
' "$results_dir/cut-show-before.json" >/dev/null
jq -e --arg workflow "$workflow_id" --arg run "$run_id" '
  .workflowExecutionInfo.execution.workflowId == $workflow and
  .workflowExecutionInfo.execution.runId == $run and
  .workflowExecutionInfo.status == "WORKFLOW_EXECUTION_STATUS_RUNNING" and
  (.pendingActivities | length) == 1 and
  .pendingActivities[0].activityId == "5" and
  .pendingActivities[0].activityType.name == "ChargePayment" and
  .pendingActivities[0].state == "PENDING_ACTIVITY_STATE_STARTED" and
  .pendingActivities[0].attempt == 1 and
  .pendingActivities[0].maximumAttempts == 1 and
  .pendingActivities[0].lastWorkerIdentity == "safe-change-food-order-v1-worker" and
  .pendingActivities[0].lastDeploymentVersion.deploymentName == "safe-change-food-order-worker" and
  .pendingActivities[0].lastDeploymentVersion.buildId == "food-order-v1"
' "$results_dir/cut-describe.json" >/dev/null

cp "$payment_state_dir/payment.history" "$results_dir/payment-cut.history"
cp "$completion_state_dir/completion.history" "$results_dir/completion-cut.history"
v1_container="$("${compose[@]}" ps --quiet worker-v1)"
docker inspect "$v1_container" >"$results_dir/v1-running-inspect.json"
jq -e --arg image "$WORKER_V1_ID" '
  length == 1 and .[0].State.Running == true and .[0].Image == $image
' "$results_dir/v1-running-inspect.json" >/dev/null

"${compose[@]}" stop --timeout 0 worker-v1
docker inspect "$v1_container" >"$results_dir/v1-stopped-inspect.json"
jq -e 'length == 1 and .[0].State.Running == false' "$results_dir/v1-stopped-inspect.json" >/dev/null

for _ in $(seq 1 45); do
  workflow_show "$results_dir/pre-v2-history.json"
  if jq -e '
    ([.events[] | select(.eventType == "EVENT_TYPE_ACTIVITY_TASK_TIMED_OUT")] | length) == 1
  ' "$results_dir/pre-v2-history.json" >/dev/null; then
    break
  fi
  sleep 1
done
jq -e '
  ([.events[] | select(.eventType == "EVENT_TYPE_ACTIVITY_TASK_STARTED")] | length) == 1 and
  ([.events[] | select(.eventType == "EVENT_TYPE_ACTIVITY_TASK_TIMED_OUT")] | length) == 1 and
  ([.events[] | select(.eventType == "EVENT_TYPE_ACTIVITY_TASK_COMPLETED")] | length) == 0
' "$results_dir/pre-v2-history.json" >/dev/null

provider_stats payment "$results_dir/payment-before-v2-stats.json"
jq -e --arg case "$case_name" '
  .deliveries == 1 and .commits == (if $case == "h0" then 0 else 1 end)
' "$results_dir/payment-before-v2-stats.json" >/dev/null

if [[ "$mode" == manual_branch ]]; then
  signal_business_stages safe-change-harness
fi

"${compose[@]}" up --detach worker-v2
wait_poller workflow food-order-v2 "$results_dir/v2-workflow-pollers.json"
wait_poller activity food-order-v2 "$results_dir/v2-activity-pollers.json"
wait_deployment_version_task_queues \
  safe-change-food-order-worker food-order-v2 safe-change-food-orders \
  "$results_dir/version-v2-before-current.json"
temporal_json "$results_dir/set-current-v2.json" worker deployment set-current-version \
  --deployment-name safe-change-food-order-worker --build-id food-order-v2 --yes
temporal_json "$results_dir/deployment-v2-current.json" worker deployment describe \
  --name safe-change-food-order-worker
temporal_json "$results_dir/version-v2-current.json" worker deployment describe-version \
  --deployment-name safe-change-food-order-worker --build-id food-order-v2
jq -e '
  .routingConfig.currentVersionDeploymentName == "safe-change-food-order-worker" and
  .routingConfig.currentVersionBuildID == "food-order-v2"
' "$results_dir/deployment-v2-current.json" >/dev/null

if [[ "$mode" != manual_branch ]]; then
  signal_business_stages safe-change-harness
fi

final_wait_seconds="${FINAL_WAIT_SECONDS:-12}"
for _ in $(seq 1 "$final_wait_seconds"); do
  workflow_show "$results_dir/final-history.json"
  workflow_describe "$results_dir/final-describe.json"
  if jq -e '
    ([.events[] | select(
      .eventType == "EVENT_TYPE_WORKFLOW_EXECUTION_SIGNALED" and
      .workflowExecutionSignaledEventAttributes.identity == "safe-change-harness"
    ) | .workflowExecutionSignaledEventAttributes.signalName] ==
      ["preparation_finished","driver_selected","driver_at_restaurant","delivery_finished"]) and (
      ([.events[] | select(.eventType == "EVENT_TYPE_WORKFLOW_TASK_FAILED")] | length) > 0 or
      ([.events[] | select(.eventType | test("EVENT_TYPE_WORKFLOW_EXECUTION_(COMPLETED|FAILED|CANCELED|TERMINATED|TIMED_OUT)$"))] | length) > 0
    )
  ' "$results_dir/final-history.json" >/dev/null; then
    break
  fi
  sleep 1
done
workflow_show "$results_dir/final-history.json"
workflow_describe "$results_dir/final-describe.json"
jq -e '
  ([.events[] | select(
    .eventType == "EVENT_TYPE_WORKFLOW_EXECUTION_SIGNALED" and
    .workflowExecutionSignaledEventAttributes.identity == "safe-change-harness"
  ) | .workflowExecutionSignaledEventAttributes.signalName] ==
    ["preparation_finished","driver_selected","driver_at_restaurant","delivery_finished"])
' "$results_dir/final-history.json" >/dev/null
provider_stats payment "$results_dir/payment-final-stats.json"
provider_stats completion "$results_dir/completion-final-stats.json"
cp "$payment_state_dir/payment.history" "$results_dir/payment-final.history"
cp "$completion_state_dir/completion.history" "$results_dir/completion-final.history"

v2_container="$("${compose[@]}" ps --quiet worker-v2)"
docker inspect "$v2_container" >"$results_dir/v2-running-inspect.json"
jq -e --arg image "$WORKER_V2_ID" '
  length == 1 and .[0].State.Running == true and .[0].Image == $image
' "$results_dir/v2-running-inspect.json" >/dev/null
mapfile -t project_containers < <(docker ps --all --quiet \
  --filter "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME" | sort)
if [[ ${#project_containers[@]} -eq 0 ]]; then
  echo "Compose project has no containers to inspect" >&2
  exit 1
fi
docker inspect "${project_containers[@]}" >"$results_dir/containers-final.json"

jq -n \
  --arg case "$case_name" --arg mode "$mode" \
  --arg workflow_id "$workflow_id" --arg run_id "$run_id" \
  --arg status "$(jq -r .workflowExecutionInfo.status "$results_dir/final-describe.json")" \
  --argjson workflow_task_failures "$(jq '[.events[] | select(.eventType == "EVENT_TYPE_WORKFLOW_TASK_FAILED")] | length' "$results_dir/final-history.json")" \
  --argjson payment "$(<"$results_dir/payment-final-stats.json")" \
  --argjson completion "$(<"$results_dir/completion-final-stats.json")" \
  '{schema:1,case:$case,mode:$mode,workflow_id:$workflow_id,run_id:$run_id,
    final_status:$status,workflow_task_failures:$workflow_task_failures,
    payment:$payment,completion:$completion}' >"$results_dir/observed.json"

cat "$results_dir/observed.json"
