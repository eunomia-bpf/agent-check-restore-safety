#!/usr/bin/env bash
set -Eeuo pipefail

export LC_ALL=C

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
unsafe_dir="$script_dir/../temporal-unsafe"
expected_main_sha256="495e37bda60465e4be169605449a6d586f705faac95cbeb57f0ea49ab97a7fa5"
expected_unsafe_sha256="646c611a607556df783569332f0fbf941c31ddb790c1a32261d9bb81851e55e6"
repetitions=5

if [[ $# -ne 3 ]]; then
  echo "usage: $0 OUTPUT_ROOT MAIN_BUILD_ENV UNSAFE_BUILD_ENV" >&2
  exit 64
fi
output_root=$1
main_build_env=$2
unsafe_build_env=$3

for variable in \
  COMPOSE_FILE COMPOSE_PROFILES COMPOSE_PROJECT_NAME COMPOSE_PATH_SEPARATOR \
  COMPOSE_ENV_FILES COMPOSE_DISABLE_ENV_FILE; do
  if [[ -n "${!variable:-}" ]]; then
    echo "$variable must be empty" >&2
    exit 64
  fi
  unset "$variable"
done

for command in date docker find jq mkdir python3 realpath seq sha256sum sort; do
  command -v "$command" >/dev/null || {
    echo "required command not found: $command" >&2
    exit 1
  }
done
for input in "$main_build_env" "$unsafe_build_env"; do
  if [[ ! -f "$input" || -L "$input" ]]; then
    echo "build environment must be a regular, non-symlink file: $input" >&2
    exit 64
  fi
done
main_build_env="$(realpath -- "$main_build_env")"
unsafe_build_env="$(realpath -- "$unsafe_build_env")"
if [[ "$(sha256sum -- "$main_build_env" | awk '{print $1}')" != "$expected_main_sha256" ]]; then
  echo "MAIN_BUILD_ENV is not the frozen full-parity build" >&2
  exit 64
fi
if [[ "$(sha256sum -- "$unsafe_build_env" | awk '{print $1}')" != "$expected_unsafe_sha256" ]]; then
  echo "UNSAFE_BUILD_ENV is not the frozen full-parity unsafe build" >&2
  exit 64
fi

if [[ -e "$output_root" ]]; then
  if [[ ! -d "$output_root" || -n "$(find "$output_root" -mindepth 1 -print -quit)" ]]; then
    echo "OUTPUT_ROOT must be absent or empty" >&2
    exit 64
  fi
else
  mkdir -p -- "$output_root"
fi
output_root="$(realpath -- "$output_root")"
mkdir -p -- "$output_root/checkpoints"
chmod 700 "$output_root" "$output_root/checkpoints"
cp -- "$main_build_env" "$output_root/main-build.env"
cp -- "$unsafe_build_env" "$output_root/unsafe-build.env"
chmod 400 "$output_root/main-build.env" "$output_root/unsafe-build.env"

date -u +'%Y-%m-%dT%H:%M:%SZ' >"$output_root/start-time.txt"
sha256sum -- \
  "$script_dir/run-full-parity.sh" \
  "$script_dir/run-paired.sh" \
  "$script_dir/run-compatible.sh" \
  "$script_dir/run-old-drain-full.sh" \
  "$unsafe_dir/run-unsafe-full.sh" \
  "$script_dir/check-pair.py" \
  "$script_dir/check-compatible.py" \
  "$script_dir/check-old-drain.py" \
  "$unsafe_dir/check-unsafe.py" >"$output_root/programs.sha256"
jq -n \
  --arg recorded_at "$(date --utc --iso-8601=seconds)" \
  --arg output_root "$output_root" \
  --arg main_build_env "$main_build_env" \
  --arg unsafe_build_env "$unsafe_build_env" \
  --arg main_build_sha256 "$expected_main_sha256" \
  --arg unsafe_build_sha256 "$expected_unsafe_sha256" \
  --argjson repetitions "$repetitions" '{
    schema:1,recorded_at:$recorded_at,output_root:$output_root,
    main_build_env:$main_build_env,unsafe_build_env:$unsafe_build_env,
    main_build_sha256:$main_build_sha256,unsafe_build_sha256:$unsafe_build_sha256,
    repetitions:$repetitions,lane_count:55,
    order:["manual_branch","compatible","auto_upgrade","pinned","old-drain","unsafe"],
    stop_on_first_failure:true
  }' >"$output_root/full-metadata.json"

active_pid=""
finished=0
stop_child() {
  if [[ -n "$active_pid" ]]; then
    kill -TERM "$active_pid" >/dev/null 2>&1 || true
  fi
}
finalize() {
  local status=$?
  trap - EXIT
  stop_child
  if [[ "$status" == 0 && "$finished" != 1 ]]; then
    echo "full-parity run ended before its final 55-lane check" >&2
    status=1
  fi
  printf '%s\n' "$status" >"$output_root/exit-status.txt"
  date -u +'%Y-%m-%dT%H:%M:%SZ' >"$output_root/end-time.txt"
  (
    cd -- "$output_root"
    while IFS= read -r -d '' artifact; do
      sha256sum -- "$artifact"
    done < <(find . -type f ! -path './SHA256SUMS' -print0 | sort -z)
  ) >"$output_root/SHA256SUMS" 2>/dev/null || true
  if [[ "$status" != 0 ]]; then
    echo "full-parity run failed; partial evidence retained at $output_root" >&2
  fi
  exit "$status"
}
trap finalize EXIT
trap 'stop_child; exit 130' INT
trap 'stop_child; exit 143' TERM

resource_snapshot() {
  local destination=$1
  mkdir -p -- "$destination"
  docker ps -a --format '{{.Names}}' |
    awk '/^(safe-change-temporal-|safe-change-tu-)/' >"$destination/containers.txt"
  docker network ls --format '{{.Name}}' |
    awk '/^(safe-change-temporal-|safe-change-tu-)/' >"$destination/networks.txt"
  docker volume ls --format '{{.Name}}' |
    awk '/^(safe-change-temporal-|safe-change-tu-)/' >"$destination/volumes.txt"
  jq -n \
    --argjson containers "$(wc -l <"$destination/containers.txt")" \
    --argjson networks "$(wc -l <"$destination/networks.txt")" \
    --argjson volumes "$(wc -l <"$destination/volumes.txt")" \
    '{schema:1,containers:$containers,networks:$networks,volumes:$volumes,
      clean:($containers == 0 and $networks == 0 and $volumes == 0)}' \
    >"$destination/summary.json"
  jq -e '.clean == true' "$destination/summary.json" >/dev/null
}

