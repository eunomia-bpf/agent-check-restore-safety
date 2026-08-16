#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
runtime_root="$(realpath "$script_dir/../..")"
if [[ $# -ne 2 ]]; then
  echo "usage: $0 OUTPUT_ROOT BUILD_ENV" >&2
  exit 64
fi
output_root=$1
input_build_env=$2

for command in chmod cp date find jq mkdir python3 realpath sed seq sha256sum; do
  command -v "$command" >/dev/null || { echo "required command not found: $command" >&2; exit 1; }
done
if [[ ! -f "$input_build_env" ]]; then
  echo "BUILD_ENV must be an existing regular file" >&2
  exit 64
fi
input_build_env="$(realpath "$input_build_env")"
if [[ -e "$output_root" ]]; then
  if [[ ! -d "$output_root" || -n "$(find "$output_root" -mindepth 1 -print -quit)" ]]; then
    echo "OUTPUT_ROOT must be absent or an empty directory" >&2
    exit 64
  fi
else
  mkdir -p "$output_root"
fi
output_root="$(realpath "$output_root")"
chmod 700 "$output_root"

build_env="$output_root/build.env"
cp "$input_build_env" "$build_env"
chmod 400 "$build_env"
set -a
# shellcheck source=/dev/null
source "$build_env"
set +a
for required in ORDER_V1_IMAGE ORDER_UNSAFE_V2_IMAGE NATIVE_ORDER_V1_IMAGE \
  NATIVE_ORDER_UNSAFE_V2_IMAGE UNSAFE_V2_WORKFLOW_SHA256 \
  UNSAFE_V2_COMPILED_SHA256 NATIVE_UNSAFE_V2_COMPILED_SHA256; do
  [[ -n "${!required:-}" ]] || { echo "BUILD_ENV omitted $required" >&2; exit 64; }
done
if [[ "$UNSAFE_V2_COMPILED_SHA256" != "$NATIVE_UNSAFE_V2_COMPILED_SHA256" ]]; then
  echo "BUILD_ENV does not bind both lanes to identical target workflow bytes" >&2
  exit 64
fi

sha256sum "$script_dir/run-unsafe-full.sh" >"$output_root/wrapper.sha256"
sha256sum "$script_dir/run-unsafe-case.sh" >"$output_root/case-runner.sha256"
sha256sum "$script_dir/check-unsafe.py" >"$output_root/checker.sha256"
sha256sum "$script_dir/check-unsafe-mutations.py" >"$output_root/mutation-checker.sha256"
sha256sum "$script_dir/check-unsafe-pair.py" >"$output_root/pair-checker.sha256"
build_sha256="$(sha256sum "$build_env" | sed 's/ .*//')"
jq -n \
  --arg recorded_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg output_root "$output_root" --arg input_build_env "$input_build_env" \
  --arg build_env "$build_env" --arg build_sha256 "$build_sha256" \
  --arg target_workflow_sha256 "$UNSAFE_V2_COMPILED_SHA256" '{
    schema:1,recorded_at:$recorded_at,cell:"history-dependent-unsafe-edit",
    system:"restate-food-ordering",output_root:$output_root,
    repetitions:5,methods:["proposed","native"],attempts:10,
    input_build_env:$input_build_env,shared_build_env:$build_env,
    shared_build_sha256:$build_sha256,skip_build:true,
    target_workflow_sha256:$target_workflow_sha256,
    checks:["independent-evidence","mutations","matched-pair"]
  }' >"$output_root/full-metadata.json"

for number in $(seq 1 5); do
  printf -v repetition 'rep-%02d' "$number"
  repetition_dir="$output_root/$repetition"
  mkdir -p "$repetition_dir"
  chmod 700 "$repetition_dir"
  clean_order_id="unsafe-clean-full-$repetition"
  main_order_id="unsafe-full-$repetition"

  for method in proposed native; do
    attempt="$repetition_dir/$method"
    echo "unsafe full $repetition $method"
    set +e
    UNSAFE_METHOD="$method" \
    UNSAFE_STATE_DIR="$attempt" \
    UNSAFE_CLEAN_ORDER_ID="$clean_order_id" \
    ORDER_ID="$main_order_id" \
    SKIP_BUILD=1 \
    HARNESS_BUILD_ENV="$build_env" \
      "$script_dir/run-unsafe-case.sh" \
      >"$repetition_dir/$method-runner.stdout" \
      2>"$repetition_dir/$method-runner.stderr"
    runner_status=$?
    set -e
    printf '%s\n' "$runner_status" >"$repetition_dir/$method-runner.exit-status.txt"
    if [[ $runner_status -ne 0 ]]; then
      echo "unsafe full $repetition $method runner failed with status $runner_status; evidence retained at $attempt" >&2
      exit 1
    fi

    if ! python3 "$script_dir/check-unsafe.py" \
      --evidence "$attempt" --runtime-root "$runtime_root" \
      >"$repetition_dir/$method-check.json"; then
      echo "unsafe full $repetition $method evidence check failed; attempt retained" >&2
      exit 1
    fi
    if ! python3 "$script_dir/check-unsafe-mutations.py" \
      --evidence "$attempt" --runtime-root "$runtime_root" \
      >"$repetition_dir/$method-mutations.json"; then
      echo "unsafe full $repetition $method mutation suite failed; attempt retained" >&2
      exit 1
    fi
  done

  jq -e -s --arg clean "$clean_order_id" --arg main "$main_order_id" '
    length == 2 and
    .[0].method == "proposed" and .[1].method == "native" and
    all(.[]; .clean_order_id == $clean and .main_order_id == $main and .skip_build == true) and
    .[0].target_binding.requirement_sha256 == .[1].target_binding.requirement_sha256
  ' "$repetition_dir/proposed/results/run-metadata.json" \
    "$repetition_dir/native/results/run-metadata.json" >/dev/null || {
      echo "unsafe full $repetition did not use matched frozen inputs" >&2
      exit 1
    }

  if ! python3 "$script_dir/check-unsafe-pair.py" \
    --proposed "$repetition_dir/proposed" --native "$repetition_dir/native" \
    --runtime-root "$runtime_root" >"$repetition_dir/pair-check.json"; then
    echo "unsafe full $repetition pair check failed; both attempts retained" >&2
    exit 1
  fi

  jq -n --arg repetition "$repetition" --arg clean "$clean_order_id" --arg main "$main_order_id" \
    --slurpfile proposed "$repetition_dir/proposed-check.json" \
    --slurpfile native "$repetition_dir/native-check.json" \
    --slurpfile proposed_mutations "$repetition_dir/proposed-mutations.json" \
    --slurpfile native_mutations "$repetition_dir/native-mutations.json" \
    --slurpfile pair "$repetition_dir/pair-check.json" '
      $proposed[0] as $p | $native[0] as $n |
      $proposed_mutations[0] as $pm | $native_mutations[0] as $nm |
      $pair[0] as $pair_check |
      if (
        $p.valid == true and $p.method == "proposed" and
        $p.clean_target_completed == true and $p.main_decision == "impossible" and
        $p.target_started == false and $p.external_requirement_violated == false and
        $n.valid == true and $n.method == "native" and
        $n.clean_target_completed == true and
        $n.main_decision == "runtime-completed-without-external-requirement-enforcement" and
        $n.target_started == true and $n.external_requirement_violated == true and
        $n.approval_used == 2 and $n.approval_capacity == 1 and
        $pm.valid == true and $nm.valid == true and
        $pm.mutation_count == 18 and $nm.mutation_count == 18 and
        $pm.rejected_count == 17 and $nm.rejected_count == 17 and
        $pm.semantic_flips == {
          "capacity-to-two":true,"delete-old-payment":true,
          "finish-v2-cost-to-zero":true,"old-cost-to-zero":true
        } and $nm.semantic_flips == $pm.semantic_flips and
        $pair_check.valid == true and $pair_check.same_target_requirement == true and
        $pair_check.same_target_workflow_bytes == true and
        $pair_check.matched_workload == true and
        $pair_check.clean_order_id == $clean and $pair_check.main_order_id == $main and
        ($pair_check.main_payment_operation_id | type) == "string" and
        ($pair_check.main_completion_operation_id | type) == "string" and
        $pair_check.proposed_decision == "impossible" and
        $pair_check.native_runtime_status == "completed" and
        $pair_check.native_approval_used == 2 and $pair_check.native_approval_capacity == 1
      ) then {
        schema:1,valid:true,repetition:$repetition,
        clean_order_id:$clean,main_order_id:$main,attempts:2,
        clean_target_completed_both:true,
        proposed:{decision:$p.main_decision,target_started:$p.target_started,
          evidence_digest:$p.evidence_digest},
        native:{runtime_status:$pair_check.native_runtime_status,
          target_started:$n.target_started,external_requirement_violated:$n.external_requirement_violated,
          approval_used:$n.approval_used,approval_capacity:$n.approval_capacity,
          evidence_digest:$n.evidence_digest},
        mutation_tests:($pm.mutation_count + $nm.mutation_count),
        rejected_mutations:($pm.rejected_count + $nm.rejected_count),
        ignored_summary_mutations:2,pair_digest:$pair_check.pair_digest,
        main_payment_operation_id:$pair_check.main_payment_operation_id,
        main_completion_operation_id:$pair_check.main_completion_operation_id
      } else error("unsafe repetition invariants failed") end
    ' >"$repetition_dir/summary.json"
