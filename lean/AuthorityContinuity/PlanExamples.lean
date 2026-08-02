import AuthorityContinuity.Step
import Mathlib.Tactic.FinCases

/-!
# Observation lower bound and cross-slot Merge examples

This module is deliberately self-contained.  The old promotion plan is
represented by a fixed batch, an immutable root-slot map, a slot-order
deadline predicate, and a computed owner-purity condition.  The negative
history is produced by the repository's real simulation-Merge relation.
-/

namespace AuthorityContinuity.PlanExamples

open LifecycleState

abbrev Coord := Fin 1
abbrev Claim := Fin 7
abbrev Branch := Fin 7
abbrev Grant := Fin 2
abbrev Operation := Fin 1
abbrev Slot := Fin 4

namespace Claim
def a : Claim := 0
def b : Claim := 1
def c : Claim := 2
def d : Claim := 3
def bPad : Claim := 4
def cPad : Claim := 5
def unrelated : Claim := 6
end Claim

namespace Branch
def a : Branch := 0
def b : Branch := 1
def c : Branch := 2
def d : Branch := 3
def x : Branch := 4
def y : Branch := 5
def unrelated : Branch := 6
end Branch

namespace Slot
def a : Slot := 0
def b : Slot := 1
def c : Slot := 2
def d : Slot := 3
end Slot

def oldBatch : Finset Claim := {Claim.a, Claim.b, Claim.c, Claim.d}

/-- Source contract: `{a,c}` and `{b,d}` are the two maximal planned
configurations; the zero-demand unrelated owner may coexist with either. -/
def sourceAllowed : Finset (Finset Branch) :=
  ({Branch.a, Branch.c, Branch.unrelated} : Finset Branch).powerset ∪
  ({Branch.b, Branch.d, Branch.unrelated} : Finset Branch).powerset

def source : LifecycleState Coord Claim Branch Grant Operation where
  auth := {
    capacity := fun _ => 4
    demand := fun c _ => if c = Claim.unrelated then 0 else 1
    status := fun c =>
      if c = Claim.a then .tentative Branch.a
      else if c = Claim.b ∨ c = Claim.bPad then .tentative Branch.b
      else if c = Claim.c ∨ c = Claim.cPad then .tentative Branch.c
      else if c = Claim.d then .tentative Branch.d
      else .tentative Branch.unrelated
    allowed := sourceAllowed
  }
  grantOf := fun c => if c = Claim.unrelated then 1 else 0
  branchEpoch := fun b =>
    if b = Branch.a ∨ b = Branch.b ∨ b = Branch.c ∨ b = Branch.d ∨
        b = Branch.unrelated then .open else .unissued
  grantEpoch := fun _ => .open
  tickets := fun _ => none
  receipts := fun _ => none

/-- Retained claim IDs are coarsened across old slot boundaries. -/
def crossSlotTransfer : Transfer Claim Branch where
  owner := fun c =>
    if c = Claim.a ∨ c = Claim.c ∨ c = Claim.cPad then some Branch.x
    else if c = Claim.unrelated then some Branch.unrelated
    else some Branch.y
  rho := fun c => some c

def mergeAllowed : Finset (Finset Branch) :=
  ({Branch.x, Branch.unrelated} : Finset Branch).powerset ∪
  ({Branch.y, Branch.unrelated} : Finset Branch).powerset

def crossSlotMerge : MergeDescriptor Claim Branch where
  allowed := mergeAllowed
  branchEpoch := fun b =>
    if b = Branch.x ∨ b = Branch.y ∨ b = Branch.unrelated then .open
    else .closed
  transfer := crossSlotTransfer

/-- The target choice projects to the corresponding source configuration. -/
def crossSlotProject (C : Finset Branch) : Finset Branch :=
  (if Branch.x ∈ C then {Branch.a, Branch.c} else ∅) ∪
  (if Branch.y ∈ C then {Branch.b, Branch.d} else ∅) ∪
  (if Branch.unrelated ∈ C then {Branch.unrelated} else ∅)

def merged : LifecycleState Coord Claim Branch Grant Operation :=
  crossSlotMerge.target source

