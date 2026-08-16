#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
output_root="${TEMPORAL_OLD_DRAIN_FULL_DIR:-}"
build_env="${HARNESS_BUILD_ENV:-}"
repetitions="${TEMPORAL_OLD_DRAIN_REPETITIONS:-5}"

if [[ -z "$output_root" || -z "$build_env" || "${SKIP_BUILD:-0}" != 1 ]]; then
  echo "TEMPORAL_OLD_DRAIN_FULL_DIR, SKIP_BUILD=1, and HARNESS_BUILD_ENV are required" >&2
  exit 64
fi
if [[ "$repetitions" != 5 ]]; then
  echo "the frozen old-drain matrix requires exactly 5 repetitions" >&2
  exit 64
fi
for command in chmod cp date find jq mkdir python3 realpath seq sha256sum sort wait; do
  command -v "$command" >/dev/null || {
    echo "required command not found: $command" >&2
    exit 1
  }
done
if [[ ! -f "$build_env" ]]; then
  echo "HARNESS_BUILD_ENV is not a file" >&2
  exit 64
fi
if [[ -e "$output_root" ]]; then
  if [[ ! -d "$output_root" || -n "$(find "$output_root" -mindepth 1 -print -quit)" ]]; then
    echo "TEMPORAL_OLD_DRAIN_FULL_DIR must be absent or empty" >&2
    exit 64
  fi
else
  mkdir -p "$output_root"
fi
output_root="$(realpath "$output_root")"
build_env="$(realpath "$build_env")"
chmod 700 "$output_root"
cp "$build_env" "$output_root/build.env"
sha256sum "$script_dir/run-old-drain-full.sh" >"$output_root/wrapper.sha256"
jq -n \
  --arg recorded_at "$(date --utc --iso-8601=seconds)" \
  --arg output_root "$output_root" --arg build_env "$build_env" \
  --argjson repetitions "$repetitions" '{
    schema:1,recorded_at:$recorded_at,cell:"old-drain",system:"temporal-pinned",
    output_root:$output_root,build_env:$build_env,repetitions:$repetitions,
    cases:["h0","h1"],decision:"retain-v1",target_started:false
  }' >"$output_root/full-metadata.json"

active_pids=()
stop_children() {
  local pid
  for pid in "${active_pids[@]}"; do
    kill -TERM "$pid" >/dev/null 2>&1 || true
  done
}
trap stop_children INT TERM

for repetition in $(seq 1 "$repetitions"); do
  printf -v label 'rep-%02d' "$repetition"
  pair_dir="$output_root/$label"
  mkdir -p "$pair_dir"

  OLD_DRAIN_CASE=h0 \
  TEMPORAL_OLD_DRAIN_STATE_ROOT="$pair_dir/h0" \
  SKIP_BUILD=1 HARNESS_BUILD_ENV="$build_env" \
    "$script_dir/run-old-drain-case.sh" \
    >"$pair_dir/h0-runner.stdout" 2>"$pair_dir/h0-runner.stderr" &
  h0_pid=$!
  OLD_DRAIN_CASE=h1 \
  TEMPORAL_OLD_DRAIN_STATE_ROOT="$pair_dir/h1" \
  SKIP_BUILD=1 HARNESS_BUILD_ENV="$build_env" \
    "$script_dir/run-old-drain-case.sh" \
    >"$pair_dir/h1-runner.stdout" 2>"$pair_dir/h1-runner.stderr" &
  h1_pid=$!
  active_pids=("$h0_pid" "$h1_pid")

  h0_status=0
  h1_status=0
  wait "$h0_pid" || h0_status=$?
  wait "$h1_pid" || h1_status=$?
  active_pids=()
  if [[ "$h0_status" -ne 0 || "$h1_status" -ne 0 ]]; then
    echo "$label runner failed: h0=$h0_status h1=$h1_status" >&2
    exit 1
  fi

  python3 "$script_dir/check-old-drain.py" --evidence "$pair_dir/h0" --case h0 \
    >"$pair_dir/h0-check.json"
  python3 "$script_dir/check-old-drain.py" --evidence "$pair_dir/h1" --case h1 \
    >"$pair_dir/h1-check.json"
  python3 "$script_dir/check-old-drain.py" --evidence "$pair_dir/h0" --peer "$pair_dir/h1" \
    >"$pair_dir/pair-check.json"
  python3 "$script_dir/check-old-drain-mutations.py" \
    --evidence "$pair_dir/h0" --case h0 --peer "$pair_dir/h1" \
    >"$pair_dir/h0-mutations.json"
  python3 "$script_dir/check-old-drain-mutations.py" \
    --evidence "$pair_dir/h1" --case h1 \
    >"$pair_dir/h1-mutations.json"
done

mapfile -t pair_checks < <(
  find "$output_root" -mindepth 2 -maxdepth 2 -name pair-check.json -type f -print | sort
)
if [[ "${#pair_checks[@]}" -ne "$repetitions" ]]; then
  echo "full matrix omitted a pair check" >&2
  exit 1
fi
jq -s --argjson repetitions "$repetitions" '
  [.[].h0, .[].h1] as $attempts |
  {
    schema:1,valid:(length == $repetitions and all(.[]; .valid == true)),
    cell:"old-drain",system:"temporal-pinned",repetitions:$repetitions,
    attempts:($attempts | length),same_temporal_cut:(all(.[]; .same_temporal_cut == true)),
    different_external_commit_fact:(all(.[]; .different_external_commit_fact == true)),
    old_code_required:(all($attempts[]; .old_code_required == true)),
    availability_preserved:(all($attempts[]; .availability_preserved == true)),
    target_never_started:(all($attempts[]; .target_started == false)),
    decisions:([$attempts[] | .case + ":retain-v1"] | unique),
    unique_evidence_digests:([$attempts[].evidence_digest] | unique | length),
    unique_pair_digests:([.[].pair_digest] | unique | length),
    unique_run_ids:([$attempts[].run_id] | unique | length),
    unique_v1_containers:([$attempts[].v1_container_id] | unique | length),
    payment_operation_ids:([$attempts[].payment_operation_id] | unique),
    completion_operation_ids:([$attempts[].completion_operation_id] | unique),
    pairs:.
  }
  | select(
      .valid and .attempts == (2 * $repetitions) and .same_temporal_cut
      and .different_external_commit_fact and .old_code_required
      and .availability_preserved and .target_never_started
      and .decisions == ["h0:retain-v1","h1:retain-v1"]
      and .unique_evidence_digests == (2 * $repetitions)
      and .unique_pair_digests == $repetitions
      and .unique_run_ids == (2 * $repetitions)
      and .unique_v1_containers == (2 * $repetitions)
      and (.payment_operation_ids | length) == 1
      and (.completion_operation_ids | length) == 1
    )
' "${pair_checks[@]}" >"$output_root/summary.json"
if [[ ! -s "$output_root/summary.json" ]]; then
  echo "full matrix summary invariant failed" >&2
  exit 1
fi
(
  cd "$output_root"
  while IFS= read -r -d '' artifact; do
    sha256sum "$artifact"
  done < <(find . -type f ! -path './SHA256SUMS' -print0 | sort -z)
) >"$output_root/SHA256SUMS"
cat "$output_root/summary.json"
