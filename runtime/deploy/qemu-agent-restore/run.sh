#!/usr/bin/env bash
set -Eeuo pipefail

readonly DEATHSTAR_REPOSITORY="https://github.com/delimitrou/DeathStarBench.git"
readonly DEATHSTAR_TAG="hotelReservation-0.3.5"
readonly DEATHSTAR_COMMIT="6ecb09706140f8730b5385c08f1386c654c3c526"
readonly PROJECT="safe-change-qemu-agent-restore-step24"
readonly APPLICATION_IMAGE="safe-change-step24/deathstar:hotel-reservation-0.3.5"
readonly RUNTIME_IMAGE="safe-change-step24/runtime:local"
readonly FRONTDOOR_NETWORK="safe-change-step24-frontdoor"
readonly OBSERVATION_NETWORK="safe-change-step24-observation"
readonly FRONTEND="safe-change-step24-frontend"
readonly OBSERVER="safe-change-step24-observer"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/../../.." && pwd)"
runtime_root="$repo_root/runtime"
work_dir="$(mktemp -d /tmp/safe-change-qemu-agent-restore-step24.XXXXXX)"

: "${QEMU_BINARY:?QEMU_BINARY is required}"
: "${CLAUDE_BINARY:?CLAUDE_BINARY is required}"
: "${CLAUDE_SHA256:?CLAUDE_SHA256 is required}"
: "${CONTROL_BINARY:?CONTROL_BINARY is required}"
: "${EFFECT_PROXY_BINARY:?EFFECT_PROXY_BINARY is required}"
: "${DEATHSTAR_ADAPTER_BINARY:?DEATHSTAR_ADAPTER_BINARY is required}"
: "${UBUNTU_IMAGE:?UBUNTU_IMAGE is required}"
: "${UBUNTU_IMAGE_SHA256:?UBUNTU_IMAGE_SHA256 is required}"
: "${EVIDENCE_DIR:?EVIDENCE_DIR is required}"
REPETITIONS="${REPETITIONS:-3}"
QEMU_ACCEL="${QEMU_ACCEL:-kvm}"
PREFLIGHT_GATE="${PREFLIGHT_GATE:-}"
EVIDENCE_CHECKER="${EVIDENCE_CHECKER:-$repo_root/adapter/check_qemu_agent_restore_evidence.py}"
RUN_TIMEOUT_SECONDS="${RUN_TIMEOUT_SECONDS:-}"

for command in awk cp curl cut date docker git go head id jq ps python3 realpath seq setsid sha256sum sleep sort timeout tr wc; do
  command -v "$command" >/dev/null || { echo "missing required command: $command" >&2; exit 1; }
done
docker compose version >/dev/null
for path in "$QEMU_BINARY" "$CLAUDE_BINARY" "$CONTROL_BINARY" "$EFFECT_PROXY_BINARY" \
  "$DEATHSTAR_ADAPTER_BINARY" "$UBUNTU_IMAGE"; do
  [[ -f "$path" && ! -L "$path" ]] || { echo "required direct file is missing: $path" >&2; exit 1; }
done
[[ "$(sha256sum "$CLAUDE_BINARY" | cut -d' ' -f1)" == "$CLAUDE_SHA256" ]]
[[ "$(sha256sum "$UBUNTU_IMAGE" | cut -d' ' -f1)" == "$UBUNTU_IMAGE_SHA256" ]]
if ((REPETITIONS > 1)); then
  [[ -n "$PREFLIGHT_GATE" ]] || { echo "PREFLIGHT_GATE is required for a full matrix" >&2; exit 1; }
  : "${CERTIFICATE_CHECKER_BINARY:?CERTIFICATE_CHECKER_BINARY is required for a full matrix}"
  python3 -I "$repo_root/adapter/qemu_agent_restore_gate.py" verify \
    --repo-root "$repo_root" --gate "$PREFLIGHT_GATE" --checker "$EVIDENCE_CHECKER" \
    --certificate-checker "$CERTIFICATE_CHECKER_BINARY" >/dev/null
  if [[ -z "$RUN_TIMEOUT_SECONDS" ]]; then
    RUN_TIMEOUT_SECONDS="$(jq -er '(.preflight_elapsed_seconds * 3 + 900) | ceil | if . < 1800 then 1800 elif . > 14400 then 14400 else . end' "$PREFLIGHT_GATE")"
  fi