done

mapfile -t repetition_summaries < <(
  find "$output_root" -mindepth 2 -maxdepth 2 -name summary.json -type f | sort
)
if [[ ${#repetition_summaries[@]} -ne 5 ]]; then
  echo "unsafe full matrix omitted a repetition summary" >&2
  exit 1
fi
jq -s '
  [.[].proposed.evidence_digest, .[].native.evidence_digest] as $digests |
  {
    schema:1,valid:(length == 5 and all(.[]; .valid == true)),
    cell:"history-dependent-unsafe-edit",system:"restate-food-ordering",
    repetitions:length,attempts:([.[].attempts] | add),
    clean_target_completed:(all(.[]; .clean_target_completed_both == true)),
    proposed_refused_before_target:(all(.[];
      .proposed.decision == "impossible" and .proposed.target_started == false)),
    native_completed_without_external_requirement_enforcement:(all(.[];
      .native.runtime_status == "completed" and .native.target_started == true and
      .native.external_requirement_violated == true and
      .native.approval_used == 2 and .native.approval_capacity == 1)),
    mutation_tests:([.[].mutation_tests] | add),
    rejected_mutations:([.[].rejected_mutations] | add),
    ignored_summary_mutations:([.[].ignored_summary_mutations] | add),
    unique_evidence_digests:($digests | unique | length),
    unique_pair_digests:([.[].pair_digest] | unique | length),
    unique_main_payment_operation_ids:([.[].main_payment_operation_id] | unique | length),
    unique_main_completion_operation_ids:([.[].main_completion_operation_id] | unique | length),
    pairs:.
  }
  | select(
      .valid and .repetitions == 5 and .attempts == 10 and
      .clean_target_completed and .proposed_refused_before_target and
      .native_completed_without_external_requirement_enforcement and
      .mutation_tests == 180 and .rejected_mutations == 170 and
      .ignored_summary_mutations == 10 and
      .unique_evidence_digests == 10 and .unique_pair_digests == 5 and
      .unique_main_payment_operation_ids == 5 and
      .unique_main_completion_operation_ids == 5
    )
' "${repetition_summaries[@]}" >"$output_root/summary.json"
if [[ ! -s "$output_root/summary.json" ]]; then
  echo "unsafe full matrix summary invariant failed" >&2
  exit 1
fi
cat "$output_root/summary.json"
