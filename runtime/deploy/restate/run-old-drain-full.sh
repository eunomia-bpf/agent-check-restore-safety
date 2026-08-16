#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
output_root="${OLD_DRAIN_FULL_DIR:-}"
build_env="${HARNESS_BUILD_ENV:-}"
repetitions="${OLD_DRAIN_REPETITIONS:-5}"
observation_seconds="${OLD_DRAIN_OBSERVATION_SECONDS:-20}"
terminal_seconds="${OLD_DRAIN_TERMINAL_SECONDS:-120}"

if [[ -z "$output_root" || -z "$build_env" ]]; then
  echo "OLD_DRAIN_FULL_DIR and HARNESS_BUILD_ENV are required" >&2
  exit 64
fi
if [[ ! "$repetitions" =~ ^[0-9]+$ || "$repetitions" -lt 1 || "$repetitions" -gt 20 ]]; then
  echo "OLD_DRAIN_REPETITIONS must be in [1,20]" >&2
  exit 64
fi
if [[ ! "$observation_seconds" =~ ^[0-9]+$ || "$observation_seconds" -lt 5 || "$observation_seconds" -gt 120 ]]; then
  echo "OLD_DRAIN_OBSERVATION_SECONDS must be in [5,120]" >&2
  exit 64
fi
if [[ ! "$terminal_seconds" =~ ^[0-9]+$ || "$terminal_seconds" -lt 20 || "$terminal_seconds" -gt 300 ]]; then
  echo "OLD_DRAIN_TERMINAL_SECONDS must be in [20,300]" >&2
  exit 64
fi
for command in cat chmod cp find jq mkdir python3 realpath seq sha256sum; do
  command -v "$command" >/dev/null || { echo "required command not found: $command" >&2; exit 1; }
done
[[ -f "$build_env" ]] || { echo "HARNESS_BUILD_ENV is not a file" >&2; exit 64; }
if [[ -e "$output_root" ]]; then
  if [[ ! -d "$output_root" || -n "$(find "$output_root" -mindepth 1 -print -quit)" ]]; then
    echo "OLD_DRAIN_FULL_DIR must be absent or empty" >&2
    exit 64
  fi
else
  mkdir -p "$output_root"
fi
output_root="$(realpath "$output_root")"
build_env="$(realpath "$build_env")"
chmod 700 "$output_root"
sha256sum "$script_dir/run-old-drain-full.sh" >"$output_root/wrapper.sha256"
cp "$build_env" "$output_root/build.env"
jq -n \
  --arg recorded_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg output_root "$output_root" --arg build_env "$build_env" \
  --argjson repetitions "$repetitions" --argjson observation_seconds "$observation_seconds" \
  --argjson terminal_seconds "$terminal_seconds" '{
    schema:1,recorded_at:$recorded_at,cell:"old-drain",system:"native-restate",
    output_root:$output_root,build_env:$build_env,repetitions:$repetitions,
    observation_seconds:$observation_seconds,terminal_seconds:$terminal_seconds
  }' >"$output_root/full-metadata.json"