fi
RUN_TIMEOUT_SECONDS="${RUN_TIMEOUT_SECONDS:-7200}"
[[ "$RUN_TIMEOUT_SECONDS" =~ ^[1-9][0-9]*$ ]] || { echo "RUN_TIMEOUT_SECONDS must be a positive integer" >&2; exit 1; }
overall_started_time_ns="$(date +%s%N)"
overall_started_seconds="$(date +%s)"
if [[ "$QEMU_ACCEL" == kvm ]]; then
  [[ -c /dev/kvm && -r /dev/kvm && -w /dev/kvm ]] || { echo "read/write /dev/kvm is required" >&2; exit 1; }
fi

EVIDENCE_DIR="$(realpath -m "$EVIDENCE_DIR")"
if [[ -e "$EVIDENCE_DIR" ]]; then
  echo "refusing to overwrite evidence directory: $EVIDENCE_DIR" >&2
  exit 1
fi
mkdir -m 0700 -p "$EVIDENCE_DIR"
mkdir -m 0700 "$EVIDENCE_DIR/docker" "$EVIDENCE_DIR/terminal-fences"
adapter_audit="$EVIDENCE_DIR/deathstar-adapter.audit.jsonl"
: > "$adapter_audit"
chmod 0600 "$adapter_audit"
: > "$EVIDENCE_DIR/heartbeat.jsonl"
chmod 0600 "$EVIDENCE_DIR/heartbeat.jsonl"
compose=()
driver_pid=""
monitor_pid=""
stage_path="$EVIDENCE_DIR/stage"
deadline_path="$EVIDENCE_DIR/deadline-expired"
monitor_stop_path="$EVIDENCE_DIR/monitor-stop-requested"
monitor_failure_path="$EVIDENCE_DIR/monitor-failed"
deadline_seconds=$((overall_started_seconds + RUN_TIMEOUT_SECONDS))

set_stage() {
  printf '%s\n' "$1" > "$stage_path"
  chmod 0600 "$stage_path"
}

bounded() {
  local now remaining
  now="$(date +%s)"
  remaining=$((deadline_seconds - now))
  if ((remaining <= 0)); then
    return 124
  fi
  timeout --signal=TERM --kill-after=15s "${remaining}s" "$@"
}

monitor_run() {
  local parent_pid=$1
  trap 'monitor_status=$?; if [[ ! -e "$monitor_stop_path" ]]; then printf "%s\n" "$monitor_status" > "$monitor_failure_path"; kill -TERM "$parent_pid" 2>/dev/null || true; fi' EXIT
  while kill -0 "$parent_pid" 2>/dev/null; do
    local heartbeat_time_ns stage
    heartbeat_time_ns="$(date +%s%N)"
    stage="$(head -n 1 "$stage_path" 2>/dev/null || echo unknown)"
    jq -cn --argjson time_ns "$heartbeat_time_ns" --arg stage "$stage" \
      '{schema:1,time_ns:$time_ns,stage:$stage}' >> "$EVIDENCE_DIR/heartbeat.jsonl"
    if (( $(date +%s) - overall_started_seconds >= RUN_TIMEOUT_SECONDS )); then
      printf '%s\n' "$heartbeat_time_ns" > "$deadline_path"
      chmod 0600 "$deadline_path"
      kill -TERM "$parent_pid" 2>/dev/null || true
      return
    fi
    for _ in $(seq 1 30); do
      [[ -e "$monitor_stop_path" ]] && return 0
      sleep 1
    done
  done
}

child_stopped() {
  local pid=$1 state
  [[ -r "/proc/$pid/stat" ]] || return 0
  state="$(ps -o stat= -p "$pid" 2>/dev/null | tr -d '[:space:]' || true)"
  [[ -z "$state" || "$state" == Z* ]]
}

