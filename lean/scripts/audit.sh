#!/usr/bin/env bash
set -euo pipefail

script_dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
lean_root="$(dirname -- "$script_dir")"
cd "$lean_root"

frozen_constants=(
  checkAC_sound
  guardClosure_iff
  simulation_preserves_ac
  restriction_preserves_wf_ac
  prepare_preserves_wf_ac
  ticket_step_preserves_wf_ac
  restrictLifecycle_epoch_exact
  canonicalProjection_zero
  canonicalProjection_mono
  checkTransfer_sound
  topology_fiber_conservation
  choiceFork_allowed_iff
  parallelFork_allowed_iff
  replaceRestore_allowed_iff
  liveRestore_allowed_iff
  choiceFork_preserves_wf_ac
  parallelFork_preserves_wf_ac
  replaceRestore_preserves_wf_ac
  liveRestore_preserves_wf_ac
  checkMergeStructure_sound
  simulation_merge_preserves_wf_ac
  direct_merge_preserves_wf_ac
  step_preserves_wf_ac
  trace_preserves_wf_ac
  effect_coverage
  concrete_trace_authority_safety
  fresh_fragment_parallel_preflight
  checkLinear_sound
  LinearValid.token_trichotomy
  checkTransferTokenNonAmplifying_sound
  checkTransferTokenNonAmplifying_complete
  afterTransfer_nonAmplifying_iff_target_current_linear
  canonical_nonAmplifying_iff_target_current_linear
  simulationMerge_nonAmplifying_iff_target_current_linear
  directMerge_nonAmplifying_iff_target_current_linear
  bound_durable_origin_afterTransfer
  afterTransfer_preserves_linearity_source
  checkCanonicalTokenDefended_eq_tokenPlan
  checkSimulationMergeTokenDefended_eq_tokenPlan
  checkDirectMergeTokenDefended_eq_tokenPlan
  checkedCanonicalDefended_token_step
  checkedSimulationMergeDefended_token_step
  checkedDirectMergeDefended_token_step
  prepare_preserves_linearity_source
  restriction_preserves_linearity_source
  revoke_preserves_linearity_source
  tokenPositiveStep_preserves_linearity_source_decomposed
  token_positive_trace_preserves_source_decomposed
  tokenPositiveStep_preserves_existing_operation_token
  prepare_binding_new_or_preserved
  token_positive_trace_preserves_existing_operation_token
  within_plan_epoch_initial_tokens_fixed
  token_positive_trace_projects_actual
  token_positive_trace_version_mono
  zero_demand_parallelFork_rejected
  duplicated_token_fiber_cardinality
  weighted_partition_exact
  cardinality_partition
  zero_weight_token_visible
  tokenSafe_unifiedProjection
  unifiedProjection_initial_same_epoch
  trace_preserves_unifiedProjection
  trace_initial_token_same_epoch
  current_witness_matches_spec
  binding_witness_matches_spec
  collision_capacity_one_witness
  forbidden_image_indicator_witness
  universalAdditiveTransport_iff_configMorphism
  two_handles_one_cell
  exclusive_shared_lineage_transports
  parallel_capacity_one_counterexample
  fresh_preserves_safe
  step_preserves_phaseWF
  step_phase_mono
  rtc_preserves_safe
  rtc_preserves_phaseWF
  rtc_phase_mono
  rtc_ledger_mono
  committed_card_le_issued_card
  step_committed_card
  committed_card_growth
  conflicting_digest_has_no_retry
  three_retries_trace
  cloned_private_cells_two_commitments
  rollback_local_restore_yields_two_receipts
  retry_successes_share_one_commitment
  same_operation_two_cells_create_two_commitments
  spent_mono
  final_card_eq_initial_add_commitment_length
  initial_card_add_commitment_length_le_reachable_card
  admissible_card_le_unusedActiveCells_card
  committed_add_accepted_card_le_reachableCells_card
  exists_tight_admissible_of_soloAvailable_productIndependent
  all_admissible_card_le_iff_unusedActiveCells_card_le_of_independent
  unusedActiveCells_card_eq_activeOccurrences_card_of_independent
  independentOccurrences_single_redemption_iff_current_card_le_one
  shared_cell_aliases_safe_but_not_occurrence_linear
  restored_attempt_blocked_by_pruned_consumed_history
  two_cells_but_choice_accepts_at_most_one
  choice_is_not_productIndependent
  rollback_clone_double_accept_counterexample
)

