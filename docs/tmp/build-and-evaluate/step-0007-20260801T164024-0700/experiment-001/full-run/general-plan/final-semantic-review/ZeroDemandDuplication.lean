import AuthorityContinuity.PlanInvariantGrammar
import Mathlib.Tactic.FinCases

/-!
Adversarial executable model: a checked canonical parallel fork can refine one
zero-demand selected leaf into two distinct selected leaves.  This is not an
authority-safety counterexample; it bounds what may be called "linear" or
"never copied" without an additional discrete conservation invariant.
-/

namespace ZeroDemandDuplication

open AuthorityContinuity LifecycleState
open AuthorityContinuity.PlanInvariant
open AuthorityContinuity.PlanInvariant.PlanData

abbrev Coord := Fin 1
abbrev Claim := Fin 3
abbrev Branch := Fin 3
abbrev Grant := Fin 1
abbrev Operation := Fin 2
abbrev Slot := Fin 1

def source : LifecycleState Coord Claim Branch Grant Operation where
  auth := {
    capacity := fun _ => 0
    demand := fun _ _ => 0
    status := fun c => if c = 0 then .tentative 0 else .unissued
    allowed := ({0} : Finset Branch).powerset }
  grantOf := fun _ => 0
  branchEpoch := fun b => if b = 0 then .open else .unissued
  grantEpoch := fun _ => .open
  tickets := fun _ => none
  receipts := fun _ => none

def split : Transfer Claim Branch where
  owner := fun c => if c = 1 then some 1 else if c = 2 then some 2 else none
  rho := fun c => if c = 1 ∨ c = 2 then some 0 else none

def fork : CanonicalOp Branch := .parallelFork 0 1 2

def plan : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot) where
  version := 0
  d0 := fun _ => 0
  cap0 := fun _ => 0
  slots := Finset.univ
  rootSlot := fun c => if c = 0 then some 0 else none
  remaining := {0}
  R := fun _ _ => 0
  P := fun _ _ => 0
  E := fun _ _ => 0

theorem source_lwf : source.LWF := by
  refine {
    core := ?_
    configuration_open := ?_
    owner_open := ?_
    grant_open := ?_
    ticket_receipt_disjoint := ?_
    bound_durable := ?_
    binding_injective := ?_ }
  · refine {
      empty_mem := by simp [source]
      downward := ?_
      supported := ?_ }
    · intro C C' hC hsub
      exact Finset.mem_powerset.mpr
        (hsub.trans (by simpa [source] using Finset.mem_powerset.mp hC))
    · intro c b hstatus
      fin_cases c <;> fin_cases b <;> simp [source] at hstatus ⊢
  · intro C hC b hb
    have hb0 : b = 0 := by
      have hCsub : C ⊆ ({0} : Finset Branch) := by
        simpa [source] using Finset.mem_powerset.mp hC
      have : b ∈ ({0} : Finset Branch) := hCsub hb
      simpa using this
    subst b
    simp [source]
  · intro c b hstatus
    fin_cases c <;> fin_cases b <;> simp [source] at hstatus ⊢
  · intro c b hstatus
    simp [LifecycleState.claimOpen, source]
  · intro e t r ht
    simp [source] at ht
  · intro e c hbound
    simp [LifecycleState.opClaim, source] at hbound
  · intro e e' c hbound
    simp [LifecycleState.opClaim, source] at hbound

theorem source_ac : AC source.auth :=
  checkAC_sound source.auth (by decide)

theorem source_active_exact : source.ActiveExact := by
  intro b
  fin_cases b <;> simp [source]

theorem source_plan_valid : plan.Valid source := by
  refine {
    capacity_eq := ?_
    remaining_rooted := ?_
    owner_root_pure := ?_
    root_mem := ?_
    E_outside_zero := ?_
    P_outside_zero := ?_
    durable_eq := ?_
    envelope := ?_
    deadline := ?_
    batch_bound := ?_
    cursor_phase := ?_ }
  · intro k
    rfl
  · intro c hc
    have hc0 : c = 0 := by simpa [plan] using hc
    subst c
    exact ⟨0, 0, by simp [source], Finset.mem_univ _, by simp [plan]⟩
  · intro c c' b hc hc'
    fin_cases c <;> fin_cases c' <;> fin_cases b <;>
      simp [source, plan] at hc hc' ⊢
  · intro c s _
    exact Finset.mem_univ s
  · intro s hs k
    rfl
  · intro s hs k
    rfl
  · intro k
    fin_cases k
    decide
  · intro s _ k
    fin_cases s <;> fin_cases k <;> decide
  · intro s _ k
    fin_cases s <;> fin_cases k <;> decide
  · intro s _ k
    fin_cases s <;> fin_cases k <;> decide
  · intro s b _ t _ hlt k
    fin_cases s <;> fin_cases t
    simp at hlt