wait_for_child_stop() {
  local pid=$1 attempts=$2
  for _ in $(seq 1 "$attempts"); do
    child_stopped "$pid" && return 0
    sleep 0.1
  done
  return 1
}

process_group_stopped() {
  local process_group=$1
  ps -eo pgid=,stat= | awk -v target="$process_group" '
    $1 == target && $2 !~ /^Z/ { active = 1 }
    END { exit active ? 1 : 0 }
  '
}

wait_for_process_group_stop() {
  local process_group=$1 attempts=$2
  for _ in $(seq 1 "$attempts"); do
    process_group_stopped "$process_group" && return 0
    sleep 0.1
  done
  return 1
}

stop_driver() {
  [[ -n "$driver_pid" ]] || return
  kill -INT -- "-$driver_pid" 2>/dev/null || true
  if ! wait_for_process_group_stop "$driver_pid" 600; then
    kill -TERM -- "-$driver_pid" 2>/dev/null || true
  fi
  if ! wait_for_process_group_stop "$driver_pid" 150; then
    kill -KILL -- "-$driver_pid" 2>/dev/null || true
  fi
  wait_for_process_group_stop "$driver_pid" 50 || return 1
  wait_for_child_stop "$driver_pid" 50 || return 1
  wait "$driver_pid" 2>/dev/null || true
}

stop_monitor() {
  [[ -n "$monitor_pid" ]] || return
  printf '%s\n' "$(date +%s%N)" > "$monitor_stop_path"
  chmod 0600 "$monitor_stop_path"
  if ! wait_for_child_stop "$monitor_pid" 20; then
    kill -TERM "$monitor_pid" 2>/dev/null || true
  fi
  if ! wait_for_child_stop "$monitor_pid" 20; then
    kill -KILL "$monitor_pid" 2>/dev/null || true
  fi
  wait_for_child_stop "$monitor_pid" 50 || return 1
  set +e
  wait "$monitor_pid"
  monitor_exit_status=$?
  set -e
  monitor_pid=""
  [[ ! -e "$monitor_failure_path" ]] || return 1
  jq -n --argjson exit_status "$monitor_exit_status" --argjson unexpected_failure "$((monitor_exit_status != 0))" \
    '{schema:1,stopped_by_launcher:true,unexpected_failure:($unexpected_failure == 1),exit_status:$exit_status}' \
    > "$EVIDENCE_DIR/monitor-status.json"
  chmod 0600 "$EVIDENCE_DIR/monitor-status.json"
  ((monitor_exit_status == 0))
}

save_logs() {
  local name=$1
  timeout --kill-after=5s 20s docker logs "$name" > "$EVIDENCE_DIR/docker/$name.log" 2>&1 || true
}

write_execution() {
  local overall_finished_time_ns=$1 driver_finished_time_ns=$2 driver_exit_status=$3 timed_out=$4
  jq -n --argjson overall_started_time_ns "$overall_started_time_ns" \
    --argjson driver_started_time_ns "$driver_started_time_ns" --argjson driver_finished_time_ns "$driver_finished_time_ns" \
    --argjson overall_finished_time_ns "$overall_finished_time_ns" --argjson exit_status "$driver_exit_status" \
    --argjson timeout_seconds "$RUN_TIMEOUT_SECONDS" --argjson timed_out "$timed_out" \
    '{schema:1,overall_started_time_ns:$overall_started_time_ns,driver_started_time_ns:$driver_started_time_ns,
    driver_finished_time_ns:$driver_finished_time_ns,overall_finished_time_ns:$overall_finished_time_ns,
    total_duration_seconds:(($overall_finished_time_ns-$overall_started_time_ns)/1000000000),
    driver_duration_seconds:(($driver_finished_time_ns-$driver_started_time_ns)/1000000000),
    driver_exit_status:$exit_status,timeout_seconds:$timeout_seconds,timed_out:$timed_out}' \
    > "$EVIDENCE_DIR/execution.json"
  chmod 0600 "$EVIDENCE_DIR/execution.json"
}

