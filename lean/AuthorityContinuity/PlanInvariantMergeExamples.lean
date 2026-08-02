import AuthorityContinuity.PlanInvariantMerge
import AuthorityContinuity.PlanExamples

/-!
# Checked Merge plan-continuity examples

Concrete negative witnesses live outside the generic Merge/grammar modules so
the paper-facing controller theorem does not depend on the example suite.
-/

namespace AuthorityContinuity.PlanInvariant.PlanData

open AuthorityContinuity LifecycleState

/-! ## Executable negative fixture -/

/-- The existing simulation-admitted cross-slot Merge is rejected by the new
owner/root checker: claims `a` and `c` become co-owned while retaining distinct
inherited roots.  This is a specific negative witness, not a completeness
claim about all cross-slot or same-slot Merge descriptors. -/
theorem crossSlotMerge_ownerRoot_check_rejected :
    PlanRootTransport.checkTargetOwnerRootPure
      PlanExamples.source PlanExamples.crossSlotMerge.transfer
      PlanExamples.crossSlotMerge.allowed PlanExamples.sourceRootSlot =
        false := by
  apply PlanRootTransport.checkTargetOwnerRootPure_rejects_distinct_roots
      (c := PlanExamples.Claim.a) (c' := PlanExamples.Claim.c)
      (b := PlanExamples.Branch.x) (s := PlanExamples.Slot.a)
      (t := PlanExamples.Slot.c)
  · change PlanExamples.merged.auth.status PlanExamples.Claim.a =
      .tentative PlanExamples.Branch.x
    exact PlanExamples.merged_crosses_root_slots.1
  · change PlanExamples.merged.auth.status PlanExamples.Claim.c =
      .tentative PlanExamples.Branch.x
    exact PlanExamples.merged_crosses_root_slots.2.1
  · change PlanExamples.mergedRootSlot PlanExamples.Claim.a =
      some PlanExamples.Slot.a
    exact PlanExamples.merged_crosses_root_slots.2.2.1
  · change PlanExamples.mergedRootSlot PlanExamples.Claim.c =
      some PlanExamples.Slot.c
    exact PlanExamples.merged_crosses_root_slots.2.2.2
  · decide

/-- The negative witness is not rejected by lifecycle simulation: the existing
simulation checker accepts it, while the independent plan-lineage checker
rejects it. -/
theorem crossSlotMerge_simulation_admitted_but_plan_rejected :
    MergeCheck.simulationAdmission PlanExamples.source
        PlanExamples.crossSlotMerge PlanExamples.crossSlotProject = true ∧
      PlanRootTransport.checkTargetOwnerRootPure
        PlanExamples.source PlanExamples.crossSlotMerge.transfer
        PlanExamples.crossSlotMerge.allowed PlanExamples.sourceRootSlot =
          false :=
  ⟨PlanExamples.cross_slot_simulation_admitted,
    crossSlotMerge_ownerRoot_check_rejected⟩

#print axioms crossSlotMerge_ownerRoot_check_rejected
#print axioms crossSlotMerge_simulation_admitted_but_plan_rejected

end AuthorityContinuity.PlanInvariant.PlanData
