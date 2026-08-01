import AuthorityContinuity.Trace

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

end AuthorityContinuity
