#!/usr/bin/env bash
set -Eeuo pipefail

readonly DEATHSTAR_REPOSITORY="https://github.com/delimitrou/DeathStarBench.git"
readonly V1_TAG="hotelReservation-0.2.2"
readonly V1_COMMIT="25ccc81c1f6a1e7fe4d6b726d6a310cd2b607fa9"
readonly V2_TAG="hotelReservation-0.3.5"
readonly V2_COMMIT="6ecb09706140f8730b5385c08f1386c654c3c526"
readonly PROJECT="safe-change-deathstar-step15"
readonly CONTROL_NETWORK="safe-change-step15-control"
readonly FRONTDOOR_NETWORK="safe-change-step15-frontdoor"
readonly OBSERVATION_NETWORK="safe-change-step15-observation"
readonly V1_IMAGE="safe-change-step15/deathstar:hotel-reservation-0.2.2"
readonly V2_IMAGE="safe-change-step15/deathstar:hotel-reservation-0.3.5"
readonly RUNTIME_IMAGE="safe-change-step15/runtime:local"
readonly DOMAIN="deathstar-step15"
readonly RAW_CALL_ID="raw-retry-17"
readonly DRAIN_CALL_ID="old-version-drain-18"
readonly OLD_CALL_ID="proposed-old-19"
readonly NEW_CALL_ID="proposed-new-20"
readonly NEVER_CALL_ID="never-executed-21"
readonly MULTI_CALL_ID="multi-night-16"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/../../.." && pwd)"
runtime_root="$repo_root/runtime"
work_dir="$(mktemp -d /tmp/safe-change-deathstar-step15.XXXXXX)"
if [[ -z "${EVIDENCE_DIR:-}" ]]; then
  EVIDENCE_DIR="$(mktemp -d /tmp/safe-change-deathstar-evidence.XXXXXX)"
else
  mkdir -p "$EVIDENCE_DIR"
fi
EVIDENCE_DIR="$(realpath "$EVIDENCE_DIR")"
runner_outputs=(adapter baselines baseline-matrix.json certificates docker proposed requirements result.json state timeline.jsonl upstream.json)
for output in "${runner_outputs[@]}"; do
  if [[ -e "$EVIDENCE_DIR/$output" ]]; then
    echo "refusing to overwrite existing runner output: $EVIDENCE_DIR/$output" >&2
    exit 1
  fi
done
mkdir -p "$EVIDENCE_DIR"/{adapter,baselines/raw-retry,baselines/old-version-drain,certificates,docker/logs,proposed,requirements,state}
chmod 700 "$EVIDENCE_DIR" "$EVIDENCE_DIR"/{adapter,baselines,certificates,docker,proposed,requirements,state}

compose=()
custom_containers=()
timeline_sequence=0
run_succeeded=0

record_timeline() {
  local event=$1 details=${2:-'{}'}
  timeline_sequence=$((timeline_sequence + 1))
  jq -cn --argjson seq "$timeline_sequence" --argjson at_ns "$(date +%s%N)" \
    --arg event "$event" --argjson details "$details" \
    '{schema:1,seq:$seq,at_ns:$at_ns,event:$event,details:$details}' >> "$EVIDENCE_DIR/timeline.jsonl"
}

save_logs() {
  local name=$1 file=$2
  docker logs "$name" > "$file" 2>&1 || true
}

