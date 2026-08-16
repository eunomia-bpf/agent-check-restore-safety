#!/usr/bin/env bash
set -Eeuo pipefail

export LC_ALL=C

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
runtime_root="$(cd -- "$script_dir/../.." && pwd -P)"
expected_build_sha256="646c611a607556df783569332f0fbf941c31ddb790c1a32261d9bb81851e55e6"
repetitions=5

if [[ $# -ne 2 ]]; then
  echo "usage: $0 OUTPUT_ROOT FINAL_BUILD_ENV" >&2
  exit 64
fi
output_root=$1
input_build_env=$2

for variable in \
  COMPOSE_FILE COMPOSE_PROFILES COMPOSE_PROJECT_NAME COMPOSE_PATH_SEPARATOR \
  COMPOSE_ENV_FILES COMPOSE_DISABLE_ENV_FILE; do
  if [[ -n "${!variable:-}" ]]; then
    echo "$variable must be empty" >&2
    exit 64
  fi
  unset "$variable"
done

for command in awk chmod cmp cp date find jq mkdir python3 realpath seq sha256sum sort; do
  command -v "$command" >/dev/null || {
    echo "required command not found: $command" >&2
    exit 1
  }
done
if [[ ! -f "$input_build_env" || -L "$input_build_env" ]]; then
  echo "FINAL_BUILD_ENV must be an existing regular file" >&2
  exit 64
fi
input_build_env="$(realpath -- "$input_build_env")"
if [[ "$(sha256sum -- "$input_build_env" | awk '{print $1}')" != "$expected_build_sha256" ]]; then
  echo "FINAL_BUILD_ENV is not the frozen final Temporal unsafe build environment" >&2
  exit 64
fi
input_name="$(basename -- "$input_build_env")"
if [[ "$input_name" == *.* ]]; then
  input_evidence_name="${input_name%.*}-evidence"
else
  input_evidence_name="${input_name}-evidence"
fi
input_build_evidence="$(dirname -- "$input_build_env")/$input_evidence_name"
if [[ ! -d "$input_build_evidence" || -L "$input_build_evidence" ||
      ! -f "$input_build_evidence/SHA256SUMS" ]]; then
  echo "final build evidence is absent or unsafe" >&2
  exit 64
fi
unexpected="$(find "$input_build_evidence" -mindepth 1 ! -type d ! -type f -print -quit)"
if [[ -n "$unexpected" ]]; then
  echo "final build evidence contains a symlink or special file: $unexpected" >&2
  exit 64
fi
(
  cd -- "$input_build_evidence"
  sha256sum --check --strict SHA256SUMS >/dev/null
)
cmp -- "$input_build_env" "$input_build_evidence/build.env"

if [[ -e "$output_root" ]]; then
  if [[ ! -d "$output_root" || -n "$(find "$output_root" -mindepth 1 -print -quit)" ]]; then
    echo "OUTPUT_ROOT must be absent or an empty directory" >&2
    exit 64
  fi
else
  mkdir -p -- "$output_root"
fi
output_root="$(realpath -- "$output_root")"
chmod 700 "$output_root"
build_env="$output_root/build.env"
cp -- "$input_build_env" "$build_env"
cp -a -- "$input_build_evidence" "$output_root/build-evidence"
(
  cd -- "$output_root/build-evidence"
  sha256sum --check --strict SHA256SUMS >/dev/null
)
cmp -- "$build_env" "$output_root/build-evidence/build.env"
chmod 400 "$build_env"

set -a
# shellcheck source=/dev/null
source "$build_env"
set +a
for variable in \
  TEMPORAL_UNSAFE_WORKER_ID PROPOSED_UNSAFE_WORKER_ID NATIVE_UNSAFE_WORKER_ID \
  PROPOSED_NATIVE_IMAGE_ID_EQUAL TEMPORAL_UNSAFE_PAYMENT_TOKEN_CONTRACT \
  TEMPORAL_UNSAFE_COMPOSE_PROFILES_CONTRACT; do
  if [[ -z "${!variable:-}" ]]; then
    echo "final build environment omitted $variable" >&2
    exit 64
  fi
done
if [[ "$TEMPORAL_UNSAFE_WORKER_ID" != "$PROPOSED_UNSAFE_WORKER_ID" ||
      "$TEMPORAL_UNSAFE_WORKER_ID" != "$NATIVE_UNSAFE_WORKER_ID" ||
      "$PROPOSED_NATIVE_IMAGE_ID_EQUAL" != true ||
      "$TEMPORAL_UNSAFE_PAYMENT_TOKEN_CONTRACT" != payment_token_equals_order_id ||
      "$TEMPORAL_UNSAFE_COMPOSE_PROFILES_CONTRACT" != empty ]]; then
  echo "final build does not bind both lanes to one target and empty profiles" >&2
  exit 64
fi

(cd -- "$script_dir" && sha256sum run-unsafe-full.sh) >"$output_root/wrapper.sha256"
(cd -- "$script_dir" && sha256sum run-unsafe-case.sh) >"$output_root/case-runner.sha256"
(cd -- "$script_dir" && sha256sum check-unsafe.py) >"$output_root/case-checker.sha256"
(cd -- "$script_dir" && sha256sum check-unsafe-pair.py) >"$output_root/pair-checker.sha256"
(cd -- "$script_dir" && sha256sum check-unsafe-mutations.py) >"$output_root/mutation-checker.sha256"
(cd -- "$script_dir" && sha256sum check-unsafe-full.py) >"$output_root/full-checker.sha256"

finished=0
finalize() {
  local status=$?
  trap - EXIT
  if [[ "$status" == 0 && "$finished" != 1 ]]; then
    echo "Temporal unsafe full run ended before its final independent check" >&2
    status=1
  fi
  printf '%s\n' "$status" >"$output_root/exit-status.txt"
  (
    cd -- "$output_root"
    while IFS= read -r -d '' artifact; do
      sha256sum -- "$artifact"
    done < <(find . -type f ! -path './SHA256SUMS' -print0 | sort -z)
  ) >"$output_root/SHA256SUMS" 2>/dev/null || true
  if [[ "$status" != 0 ]]; then
    echo "Temporal unsafe full run failed; partial evidence retained at $output_root" >&2
  fi
  exit "$status"
}
trap finalize EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

build_sha256="$(sha256sum -- "$build_env" | awk '{print $1}')"
jq -n \
  --arg recorded_at "$(date --utc --iso-8601=seconds)" \
  --arg output_root "$output_root" --arg input_build_env "$input_build_env" \
  --arg build_env "$build_env" --arg build_sha256 "$build_sha256" \
  --arg target_image "$TEMPORAL_UNSAFE_WORKER_ID" \
  --argjson repetitions "$repetitions" '
  {schema:1,recorded_at:$recorded_at,cell:"temporal-history-dependent-unsafe-edit",
    system:"temporal-food-ordering",output_root:$output_root,
    repetitions:$repetitions,methods:["proposed","native"],attempts:(2*$repetitions),
    input_build_env:$input_build_env,shared_build_env:$build_env,
    shared_build_sha256:$build_sha256,skip_build:true,one_target_image:$target_image,
    identity_contract:"payment_token_equals_order_id",compose_profiles:[],
    checks:["independent-case","mutations","matched-pair","independent-full"]}
' >"$output_root/full-metadata.json"

for number in $(seq 1 "$repetitions"); do
  printf -v repetition 'rep-%02d' "$number"
  repetition_dir="$output_root/$repetition"
  mkdir -p -- "$repetition_dir"
  chmod 700 "$repetition_dir"

  clean_order_id="temporal-unsafe-clean-full-$repetition"
  main_order_id="temporal-unsafe-main-full-$repetition"
  clean_workflow_id="temporal-unsafe-clean-workflow-full-$repetition"
  main_workflow_id="temporal-unsafe-main-workflow-full-$repetition"

  for method in proposed native; do
    attempt="$repetition_dir/$method"
    project_base="safe-change-tu-${number}-${method}-$$"
    echo "Temporal unsafe full $repetition $method" >&2
    set +e
    TEMPORAL_UNSAFE_METHOD="$method" \
    TEMPORAL_UNSAFE_STATE_ROOT="$attempt" \
    TEMPORAL_UNSAFE_PROJECT_BASE="$project_base" \
    TEMPORAL_UNSAFE_CLEAN_ORDER_ID="$clean_order_id" \
    TEMPORAL_UNSAFE_ORDER_ID="$main_order_id" \
    TEMPORAL_UNSAFE_CLEAN_WORKFLOW_ID="$clean_workflow_id" \
    TEMPORAL_UNSAFE_WORKFLOW_ID="$main_workflow_id" \
    SKIP_BUILD=1 HARNESS_BUILD_ENV="$build_env" \
      "$script_dir/run-unsafe-case.sh" \
      >"$repetition_dir/$method-runner.stdout" \
      2>"$repetition_dir/$method-runner.stderr"
    runner_status=$?
    set -e
    printf '%s\n' "$runner_status" >"$repetition_dir/$method-runner.exit-status.txt"
    if [[ "$runner_status" != 0 ]]; then
      echo "$repetition $method runner failed with status $runner_status" >&2
      exit 1
    fi

    python3 "$script_dir/check-unsafe.py" \
      --evidence "$attempt" --runtime-root "$runtime_root" \
      >"$repetition_dir/$method-check.json"
    python3 "$script_dir/check-unsafe-mutations.py" \
      --evidence "$attempt" --runtime-root "$runtime_root" \
      >"$repetition_dir/$method-mutations.json"
    jq -e --arg method "$method" '
      .schema == 1 and .valid == true and
      .cell == "temporal-history-dependent-unsafe-edit" and .method == $method and
      .clean_target_completed == true and
      (if $method == "proposed" then
        .main_decision == "impossible" and .target_started == false and .source_completed == true
       else
        .main_decision == "native-completed" and .target_started == true and
        .external_requirement_violated == true
       end)
    ' "$repetition_dir/$method-check.json" >/dev/null
    jq -e --arg method "$method" '
      .schema == 1 and .valid == true and .method == $method and
      .mutation_count > 1 and .rejected_count == (.mutation_count - 1) and
      .positive_control_count == 1
    ' "$repetition_dir/$method-mutations.json" >/dev/null
  done

  cmp -- "$build_env" "$repetition_dir/proposed/results/build.env"
  cmp -- "$build_env" "$repetition_dir/native/results/build.env"
  jq -e -s --arg clean_order "$clean_order_id" --arg main_order "$main_order_id" \
    --arg clean_workflow "$clean_workflow_id" --arg main_workflow "$main_workflow_id" '
    .[0] as $first |
    length == 2 and $first.method == "proposed" and .[1].method == "native" and
    all(.[];
      .clean_order_id == $clean_order and .main_order_id == $main_order and
      .clean_workflow_id == $clean_workflow and .main_workflow_id == $main_workflow and
      .source_image == $first.source_image and .target_image == $first.target_image and
      .build_sha256 == $first.build_sha256 and .skip_build == true) and
    .[0].clean_project != .[1].clean_project and .[0].main_project != .[1].main_project
  ' "$repetition_dir/proposed/results/run-metadata.json" \
    "$repetition_dir/native/results/run-metadata.json" >/dev/null

  python3 "$script_dir/check-unsafe-pair.py" \
    --proposed "$repetition_dir/proposed" --native "$repetition_dir/native" \
    --runtime-root "$runtime_root" >"$repetition_dir/pair-check.json"
  jq -e '
    .schema == 1 and .valid == true and
    .cell == "temporal-history-dependent-unsafe-edit" and
    .matched_workload == true and .same_source_image == true and
    .same_target_image == true and .same_substantive_cut == true and
    .clean_target_completed_both == true and
    .proposed_decision == "impossible" and .proposed_target_started == false and
    .native_runtime_status == "completed" and
    .native_approval_used == 2 and .native_approval_capacity == 1
  ' "$repetition_dir/pair-check.json" >/dev/null

  jq -n --arg repetition "$repetition" \
    --slurpfile proposed "$repetition_dir/proposed-check.json" \
    --slurpfile native "$repetition_dir/native-check.json" \
    --slurpfile proposed_mutations "$repetition_dir/proposed-mutations.json" \
    --slurpfile native_mutations "$repetition_dir/native-mutations.json" \
    --slurpfile pair "$repetition_dir/pair-check.json" '
    {schema:1,valid:true,repetition:$repetition,attempts:2,
      proposed_evidence_digest:$proposed[0].evidence_digest,
      native_evidence_digest:$native[0].evidence_digest,
      pair_digest:$pair[0].pair_digest,
      mutation_count:($proposed_mutations[0].mutation_count + $native_mutations[0].mutation_count),
      rejected_count:($proposed_mutations[0].rejected_count + $native_mutations[0].rejected_count),
      positive_control_count:($proposed_mutations[0].positive_control_count + $native_mutations[0].positive_control_count),
      main_payment_operation_id:$pair[0].main_payment_operation_id,
      main_completion_operation_id:$pair[0].main_completion_operation_id}
  ' >"$repetition_dir/summary.json"
done

python3 "$script_dir/check-unsafe-full.py" \
  --evidence "$output_root" --runtime-root "$runtime_root" --repetitions "$repetitions" \
  >"$output_root/full-check.json"
jq -e --arg image "$TEMPORAL_UNSAFE_WORKER_ID" --argjson repetitions "$repetitions" '
  .schema == 1 and .valid == true and
  .cell == "temporal-history-dependent-unsafe-edit" and
  .repetitions == $repetitions and .case_count == (2*$repetitions) and
  .pair_count == $repetitions and .unique_case_evidence_digests == (2*$repetitions) and
  .unique_pair_digests == $repetitions and .unique_run_ids == (4*$repetitions) and
  .one_target_image == $image
' "$output_root/full-check.json" >/dev/null

mapfile -t repetition_summaries < <(
  find "$output_root" -mindepth 2 -maxdepth 2 -name summary.json -type f -print | sort
)
if [[ ${#repetition_summaries[@]} -ne "$repetitions" ]]; then
  echo "full matrix omitted a repetition summary" >&2
  exit 1
fi
jq -s --arg target_image "$TEMPORAL_UNSAFE_WORKER_ID" --argjson repetitions "$repetitions" '
  {
    schema:1,valid:(length == $repetitions and all(.[]; .valid == true)),
    cell:"temporal-history-dependent-unsafe-edit",system:"temporal-food-ordering",
    repetitions:$repetitions,attempts:([.[].attempts] | add),
    clean_target_completed_both:true,proposed_refused_before_target:true,
    native_completed_without_requirement_enforcement:true,
    mutation_count:([.[].mutation_count] | add),
    rejected_count:([.[].rejected_count] | add),
    positive_control_count:([.[].positive_control_count] | add),
    unique_case_evidence_digests:([.[].proposed_evidence_digest,.[].native_evidence_digest] | unique | length),
    unique_pair_digests:([.[].pair_digest] | unique | length),
    unique_payment_operation_ids:([.[].main_payment_operation_id] | unique | length),
    unique_completion_operation_ids:([.[].main_completion_operation_id] | unique | length),
    one_target_image:$target_image,pairs:.
  }
  | select(.valid and .attempts == (2*$repetitions) and
      .rejected_count == (.mutation_count - .positive_control_count) and
      .positive_control_count == (2*$repetitions) and
      .unique_case_evidence_digests == (2*$repetitions) and
      .unique_pair_digests == $repetitions and
      .unique_payment_operation_ids == $repetitions and
      .unique_completion_operation_ids == $repetitions)
' "${repetition_summaries[@]}" >"$output_root/summary.json"
if [[ ! -s "$output_root/summary.json" ]]; then
  echo "full matrix summary invariant failed" >&2
  exit 1
fi

finished=1
jq . "$output_root/summary.json"
