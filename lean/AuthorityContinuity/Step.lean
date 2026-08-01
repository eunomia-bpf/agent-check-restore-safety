import AuthorityContinuity.Topology
import AuthorityContinuity.Merge

/-!
# Authoritative full lifecycle step

This module is the sole paper-facing transition relation.  It embeds every
non-topology `CoreStep`, gives the four canonical Fork/Restore forms one
computed-target constructor, and keeps simulation-certified Merge separate
from direct target admission.  In particular, there is no constructor taking
an arbitrary target state or a fieldwise logical target certificate.
-/

namespace AuthorityContinuity

open LifecycleState

universe uC uI uB uG uO

variable {Coord : Type uC} {Claim : Type uI} {Branch : Type uB}
variable {Grant : Type uG} {Operation : Type uO}
variable [Fintype Coord] [DecidableEq Coord]
variable [Fintype Claim] [DecidableEq Claim]
variable [Fintype Branch] [DecidableEq Branch]
variable [DecidableEq Grant] [DecidableEq Operation]

/-- The unique full lifecycle relation used by the paper and trace theorems.
Canonical targets are functions of the source, transfer, and operation;
explicit Merge targets are functions of the source and checked descriptor. -/
inductive Step :
    LifecycleState Coord Claim Branch Grant Operation →
    Label Operation Claim →
    LifecycleState Coord Claim Branch Grant Operation → Prop where
  | core {A A' eta} (transition : CoreStep A eta A') : Step A eta A'
  | canonical {A} (tr : Transfer Claim Branch) (op : CanonicalOp Branch)
      (checked : checkCanonical A tr op = true) :
      Step A .tau (canonicalTarget A tr op)
  | simulationMerge {A} (d : MergeDescriptor Claim Branch)
      (project : Finset Branch → Finset Branch)
      (checked : MergeCheck.simulationAdmission A d project = true) :
      Step A .tau (d.target A)
  | directMerge {A} (d : MergeDescriptor Claim Branch)
      (checked : MergeCheck.directAdmission A d = true) :
      Step A .tau (d.target A)

/-- Every full lifecycle step preserves all three coupled invariants.  The
source exact-activity premise is load-bearing for canonical topology: it lets
the computed builder derive, rather than assume, the target support. -/
theorem step_preserves_wf_ac
    {A A' : LifecycleState Coord Claim Branch Grant Operation}
    {eta : Label Operation Claim} (hstep : Step A eta A')
    (hWF : LWF A) (hAC : AC A.auth) (hActive : ActiveExact A) :
    LWF A' ∧ AC A'.auth ∧ ActiveExact A' := by
  cases hstep with
  | core transition =>
      have hCore := core_step_preserves_wf_ac transition hWF hAC
      exact ⟨hCore.1, hCore.2,
        core_step_preserves_active_exact transition hWF hActive⟩
  | canonical tr op checked =>
      exact canonical_preserves_wf_ac A tr op hWF hAC hActive checked
  | simulationMerge d project checked =>
      exact simulation_merge_preserves_wf_ac A d project hWF hAC checked
  | directMerge d checked =>
      exact direct_merge_preserves_wf_ac A d hWF checked

/-- Existing stable operation bindings survive every full lifecycle step.
Prepare may allocate a previously unbound operation, but it cannot replace a
binding; canonical and Merge targets preserve the ticket/receipt maps. -/
theorem step_preserves_existing_binding
    {A A' : LifecycleState Coord Claim Branch Grant Operation}
    {eta : Label Operation Claim} (hstep : Step A eta A') :
    ∀ e c, A.opClaim e = some c → A'.opClaim e = some c := by
  intro e c hbound
  cases hstep with
  | core transition =>
      exact core_step_preserves_existing_binding transition e c hbound
  | canonical tr op checked =>
      exact (canonicalTarget_existing_binding A tr op e).trans hbound
  | simulationMerge d project checked =>
      exact (d.target_opClaim A e).trans hbound
  | directMerge d checked =>
      exact (d.target_opClaim A e).trans hbound

/-- No full lifecycle step can resurrect a terminal claim identifier. -/
theorem step_terminal_mono
    {A A' : LifecycleState Coord Claim Branch Grant Operation}
    {eta : Label Operation Claim} (hstep : Step A eta A') :
    A.TerminalMonotone A' := by
  cases hstep with
  | core transition => exact core_step_terminal_mono transition
  | canonical tr op checked =>
      exact canonicalTarget_terminal_mono A tr op checked
  | simulationMerge d project checked =>
      have hparts :
          (MergeCheck.structural A d = true ∧
            MergeCheck.monoZero project = true) ∧
            MergeCheck.simulation A d project = true := by
        simpa [MergeCheck.simulationAdmission, Bool.and_eq_true] using checked
      exact d.target_terminal_mono A
        (MergeCheck.checkMergeStructure_sound A d hparts.1.1)
  | directMerge d checked =>
      have hparts : MergeCheck.structural A d = true ∧
          checkAC (d.target A).auth = true := by
        simpa [MergeCheck.directAdmission, Bool.and_eq_true] using checked
      exact d.target_terminal_mono A
        (MergeCheck.checkMergeStructure_sound A d hparts.1)

/-- Branch and grant epochs advance monotonically across every full step. -/
theorem step_epoch_mono
    {A A' : LifecycleState Coord Claim Branch Grant Operation}
    {eta : Label Operation Claim} (hstep : Step A eta A') :
    A.EpochMonotone A' := by
  cases hstep with
  | core transition => exact core_step_epoch_mono transition
  | canonical tr op checked =>
      exact canonicalTarget_epoch_mono A tr op checked
  | simulationMerge d project checked =>
      have hparts :
          (MergeCheck.structural A d = true ∧
            MergeCheck.monoZero project = true) ∧
            MergeCheck.simulation A d project = true := by
        simpa [MergeCheck.simulationAdmission, Bool.and_eq_true] using checked
      exact d.target_epoch_mono A
        (MergeCheck.checkMergeStructure_sound A d hparts.1.1)
  | directMerge d checked =>
      have hparts : MergeCheck.structural A d = true ∧
          checkAC (d.target A).auth = true := by
        simpa [MergeCheck.directAdmission, Bool.and_eq_true] using checked
      exact d.target_epoch_mono A
        (MergeCheck.checkMergeStructure_sound A d hparts.1)

/-- An attempt label can arise only from the ticket subrelation; it therefore
uses the pre-existing stable binding of a claim already durable before the
physical attempt. -/
theorem step_attempt_safe
    {A A' : LifecycleState Coord Claim Branch Grant Operation}
    {e : Operation} {c : Claim}
    (hstep : Step A (.attempt e c) A') (hWF : LWF A) :
    A.opClaim e = some c ∧ A.auth.status c = .durable ∧
      A'.opClaim e = some c := by
  cases hstep with
  | core transition => exact core_step_attempt_safe transition hWF

end AuthorityContinuity