theorem source_lwf : source.LWF := by
  refine ⟨⟨?_, ?_, ?_⟩, ?_, ?_, ?_, ?_, ?_, ?_⟩
  · simp [source, sourceAllowed]
  · intro C C' hC hsub
    simp only [source, sourceAllowed, Finset.mem_union,
      Finset.mem_powerset] at hC ⊢
    exact hC.elim (fun h => Or.inl (hsub.trans h))
      (fun h => Or.inr (hsub.trans h))
  · intro c b hstatus
    refine ⟨{b}, ?_, by simp⟩
    fin_cases c <;> fin_cases b <;>
      simp [source, sourceAllowed, Claim.a, Claim.b, Claim.c, Claim.d,
        Claim.bPad, Claim.cPad, Claim.unrelated, Branch.a, Branch.b,
        Branch.c, Branch.d, Branch.unrelated] at hstatus ⊢
  · intro C hC b hbC
    simp only [source, sourceAllowed, Finset.mem_union,
      Finset.mem_powerset] at hC
    rcases hC with hC | hC
    · have hb := hC hbC
      fin_cases b <;>
        simp [source, Branch.a, Branch.b, Branch.c, Branch.d,
          Branch.unrelated] at hb ⊢
    · have hb := hC hbC
      fin_cases b <;>
        simp [source, Branch.a, Branch.b, Branch.c, Branch.d,
          Branch.unrelated] at hb ⊢
  · intro c b hstatus
    fin_cases c <;> fin_cases b <;>
      simp [source, Claim.a, Claim.b, Claim.c, Claim.d, Claim.bPad,
        Claim.cPad, Claim.unrelated, Branch.a, Branch.b, Branch.c,
        Branch.d, Branch.unrelated] at hstatus ⊢
  · intro c b hstatus
    simp [LifecycleState.claimOpen, source]
  · intro e t r ht
    simp [source] at ht
  · intro e c hop
    simp [LifecycleState.opClaim, source] at hop
  · intro e e' c hop
    simp [LifecycleState.opClaim, source] at hop

theorem source_ac : AC source.auth :=
  checkAC_sound source.auth (by decide)

set_option maxRecDepth 100000 in
set_option maxHeartbeats 20000000 in
theorem cross_slot_simulation_admitted :
    MergeCheck.simulationAdmission source crossSlotMerge crossSlotProject = true := by
  decide

theorem actual_cross_slot_merge : Step source .tau merged :=
  Step.simulationMerge crossSlotMerge crossSlotProject
    cross_slot_simulation_admitted

theorem merged_lwf_ac :
    merged.LWF ∧ AC merged.auth ∧ merged.ActiveExact :=
  simulation_merge_preserves_wf_ac source crossSlotMerge crossSlotProject
    source_lwf source_ac cross_slot_simulation_admitted

/-! ## Explicit old-plan continuity predicate -/

/-- Root slots are immutable lineage labels, not mutable branch names. -/
def sourceRootSlot (c : Claim) : Option Slot :=
  if c = Claim.a then some Slot.a
  else if c = Claim.b ∨ c = Claim.bPad then some Slot.b
  else if c = Claim.c ∨ c = Claim.cPad then some Slot.c
  else if c = Claim.d then some Slot.d
  else none

/-- Transfer computes the child/root lineage from `rho`; no target slot map is
accepted from the Merge caller. -/
def inheritedRootSlot (tr : Transfer Claim Branch)
    (root : Claim → Option Slot) (c : Claim) : Option Slot :=
  (tr.rho c).bind root

def mergedRootSlot : Claim → Option Slot :=
  inheritedRootSlot crossSlotTransfer sourceRootSlot

def tentativeSlotLoad
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (root : Claim → Option Slot) (i : Slot) (k : Coord) : Nat :=
  ∑ c ∈ Finset.univ.filter (fun c =>
    (root c = some i) ∧ ∃ b, A.auth.status c = .tentative b),
    A.auth.demand c k

def batchSlotLoad
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (U : Finset Claim) (root : Claim → Option Slot)
    (i : Slot) (k : Coord) : Nat :=
  ∑ c ∈ U.filter (fun c => root c = some i), A.auth.demand c k

def priorBatchLoad
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (U : Finset Claim) (root : Claim → Option Slot)
    (i : Slot) (k : Coord) : Nat :=
  ∑ j ∈ Finset.univ.filter (fun j : Slot => j < i),
    batchSlotLoad A U root j k

/-- The frozen order has enough headroom at every slot. -/
def SlotDeadlines
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (U : Finset Claim) (root : Claim → Option Slot) : Prop :=
  ∀ i k, priorBatchLoad A U root i k + tentativeSlotLoad A root i k ≤
    A.auth.capacity k

/-- A target owner may not combine claims descended from distinct old slots. -/
def OwnerPure
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (root : Claim → Option Slot) : Prop :=
  ∀ c c' b,
    A.auth.status c = .tentative b →
    A.auth.status c' = .tentative b →
    root c = root c'

