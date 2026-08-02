import AuthorityContinuity.PlanInvariant

/-!
# Deriving the current-head phase bound

This module shows that the head-scoped exposure bound is not independent
controller state.  It follows from the executable cursor, the per-slot batch
bound, and the fact that exposure outside the declared schedule is zero.
-/

namespace AuthorityContinuity.PlanInvariant

open AuthorityContinuity LifecycleState

universe uC uI uB uG uO uS

variable {Coord : Type uC} {Claim : Type uI} {Branch : Type uB}
variable {Grant : Type uG} {Operation : Type uO} {Slot : Type uS}
variable [Fintype Coord] [DecidableEq Coord]
variable [Fintype Claim] [LinearOrder Claim]
variable [Fintype Branch] [LinearOrder Branch]
variable [DecidableEq Grant] [Fintype Operation] [DecidableEq Operation]
variable [Fintype Slot] [LinearOrder Slot]

namespace PlanData

/-- At the executable head, all exposure is either from an earlier slot or
the head itself.  Earlier exposure is bounded by planned demand; later and
out-of-schedule exposure is zero.  In particular, `HeadPhaseBound` need not be
stored as an independent field of `Valid`.

Neither `root_mem` nor `P_outside_zero` is required.  The current slot's
exposure occurs verbatim on the right-hand side, while nonzero planned demand
outside the declared schedule can only make that side larger. -/
theorem head_phase_bound_of_structural
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    (hEOutside : ∀ t, t ∉ p.slots → ∀ k, p.E t k = 0)
    (hBatch : p.BatchBound A)
    (hCursor : p.CursorPhase A) :
    p.HeadPhaseBound A := by
  intro s b hHead k
  unfold PlanScheduleArithmetic.PhaseBound PlanScheduleArithmetic.totalE
    PlanScheduleArithmetic.priorP
  calc
    (∑ t : Slot, p.E t k) ≤
        ∑ t : Slot, if t < s then p.P t k else if t = s then p.E s k else 0 := by
      apply Finset.sum_le_sum
      intro t ht
      by_cases hlt : t < s
      · simp only [hlt, if_true]
        by_cases htSlots : t ∈ p.slots
        · have hBound := hBatch t htSlots k
          omega
        · simp [hEOutside t htSlots k]
      · simp only [hlt, if_false]
        rcases lt_or_eq_of_le (le_of_not_gt hlt) with hgt | rfl
        · have hZero : p.E t k = 0 := by
            by_cases htSlots : t ∈ p.slots
            · exact hCursor s b hHead t htSlots hgt k
            · exact hEOutside t htSlots k
          simp [hgt.ne', hZero]
        · simp
    _ = (∑ t ∈ Finset.univ.filter (fun t : Slot => t < s), p.P t k) +
          p.E s k := by
      rw [Finset.sum_ite]
      congr 1
      · simp

#print axioms head_phase_bound_of_structural

end PlanData

end AuthorityContinuity.PlanInvariant
