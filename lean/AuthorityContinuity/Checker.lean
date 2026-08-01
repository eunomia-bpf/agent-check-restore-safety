import AuthorityContinuity.Model

/-!
# Executable admission checker and derived topology rules

`checkAC` is deliberately an AC-only checker.  Lifecycle constructors must
derive target well-formedness from their structural premises; a successful
Boolean check is never used as a hidden target-WF certificate.
-/

namespace AuthorityContinuity

universe uC uI uB

variable {Coord : Type uC} {Claim : Type uI} {Branch : Type uB}
variable [Fintype Coord] [Fintype Claim] [Fintype Branch]
variable [DecidableEq Coord] [DecidableEq Claim] [DecidableEq Branch]

/-- Executable universal quantification over an explicitly finite carrier. -/
def finiteAll {α : Type*} (s : Finset α) (p : α → Bool) : Bool :=
  s.fold Bool.and true p

@[simp]
theorem finiteAll_eq_true {α : Type*} (s : Finset α) (p : α → Bool) :
    finiteAll s p = true ↔ ∀ x ∈ s, p x = true := by
  classical
  induction s using Finset.induction_on with
  | empty => simp [finiteAll]
  | @insert a s ha ih =>
      rw [show finiteAll (insert a s) p = (p a && finiteAll s p) by
        simp [finiteAll, Finset.fold_insert, ha]]
      simp [ih, ha]

/-- Executable exhaustive check of the vector AC inequalities over the finite
contract and finite coordinate space. -/
def checkAC (A : State Coord Claim Branch) : Bool :=
  finiteAll A.allowed fun C =>
    finiteAll Finset.univ fun k =>
      decide (A.durableLoad k + A.conditionalLoad C k ≤ A.capacity k)

/-- A successful finite check is a proof of authority continuity. -/
theorem checkAC_sound (A : State Coord Claim Branch)
    (hcheck : checkAC A = true) : AC A := by
  intro C hC k
  have hCcheck := (finiteAll_eq_true A.allowed _).mp hcheck C hC
  have hk := (finiteAll_eq_true Finset.univ _).mp hCcheck k (Finset.mem_univ k)
  exact of_decide_eq_true hk

/-- Durable load immediately after promoting all IDs in `U`. -/
def promotedLoad (A : State Coord Claim Branch) (U : Finset Claim)
    (k : Coord) : Nat :=
  A.durableLoad k + ∑ c ∈ U, A.demand c k

/-- Conditional load remaining after the same IDs leave tentative bundles. -/
def remainingConditionalLoad (A : State Coord Claim Branch) (U : Finset Claim)
    (C : Finset Branch) (k : Coord) : Nat :=
  ∑ c ∈ A.conditionalClaims C \ U, A.demand c k

/-- The exact frozen Prepare guard, represented extensionally as a finite
filter of the old contract. -/
def guardedAllowed (A : State Coord Claim Branch) (U : Finset Claim) :
    Finset (Finset Branch) :=
  A.allowed.filter fun C =>
    finiteAll Finset.univ fun k =>
      decide (promotedLoad A U k + remainingConditionalLoad A U C k ≤
        A.capacity k)

/-- Exact Prepare guard closure: membership is old membership conjoined with
the promoted vector-load inequality, in both directions. -/
theorem guardClosure_iff (A : State Coord Claim Branch) (U : Finset Claim)
    (C : Finset Branch) :
    C ∈ guardedAllowed A U ↔
      C ∈ A.allowed ∧ ∀ k,
        promotedLoad A U k + remainingConditionalLoad A U C k ≤ A.capacity k := by
  simp [guardedAllowed]

/-- A simulation-certified topology change derives target AC from source AC,
configuration projection, load nonincrease, and preservation of issued
capacity.  Target AC is not a premise. -/
theorem simulation_preserves_ac
    (source target : State Coord Claim Branch)
    (project : Finset Branch → Finset Branch)
    (hcapacity : target.capacity = source.capacity)
    (hsource : AC source)
    (hsim : ∀ C' ∈ target.allowed,
      project C' ∈ source.allowed ∧
      ∀ k,
        target.durableLoad k + target.conditionalLoad C' k ≤
          source.durableLoad k + source.conditionalLoad (project C') k) :
    AC target := by
  intro C' hC' k
  have h := hsim C' hC'
  calc
    target.durableLoad k + target.conditionalLoad C' k
        ≤ source.durableLoad k + source.conditionalLoad (project C') k := h.2 k
    _ ≤ source.capacity k := hsource (project C') h.1 k
    _ = target.capacity k := by rw [hcapacity]

/-- Root-namespace paper-facing name for exact contract restriction. -/
theorem restriction_preserves_wf_ac
    (A : State Coord Claim Branch) (S : Finset Branch) (keep : Finset Claim)
    (hWF : WF A) (hAC : AC A) :
    WF (A.restrictStateBy S keep) ∧ AC (A.restrictStateBy S keep) :=
  State.restrictStateBy_preserves_wf_ac A S keep hWF hAC

end AuthorityContinuity
