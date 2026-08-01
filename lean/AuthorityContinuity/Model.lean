import Mathlib.Data.Fintype.Basic
import Mathlib.Algebra.Order.BigOperators.Group.Finset

/-!
# Finite authority-continuity model

This module fixes the finite, typed state on which the executable checker and
the lifecycle development operate.  Claim partitioning is structural: one
total status function assigns every ID exactly one of four disjoint states.
In particular, `terminal` and `unissued` are distinct, so a lifecycle rule can
require freshness without reviving a tombstoned ID.
-/

namespace AuthorityContinuity

universe uC uI uB

/-- The unique ledger location of a claim ID. -/
inductive ClaimStatus (Branch : Type uB) where
  | unissued
  | durable
  | terminal
  | tentative (owner : Branch)
  deriving DecidableEq, Repr

/-- A finite typed authority state.  `allowed` is the durable contract. -/
@[ext]
structure State (Coord : Type uC) (Claim : Type uI) (Branch : Type uB) where
  capacity : Coord → Nat
  demand : Claim → Coord → Nat
  status : Claim → ClaimStatus Branch
  allowed : Finset (Finset Branch)

namespace State

variable {Coord : Type uC} {Claim : Type uI} {Branch : Type uB}
variable [Fintype Claim] [DecidableEq Claim] [DecidableEq Branch]

/-- Exactly the IDs already issued by the controller. -/
def issuedClaims (A : State Coord Claim Branch) : Finset Claim :=
  Finset.univ.filter fun c => A.status c ≠ .unissued

/-- Exactly the claims already made durable (including conservative uncertainty). -/
def durableClaims (A : State Coord Claim Branch) : Finset Claim :=
  Finset.univ.filter fun c => A.status c = .durable

/-- Tentative claims whose owners occur in configuration `C`. -/
def conditionalClaims (A : State Coord Claim Branch) (C : Finset Branch) : Finset Claim :=
  Finset.univ.filter fun c =>
    (match A.status c with
    | .tentative b => decide (b ∈ C)
    | _ => false) = true

/-- Componentwise demand already made durable. -/
def durableLoad (A : State Coord Claim Branch) (k : Coord) : Nat :=
  ∑ c ∈ A.durableClaims, A.demand c k

/-- Componentwise conditional demand contributed by configuration `C`. -/
def conditionalLoad (A : State Coord Claim Branch) (C : Finset Branch)
    (k : Coord) : Nat :=
  ∑ c ∈ A.conditionalClaims C, A.demand c k

/-- A compatibility alias used by the concrete trace layer. -/
abbrev durableDemand := @durableLoad

/-- A compatibility alias used by the concrete trace layer. -/
abbrev conditionalDemand := @conditionalLoad

end State

/-- Well-formed contracts contain the empty configuration, are downward
closed, and support the owner of every tentative claim.  The claim partition
itself needs no proposition: it follows from the single total status field. -/
structure WF {Coord : Type uC} {Claim : Type uI} {Branch : Type uB}
    [Fintype Claim] [DecidableEq Claim] [DecidableEq Branch]
    (A : State Coord Claim Branch) : Prop where
  empty_mem : ∅ ∈ A.allowed
  downward : ∀ ⦃C C' : Finset Branch⦄, C ∈ A.allowed → C' ⊆ C → C' ∈ A.allowed
  supported : ∀ (c : Claim) (b : Branch), A.status c = .tentative b →
    ∃ C ∈ A.allowed, b ∈ C

/-- Authority continuity is the paper's componentwise vector inequality for
every durability configuration. -/
def AC {Coord : Type uC} {Claim : Type uI} {Branch : Type uB}
    [Fintype Claim] [DecidableEq Claim] [DecidableEq Branch]
    (A : State Coord Claim Branch) : Prop :=
  ∀ C ∈ A.allowed, ∀ k,
    A.durableLoad k + A.conditionalLoad C k ≤ A.capacity k

namespace State

variable {Coord : Type uC} {Claim : Type uI} {Branch : Type uB}
variable [Fintype Claim] [DecidableEq Claim] [DecidableEq Branch]

