#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -z "${PAIR_STATE_DIR:-}" ]]; then
  PAIR_STATE_DIR="$(mktemp -d /tmp/safe-change-restate-pair.XXXXXX)"
fi
PAIR_STATE_DIR="$(realpath "$PAIR_STATE_DIR")"
h0_dir="$PAIR_STATE_DIR/h0"
h1_dir="$PAIR_STATE_DIR/h1"
comparison_dir="$PAIR_STATE_DIR/comparison"
mkdir -p "$h0_dir" "$h1_dir" "$comparison_dir"
chmod 700 "$PAIR_STATE_DIR" "$h0_dir" "$h1_dir" "$comparison_dir"

for command in awk cat chmod cmp date jq mkdir realpath sha256sum tee wc; do
  command -v "$command" >/dev/null || {
    echo "required command not found: $command" >&2
    exit 1
  }
done

cleanup() {
  local status=$?
  printf '%s\n' "$status" >"$PAIR_STATE_DIR/exit-status.txt"
  echo "Restate paired preflight evidence: $PAIR_STATE_DIR" >&2
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

build_env="${HARNESS_BUILD_ENV:-$PAIR_STATE_DIR/build.env}"
if [[ "${SKIP_BUILD:-0}" != "1" ]]; then
  "$script_dir/build.sh" "$build_env" | tee "$PAIR_STATE_DIR/build.log"
elif [[ ! -f "$build_env" ]]; then
  echo "SKIP_BUILD=1 requires HARNESS_BUILD_ENV to name an existing file" >&2
  exit 1
fi

order_id="${ORDER_ID:-paired-order-$(date +%s)-$$}"
if [[ ! "$order_id" =~ ^[A-Za-z0-9._-]{1,128}$ ]]; then
  echo "ORDER_ID must contain only letters, digits, dot, underscore, or hyphen" >&2
  exit 1
fi
project_prefix="${COMPOSE_PROJECT_NAME:-safe-change-restate-pair-$$}"

echo "Running matched H0 for $order_id" >&2
ORDER_ID="$order_id" \
H0_STATE_DIR="$h0_dir" H1_STATE_DIR="$h0_dir" \
COMPOSE_PROJECT_NAME="${project_prefix}-h0" \
SKIP_BUILD=1 HARNESS_BUILD_ENV="$build_env" \
  "$script_dir/run-h0-preflight.sh" \
  >"$PAIR_STATE_DIR/h0.stdout" 2>"$PAIR_STATE_DIR/h0.stderr"

echo "Running matched H1 for $order_id" >&2
ORDER_ID="$order_id" \
H1_STATE_DIR="$h1_dir" \
COMPOSE_PROJECT_NAME="${project_prefix}-h1" \
SKIP_BUILD=1 HARNESS_BUILD_ENV="$build_env" \
  "$script_dir/run-h1-preflight.sh" \
  >"$PAIR_STATE_DIR/h1.stdout" 2>"$PAIR_STATE_DIR/h1.stderr"

h0="$h0_dir/results"
h1="$h1_dir/results"
[[ "$(cat "$h0/exit-status.txt")" == 0 ]]
[[ "$(cat "$h1/exit-status.txt")" == 0 ]]

cmp "$h0/order.json" "$h1/order.json"
cmp "$h0/requirement-v2.json" "$h1/requirement-v2.json"
order_sha256="$(sha256sum "$h0/order.json" | awk '{print $1}')"
requirement_sha256="$(sha256sum "$h0/requirement-v2.json" | awk '{print $1}')"

h0_token="$(jq -r '.payment.token' "$h0/summary.json")"
h1_token="$(jq -r '.payment.token' "$h1/summary.json")"
h0_operation="$(jq -r '.payment.operation_id' "$h0/summary.json")"
h1_operation="$(jq -r '.payment.operation_id' "$h1/summary.json")"
h0_invocation="$(jq -r '.source.invocation_id' "$h0/summary.json")"
h1_invocation="$(jq -r '.source.invocation_id' "$h1/summary.json")"
h0_source_image="$(jq -r '.source.image_id' "$h0/summary.json")"
h1_source_image="$(jq -r '.source.image_id' "$h1/summary.json")"
h0_target_image="$(jq -r '.target.planned_image_id' "$h0/summary.json")"
h1_target_image="$(jq -r '.target.image_id' "$h1/summary.json")"
h0_decision="$(jq -r '.decision' "$h0/certificate-v2.json")"
h1_decision="$(jq -r '.decision' "$h1/certificate-v2.json")"
[[ "$h0_token" == "$h1_token" ]]
[[ "$h0_operation" == "$h1_operation" ]]
[[ "$h0_invocation" == "$h1_invocation" ]]
[[ "$h0_source_image" == "$h1_source_image" ]]
[[ "$h0_target_image" == "$h1_target_image" ]]
[[ "$h0_decision" == "impossible" ]]
[[ "$h1_decision" == "activate" ]]

jq -S '{rows:[.rows[] | {
  index,version,entry_type,name,completed,raw,raw_length,entry_lite_json
}]}' "$h0/source-cut-journal.json" \
  >"$comparison_dir/h0-journal.normalized.json"
