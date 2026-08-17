#!/usr/bin/env bash
set -Eeuo pipefail

readonly DEATHSTAR_REPOSITORY="https://github.com/delimitrou/DeathStarBench.git"
readonly DEATHSTAR_TAG="hotelReservation-0.3.5"
readonly DEATHSTAR_COMMIT="6ecb09706140f8730b5385c08f1386c654c3c526"
readonly PROJECT="safe-change-firecracker-history-step25"
readonly APPLICATION_IMAGE="safe-change-step25/deathstar:hotel-reservation-0.3.5"
readonly RUNTIME_IMAGE="safe-change-step25/runtime:local"
readonly FRONTDOOR_NETWORK="safe-change-step25-frontdoor"
readonly OBSERVATION_NETWORK="safe-change-step25-observation"
readonly FRONTEND="safe-change-step25-frontend"
readonly OBSERVER="safe-change-step25-observer"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/../../.." && pwd)"
runtime_root="$repo_root/runtime"
work_dir="$(mktemp -d /tmp/safe-change-firecracker-history-step25.XXXXXX)"

: "${PROTECTED_CELL_BINARY:?PROTECTED_CELL_BINARY is required}"
: "${BASELINE_CELL_BINARY:?BASELINE_CELL_BINARY is required}"
: "${GUEST_BINARY:?GUEST_BINARY is required}"
: "${PAYLOAD:?PAYLOAD is required}"
: "${PAYLOAD_RESULT:?PAYLOAD_RESULT is required}"
: "${CLAUDE_BINARY:?CLAUDE_BINARY is required}"
: "${CLAUDE_SHA256:?CLAUDE_SHA256 is required}"
: "${CONTROL_BINARY:?CONTROL_BINARY is required}"
: "${EFFECT_PROXY_BINARY:?EFFECT_PROXY_BINARY is required}"
: "${DEATHSTAR_ADAPTER_BINARY:?DEATHSTAR_ADAPTER_BINARY is required}"
: "${CERTIFICATE_CHECKER_BINARY:?CERTIFICATE_CHECKER_BINARY is required}"
: "${EVIDENCE_DIR:?EVIDENCE_DIR is required}"
BUSYBOX="${BUSYBOX:-/usr/bin/busybox}"
REPETITIONS="${REPETITIONS:-3}"
PREFLIGHT_GATE="${PREFLIGHT_GATE:-}"
EVIDENCE_CHECKER="${EVIDENCE_CHECKER:-$repo_root/adapter/check_firecracker_history_start_evidence.py}"
RUN_TIMEOUT_SECONDS="${RUN_TIMEOUT_SECONDS:-}"

for command in curl date docker git go id jq python3 realpath setsid sha256sum sort timeout wc; do
  command -v "$command" >/dev/null || { echo "missing required command: $command" >&2; exit 1; }
done
docker compose version >/dev/null
for path in "$PROTECTED_CELL_BINARY" "$BASELINE_CELL_BINARY" "$GUEST_BINARY" "$PAYLOAD" \
  "$PAYLOAD_RESULT" "$CLAUDE_BINARY" "$CONTROL_BINARY" "$EFFECT_PROXY_BINARY" \
  "$DEATHSTAR_ADAPTER_BINARY" "$CERTIFICATE_CHECKER_BINARY" "$BUSYBOX"; do
  [[ -f "$path" && ! -L "$path" ]] || { echo "required direct file is missing: $path" >&2; exit 1; }
done
[[ -c /dev/kvm && -r /dev/kvm && -w /dev/kvm ]] || { echo "read/write /dev/kvm is required" >&2; exit 1; }
[[ "$REPETITIONS" =~ ^[1-5]$ ]] || { echo "REPETITIONS must be between one and five" >&2; exit 1; }
[[ "$(sha256sum "$CLAUDE_BINARY" | cut -d' ' -f1)" == "$CLAUDE_SHA256" ]]
[[ "$(sha256sum "$PROTECTED_CELL_BINARY" | cut -d' ' -f1)" != "$(sha256sum "$BASELINE_CELL_BINARY" | cut -d' ' -f1)" ]] || {
  echo "protected and baseline cell binaries must differ" >&2
  exit 1
}
if ((REPETITIONS > 1)); then
  [[ -n "$PREFLIGHT_GATE" ]] || { echo "PREFLIGHT_GATE is required for a full matrix" >&2; exit 1; }
  python3 -I "$repo_root/adapter/qemu_agent_restore_gate.py" verify \
    --repo-root "$repo_root" --gate "$PREFLIGHT_GATE" --checker "$EVIDENCE_CHECKER" \
    --certificate-checker "$CERTIFICATE_CHECKER_BINARY" >/dev/null
  if [[ -z "$RUN_TIMEOUT_SECONDS" ]]; then
    RUN_TIMEOUT_SECONDS="$(jq -er '(.preflight_elapsed_seconds * 3 + 900) | ceil | if . < 1800 then 1800 elif . > 14400 then 14400 else . end' "$PREFLIGHT_GATE")"
  fi