cleanup() {
  local status=$?
  trap - EXIT
  if [[ $status -ne 0 ]]; then
    record_timeline run_failed "$(jq -cn --argjson exit_code "$status" '{exit_code:$exit_code}')" || true
    if ((${#compose[@]})); then
      "${compose[@]}" logs --no-color > "$EVIDENCE_DIR/docker/logs/official-compose-failure.log" 2>&1 || true
    fi
    for name in "${custom_containers[@]}"; do
      save_logs "$name" "$EVIDENCE_DIR/docker/logs/${name}-failure.log"
    done
  fi
  if [[ "${KEEP_DEMO:-0}" != "1" ]]; then
    for name in "${custom_containers[@]}"; do
      docker rm -f "$name" >/dev/null 2>&1 || true
    done
    if ((${#compose[@]})); then
      "${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
    fi
    docker network rm "$CONTROL_NETWORK" "$FRONTDOOR_NETWORK" "$OBSERVATION_NETWORK" >/dev/null 2>&1 || true
  fi
  case "$work_dir" in
    /tmp/safe-change-deathstar-step15.*) rm -rf -- "$work_dir" ;;
    *) echo "refusing to remove unexpected work directory: $work_dir" >&2 ;;
  esac
  echo "evidence directory: $EVIDENCE_DIR" >&2
  exit "$status"
}
trap cleanup EXIT

for command in base64 curl docker git go jq python3 realpath sha256sum tar; do
  command -v "$command" >/dev/null || { echo "missing required command: $command" >&2; exit 1; }
done
docker compose version >/dev/null

fixed_names=(
  safe-change-step15-control safe-change-step15-front-client safe-change-step15-observation-client
  safe-change-step15-observer safe-change-step15-frontend-v1 safe-change-step15-frontend-v2
  safe-change-step15-effect-raw safe-change-step15-effect-drain
  safe-change-step15-effect-v1 safe-change-step15-effect-v2
)
for name in "${fixed_names[@]}"; do
  if docker container inspect "$name" >/dev/null 2>&1; then
    echo "fixed step15 container already exists: $name" >&2
    exit 1
  fi
done
for network in "$CONTROL_NETWORK" "$FRONTDOOR_NETWORK" "$OBSERVATION_NETWORK"; do
  if docker network inspect "$network" >/dev/null 2>&1; then
    echo "fixed step15 network already exists: $network" >&2
    exit 1
  fi
done
if [[ -n "$(docker ps -aq --filter "label=com.docker.compose.project=$PROJECT")" ]] ||
   [[ -n "$(docker volume ls -q --filter "label=com.docker.compose.project=$PROJECT")" ]] ||
   [[ -n "$(docker network ls -q --filter "label=com.docker.compose.project=$PROJECT")" ]]; then
  echo "fixed Compose project already has containers, volumes, or networks: $PROJECT" >&2
  exit 1
fi

record_timeline source_clone_started
git clone --quiet --filter=blob:none --no-checkout "$DEATHSTAR_REPOSITORY" "$work_dir/repository"
v1_resolved="$(git -C "$work_dir/repository" rev-parse "refs/tags/$V1_TAG^{commit}")"
v2_resolved="$(git -C "$work_dir/repository" rev-parse "refs/tags/$V2_TAG^{commit}")"
[[ "$v1_resolved" == "$V1_COMMIT" ]]
[[ "$v2_resolved" == "$V2_COMMIT" ]]
mkdir -p "$work_dir/v1" "$work_dir/v2"
git -C "$work_dir/repository" worktree add --quiet --detach --no-checkout "$work_dir/v1" "$V1_COMMIT"
git -C "$work_dir/v1" sparse-checkout init --cone
git -C "$work_dir/v1" sparse-checkout set hotelReservation
git -C "$work_dir/v1" checkout --quiet --detach "$V1_COMMIT"
git -C "$work_dir/repository" worktree add --quiet --detach --no-checkout "$work_dir/v2" "$V2_COMMIT"
git -C "$work_dir/v2" sparse-checkout init --cone
git -C "$work_dir/v2" sparse-checkout set hotelReservation
git -C "$work_dir/v2" checkout --quiet --detach "$V2_COMMIT"
# This host runs with umask 0077, while the pinned frontend images run as
# uid 65532 and read the bind-mounted upstream config directly. Git does not
# track the group/other read bits of regular files, so normalizing these modes
# changes neither source content nor the recorded upstream tree.
chmod 0644 "$work_dir/v1/hotelReservation/config.json" "$work_dir/v2/hotelReservation/config.json"
v1_tree="$(git -C "$work_dir/repository" rev-parse "$V1_COMMIT:hotelReservation")"
v2_tree="$(git -C "$work_dir/repository" rev-parse "$V2_COMMIT:hotelReservation")"
assert_source_clean() {
  local source=$1 commit=$2
  [[ "$(git -C "$source" rev-parse HEAD)" == "$commit" ]]
  git -C "$source" diff --quiet -- hotelReservation
  git -C "$source" diff --cached --quiet -- hotelReservation
  [[ -z "$(git -C "$source" ls-files --others --exclude-standard -- hotelReservation)" ]]
  [[ -z "$(git -C "$source" status --porcelain -- hotelReservation)" ]]
}
assert_source_clean "$work_dir/v1" "$V1_COMMIT"
assert_source_clean "$work_dir/v2" "$V2_COMMIT"
v1_status_before_build="$(git -C "$work_dir/v1" status --porcelain=v1 --untracked-files=all -- hotelReservation)"
v2_status_before_build="$(git -C "$work_dir/v2" status --porcelain=v1 --untracked-files=all -- hotelReservation)"
[[ -z "$v1_status_before_build" && -z "$v2_status_before_build" ]]
v1_source_clean_before_build=true
v2_source_clean_before_build=true
record_timeline source_commits_verified "$(jq -cn --arg v1 "$V1_COMMIT" --arg v2 "$V2_COMMIT" '{v1:$v1,v2:$v2}')"

docker build --label "org.opencontainers.image.source=$DEATHSTAR_REPOSITORY" \
  --label "org.opencontainers.image.revision=$V1_COMMIT" -t "$V1_IMAGE" \
  "$work_dir/v1/hotelReservation" > "$EVIDENCE_DIR/docker/logs/build-deathstar-v1.log" 2>&1
docker build --label "org.opencontainers.image.source=$DEATHSTAR_REPOSITORY" \
  --label "org.opencontainers.image.revision=$V2_COMMIT" -t "$V2_IMAGE" \
  "$work_dir/v2/hotelReservation" > "$EVIDENCE_DIR/docker/logs/build-deathstar-v2.log" 2>&1
runtime_git_head="$(git -C "$repo_root" rev-parse HEAD)"
runtime_status_before_build="$(git -C "$repo_root" status --porcelain=v1 --untracked-files=all -- runtime)"
[[ -z "$runtime_status_before_build" ]]
git -C "$repo_root" diff --quiet -- runtime
git -C "$repo_root" diff --cached --quiet -- runtime
docker build --label "org.opencontainers.image.revision=$runtime_git_head" \
  -f "$runtime_root/deploy/microservice/Dockerfile" -t "$RUNTIME_IMAGE" \
  "$runtime_root" > "$EVIDENCE_DIR/docker/logs/build-runtime.log" 2>&1
runtime_status_after_build="$(git -C "$repo_root" status --porcelain=v1 --untracked-files=all -- runtime)"
[[ -z "$runtime_status_after_build" ]]
git -C "$repo_root" diff --quiet -- runtime
git -C "$repo_root" diff --cached --quiet -- runtime
assert_source_clean "$work_dir/v1" "$V1_COMMIT"
assert_source_clean "$work_dir/v2" "$V2_COMMIT"
v1_status_after_build="$(git -C "$work_dir/v1" status --porcelain=v1 --untracked-files=all -- hotelReservation)"
v2_status_after_build="$(git -C "$work_dir/v2" status --porcelain=v1 --untracked-files=all -- hotelReservation)"
[[ -z "$v1_status_after_build" && -z "$v2_status_after_build" ]]
v1_source_clean_after_build=true
v2_source_clean_after_build=true
go -C "$runtime_root" build -trimpath -o "$work_dir/check-certificate" ./cmd/check-certificate
v1_image_id="$(docker image inspect -f '{{.Id}}' "$V1_IMAGE")"
v2_image_id="$(docker image inspect -f '{{.Id}}' "$V2_IMAGE")"
runtime_image_id="$(docker image inspect -f '{{.Id}}' "$RUNTIME_IMAGE")"
checker_sha256="$(sha256sum "$work_dir/check-certificate" | cut -d' ' -f1)"
[[ "$(docker image inspect -f '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$V1_IMAGE")" == "$V1_COMMIT" ]]
[[ "$(docker image inspect -f '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$V2_IMAGE")" == "$V2_COMMIT" ]]
[[ "$(docker image inspect -f '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$RUNTIME_IMAGE")" == "$runtime_git_head" ]]
record_timeline images_built "$(jq -cn --arg v1 "$v1_image_id" --arg v2 "$v2_image_id" --arg runtime "$runtime_image_id" '{v1:$v1,v2:$v2,runtime:$runtime}')"

derive_operation_id() {
  local call_id=$1
  printf 'operation-id-v1\0%s\0%s' "$DOMAIN" "$call_id" | sha256sum | awk '{print "op-" $1}'
}
old_operation_id="$(derive_operation_id "$OLD_CALL_ID")"
new_operation_id="$(derive_operation_id "$NEW_CALL_ID")"
raw_operation_id="$(derive_operation_id "$RAW_CALL_ID")"
drain_operation_id="$(derive_operation_id "$DRAIN_CALL_ID")"
never_operation_id="$(derive_operation_id "$NEVER_CALL_ID")"
multi_operation_id="$(derive_operation_id "$MULTI_CALL_ID")"

gateway_request_hash() {
  local url=$1 operation_id=$2 body_file=$3
  python3 -c '
import hashlib, pathlib, sys
url, operation_id, body_path = sys.argv[1:]
headers = {
    "accept-encoding": "identity",
    "content-type": "application/json",
    "idempotency-key": operation_id,
    "user-agent": "safe-change-runtime/1",
    "x-operation-id": operation_id,
}
h = hashlib.sha256()
h.update(b"POST\x00")
h.update(url.encode())
h.update(b"\x00")
for name, value in sorted(headers.items()):
    h.update(name.encode())
    h.update(b":")
    h.update(value.encode())
    h.update(b"\x00")
h.update(pathlib.Path(body_path).read_bytes())
print(h.hexdigest())
' "$url" "$operation_id" "$body_file"
}

export DEATHSTAR_V2_IMAGE="$V2_IMAGE"
compose=(docker compose -p "$PROJECT" -f "$work_dir/v2/hotelReservation/docker-compose.yml" -f "$script_dir/compose.override.yaml")
"${compose[@]}" config > "$EVIDENCE_DIR/docker/compose-config.yaml"
"${compose[@]}" config --services | sort > "$EVIDENCE_DIR/docker/official-services.txt"
[[ "$(wc -l < "$EVIDENCE_DIR/docker/official-services.txt")" -eq 24 ]]

docker network create --label safe-change.step=15 "$CONTROL_NETWORK" >/dev/null
docker network create --label safe-change.step=15 "$FRONTDOOR_NETWORK" >/dev/null
docker network create --label safe-change.step=15 "$OBSERVATION_NETWORK" >/dev/null
"${compose[@]}" up -d --no-build --scale frontend=0
application_network="$(docker network ls -q \
  --filter "label=com.docker.compose.project=$PROJECT" \
  --filter 'label=com.docker.compose.network=default')"
[[ -n "$application_network" ]]
[[ "$(wc -w <<< "$application_network")" -eq 1 ]]
reservation_container="$("${compose[@]}" ps -q reservation)"
mongo_container="$("${compose[@]}" ps -q mongodb-reservation)"
[[ -n "$reservation_container" && -n "$mongo_container" ]]
docker network connect --alias reservation-mongo "$OBSERVATION_NETWORK" "$mongo_container"
record_timeline official_service_graph_started "$(jq -cn --arg project "$PROJECT" '{project:$project,frontend_scaled_to_zero:true}')"

uid="$(id -u)"
gid="$(id -g)"
start_idle_client() {
  local name=$1 network=$2
  docker run -d --name "$name" --user "$uid:$gid" --network "$network" \
    --label safe-change.step=15 --mount "type=bind,src=$EVIDENCE_DIR,dst=/evidence,readonly" \
    "$RUNTIME_IMAGE" sh -c 'while :; do sleep 3600; done' >/dev/null
  custom_containers+=("$name")
}
start_idle_client safe-change-step15-front-client "$FRONTDOOR_NETWORK"
start_idle_client safe-change-step15-observation-client "$OBSERVATION_NETWORK"
front_client=safe-change-step15-front-client
observation_client=safe-change-step15-observation-client

wait_http_from() {
  local client=$1 url=$2
  for _ in $(seq 1 180); do
    if docker exec "$client" wget -qO- -T 3 "$url" >/dev/null 2>&1; then return 0; fi
    sleep 1
  done
  echo "timed out waiting for $url from $client" >&2
  return 1
}

start_frontend() {
  local version=$1 name image config binary alias
  name="safe-change-step15-frontend-$version"
  alias="frontend-$version"
  if [[ "$version" == v1 ]]; then
    image="$V1_IMAGE"
    config="$work_dir/v1/hotelReservation/config.json"
    binary=/frontend
  else
    image="$V2_IMAGE"
    config="$work_dir/v2/hotelReservation/config.json"
    binary=/go/bin/frontend
  fi
  docker run -d --name "$name" --network "$application_network" \
    --label safe-change.step=15 --mount "type=bind,src=$config,dst=/config.json,readonly" \
    "$image" "$binary" >/dev/null
  custom_containers+=("$name")
  docker network connect --alias "$alias" "$FRONTDOOR_NETWORK" "$name"
}

start_effect() {
  local suffix=$1 frontend_alias=$2 audit=$3 drop=$4
  local name="safe-change-step15-effect-$suffix"
  : > "$audit"
  chmod 600 "$audit"
  args=(deathstar-adapter -mode effect -listen 0.0.0.0:8090 \
    -frontend "http://$frontend_alias:5000" -audit /adapter.audit.jsonl)
  if [[ "$drop" == true ]]; then args+=(-drop-first-response); fi
  docker run -d --name "$name" --user "$uid:$gid" --network "$FRONTDOOR_NETWORK" \
    --network-alias "effect-$suffix" --label safe-change.step=15 \
    -p 127.0.0.1::8090 \
    --mount "type=bind,src=$audit,dst=/adapter.audit.jsonl" \
    "$RUNTIME_IMAGE" "${args[@]}" >/dev/null
  custom_containers+=("$name")
  docker network connect --alias "effect-$suffix" "$CONTROL_NETWORK" "$name"
  wait_http_from "$front_client" "http://effect-$suffix:8090/healthz"
}

observer=safe-change-step15-observer
docker run -d --name "$observer" --user "$uid:$gid" --network "$OBSERVATION_NETWORK" \
  --network-alias observer --label safe-change.step=15 "$RUNTIME_IMAGE" deathstar-adapter -mode observer \
  -listen 0.0.0.0:8090 -mongo-uri mongodb://reservation-mongo:27017 >/dev/null
custom_containers+=("$observer")
docker network connect --alias observer "$CONTROL_NETWORK" "$observer"
wait_http_from "$observation_client" http://observer:8090/healthz

start_frontend v1
frontend_v1=safe-change-step15-frontend-v1
for _ in $(seq 1 180); do
  login="$(docker exec "$front_client" wget -qO- -T 5 \
    'http://frontend-v1:5000/user?username=Cornell_30&password=0000000000' 2>/dev/null || true)"
  if jq -e '.message == "Login successfully!"' >/dev/null 2>&1 <<< "$login"; then break; fi
  sleep 1
done
jq -e '.message == "Login successfully!"' >/dev/null <<< "$login"

for _ in $(seq 1 180); do
  all_official_running=true
  while IFS= read -r service; do
    [[ "$service" == frontend ]] && continue
    container_id="$("${compose[@]}" ps -q "$service")"
    if [[ -z "$container_id" ]] || [[ "$(docker inspect -f '{{.State.Running}}' "$container_id" 2>/dev/null || true)" != true ]]; then
      all_official_running=false
      break
    fi
  done < "$EVIDENCE_DIR/docker/official-services.txt"
  [[ "$all_official_running" == true ]] && break
  sleep 1
done
[[ "$all_official_running" == true ]]
: > "$work_dir/official-service-state.jsonl"
while IFS= read -r service; do
  if [[ "$service" == frontend ]]; then
    jq -cn --arg service "$service" '{service:$service,compose_scaled_to_zero:true,running:false}' \
      >> "$work_dir/official-service-state.jsonl"
    continue
  fi
  container_id="$("${compose[@]}" ps -q "$service")"
  running="$(docker inspect -f '{{.State.Running}}' "$container_id")"
  jq -cn --arg service "$service" --arg container_id "$container_id" --argjson running "$running" \
    '{service:$service,container_id:$container_id,compose_scaled_to_zero:false,running:$running}' \
    >> "$work_dir/official-service-state.jsonl"
done < "$EVIDENCE_DIR/docker/official-services.txt"
jq -s '{schema:1,services:.,pass:(length == 24 and ([.[]|select(.service != "frontend")]|all(.running == true)) and
  ([.[]|select(.service == "frontend" and .compose_scaled_to_zero == true)]|length == 1))}' \
  "$work_dir/official-service-state.jsonl" > "$EVIDENCE_DIR/docker/official-service-state.json"
jq -e '.pass == true' "$EVIDENCE_DIR/docker/official-service-state.json" >/dev/null
record_timeline frontend_v1_ready

direct_effect_post() {
  local alias=$1 operation_id=$2 body_file=$3 response_file=$4 transport_file=$5
  local container_name host_address exit_code http_status
  container_name="safe-change-step15-$alias"
  host_address="$(docker port "$container_name" 8090/tcp)"
  [[ "$host_address" == 127.0.0.1:* ]]
  # curl need not create its -o target when the peer closes before sending any
  # HTTP bytes. Create all capture files first so a zero-byte response is
  # evidence rather than a harness error.
  : > "$response_file"
  : > "$transport_file.headers"
  : > "$transport_file.curl-stderr"
  set +e
  http_status="$(curl --noproxy '*' --fail-with-body -sS --max-time 35 -X POST \
    -A safe-change-runtime/1 -H 'Accept:' -H 'Accept-Encoding: identity' \
    -H 'Content-Type: application/json' -H "Idempotency-Key: $operation_id" \
    -H "X-Operation-ID: $operation_id" --data-binary "@$body_file" \
    -D "$transport_file.headers" -o "$response_file" "http://$host_address/v1/reserve" \
    -w '%{http_code}' 2> "$transport_file.curl-stderr")"
  exit_code=$?
  set -e
  { cat "$transport_file.curl-stderr"; cat "$transport_file.headers"; } > "$transport_file.stderr"
  jq -n --argjson exit_code "$exit_code" --arg http_status "$http_status" \
    --argjson response_bytes "$(wc -c < "$response_file")" \
    --rawfile stderr "$transport_file.stderr" \
    '{schema:1,transport:"curl",exit_code:$exit_code,http_status:$http_status,
      response_bytes:$response_bytes,stderr:$stderr}' \
    > "$transport_file"
  rm -f -- "$transport_file.stderr" "$transport_file.curl-stderr" "$transport_file.headers"
  return "$exit_code"
}

effect_stats() {
  local alias=$1 output=$2
  docker exec "$front_client" wget -qO- -T 5 "http://$alias:8090/v1/stats/facts" > "$output"
  jq -e '.mode == "effect"' "$output" >/dev/null
}

observer_post() {
  local operation_id=$1 request_hash=$2 body_file=$3 output=$4
  local container_body="/evidence/${body_file#"$EVIDENCE_DIR"/}"
  docker exec "$observation_client" wget -qO- -T 10 \
    --header 'Content-Type: application/json' --header "X-Operation-ID: $operation_id" \
    --header "X-Operation-Request-Hash: $request_hash" --post-file "$container_body" \
    http://observer:8090/v1/query > "$output"
}

save_mongo_fact() {
  local operation_id=$1 hotel=$2 _body_file=$3 output=$4
  local in_date=${5:-2015-04-09} out_date=${6:-2015-04-10}
  local filter javascript raw
  filter="$(jq -cn --arg customer "safe-$operation_id" --arg hotel "$hotel" \
    --arg in_date "$in_date" --arg out_date "$out_date" \
    '{customerName:$customer,hotelId:$hotel,inDate:$in_date,outDate:$out_date,number:1}')"
  javascript="var f=$filter; var d=db.reservation.find(f,{_id:0}).sort({_id:1}).toArray(); print(JSON.stringify({count:d.length,facts:d}));"
  raw="$(docker exec "$mongo_container" mongo --quiet reservation-db --eval "$javascript" | tail -n 1)"
  jq -en --arg operation_id "$operation_id" --argjson filter "$filter" --argjson raw "$raw" '{
    schema:1,operation_id:$operation_id,filter:$filter,count:$raw.count,
    facts:[$raw.facts[]|{customer_name:.customerName,hotel_id:.hotelId,in_date:.inDate,out_date:.outDate,rooms:.number}]
  }' > "$output"
  jq -e '.schema == 1 and (.count | type == "number") and (.facts | type == "array") and
    .count == (.facts | length)' "$output" >/dev/null
}

jq -jcn '{hotel_id:"1",in_date:"2015-04-09",out_date:"2015-04-10",rooms:1,username:"Cornell_30",password:"0000000000"}' \
  > "$EVIDENCE_DIR/baselines/raw-retry/request-body.json"
cp "$EVIDENCE_DIR/baselines/raw-retry/request-body.json" "$EVIDENCE_DIR/baselines/old-version-drain/request-body.json"
cp "$EVIDENCE_DIR/baselines/raw-retry/request-body.json" "$EVIDENCE_DIR/proposed/old-request-body.json"
cp "$EVIDENCE_DIR/baselines/raw-retry/request-body.json" "$EVIDENCE_DIR/proposed/new-request-body.json"
cp "$EVIDENCE_DIR/baselines/raw-retry/request-body.json" "$EVIDENCE_DIR/adapter/unexecuted-request-body.json"
jq -jcn '{hotel_id:"1",in_date:"2015-04-09",out_date:"2015-04-11",rooms:1,username:"Cornell_30",password:"0000000000"}' \
  > "$EVIDENCE_DIR/adapter/multi-night-request-body.json"
cmp -s "$EVIDENCE_DIR/baselines/raw-retry/request-body.json" "$EVIDENCE_DIR/baselines/old-version-drain/request-body.json"
cmp -s "$EVIDENCE_DIR/baselines/raw-retry/request-body.json" "$EVIDENCE_DIR/proposed/old-request-body.json"
cmp -s "$EVIDENCE_DIR/baselines/raw-retry/request-body.json" "$EVIDENCE_DIR/proposed/new-request-body.json"
cmp -s "$EVIDENCE_DIR/baselines/raw-retry/request-body.json" "$EVIDENCE_DIR/adapter/unexecuted-request-body.json"

# Baseline 1: a raw retry of the same business identity duplicates the durable row.
raw_audit="$EVIDENCE_DIR/baselines/raw-retry/adapter-audit.jsonl"
start_effect raw frontend-v1 "$raw_audit" true

# Negative control: an unsupported multi-night request is rejected before the
# adapter records a delivery or reaches the official application.
if direct_effect_post effect-raw "$multi_operation_id" "$EVIDENCE_DIR/adapter/multi-night-request-body.json" \
  "$EVIDENCE_DIR/adapter/multi-night-response.body" "$EVIDENCE_DIR/adapter/multi-night-transport.json"; then
  echo "multi-night request unexpectedly succeeded" >&2
  exit 1
fi
jq -e '.exit_code != 0 and .http_status == "400" and .response_bytes > 0' \
  "$EVIDENCE_DIR/adapter/multi-night-transport.json" >/dev/null
jq -n --slurpfile transport "$EVIDENCE_DIR/adapter/multi-night-transport.json" \
  '{schema:1,http_status:400,outcome:"rejected-before-dispatch",transport:$transport[0]}' \
  > "$EVIDENCE_DIR/adapter/multi-night-response.json"
effect_stats effect-raw "$EVIDENCE_DIR/adapter/multi-night-adapter-stats.json"
jq -e '.deliveries == 0 and .upstream_successes == 0 and .drops == 0' \
  "$EVIDENCE_DIR/adapter/multi-night-adapter-stats.json" >/dev/null
[[ ! -s "$raw_audit" ]]
save_mongo_fact "$multi_operation_id" 1 "$EVIDENCE_DIR/adapter/multi-night-request-body.json" \
  "$EVIDENCE_DIR/adapter/multi-night-mongo.json" 2015-04-09 2015-04-11
jq -e '.count == 0 and (.facts | length) == 0' "$EVIDENCE_DIR/adapter/multi-night-mongo.json" >/dev/null

if direct_effect_post effect-raw "$raw_operation_id" "$EVIDENCE_DIR/baselines/raw-retry/request-body.json" \
  "$EVIDENCE_DIR/baselines/raw-retry/first-response.json" "$EVIDENCE_DIR/baselines/raw-retry/first-transport.json"; then
  echo "raw first delivery unexpectedly returned a response" >&2
  exit 1
fi
jq -e '.exit_code != 0 and .response_bytes == 0' "$EVIDENCE_DIR/baselines/raw-retry/first-transport.json" >/dev/null
mv "$EVIDENCE_DIR/baselines/raw-retry/first-response.json" "$EVIDENCE_DIR/baselines/raw-retry/first-response.body"
jq -n --slurpfile transport "$EVIDENCE_DIR/baselines/raw-retry/first-transport.json" \
  '{schema:1,outcome:"unknown",transport:$transport[0]}' > "$EVIDENCE_DIR/baselines/raw-retry/first-response.json"
direct_effect_post effect-raw "$raw_operation_id" "$EVIDENCE_DIR/baselines/raw-retry/request-body.json" \
  "$EVIDENCE_DIR/baselines/raw-retry/second-response.json" "$EVIDENCE_DIR/baselines/raw-retry/second-transport.json"
jq -e --arg id "$raw_operation_id" '.operation_id == $id and .outcome == "succeeded"' \
  "$EVIDENCE_DIR/baselines/raw-retry/second-response.json" >/dev/null
effect_stats effect-raw "$EVIDENCE_DIR/baselines/raw-retry/adapter-stats.json"
jq -e '.deliveries == 2 and .upstream_successes == 2 and .drops == 1' \
  "$EVIDENCE_DIR/baselines/raw-retry/adapter-stats.json" >/dev/null
raw_probe_hash="$(gateway_request_hash http://effect-raw:8090/v1/reserve "$raw_operation_id" "$EVIDENCE_DIR/baselines/raw-retry/request-body.json")"
jq -cn --arg operation_id "$raw_operation_id" --arg effect_url http://effect-raw:8090/v1/reserve \
  --arg request_hash "$raw_probe_hash" '{schema:1,operation_id:$operation_id,effect_url:$effect_url,request_hash:$request_hash}' \
  > "$EVIDENCE_DIR/baselines/raw-retry/observer-request.json"
observer_post "$raw_operation_id" "$raw_probe_hash" "$EVIDENCE_DIR/baselines/raw-retry/request-body.json" \
  "$EVIDENCE_DIR/baselines/raw-retry/observer-response.json"
jq -e '.outcome == "inconclusive" and .fact_hash == "" and .remote_reference == "reservation-db.reservation/count=2"' \
  "$EVIDENCE_DIR/baselines/raw-retry/observer-response.json" >/dev/null
save_mongo_fact "$raw_operation_id" 1 "$EVIDENCE_DIR/baselines/raw-retry/request-body.json" \
  "$EVIDENCE_DIR/baselines/raw-retry/mongo.json"
jq -e '.count == 2 and (.facts | length) == 2' "$EVIDENCE_DIR/baselines/raw-retry/mongo.json" >/dev/null
save_logs safe-change-step15-effect-raw "$EVIDENCE_DIR/docker/logs/effect-raw.log"
docker rm -f safe-change-step15-effect-raw >/dev/null
record_timeline raw_retry_completed '{"deliveries":2,"commits":2,"mongo_rows":2}'

# Observer control: a never-executed identity returns a real zero-count,
# inconclusive observation.
never_probe_hash="$(gateway_request_hash http://effect-v1:8090/v1/reserve "$never_operation_id" "$EVIDENCE_DIR/adapter/unexecuted-request-body.json")"
jq -cn --arg operation_id "$never_operation_id" --arg effect_url http://effect-v1:8090/v1/reserve \
  --arg request_hash "$never_probe_hash" '{schema:1,operation_id:$operation_id,effect_url:$effect_url,request_hash:$request_hash}' \
  > "$EVIDENCE_DIR/adapter/unexecuted-observer-request.json"
observer_post "$never_operation_id" "$never_probe_hash" "$EVIDENCE_DIR/adapter/unexecuted-request-body.json" \
  "$EVIDENCE_DIR/adapter/unexecuted-observation.json"
jq -e '.outcome == "inconclusive" and .fact_hash == "" and .remote_reference == "reservation-db.reservation/count=0"' \
  "$EVIDENCE_DIR/adapter/unexecuted-observation.json" >/dev/null

# Baseline 2: draining the old version is safe only by staying unavailable.
drain_audit="$EVIDENCE_DIR/baselines/old-version-drain/adapter-audit.jsonl"
start_effect drain frontend-v1 "$drain_audit" true
if direct_effect_post effect-drain "$drain_operation_id" "$EVIDENCE_DIR/baselines/old-version-drain/request-body.json" \
  "$EVIDENCE_DIR/baselines/old-version-drain/response.json" "$EVIDENCE_DIR/baselines/old-version-drain/transport.json"; then
  echo "drain delivery unexpectedly returned a response" >&2
  exit 1
fi
jq -e '.exit_code != 0 and .response_bytes == 0' "$EVIDENCE_DIR/baselines/old-version-drain/transport.json" >/dev/null
mv "$EVIDENCE_DIR/baselines/old-version-drain/response.json" "$EVIDENCE_DIR/baselines/old-version-drain/response.body"
jq -n --slurpfile transport "$EVIDENCE_DIR/baselines/old-version-drain/transport.json" \
  '{schema:1,outcome:"unknown",transport:$transport[0]}' > "$EVIDENCE_DIR/baselines/old-version-drain/response.json"
effect_stats effect-drain "$EVIDENCE_DIR/baselines/old-version-drain/adapter-stats.json"
jq -e '.deliveries == 1 and .upstream_successes == 1 and .drops == 1' \
  "$EVIDENCE_DIR/baselines/old-version-drain/adapter-stats.json" >/dev/null
drain_probe_hash="$(gateway_request_hash http://effect-drain:8090/v1/reserve "$drain_operation_id" "$EVIDENCE_DIR/baselines/old-version-drain/request-body.json")"
jq -cn --arg operation_id "$drain_operation_id" --arg effect_url http://effect-drain:8090/v1/reserve \
  --arg request_hash "$drain_probe_hash" '{schema:1,operation_id:$operation_id,effect_url:$effect_url,request_hash:$request_hash}' \
  > "$EVIDENCE_DIR/baselines/old-version-drain/observer-request.json"
observer_post "$drain_operation_id" "$drain_probe_hash" "$EVIDENCE_DIR/baselines/old-version-drain/request-body.json" \
  "$EVIDENCE_DIR/baselines/old-version-drain/observer-response.json"
jq -e '.outcome == "succeeded"' "$EVIDENCE_DIR/baselines/old-version-drain/observer-response.json" >/dev/null
save_mongo_fact "$drain_operation_id" 1 "$EVIDENCE_DIR/baselines/old-version-drain/request-body.json" \
  "$EVIDENCE_DIR/baselines/old-version-drain/mongo.json"
jq -e '.count == 1 and (.facts | length) == 1' "$EVIDENCE_DIR/baselines/old-version-drain/mongo.json" >/dev/null
docker inspect "$frontend_v1" > "$EVIDENCE_DIR/baselines/old-version-drain/frontend-inspect.json"
docker inspect safe-change-step15-effect-drain > "$EVIDENCE_DIR/baselines/old-version-drain/effect-inspect.json"
jq -e '.[0].State.Running == true' "$EVIDENCE_DIR/baselines/old-version-drain/frontend-inspect.json" >/dev/null
jq -e '.[0].State.Running == true' "$EVIDENCE_DIR/baselines/old-version-drain/effect-inspect.json" >/dev/null
save_logs safe-change-step15-effect-drain "$EVIDENCE_DIR/docker/logs/effect-drain.log"
docker rm -f safe-change-step15-effect-drain >/dev/null
record_timeline old_version_drain_sampled '{"known_result":false,"old_version_retained":true,"mongo_rows":1}'

# Proposed condition: one History survives a Requirement change and control restart.
state_dir="$EVIDENCE_DIR/state"
config_dir="$work_dir/control-config"
mkdir -p "$config_dir"
admin_token="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
operation_token="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
printf '%s\n' "$admin_token" > "$config_dir/admin-token"
printf '%s\n' "$operation_token" > "$config_dir/operation-token"
chmod 600 "$config_dir/admin-token" "$config_dir/operation-token"
jq -cn '{schema:1,adapters:[{domain:"deathstar-step15",token_file:"/config/operation-token",kinds:["reserve-v1","reserve-v2"]}]}' \
  > "$config_dir/adapters.json"
chmod 600 "$config_dir/adapters.json"
control_port="$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')"
control=safe-change-step15-control
docker run -d --name "$control" --user "$uid:$gid" --network "$CONTROL_NETWORK" \
  --label safe-change.step=15 -p "127.0.0.1:$control_port:8787" \
  --mount "type=bind,src=$state_dir,dst=/state" --mount "type=bind,src=$config_dir,dst=/config,readonly" \
  "$RUNTIME_IMAGE" control -history /state/runtime.history -head-anchor /state/runtime.head \
  -listen 0.0.0.0:8787 -allow-nonloopback -admin-token-file /config/admin-token \
  -adapter-config /config/adapters.json >/dev/null
custom_containers+=("$control")
control_url="http://127.0.0.1:$control_port"
for _ in $(seq 1 90); do
  if curl -fsS "$control_url/healthz" >/dev/null; then break; fi
  sleep 1
done
curl -fsS "$control_url/healthz" >/dev/null

api_post() {
  local path=$1 input=$2 output=$3 expected=$4 token=$5
  local code
  code="$(curl -sS -o "$output" -w '%{http_code}' -H "Authorization: Bearer $token" \
    -H 'Content-Type: application/json' --data-binary "@$input" "$control_url$path")"
  if [[ "$code" != "$expected" ]]; then
    echo "POST $path returned HTTP $code, expected $expected" >&2
    jq . "$output" >&2 || true
    return 1
  fi
}

effect_v1_url=http://effect-v1:8090/v1/reserve
effect_v2_url=http://effect-v2:8090/v1/reserve
query_url=http://observer:8090/v1/query
jq -cn --arg target "$effect_v1_url" --arg query "$query_url" '{
  id:"deathstar-reservations-v1",results:{reserved:1},capacities:{reservation:1},kinds:{
    "reserve-v1":{costs:{reservation:1},produces:{reserved:1},retry_safe:false,queryable:true,
      target:$target,method:"POST",response_classifier:"operation-receipt-v1",
      query_target:$query,query_method:"POST",query_classifier:"operation-observation-v1"}
  }}' > "$EVIDENCE_DIR/requirements/v1.json"
api_post /v1/compile "$EVIDENCE_DIR/requirements/v1.json" "$EVIDENCE_DIR/certificates/v1.json" 200 "$admin_token"
jq -e '.decision == "activate" and .rule != null' "$EVIDENCE_DIR/certificates/v1.json" >/dev/null
api_post /v1/certificate-state "$EVIDENCE_DIR/certificates/v1.json" "$EVIDENCE_DIR/certificates/state-v1.json" 200 "$admin_token"
"$work_dir/check-certificate" -state "$EVIDENCE_DIR/certificates/state-v1.json" \
  -certificate "$EVIDENCE_DIR/certificates/v1.json" > "$EVIDENCE_DIR/certificates/verdict-v1.json"
jq -e '.valid == true' "$EVIDENCE_DIR/certificates/verdict-v1.json" >/dev/null
api_post /v1/activate "$EVIDENCE_DIR/certificates/v1.json" "$EVIDENCE_DIR/state/active-v1.json" 200 "$admin_token"

proposed_v1_audit="$EVIDENCE_DIR/proposed/effect-v1-audit.jsonl"
start_effect v1 frontend-v1 "$proposed_v1_audit" true
old_body_base64="$(base64 -w0 "$EVIDENCE_DIR/proposed/old-request-body.json")"
jq -cn --arg call "$OLD_CALL_ID" --arg url "$effect_v1_url" --arg body "$old_body_base64" '{
  call_id:$call,kind:"reserve-v1",method:"POST",url:$url,
  headers:{"Content-Type":"application/json"},body:$body
}' > "$EVIDENCE_DIR/proposed/execute-first.json"
api_post /v1/execute "$EVIDENCE_DIR/proposed/execute-first.json" "$EVIDENCE_DIR/proposed/first-unknown.json" 409 "$operation_token"
jq -e '.outcome.phase == "unknown"' "$EVIDENCE_DIR/proposed/first-unknown.json" >/dev/null
effect_stats effect-v1 "$EVIDENCE_DIR/proposed/effect-v1-stats.json"
jq -e '.deliveries == 1 and .upstream_successes == 1 and .drops == 1' "$EVIDENCE_DIR/proposed/effect-v1-stats.json" >/dev/null
docker inspect "$frontend_v1" > "$EVIDENCE_DIR/proposed/frontend-v1-before-removal.json"
docker inspect safe-change-step15-effect-v1 > "$EVIDENCE_DIR/proposed/effect-v1-before-removal.json"
record_timeline proposed_old_response_lost "$(jq -cn --arg operation_id "$old_operation_id" '{operation_id:$operation_id,phase:"unknown",commits:1}')"