/-- Conditional load is monotone in the selected branch configuration. -/
theorem conditionalLoad_mono (A : State Coord Claim Branch)
    {C C' : Finset Branch} (hCC' : C ⊆ C') (k : Coord) :
    A.conditionalLoad C k ≤ A.conditionalLoad C' k := by
  apply Finset.sum_le_sum_of_subset
  intro c hc
  simp only [conditionalClaims, Finset.mem_filter, Finset.mem_univ, true_and] at hc ⊢
  cases hs : A.status c with
  | unissued => simp [hs] at hc
  | durable => simp [hs] at hc
  | terminal => simp [hs] at hc
  | tentative b =>
      simpa [hs] using hCC' (by simpa [hs] using hc)

/-- Demand of any finite subset of durable claims is bounded by durable load. -/
theorem sum_demand_le_durableLoad (A : State Coord Claim Branch)
    (claims : Finset Claim) (k : Coord)
    (hdurable : ∀ c ∈ claims, A.status c = .durable) :
    ∑ c ∈ claims, A.demand c k ≤ A.durableLoad k := by
  apply Finset.sum_le_sum_of_subset
  intro c hc
  simp only [durableClaims, Finset.mem_filter, Finset.mem_univ, true_and]
  exact hdurable c hc

/-- Combined exact restriction: a tentative claim remains live exactly when
both its owner and its ID are retained.  Every other tentative ID is
terminalized; non-tentative statuses never change. -/
def restrictStateBy (A : State Coord Claim Branch) (S : Finset Branch)
    (keep : Finset Claim) :
    State Coord Claim Branch where
  capacity := A.capacity
  demand := A.demand
  status c :=
    match A.status c with
    | .tentative b => if b ∈ S ∧ c ∈ keep then .tentative b else .terminal
    | s => s
  allowed := A.allowed.filter fun C => C ⊆ S

/-- Exact paper restriction `A ↓ S`: all tentative IDs of retained owners
are kept, and the contract retains exactly old configurations contained in
`S`. -/
def restrictState (A : State Coord Claim Branch) (S : Finset Branch) :
    State Coord Claim Branch :=
  A.restrictStateBy S Finset.univ

@[simp]
theorem mem_restrictStateBy_allowed_iff (A : State Coord Claim Branch)
    (S : Finset Branch) (keep : Finset Claim) (C : Finset Branch) :
    C ∈ (A.restrictStateBy S keep).allowed ↔ C ∈ A.allowed ∧ C ⊆ S := by
  simp [restrictStateBy]

@[simp]
theorem restrictStateBy_status_tentative_iff (A : State Coord Claim Branch)
    (S : Finset Branch) (keep : Finset Claim) (c : Claim) (b : Branch) :
    (A.restrictStateBy S keep).status c = .tentative b ↔
      A.status c = .tentative b ∧ b ∈ S ∧ c ∈ keep := by
  constructor
  · intro h
    cases hs : A.status c with
    | unissued => simp [restrictStateBy, hs] at h
    | durable => simp [restrictStateBy, hs] at h
    | terminal => simp [restrictStateBy, hs] at h
    | tentative owner =>
        by_cases hkeep : owner ∈ S ∧ c ∈ keep
        · have hob : owner = b := by
            simpa [restrictStateBy, hs, hkeep] using h
          subst b
          exact ⟨rfl, hkeep⟩
        · simp [restrictStateBy, hs, hkeep] at h
  · rintro ⟨hstatus, hbS, hckeep⟩
    simp [restrictStateBy, hstatus, hbS, hckeep]

@[simp]
theorem mem_restrictState_allowed_iff (A : State Coord Claim Branch)
    (S C : Finset Branch) :
    C ∈ (A.restrictState S).allowed ↔ C ∈ A.allowed ∧ C ⊆ S := by
  simpa [restrictState] using mem_restrictStateBy_allowed_iff A S Finset.univ C

@[simp]
theorem restrictState_status_tentative_iff (A : State Coord Claim Branch)
    (S : Finset Branch) (c : Claim) (b : Branch) :
    (A.restrictState S).status c = .tentative b ↔
      A.status c = .tentative b ∧ b ∈ S := by
  simpa [restrictState] using
    restrictStateBy_status_tentative_iff A S Finset.univ c b

@[simp]
theorem restrictStateBy_durableLoad (A : State Coord Claim Branch)
    (S : Finset Branch) (keep : Finset Claim) (k : Coord) :
    (A.restrictStateBy S keep).durableLoad k = A.durableLoad k := by
  unfold durableLoad durableClaims
  apply Finset.sum_congr
  · ext c
    cases hs : A.status c with
    | unissued => simp [restrictStateBy, hs]
    | durable => simp [restrictStateBy, hs]
    | terminal => simp [restrictStateBy, hs]
    | tentative b =>
        by_cases hkeep : b ∈ S ∧ c ∈ keep <;>
          simp [restrictStateBy, hs, hkeep]
  · intro c hc
    rfl

/-- Combined restriction can only remove conditional demand. -/
theorem restrictStateBy_conditionalLoad_le (A : State Coord Claim Branch)
    (S : Finset Branch) (keep : Finset Claim) (C : Finset Branch) (k : Coord) :
    (A.restrictStateBy S keep).conditionalLoad C k ≤ A.conditionalLoad C k := by
  unfold conditionalLoad
  apply Finset.sum_le_sum_of_subset
  intro c hc
  simp only [conditionalClaims, Finset.mem_filter, Finset.mem_univ, true_and] at hc ⊢
  cases hs : A.status c with
  | unissued => simp [restrictStateBy, hs] at hc
  | durable => simp [restrictStateBy, hs] at hc
  | terminal => simp [restrictStateBy, hs] at hc
  | tentative b =>
      by_cases hkeep : b ∈ S ∧ c ∈ keep
      · simpa [restrictStateBy, hs, hkeep] using hc
      · simp [restrictStateBy, hs, hkeep] at hc

/-- Combined owner/claim restriction derives target WF and AC.  The target is
computed by `restrictStateBy`; neither target property is assumed. -/
theorem restrictStateBy_preserves_wf_ac (A : State Coord Claim Branch)
    (S : Finset Branch) (keep : Finset Claim) (hWF : WF A) (hAC : AC A) :
    WF (A.restrictStateBy S keep) ∧ AC (A.restrictStateBy S keep) := by
  constructor
  · constructor
    · exact (mem_restrictStateBy_allowed_iff A S keep ∅).2
        ⟨hWF.empty_mem, Finset.empty_subset S⟩
    · intro C C' hC hsub
      rw [mem_restrictStateBy_allowed_iff] at hC ⊢
      exact ⟨hWF.downward hC.1 hsub, hsub.trans hC.2⟩
    · intro c b hstatus
      rw [restrictStateBy_status_tentative_iff] at hstatus
      obtain ⟨C, hC, hbC⟩ := hWF.supported c b hstatus.1
      refine ⟨C ∩ S, ?_, Finset.mem_inter.2 ⟨hbC, hstatus.2.1⟩⟩
      rw [mem_restrictStateBy_allowed_iff]
      exact ⟨hWF.downward hC Finset.inter_subset_left,
        Finset.inter_subset_right⟩
  · intro C hC k
    rw [mem_restrictStateBy_allowed_iff] at hC
    calc
      (A.restrictStateBy S keep).durableLoad k +
          (A.restrictStateBy S keep).conditionalLoad C k
          ≤ A.durableLoad k + A.conditionalLoad C k := by
            rw [restrictStateBy_durableLoad]
            exact Nat.add_le_add_left
              (restrictStateBy_conditionalLoad_le A S keep C k) _
      _ ≤ A.capacity k := hAC C hC.1 k
      _ = (A.restrictStateBy S keep).capacity k := rfl

@[simp]
theorem restrictState_durableLoad (A : State Coord Claim Branch)
    (S : Finset Branch) (k : Coord) :
    (A.restrictState S).durableLoad k = A.durableLoad k := by
  simpa [restrictState] using restrictStateBy_durableLoad A S Finset.univ k

@[simp]
theorem restrictState_conditionalLoad (A : State Coord Claim Branch)
    (S C : Finset Branch) (hCS : C ⊆ S) (k : Coord) :
    (A.restrictState S).conditionalLoad C k = A.conditionalLoad C k := by
  unfold conditionalLoad conditionalClaims
  apply Finset.sum_congr
  · ext c
    cases hs : A.status c with
    | unissued => simp [restrictState, restrictStateBy, hs]
    | durable => simp [restrictState, restrictStateBy, hs]
    | terminal => simp [restrictState, restrictStateBy, hs]
    | tentative b =>
        by_cases hbC : b ∈ C
        · have hbS : b ∈ S := hCS hbC
          simp [restrictState, restrictStateBy, hs, hbC, hbS]
        · by_cases hbS : b ∈ S <;>
            simp [restrictState, restrictStateBy, hs, hbC, hbS]
  · intro c hc
    rfl

/-- Exact restriction derives both target well-formedness and continuity; it
does not take either target property as a premise. -/
theorem restrictState_preserves_wf_ac (A : State Coord Claim Branch)
    (S : Finset Branch) (hWF : WF A) (hAC : AC A) :
    WF (A.restrictState S) ∧ AC (A.restrictState S) := by
  constructor
  · constructor
    · exact (mem_restrictState_allowed_iff A S ∅).2 ⟨hWF.empty_mem, Finset.empty_subset S⟩
    · intro C C' hC hsub
      rw [mem_restrictState_allowed_iff] at hC ⊢
      exact ⟨hWF.downward hC.1 hsub, hsub.trans hC.2⟩
    · intro c b hstatus
      rw [restrictState_status_tentative_iff] at hstatus
      obtain ⟨C, hC, hbC⟩ := hWF.supported c b hstatus.1
      refine ⟨C ∩ S, ?_, Finset.mem_inter.2 ⟨hbC, hstatus.2⟩⟩
      rw [mem_restrictState_allowed_iff]
      exact ⟨hWF.downward hC Finset.inter_subset_left,
        Finset.inter_subset_right⟩
  · intro C hC k
    rw [mem_restrictState_allowed_iff] at hC
    simpa [restrictState_durableLoad, restrictState_conditionalLoad A S C hC.2 k]
      using hAC C hC.1 k

end State

end AuthorityContinuity