cleanup() {
  local status=$?
  trap - EXIT TERM INT
  stop_monitor || status=1
  stop_driver || status=1
  if [[ -d "$EVIDENCE_DIR/runtime" && ! -e "$EVIDENCE_DIR/residual-processes.json" ]]; then
    timeout --kill-after=5s 20s python3 -I "$repo_root/adapter/qemu_agent_restore_cleanup.py" \
      --evidence "$EVIDENCE_DIR/runtime" --terminate > "$EVIDENCE_DIR/residual-processes.json" || status=1
    chmod 0600 "$EVIDENCE_DIR/residual-processes.json" 2>/dev/null || true
  fi
  for name in "$OBSERVER" "$FRONTEND"; do
    save_logs "$name"
    timeout --kill-after=5s 20s docker rm -f "$name" >/dev/null 2>&1 || true
  done
  if ((${#compose[@]})); then
    timeout --kill-after=5s 20s "${compose[@]}" logs --no-color > "$EVIDENCE_DIR/docker/official-compose.log" 2>&1 || true
    timeout --kill-after=5s 30s "${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
  fi
  timeout --kill-after=5s 20s docker network rm "$FRONTDOOR_NETWORK" "$OBSERVATION_NETWORK" >/dev/null 2>&1 || true
  case "$work_dir" in
    /tmp/safe-change-qemu-agent-restore-step24.*) rm -rf -- "$work_dir" ;;
    *) echo "refusing unexpected work directory cleanup: $work_dir" >&2 ;;
  esac
  if [[ -e "$deadline_path" ]]; then
    status=124
  fi
  echo "evidence directory: $EVIDENCE_DIR" >&2
  exit "$status"
}
trap cleanup EXIT
trap 'exit 124' TERM INT
set_stage infrastructure-preflight
monitor_run "$$" &
monitor_pid=$!

for name in "$FRONTEND" "$OBSERVER"; do
  if bounded docker container inspect "$name" >/dev/null 2>&1; then
    echo "fixed Step 24 container exists: $name" >&2
    exit 1
  else
    inspect_status=$?
    ((inspect_status == 124)) && exit 124
  fi
done
for network in "$FRONTDOOR_NETWORK" "$OBSERVATION_NETWORK"; do
  if bounded docker network inspect "$network" >/dev/null 2>&1; then
    echo "fixed Step 24 network exists: $network" >&2
    exit 1
  else
    inspect_status=$?
    ((inspect_status == 124)) && exit 124
  fi
done
if [[ -n "$(bounded docker ps -aq --filter "label=com.docker.compose.project=$PROJECT")" ]]; then
  echo "fixed Step 24 Compose project exists" >&2
  exit 1
fi

set_stage clone-deathstar
bounded git clone --quiet --filter=blob:none --no-checkout "$DEATHSTAR_REPOSITORY" "$work_dir/repository"
resolved="$(bounded git -C "$work_dir/repository" rev-parse "refs/tags/$DEATHSTAR_TAG^{commit}")"
[[ "$resolved" == "$DEATHSTAR_COMMIT" ]]
bounded git -C "$work_dir/repository" sparse-checkout init --cone
bounded git -C "$work_dir/repository" sparse-checkout set hotelReservation
bounded git -C "$work_dir/repository" checkout --quiet --detach "$DEATHSTAR_COMMIT"
chmod 0644 "$work_dir/repository/hotelReservation/config.json"
[[ -z "$(bounded git -C "$work_dir/repository" status --porcelain -- hotelReservation)" ]]
tree="$(bounded git -C "$work_dir/repository" rev-parse "$DEATHSTAR_COMMIT:hotelReservation")"

set_stage build-deathstar
bounded docker build \
  --label "org.opencontainers.image.source=$DEATHSTAR_REPOSITORY" \
  --label "org.opencontainers.image.revision=$DEATHSTAR_COMMIT" \
  -t "$APPLICATION_IMAGE" "$work_dir/repository/hotelReservation" \
  > "$EVIDENCE_DIR/docker/build-deathstar.log" 2>&1
set_stage build-runtime
runtime_status="$(bounded git -C "$repo_root" status --porcelain=v1 --untracked-files=all -- runtime adapter Makefile)"
bounded python3 -I "$repo_root/adapter/qemu_agent_restore_gate.py" manifest \
  --repo-root "$repo_root" --output "$EVIDENCE_DIR/source-manifest.json" >/dev/null
runtime_tree_hash="$(jq -er '.root_sha256' "$EVIDENCE_DIR/source-manifest.json")"
source_revision="$(bounded git -C "$repo_root" rev-parse HEAD)"
bounded docker build \
  --build-arg "SOURCE_REVISION=$source_revision" \
  --build-arg "SOURCE_TREE_SHA256=$runtime_tree_hash" \
  -f "$runtime_root/deploy/microservice/Dockerfile" -t "$RUNTIME_IMAGE" "$runtime_root" \
  > "$EVIDENCE_DIR/docker/build-runtime.log" 2>&1
application_image_id="$(bounded docker image inspect -f '{{.Id}}' "$APPLICATION_IMAGE")"
runtime_image_id="$(bounded docker image inspect -f '{{.Id}}' "$RUNTIME_IMAGE")"

export DEATHSTAR_V2_IMAGE="$APPLICATION_IMAGE"
set_stage deploy-deathstar
compose=(docker compose -p "$PROJECT" \
  -f "$work_dir/repository/hotelReservation/docker-compose.yml" \
  -f "$runtime_root/deploy/deathstar/compose.override.yaml")
bounded "${compose[@]}" config > "$EVIDENCE_DIR/docker/compose-config.yaml"
bounded "${compose[@]}" config --services | sort > "$EVIDENCE_DIR/docker/official-services.txt"
[[ "$(wc -l < "$EVIDENCE_DIR/docker/official-services.txt")" -eq 24 ]]
bounded "${compose[@]}" up -d --no-build --scale frontend=0
application_network_id="$(bounded docker network ls -q \
  --filter "label=com.docker.compose.project=$PROJECT" \
  --filter 'label=com.docker.compose.network=default')"
[[ -n "$application_network_id" && "$(wc -w <<< "$application_network_id")" -eq 1 ]]
application_network="$(bounded docker network inspect -f '{{.Name}}' "$application_network_id")"
mongo_container="$(bounded "${compose[@]}" ps -q mongodb-reservation)"
[[ -n "$mongo_container" ]]

bounded docker network create --label safe-change.step=24 "$FRONTDOOR_NETWORK" >/dev/null
bounded docker network create --label safe-change.step=24 "$OBSERVATION_NETWORK" >/dev/null
bounded docker network connect --alias reservation-mongo "$OBSERVATION_NETWORK" "$mongo_container"
bounded docker run -d --name "$FRONTEND" --network "$application_network" \
  --label safe-change.step=24 -p 127.0.0.1::5000 \
  --mount "type=bind,src=$work_dir/repository/hotelReservation/config.json,dst=/config.json,readonly" \
  "$APPLICATION_IMAGE" /go/bin/frontend >/dev/null
bounded docker network connect --alias frontend-v2 "$FRONTDOOR_NETWORK" "$FRONTEND"
frontend_address="$(bounded docker port "$FRONTEND" 5000/tcp)"
[[ "$frontend_address" == 127.0.0.1:* ]]

for _ in $(seq 1 180); do
  if login="$(bounded curl --noproxy '*' --connect-timeout 2 --max-time 5 -fsS "http://$frontend_address/user?username=Cornell_30&password=0000000000" 2>/dev/null)"; then
    :
  else
    request_status=$?
    ((request_status == 124)) && exit 124
    login=""
  fi
  if jq -e '.message == "Login successfully!"' >/dev/null 2>&1 <<< "$login"; then break; fi
  sleep 1
done
jq -e '.message == "Login successfully!"' >/dev/null <<< "$login"

for _ in $(seq 1 180); do
  all_running=true
  while IFS= read -r service; do
    [[ "$service" == frontend ]] && continue
    container_id="$(bounded "${compose[@]}" ps -q "$service")"
    if [[ -z "$container_id" ]]; then
      all_running=false
      break
    fi
    if container_running="$(bounded docker inspect -f '{{.State.Running}}' "$container_id" 2>/dev/null)"; then
      :
    else
      inspect_status=$?
      ((inspect_status == 124)) && exit 124
      container_running=""
    fi
    if [[ "$container_running" != true ]]; then
      all_running=false
      break
    fi
  done < "$EVIDENCE_DIR/docker/official-services.txt"
  [[ "$all_running" == true ]] && break
  sleep 1
done
[[ "$all_running" == true ]]

uid="$(id -u)"
gid="$(id -g)"
bounded docker run -d --name "$OBSERVER" --user "$uid:$gid" --network "$OBSERVATION_NETWORK" \
  --label safe-change.step=24 -p 127.0.0.1::8090 \
  --mount "type=bind,src=$EVIDENCE_DIR/terminal-fences,dst=/terminal-fences" \
  "$RUNTIME_IMAGE" deathstar-adapter -mode observer -listen 0.0.0.0:8090 \
  -mongo-uri mongodb://reservation-mongo:27017 -terminal-fence-directory /terminal-fences >/dev/null
observer_address="$(bounded docker port "$OBSERVER" 8090/tcp)"
[[ "$observer_address" == 127.0.0.1:* ]]
observer_url="http://$observer_address/v1/query"
for _ in $(seq 1 120); do
  if bounded curl --noproxy '*' --connect-timeout 2 --max-time 5 -fsS "http://$observer_address/healthz" >/dev/null; then
    break
  else
    health_status=$?
    ((health_status == 124)) && exit 124
  fi
  sleep 0.5
done
bounded curl --noproxy '*' --connect-timeout 2 --max-time 5 -fsS "http://$observer_address/healthz" >/dev/null

effect_port="$(bounded python3 -c 'import socket; listener=socket.socket(); listener.bind(("127.0.0.1", 0)); print(listener.getsockname()[1]); listener.close()')"
effect_address="127.0.0.1:$effect_port"
official_running="$(bounded docker ps -q --filter "label=com.docker.compose.project=$PROJECT" | wc -l)"
jq -n \
  --arg repository "$DEATHSTAR_REPOSITORY" --arg tag "$DEATHSTAR_TAG" --arg commit "$DEATHSTAR_COMMIT" \
  --arg tree "$tree" --arg application_image "$APPLICATION_IMAGE" --arg application_image_id "$application_image_id" \
  --arg runtime_image "$RUNTIME_IMAGE" --arg runtime_image_id "$runtime_image_id" \
  --arg runtime_tree_hash "$runtime_tree_hash" --arg runtime_status "$runtime_status" \
  --arg application_network "$application_network" --arg frontdoor_network "$FRONTDOOR_NETWORK" \
  --arg observation_network "$OBSERVATION_NETWORK" --argjson official_running "$official_running" '{
    schema:1,repository:$repository,tag:$tag,commit:$commit,tree:$tree,
    official_services:24,official_compose_running:$official_running,compose_frontend_scaled_to_zero:true,
    custom_unmodified_frontend_running:true,application_image:$application_image,
    application_image_id:$application_image_id,runtime_image:$runtime_image,runtime_image_id:$runtime_image_id,
    runtime_tree_hash:$runtime_tree_hash,runtime_status:$runtime_status,
    networks:{application:$application_network,frontdoor:$frontdoor_network,observation:$observation_network},
    source_modified:false,
    pass:($commit == "6ecb09706140f8730b5385c08f1386c654c3c526" and $official_running == 23)
  }' > "$EVIDENCE_DIR/graph.json"