jq -cn --arg target "$effect_v2_url" --arg query "$query_url" '{
  id:"deathstar-reservations-v2",results:{reserved:2},capacities:{reservation:2},kinds:{
    "reserve-v2":{costs:{reservation:1},produces:{reserved:1},retry_safe:false,queryable:true,
      target:$target,method:"POST",response_classifier:"operation-receipt-v1",
      query_target:$query,query_method:"POST",query_classifier:"operation-observation-v1"}
  }}' > "$EVIDENCE_DIR/requirements/v2.json"
api_post /v1/compile "$EVIDENCE_DIR/requirements/v2.json" "$EVIDENCE_DIR/certificates/v2.json" 200 "$admin_token"
jq -e '.decision == "activate" and .rule != null' "$EVIDENCE_DIR/certificates/v2.json" >/dev/null
api_post /v1/certificate-state "$EVIDENCE_DIR/certificates/v2.json" "$EVIDENCE_DIR/certificates/state-v2.json" 200 "$admin_token"
"$work_dir/check-certificate" -state "$EVIDENCE_DIR/certificates/state-v2.json" \
  -certificate "$EVIDENCE_DIR/certificates/v2.json" > "$EVIDENCE_DIR/certificates/verdict-v2.json"
jq -e '.valid == true' "$EVIDENCE_DIR/certificates/verdict-v2.json" >/dev/null
api_post /v1/activate "$EVIDENCE_DIR/certificates/v2.json" "$EVIDENCE_DIR/state/active-v2.json" 200 "$admin_token"