run_logged() {
  local label=$1
  shift
  local checkpoint="$output_root/checkpoints/$label"
  local status=0 resource_status=0
  mkdir -p -- "$checkpoint"
  {
    printf '%q ' "$@"
    printf '\n'
  } >"$checkpoint/command.txt"
  date -u +'%Y-%m-%dT%H:%M:%SZ' >"$checkpoint/start-time.txt"
  echo "[$(date -u +'%H:%M:%S')] start $label" >&2
  set +e
  "$@" >"$checkpoint/stdout" 2>"$checkpoint/stderr" &
  active_pid=$!
  wait "$active_pid"
  status=$?
  active_pid=""
  set -e
  printf '%s\n' "$status" >"$checkpoint/exit-status.txt"
  date -u +'%Y-%m-%dT%H:%M:%SZ' >"$checkpoint/end-time.txt"
  resource_snapshot "$checkpoint/resources" || resource_status=$?
  if [[ "$status" != 0 || "$resource_status" != 0 ]]; then
    echo "checkpoint $label failed: command=$status resources=$resource_status" >&2
    return 1
  fi
  echo "[$(date -u +'%H:%M:%S')] pass  $label" >&2
}

resource_snapshot "$output_root/checkpoints/preflight-resources"

run_main_mode() {
  local mode=$1 number label pair_root
  for number in $(seq 1 "$repetitions"); do
    printf -v label '%s-rep-%02d' "$mode" "$number"
    pair_root="$output_root/main/$mode/rep-$(printf '%02d' "$number")"
    run_logged "$label" env \
      MODE="$mode" SKIP_BUILD=1 HARNESS_BUILD_ENV="$main_build_env" \
      TEMPORAL_PAIR_ROOT="$pair_root" "$script_dir/run-paired.sh"
    jq -e --arg mode "$mode" \
      '.valid == true and .mode == $mode and .cut_history_equal == true and
       .pending_activity_equal == true' "$pair_root/verdict.json" >/dev/null
  done
}

run_main_mode manual_branch