fi
RUN_TIMEOUT_SECONDS="${RUN_TIMEOUT_SECONDS:-5400}"
[[ "$RUN_TIMEOUT_SECONDS" =~ ^[1-9][0-9]*$ ]] || { echo "RUN_TIMEOUT_SECONDS must be positive" >&2; exit 1; }

EVIDENCE_DIR="$(realpath -m "$EVIDENCE_DIR")"
[[ ! -e "$EVIDENCE_DIR" ]] || { echo "refusing to overwrite evidence: $EVIDENCE_DIR" >&2; exit 1; }
mkdir -m 0700 -p "$EVIDENCE_DIR/docker" "$EVIDENCE_DIR/terminal-fences"
adapter_audit="$EVIDENCE_DIR/deathstar-adapter.audit.jsonl"
: > "$adapter_audit"
chmod 0600 "$adapter_audit"
compose=()
driver_pid=""
driver_started_time_ns=0
driver_finished_time_ns=0
driver_status=1
timed_out=false
started_time_ns="$(date +%s%N)"

save_logs() {
  local name=$1
  timeout --kill-after=5s 20s docker logs "$name" > "$EVIDENCE_DIR/docker/$name.log" 2>&1 || true
}

stop_driver() {
  [[ -n "$driver_pid" ]] || return 0
  kill -INT -- "-$driver_pid" 2>/dev/null || true
  for _ in $(seq 1 100); do
    kill -0 "$driver_pid" 2>/dev/null || break
    sleep 0.1
  done
  kill -KILL -- "-$driver_pid" 2>/dev/null || true
  wait "$driver_pid" 2>/dev/null || true
  driver_pid=""
}

write_execution() {
  local finished_time_ns
  finished_time_ns="$(date +%s%N)"
  jq -n --argjson started "$started_time_ns" --argjson driver_started "$driver_started_time_ns" \
    --argjson driver_finished "$driver_finished_time_ns" --argjson finished "$finished_time_ns" \
    --argjson status "$driver_status" --argjson timeout_seconds "$RUN_TIMEOUT_SECONDS" --argjson timed_out "$timed_out" '{
      schema:1,overall_started_time_ns:$started,driver_started_time_ns:$driver_started,
      driver_finished_time_ns:$driver_finished,overall_finished_time_ns:$finished,
      total_duration_seconds:(($finished-$started)/1000000000),
      driver_duration_seconds:(if $driver_finished >= $driver_started then ($driver_finished-$driver_started)/1000000000 else 0 end),
      driver_exit_status:$status,timeout_seconds:$timeout_seconds,timed_out:$timed_out
    }' > "$EVIDENCE_DIR/execution.json"
  chmod 0600 "$EVIDENCE_DIR/execution.json"
}