save_logs "$frontend_v1" "$EVIDENCE_DIR/docker/logs/frontend-v1.log"
save_logs safe-change-step15-effect-v1 "$EVIDENCE_DIR/docker/logs/effect-v1.log"
docker network inspect "$CONTROL_NETWORK" "$FRONTDOOR_NETWORK" "$OBSERVATION_NETWORK" "$application_network" \
  > "$EVIDENCE_DIR/docker/networks-v1.json"
docker rm -f "$frontend_v1" safe-change-step15-effect-v1 >/dev/null
record_timeline old_processes_removed

start_frontend v2
frontend_v2=safe-change-step15-frontend-v2
for _ in $(seq 1 180); do
  login="$(docker exec "$front_client" wget -qO- -T 5 \
    'http://frontend-v2:5000/user?username=Cornell_30&password=0000000000' 2>/dev/null || true)"
  if jq -e '.message == "Login successfully!"' >/dev/null 2>&1 <<< "$login"; then break; fi
  sleep 1
done
jq -e '.message == "Login successfully!"' >/dev/null <<< "$login"
proposed_v2_audit="$EVIDENCE_DIR/proposed/effect-v2-audit.jsonl"
start_effect v2 frontend-v2 "$proposed_v2_audit" false

control_pid_before="$(docker inspect -f '{{.State.Pid}}' "$control")"
docker restart "$control" >/dev/null
for _ in $(seq 1 90); do
  if curl -fsS "$control_url/healthz" >/dev/null; then break; fi
  sleep 1