for repetition in $(seq 1 "$repetitions"); do
  printf -v label 'rep-%02d' "$repetition"
  pair_dir="$output_root/$label"
  mkdir -p "$pair_dir"
  order_id="old-drain-$label"

  OLD_DRAIN_CASE=h0 \
  OLD_DRAIN_STATE_DIR="$pair_dir/h0" \
  ORDER_ID="$order_id" \
  OLD_DRAIN_OBSERVATION_SECONDS="$observation_seconds" \
  OLD_DRAIN_TERMINAL_SECONDS="$terminal_seconds" \
  SKIP_BUILD=1 HARNESS_BUILD_ENV="$build_env" \
    "$script_dir/run-old-drain-case.sh" >"$pair_dir/h0-runner.stdout" 2>"$pair_dir/h0-runner.stderr" &
  h0_pid=$!
  OLD_DRAIN_CASE=h1 \
  OLD_DRAIN_STATE_DIR="$pair_dir/h1" \
  ORDER_ID="$order_id" \
  OLD_DRAIN_OBSERVATION_SECONDS="$observation_seconds" \
  OLD_DRAIN_TERMINAL_SECONDS="$terminal_seconds" \
  SKIP_BUILD=1 HARNESS_BUILD_ENV="$build_env" \
    "$script_dir/run-old-drain-case.sh" >"$pair_dir/h1-runner.stdout" 2>"$pair_dir/h1-runner.stderr" &
  h1_pid=$!

  h0_status=0
  h1_status=0
  wait "$h0_pid" || h0_status=$?
  wait "$h1_pid" || h1_status=$?
  if [[ "$h0_status" -ne 0 || "$h1_status" -ne 0 ]]; then
    echo "$label runner failed: h0=$h0_status h1=$h1_status" >&2
    exit 1
  fi

  python3 "$script_dir/check-old-drain.py" --evidence "$pair_dir/h0" --case h0 \
    >"$pair_dir/h0-check.json"
  python3 "$script_dir/check-old-drain.py" --evidence "$pair_dir/h1" --case h1 \
    >"$pair_dir/h1-check.json"
  python3 "$script_dir/check-old-drain-mutations.py" --evidence "$pair_dir/h0" --case h0 \
    >"$pair_dir/h0-mutations.json"
  python3 "$script_dir/check-old-drain-mutations.py" --evidence "$pair_dir/h1" --case h1 \
    >"$pair_dir/h1-mutations.json"
  python3 "$script_dir/check-old-drain.py" --evidence "$pair_dir/h0" --peer "$pair_dir/h1" \
    >"$pair_dir/pair-check.json"
done

mapfile -t pair_checks < <(find "$output_root" -mindepth 2 -maxdepth 2 -name pair-check.json -type f | sort)
[[ "${#pair_checks[@]}" -eq "$repetitions" ]] || { echo "full matrix omitted a pair check" >&2; exit 1; }
jq -s --argjson repetitions "$repetitions" '
  [.[].h0, .[].h1] as $attempts |
  {
    schema:1,valid:(length == $repetitions and all(.[]; .valid == true)),
    cell:"old-drain",system:"native-restate",repetitions:$repetitions,
    attempts:($attempts | length),same_runtime_view:(all(.[]; .same_runtime_view == true)),
    different_external_commit_fact:(all(.[]; .different_external_commit_fact == true)),
    old_code_required:(all($attempts[]; .old_code_required == true)),
    v1_engaged:(all($attempts[]; .v1_engaged == true)),
    availability_preserved:(all($attempts[]; .availability_preserved == true)),
    completed_h0:([.[].h0 | select(.runtime_status == "completed")] | length),
    completed_h1:([.[].h1 | select(.runtime_status == "completed")] | length),
    requirement_satisfied_h0:([.[].h0 | select(.requirement_satisfied == true)] | length),
    requirement_satisfied_h1:([.[].h1 | select(.requirement_satisfied == true)] | length),
    duplicate_external_effect_h0:([.[].h0 | select(.duplicate_external_effect == true)] | length),
    duplicate_external_effect_h1:([.[].h1 | select(.duplicate_external_effect == true)] | length),
    h0_payment_counts:[.[].h0 | {deliveries:.payment_deliveries,commits:.payment_commits}],
    h1_payment_counts:[.[].h1 | {deliveries:.payment_deliveries,commits:.payment_commits}],
    h0_completion_counts:[.[].h0 | {deliveries:.completion_deliveries,commits:.completion_commits}],
    h1_completion_counts:[.[].h1 | {deliveries:.completion_deliveries,commits:.completion_commits}],
    unique_evidence_digests:([$attempts[].evidence_digest] | unique | length),
    unique_pair_digests:([.[].pair_digest] | unique | length),
    unique_invocation_ids:([.[].invocation_id] | unique | length),
    unique_payment_operation_ids:([$attempts[].payment_operation_id] | unique | length),
    pairs:.
  }
  | select(
      .valid and .attempts == (2 * $repetitions) and .same_runtime_view
      and .different_external_commit_fact and .old_code_required and .v1_engaged
      and .unique_evidence_digests == (2 * $repetitions)
      and .unique_pair_digests == $repetitions
      and .unique_invocation_ids == $repetitions
      and .unique_payment_operation_ids == $repetitions
    )
' "${pair_checks[@]}" >"$output_root/summary.json"
[[ -s "$output_root/summary.json" ]] || { echo "full matrix summary invariant failed" >&2; exit 1; }
cat "$output_root/summary.json"