cleanup() {
  local status=$?
  trap - EXIT INT TERM
  stop_driver || status=1
  if [[ -d "$EVIDENCE_DIR/runtime" && ! -e "$EVIDENCE_DIR/residual-processes.json" ]]; then
    python3 -I "$repo_root/adapter/firecracker_history_cleanup.py" \
      --evidence "$EVIDENCE_DIR/runtime" --terminate > "$EVIDENCE_DIR/residual-processes.json" || status=1
    chmod 0600 "$EVIDENCE_DIR/residual-processes.json" 2>/dev/null || true
  fi
  for name in "$OBSERVER" "$FRONTEND"; do
    save_logs "$name"
    docker rm -f "$name" >/dev/null 2>&1 || true
  done
  if ((${#compose[@]})); then
    "${compose[@]}" logs --no-color > "$EVIDENCE_DIR/docker/official-compose.log" 2>&1 || true
    "${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
  fi
  docker network rm "$FRONTDOOR_NETWORK" "$OBSERVATION_NETWORK" >/dev/null 2>&1 || true
  case "$work_dir" in
    /tmp/safe-change-firecracker-history-step25.*) rm -rf -- "$work_dir" ;;
    *) echo "refusing unexpected work directory cleanup: $work_dir" >&2; status=1 ;;
  esac
  [[ -e "$EVIDENCE_DIR/execution.json" ]] || write_execution
  echo "evidence directory: $EVIDENCE_DIR" >&2
  exit "$status"
}
trap cleanup EXIT
trap 'timed_out=true; exit 124' INT TERM

for name in "$FRONTEND" "$OBSERVER"; do
  ! docker container inspect "$name" >/dev/null 2>&1 || { echo "fixed Step 25 container exists: $name" >&2; exit 1; }
done
for network in "$FRONTDOOR_NETWORK" "$OBSERVATION_NETWORK"; do
  ! docker network inspect "$network" >/dev/null 2>&1 || { echo "fixed Step 25 network exists: $network" >&2; exit 1; }
done
[[ -z "$(docker ps -aq --filter "label=com.docker.compose.project=$PROJECT")" ]] || { echo "fixed Step 25 Compose project exists" >&2; exit 1; }

git clone --quiet --filter=blob:none --no-checkout "$DEATHSTAR_REPOSITORY" "$work_dir/repository"
resolved="$(git -C "$work_dir/repository" rev-parse "refs/tags/$DEATHSTAR_TAG^{commit}")"
[[ "$resolved" == "$DEATHSTAR_COMMIT" ]]
git -C "$work_dir/repository" sparse-checkout init --cone
git -C "$work_dir/repository" sparse-checkout set hotelReservation
git -C "$work_dir/repository" checkout --quiet --detach "$DEATHSTAR_COMMIT"
chmod 0644 "$work_dir/repository/hotelReservation/config.json"
[[ -z "$(git -C "$work_dir/repository" status --porcelain -- hotelReservation)" ]]
tree="$(git -C "$work_dir/repository" rev-parse "$DEATHSTAR_COMMIT:hotelReservation")"

docker build --label "org.opencontainers.image.source=$DEATHSTAR_REPOSITORY" \
  --label "org.opencontainers.image.revision=$DEATHSTAR_COMMIT" \
  -t "$APPLICATION_IMAGE" "$work_dir/repository/hotelReservation" \
  > "$EVIDENCE_DIR/docker/build-deathstar.log" 2>&1
runtime_status="$(git -C "$repo_root" status --porcelain=v1 --untracked-files=all -- runtime adapter Makefile)"
python3 -I "$repo_root/adapter/qemu_agent_restore_gate.py" manifest \
  --repo-root "$repo_root" --output "$EVIDENCE_DIR/source-manifest.json" >/dev/null
runtime_tree_hash="$(jq -er '.root_sha256' "$EVIDENCE_DIR/source-manifest.json")"
source_revision="$(git -C "$repo_root" rev-parse HEAD)"
docker build --build-arg "SOURCE_REVISION=$source_revision" --build-arg "SOURCE_TREE_SHA256=$runtime_tree_hash" \
  -f "$runtime_root/deploy/microservice/Dockerfile" -t "$RUNTIME_IMAGE" "$runtime_root" \
  > "$EVIDENCE_DIR/docker/build-runtime.log" 2>&1
application_image_id="$(docker image inspect -f '{{.Id}}' "$APPLICATION_IMAGE")"
runtime_image_id="$(docker image inspect -f '{{.Id}}' "$RUNTIME_IMAGE")"

export DEATHSTAR_V2_IMAGE="$APPLICATION_IMAGE"
compose=(docker compose -p "$PROJECT" \
  -f "$work_dir/repository/hotelReservation/docker-compose.yml" \
  -f "$runtime_root/deploy/deathstar/compose.override.yaml")
"${compose[@]}" config > "$EVIDENCE_DIR/docker/compose-config.yaml"
"${compose[@]}" config --services | sort > "$EVIDENCE_DIR/docker/official-services.txt"
[[ "$(wc -l < "$EVIDENCE_DIR/docker/official-services.txt")" -eq 24 ]]
"${compose[@]}" up -d --no-build --scale frontend=0
application_network_id="$(docker network ls -q --filter "label=com.docker.compose.project=$PROJECT" --filter 'label=com.docker.compose.network=default')"
[[ -n "$application_network_id" && "$(wc -w <<< "$application_network_id")" -eq 1 ]]
application_network="$(docker network inspect -f '{{.Name}}' "$application_network_id")"
mongo_container="$("${compose[@]}" ps -q mongodb-reservation)"
[[ -n "$mongo_container" ]]

docker network create --label safe-change.step=25 "$FRONTDOOR_NETWORK" >/dev/null
docker network create --label safe-change.step=25 "$OBSERVATION_NETWORK" >/dev/null
docker network connect --alias reservation-mongo "$OBSERVATION_NETWORK" "$mongo_container"
docker run -d --name "$FRONTEND" --network "$application_network" --label safe-change.step=25 \
  -p 127.0.0.1::5000 \
  --mount "type=bind,src=$work_dir/repository/hotelReservation/config.json,dst=/config.json,readonly" \
  "$APPLICATION_IMAGE" /go/bin/frontend >/dev/null
docker network connect --alias frontend-v2 "$FRONTDOOR_NETWORK" "$FRONTEND"
frontend_address="$(docker port "$FRONTEND" 5000/tcp)"
[[ "$frontend_address" == 127.0.0.1:* ]]
for _ in $(seq 1 180); do
  login="$(curl --noproxy '*' --connect-timeout 2 --max-time 5 -fsS "http://$frontend_address/user?username=Cornell_30&password=0000000000" 2>/dev/null || true)"
  jq -e '.message == "Login successfully!"' >/dev/null 2>&1 <<< "$login" && break
  sleep 1
done
jq -e '.message == "Login successfully!"' >/dev/null <<< "$login"

for _ in $(seq 1 180); do
  all_running=true
  while IFS= read -r service; do
    [[ "$service" == frontend ]] && continue
    container_id="$("${compose[@]}" ps -q "$service")"
    [[ -n "$container_id" && "$(docker inspect -f '{{.State.Running}}' "$container_id" 2>/dev/null || true)" == true ]] || { all_running=false; break; }
  done < "$EVIDENCE_DIR/docker/official-services.txt"
  [[ "$all_running" == true ]] && break
  sleep 1
done
[[ "$all_running" == true ]]

# Container state is not application readiness. Exercise the exact reservation
# dependency chain once with a separately identifiable customer before any
# measured lane. The experiment's Mongo predicates cannot match this customer,
# but this traffic intentionally shares the application's hotel inventory.
readiness_url="http://$frontend_address/reservation?inDate=2015-04-09&outDate=2015-04-10&hotelId=1&customerName=step25-readiness&username=Cornell_30&password=0000000000&number=1"
readiness_response="$(curl --noproxy '*' --connect-timeout 5 --max-time 90 -fsS "$readiness_url")"
jq -e '.message == "Reserve successfully!"' >/dev/null <<< "$readiness_response"
jq -n --arg customer_name step25-readiness --argjson response "$readiness_response" \
  --argjson observed_time_ns "$(date +%s%N)" '{
    schema:1,customer_name:$customer_name,response:$response,observed_time_ns:$observed_time_ns,
    separately_identifiable_from_measured_operations:true,shares_application_inventory:true
  }' > "$EVIDENCE_DIR/reservation-readiness.json"
