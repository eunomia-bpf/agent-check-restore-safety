import AuthorityContinuity.Trace
import AuthorityContinuity.TopologyExamples

/-!
# Frozen theorem audit

Elaboration of this module confirms the complete paper-facing theorem matrix;
the commands below expose every kernel dependency in the audit log.
-/

namespace AuthorityContinuity

#check checkAC_sound
#print axioms checkAC_sound

#check guardClosure_iff
#print axioms guardClosure_iff

#check simulation_preserves_ac
#print axioms simulation_preserves_ac

#check restriction_preserves_wf_ac
#print axioms restriction_preserves_wf_ac

#check prepare_preserves_wf_ac
#print axioms prepare_preserves_wf_ac

#check ticket_step_preserves_wf_ac
#print axioms ticket_step_preserves_wf_ac

#check LifecycleState.restrictLifecycle_epoch_exact
#print axioms LifecycleState.restrictLifecycle_epoch_exact

#check canonicalProjection_zero
#print axioms canonicalProjection_zero

#check canonicalProjection_mono
#print axioms canonicalProjection_mono

#check Transfer.checkTransfer_sound
#print axioms Transfer.checkTransfer_sound

#check Transfer.topology_fiber_conservation
#print axioms Transfer.topology_fiber_conservation

#check choiceFork_allowed_iff
#print axioms choiceFork_allowed_iff

#check parallelFork_allowed_iff
#print axioms parallelFork_allowed_iff

#check replaceRestore_allowed_iff
#print axioms replaceRestore_allowed_iff

#check liveRestore_allowed_iff
#print axioms liveRestore_allowed_iff

#check choiceFork_preserves_wf_ac
#print axioms choiceFork_preserves_wf_ac

#check parallelFork_preserves_wf_ac
#print axioms parallelFork_preserves_wf_ac

#check replaceRestore_preserves_wf_ac
#print axioms replaceRestore_preserves_wf_ac

#check liveRestore_preserves_wf_ac
#print axioms liveRestore_preserves_wf_ac

#check MergeCheck.checkMergeStructure_sound
#print axioms MergeCheck.checkMergeStructure_sound

#check simulation_merge_preserves_wf_ac
#print axioms simulation_merge_preserves_wf_ac

#check direct_merge_preserves_wf_ac
#print axioms direct_merge_preserves_wf_ac

#check step_preserves_wf_ac
#print axioms step_preserves_wf_ac

#check step_attempt_safe
#print axioms step_attempt_safe

#check step_preserves_existing_binding
#print axioms step_preserves_existing_binding

#check trace_preserves_existing_binding
#print axioms trace_preserves_existing_binding

#check trace_preserves_wf_ac
#print axioms trace_preserves_wf_ac

#check trace_terminal_mono
#print axioms trace_terminal_mono

#check trace_epoch_mono
#print axioms trace_epoch_mono

#check SimulatedTrace.attempt_binding_final
#print axioms SimulatedTrace.attempt_binding_final

#check effect_coverage
#print axioms effect_coverage

#check concrete_trace_authority_safety
#print axioms concrete_trace_authority_safety

#check TopologyExamples.fresh_fragment_parallel_preflight
#print axioms TopologyExamples.fresh_fragment_parallel_preflight

end AuthorityContinuity