# Named executable controls are elaborated through `AuthorityContinuity.Main`.
# Most use `native_decide`, so they are frozen for presence separately from the
# proof-theorem axiom whitelist above.
frozen_controls=(
  choice_fork_admission_accepts
  parallel_fork_admission_accepts
  replace_restore_admission_accepts
  live_restore_admission_accepts
  choice_rejects_child_copresence
  parallel_accepts_child_copresence
  copied_full_demand_rejected
  retained_fragment_mix_rejected
  terminal_fragment_reuse_rejected
  nontentative_rho_rejected
  closed_epoch_reopen_rejected
  simulation_merge_identity_accepts
  direct_merge_identity_accepts
  merge_modes_separated
  exclusive_source_ac
  unsafe_codurable_direct_merge_rejected
  canonical_history_definitionally_preserved
  replace_restore_closes_parent
)

placeholder_pattern='(^|[^[:alnum:]_])(sorryAx|sorry|admit)([^[:alnum:]_]|$)'
if rg --line-number --glob '*.lean' "$placeholder_pattern" AuthorityContinuity; then
  echo "audit: proof placeholder found in project source" >&2
  exit 1
fi

declaration_pattern='^[[:space:]]*((private|protected|noncomputable|scoped)[[:space:]]+)*(axiom|constant)[[:space:]]'
if rg --line-number --glob '*.lean' "$declaration_pattern" AuthorityContinuity; then
  echo "audit: project axiom/constant declaration found" >&2
  exit 1
fi

if rg --line-number --glob '*.lean' 'TopologyShape' AuthorityContinuity; then
  echo "audit: former fieldwise topology certificate remains in authoritative source" >&2
  exit 1
fi

for name in "${frozen_constants[@]}"; do
  if ! rg --quiet --glob '*.lean' \
      "^[[:space:]]*(theorem|lemma)[[:space:]]+${name}([^[:alnum:]_]|$)" \
      AuthorityContinuity; then
    echo "audit: frozen theorem is missing: $name" >&2
    exit 1
  fi
done

for name in "${frozen_controls[@]}"; do
  if ! rg --quiet --glob '*.lean' \
      "^[[:space:]]*(theorem|lemma)[[:space:]]+${name}([^[:alnum:]_]|$)" \
      AuthorityContinuity; then
    echo "audit: frozen executable control is missing: $name" >&2
    exit 1
  fi
done

lake build AuthorityContinuity

mkdir -p results
audit_log="results/topology-axioms.log"
lake env lean AuthorityContinuity/Audit.lean 2>&1 | tee "$audit_log" results/axioms.log

for name in "${frozen_constants[@]}"; do
  if ! rg --quiet "${name}' (does not depend on any axioms|depends on axioms:)" \
      "$audit_log"; then
    echo "audit: Audit.lean did not print dependencies for: $name" >&2
    exit 1
  fi
done

if rg --quiet 'sorryAx' "$audit_log"; then
  echo "audit: kernel dependency on a proof placeholder" >&2
  exit 1
fi

mapfile -t reported_axioms < <(
  sed -nE 's/.*depends on axioms: \[([^]]*)\].*/\1/p' "$audit_log" |
    tr ',' '\n' |
    sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//' |
    sed '/^$/d' |
    sort -u
)
for dependency in "${reported_axioms[@]}"; do
  case "$dependency" in
    propext|Quot.sound|Classical.choice) ;;
    *)
      echo "audit: non-whitelisted kernel dependency: $dependency" >&2
      exit 1
      ;;
  esac
done

lake env leanchecker --fresh AuthorityContinuity.Main
echo "audit: all frozen theorems and controls present; source and kernel replay checks passed"