chmod 0600 "$EVIDENCE_DIR/reservation-readiness.json"

uid="$(id -u)"
gid="$(id -g)"
docker run -d --name "$OBSERVER" --user "$uid:$gid" --network "$OBSERVATION_NETWORK" \
  --label safe-change.step=25 -p 127.0.0.1::8090 \
  --mount "type=bind,src=$EVIDENCE_DIR/terminal-fences,dst=/terminal-fences" \
  "$RUNTIME_IMAGE" deathstar-adapter -mode observer -listen 0.0.0.0:8090 \
  -mongo-uri mongodb://reservation-mongo:27017 -terminal-fence-directory /terminal-fences >/dev/null
observer_address="$(docker port "$OBSERVER" 8090/tcp)"
[[ "$observer_address" == 127.0.0.1:* ]]
for _ in $(seq 1 120); do
  curl --noproxy '*' --connect-timeout 2 --max-time 5 -fsS "http://$observer_address/healthz" >/dev/null 2>&1 && break
  sleep 0.5
done
curl --noproxy '*' -fsS "http://$observer_address/healthz" >/dev/null
observer_url="http://$observer_address/v1/query"
effect_port="$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')"
effect_address="127.0.0.1:$effect_port"
official_running="$(docker ps -q --filter "label=com.docker.compose.project=$PROJECT" | wc -l)"
jq -n --arg repository "$DEATHSTAR_REPOSITORY" --arg tag "$DEATHSTAR_TAG" --arg commit "$DEATHSTAR_COMMIT" \
  --arg tree "$tree" --arg application_image "$APPLICATION_IMAGE" --arg application_image_id "$application_image_id" \
  --arg runtime_image "$RUNTIME_IMAGE" --arg runtime_image_id "$runtime_image_id" --arg runtime_tree_hash "$runtime_tree_hash" \
  --arg runtime_status "$runtime_status" --arg application_network "$application_network" \
  --arg frontdoor_network "$FRONTDOOR_NETWORK" --arg observation_network "$OBSERVATION_NETWORK" \
  --argjson official_running "$official_running" '{
    schema:1,repository:$repository,tag:$tag,commit:$commit,tree:$tree,
    official_services:24,official_compose_running:$official_running,compose_frontend_scaled_to_zero:true,
    custom_unmodified_frontend_running:true,application_image:$application_image,application_image_id:$application_image_id,
    runtime_image:$runtime_image,runtime_image_id:$runtime_image_id,runtime_tree_hash:$runtime_tree_hash,runtime_status:$runtime_status,
    networks:{application:$application_network,frontdoor:$frontdoor_network,observation:$observation_network},
    source_modified:false,pass:($commit == "6ecb09706140f8730b5385c08f1386c654c3c526" and $official_running == 23)
  }' > "$EVIDENCE_DIR/graph.json"
