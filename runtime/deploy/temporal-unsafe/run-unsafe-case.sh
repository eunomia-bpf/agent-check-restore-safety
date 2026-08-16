#!/usr/bin/env bash
set -Eeuo pipefail

export LC_ALL=C

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
temporal_dir="$(cd -- "$script_dir/../temporal" && pwd -P)"
runtime_root="$(cd -- "$script_dir/../.." && pwd -P)"
repo_root="$(cd -- "$runtime_root/.." && pwd -P)"
method="${TEMPORAL_UNSAFE_METHOD:-}"
if [[ "$method" != proposed && "$method" != native ]]; then
  echo "TEMPORAL_UNSAFE_METHOD must be proposed or native" >&2
  exit 64
fi
if [[ "${SKIP_BUILD:-0}" != 1 || -z "${HARNESS_BUILD_ENV:-}" || ! -f "$HARNESS_BUILD_ENV" ]]; then
  echo "Temporal unsafe cases require SKIP_BUILD=1 and an existing HARNESS_BUILD_ENV" >&2
  exit 64
fi

ambient_compose_variables=(
  COMPOSE_FILE COMPOSE_PROFILES COMPOSE_PROJECT_NAME COMPOSE_PATH_SEPARATOR
  COMPOSE_ENV_FILES COMPOSE_DISABLE_ENV_FILE
)
for variable in "${ambient_compose_variables[@]}"; do
  if [[ -n "${!variable:-}" ]]; then
    echo "$variable must be empty; the runner supplies an explicit frozen Compose context" >&2
    exit 64
  fi
  unset "$variable"
done

for command in \
  awk chmod cmp cp curl date docker find git go grep id jq mkdir mktemp mv realpath \
  rmdir sed seq sha256sum sleep sort stdbuf timeout tr wc; do
  command -v "$command" >/dev/null || {
    echo "required command not found: $command" >&2
    exit 1
  }
done

if [[ -n "${TEMPORAL_UNSAFE_STATE_ROOT:-}" ]]; then
  case_root="$(realpath -m -- "$TEMPORAL_UNSAFE_STATE_ROOT")"
  if [[ -d "$case_root" && -n "$(find "$case_root" -mindepth 1 -print -quit)" ]]; then
    echo "TEMPORAL_UNSAFE_STATE_ROOT must be absent or empty" >&2
    exit 64
  fi
  mkdir -p -- "$case_root"
else
  case_root="$(mktemp -d "/tmp/safe-change-temporal-unsafe-${method}.XXXXXX")"
fi
results_dir="$case_root/results"
clean_root="$case_root/clean"
main_root="$case_root/main"
for phase_root in "$clean_root" "$main_root"; do
  mkdir -p -- \
    "$phase_root/temporal" "$phase_root/payment" "$phase_root/completion" \
    "$phase_root/control-state" "$phase_root/control-anchor" "$phase_root/operation-token"
done
mkdir -p -- "$results_dir"
chmod 700 "$case_root" "$results_dir" "$clean_root" "$main_root"
find "$clean_root" "$main_root" -mindepth 1 -type d -exec chmod 700 {} +

build_env="$(realpath -- "$HARNESS_BUILD_ENV")"
build_name="$(basename -- "$build_env")"
if [[ "$build_name" == *.* ]]; then
  build_evidence_name="${build_name%.*}-evidence"
else
  build_evidence_name="${build_name}-evidence"
fi
build_evidence="$(dirname -- "$build_env")/$build_evidence_name"
if [[ ! -d "$build_evidence" || -L "$build_evidence" || ! -f "$build_evidence/SHA256SUMS" ]]; then
  echo "HARNESS_BUILD_ENV must have complete sibling build evidence: $build_evidence" >&2
  exit 64
fi
unexpected_build_evidence="$(find "$build_evidence" -mindepth 1 ! -type d ! -type f -print -quit)"
if [[ -n "$unexpected_build_evidence" ]]; then
  echo "build evidence contains a symlink or special file: $unexpected_build_evidence" >&2
  exit 64
fi
(
  cd -- "$build_evidence"
  sha256sum --check --strict SHA256SUMS >/dev/null
)
cmp -- "$build_env" "$build_evidence/build.env"

cp -- "$build_env" "$results_dir/build.env"
cp -- "$script_dir/frozen-inputs.env" "$results_dir/frozen-inputs.env"
cp -- "$temporal_dir/versions.env" "$results_dir/versions.env"
cp -- "$script_dir/ARTIFACTS.md" "$results_dir/ARTIFACTS.md"
cp -- "$script_dir/run-unsafe-case.sh" "$results_dir/runner.sh"
(cd -- "$script_dir" && sha256sum run-unsafe-case.sh) >"$results_dir/runner.sha256"
cp -- "$temporal_dir/compose.yaml" "$results_dir/compose-base.yaml"
if [[ "$method" == proposed ]]; then
  overlay="$script_dir/compose-proposed.yaml"
else
  overlay="$script_dir/compose-native.yaml"
fi
cp -- "$overlay" "$results_dir/compose-overlay.yaml"
cp -- "$script_dir/requirements/source.json" "$results_dir/requirement-source.json"
cp -- "$script_dir/requirements/target.json" "$results_dir/requirement-target.json"
cp -- "$script_dir/configs/source-adapter.json" "$results_dir/source-adapter.json"
cp -- "$script_dir/configs/target-adapter.json" "$results_dir/target-adapter.json"
cp -a -- "$build_evidence" "$results_dir/build-evidence"
(
  cd -- "$results_dir/build-evidence"
  sha256sum --check --strict SHA256SUMS >/dev/null
)
cmp -- "$results_dir/build.env" "$results_dir/build-evidence/build.env"
git -C "$repo_root" rev-parse --verify HEAD >"$results_dir/git-revision.txt"
git -C "$repo_root" status --porcelain=v1 >"$results_dir/git-status.txt"

set -a
# shellcheck source=../temporal/versions.env
source "$temporal_dir/versions.env"
# shellcheck source=/dev/null
source "$build_env"
set +a

required_build_values=(
  TEMPORAL_IMAGE TEMPORAL_IMAGE_ID WORKER_V1_ID WORKER_V1_BINARY_SHA256
  WORKER_V2_ID STARTER_ID STARTER_BINARY_SHA256 EFFECTS_ID EFFECTS_BINARY_SHA256
  SAFE_CHANGE_CONTROL_IMAGE CONTROL_BINARY_SHA256 CONTROL_SOURCE_MANIFEST_SHA256
  CONTROL_DOCKERFILE_SHA256 TEMPORAL_UNSAFE_WORKER_ID
  TEMPORAL_UNSAFE_WORKER_BINARY_SHA256 PROPOSED_UNSAFE_WORKER_ID
  NATIVE_UNSAFE_WORKER_ID PROPOSED_NATIVE_IMAGE_ID_EQUAL
  TEMPORAL_UNSAFE_ADAPTER_ID TEMPORAL_UNSAFE_ADAPTER_BINARY_SHA256
  TEMPORAL_UNSAFE_PAYMENT_TOKEN_CONTRACT TEMPORAL_UNSAFE_COMPOSE_PROFILES_CONTRACT
  TEMPORAL_UNSAFE_EXCLUDED_PROFILE FROZEN_INPUTS_SHA256 FROZEN_VERSIONS_SHA256
  BASE_COMPOSE_SHA256 PROPOSED_COMPOSE_SHA256 NATIVE_COMPOSE_SHA256
  SOURCE_ADAPTER_CONFIG_SHA256 TARGET_ADAPTER_CONFIG_SHA256
)
for variable in "${required_build_values[@]}"; do
  if [[ -z "${!variable:-}" ]]; then
    echo "frozen build environment omitted $variable" >&2
    exit 64
  fi
done
if [[ "$PROPOSED_UNSAFE_WORKER_ID" != "$TEMPORAL_UNSAFE_WORKER_ID" ||
      "$NATIVE_UNSAFE_WORKER_ID" != "$TEMPORAL_UNSAFE_WORKER_ID" ||
      "$PROPOSED_NATIVE_IMAGE_ID_EQUAL" != true ||
      "$TEMPORAL_UNSAFE_PAYMENT_TOKEN_CONTRACT" != payment_token_equals_order_id ||
      "$TEMPORAL_UNSAFE_COMPOSE_PROFILES_CONTRACT" != empty ||
      "$TEMPORAL_UNSAFE_EXCLUDED_PROFILE" != excluded-base-worker-v2 ]]; then
  echo "frozen build does not bind both lanes to one target image and identity contract" >&2
  exit 64
fi

if [[ "$(sha256sum -- "$results_dir/frozen-inputs.env" | awk '{print $1}')" != "$FROZEN_INPUTS_SHA256" ||
      "$(sha256sum -- "$results_dir/versions.env" | awk '{print $1}')" != "$FROZEN_VERSIONS_SHA256" ||
      "$(sha256sum -- "$results_dir/compose-base.yaml" | awk '{print $1}')" != "$BASE_COMPOSE_SHA256" ||
      "$(sha256sum -- "$results_dir/source-adapter.json" | awk '{print $1}')" != "$SOURCE_ADAPTER_CONFIG_SHA256" ||
      "$(sha256sum -- "$results_dir/target-adapter.json" | awk '{print $1}')" != "$TARGET_ADAPTER_CONFIG_SHA256" ]]; then
  echo "a frozen runtime or topology input differs from the build profile" >&2
  exit 64
fi
if [[ "$method" == proposed ]]; then
  expected_overlay_sha256="$PROPOSED_COMPOSE_SHA256"
else
  expected_overlay_sha256="$NATIVE_COMPOSE_SHA256"
fi
if [[ "$(sha256sum -- "$results_dir/compose-overlay.yaml" | awk '{print $1}')" != "$expected_overlay_sha256" ]]; then
  echo "the selected Compose overlay differs from the build profile" >&2
  exit 64
fi