done
control_pid_after="$(docker inspect -f '{{.State.Pid}}' "$control")"
[[ "$control_pid_before" != "$control_pid_after" ]]
record_timeline control_restarted "$(jq -cn --arg before "$control_pid_before" --arg after "$control_pid_after" '{pid_before:$before,pid_after:$after}')"

jq -cn --arg call "$OLD_CALL_ID" --arg url "$effect_v2_url" --arg body "$old_body_base64" '{
  call_id:$call,kind:"reserve-v2",method:"POST",url:$url,
  headers:{"Content-Type":"application/json"},body:$body
}' > "$EVIDENCE_DIR/proposed/execute-recover.json"
api_post /v1/execute "$EVIDENCE_DIR/proposed/execute-recover.json" "$EVIDENCE_DIR/proposed/recovered-response.json" 200 "$operation_token"
jq -e --arg id "$old_operation_id" '
  .operation_id == $id and .phase == "succeeded" and .recovered_by_query == true and .reused == false
' "$EVIDENCE_DIR/proposed/recovered-response.json" >/dev/null
effect_stats effect-v2 "$EVIDENCE_DIR/proposed/effect-v2-stats-before-new.json"
jq -e '.deliveries == 0 and .upstream_successes == 0' "$EVIDENCE_DIR/proposed/effect-v2-stats-before-new.json" >/dev/null
save_mongo_fact "$old_operation_id" 1 "$EVIDENCE_DIR/proposed/old-request-body.json" "$EVIDENCE_DIR/proposed/mongo-old.json"
jq -e '.count == 1 and (.facts | length) == 1' "$EVIDENCE_DIR/proposed/mongo-old.json" >/dev/null
record_timeline old_operation_recovered_by_query "$(jq -cn --arg operation_id "$old_operation_id" '{operation_id:$operation_id,redispatched:false}')"