jq -S '{rows:[.rows[] | {
  index,version,entry_type,name,completed,raw,raw_length,entry_lite_json
}]}' "$h1/source-cut-journal.json" \
  >"$comparison_dir/h1-journal.normalized.json"
cmp "$comparison_dir/h0-journal.normalized.json" \
  "$comparison_dir/h1-journal.normalized.json"
journal_sha256="$(
  sha256sum "$comparison_dir/h0-journal.normalized.json" | awk '{print $1}'
)"

jq -S '{rows:[.rows[] | {
  service_name,service_key,key,value,value_utf8,value_length
}]}' "$h0/source-cut-workflow-state.json" \
  >"$comparison_dir/h0-workflow-state.normalized.json"
jq -S '{rows:[.rows[] | {
  service_name,service_key,key,value,value_utf8,value_length
}]}' "$h1/source-cut-workflow-state.json" \
  >"$comparison_dir/h1-workflow-state.normalized.json"
cmp "$comparison_dir/h0-workflow-state.normalized.json" \
  "$comparison_dir/h1-workflow-state.normalized.json"
workflow_state_sha256="$(
  sha256sum "$comparison_dir/h0-workflow-state.normalized.json" | awk '{print $1}'
)"

jq -S '{rows:[.rows[] | {
  id,target,status,pinned_service_protocol_version,journal_size
}]}' "$h0/source-cut-status.json" \
  >"$comparison_dir/h0-status.normalized.json"
jq -S '{rows:[.rows[] | {
  id,target,status,pinned_service_protocol_version,journal_size
}]}' "$h1/source-cut-status.json" \
  >"$comparison_dir/h1-status.normalized.json"
cmp "$comparison_dir/h0-status.normalized.json" \
  "$comparison_dir/h1-status.normalized.json"
status_sha256="$(
  sha256sum "$comparison_dir/h0-status.normalized.json" | awk '{print $1}'
)"

[[ "$(wc -c <"$h0/payment.history")" -eq 0 ]]
[[ "$(wc -l <"$h1/payment.history")" -eq 1 ]]
jq -e '
  .payment.provider.deliveries == 1 and .payment.provider.commits == 0 and
  .target.certificate.decision == "impossible" and
  .target.container_present == false and .target.deployment_present == false and
  .target.drivers_started == false and .target.completion_started == false and
  .target.continuation_started == false
' "$h0/summary.json" >/dev/null
jq -e '
  .payment.provider.deliveries == 1 and .payment.provider.commits == 1 and
  .payment.recovery.recovered_by_query == true and
  .target.activated_before_start == true and
  .order.status == "DELIVERED"
' "$h1/summary.json" >/dev/null

jq -n \
  --arg order_id "$order_id" \
  --arg order_sha256 "$order_sha256" \
  --arg requirement_sha256 "$requirement_sha256" \
  --arg payment_token "$h0_token" \
  --arg payment_operation_id "$h0_operation" \
  --arg source_invocation_id "$h0_invocation" \
  --arg source_image_id "$h0_source_image" \
  --arg target_image_id "$h0_target_image" \
  --arg h0_decision "$h0_decision" \
  --arg h1_decision "$h1_decision" \
  --arg journal_sha256 "$journal_sha256" \
  --arg workflow_state_sha256 "$workflow_state_sha256" \
  --arg status_sha256 "$status_sha256" \
  --arg h0_dir "$h0_dir" \
  --arg h1_dir "$h1_dir" \
  --argjson h0 "$(cat "$h0/summary.json")" \
  --argjson h1 "$(cat "$h1/summary.json")" '{
    schema:1,
    experiment:"restate-food-ordering-matched-h0-h1-preflight",
    order:{id:$order_id,input_sha256:$order_sha256},
    matched_cut:{
      exact_input_bytes:true,
      exact_target_requirement_bytes:true,
      payment_token:$payment_token,
      payment_operation_id:$payment_operation_id,
      source_invocation_id:$source_invocation_id,
      source_image_id:$source_image_id,
      target_image_id:$target_image_id,
      source_image_equal:true,target_image_equal:true,
      normalized_status_sha256:$status_sha256,
      normalized_journal_sha256:$journal_sha256,
      normalized_workflow_state_sha256:$workflow_state_sha256,
      status_equal:true,journal_equal:true,workflow_state_equal:true,
      requirement_sha256:$requirement_sha256
    },
    only_semantic_cut_difference:{
      h0_durable_payment_fact:false,
      h1_durable_payment_fact:true,
      h0_provider:$h0.payment.provider,
      h1_provider:$h1.payment.provider
    },
    decisions:{
      h0:$h0_decision,
      h1:$h1_decision,
      h1_allow:$h1.target.activation.rule.allow
    },
    outcomes:{
      h0:{
        recovery_http_status:$h0.payment.recovery.http_status,
        target_started:$h0.target.container_present,
        continuation_started:$h0.target.continuation_started
      },
      h1:{
        recovered_by_query:$h1.payment.recovery.recovered_by_query,
        order_status:$h1.order.status,
        payment:$h1.payment.provider,
        completion:$h1.target.completion_provider
      }
    },
    evidence:{h0:$h0_dir,h1:$h1_dir}
  }' >"$PAIR_STATE_DIR/pair-summary.json"

cat "$PAIR_STATE_DIR/pair-summary.json"
