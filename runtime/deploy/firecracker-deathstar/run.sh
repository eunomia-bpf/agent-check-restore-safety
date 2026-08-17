#!/usr/bin/env bash
set -Eeuo pipefail

readonly DEATHSTAR_REPOSITORY="https://github.com/delimitrou/DeathStarBench.git"
readonly DEATHSTAR_TAG="hotelReservation-0.3.5"
readonly DEATHSTAR_COMMIT="6ecb09706140f8730b5385c08f1386c654c3c526"
readonly PROJECT="safe-change-firecracker-deathstar-step22"
readonly APPLICATION_IMAGE="safe-change-step22/deathstar:hotel-reservation-0.3.5"
readonly RUNTIME_IMAGE="safe-change-step22/runtime:local"
readonly FRONTDOOR_NETWORK="safe-change-step22-frontdoor"
readonly OBSERVATION_NETWORK="safe-change-step22-observation"
readonly FRONTEND="safe-change-step22-frontend"
readonly EFFECT="safe-change-step22-effect"
readonly OBSERVER="safe-change-step22-observer"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/../../.." && pwd)"
runtime_root="$repo_root/runtime"
work_dir="$(mktemp -d /tmp/safe-change-fc-dsb-step22.XXXXXX)"

: "${CELL_BINARY:?CELL_BINARY is required}"
: "${GUEST_BINARY:?GUEST_BINARY is required}"
: "${PAYLOAD:?PAYLOAD is required}"
: "${PAYLOAD_RESULT:?PAYLOAD_RESULT is required}"
: "${CLAUDE_BINARY:?CLAUDE_BINARY is required}"
: "${CLAUDE_SHA256:?CLAUDE_SHA256 is required}"
: "${CONTROL_BINARY:?CONTROL_BINARY is required}"
: "${EFFECT_PROXY_BINARY:?EFFECT_PROXY_BINARY is required}"
: "${EVIDENCE_DIR:?EVIDENCE_DIR is required}"
BUSYBOX="${BUSYBOX:-/usr/bin/busybox}"
REPETITIONS="${REPETITIONS:-3}"

for command in curl docker git go jq python3 realpath sha256sum; do
  command -v "$command" >/dev/null || { echo "missing required command: $command" >&2; exit 1; }
done
docker compose version >/dev/null
for path in "$CELL_BINARY" "$GUEST_BINARY" "$PAYLOAD" "$PAYLOAD_RESULT" "$CLAUDE_BINARY" \
  "$CONTROL_BINARY" "$EFFECT_PROXY_BINARY" "$BUSYBOX"; do
  [[ -f "$path" && ! -L "$path" ]] || { echo "required direct file is missing: $path" >&2; exit 1; }
done
[[ -c /dev/kvm && -r /dev/kvm && -w /dev/kvm ]] || { echo "read/write /dev/kvm is required" >&2; exit 1; }

EVIDENCE_DIR="$(realpath -m "$EVIDENCE_DIR")"
if [[ -e "$EVIDENCE_DIR" ]]; then
  echo "refusing to overwrite evidence directory: $EVIDENCE_DIR" >&2
  exit 1
fi
mkdir -m 0700 -p "$EVIDENCE_DIR"
mkdir -m 0700 "$EVIDENCE_DIR/docker"
run_succeeded=0
compose=()

save_logs() {
  local name=$1
  docker logs "$name" > "$EVIDENCE_DIR/docker/$name.log" 2>&1 || true
}