new_body_base64="$(base64 -w0 "$EVIDENCE_DIR/proposed/new-request-body.json")"
jq -cn --arg call "$NEW_CALL_ID" --arg url "$effect_v2_url" --arg body "$new_body_base64" '{
  call_id:$call,kind:"reserve-v2",method:"POST",url:$url,
  headers:{"Content-Type":"application/json"},body:$body
}' > "$EVIDENCE_DIR/proposed/execute-new.json"
api_post /v1/execute "$EVIDENCE_DIR/proposed/execute-new.json" "$EVIDENCE_DIR/proposed/new-response.json" 200 "$operation_token"
jq -e --arg id "$new_operation_id" '.operation_id == $id and .phase == "succeeded" and .recovered_by_query == false' \
  "$EVIDENCE_DIR/proposed/new-response.json" >/dev/null
effect_stats effect-v2 "$EVIDENCE_DIR/proposed/effect-v2-stats.json"
jq -e '.deliveries == 1 and .upstream_successes == 1 and .drops == 0' "$EVIDENCE_DIR/proposed/effect-v2-stats.json" >/dev/null

curl -fsS -H "Authorization: Bearer $admin_token" "$control_url/v1/state" > "$EVIDENCE_DIR/state/final-state.json"
curl -fsS -H "Authorization: Bearer $admin_token" "$control_url/v1/history" > "$EVIDENCE_DIR/state/history.json"
new_request_hash="$(jq -r --arg id "$new_operation_id" '.operations[$id].request_hash' "$EVIDENCE_DIR/state/final-state.json")"
observer_post "$new_operation_id" "$new_request_hash" "$EVIDENCE_DIR/proposed/new-request-body.json" \
  "$EVIDENCE_DIR/proposed/new-observer-response.json"
jq -e '.outcome == "succeeded"' "$EVIDENCE_DIR/proposed/new-observer-response.json" >/dev/null
save_mongo_fact "$new_operation_id" 1 "$EVIDENCE_DIR/proposed/new-request-body.json" "$EVIDENCE_DIR/proposed/mongo-new.json"
jq -e '.count == 1 and (.facts | length) == 1' "$EVIDENCE_DIR/proposed/mongo-new.json" >/dev/null
docker exec "$observation_client" wget -qO- -T 5 http://observer:8090/v1/stats/facts > "$EVIDENCE_DIR/adapter/observer-facts.json"
cp "$EVIDENCE_DIR/state/runtime.head" "$EVIDENCE_DIR/state/history-head.json"
jq -e --arg old "$old_operation_id" --arg new "$new_operation_id" --arg old_target "$effect_v1_url" --arg new_target "$effect_v2_url" '
  .requirement.id == "deathstar-reservations-v2" and
  .operations[$old].kind == "reserve-v1" and .operations[$old].target == $old_target and
  .operations[$old].phase == "succeeded" and .operations[$old].settlement == "query" and
  .operations[$new].kind == "reserve-v2" and .operations[$new].target == $new_target and
  .operations[$new].phase == "succeeded"
' "$EVIDENCE_DIR/state/final-state.json" >/dev/null

# Real deletion probes: old containers are gone while both replacements run.
set +e
docker inspect safe-change-step15-frontend-v1 >/dev/null 2> "$work_dir/frontend-v1-removal.stderr"
frontend_v1_removal_code=$?
docker inspect safe-change-step15-effect-v1 >/dev/null 2> "$work_dir/effect-v1-removal.stderr"
effect_v1_removal_code=$?
docker inspect "$frontend_v2" > "$work_dir/frontend-v2-inspect.json" 2> "$work_dir/frontend-v2.stderr"
frontend_v2_code=$?
docker inspect safe-change-step15-effect-v2 > "$work_dir/effect-v2-inspect.json" 2> "$work_dir/effect-v2.stderr"
effect_v2_code=$?
set -e
jq -n --argjson frontend_v1_code "$frontend_v1_removal_code" --argjson effect_v1_code "$effect_v1_removal_code" \
  --argjson frontend_v2_code "$frontend_v2_code" --argjson effect_v2_code "$effect_v2_code" \
  --rawfile frontend_v1_stderr "$work_dir/frontend-v1-removal.stderr" \
  --rawfile effect_v1_stderr "$work_dir/effect-v1-removal.stderr" \
  --slurpfile frontend_v2 "$work_dir/frontend-v2-inspect.json" --slurpfile effect_v2 "$work_dir/effect-v2-inspect.json" '{
    schema:1,
    frontend_v1:{exit_code:$frontend_v1_code,stderr:$frontend_v1_stderr},
    effect_v1:{exit_code:$effect_v1_code,stderr:$effect_v1_stderr},
    frontend_v2:{exit_code:$frontend_v2_code,running:$frontend_v2[0][0].State.Running},
    effect_v2:{exit_code:$effect_v2_code,running:$effect_v2[0][0].State.Running},
    pass:($frontend_v1_code != 0 and $effect_v1_code != 0 and $frontend_v2_code == 0 and
      $effect_v2_code == 0 and $frontend_v2[0][0].State.Running and $effect_v2[0][0].State.Running)
  }' > "$EVIDENCE_DIR/docker/removal-probes.json"