jq -e '.pass == true' "$EVIDENCE_DIR/graph.json" >/dev/null

driver_started_time_ns="$(date +%s%N)"
setsid timeout --signal=INT --kill-after=30s "${RUN_TIMEOUT_SECONDS}s" python3 -m adapter.firecracker_history_start_demo \
  --protected-cell-binary "$PROTECTED_CELL_BINARY" --baseline-cell-binary "$BASELINE_CELL_BINARY" \
  --guest-binary "$GUEST_BINARY" --payload "$PAYLOAD" --payload-result "$PAYLOAD_RESULT" \
  --claude-binary "$CLAUDE_BINARY" --claude-sha256 "$CLAUDE_SHA256" --busybox "$BUSYBOX" \
  --control-binary "$CONTROL_BINARY" --effect-proxy-binary "$EFFECT_PROXY_BINARY" \
  --deathstar-adapter-binary "$DEATHSTAR_ADAPTER_BINARY" --frontend-url "http://$frontend_address" \
  --effect-address "$effect_address" --observer-url "$observer_url" --adapter-audit "$adapter_audit" \
  --fence-directory "$EVIDENCE_DIR/terminal-fences" --graph-evidence "$EVIDENCE_DIR/graph.json" \
  --evidence-dir "$EVIDENCE_DIR/runtime" --repetitions "$REPETITIONS" \
  > "$EVIDENCE_DIR/driver-result.json" 2> "$EVIDENCE_DIR/driver.stderr.log" &
driver_pid=$!
chmod 0600 "$EVIDENCE_DIR/driver-result.json" "$EVIDENCE_DIR/driver.stderr.log"
set +e
wait "$driver_pid"
driver_status=$?
set -e
driver_pid=""
driver_finished_time_ns="$(date +%s%N)"
((driver_status != 124)) || timed_out=true
write_execution
((driver_status == 0)) || exit "$driver_status"

python3 -I "$repo_root/adapter/firecracker_history_cleanup.py" \
  --evidence "$EVIDENCE_DIR/runtime" --terminate > "$EVIDENCE_DIR/residual-processes.json"
chmod 0600 "$EVIDENCE_DIR/residual-processes.json"
jq -e '.valid == true and (.residual_before | length) == 0 and (.terminated_pids | length) == 0 and .checked_sessions == ('"$REPETITIONS"' * 6)' \
  "$EVIDENCE_DIR/residual-processes.json" >/dev/null
jq -e '.valid == true' "$EVIDENCE_DIR/runtime/result.json" >/dev/null
docker inspect "$FRONTEND" "$OBSERVER" > "$EVIDENCE_DIR/docker/custom-containers.json"
"${compose[@]}" ps --format json > "$EVIDENCE_DIR/docker/official-ps.jsonl"
docker image inspect "$APPLICATION_IMAGE" "$RUNTIME_IMAGE" > "$EVIDENCE_DIR/docker/images.json"
jq -n --slurpfile graph "$EVIDENCE_DIR/graph.json" --slurpfile runtime "$EVIDENCE_DIR/runtime/result.json" '{
  schema:1,graph:$graph[0],runtime:$runtime[0],pass:($graph[0].pass and $runtime[0].valid)
}' > "$EVIDENCE_DIR/result.json"
jq -e '.pass == true' "$EVIDENCE_DIR/result.json" >/dev/null
python3 -I "$EVIDENCE_CHECKER" --evidence "$EVIDENCE_DIR" \
  --certificate-checker "$CERTIFICATE_CHECKER_BINARY" --expected-repetitions "$REPETITIONS" \
  > "$EVIDENCE_DIR/independent-check.json"
jq -e '.valid == true' "$EVIDENCE_DIR/independent-check.json" >/dev/null
jq . "$EVIDENCE_DIR/result.json"