jq -e '.pass == true' "$EVIDENCE_DIR/graph.json" >/dev/null

set_stage run-agent-matrix
driver_started_time_ns="$(date +%s%N)"
setsid python3 -m adapter.qemu_agent_restore_demo \
  --qemu-binary "$QEMU_BINARY" --image "$UBUNTU_IMAGE" --image-sha256 "$UBUNTU_IMAGE_SHA256" \
  --claude-binary "$CLAUDE_BINARY" --claude-sha256 "$CLAUDE_SHA256" \
  --control-binary "$CONTROL_BINARY" --effect-proxy-binary "$EFFECT_PROXY_BINARY" \
  --deathstar-adapter-binary "$DEATHSTAR_ADAPTER_BINARY" \
  --frontend-url "http://$frontend_address" --effect-address "$effect_address" \
  --observer-url "$observer_url" --adapter-audit "$adapter_audit" \
  --fence-directory "$EVIDENCE_DIR/terminal-fences" --graph-evidence "$EVIDENCE_DIR/graph.json" \
  --evidence-dir "$EVIDENCE_DIR/runtime" --repetitions "$REPETITIONS" --accel "$QEMU_ACCEL" \
  > "$EVIDENCE_DIR/driver-result.json" 2> "$EVIDENCE_DIR/driver.stderr.log" &