jq -e '.pass == true' "$EVIDENCE_DIR/docker/removal-probes.json" >/dev/null

networks_of() { docker inspect "$1" | jq -c '.[0].NetworkSettings.Networks | keys | sort'; }
control_networks="$(networks_of "$control")"
effect_v1_networks="$(jq -c '.[0].NetworkSettings.Networks | keys | sort' "$EVIDENCE_DIR/proposed/effect-v1-before-removal.json")"
effect_v2_networks="$(networks_of safe-change-step15-effect-v2)"
observer_networks="$(networks_of "$observer")"
frontend_v1_networks="$(jq -c '.[0].NetworkSettings.Networks | keys | sort' "$EVIDENCE_DIR/proposed/frontend-v1-before-removal.json")"
frontend_v2_networks="$(networks_of "$frontend_v2")"
reservation_networks="$(networks_of "$reservation_container")"
mongo_networks="$(networks_of "$mongo_container")"

probe_failure() {
  local container=$1 url=$2 output_prefix=$3
  local code
  set +e
  docker exec "$container" wget -qO- -T 2 "$url" > "$output_prefix.stdout" 2> "$output_prefix.stderr"
  code=$?
  set -e
  jq -n --argjson exit_code "$code" --rawfile stderr "$output_prefix.stderr" \
    '{exit_code:$exit_code,stderr:$stderr}'
}
effect_mongo_probe="$(probe_failure safe-change-step15-effect-v2 http://reservation-mongo:27017 "$work_dir/effect-mongo")"
observer_frontend_probe="$(probe_failure "$observer" http://frontend-v2:5000 "$work_dir/observer-frontend")"
observer_reservation_probe="$(probe_failure "$observer" http://reservation:8087 "$work_dir/observer-reservation")"
control_frontend_probe="$(probe_failure "$control" http://frontend-v2:5000 "$work_dir/control-frontend")"
control_reservation_probe="$(probe_failure "$control" http://reservation:8087 "$work_dir/control-reservation")"
control_mongo_probe="$(probe_failure "$control" http://reservation-mongo:27017 "$work_dir/control-mongo")"
probe_success() {
  local container=$1 url=$2
  local body code
  set +e
  body="$(docker exec "$container" wget -qO- -T 3 "$url" 2>/dev/null)"
  code=$?
  set -e
  [[ "$code" -eq 0 ]]
  jq -e '.status == "ok"' >/dev/null <<< "$body"
  jq -cn --argjson exit_code "$code" --argjson response "$body" '{exit_code:$exit_code,response:$response}'
}
control_effect_health="$(probe_success "$control" http://effect-v2:8090/healthz)"
control_observer_health="$(probe_success "$control" http://observer:8090/healthz)"

network_members() {
  docker network inspect "$1" | jq -c '[.[0].Containers[]?.Name] | sort'
}
control_members="$(network_members "$CONTROL_NETWORK")"
frontdoor_members="$(network_members "$FRONTDOOR_NETWORK")"
observation_members="$(network_members "$OBSERVATION_NETWORK")"
application_members="$(network_members "$application_network")"
jq -n --arg control_name "$CONTROL_NETWORK" --arg frontdoor_name "$FRONTDOOR_NETWORK" \
  --arg observation_name "$OBSERVATION_NETWORK" --arg application_name "$application_network" \
  --argjson control_members "$control_members" --argjson frontdoor_members "$frontdoor_members" \
  --argjson observation_members "$observation_members" --argjson application_members "$application_members" \
  --argjson control_networks "$control_networks" --argjson effect_v1_networks "$effect_v1_networks" \
  --argjson effect_v2_networks "$effect_v2_networks" --argjson observer_networks "$observer_networks" \
  --argjson frontend_v1_networks "$frontend_v1_networks" --argjson frontend_v2_networks "$frontend_v2_networks" \
  --argjson reservation_networks "$reservation_networks" --argjson mongo_networks "$mongo_networks" \
  --argjson effect_mongo_probe "$effect_mongo_probe" --argjson observer_frontend_probe "$observer_frontend_probe" \
  --argjson observer_reservation_probe "$observer_reservation_probe" --argjson control_frontend_probe "$control_frontend_probe" \
  --argjson control_reservation_probe "$control_reservation_probe" --argjson control_mongo_probe "$control_mongo_probe" \
  --argjson control_effect_health "$control_effect_health" --argjson control_observer_health "$control_observer_health" '
  def overlap($a;$b): [$a[] as $x | $b[] | select(. == $x)] | unique;
  {
    schema:1,
    networks:{control:$control_name,frontdoor:$frontdoor_name,observation:$observation_name,application:$application_name},
    members:{control:$control_members,frontdoor:$frontdoor_members,observation:$observation_members,application:$application_members},
    component_networks:{control:$control_networks,effect_v1:$effect_v1_networks,effect_v2:$effect_v2_networks,
      observer:$observer_networks,frontend_v1:$frontend_v1_networks,frontend_v2:$frontend_v2_networks,
      reservation:$reservation_networks,mongo:$mongo_networks},
    assertions:{
      effect_mongo_disjoint:((overlap($effect_v1_networks;$mongo_networks)|length == 0) and
        (overlap($effect_v2_networks;$mongo_networks)|length == 0)),
      observer_frontend_disjoint:((overlap($observer_networks;$frontend_v1_networks)|length == 0) and
        (overlap($observer_networks;$frontend_v2_networks)|length == 0)),
      observer_reservation_disjoint:(overlap($observer_networks;$reservation_networks)|length == 0),
      control_frontend_disjoint:((overlap($control_networks;$frontend_v1_networks)|length == 0) and
        (overlap($control_networks;$frontend_v2_networks)|length == 0)),
      control_reservation_disjoint:(overlap($control_networks;$reservation_networks)|length == 0),
      control_mongo_disjoint:(overlap($control_networks;$mongo_networks)|length == 0),
      control_effect_shared:((overlap($control_networks;$effect_v1_networks)|length == 1) and
        (overlap($control_networks;$effect_v2_networks)|length == 1)),
      control_observer_shared:(overlap($control_networks;$observer_networks)|length == 1)
    },
    direct_probes:{effect_to_mongo:$effect_mongo_probe,observer_to_frontend:$observer_frontend_probe,
      observer_to_reservation:$observer_reservation_probe,control_to_frontend:$control_frontend_probe,
      control_to_reservation:$control_reservation_probe,control_to_mongo:$control_mongo_probe,
      control_to_effect:$control_effect_health,control_to_observer:$control_observer_health}
  }
  | .pass=((.assertions|to_entries|all(.value == true)) and
      (.direct_probes.effect_to_mongo.exit_code != 0) and
      (.direct_probes.observer_to_frontend.exit_code != 0) and
      (.direct_probes.observer_to_reservation.exit_code != 0) and
      (.direct_probes.control_to_frontend.exit_code != 0) and
      (.direct_probes.control_to_reservation.exit_code != 0) and
      (.direct_probes.control_to_mongo.exit_code != 0) and
      (.direct_probes.control_to_effect.exit_code == 0) and
      (.direct_probes.control_to_effect.response.status == "ok") and
      (.direct_probes.control_to_observer.exit_code == 0) and
      (.direct_probes.control_to_observer.response.status == "ok"))
  ' > "$EVIDENCE_DIR/docker/network-proof.json"
jq -e '.pass == true' "$EVIDENCE_DIR/docker/network-proof.json" >/dev/null

docker image inspect "$V1_IMAGE" "$V2_IMAGE" "$RUNTIME_IMAGE" > "$EVIDENCE_DIR/docker/images.json"
mapfile -t final_container_ids < <(docker ps -aq --filter label=safe-change.step=15)
mapfile -t compose_container_ids < <(docker ps -aq --filter "label=com.docker.compose.project=$PROJECT")
all_container_ids=("${final_container_ids[@]}" "${compose_container_ids[@]}")
printf '%s\n' "${all_container_ids[@]}" | awk 'NF && !seen[$0]++' > "$work_dir/container-ids"
mapfile -t unique_container_ids < "$work_dir/container-ids"
docker inspect "${unique_container_ids[@]}" > "$EVIDENCE_DIR/docker/containers.json"
docker network inspect "$CONTROL_NETWORK" "$FRONTDOOR_NETWORK" "$OBSERVATION_NETWORK" "$application_network" \
  > "$EVIDENCE_DIR/docker/networks.json"
