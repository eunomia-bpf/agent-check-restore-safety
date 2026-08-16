#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
compose_file="$script_dir/compose.yaml"
if [[ -z "${NO_QUERY_STATE_DIR:-}" ]]; then
  NO_QUERY_STATE_DIR="$(mktemp -d /tmp/safe-change-restate-h1-no-query.XXXXXX)"
fi
NO_QUERY_STATE_DIR="$(realpath "$NO_QUERY_STATE_DIR")"
results_dir="$NO_QUERY_STATE_DIR/results"
mkdir -p "$results_dir"
chmod 700 "$NO_QUERY_STATE_DIR" "$results_dir"

for command in cmp curl docker go jq python3 realpath sha256sum tr wc; do
  command -v "$command" >/dev/null || {
    echo "required command not found: $command" >&2
    exit 1
  }
done

build_env="${HARNESS_BUILD_ENV:-$NO_QUERY_STATE_DIR/build.env}"
if [[ "${SKIP_BUILD:-0}" != "1" ]]; then
  "$script_dir/build.sh" "$build_env" >"$results_dir/build.log"
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
cp "$build_env" "$results_dir/build.env"
chmod 600 "$results_dir/build.env"

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
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-safe-change-restate-h1-no-query-$$}"
PAYMENT_HOLD_BEFORE_COMMIT=false
PAYMENT_HOLD_AFTER_COMMIT=true
export RESTATE_INGRESS_PORT RESTATE_ADMIN_PORT CONTROL_PORT JAEGER_PORT WEBUI_PORT
export COMPOSE_PROJECT_NAME PAYMENT_HOLD_BEFORE_COMMIT PAYMENT_HOLD_AFTER_COMMIT