theorem canonical_plan_check_accepts :
    checkCanonicalPlan source plan split fork 0 = true := by
  decide

theorem actual_canonical_step :
    Step source .tau (canonicalTarget source split fork) := by
  have hp := checkCanonicalPlan_parts source plan split fork 0
    canonical_plan_check_accepts
  exact Step.canonical split fork hp.2.1

theorem target_plan_valid :
    (plan.afterCanonical split).Valid (canonicalTarget source split fork) :=
  (checkCanonicalPlan_sound source_plan_valid canonical_plan_check_accepts).1

theorem target_safe :
    (canonicalTarget source split fork).LWF ∧
      AC (canonicalTarget source split fork).auth ∧
      (canonicalTarget source split fork).ActiveExact := by
  have hp := checkCanonicalPlan_parts source plan split fork 0
    canonical_plan_check_accepts
  exact canonical_preserves_wf_ac source split fork source_lwf source_ac
    source_active_exact hp.2.1

theorem one_leaf_becomes_two :
    plan.remaining.card = 1 ∧
      (plan.afterCanonical split).remaining = ({1, 2} : Finset Claim) ∧
      (plan.afterCanonical split).remaining.card = 2 := by
  decide

def forkedState : InvariantState
    (Coord := Coord) (Claim := Claim) (Branch := Branch) (Grant := Grant)
    (Operation := Operation) (Slot := Slot) where
  lifecycle := canonicalTarget source split fork
  plan := plan.afterCanonical split

def assignmentOne : Operation -> Option Claim := fun e =>
  if e = 0 then some 1 else none

def assignmentTwo : Operation -> Option Claim := fun e =>
  if e = 1 then some 2 else none

def afterOne : InvariantState
    (Coord := Coord) (Claim := Claim) (Branch := Branch) (Grant := Grant)
    (Operation := Operation) (Slot := Slot) :=
  advancePrepare forkedState assignmentOne

def afterTwo : InvariantState
    (Coord := Coord) (Claim := Claim) (Branch := Branch) (Grant := Grant)
    (Operation := Operation) (Slot := Slot) :=
  advancePrepare afterOne assignmentTwo

theorem first_remaining : forkedState.plan.remaining.Nonempty := by decide

theorem first_assignment :
    Plan.checkAssignment forkedState.lifecycle
      (forkedState.plan.headGroup forkedState.lifecycle) assignmentOne = true := by
  decide

theorem second_remaining : afterOne.plan.remaining.Nonempty := by decide

theorem second_assignment :
    Plan.checkAssignment afterOne.lifecycle
      (afterOne.plan.headGroup afterOne.lifecycle) assignmentTwo = true := by
  decide

theorem two_distinct_tickets_from_one_source_leaf :
    PreparePlanned forkedState 1 assignmentOne afterOne ∧
      PreparePlanned afterOne 2 assignmentTwo afterTwo ∧
      afterTwo.lifecycle.tickets 0 = some ⟨1, .prepared⟩ ∧
      afterTwo.lifecycle.tickets 1 = some ⟨2, .prepared⟩ := by
  have hFirst : PreparePlanned forkedState 1 assignmentOne afterOne := by
    apply PreparePlanned.mk
    · exact target_safe.1
    · exact target_plan_valid
    · exact first_remaining
    · decide
    · exact first_assignment
  have hSafeOne := hFirst.preserves_wf_ac target_safe.2.1
  have hValidOne := hFirst.preserves_valid
  have hSecond : PreparePlanned afterOne 2 assignmentTwo afterTwo := by
    apply PreparePlanned.mk
    · exact hSafeOne.1
    · exact hValidOne
    · exact second_remaining
    · decide
    · exact second_assignment
  exact ⟨hFirst, hSecond, by decide, by decide⟩

#print axioms source_plan_valid
#print axioms canonical_plan_check_accepts
#print axioms actual_canonical_step
#print axioms target_plan_valid
#print axioms one_leaf_becomes_two
#print axioms two_distinct_tickets_from_one_source_leaf

end ZeroDemandDuplication