driver_pid=$!
chmod 0600 "$EVIDENCE_DIR/driver-result.json" "$EVIDENCE_DIR/driver.stderr.log"
driver_pgid="$(ps -o pgid= -p "$driver_pid" | tr -d '[:space:]')"
[[ "$driver_pgid" == "$driver_pid" ]] || { echo "Agent driver is not its own process-group leader" >&2; exit 1; }
driver_timed_out=false
while ! child_stopped "$driver_pid"; do
  if (( $(date +%s) >= deadline_seconds )); then
    driver_timed_out=true
    printf '%s\n' "$(date +%s%N)" > "$deadline_path"
    chmod 0600 "$deadline_path"
    stop_driver
    driver_pid=""
    break
  fi
  sleep 1
done
if [[ "$driver_timed_out" == true ]]; then
  driver_status=124
else
  set +e
  wait "$driver_pid"
  driver_status=$?
  set -e
  driver_pid=""
fi
driver_finished_ns="$(date +%s%N)"
if ((driver_status != 0)); then
  stop_monitor || driver_status=1
  overall_finished_ns="$(date +%s%N)"
  write_execution "$overall_finished_ns" "$driver_finished_ns" "$driver_status" "$driver_timed_out"
  exit "$driver_status"
fi
set_stage verify-process-cleanup
bounded python3 -I "$repo_root/adapter/qemu_agent_restore_cleanup.py" \
  --evidence "$EVIDENCE_DIR/runtime" --terminate > "$EVIDENCE_DIR/residual-processes.json"