cleanup() {
  local status=$?
  trap - EXIT
  for name in "$OBSERVER" "$EFFECT" "$FRONTEND"; do
    save_logs "$name"
    docker rm -f "$name" >/dev/null 2>&1 || true
  done
  if ((${#compose[@]})); then
    "${compose[@]}" logs --no-color > "$EVIDENCE_DIR/docker/official-compose.log" 2>&1 || true
    "${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
  fi
  docker network rm "$FRONTDOOR_NETWORK" "$OBSERVATION_NETWORK" >/dev/null 2>&1 || true
  case "$work_dir" in
    /tmp/safe-change-fc-dsb-step22.*) rm -rf -- "$work_dir" ;;
    *) echo "refusing unexpected work directory cleanup: $work_dir" >&2 ;;
  esac
  echo "evidence directory: $EVIDENCE_DIR" >&2
  exit "$status"
}
trap cleanup EXIT

for name in "$FRONTEND" "$EFFECT" "$OBSERVER"; do
  if docker container inspect "$name" >/dev/null 2>&1; then
    echo "fixed Step 22 container exists: $name" >&2
    exit 1
  fi
done
for network in "$FRONTDOOR_NETWORK" "$OBSERVATION_NETWORK"; do
  if docker network inspect "$network" >/dev/null 2>&1; then
    echo "fixed Step 22 network exists: $network" >&2
    exit 1
  fi
done
if [[ -n "$(docker ps -aq --filter "label=com.docker.compose.project=$PROJECT")" ]]; then
  echo "fixed Step 22 Compose project exists" >&2
  exit 1
fi

git clone --quiet --filter=blob:none --no-checkout "$DEATHSTAR_REPOSITORY" "$work_dir/repository"
resolved="$(git -C "$work_dir/repository" rev-parse "refs/tags/$DEATHSTAR_TAG^{commit}")"
[[ "$resolved" == "$DEATHSTAR_COMMIT" ]]
git -C "$work_dir/repository" sparse-checkout init --cone
git -C "$work_dir/repository" sparse-checkout set hotelReservation
git -C "$work_dir/repository" checkout --quiet --detach "$DEATHSTAR_COMMIT"
chmod 0644 "$work_dir/repository/hotelReservation/config.json"
[[ -z "$(git -C "$work_dir/repository" status --porcelain -- hotelReservation)" ]]
tree="$(git -C "$work_dir/repository" rev-parse "$DEATHSTAR_COMMIT:hotelReservation")"

docker build \
  --label "org.opencontainers.image.source=$DEATHSTAR_REPOSITORY" \
  --label "org.opencontainers.image.revision=$DEATHSTAR_COMMIT" \
  -t "$APPLICATION_IMAGE" "$work_dir/repository/hotelReservation" \
  > "$EVIDENCE_DIR/docker/build-deathstar.log" 2>&1
runtime_status="$(git -C "$repo_root" status --porcelain=v1 --untracked-files=all -- runtime adapter Makefile)"
runtime_tree_hash="$(git -C "$repo_root" diff --binary -- runtime adapter Makefile | sha256sum | cut -d' ' -f1)"
docker build \
  --build-arg "SOURCE_REVISION=$(git -C "$repo_root" rev-parse HEAD)" \
  --build-arg "SOURCE_TREE_SHA256=$runtime_tree_hash" \
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
application_network_id="$(docker network ls -q \
  --filter "label=com.docker.compose.project=$PROJECT" \
  --filter 'label=com.docker.compose.network=default')"
[[ -n "$application_network_id" && "$(wc -w <<< "$application_network_id")" -eq 1 ]]
application_network="$(docker network inspect -f '{{.Name}}' "$application_network_id")"
mongo_container="$("${compose[@]}" ps -q mongodb-reservation)"
[[ -n "$mongo_container" ]]

docker network create --label safe-change.step=22 "$FRONTDOOR_NETWORK" >/dev/null
docker network create --label safe-change.step=22 "$OBSERVATION_NETWORK" >/dev/null
docker network connect --alias reservation-mongo "$OBSERVATION_NETWORK" "$mongo_container"
docker run -d --name "$FRONTEND" --network "$application_network" \
  --label safe-change.step=22 \
  --mount "type=bind,src=$work_dir/repository/hotelReservation/config.json,dst=/config.json,readonly" \
  "$APPLICATION_IMAGE" /go/bin/frontend >/dev/null
docker network connect --alias frontend-v2 "$FRONTDOOR_NETWORK" "$FRONTEND"

for _ in $(seq 1 180); do
  login="$(docker run --rm --network "$FRONTDOOR_NETWORK" "$RUNTIME_IMAGE" \
    sh -c "wget -qO- -T 3 'http://frontend-v2:5000/user?username=Cornell_30&password=0000000000'" 2>/dev/null || true)"
  if jq -e '.message == "Login successfully!"' >/dev/null 2>&1 <<< "$login"; then break; fi
  sleep 1
done
jq -e '.message == "Login successfully!"' >/dev/null <<< "$login"

for _ in $(seq 1 180); do
  all_running=true
  while IFS= read -r service; do
    [[ "$service" == frontend ]] && continue
    container_id="$("${compose[@]}" ps -q "$service")"
    if [[ -z "$container_id" ]] || [[ "$(docker inspect -f '{{.State.Running}}' "$container_id" 2>/dev/null || true)" != true ]]; then
      all_running=false
      break
    fi
  done < "$EVIDENCE_DIR/docker/official-services.txt"
  [[ "$all_running" == true ]] && break
  sleep 1
done
[[ "$all_running" == true ]]

adapter_audit="$EVIDENCE_DIR/deathstar-adapter.audit.jsonl"
: > "$adapter_audit"
chmod 0600 "$adapter_audit"
uid="$(id -u)"
gid="$(id -g)"
docker run -d --name "$EFFECT" --user "$uid:$gid" --network "$FRONTDOOR_NETWORK" \
  --label safe-change.step=22 -p 127.0.0.1::8090 \
  --mount "type=bind,src=$adapter_audit,dst=/adapter.audit.jsonl" \
  "$RUNTIME_IMAGE" deathstar-adapter -mode effect -listen 0.0.0.0:8090 \
  -frontend http://frontend-v2:5000 -audit /adapter.audit.jsonl -post-commit-delay 8s >/dev/null
docker run -d --name "$OBSERVER" --user "$uid:$gid" --network "$OBSERVATION_NETWORK" \
  --label safe-change.step=22 -p 127.0.0.1::8090 \
  "$RUNTIME_IMAGE" deathstar-adapter -mode observer -listen 0.0.0.0:8090 \
  -mongo-uri mongodb://reservation-mongo:27017 >/dev/null
effect_address="$(docker port "$EFFECT" 8090/tcp)"
observer_address="$(docker port "$OBSERVER" 8090/tcp)"
[[ "$effect_address" == 127.0.0.1:* && "$observer_address" == 127.0.0.1:* ]]
effect_url="http://$effect_address/v1/reserve"
observer_url="http://$observer_address/v1/query"
for origin in "http://$effect_address" "http://$observer_address"; do
  for _ in $(seq 1 120); do
    if curl --noproxy '*' -fsS "$origin/healthz" >/dev/null; then break; fi
    sleep 0.5
  done
  curl --noproxy '*' -fsS "$origin/healthz" >/dev/null
done

official_running="$(docker ps -q --filter "label=com.docker.compose.project=$PROJECT" | wc -l)"
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

python3 -m adapter.firecracker_deathstar_egress_demo \
  --cell-binary "$CELL_BINARY" --guest-binary "$GUEST_BINARY" \
  --payload "$PAYLOAD" --payload-result "$PAYLOAD_RESULT" \
  --claude-binary "$CLAUDE_BINARY" --claude-sha256 "$CLAUDE_SHA256" \
  --busybox "$BUSYBOX" --control-binary "$CONTROL_BINARY" \
  --effect-proxy-binary "$EFFECT_PROXY_BINARY" --effect-url "$effect_url" \
  --observer-url "$observer_url" --adapter-audit "$adapter_audit" \
  --graph-evidence "$EVIDENCE_DIR/graph.json" \
  --evidence-dir "$EVIDENCE_DIR/runtime" --repetitions "$REPETITIONS" \
  > "$EVIDENCE_DIR/driver-result.json"

jq -e '.valid == true' "$EVIDENCE_DIR/runtime/result.json" >/dev/null
docker inspect "$FRONTEND" "$EFFECT" "$OBSERVER" > "$EVIDENCE_DIR/docker/custom-containers.json"
"${compose[@]}" ps --format json > "$EVIDENCE_DIR/docker/official-ps.jsonl"
docker image inspect "$APPLICATION_IMAGE" "$RUNTIME_IMAGE" > "$EVIDENCE_DIR/docker/images.json"
jq -n --slurpfile graph "$EVIDENCE_DIR/graph.json" --slurpfile runtime "$EVIDENCE_DIR/runtime/result.json" '{
  schema:1,graph:$graph[0],runtime:$runtime[0],pass:($graph[0].pass and $runtime[0].valid)
}' > "$EVIDENCE_DIR/result.json"
jq -e '.pass == true' "$EVIDENCE_DIR/result.json" >/dev/null
run_succeeded=1
jq . "$EVIDENCE_DIR/result.json"
