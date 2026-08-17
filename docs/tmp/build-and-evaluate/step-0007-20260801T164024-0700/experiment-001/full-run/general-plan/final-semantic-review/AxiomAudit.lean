import AuthorityContinuity.PlanInvariantTransport
import AuthorityContinuity.PlanInvariantDrop
import AuthorityContinuity.PlanInvariantMerge
import AuthorityContinuity.PlanInvariantMergeExamples
import AuthorityContinuity.PlanInvariantGrammar
import AuthorityContinuity.PlanInvariantExamples

open AuthorityContinuity

#check PlanInvariant.PlanData.current_group_promotedLoad_le_capacity
#check PlanInvariant.PlanData.current_group_actual_step
#check PlanInvariant.PlanData.afterPrepareGroup_preserves_valid
#check PlanInvariant.PlanData.PreparePlanned.actual_step
#check PlanInvariant.PlanData.planned_prepare_trace_preserves
#check PlanInvariant.PlanData.planned_prepare_trace_projects
#check PlanInvariant.PlanData.planned_prepare_trace_version_mono
#check PlanInvariant.PlanData.two_prepare_gate

#check PlanInvariant.PlanData.checkCanonicalPlan_sound
#check PlanInvariant.PlanData.checkedCanonical_preserves_all
#check PlanInvariant.PlanData.RestrictionPlanned.preserves_all
#check PlanInvariant.PlanData.RevokePlanned.preserves_all
#check PlanInvariant.PlanData.SimulationMergePlanned.preserves_all
#check PlanInvariant.PlanData.DirectMergePlanned.preserves_all

#check PlanInvariant.PlanData.PositiveStep.actual_step
#check PlanInvariant.PlanData.PositiveStep.preserves_safe
#check PlanInvariant.PlanData.PositiveStep.version_mono
#check PlanInvariant.PlanData.positive_trace_preserves
#check PlanInvariant.PlanData.positive_trace_projects
#check PlanInvariant.PlanData.positive_trace_version_mono

#check PlanInvariant.PlanData.crossSlotMerge_simulation_admitted_but_plan_rejected
#check PlanInvariantExamples.concrete_two_prepare_execution

/-- The checked negative component forces the entire simulation-Merge plan
checker to reject any controller carrying the witnessed root map, independently
of its version or other plan fields.  This does not construct a `Valid` source
`PlanData`; it only closes the Boolean-composition point. -/
example
    (p : PlanInvariant.PlanData
      (Coord := PlanExamples.Coord) (Claim := PlanExamples.Claim)
      (Slot := PlanExamples.Slot))
    (offered : Nat) (hroot : p.rootSlot = PlanExamples.sourceRootSlot) :
    PlanInvariant.PlanData.checkSimulationMergePlan PlanExamples.source p
      PlanExamples.crossSlotMerge PlanExamples.crossSlotProject offered = false := by
  simp [PlanInvariant.PlanData.checkSimulationMergePlan, hroot,
    PlanInvariant.PlanData.crossSlotMerge_ownerRoot_check_rejected]

#print axioms PlanInvariant.PlanData.current_group_promotedLoad_le_capacity
#print axioms PlanInvariant.PlanData.current_group_actual_step
#print axioms PlanInvariant.PlanData.afterPrepareGroup_preserves_valid
#print axioms PlanInvariant.PlanData.PreparePlanned.actual_step
#print axioms PlanInvariant.PlanData.planned_prepare_trace_preserves
#print axioms PlanInvariant.PlanData.planned_prepare_trace_projects
#print axioms PlanInvariant.PlanData.planned_prepare_trace_version_mono
#print axioms PlanInvariant.PlanData.two_prepare_gate

#print axioms PlanInvariant.PlanData.checkCanonicalPlan_sound
#print axioms PlanInvariant.PlanData.checkedCanonical_preserves_all
#print axioms PlanInvariant.PlanData.RestrictionPlanned.preserves_all
#print axioms PlanInvariant.PlanData.RevokePlanned.preserves_all
#print axioms PlanInvariant.PlanData.SimulationMergePlanned.preserves_all
#print axioms PlanInvariant.PlanData.DirectMergePlanned.preserves_all

#print axioms PlanInvariant.PlanData.PositiveStep.actual_step
#print axioms PlanInvariant.PlanData.PositiveStep.preserves_safe
#print axioms PlanInvariant.PlanData.PositiveStep.version_mono
#print axioms PlanInvariant.PlanData.positive_trace_preserves
#print axioms PlanInvariant.PlanData.positive_trace_projects
#print axioms PlanInvariant.PlanData.positive_trace_version_mono

#print axioms PlanInvariant.PlanData.crossSlotMerge_simulation_admitted_but_plan_rejected
#print axioms PlanInvariantExamples.concrete_two_prepare_execution