chmod 0600 "$EVIDENCE_DIR/residual-processes.json"
jq -e '.valid == true and (.residual_before | length) == 0 and (.terminated_pids | length) == 0' \
  "$EVIDENCE_DIR/residual-processes.json" >/dev/null

set_stage retain-final-evidence
jq -e '.valid == true' "$EVIDENCE_DIR/runtime/result.json" >/dev/null
bounded docker inspect "$FRONTEND" "$OBSERVER" > "$EVIDENCE_DIR/docker/custom-containers.json"
bounded "${compose[@]}" ps --format json > "$EVIDENCE_DIR/docker/official-ps.jsonl"
bounded docker image inspect "$APPLICATION_IMAGE" "$RUNTIME_IMAGE" > "$EVIDENCE_DIR/docker/images.json"
jq -n --slurpfile graph "$EVIDENCE_DIR/graph.json" --slurpfile runtime "$EVIDENCE_DIR/runtime/result.json" '{
  schema:1,graph:$graph[0],runtime:$runtime[0],pass:($graph[0].pass and $runtime[0].valid)
}' > "$EVIDENCE_DIR/result.json"
jq -e '.pass == true' "$EVIDENCE_DIR/result.json" >/dev/null
set_stage complete
stop_monitor
overall_finished_ns="$(date +%s%N)"
write_execution "$overall_finished_ns" "$driver_finished_ns" "$driver_status" "$driver_timed_out"
jq . "$EVIDENCE_DIR/result.json"