compose_all=(docker compose --project-name "$COMPOSE_PROJECT_NAME" --file "$compose_file" --profile h1 --profile target)
cleanup() {
  local status=$?
  printf '%s\n' "$status" >"$results_dir/no-query-exit-status.txt"
  "${compose_all[@]}" ps --all >"$results_dir/no-query-compose-ps.txt" 2>&1 || true
  "${compose_all[@]}" logs --no-color >"$results_dir/no-query-compose.log" 2>&1 || true
  if [[ "${KEEP_HARNESS:-0}" != "1" ]]; then
    "${compose_all[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
  fi
  echo "Restate H1 no-query evidence: $NO_QUERY_STATE_DIR" >&2
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Reuse the exact H1 fault and official Restate cut. The only ablation is that
# the Operation's frozen query endpoint is a provider-local path that does not
# exist. The base runner is expected to stop at its first failed recovery.
set +e
KEEP_HARNESS=1 PAYMENT_QUERY_PATH=/v1/query-unavailable \
  H1_STATE_DIR="$NO_QUERY_STATE_DIR" SKIP_BUILD=1 HARNESS_BUILD_ENV="$build_env" \
  RESTATE_INGRESS_PORT="$RESTATE_INGRESS_PORT" RESTATE_ADMIN_PORT="$RESTATE_ADMIN_PORT" \
  CONTROL_PORT="$CONTROL_PORT" JAEGER_PORT="$JAEGER_PORT" WEBUI_PORT="$WEBUI_PORT" \
  COMPOSE_PROJECT_NAME="$COMPOSE_PROJECT_NAME" \
  "$script_dir/run-h1-preflight.sh" \
  >"$results_dir/base-runner.stdout" 2>"$results_dir/base-runner.stderr"
base_status=$?
set -e
printf '%s\n' "$base_status" >"$results_dir/base-runner-exit-status.txt"
if [[ $base_status -eq 0 ]]; then
  echo "H1 unexpectedly recovered through an unavailable query endpoint" >&2
  exit 1
fi

required_cut_files=(
  control-unknown.json payment-at-commit.json requirement-v1.json requirement-v2.json
  source-cut-status.json source-cut-journal.json source-cut-workflow-state.json
  source-v1-removal.json
)
for required in "${required_cut_files[@]}"; do
  [[ -s "$results_dir/$required" ]] || {
    echo "base H1 runner failed before the real cut: missing $required" >&2
    exit 1
  }
done

query_target='http://payment:8081/v1/query-unavailable'
jq -e --arg query "$query_target" '
  .kinds["charge-v1"].queryable == true and
  .kinds["charge-v1"].query_target == $query
' "$results_dir/requirement-v1.json" >/dev/null
jq -e --arg query "$query_target" '
  .deliveries == 1 and .commits == 1 and .paths["/v1/charge"] == 1
' "$results_dir/payment-at-commit.json" >/dev/null
jq -e --arg query "$query_target" '
  ([.operations[] | select(
    .kind == "charge-v1" and .phase == "unknown" and
    .queryable == true and .query_target == $query
  )] | length) == 1
' "$results_dir/control-unknown.json" >/dev/null

control_url="http://127.0.0.1:$CONTROL_PORT"
admin_token="$("${compose_all[@]}" exec -T control cat /state/admin-token | tr -d '\r\n')"
if [[ ${#admin_token} -lt 32 ]]; then
  echo "control did not retain a valid admin token" >&2
  exit 1
fi

control_get() {
  local path=$1 output=$2
  curl -fsS --header "Authorization: Bearer $admin_token" \
    "$control_url$path" >"$output"
}

control_post() {
  local path=$1 input=$2 output=$3
  curl -fsS --header "Authorization: Bearer $admin_token" \
    --header 'Content-Type: application/json' --data-binary "@$input" \
    "$control_url$path" >"$output"
}

control_get /v1/state "$results_dir/control-before-no-query.json"
control_get /v1/history "$results_dir/history-before-no-query.json"
operation_id="$(jq -r '[.operations[] | select(.kind == "charge-v1")][0].id' "$results_dir/control-unknown.json")"
if [[ ! "$operation_id" =~ ^op-[0-9a-f]{64}$ ]]; then
  echo "real cut did not retain exactly one valid payment Operation" >&2
  exit 1
fi
set +e
recovery_status="$(
  curl -sS --output "$results_dir/no-query-recovery.json" \
    --write-out '%{http_code}' --request POST \
    --header "Authorization: Bearer $admin_token" \
    "$control_url/v1/operations/$operation_id/recover"
)"
recovery_curl_status=$?
set -e
if [[ $recovery_curl_status -ne 0 || "$recovery_status" != 409 ]]; then
  echo "unavailable authoritative query did not fail closed with HTTP 409" >&2
  exit 1
fi
printf '%s\n' "$recovery_status" >"$results_dir/no-query-recovery.http-status.txt"
jq -e '
  .code == "outcome_unknown" and .outcome.phase == "unknown" and
  .outcome.result_hash == "" and .outcome.recovered_by_query == false
' "$results_dir/no-query-recovery.json" >/dev/null

control_get /v1/state "$results_dir/control-after-no-query.json"
control_get /v1/history "$results_dir/history-after-no-query.json"
jq -S . "$results_dir/control-before-no-query.json" >"$results_dir/control-before-no-query.normalized.json"
jq -S . "$results_dir/control-after-no-query.json" >"$results_dir/control-after-no-query.normalized.json"
jq -S . "$results_dir/history-before-no-query.json" >"$results_dir/history-before-no-query.normalized.json"
jq -S . "$results_dir/history-after-no-query.json" >"$results_dir/history-after-no-query.normalized.json"
cmp "$results_dir/control-before-no-query.normalized.json" "$results_dir/control-after-no-query.normalized.json"
cmp "$results_dir/history-before-no-query.normalized.json" "$results_dir/history-after-no-query.normalized.json"

control_post /v1/compile "$results_dir/requirement-v2.json" "$results_dir/no-query-certificate-v2.json"
jq -e '.decision == "impossible" and .rule == null and .witness != null' \
  "$results_dir/no-query-certificate-v2.json" >/dev/null
control_post /v1/certificate-state "$results_dir/no-query-certificate-v2.json" \
  "$results_dir/no-query-certificate-state-v2.json"
(
  cd "$script_dir/../.."
  go run ./cmd/check-certificate \
    -state "$results_dir/no-query-certificate-state-v2.json" \
    -certificate "$results_dir/no-query-certificate-v2.json"
) >"$results_dir/no-query-certificate-verdict-v2.json"
jq -e '.valid == true and .decision == "impossible"' \
  "$results_dir/no-query-certificate-verdict-v2.json" >/dev/null

if [[ -n "$("${compose_all[@]}" ps --all --quiet order-v2)" ]]; then
  echo "no-query ablation created the refused target worker" >&2
  exit 1
fi
"${compose_all[@]}" exec -T control wget -qO- http://payment:8081/v1/stats \
  >"$results_dir/no-query-payment-stats.json"
"${compose_all[@]}" exec -T control wget -qO- http://completion:8081/v1/stats \
  >"$results_dir/no-query-completion-stats.json"
jq -e '.deliveries == 1 and .commits == 1 and .paths["/v1/charge"] == 1' \
  "$results_dir/no-query-payment-stats.json" >/dev/null
jq -e '.deliveries == 0 and .commits == 0 and .paths == {}' \
  "$results_dir/no-query-completion-stats.json" >/dev/null

control_container="$("${compose_all[@]}" ps --quiet control)"
payment_container="$("${compose_all[@]}" ps --quiet payment)"
completion_container="$("${compose_all[@]}" ps --quiet completion)"
docker cp "$control_container:/state/runtime.history" "$results_dir/no-query-runtime.history"
docker cp "$control_container:/anchor/runtime.head" "$results_dir/no-query-runtime.head"
docker cp "$payment_container:/state/payment.history" "$results_dir/no-query-payment.history"
docker cp "$completion_container:/state/completion.history" "$results_dir/no-query-completion.history"
[[ "$(wc -l <"$results_dir/no-query-payment.history")" -eq 1 ]]
[[ "$(wc -c <"$results_dir/no-query-completion.history")" -eq 0 ]]

mapfile -t container_ids < <(
  docker ps --all --quiet --filter "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME"
)
docker inspect "${container_ids[@]}" >"$results_dir/no-query-containers.raw.json"
jq -e --arg v1 "$ORDER_V1_IMAGE" '
  ([.[] | select(.Image == $v1)] | length) == 0 and
  ([.[] | select(.Config.Labels["com.docker.compose.service"] == "order-v2")] | length) == 0
' "$results_dir/no-query-containers.raw.json" >/dev/null

jq -n \
  --arg operation_id "$operation_id" \
  --arg query_target "$query_target" \
  --arg target_image "$ORDER_V2_IMAGE" \
  --argjson payment "$(cat "$results_dir/no-query-payment-stats.json")" \
  --argjson recovery "$(cat "$results_dir/no-query-recovery.json")" \
  --argjson certificate "$(cat "$results_dir/no-query-certificate-v2.json")" '{
    schema:1,
    case:"h1-no-query",
    operation_id:$operation_id,
    query_target:$query_target,
    durable_payment_fact:true,
    payment:$payment,
    recovery:{http_status:409,body:$recovery},
    certificate:$certificate,
    planned_target_image:$target_image,
    target_started:false,
    completion_started:false,
    history_changed_by_failed_query:false
  }' >"$results_dir/no-query-summary.json"

cat "$results_dir/no-query-summary.json"