for number in $(seq 1 "$repetitions"); do
  printf -v label 'compatible-rep-%02d' "$number"
  case_root="$output_root/compatible/rep-$(printf '%02d' "$number")"
  run_logged "$label" env \
    SKIP_BUILD=1 HARNESS_BUILD_ENV="$main_build_env" \
    TEMPORAL_STATE_ROOT="$case_root" "$script_dir/run-compatible.sh"
  run_logged "$label-check" python3 "$script_dir/check-compatible.py" "$case_root"
  cp -- "$output_root/checkpoints/$label-check/stdout" "$case_root/independent-check.json"
  jq -e '.valid == true and .closure_version == "compatible-v2" and
    .final_status == "WORKFLOW_EXECUTION_STATUS_COMPLETED" and
    .payment_deliveries == 1 and .payment_commits == 1 and
    .completion_deliveries == 1 and .completion_commits == 1' \
    "$case_root/independent-check.json" >/dev/null
  if [[ "$number" == 1 ]]; then
    run_logged compatible-rep-01-mutations env \
      TEMPORAL_COMPATIBLE_EVIDENCE="$case_root" \
      python3 "$script_dir/test_check_compatible.py" -v
  fi
done

run_main_mode auto_upgrade
run_main_mode pinned

run_logged old-drain-full env \
  TEMPORAL_OLD_DRAIN_FULL_DIR="$output_root/old-drain" \
  TEMPORAL_OLD_DRAIN_REPETITIONS="$repetitions" \
  SKIP_BUILD=1 HARNESS_BUILD_ENV="$main_build_env" \
  "$script_dir/run-old-drain-full.sh"
jq -e --argjson repetitions "$repetitions" \
  '.valid == true and .repetitions == $repetitions and
   .attempts == (2 * $repetitions)' "$output_root/old-drain/summary.json" >/dev/null

run_logged unsafe-full \
  "$unsafe_dir/run-unsafe-full.sh" "$output_root/unsafe" "$unsafe_build_env"
jq -e --argjson repetitions "$repetitions" \
  '.valid == true and .repetitions == $repetitions and
   .attempts == (2 * $repetitions)' "$output_root/unsafe/summary.json" >/dev/null

mapfile -t main_verdicts < <(
  find "$output_root/main" -mindepth 3 -maxdepth 3 -name verdict.json -type f -print | sort
)
mapfile -t compatible_checks < <(
  find "$output_root/compatible" -mindepth 2 -maxdepth 2 -name independent-check.json -type f -print | sort
)
if [[ ${#main_verdicts[@]} -ne 15 || ${#compatible_checks[@]} -ne 5 ]]; then
  echo "full matrix omitted a main pair or compatible case" >&2
  exit 1
fi
jq -s -e 'length == 15 and all(.[]; .valid == true) and
  ([.[].mode] | group_by(.) | map({key:.[0],value:length}) | from_entries) ==
  {auto_upgrade:5,manual_branch:5,pinned:5}' "${main_verdicts[@]}" >/dev/null
jq -s -e 'length == 5 and all(.[]; .valid == true and
  .closure_version == "compatible-v2" and
  .final_status == "WORKFLOW_EXECUTION_STATUS_COMPLETED")' \
  "${compatible_checks[@]}" >/dev/null

jq -n \
  --argjson repetitions "$repetitions" \
  --argjson main_pairs "${#main_verdicts[@]}" \
  --argjson compatible_cases "${#compatible_checks[@]}" \
  --slurpfile old_drain "$output_root/old-drain/summary.json" \
  --slurpfile unsafe "$output_root/unsafe/summary.json" '{
    schema:1,valid:true,repetitions:$repetitions,
    main_pairs:$main_pairs,main_lanes:(2*$main_pairs),
    compatible_lanes:$compatible_cases,
    old_drain_lanes:$old_drain[0].attempts,
    unsafe_lanes:$unsafe[0].attempts,
    lane_count:(2*$main_pairs+$compatible_cases+$old_drain[0].attempts+$unsafe[0].attempts),
    all_real_runtime_cases:true
  } | select(.lane_count == 55)' >"$output_root/summary.json"
if [[ ! -s "$output_root/summary.json" ]]; then
  echo "final 55-lane summary invariant failed" >&2
  exit 1
fi

finished=1
jq . "$output_root/summary.json"