"${compose[@]}" logs --no-color > "$EVIDENCE_DIR/docker/logs/official-compose.log" 2>&1
for name in "$control" "$observer" "$frontend_v2" safe-change-step15-effect-v2; do
  save_logs "$name" "$EVIDENCE_DIR/docker/logs/$name.log"
done

jq -n --arg repository "$DEATHSTAR_REPOSITORY" --arg v1_tag "$V1_TAG" --arg v1_commit "$V1_COMMIT" \
  --arg v1_tree "$v1_tree" --arg v1_image "$V1_IMAGE" --arg v1_image_id "$v1_image_id" \
  --arg v2_tag "$V2_TAG" --arg v2_commit "$V2_COMMIT" --arg v2_tree "$v2_tree" \
  --arg v2_image "$V2_IMAGE" --arg v2_image_id "$v2_image_id" --arg runtime_head "$runtime_git_head" \
  --arg runtime_image "$RUNTIME_IMAGE" --arg runtime_image_id "$runtime_image_id" --arg checker_sha256 "$checker_sha256" \
  --argjson v1_clean_before "$v1_source_clean_before_build" --argjson v1_clean_after "$v1_source_clean_after_build" \
  --argjson v2_clean_before "$v2_source_clean_before_build" --argjson v2_clean_after "$v2_source_clean_after_build" \
  --arg v1_status_before "$v1_status_before_build" --arg v1_status_after "$v1_status_after_build" \
  --arg v2_status_before "$v2_status_before_build" --arg v2_status_after "$v2_status_after_build" \
  --arg runtime_status_before "$runtime_status_before_build" --arg runtime_status_after "$runtime_status_after_build" \
  --arg domain "$DOMAIN" --arg raw_call "$RAW_CALL_ID" --arg drain_call "$DRAIN_CALL_ID" \
  --arg raw_operation "$raw_operation_id" --arg drain_operation "$drain_operation_id" \
  --arg old_call "$OLD_CALL_ID" --arg old_operation "$old_operation_id" --arg new_call "$NEW_CALL_ID" \
  --arg new_operation "$new_operation_id" --arg never_call "$NEVER_CALL_ID" --arg never_operation "$never_operation_id" \
  --arg multi_call "$MULTI_CALL_ID" --arg multi_operation "$multi_operation_id" \
  --arg effect_v1 "$effect_v1_url" --arg effect_v2 "$effect_v2_url" --arg query "$query_url" '{
    schema:1,repository:$repository,
    releases:{
      v1:{tag:$v1_tag,commit:$v1_commit,tree:$v1_tree,image:$v1_image,image_id:$v1_image_id,
        source_clean_before_build:$v1_clean_before,source_clean_after_build:$v1_clean_after,
        status_porcelain_before_build:$v1_status_before,status_porcelain_after_build:$v1_status_after},
      v2:{tag:$v2_tag,commit:$v2_commit,tree:$v2_tree,image:$v2_image,image_id:$v2_image_id,
        source_clean_before_build:$v2_clean_before,source_clean_after_build:$v2_clean_after,
        status_porcelain_before_build:$v2_status_before,status_porcelain_after_build:$v2_status_after}},
    runtime:{git_head:$runtime_head,image:$runtime_image,image_id:$runtime_image_id,checker_sha256:$checker_sha256,
      source_clean_before_build:($runtime_status_before == ""),source_clean_after_build:($runtime_status_after == ""),
      status_porcelain_before_build:$runtime_status_before,status_porcelain_after_build:$runtime_status_after},
    identities:{domain:$domain,
      raw_retry:{call_id:$raw_call,operation_id:$raw_operation},
      old_version_drain:{call_id:$drain_call,operation_id:$drain_operation},
      proposed_old:{call_id:$old_call,operation_id:$old_operation},
      proposed_new:{call_id:$new_call,operation_id:$new_operation},
      unexecuted:{call_id:$never_call,operation_id:$never_operation},
      multi_night:{call_id:$multi_call,operation_id:$multi_operation}},
    urls:{raw_effect:"http://effect-raw:8090/v1/reserve",drain_effect:"http://effect-drain:8090/v1/reserve",
      effect_v1:$effect_v1,effect_v2:$effect_v2,query:$query}
  }' > "$EVIDENCE_DIR/upstream.json"

jq -n \
  --slurpfile raw_stats "$EVIDENCE_DIR/baselines/raw-retry/adapter-stats.json" \
  --slurpfile raw_mongo "$EVIDENCE_DIR/baselines/raw-retry/mongo.json" \
  --slurpfile drain_stats "$EVIDENCE_DIR/baselines/old-version-drain/adapter-stats.json" \
  --slurpfile drain_mongo "$EVIDENCE_DIR/baselines/old-version-drain/mongo.json" \
  --slurpfile old_stats "$EVIDENCE_DIR/proposed/effect-v1-stats.json" \
  --slurpfile new_stats "$EVIDENCE_DIR/proposed/effect-v2-stats.json" \
  --slurpfile old_mongo "$EVIDENCE_DIR/proposed/mongo-old.json" \
  --slurpfile new_mongo "$EVIDENCE_DIR/proposed/mongo-new.json" '{
    schema:1,rows:[
      {condition:"raw-retry",safety:false,availability:true,old_version_retained:true,
        deliveries:$raw_stats[0].deliveries,commits:$raw_stats[0].upstream_successes,
        mongo_rows:$raw_mongo[0].count,recovered_by_query:false,pass:($raw_stats[0].deliveries == 2 and $raw_mongo[0].count == 2)},
      {condition:"old-version-drain",safety:true,availability:false,old_version_retained:true,
        deliveries:$drain_stats[0].deliveries,commits:$drain_stats[0].upstream_successes,
        mongo_rows:$drain_mongo[0].count,recovered_by_query:false,pass:($drain_stats[0].deliveries == 1 and $drain_mongo[0].count == 1)},
      {condition:"history-query-recovery",safety:true,availability:true,old_version_retained:false,
        deliveries:($old_stats[0].deliveries + $new_stats[0].deliveries),
        commits:($old_stats[0].upstream_successes + $new_stats[0].upstream_successes),
        mongo_rows:($old_mongo[0].count + $new_mongo[0].count),recovered_by_query:true,
        pass:($old_stats[0].deliveries == 1 and $new_stats[0].deliveries == 1 and
          $old_mongo[0].count == 1 and $new_mongo[0].count == 1)}
    ]
  } | .pass=(.rows|all(.pass == true))' > "$EVIDENCE_DIR/baseline-matrix.json"
jq -e '.pass == true' "$EVIDENCE_DIR/baseline-matrix.json" >/dev/null

history_sequence="$(jq -r '.history.sequence' "$EVIDENCE_DIR/state/final-state.json")"
history_hash="$(jq -r '.history.hash' "$EVIDENCE_DIR/state/final-state.json")"
jq -n --slurpfile upstream "$EVIDENCE_DIR/upstream.json" --slurpfile matrix "$EVIDENCE_DIR/baseline-matrix.json" \
  --slurpfile network "$EVIDENCE_DIR/docker/network-proof.json" --slurpfile removal "$EVIDENCE_DIR/docker/removal-probes.json" \
  --slurpfile final_state "$EVIDENCE_DIR/state/final-state.json" --argjson history_sequence "$history_sequence" \
  --arg history_hash "$history_hash" --arg old_operation "$old_operation_id" --arg new_operation "$new_operation_id" '{
    schema:1,
    upstream:$upstream[0].releases,
    conditions:($matrix[0].rows | map({key:.condition,value:.}) | from_entries),
    history:{sequence:$history_sequence,hash:$history_hash},
    network_isolation:true,
    pass:false
  }
  | .pass=(($upstream[0].releases.v1.source_clean_before_build and $upstream[0].releases.v1.source_clean_after_build and
      $upstream[0].releases.v2.source_clean_before_build and $upstream[0].releases.v2.source_clean_after_build) and
    $network[0].pass and $removal[0].pass and $matrix[0].pass and
    $final_state[0].operations[$old_operation].kind == "reserve-v1" and
    $final_state[0].operations[$old_operation].settlement == "query" and
    $final_state[0].operations[$new_operation].kind == "reserve-v2" and
    .history.sequence > 0 and (.history.hash|test("^[0-9a-f]{64}$")))' > "$EVIDENCE_DIR/result.json"
jq -e '.pass == true' "$EVIDENCE_DIR/result.json" >/dev/null
record_timeline run_passed "$(jq -cn --argjson sequence "$history_sequence" --arg hash "$history_hash" '{history_sequence:$sequence,history_hash:$hash}')"
run_succeeded=1
jq . "$EVIDENCE_DIR/result.json"