for image_id in \
  "$TEMPORAL_IMAGE_ID" "$WORKER_V1_ID" "$WORKER_V2_ID" "$STARTER_ID" \
  "$EFFECTS_ID" "$SAFE_CHANGE_CONTROL_IMAGE" "$TEMPORAL_UNSAFE_WORKER_ID" \
  "$TEMPORAL_UNSAFE_ADAPTER_ID"; do
  if [[ ! "$image_id" =~ ^sha256:[0-9a-f]{64}$ ]]; then
    echo "frozen build contains a non-immutable image ID: $image_id" >&2
    exit 64
  fi
done

project_base="${TEMPORAL_UNSAFE_PROJECT_BASE:-safe-change-temporal-unsafe-${method}-$$}"
if [[ ! "$project_base" =~ ^[a-z0-9][a-z0-9_-]{2,80}$ ]]; then
  echo "TEMPORAL_UNSAFE_PROJECT_BASE is not a safe Compose project stem" >&2
  exit 64
fi
clean_project="${project_base}-clean"
main_project="${project_base}-main"
jq -n \
  --arg clean_project "$clean_project" --arg main_project "$main_project" \
  '{schema:1,ambient:{COMPOSE_FILE:"",COMPOSE_PROFILES:"",COMPOSE_PROJECT_NAME:"",
    COMPOSE_PATH_SEPARATOR:"",COMPOSE_ENV_FILES:"",COMPOSE_DISABLE_ENV_FILE:""},
    explicit_projects:{clean:$clean_project,main:$main_project},profiles_enabled:[]}' \
  >"$results_dir/compose-environment.json"

DEMO_UID="$(id -u)"
DEMO_GID="$(id -g)"
PAYMENT_HOLD_BEFORE_COMMIT=false
PAYMENT_HOLD_AFTER_COMMIT=false
export DEMO_UID DEMO_GID PAYMENT_HOLD_BEFORE_COMMIT PAYMENT_HOLD_AFTER_COMMIT

compose=()
compose_project=""
current_phase="setup"
set_phase() {
  local phase=$1 phase_root
  case "$phase" in
    clean) phase_root="$clean_root"; compose_project="$clean_project" ;;
    main) phase_root="$main_root"; compose_project="$main_project" ;;
    *) echo "unknown phase: $phase" >&2; return 64 ;;
  esac
  current_phase="$phase"
  TEMPORAL_STATE_DIR="$phase_root/temporal"
  PAYMENT_STATE_DIR="$phase_root/payment"
  COMPLETION_STATE_DIR="$phase_root/completion"
  UNSAFE_CONTROL_STATE_DIR="$phase_root/control-state"
  UNSAFE_CONTROL_ANCHOR_DIR="$phase_root/control-anchor"
  UNSAFE_OPERATION_TOKEN_DIR="$phase_root/operation-token"
  export TEMPORAL_STATE_DIR PAYMENT_STATE_DIR COMPLETION_STATE_DIR
  export UNSAFE_CONTROL_STATE_DIR UNSAFE_CONTROL_ANCHOR_DIR UNSAFE_OPERATION_TOKEN_DIR
  compose=(
    docker compose --project-name "$compose_project"
    --file "$temporal_dir/compose.yaml" --file "$overlay"
  )
  if [[ -n "$(docker ps --all --quiet --filter "label=com.docker.compose.project=$compose_project")" ]]; then
    echo "Compose project already has containers: $compose_project" >&2
    return 64
  fi
  if [[ -n "$(docker network ls --quiet --filter "label=com.docker.compose.project=$compose_project")" ]]; then
    echo "Compose project already has networks: $compose_project" >&2
    return 64
  fi
}

event_pid=""
event_file=""
probe_containers=()
stop_events() {
  if [[ -n "$event_pid" ]]; then
    kill -TERM "$event_pid" >/dev/null 2>&1 || true
    wait "$event_pid" >/dev/null 2>&1 || true
    event_pid=""
  fi
}

