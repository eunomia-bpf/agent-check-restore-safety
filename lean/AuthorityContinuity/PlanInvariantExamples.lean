import AuthorityContinuity.PlanInvariant

/-!
# Closed two-slot scheduler fixture

This module gives a finite, executable witness that the multi-slot invariant
and its two-Prepare gate are non-vacuous.  Every admission fact below is proved
for concrete data; no target invariant, second-step nonemptiness, or assignment
certificate is a theorem argument.
-/

namespace AuthorityContinuity.PlanInvariantExamples

open AuthorityContinuity LifecycleState PlanInvariant
open PlanInvariant.PlanData

abbrev ExCoord := Fin 1
abbrev ExClaim := Fin 2
abbrev ExBranch := Fin 2
abbrev ExGrant := Fin 2
abbrev ExOperation := Fin 2
abbrev ExSlot := Fin 2

def sourceAuth : State ExCoord ExClaim ExBranch where
  capacity := fun _ => 2
  demand := fun _ _ => 1
  status := fun c => .tentative c
  allowed := Finset.univ

def sourceLifecycle :
    LifecycleState ExCoord ExClaim ExBranch ExGrant ExOperation where
  auth := sourceAuth
  grantOf := fun c => c
  branchEpoch := fun _ => .open
  grantEpoch := fun _ => .open
  tickets := fun _ => none
  receipts := fun _ => none

def sourcePlan :
    PlanData (Coord := ExCoord) (Claim := ExClaim) (Slot := ExSlot) where
  version := 0
  d0 := fun _ => 0
  cap0 := fun _ => 2
  slots := Finset.univ
  rootSlot := fun c => some c
  remaining := Finset.univ
  R := fun _ _ => 1
  P := fun _ _ => 1
  E := fun _ _ => 0

def sourceState :
    InvariantState (Coord := ExCoord) (Claim := ExClaim)
      (Branch := ExBranch) (Grant := ExGrant) (Operation := ExOperation)
      (Slot := ExSlot) where
  lifecycle := sourceLifecycle
  plan := sourcePlan

/-- The first fresh operation covers exactly the first owner group. -/
def assignment₀ : ExOperation -> Option ExClaim := fun e =>
  if e = 0 then some 0 else none

/-- The second fresh operation covers exactly the surviving owner group. -/
def assignment₁ : ExOperation -> Option ExClaim := fun e =>
  if e = 1 then some 1 else none

def state₁ :
    InvariantState (Coord := ExCoord) (Claim := ExClaim)
      (Branch := ExBranch) (Grant := ExGrant) (Operation := ExOperation)
      (Slot := ExSlot) :=
  advancePrepare sourceState assignment₀

def state₂ :
    InvariantState (Coord := ExCoord) (Claim := ExClaim)
      (Branch := ExBranch) (Grant := ExGrant) (Operation := ExOperation)
      (Slot := ExSlot) :=
  advancePrepare state₁ assignment₁

theorem source_has_two_owner_groups :
    (sourcePlan.ownerGroup sourceLifecycle 0 0).Nonempty ∧
      (sourcePlan.ownerGroup sourceLifecycle 1 1).Nonempty := by
  decide

theorem source_first_group :
    sourcePlan.firstGroup sourceLifecycle = some (0, 0) := by
  decide

theorem source_lwf : sourceLifecycle.LWF := by
  refine {
    core := ?_
    configuration_open := ?_
    owner_open := ?_
    grant_open := ?_
    ticket_receipt_disjoint := ?_
    bound_durable := ?_
    binding_injective := ?_ }
  · refine {
      empty_mem := by simp [sourceLifecycle, sourceAuth]
      downward := ?_
      supported := ?_ }
    · intro C C' _ _
      simp [sourceLifecycle, sourceAuth]
    · intro c b hstatus
      have hbc : b = c := by
        simpa [sourceLifecycle, sourceAuth] using hstatus.symm
      subst b
      exact ⟨{c}, by simp [sourceLifecycle, sourceAuth], by simp⟩
  · intro C _ b _
    rfl
  · intro c b _
    rfl
  · intro c b _
    rfl
  · intro e t r ht _
    simp [sourceLifecycle] at ht
  · intro e c hclaim
    simp [LifecycleState.opClaim, sourceLifecycle] at hclaim
  · intro e e' c hclaim
    simp [LifecycleState.opClaim, sourceLifecycle] at hclaim

theorem source_ac : AC sourceLifecycle.auth := by
  intro C _ k
  fin_cases C <;> fin_cases k <;> decide