def checkSlotDeadlines
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (U : Finset Claim) (root : Claim → Option Slot) : Bool :=
  finiteAll Finset.univ fun i : Slot =>
    finiteAll Finset.univ fun k : Coord => decide
      (priorBatchLoad A U root i k + tentativeSlotLoad A root i k ≤
        A.auth.capacity k)

def checkOwnerPure
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (root : Claim → Option Slot) : Bool :=
  finiteAll Finset.univ fun c : Claim =>
    finiteAll Finset.univ fun c' : Claim =>
      match A.auth.status c, A.auth.status c' with
      | .tentative b, .tentative b' =>
          if b = b' then decide (root c = root c') else true
      | _, _ => true

theorem checkSlotDeadlines_sound
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {U : Finset Claim} {root : Claim → Option Slot}
    (h : checkSlotDeadlines A U root = true) : SlotDeadlines A U root := by
  intro i k
  have hi := (finiteAll_eq_true Finset.univ _).mp h i (Finset.mem_univ i)
  have hk := (finiteAll_eq_true Finset.univ _).mp hi k (Finset.mem_univ k)
  exact of_decide_eq_true hk

theorem checkOwnerPure_sound
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {root : Claim → Option Slot}
    (h : checkOwnerPure A root = true) : OwnerPure A root := by
  intro c c' b hc hc'
  have hrow := (finiteAll_eq_true Finset.univ _).mp h c (Finset.mem_univ c)
  have hpair := (finiteAll_eq_true Finset.univ _).mp hrow c'
    (Finset.mem_univ c')
  simpa [checkOwnerPure, hc, hc'] using hpair

def PlanContinuity
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (U : Finset Claim) (root : Claim → Option Slot) : Prop :=
  checkSlotDeadlines A U root = true ∧ checkOwnerPure A root = true

theorem PlanContinuity.sound
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {U : Finset Claim} {root : Claim → Option Slot}
    (h : PlanContinuity A U root) :
    SlotDeadlines A U root ∧ OwnerPure A root :=
  ⟨checkSlotDeadlines_sound h.1, checkOwnerPure_sound h.2⟩

theorem source_plan_continuity :
    PlanContinuity source oldBatch sourceRootSlot := by
  change checkSlotDeadlines source oldBatch sourceRootSlot = true ∧
    checkOwnerPure source sourceRootSlot = true
  set_option maxRecDepth 100000 in
    decide

theorem source_plan_semantics :
    SlotDeadlines source oldBatch sourceRootSlot ∧
      OwnerPure source sourceRootSlot :=
  source_plan_continuity.sound

theorem merged_crosses_root_slots :
    merged.auth.status Claim.a = .tentative Branch.x ∧
    merged.auth.status Claim.c = .tentative Branch.x ∧
    mergedRootSlot Claim.a = some Slot.a ∧
    mergedRootSlot Claim.c = some Slot.c := by decide

theorem cross_slot_merge_breaks_plan :
    ¬ PlanContinuity merged oldBatch mergedRootSlot := by
  change ¬ (checkSlotDeadlines merged oldBatch mergedRootSlot = true ∧
    checkOwnerPure merged mergedRootSlot = true)
  set_option maxRecDepth 100000 in
    decide

theorem merged_not_owner_pure : ¬ OwnerPure merged mergedRootSlot := by
  intro h
  have hslots := h Claim.a Claim.c Branch.x (by decide) (by decide)
  have hne : mergedRootSlot Claim.a ≠ mergedRootSlot Claim.c := by decide
  exact hne hslots

theorem cross_slot_merge_breaks_plan_semantics :
    ¬ (SlotDeadlines merged oldBatch mergedRootSlot ∧
      OwnerPure merged mergedRootSlot) := by
  intro h
  exact merged_not_owner_pure h.2

def ownerTentativeLoad
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (b : Branch) (k : Coord) : Nat :=
  ∑ c ∈ Finset.univ.filter (fun c => A.auth.status c = .tentative b),
    A.auth.demand c k

def ownerBatchLoad
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (U : Finset Claim) (b : Branch) (k : Coord) : Nat :=
  ∑ c ∈ U.filter (fun c => A.auth.status c = .tentative b),
    A.auth.demand c k

def TwoOwnerOrderSafe
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (U : Finset Claim) (first second : Branch) : Prop :=
  (finiteAll Finset.univ fun k : Coord => decide
    (ownerBatchLoad A U first k + ownerTentativeLoad A second k ≤
      A.auth.capacity k)) = true

theorem merged_x_then_y_unsafe :
    ¬ TwoOwnerOrderSafe merged oldBatch Branch.x Branch.y := by
  change ¬ ((finiteAll Finset.univ fun k : Coord => decide
    (ownerBatchLoad merged oldBatch Branch.x k +
      ownerTentativeLoad merged Branch.y k ≤ merged.auth.capacity k)) = true)
  decide

theorem merged_y_then_x_unsafe :
    ¬ TwoOwnerOrderSafe merged oldBatch Branch.y Branch.x := by
  change ¬ ((finiteAll Finset.univ fun k : Coord => decide
    (ownerBatchLoad merged oldBatch Branch.y k +
      ownerTentativeLoad merged Branch.x k ≤ merged.auth.capacity k)) = true)
  decide

/-! ## Frozen local observation and quantified lower bound -/

inductive CoarsePhase where
  | unissued | tentative | durable | terminal
  deriving DecidableEq, Repr

def coarsePhase : ClaimStatus Branch → CoarsePhase
  | .unissued => .unissued
  | .tentative _ => .tentative
  | .durable => .durable
  | .terminal => .terminal

/-- This footprint intentionally omits tentative owner, the allowed-contract
topology, transfer roots, and owner-slot grouping.  Metadata functions are
masked outside `scheduled`, so unrelated claims are unobserved. -/
@[ext] structure LocalAuthObs where
  offeredPlan : Nat
  capacity : Coord → Nat
  durableLoad : Coord → Nat
  scheduled : Finset Claim
  demand : Claim → Coord → Option Nat
  grant : Claim → Option Grant
  phase : Claim → Option CoarsePhase
  grantEpoch : Claim → Option EpochStatus
  deriving DecidableEq

def observeLocal (offered : Nat) (U : Finset Claim)
    (A : LifecycleState Coord Claim Branch Grant Operation) : LocalAuthObs where
  offeredPlan := offered
  capacity := A.auth.capacity
  durableLoad := A.auth.durableLoad
  scheduled := U
  demand := fun c k => if c ∈ U then some (A.auth.demand c k) else none
  grant := fun c => if c ∈ U then some (A.grantOf c) else none
  phase := fun c => if c ∈ U then some (coarsePhase (A.auth.status c)) else none
  grantEpoch := fun c =>
    if c ∈ U then some (A.grantEpoch (A.grantOf c)) else none

def safeLocalObs : LocalAuthObs := observeLocal 17 oldBatch source
def unsafeLocalObs : LocalAuthObs := observeLocal 17 oldBatch merged

theorem local_observation_indistinguishable :
    safeLocalObs = unsafeLocalObs := by
  apply LocalAuthObs.ext
  · rfl
  · rfl
  · funext k
    fin_cases k
    decide
  · rfl
  · rfl
  · rfl
  · funext c
    fin_cases c <;> decide
  · rfl

theorem local_safe_unsafe_pair :
    (SlotDeadlines source oldBatch sourceRootSlot ∧
      OwnerPure source sourceRootSlot) ∧
    ¬ (SlotDeadlines merged oldBatch mergedRootSlot ∧
      OwnerPure merged mergedRootSlot) ∧
    safeLocalObs = unsafeLocalObs :=
  ⟨source_plan_semantics, cross_slot_merge_breaks_plan_semantics,
    local_observation_indistinguishable⟩

/-- No decision procedure over the frozen local footprint can both accept the
valid old plan and reject the actual cross-slot Merge history. -/
theorem version_observation_lower_bound
    (f : LocalAuthObs → Bool) :
    (f unsafeLocalObs = true ∧
      ¬ (SlotDeadlines merged oldBatch mergedRootSlot ∧
        OwnerPure merged mergedRootSlot)) ∨
    (f safeLocalObs = false ∧
      (SlotDeadlines source oldBatch sourceRootSlot ∧
        OwnerPure source sourceRootSlot)) := by
  by_cases h : f safeLocalObs = true
  · left
    refine ⟨?_, cross_slot_merge_breaks_plan_semantics⟩
    simpa [local_observation_indistinguishable] using h
  · right
    exact ⟨Bool.eq_false_of_not_eq_true h, source_plan_semantics⟩

/-! ## Global invalidation is safe but unnecessarily coarse -/

def plannedBranches : Finset Branch :=
  {Branch.a, Branch.b, Branch.c, Branch.d}

def irrelevantMutation : LifecycleState Coord Claim Branch Grant Operation :=
  restrictLifecycle source plannedBranches Finset.univ

theorem irrelevant_mutation_actual_step : Step source .tau irrelevantMutation :=
  Step.core (CoreStep.restriction source plannedBranches Finset.univ)

theorem irrelevant_mutation_confined_to_none_slot :
    (∀ c ∈ oldBatch,
      irrelevantMutation.auth.status c = source.auth.status c) ∧
    sourceRootSlot Claim.unrelated = none ∧
    source.auth.status Claim.unrelated = .tentative Branch.unrelated ∧
    irrelevantMutation.auth.status Claim.unrelated = .terminal := by decide

theorem irrelevant_mutation_preserves_plan :
    PlanContinuity irrelevantMutation oldBatch sourceRootSlot := by
  change checkSlotDeadlines irrelevantMutation oldBatch sourceRootSlot = true ∧
    checkOwnerPure irrelevantMutation sourceRootSlot = true
  set_option maxRecDepth 100000 in
    decide

structure VersionedController where
  revision : Nat
  lifecycle : LifecycleState Coord Claim Branch Grant Operation

structure GlobalObs where
  controllerRevision : Nat
  deriving DecidableEq

def observeGlobal (S : VersionedController) : GlobalObs :=
  ⟨S.revision⟩

def beforeIrrelevant : VersionedController := ⟨40, source⟩
def afterIrrelevant : VersionedController := ⟨41, irrelevantMutation⟩

theorem global_observation_rejects_irrelevant :
    observeGlobal beforeIrrelevant ≠ observeGlobal afterIrrelevant := by decide

theorem local_observation_ignores_irrelevant :
    observeLocal 17 oldBatch source =
      observeLocal 17 oldBatch irrelevantMutation := by
  apply LocalAuthObs.ext
  · rfl
  · rfl
  · funext k
    fin_cases k
    decide
  · rfl
  · rfl
  · rfl
  · funext c
    fin_cases c <;> decide
  · rfl

/-! ## Proposed semantic dependency -/

def scheduledCoOwner
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (U : Finset Claim) (c c' : Claim) : Bool :=
  if c ∈ U ∧ c' ∈ U then
    match A.auth.status c, A.auth.status c' with
    | .tentative b, .tentative b' => decide (b = b')
    | _, _ => false
  else false

@[ext] structure SemanticObs where
  localView : LocalAuthObs
  rootLineage : Claim → Option Slot
  scheduledOwnerTopology : Claim → Claim → Bool
  deriving DecidableEq

def observeSemantic (offered : Nat) (U : Finset Claim)
    (root : Claim → Option Slot)
    (A : LifecycleState Coord Claim Branch Grant Operation) : SemanticObs where
  localView := observeLocal offered U A
  rootLineage := fun c => if c ∈ U then root c else none
  scheduledOwnerTopology := scheduledCoOwner A U

def sourceSemanticObs : SemanticObs :=
  observeSemantic 17 oldBatch sourceRootSlot source

def mergedSemanticObs : SemanticObs :=
  observeSemantic 17 oldBatch mergedRootSlot merged

def irrelevantSemanticObs : SemanticObs :=
  observeSemantic 17 oldBatch sourceRootSlot irrelevantMutation

theorem semantic_observation_distinguishes_cross_slot :
    sourceSemanticObs ≠ mergedSemanticObs := by
  intro h
  have hfield := congrArg
    (fun o => o.scheduledOwnerTopology Claim.a Claim.c) h
  have hsource :
      sourceSemanticObs.scheduledOwnerTopology Claim.a Claim.c = false := by
    decide
  have hmerged :
      mergedSemanticObs.scheduledOwnerTopology Claim.a Claim.c = true := by
    decide
  change sourceSemanticObs.scheduledOwnerTopology Claim.a Claim.c =
    mergedSemanticObs.scheduledOwnerTopology Claim.a Claim.c at hfield
  rw [hsource, hmerged] at hfield
  contradiction

theorem semantic_observation_ignores_irrelevant :
    sourceSemanticObs = irrelevantSemanticObs := by
  apply SemanticObs.ext
  · exact local_observation_ignores_irrelevant
  · rfl
  · funext c c'
    fin_cases c <;> fin_cases c' <;> decide

theorem observation_separation_suite :
    safeLocalObs = unsafeLocalObs ∧
    sourceSemanticObs ≠ mergedSemanticObs ∧
    observeGlobal beforeIrrelevant ≠ observeGlobal afterIrrelevant ∧
    sourceSemanticObs = irrelevantSemanticObs :=
  ⟨local_observation_indistinguishable,
    semantic_observation_distinguishes_cross_slot,
    global_observation_rejects_irrelevant,
    semantic_observation_ignores_irrelevant⟩

#print axioms actual_cross_slot_merge
#print axioms merged_lwf_ac
#print axioms cross_slot_merge_breaks_plan
#print axioms version_observation_lower_bound
#print axioms irrelevant_mutation_actual_step
#print axioms observation_separation_suite

end AuthorityContinuity.PlanExamples