cleanup() {
  local status=$?
  trap - EXIT
  stop_events
  printf '%s\n' "$status" >"$results_dir/exit-status.txt"
  if ((${#probe_containers[@]})); then
    docker container rm --force "${probe_containers[@]}" >/dev/null 2>&1 || true
  fi
  for project in "$clean_project" "$main_project"; do
    if [[ "$status" != 0 ]]; then
      local failure_prefix="failure-${project##*-}"
      docker compose --project-name "$project" \
        --file "$temporal_dir/compose.yaml" --file "$overlay" \
        ps --all >"$results_dir/$failure_prefix-compose-ps.txt" 2>&1 || true
      docker compose --project-name "$project" \
        --file "$temporal_dir/compose.yaml" --file "$overlay" \
        logs --no-color >"$results_dir/$failure_prefix-compose.log" 2>&1 || true
    fi
    if [[ "${KEEP_HARNESS:-0}" != 1 ]]; then
      docker compose --project-name "$project" \
        --file "$temporal_dir/compose.yaml" --file "$overlay" \
        down --volumes --remove-orphans >/dev/null 2>&1 || true
    fi
  done
  (
    cd -- "$results_dir"
    while IFS= read -r -d '' artifact; do
      sha256sum -- "$artifact"
    done < <(find . -type f ! -path './SHA256SUMS' -print0 | sort -z)
  ) >"$results_dir/SHA256SUMS" 2>/dev/null || true
  echo "Temporal history-dependent unsafe $method evidence: $case_root" >&2
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

image_binary_sha256() {
  local image=$1 path=$2 destination=$3 output_name=$4 container_id digest
  container_id="$(docker container create "$image")"
  probe_containers+=("$container_id")
  docker container cp "$container_id:$path" "$destination"
  docker container rm "$container_id" >/dev/null
  probe_containers=("${probe_containers[@]:0:${#probe_containers[@]}-1}")
  digest="$(sha256sum -- "$destination" | awk '{print $1}')"
  printf -v "$output_name" '%s' "$digest"
}

docker image inspect "$TEMPORAL_IMAGE" >"$results_dir/temporal-image-inspect.json"
docker image inspect "$WORKER_V1_ID" >"$results_dir/v1-image-inspect.json"
docker image inspect "$TEMPORAL_UNSAFE_WORKER_ID" >"$results_dir/target-image-inspect.json"
docker image inspect "$STARTER_ID" >"$results_dir/starter-image-inspect.json"
docker image inspect "$EFFECTS_ID" >"$results_dir/effects-image-inspect.json"
docker image inspect "$TEMPORAL_UNSAFE_ADAPTER_ID" >"$results_dir/adapter-image-inspect.json"
docker image inspect "$SAFE_CHANGE_CONTROL_IMAGE" >"$results_dir/control-image-inspect.json"
binary_dir="$case_root/binary-probe"
mkdir -p -- "$binary_dir"
image_binary_sha256 "$WORKER_V1_ID" /usr/local/bin/worker "$binary_dir/worker-v1" actual_v1_binary
image_binary_sha256 "$TEMPORAL_UNSAFE_WORKER_ID" /usr/local/bin/worker "$binary_dir/worker-target" actual_target_binary
image_binary_sha256 "$STARTER_ID" /usr/local/bin/starter "$binary_dir/starter" actual_starter_binary
image_binary_sha256 "$EFFECTS_ID" /usr/local/bin/payment "$binary_dir/effects" actual_effects_binary
image_binary_sha256 "$TEMPORAL_UNSAFE_ADAPTER_ID" /usr/local/bin/temporal-provider-adapter "$binary_dir/adapter" actual_adapter_binary
image_binary_sha256 "$SAFE_CHANGE_CONTROL_IMAGE" /usr/local/bin/control "$binary_dir/control" actual_control_binary
find "$binary_dir" -mindepth 1 -type f -delete
rmdir "$binary_dir"
cat_binary_mismatch=0
[[ "$actual_v1_binary" == "$WORKER_V1_BINARY_SHA256" ]] || cat_binary_mismatch=1
[[ "$actual_target_binary" == "$TEMPORAL_UNSAFE_WORKER_BINARY_SHA256" ]] || cat_binary_mismatch=1
[[ "$actual_starter_binary" == "$STARTER_BINARY_SHA256" ]] || cat_binary_mismatch=1
[[ "$actual_effects_binary" == "$EFFECTS_BINARY_SHA256" ]] || cat_binary_mismatch=1
[[ "$actual_adapter_binary" == "$TEMPORAL_UNSAFE_ADAPTER_BINARY_SHA256" ]] || cat_binary_mismatch=1
[[ "$actual_control_binary" == "$CONTROL_BINARY_SHA256" ]] || cat_binary_mismatch=1
printf '%s\n' \
  "WORKER_V1_BINARY_SHA256=$actual_v1_binary" \
  "TEMPORAL_UNSAFE_WORKER_BINARY_SHA256=$actual_target_binary" \
  "STARTER_BINARY_SHA256=$actual_starter_binary" \
  "EFFECTS_BINARY_SHA256=$actual_effects_binary" \
  "TEMPORAL_UNSAFE_ADAPTER_BINARY_SHA256=$actual_adapter_binary" \
  "CONTROL_BINARY_SHA256=$actual_control_binary" \
  >"$results_dir/binary-verification.env"
if [[ "$cat_binary_mismatch" != 0 ]]; then
  echo "an immutable image binary differs from the frozen build environment" >&2
  exit 1
fi

temporal_json() {
  local output=$1
  shift
  timeout 45 "${compose[@]}" exec -T temporal temporal "$@" \
    --output json --time-format iso >"$output"
}

wait_poller() {
  local queue_type=$1 build_id=$2 identity=$3 output=$4
  for _ in $(seq 1 120); do
    if temporal_json "$output" task-queue describe \
      --task-queue safe-change-food-orders \
      --legacy-mode --task-queue-type-legacy "$queue_type" 2>/dev/null &&
      jq -e --arg build "$build_id" --arg identity "$identity" '
        ([.pollers[]? | select(
          .identity == $identity and
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
  timeout 15 "${compose[@]}" exec -T "$service" \
    wget -T 5 -qO- http://127.0.0.1:8081/v1/stats >"$output"
}

workflow_id=""
run_id=""
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

wait_workflow_phase() {
  local expected_build=$1 expected_phase=$2 prefix=$3 completed=0
  for _ in $(seq 1 90); do
    workflow_show "$results_dir/$prefix-history.json"
    workflow_describe "$results_dir/$prefix-describe.json"
    if workflow_query "$results_dir/$prefix-query.json" 2>/dev/null &&
      jq -e --arg order "$order_id" --arg restaurant "$restaurant_id" \
        --arg build "$expected_build" --arg phase "$expected_phase" \
        --arg delivery "delivery-$order_id" --arg driver "$driver_id" '
        .queryResult == [{
          schema:1,order_id:$order,restaurant_id:$restaurant,product_count:2,
          worker_build:$build,phase:$phase,
          delivery_id:(if $phase == "DELIVERED" then $delivery else "" end),
          driver_id:(if $phase == "DELIVERED" then $driver else "" end),
          stages:(if $phase == "DELIVERED" then [
            "RESTAURANT_SELECTED","CREATED","PAYMENT_PENDING","PAYMENT_COMMITTED",
            "SCHEDULED","IN_PREPARATION","SCHEDULING_DELIVERY",
            "WAITING_FOR_DRIVER","IN_DELIVERY","DELIVERED"
          ] else [
            "RESTAURANT_SELECTED","CREATED","PAYMENT_PENDING","PAYMENT_COMMITTED",
            "SCHEDULED","IN_PREPARATION"
          ] end)
        }]
      ' "$results_dir/$prefix-query.json" >/dev/null; then
      if [[ "$expected_phase" == DELIVERED ]]; then
        jq -e '.workflowExecutionInfo.status == "WORKFLOW_EXECUTION_STATUS_COMPLETED"' \
          "$results_dir/$prefix-describe.json" >/dev/null || {
            sleep 1
            continue
          }
      else
        jq -e '.workflowExecutionInfo.status == "WORKFLOW_EXECUTION_STATUS_RUNNING"' \
          "$results_dir/$prefix-describe.json" >/dev/null || {
            sleep 1
            continue
          }
      fi
      completed=1
      break
    fi
    sleep 1
  done
  [[ "$completed" == 1 ]] || {
    echo "workflow did not reach $expected_build/$expected_phase" >&2
    return 1
  }
  workflow_show "$results_dir/$prefix-history.json"
  workflow_describe "$results_dir/$prefix-describe.json"
  workflow_query "$results_dir/$prefix-query.json"
}

start_workflow() {
  local prefix=$1
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
    -amount-cents="$amount_cents" >"$results_dir/$prefix-start.json"
  run_id="$(jq -er --arg workflow "$workflow_id" '
    select(.schema == 1 and .behavior == "autoupgrade" and .workflow_id == $workflow) |
    .run_id | select(type == "string" and length > 0)
  ' "$results_dir/$prefix-start.json")"
  printf '%s\n' "$run_id" >"$results_dir/$prefix-run-id.txt"
}

signal_business_stages() {
  local prefix=$1 identity=$2 delivery_id="delivery-$order_id"
  temporal_json "$results_dir/$prefix-signal.json" workflow signal \
    --workflow-id "$workflow_id" --run-id "$run_id" \
    --name preparation_finished --identity "$identity"
  temporal_json "$results_dir/$prefix-signal-driver-selected.json" workflow signal \
    --workflow-id "$workflow_id" --run-id "$run_id" \
    --name driver_selected --identity "$identity" \
    --input "{\"delivery_id\":\"$delivery_id\",\"driver_id\":\"$driver_id\"}"
  temporal_json "$results_dir/$prefix-signal-driver-at-restaurant.json" workflow signal \
    --workflow-id "$workflow_id" --run-id "$run_id" \
    --name driver_at_restaurant --identity "$identity"
  temporal_json "$results_dir/$prefix-signal-delivery-finished.json" workflow signal \
    --workflow-id "$workflow_id" --run-id "$run_id" \
    --name delivery_finished --identity "$identity"
}

capture_provider_history() {
  local phase=$1 moment=$2
  cp -- "$PAYMENT_STATE_DIR/payment.history" "$results_dir/$phase-payment-$moment.history"
  cp -- "$COMPLETION_STATE_DIR/completion.history" "$results_dir/$phase-completion-$moment.history"
}

capture_topology() {
  local prefix=$1
  "${compose[@]}" ps --all >"$results_dir/$prefix-compose-ps.txt"
  mapfile -t project_containers < <(
    docker ps --all --quiet --filter "label=com.docker.compose.project=$compose_project" | sort
  )
  if ((${#project_containers[@]} == 0)); then
    echo "project $compose_project has no containers" >&2
    return 1
  fi
  docker inspect "${project_containers[@]}" >"$results_dir/$prefix-containers.json"
  mapfile -t project_networks < <(
    docker network ls --quiet --filter "label=com.docker.compose.project=$compose_project" | sort
  )
  if ((${#project_networks[@]} == 0)); then
    echo "project $compose_project has no networks" >&2
    return 1
  fi
  docker network inspect "${project_networks[@]}" >"$results_dir/$prefix-networks.json"
  "${compose[@]}" logs --no-color >"$results_dir/$prefix-compose.log" 2>&1
}

capture_runtime_config() {
  local phase=$1
  shift
  "${compose[@]}" config "$@" >"$results_dir/$phase-compose-config.yaml"
  "${compose[@]}" --profile '*' config >"$results_dir/$phase-compose-all-profiles-config.yaml"
  if grep -Eq '^  worker-v2:' "$results_dir/$phase-compose-config.yaml"; then
    echo "default selected config unexpectedly includes excluded worker-v2" >&2
    return 1
  fi
  grep -Eq '^  worker-v2:' "$results_dir/$phase-compose-all-profiles-config.yaml" || {
    echo "all-profiles config omitted the neutralized worker-v2 audit definition" >&2
    return 1
  }
}

wait_for_event() {
  local file=$1 id=$2 boundary=$3
  for _ in $(seq 1 120); do
    if jq -s -e --arg id "$id" --arg boundary "$boundary" '
      any(.[];
        .Type == "container" and .Action == "create" and .Actor.ID == $id and
        .Actor.Attributes["io.safe-change.event-sentinel"] == "true" and
        .Actor.Attributes["io.safe-change.event-boundary"] == $boundary)
    ' "$file" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.1
  done
  echo "live Docker event listener did not observe $boundary sentinel $id" >&2
  return 1
}

create_event_sentinel() {
  local phase=$1 boundary=$2 output_name service id
  service="event-sentinel-$boundary"
  id="$(docker container create \
    --name "${compose_project}-${service}" \
    --label "com.docker.compose.project=$compose_project" \
    --label "com.docker.compose.service=$service" \
    --label io.safe-change.event-sentinel=true \
    --label "io.safe-change.event-boundary=$boundary" \
    --entrypoint /bin/true "$TEMPORAL_RUNTIME_IMAGE")"
  output_name="$results_dir/$phase-event-$boundary-sentinel-id.txt"
  printf '%s\n' "$id" >"$output_name"
  wait_for_event "$event_file" "$id" "$boundary"
  docker container rm "$id" >/dev/null
}

start_events() {
  local phase=$1
  event_file="$results_dir/$phase-docker-events.jsonl"
  date --utc --iso-8601=ns >"$results_dir/$phase-events-since-at.txt"
  (
    docker_child=""
    finish_listener() {
      if [[ -n "$docker_child" ]]; then
        kill -TERM "$docker_child" >/dev/null 2>&1 || true
        wait "$docker_child" >/dev/null 2>&1 || true
      fi
      exit 0
    }
    trap finish_listener TERM INT
    stdbuf -oL -eL docker events \
      --since "$(<"$results_dir/$phase-events-since-at.txt")" \
      --filter type=container \
      --filter "label=com.docker.compose.project=$compose_project" \
      --format '{{json .}}' >"$event_file" &
    docker_child=$!
    wait "$docker_child"
  ) &
  event_pid=$!
  create_event_sentinel "$phase" begin
  kill -0 "$event_pid" 2>/dev/null || {
    echo "Docker event listener died after its begin sentinel" >&2
    return 1
  }
  date --utc --iso-8601=ns >"$results_dir/$phase-event-listener-ready-at.txt"
}

end_events() {
  local phase=$1 listener_status=0 begin_id end_id
  kill -0 "$event_pid" 2>/dev/null || {
    echo "Docker event listener died before its end sentinel" >&2
    return 1
  }
  create_event_sentinel "$phase" end
  end_id="$(<"$results_dir/$phase-event-end-sentinel-id.txt")"
  begin_id="$(<"$results_dir/$phase-event-begin-sentinel-id.txt")"
  kill -0 "$event_pid" 2>/dev/null || {
    echo "Docker event listener died after observing its end sentinel" >&2
    return 1
  }
  kill -TERM "$event_pid" >/dev/null 2>&1 || true
  wait "$event_pid" || listener_status=$?
  event_pid=""
  printf '%s\n' "$listener_status" >"$results_dir/$phase-event-listener-exit-status.txt"
  date --utc --iso-8601=ns >"$results_dir/$phase-event-listener-ended-at.txt"
  if [[ "$listener_status" != 0 ]]; then
    echo "Docker event listener did not stop cleanly" >&2
    return 1
  fi
  jq -s -e --arg begin "$begin_id" --arg end "$end_id" '
    ([.[] | select(.Type == "container" and .Action == "create" and .Actor.ID == $begin)] | length) == 1 and
    ([.[] | select(.Type == "container" and .Action == "create" and .Actor.ID == $end)] | length) == 1 and
    ([.[] | select(.Type == "container" and .Action == "create" and .Actor.ID == $begin)][0].timeNano) as $begin_time |
    ([.[] | select(.Type == "container" and .Action == "create" and .Actor.ID == $end)][0].timeNano) as $end_time |
    $begin_time < $end_time and
    all(.[];
      if .Type == "container" and (.Action == "create" or .Action == "start") and
        (.Actor.Attributes["io.safe-change.event-sentinel"] // "") != "true"
      then (.timeNano > $begin_time and .timeNano < $end_time)
      else true end) and
    all(.[];
      (.Actor.Attributes["com.docker.compose.service"] // "") != "worker-v2")
  ' "$event_file" >/dev/null
}

control_url=""
admin_token=""
resolve_control() {
  local phase=$1 network_suffix=$2 container ip network
  container="$("${compose[@]}" ps --quiet unsafe-control)"
  docker inspect "$container" >"$results_dir/$phase-control-container.json"
  read -r network ip < <(docker inspect "$container" | jq -er --arg suffix "_$network_suffix" '
    .[0].NetworkSettings.Networks | to_entries |
    [.[] | select(.key | endswith($suffix))] |
    select(length == 1) | .[0] | [.key,.value.IPAddress] | @tsv
  ')
  if [[ -z "$network" || ! "$ip" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
    echo "unsafe control has no unique $network_suffix address" >&2
    return 1
  fi
  jq -e 'length == 1 and ((.[0].HostConfig.PortBindings // {}) | length) == 0' \
    "$results_dir/$phase-control-container.json" >/dev/null
  control_url="http://$ip:8787"
  jq -n --arg network "$network" --arg ip "$ip" --arg url "$control_url" \
    '{schema:1,network:$network,container_ip:$ip,url:$url,published_ports:false}' \
    >"$results_dir/$phase-control-endpoint.json"
  curl --fail-with-body --silent --show-error --connect-timeout 3 --max-time 10 \
    "$control_url/healthz" >/dev/null
  admin_token="$("${compose[@]}" exec -T unsafe-control cat /state/admin-token | tr -d '\r\n')"
  [[ ${#admin_token} -ge 32 ]] || {
    echo "control admin token is invalid" >&2
    return 1
  }
}

control_post() {
  local path=$1 input=$2 output=$3
  curl --fail-with-body --silent --show-error --connect-timeout 3 --max-time 60 \
    --request POST --header "Authorization: Bearer $admin_token" \
    --header 'Content-Type: application/json' --data-binary "@$input" \
    "$control_url$path" >"$output"
}

control_get() {
  local path=$1 output=$2
  curl --fail-with-body --silent --show-error --connect-timeout 3 --max-time 30 \
    --header "Authorization: Bearer $admin_token" "$control_url$path" >"$output"
}

check_certificate() {
  local state=$1 certificate=$2 output=$3
  (cd -- "$runtime_root" && go run ./cmd/check-certificate \
    -state "$state" -certificate "$certificate") >"$output"
}

probe_jsonl=""
network_probe() {
  local phase=$1 service=$2 name=$3 expected=$4 url=$5 status=0
  set +e
  "${compose[@]}" exec -T "$service" wget -T 2 -qO- "$url" >/dev/null 2>&1
  status=$?
  set -e
  jq -cn --arg phase "$phase" --arg service "$service" --arg name "$name" \
    --arg url "$url" --argjson expected "$expected" --argjson status "$status" \
    '{phase:$phase,service:$service,name:$name,url:$url,
      expected_reachable:$expected,exit_status:$status}' >>"$probe_jsonl"
  if [[ "$expected" == true && "$status" != 0 ]]; then
    echo "expected network path failed: $service -> $url" >&2
    return 1
  fi
  if [[ "$expected" == false && "$status" == 0 ]]; then
    echo "forbidden network path succeeded: $service -> $url" >&2
    return 1
  fi
}

service_ip_for_network() {
  local service=$1 network_suffix=$2 container
  container="$("${compose[@]}" ps --quiet "$service")"
  docker inspect "$container" | jq -er --arg suffix "_$network_suffix" '
    .[0].NetworkSettings.Networks | to_entries |
    [.[] | select(.key | endswith($suffix))] |
    select(length == 1) | .[0].value.IPAddress |
    select(test("^([0-9]{1,3}\\.){3}[0-9]{1,3}$"))
  '
}

finish_network_probes() {
  local phase=$1
  jq -s --arg phase "$phase" '{schema:1,phase:$phase,probes:.}' "$probe_jsonl" \
    >"$results_dir/$phase-network-probes.json"
  find "$probe_jsonl" -delete
}

derive_operation_id() {
  local identity=$1 digest
  digest="$(printf 'operation-id-v1\0temporal-order-workflow\0%s' "$identity" | sha256sum | awk '{print $1}')"
  printf 'op-%s' "$digest"
}

write_native_absence() {
  local phase=$1 output=$2 services_json
  mapfile -t ids < <(
    docker ps --all --quiet --filter "label=com.docker.compose.project=$compose_project" | sort
  )
  services_json="$(docker inspect "${ids[@]}" | jq -c '
    [.[].Config.Labels["com.docker.compose.service"]] | sort | unique
  ')"
  jq -n --arg phase "$phase" --argjson present "$services_json" '
    {schema:1,phase:$phase,absent_services:["unsafe-control","source-adapter","target-adapter"],
      present_services:$present} as $root
    | $root | select(all($root.absent_services[]; . as $service |
        $root.present_services | index($service) == null))
  ' >"$output"
  [[ -s "$output" ]] || {
    echo "native project unexpectedly contains a control or adapter service" >&2
    return 1
  }
}

clean_order_id="${TEMPORAL_UNSAFE_CLEAN_ORDER_ID:-temporal-unsafe-clean-${method}-$$}"
main_order_id="${TEMPORAL_UNSAFE_ORDER_ID:-temporal-unsafe-main-${method}-$$}"
clean_workflow_id="${TEMPORAL_UNSAFE_CLEAN_WORKFLOW_ID:-workflow-$clean_order_id}"
main_workflow_id="${TEMPORAL_UNSAFE_WORKFLOW_ID:-workflow-$main_order_id}"
amount_cents="${TEMPORAL_UNSAFE_AMOUNT_CENTS:-4200}"
restaurant_id="restaurant-1"
product_id="pizza-1"
product_description="Margherita Pizza"
product_quantity=2
delivery_delay_millis=25
driver_id="driver-1"
for value in "$clean_order_id" "$main_order_id" "$clean_workflow_id" "$main_workflow_id"; do
  if [[ ! "$value" =~ ^[A-Za-z0-9._-]{1,128}$ ]]; then
    echo "workflow and order identities must use 1-128 stable characters" >&2
    exit 64
  fi
done
if [[ "$clean_order_id" == "$main_order_id" || "$clean_workflow_id" == "$main_workflow_id" ]]; then
  echo "clean and main identities must differ" >&2
  exit 64
fi
if [[ "$amount_cents" != 4200 ]]; then
  echo "the frozen paired workload requires TEMPORAL_UNSAFE_AMOUNT_CENTS=4200" >&2
  exit 64
fi
clean_payment_operation_id="$(derive_operation_id "$clean_order_id")"
clean_completion_operation_id="$(derive_operation_id "complete:$clean_order_id")"
main_payment_operation_id="$(derive_operation_id "$main_order_id")"
main_completion_operation_id="$(derive_operation_id "complete:$main_order_id")"
signal_identity="safe-change-temporal-unsafe-harness"

# Phase A: a fresh real execution of the exact target image.  The proposed
# lane activates the target Requirement before the target container exists.
set_phase clean
if [[ "$method" == proposed ]]; then
  capture_runtime_config clean \
    temporal payment completion unsafe-control target-adapter worker-unsafe-v2 starter
else
  capture_runtime_config clean temporal payment completion worker-unsafe-v2 starter
fi
jq -n --arg method "$method" --arg project "$compose_project" \
  --arg workflow_id "$clean_workflow_id" --arg order_id "$clean_order_id" \
  --arg restaurant_id "$restaurant_id" --arg product_id "$product_id" \
  --arg product_description "$product_description" --argjson product_quantity "$product_quantity" \
  --argjson delivery_delay_millis "$delivery_delay_millis" --arg driver_id "$driver_id" \
  --arg payment_token "$clean_order_id" --arg payment_operation_id "$clean_payment_operation_id" \
  --arg completion_operation_id "$clean_completion_operation_id" \
  --arg signal_identity "$signal_identity" --argjson amount_cents "$amount_cents" '
  {schema:1,phase:"clean",cell:"temporal-history-dependent-unsafe-edit",method:$method,
    compose_project:$project,workflow_id:$workflow_id,order_id:$order_id,
    restaurant_id:$restaurant_id,
    products:[{product_id:$product_id,description:$product_description,quantity:$product_quantity}],
    delivery_delay_millis:$delivery_delay_millis,
    payment_token:$payment_token,amount_cents:$amount_cents,
    operation_ids:{payment:$payment_operation_id,completion:$completion_operation_id},
    source_build:"food-order-unsafe-v2",target_build:"food-order-unsafe-v2",
    deployment:"safe-change-food-order-worker",behavior:"autoupgrade",
    signals:[
      {name:"preparation_finished",identity:$signal_identity},
      {name:"driver_selected",identity:$signal_identity,
        input:{delivery_id:("delivery-" + $order_id),driver_id:$driver_id}},
      {name:"driver_at_restaurant",identity:$signal_identity},
      {name:"delivery_finished",identity:$signal_identity}
    ]}
' >"$results_dir/clean-invocation.json"
start_events clean

if [[ "$method" == proposed ]]; then
  "${compose[@]}" up --detach --wait --wait-timeout 180 \
    temporal payment completion unsafe-control target-adapter
  resolve_control clean target-runtime
  "${compose[@]}" ps --all --quiet worker-unsafe-v2 \
    >"$results_dir/clean-target-containers-before-decision.txt"
  [[ ! -s "$results_dir/clean-target-containers-before-decision.txt" ]] || {
    echo "clean target existed before target Requirement activation" >&2
    exit 1
  }
  control_post /v1/compile "$results_dir/requirement-target.json" \
    "$results_dir/clean-certificate-target.json"
  jq -e '
    .decision == "activate" and .requirement.id == "temporal-unsafe-target-v2" and
    .rule.allow == ["charge-v2","finish-v2"]
  ' "$results_dir/clean-certificate-target.json" >/dev/null
  control_post /v1/certificate-state "$results_dir/clean-certificate-target.json" \
    "$results_dir/clean-certificate-target-state.json"
  check_certificate "$results_dir/clean-certificate-target-state.json" \
    "$results_dir/clean-certificate-target.json" \
    "$results_dir/clean-certificate-target-verdict.json"
  jq -e '.valid == true and .decision == "activate" and .history_sequence == 0' \
    "$results_dir/clean-certificate-target-verdict.json" >/dev/null
  control_post /v1/activate "$results_dir/clean-certificate-target.json" \
    "$results_dir/clean-active-target.json"
  control_get /v1/state "$results_dir/clean-control-after-activate.json"
  control_get /v1/history "$results_dir/clean-control-history-after-activate.json"
else
  "${compose[@]}" up --detach --wait --wait-timeout 180 temporal payment completion
  "${compose[@]}" ps --all --quiet worker-unsafe-v2 \
    >"$results_dir/clean-target-containers-before-decision.txt"
  [[ ! -s "$results_dir/clean-target-containers-before-decision.txt" ]] || {
    echo "native clean target existed before its start decision" >&2
    exit 1
  }
  write_native_absence clean "$results_dir/clean-native-absence.json"
fi
date --utc --iso-8601=ns >"$results_dir/clean-decision-at.txt"

"${compose[@]}" up --detach --wait --wait-timeout 180 worker-unsafe-v2
wait_poller workflow food-order-unsafe-v2 safe-change-food-order-unsafe-v2-worker \
  "$results_dir/clean-target-workflow-pollers.json"
wait_poller activity food-order-unsafe-v2 safe-change-food-order-unsafe-v2-worker \
  "$results_dir/clean-target-activity-pollers.json"
temporal_json "$results_dir/clean-deployment-before-current.json" worker deployment describe \
  --name safe-change-food-order-worker
wait_deployment_version_task_queues \
  safe-change-food-order-worker food-order-unsafe-v2 safe-change-food-orders \
  "$results_dir/clean-target-version-before-current.json"
temporal_json "$results_dir/clean-set-current-target.json" worker deployment set-current-version \
  --deployment-name safe-change-food-order-worker --build-id food-order-unsafe-v2 --yes
temporal_json "$results_dir/clean-deployment-target-current.json" worker deployment describe \
  --name safe-change-food-order-worker
jq -e '
  .routingConfig.currentVersionDeploymentName == "safe-change-food-order-worker" and
  .routingConfig.currentVersionBuildID == "food-order-unsafe-v2"
' "$results_dir/clean-deployment-target-current.json" >/dev/null

workflow_id="$clean_workflow_id"
order_id="$clean_order_id"
payment_token="$order_id"
[[ "$payment_token" == "$order_id" ]] || {
  echo "payment_token must equal order_id" >&2
  exit 64
}
start_workflow clean
wait_workflow_phase food-order-unsafe-v2 IN_PREPARATION clean-wait
provider_stats payment "$results_dir/clean-payment-wait-stats.json"
provider_stats completion "$results_dir/clean-completion-wait-stats.json"
capture_provider_history clean wait
jq -e '.deliveries == 1 and .commits == 1 and .paths == {"/v2/charge":1}' \
  "$results_dir/clean-payment-wait-stats.json" >/dev/null
jq -e '.deliveries == 0 and .commits == 0 and .paths == {}' \
  "$results_dir/clean-completion-wait-stats.json" >/dev/null
jq -e '
  [.events[] | select(.eventType == "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED") |
    .activityTaskScheduledEventAttributes.activityType.name] ==
    ["ChargePaymentV2","PrepareFood"] and
  ([.events[] | select(.eventType == "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED" and
    .activityTaskScheduledEventAttributes.activityType.name == "ChargePayment")] | length) == 0 and
  ([.events[] | select(.eventType == "EVENT_TYPE_ACTIVITY_TASK_COMPLETED")] | length) == 2 and
  ([.events[] | select(.eventType == "EVENT_TYPE_TIMER_STARTED")] | length) == 1 and
  ([.events[] | select(.eventType == "EVENT_TYPE_TIMER_FIRED")] | length) == 1 and
  ([.events[] | select(.eventType == "EVENT_TYPE_WORKFLOW_EXECUTION_SIGNALED")] | length) == 0 and
  ([.events[] | select(.eventType == "EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED")] | length) == 0
' "$results_dir/clean-wait-history.json" >/dev/null

clean_target_container="$("${compose[@]}" ps --quiet worker-unsafe-v2)"
docker inspect "$clean_target_container" >"$results_dir/clean-target-container.json"
jq -e --arg image "$TEMPORAL_UNSAFE_WORKER_ID" '
  length == 1 and .[0].State.Running == true and .[0].Image == $image
' "$results_dir/clean-target-container.json" >/dev/null

probe_jsonl="$case_root/clean-network-probes.jsonl"
: >"$probe_jsonl"
if [[ "$method" == proposed ]]; then
  clean_payment_ip="$(service_ip_for_network payment effects)"
  clean_completion_ip="$(service_ip_for_network completion effects)"
  clean_control_ip="$(service_ip_for_network unsafe-control target-runtime)"
  network_probe clean worker-unsafe-v2 target-adapter true http://target-adapter:8790/healthz
  network_probe clean worker-unsafe-v2 payment-dns-denied false http://payment:8081/healthz
  network_probe clean worker-unsafe-v2 payment-ip-denied false "http://$clean_payment_ip:8081/healthz"
  network_probe clean worker-unsafe-v2 completion-dns-denied false http://completion:8081/healthz
  network_probe clean worker-unsafe-v2 completion-ip-denied false "http://$clean_completion_ip:8081/healthz"
  network_probe clean worker-unsafe-v2 control-dns-denied false http://unsafe-control:8787/healthz
  network_probe clean worker-unsafe-v2 control-ip-denied false "http://$clean_control_ip:8787/healthz"
  network_probe clean target-adapter control true http://unsafe-control:8787/healthz
  network_probe clean target-adapter payment-dns-denied false http://payment:8081/healthz
  network_probe clean target-adapter payment-ip-denied false "http://$clean_payment_ip:8081/healthz"
  network_probe clean unsafe-control payment true http://payment:8081/healthz
  network_probe clean unsafe-control completion true http://completion:8081/healthz
else
  network_probe clean worker-unsafe-v2 payment true http://payment:8081/healthz
  network_probe clean worker-unsafe-v2 completion true http://completion:8081/healthz
  network_probe clean worker-unsafe-v2 control false http://unsafe-control:8787/healthz
  network_probe clean worker-unsafe-v2 adapter false http://target-adapter:8790/healthz
fi
finish_network_probes clean

signal_business_stages clean "$signal_identity"
wait_workflow_phase food-order-unsafe-v2 DELIVERED clean-final
provider_stats payment "$results_dir/clean-payment-final-stats.json"
provider_stats completion "$results_dir/clean-completion-final-stats.json"
capture_provider_history clean final
cmp -- "$results_dir/clean-payment-wait.history" "$results_dir/clean-payment-final.history"
jq -e '.deliveries == 1 and .commits == 1 and .paths == {"/v2/charge":1}' \
  "$results_dir/clean-payment-final-stats.json" >/dev/null
jq -e '.deliveries == 1 and .commits == 1 and .paths == {"/v1/complete":1}' \
  "$results_dir/clean-completion-final-stats.json" >/dev/null
jq -e '
  ([.events[] | select(.eventType == "EVENT_TYPE_WORKFLOW_TASK_FAILED")] | length) == 0 and
  [.events[] | select(.eventType == "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED") |
    .activityTaskScheduledEventAttributes.activityType.name] ==
    ["ChargePaymentV2","PrepareFood","ScheduleDelivery","CompleteOrder"] and
  [.events[] | select(.eventType == "EVENT_TYPE_WORKFLOW_EXECUTION_SIGNALED") |
    .workflowExecutionSignaledEventAttributes.signalName] ==
    ["preparation_finished","driver_selected","driver_at_restaurant","delivery_finished"] and
  ([.events[] | select(.eventType == "EVENT_TYPE_ACTIVITY_TASK_COMPLETED")] | length) == 4 and
  ([.events[] | select(.eventType == "EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED")] | length) == 1
' "$results_dir/clean-final-history.json" >/dev/null
temporal_json "$results_dir/clean-target-version-final.json" worker deployment describe-version \
  --deployment-name safe-change-food-order-worker --build-id food-order-unsafe-v2
temporal_json "$results_dir/clean-deployment-final.json" worker deployment describe \
  --name safe-change-food-order-worker

if [[ "$method" == proposed ]]; then
  control_get /v1/state "$results_dir/clean-final-control-state.json"
  control_get /v1/history "$results_dir/clean-final-control-history.json"
  cp -- "$UNSAFE_CONTROL_STATE_DIR/runtime.history" "$results_dir/clean-runtime.history"
  cp -- "$UNSAFE_CONTROL_ANCHOR_DIR/runtime.head" "$results_dir/clean-runtime.head"
  jq -e '
    .requirement.id == "temporal-unsafe-target-v2" and
    ([.operations[] | select(.kind == "charge-v2" and .phase == "succeeded")] | length) == 1 and
    ([.operations[] | select(.kind == "finish-v2" and .phase == "succeeded")] | length) == 1
  ' "$results_dir/clean-final-control-state.json" >/dev/null
else
  write_native_absence clean "$results_dir/clean-native-absence.json"
fi
capture_topology clean
end_events clean
jq -s -e '
  ([.[] | select(.Type == "container" and .Action == "start" and
    .Actor.Attributes["com.docker.compose.service"] == "worker-unsafe-v2")] | length) == 1 and
  all(.[]; (.Actor.Attributes["com.docker.compose.service"] // "") != "worker-v2")
' "$results_dir/clean-docker-events.jsonl" >/dev/null

"${compose[@]}" down --volumes --remove-orphans >/dev/null
if [[ -n "$(docker ps --all --quiet --filter "label=com.docker.compose.project=$clean_project")" ||
      -n "$(docker network ls --quiet --filter "label=com.docker.compose.project=$clean_project")" ]]; then
  echo "clean project was not isolated and removed before main" >&2
  exit 1
fi

# Phase B: a fresh source execution reaches the paid/waiting cut.  Proposed
# compiles and refuses the target without creating it; native removes v1 and
# lets the same target image process the next Workflow Task.
set_phase main
if [[ "$method" == proposed ]]; then
  capture_runtime_config main \
    temporal payment completion unsafe-control source-adapter worker-v1 starter
else
  capture_runtime_config main \
    temporal payment completion worker-v1 worker-unsafe-v2 starter
fi
jq -n --arg method "$method" --arg project "$compose_project" \
  --arg workflow_id "$main_workflow_id" --arg order_id "$main_order_id" \
  --arg restaurant_id "$restaurant_id" --arg product_id "$product_id" \
  --arg product_description "$product_description" --argjson product_quantity "$product_quantity" \
  --argjson delivery_delay_millis "$delivery_delay_millis" --arg driver_id "$driver_id" \
  --arg payment_token "$main_order_id" --arg payment_operation_id "$main_payment_operation_id" \
  --arg completion_operation_id "$main_completion_operation_id" \
  --arg signal_identity "$signal_identity" --argjson amount_cents "$amount_cents" '
  {schema:1,phase:"main",cell:"temporal-history-dependent-unsafe-edit",method:$method,
    compose_project:$project,workflow_id:$workflow_id,order_id:$order_id,
    restaurant_id:$restaurant_id,
    products:[{product_id:$product_id,description:$product_description,quantity:$product_quantity}],
    delivery_delay_millis:$delivery_delay_millis,
    payment_token:$payment_token,amount_cents:$amount_cents,
    operation_ids:{payment:$payment_operation_id,completion:$completion_operation_id},
    source_build:"food-order-v1",target_build:"food-order-unsafe-v2",
    deployment:"safe-change-food-order-worker",behavior:"autoupgrade",
    signals:[
      {name:"preparation_finished",identity:$signal_identity},
      {name:"driver_selected",identity:$signal_identity,
        input:{delivery_id:("delivery-" + $order_id),driver_id:$driver_id}},
      {name:"driver_at_restaurant",identity:$signal_identity},
      {name:"delivery_finished",identity:$signal_identity}
    ]}
' >"$results_dir/main-invocation.json"
start_events main

if [[ "$method" == proposed ]]; then
  "${compose[@]}" up --detach --wait --wait-timeout 180 \
    temporal payment completion unsafe-control source-adapter
  resolve_control main source-runtime
  control_post /v1/compile "$results_dir/requirement-source.json" \
    "$results_dir/main-certificate-source.json"
  jq -e '
    .decision == "activate" and .requirement.id == "temporal-unsafe-source-v1" and
    .rule.allow == ["charge-v1","finish-v1"]
  ' "$results_dir/main-certificate-source.json" >/dev/null
  control_post /v1/certificate-state "$results_dir/main-certificate-source.json" \
    "$results_dir/main-certificate-source-state.json"
  check_certificate "$results_dir/main-certificate-source-state.json" \
    "$results_dir/main-certificate-source.json" \
    "$results_dir/main-certificate-source-verdict.json"
  jq -e '.valid == true and .decision == "activate" and .history_sequence == 0' \
    "$results_dir/main-certificate-source-verdict.json" >/dev/null
  control_post /v1/activate "$results_dir/main-certificate-source.json" \
    "$results_dir/main-active-source.json"
  control_get /v1/state "$results_dir/main-control-after-source-activate.json"
  control_get /v1/history "$results_dir/main-control-history-after-source-activate.json"
else
  "${compose[@]}" up --detach --wait --wait-timeout 180 temporal payment completion
  write_native_absence main "$results_dir/main-native-absence.json"
fi

"${compose[@]}" up --detach --wait --wait-timeout 180 worker-v1
wait_poller workflow food-order-v1 safe-change-food-order-v1-worker \
  "$results_dir/main-source-workflow-pollers.json"
wait_poller activity food-order-v1 safe-change-food-order-v1-worker \
  "$results_dir/main-source-activity-pollers.json"
temporal_json "$results_dir/main-deployment-before-current.json" worker deployment describe \
  --name safe-change-food-order-worker
wait_deployment_version_task_queues \
  safe-change-food-order-worker food-order-v1 safe-change-food-orders \
  "$results_dir/main-source-version-before-current.json"
temporal_json "$results_dir/main-set-current-source.json" worker deployment set-current-version \
  --deployment-name safe-change-food-order-worker --build-id food-order-v1 --yes
temporal_json "$results_dir/main-deployment-source-current.json" worker deployment describe \
  --name safe-change-food-order-worker
jq -e '
  .routingConfig.currentVersionDeploymentName == "safe-change-food-order-worker" and
  .routingConfig.currentVersionBuildID == "food-order-v1"
' "$results_dir/main-deployment-source-current.json" >/dev/null

workflow_id="$main_workflow_id"
order_id="$main_order_id"
payment_token="$order_id"
[[ "$payment_token" == "$order_id" ]] || {
  echo "payment_token must equal order_id" >&2
  exit 64
}
start_workflow main
wait_workflow_phase food-order-v1 IN_PREPARATION main-cut
provider_stats payment "$results_dir/main-payment-cut-stats.json"
provider_stats completion "$results_dir/main-completion-cut-stats.json"
capture_provider_history main cut
jq -e '.deliveries == 1 and .commits == 1 and .paths == {"/v1/charge":1}' \
  "$results_dir/main-payment-cut-stats.json" >/dev/null
jq -e '.deliveries == 0 and .commits == 0 and .paths == {}' \
  "$results_dir/main-completion-cut-stats.json" >/dev/null
jq -e '
  [.events[] | select(.eventType == "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED") |
    .activityTaskScheduledEventAttributes.activityType.name] ==
    ["ChargePayment","PrepareFood"] and
  ([.events[] | select(.eventType == "EVENT_TYPE_ACTIVITY_TASK_COMPLETED")] | length) == 2 and
  ([.events[] | select(.eventType == "EVENT_TYPE_TIMER_STARTED")] | length) == 1 and
  ([.events[] | select(.eventType == "EVENT_TYPE_TIMER_FIRED")] | length) == 1 and
  ([.events[] | select(.eventType == "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED" and
    .activityTaskScheduledEventAttributes.activityType.name == "ChargePaymentV2")] | length) == 0 and
  ([.events[] | select(.eventType == "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED" and
    .activityTaskScheduledEventAttributes.activityType.name == "ScheduleDelivery")] | length) == 0 and
  ([.events[] | select(.eventType == "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED" and
    .activityTaskScheduledEventAttributes.activityType.name == "CompleteOrder")] | length) == 0 and
  ([.events[] | select(.eventType == "EVENT_TYPE_WORKFLOW_EXECUTION_SIGNALED")] | length) == 0 and
  ([.events[] | select(.eventType == "EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED")] | length) == 0
' "$results_dir/main-cut-history.json" >/dev/null
temporal_json "$results_dir/main-cut-deployment.json" worker deployment describe \
  --name safe-change-food-order-worker
temporal_json "$results_dir/main-cut-source-version.json" worker deployment describe-version \
  --deployment-name safe-change-food-order-worker --build-id food-order-v1
main_source_container="$("${compose[@]}" ps --quiet worker-v1)"
docker inspect "$main_source_container" >"$results_dir/main-source-container-at-cut.json"
jq -e --arg image "$WORKER_V1_ID" '
  length == 1 and .[0].State.Running == true and .[0].Image == $image
' "$results_dir/main-source-container-at-cut.json" >/dev/null

"${compose[@]}" ps --all --quiet worker-unsafe-v2 \
  >"$results_dir/main-target-containers-before-decision.txt"
"${compose[@]}" ps --all --quiet worker-v2 \
  >"$results_dir/main-worker-v2-containers-before-decision.txt"
if [[ -s "$results_dir/main-target-containers-before-decision.txt" ||
      -s "$results_dir/main-worker-v2-containers-before-decision.txt" ]]; then
  echo "a target worker existed before the main decision" >&2
  exit 1
fi
mapfile -t main_cut_containers < <(
  docker ps --all --quiet --filter "label=com.docker.compose.project=$compose_project" | sort
)
docker inspect "${main_cut_containers[@]}" >"$results_dir/main-containers-before-decision.json"
mapfile -t main_cut_networks < <(
  docker network ls --quiet --filter "label=com.docker.compose.project=$compose_project" | sort
)
docker network inspect "${main_cut_networks[@]}" >"$results_dir/main-networks-before-decision.json"

probe_jsonl="$case_root/main-network-probes.jsonl"
: >"$probe_jsonl"
if [[ "$method" == proposed ]]; then
  main_payment_ip="$(service_ip_for_network payment effects)"
  main_completion_ip="$(service_ip_for_network completion effects)"
  main_control_ip="$(service_ip_for_network unsafe-control source-runtime)"
  network_probe main worker-v1 source-adapter true http://source-adapter:8790/healthz
  network_probe main worker-v1 payment-dns-denied false http://payment:8081/healthz
  network_probe main worker-v1 payment-ip-denied false "http://$main_payment_ip:8081/healthz"
  network_probe main worker-v1 completion-dns-denied false http://completion:8081/healthz
  network_probe main worker-v1 completion-ip-denied false "http://$main_completion_ip:8081/healthz"
  network_probe main worker-v1 control-dns-denied false http://unsafe-control:8787/healthz
  network_probe main worker-v1 control-ip-denied false "http://$main_control_ip:8787/healthz"
  network_probe main source-adapter control true http://unsafe-control:8787/healthz
  network_probe main source-adapter payment-dns-denied false http://payment:8081/healthz
  network_probe main source-adapter payment-ip-denied false "http://$main_payment_ip:8081/healthz"
  network_probe main unsafe-control payment true http://payment:8081/healthz
  network_probe main unsafe-control completion true http://completion:8081/healthz
else
  network_probe main worker-v1 payment true http://payment:8081/healthz
  network_probe main worker-v1 completion true http://completion:8081/healthz
  network_probe main worker-v1 control false http://unsafe-control:8787/healthz
  network_probe main worker-v1 adapter false http://source-adapter:8790/healthz
fi
finish_network_probes main

if [[ "$method" == proposed ]]; then
  control_get /v1/state "$results_dir/main-control-at-cut.json"
  control_get /v1/history "$results_dir/main-control-history-at-cut.json"
  jq -e '
    .requirement.id == "temporal-unsafe-source-v1" and .rule.version == 1 and
    .rule.allow == ["finish-v1"] and
    ([.operations[] | select(.kind == "charge-v1" and .phase == "succeeded")] | length) == 1 and
    ([.operations[] | select(.kind == "finish-v1")] | length) == 0
  ' "$results_dir/main-control-at-cut.json" >/dev/null
fi
date --utc --iso-8601=ns >"$results_dir/main-decision-requested-at.txt"

if [[ "$method" == proposed ]]; then
  control_post /v1/compile "$results_dir/requirement-target.json" \
    "$results_dir/main-certificate-unsafe.json"
  jq -e '
    .decision == "impossible" and .rule == null and
    .requirement.id == "temporal-unsafe-target-v2" and
    .witness == {reason:"no completion fits the remaining resources for delivered:1"}
  ' "$results_dir/main-certificate-unsafe.json" >/dev/null
  control_post /v1/certificate-state "$results_dir/main-certificate-unsafe.json" \
    "$results_dir/main-certificate-unsafe-state.json"
  check_certificate "$results_dir/main-certificate-unsafe-state.json" \
    "$results_dir/main-certificate-unsafe.json" \
    "$results_dir/main-certificate-unsafe-verdict.json"
  jq -e '.valid == true and .decision == "impossible"' \
    "$results_dir/main-certificate-unsafe-verdict.json" >/dev/null
  control_get /v1/state "$results_dir/main-control-after-refusal.json"
  control_get /v1/history "$results_dir/main-control-history-after-refusal.json"
  cmp -- "$results_dir/main-control-at-cut.json" "$results_dir/main-control-after-refusal.json"
  cmp -- "$results_dir/main-control-history-at-cut.json" \
    "$results_dir/main-control-history-after-refusal.json"
  date --utc --iso-8601=ns >"$results_dir/main-decision-recorded-at.txt"
  workflow_show "$results_dir/main-history-after-decision.json"
  cmp -- "$results_dir/main-cut-history.json" "$results_dir/main-history-after-decision.json"
  provider_stats payment "$results_dir/main-payment-after-decision-stats.json"
  provider_stats completion "$results_dir/main-completion-after-decision-stats.json"
  capture_provider_history main after-decision
  cmp -- "$results_dir/main-payment-cut-stats.json" \
    "$results_dir/main-payment-after-decision-stats.json"
  cmp -- "$results_dir/main-completion-cut-stats.json" \
    "$results_dir/main-completion-after-decision-stats.json"
  cmp -- "$results_dir/main-payment-cut.history" \
    "$results_dir/main-payment-after-decision.history"
  cmp -- "$results_dir/main-completion-cut.history" \
    "$results_dir/main-completion-after-decision.history"
  mapfile -t services_after_refusal < <(
    docker ps --all --filter "label=com.docker.compose.project=$compose_project" \
      --format '{{.Label "com.docker.compose.service"}}' | sort -u
  )
  target_after_refusal="$("${compose[@]}" ps --all --quiet worker-unsafe-v2)"
  worker_v2_after_refusal="$("${compose[@]}" ps --all --quiet worker-v2)"
  target_adapter_after_refusal="$("${compose[@]}" ps --all --quiet target-adapter)"
  jq -n --arg target "$target_after_refusal" --arg base "$worker_v2_after_refusal" \
    --arg target_adapter "$target_adapter_after_refusal" \
    --argjson present "$(printf '%s\n' "${services_after_refusal[@]}" | jq -Rsc 'split("\n")[:-1]')" '
    {schema:1,phase:"main",absent_services:["target-adapter","worker-unsafe-v2","worker-v2"],
      target_container_ids:(if $target == "" then [] else [$target] end),
      target_adapter_container_ids:(if $target_adapter == "" then [] else [$target_adapter] end),
      base_worker_v2_container_ids:(if $base == "" then [] else [$base] end),
      present_services:$present}
    | select(.target_container_ids == [] and .target_adapter_container_ids == [] and
        .base_worker_v2_container_ids == [])
  ' >"$results_dir/main-proposed-target-absence.json"
  [[ -s "$results_dir/main-proposed-target-absence.json" ]] || {
    echo "proposed target appeared during rejected compilation" >&2
    exit 1
  }
else
  date --utc --iso-8601=ns >"$results_dir/main-decision-recorded-at.txt"
  "${compose[@]}" rm --stop --force worker-v1 >"$results_dir/main-remove-source.txt"
  set +e
  docker inspect "$main_source_container" \
    >"$results_dir/main-source-removed-inspect.json" \
    2>"$results_dir/main-source-removed-inspect.stderr"
  source_removed_status=$?
  set -e
  printf '%s\n' "$source_removed_status" \
    >"$results_dir/main-source-removed-inspect-status.txt"
  if [[ "$source_removed_status" == 0 ||
        -n "$("${compose[@]}" ps --all --quiet worker-v1)" ]]; then
    echo "native source worker was not removed before target start" >&2
    exit 1
  fi
  "${compose[@]}" up --detach --wait --wait-timeout 180 worker-unsafe-v2
  wait_poller workflow food-order-unsafe-v2 safe-change-food-order-unsafe-v2-worker \
    "$results_dir/main-target-workflow-pollers.json"
  wait_poller activity food-order-unsafe-v2 safe-change-food-order-unsafe-v2-worker \
    "$results_dir/main-target-activity-pollers.json"
  wait_deployment_version_task_queues \
    safe-change-food-order-worker food-order-unsafe-v2 safe-change-food-orders \
    "$results_dir/main-target-version-before-current.json"
  temporal_json "$results_dir/main-set-current-target.json" worker deployment set-current-version \
    --deployment-name safe-change-food-order-worker --build-id food-order-unsafe-v2 --yes
  temporal_json "$results_dir/main-deployment-target-current.json" worker deployment describe \
    --name safe-change-food-order-worker
  jq -e '
    .routingConfig.currentVersionDeploymentName == "safe-change-food-order-worker" and
    .routingConfig.currentVersionBuildID == "food-order-unsafe-v2"
  ' "$results_dir/main-deployment-target-current.json" >/dev/null
  main_target_container="$("${compose[@]}" ps --quiet worker-unsafe-v2)"
  docker inspect "$main_target_container" >"$results_dir/main-target-container.json"
  jq -e --arg image "$TEMPORAL_UNSAFE_WORKER_ID" '
    length == 1 and .[0].State.Running == true and .[0].Image == $image
  ' "$results_dir/main-target-container.json" >/dev/null
  workflow_show "$results_dir/main-history-after-decision.json"
  cmp -- "$results_dir/main-cut-history.json" "$results_dir/main-history-after-decision.json"
  provider_stats payment "$results_dir/main-payment-after-decision-stats.json"
  provider_stats completion "$results_dir/main-completion-after-decision-stats.json"
  capture_provider_history main after-decision
  cmp -- "$results_dir/main-payment-cut-stats.json" \
    "$results_dir/main-payment-after-decision-stats.json"
  cmp -- "$results_dir/main-completion-cut-stats.json" \
    "$results_dir/main-completion-after-decision-stats.json"
  cmp -- "$results_dir/main-payment-cut.history" \
    "$results_dir/main-payment-after-decision.history"
  cmp -- "$results_dir/main-completion-cut.history" \
    "$results_dir/main-completion-after-decision.history"
fi

signal_business_stages main "$signal_identity"
if [[ "$method" == proposed ]]; then
  final_build=food-order-v1
  expected_final_build_completions=4
else
  final_build=food-order-unsafe-v2
  expected_final_build_completions=2
fi
wait_workflow_phase "$final_build" DELIVERED main-final
provider_stats payment "$results_dir/main-payment-final-stats.json"
provider_stats completion "$results_dir/main-completion-final-stats.json"
capture_provider_history main final
cmp -- "$results_dir/main-payment-cut.history" "$results_dir/main-payment-final.history"
jq -e '.deliveries == 1 and .commits == 1 and .paths == {"/v1/charge":1}' \
  "$results_dir/main-payment-final-stats.json" >/dev/null
jq -e '.deliveries == 1 and .commits == 1 and .paths == {"/v1/complete":1}' \
  "$results_dir/main-completion-final-stats.json" >/dev/null
jq -e --arg identity "safe-change-${final_build}-worker" \
  --argjson expected_final_build_completions "$expected_final_build_completions" '
  ([.events[] | select(.eventType == "EVENT_TYPE_WORKFLOW_TASK_FAILED")] | length) == 0 and
  [.events[] | select(.eventType == "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED") |
    .activityTaskScheduledEventAttributes.activityType.name] ==
    ["ChargePayment","PrepareFood","ScheduleDelivery","CompleteOrder"] and
  ([.events[] | select(.eventType == "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED" and
    .activityTaskScheduledEventAttributes.activityType.name == "ChargePaymentV2")] | length) == 0 and
  [.events[] | select(.eventType == "EVENT_TYPE_WORKFLOW_EXECUTION_SIGNALED") |
    .workflowExecutionSignaledEventAttributes.signalName] ==
    ["preparation_finished","driver_selected","driver_at_restaurant","delivery_finished"] and
  ([.events[] | select(.eventType == "EVENT_TYPE_ACTIVITY_TASK_COMPLETED")] | length) == 4 and
  ([.events[] | select(.eventType == "EVENT_TYPE_ACTIVITY_TASK_COMPLETED" and
    .activityTaskCompletedEventAttributes.identity == $identity)] | length) ==
    $expected_final_build_completions and
  ([.events[] | select(.eventType == "EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED")] | length) == 1
' "$results_dir/main-final-history.json" >/dev/null
temporal_json "$results_dir/main-deployment-final.json" worker deployment describe \
  --name safe-change-food-order-worker

if [[ "$method" == proposed ]]; then
  docker inspect "$main_source_container" >"$results_dir/main-final-source-container.json"
  temporal_json "$results_dir/main-final-source-version.json" worker deployment describe-version \
    --deployment-name safe-change-food-order-worker --build-id food-order-v1
  control_get /v1/state "$results_dir/main-final-control-state.json"
  control_get /v1/history "$results_dir/main-final-control-history.json"
  cp -- "$UNSAFE_CONTROL_STATE_DIR/runtime.history" "$results_dir/main-runtime.history"
  cp -- "$UNSAFE_CONTROL_ANCHOR_DIR/runtime.head" "$results_dir/main-runtime.head"
  jq -e '
    .requirement.id == "temporal-unsafe-source-v1" and
    ([.operations[] | select(.kind == "charge-v1" and .phase == "succeeded")] | length) == 1 and
    ([.operations[] | select(.kind == "finish-v1" and .phase == "succeeded")] | length) == 1
  ' "$results_dir/main-final-control-state.json" >/dev/null
  [[ -z "$("${compose[@]}" ps --all --quiet worker-unsafe-v2)" ]] || {
    echo "refused target was started" >&2
    exit 1
  }
else
  temporal_json "$results_dir/main-target-version-final.json" worker deployment describe-version \
    --deployment-name safe-change-food-order-worker --build-id food-order-unsafe-v2
  write_native_absence main "$results_dir/main-native-absence.json"
fi

capture_topology main
end_events main
if [[ "$method" == proposed ]]; then
  jq -s -e '
    all(.[];
      (.Actor.Attributes["com.docker.compose.service"] // "") != "worker-v2" and
      (.Actor.Attributes["com.docker.compose.service"] // "") != "worker-unsafe-v2" and
      (.Actor.Attributes["com.docker.compose.service"] // "") != "target-adapter")
  ' "$results_dir/main-docker-events.jsonl" >/dev/null
else
  jq -s -e --arg source "$main_source_container" '
    all(.[]; (.Actor.Attributes["com.docker.compose.service"] // "") != "worker-v2") and
    ([.[] | select(.Type == "container" and .Action == "destroy" and .Actor.ID == $source)] | length) == 1 and
    ([.[] | select(.Type == "container" and .Action == "create" and
      .Actor.Attributes["com.docker.compose.service"] == "worker-unsafe-v2")] | length) == 1 and
    ([.[] | select(.Type == "container" and .Action == "start" and
      .Actor.Attributes["com.docker.compose.service"] == "worker-unsafe-v2")] | length) == 1 and
    ([.[] | select(.Type == "container" and .Action == "destroy" and .Actor.ID == $source)][0].timeNano) <
    ([.[] | select(.Type == "container" and .Action == "create" and
      .Actor.Attributes["com.docker.compose.service"] == "worker-unsafe-v2")][0].timeNano)
  ' "$results_dir/main-docker-events.jsonl" >/dev/null
fi

read -r runner_sha256 _ <"$results_dir/runner.sha256"
build_sha256="$(sha256sum -- "$results_dir/build.env" | awk '{print $1}')"
jq -n --arg method "$method" --arg state_root "$case_root" \
  --arg clean_project "$clean_project" --arg main_project "$main_project" \
  --arg clean_workflow_id "$clean_workflow_id" --arg main_workflow_id "$main_workflow_id" \
  --arg clean_order_id "$clean_order_id" --arg main_order_id "$main_order_id" \
  --arg restaurant_id "$restaurant_id" --arg product_id "$product_id" \
  --arg product_description "$product_description" --argjson product_quantity "$product_quantity" \
  --argjson delivery_delay_millis "$delivery_delay_millis" --argjson amount_cents "$amount_cents" \
  --arg driver_id "$driver_id" \
  --arg clean_payment_operation_id "$clean_payment_operation_id" \
  --arg clean_completion_operation_id "$clean_completion_operation_id" \
  --arg main_payment_operation_id "$main_payment_operation_id" \
  --arg main_completion_operation_id "$main_completion_operation_id" \
  --arg source_image "$WORKER_V1_ID" --arg target_image "$TEMPORAL_UNSAFE_WORKER_ID" \
  --arg adapter_image "$TEMPORAL_UNSAFE_ADAPTER_ID" \
  --arg control_image "$SAFE_CHANGE_CONTROL_IMAGE" \
  --arg build_env "$build_env" --arg build_sha256 "$build_sha256" \
  --arg runner_sha256 "$runner_sha256" --arg signal_identity "$signal_identity" \
  --arg source_requirement_sha256 "$(sha256sum -- "$results_dir/requirement-source.json" | awk '{print $1}')" \
  --arg target_requirement_sha256 "$(sha256sum -- "$results_dir/requirement-target.json" | awk '{print $1}')" \
  --arg source_adapter_sha256 "$(sha256sum -- "$results_dir/source-adapter.json" | awk '{print $1}')" \
  --arg target_adapter_sha256 "$(sha256sum -- "$results_dir/target-adapter.json" | awk '{print $1}')" \
  --arg base_compose_sha256 "$(sha256sum -- "$results_dir/compose-base.yaml" | awk '{print $1}')" \
  --arg overlay_sha256 "$(sha256sum -- "$results_dir/compose-overlay.yaml" | awk '{print $1}')" \
  --arg frozen_inputs_sha256 "$(sha256sum -- "$results_dir/frozen-inputs.env" | awk '{print $1}')" \
  --arg versions_sha256 "$(sha256sum -- "$results_dir/versions.env" | awk '{print $1}')" \
  --arg artifact_contract_sha256 "$(sha256sum -- "$results_dir/ARTIFACTS.md" | awk '{print $1}')" '
  {schema:1,cell:"temporal-history-dependent-unsafe-edit",method:$method,
    state_root:$state_root,clean_project:$clean_project,main_project:$main_project,
    clean_workflow_id:$clean_workflow_id,main_workflow_id:$main_workflow_id,
    clean_order_id:$clean_order_id,main_order_id:$main_order_id,
    projects:{clean:$clean_project,main:$main_project},
    clean:{workflow_id:$clean_workflow_id,order_id:$clean_order_id,
      restaurant_id:$restaurant_id,
      products:[{product_id:$product_id,description:$product_description,quantity:$product_quantity}],
      delivery_delay_millis:$delivery_delay_millis,amount_cents:$amount_cents,
      payment_token:$clean_order_id,
      delivery_id:("delivery-" + $clean_order_id),driver_id:$driver_id,
      operation_ids:{payment:$clean_payment_operation_id,
        completion:$clean_completion_operation_id}},
    main:{workflow_id:$main_workflow_id,order_id:$main_order_id,
      restaurant_id:$restaurant_id,
      products:[{product_id:$product_id,description:$product_description,quantity:$product_quantity}],
      delivery_delay_millis:$delivery_delay_millis,amount_cents:$amount_cents,
      payment_token:$main_order_id,
      delivery_id:("delivery-" + $main_order_id),driver_id:$driver_id,
      operation_ids:{payment:$main_payment_operation_id,
        completion:$main_completion_operation_id}},
    source_image:$source_image,target_image:$target_image,adapter_image:$adapter_image,
    control_image:$control_image,build_env:$build_env,build_sha256:$build_sha256,
    runner_sha256:$runner_sha256,skip_build:true,signal_identity:$signal_identity,
    signal_names:["preparation_finished","driver_selected","driver_at_restaurant","delivery_finished"],
    input_sha256:{source_requirement:$source_requirement_sha256,
      target_requirement:$target_requirement_sha256,source_adapter:$source_adapter_sha256,
      target_adapter:$target_adapter_sha256,base_compose:$base_compose_sha256,
      overlay:$overlay_sha256,frozen_inputs:$frozen_inputs_sha256,
      versions:$versions_sha256,artifact_contract:$artifact_contract_sha256}}
' >"$results_dir/run-metadata.json"

if [[ "$method" == proposed ]]; then
  main_decision=impossible
  target_started=false
  external_requirement_violated=false
  source_completed=true
else
  main_decision=native-completed
  target_started=true
  external_requirement_violated=true
  source_completed=false
fi
jq -n --arg method "$method" --arg main_decision "$main_decision" \
  --argjson target_started "$target_started" \
  --argjson external_requirement_violated "$external_requirement_violated" \
  --argjson source_completed "$source_completed" \
  --arg clean_run_id "$(<"$results_dir/clean-run-id.txt")" \
  --arg main_run_id "$(<"$results_dir/main-run-id.txt")" '
  {schema:1,cell:"temporal-history-dependent-unsafe-edit",method:$method,
    clean_run_id:$clean_run_id,main_run_id:$main_run_id,
    clean_target_completed:true,main_decision:$main_decision,
    target_started:$target_started,source_completed:$source_completed,
    external_requirement_violated:$external_requirement_violated}
' >"$results_dir/observed.json"

current_phase=complete
jq . "$results_dir/observed.json"