theorem source_active_exact : sourceLifecycle.ActiveExact := by
  intro b
  constructor
  · intro _
    exact ⟨{b}, by simp [sourceLifecycle, sourceAuth], by simp⟩
  · intro _
    rfl

theorem source_valid : sourcePlan.Valid sourceLifecycle := by
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
  · intro c _
    exact ⟨c, c, rfl, Finset.mem_univ c, rfl⟩
  · intro c c' b
    fin_cases c <;> fin_cases c' <;> fin_cases b <;> decide
  · intro c s _
    exact Finset.mem_univ s
  · intro s _ k
    rfl
  · intro s hs k
    simp [sourcePlan] at hs
  · intro k
    fin_cases k
    decide
  · intro s _ k
    fin_cases s <;> fin_cases k <;> decide
  · intro s _ k
    fin_cases s <;> fin_cases k <;> decide
  · intro s _ k
    fin_cases s <;> fin_cases k <;> decide
  · intro s b _ t _ _ k
    rfl

theorem first_remaining_nonempty : sourcePlan.remaining.Nonempty := by
  decide

theorem first_assignment_checked :
    Plan.checkAssignment sourceLifecycle
      (sourcePlan.headGroup sourceLifecycle) assignment₀ = true := by
  decide

theorem second_remaining_nonempty : state₁.plan.remaining.Nonempty := by
  decide

theorem second_head_group :
    state₁.plan.firstGroup state₁.lifecycle = some (1, 1) := by
  decide

theorem second_assignment_checked :
    Plan.checkAssignment state₁.lifecycle
      (state₁.plan.headGroup state₁.lifecycle) assignment₁ = true := by
  decide

theorem final_remaining_empty : state₂.plan.remaining = ∅ := by
  decide

/-- Direct closed instantiation of the frozen abstract two-Prepare gate. -/
theorem concrete_two_prepare_gate :
    ∃ S₁ S₂,
      PreparePlanned sourceState sourceState.plan.version assignment₀ S₁ ∧
      PreparePlanned S₁ S₁.plan.version assignment₁ S₂ ∧
      Step sourceState.lifecycle .tau S₁.lifecycle ∧
      Step S₁.lifecycle .tau S₂.lifecycle ∧
      S₂.plan.Valid S₂.lifecycle := by
  exact two_prepare_gate sourceState source_lwf source_ac source_valid
    first_remaining_nonempty assignment₀ first_assignment_checked
    (by simpa [state₁] using second_remaining_nonempty)
    assignment₁ (by simpa [state₁] using second_assignment_checked)

/-- A fully closed two-step execution witness.  Both `PreparePlanned` edges are
constructed from concrete Boolean checks, and both lifecycle edges are the
repository's actual `Step` relation. -/
theorem concrete_two_prepare_execution :
    PreparePlanned sourceState 0 assignment₀ state₁ ∧
      PreparePlanned state₁ 1 assignment₁ state₂ ∧
      Step sourceState.lifecycle .tau state₁.lifecycle ∧
      Step state₁.lifecycle .tau state₂.lifecycle ∧
      state₂.plan.Valid state₂.lifecycle ∧
      state₂.plan.version = sourceState.plan.version + 2 ∧
      state₁.plan.remaining.card < sourceState.plan.remaining.card ∧
      state₂.plan.remaining.card < state₁.plan.remaining.card ∧
      state₂.plan.remaining = ∅ := by
  have hVersion₀ : sourceState.plan.checkVersion 0 = true := by decide
  have hFirst : PreparePlanned sourceState 0 assignment₀ state₁ := by
    simpa [state₁, sourceState] using
      (PreparePlanned.mk source_lwf source_valid first_remaining_nonempty
        hVersion₀ first_assignment_checked)
  have hSafe₁ := hFirst.preserves_wf_ac source_ac
  have hValid₁ := hFirst.preserves_valid
  have hVersion₁ : state₁.plan.checkVersion 1 = true := by decide
  have hSecond : PreparePlanned state₁ 1 assignment₁ state₂ := by
    simpa [state₂] using
      (PreparePlanned.mk hSafe₁.1 hValid₁ second_remaining_nonempty
        hVersion₁ second_assignment_checked)
  refine ⟨hFirst, hSecond, hFirst.actual_step, hSecond.actual_step,
    hSecond.preserves_valid, ?_, hFirst.remaining_card_lt,
    hSecond.remaining_card_lt, final_remaining_empty⟩
  decide

#print axioms source_lwf
#print axioms source_ac
#print axioms source_active_exact
#print axioms source_valid
#print axioms concrete_two_prepare_gate
#print axioms concrete_two_prepare_execution

end AuthorityContinuity.PlanInvariantExamples
