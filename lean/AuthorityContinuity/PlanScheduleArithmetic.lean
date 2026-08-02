import Mathlib

/-!
# Arithmetic core for schedule readiness

This module isolates the natural-number argument used by the authority-plan
scheduler.  In particular, the main theorem does not assume a readiness
predicate: it derives the capacity check from the durable-accounting equation,
the phase bound, the per-slot envelope, the requested load, and the deadline.
-/

namespace AuthorityContinuity.PlanScheduleArithmetic

universe uS uC

variable {Slot : Type uS} {Coord : Type uC}

section TotalExposure

variable [Fintype Slot]

/-- Demand made durable in all schedule slots. -/
def totalE (E : Slot -> Coord -> Nat) (k : Coord) : Nat :=
  ∑ s : Slot, E s k

@[simp] theorem totalE_zero (k : Coord) :
    totalE (fun (_ : Slot) (_ : Coord) => 0) k = 0 := by
  simp [totalE]

end TotalExposure

section OrderedSchedule

variable [Fintype Slot] [LinearOrder Slot]

/-- Planned demand in slots strictly preceding `s`. -/
def priorP (P : Slot -> Coord -> Nat) (s : Slot) (k : Coord) : Nat :=
  ∑ t ∈ Finset.univ.filter (fun t : Slot => t < s), P t k

/-- At the current head `s`, all durable exposure in coordinate `k` lies in
completed slots or in `s`.  This is deliberately head-scoped: requiring it for
every slot at once would be stronger than the scheduler needs. -/
def PhaseBound (P E : Slot -> Coord -> Nat) (s : Slot) (k : Coord) : Prop :=
  totalE E k ≤ priorP P s k + E s k

@[simp] theorem priorP_zero (s : Slot) (k : Coord) :
    priorP (fun (_ : Slot) (_ : Coord) => 0) s k = 0 := by
  simp [priorP]

/-- A fresh schedule, with no exposed demand, satisfies the phase bound at
every possible current head. -/
theorem initial_phaseBound (P : Slot -> Coord -> Nat) (s : Slot) (k : Coord) :
    PhaseBound P (fun _ _ => 0) s k := by
  simp [PhaseBound]

/-- A current-head phase bound follows from planned bounds before the head and
zero exposure after it.  Exposure at the head is retained verbatim, so no
bound on `E s k` is needed. -/
theorem phaseBound_of_before_le_and_after_zero
    (P E : Slot -> Coord -> Nat) (s : Slot) (k : Coord)
    (hBefore : ∀ t, t < s -> E t k ≤ P t k)
    (hAfter : ∀ t, s < t -> E t k = 0) :
    PhaseBound P E s k := by
  unfold PhaseBound totalE priorP
  calc
    (∑ t : Slot, E t k) ≤
        ∑ t : Slot, if t < s then P t k else if t = s then E s k else 0 := by
      apply Finset.sum_le_sum
      intro t _
      by_cases hlt : t < s
      · simp [hlt, hBefore t hlt]
      · simp only [hlt, if_false]
        rcases lt_or_eq_of_le (le_of_not_gt hlt) with hgt | rfl
        · simp [hgt.ne', hAfter t hgt]
        · simp
    _ = (∑ t ∈ Finset.univ.filter (fun t : Slot => t < s), P t k) +
          E s k := by
      rw [Finset.sum_ite]
      congr 1
      simp

end OrderedSchedule

/-- Exact residual accounting implies that exposed demand never exceeds the
originally planned demand in a slot. -/
theorem E_le_P_of_partition
    (B E W P : Slot -> Coord -> Nat) (s : Slot) (k : Coord)
    (hPartition : B s k + E s k + W s k = P s k) :
    E s k ≤ P s k := by
  omega

section Readiness

variable [Fintype Slot] [LinearOrder Slot]

/-- Non-circular readiness arithmetic.

The conclusion is the capacity check needed to Prepare `q` units at slot `s`.
It is derived without assuming a readiness predicate, a promoted-load value,
or the conclusion under another name.
-/
theorem durable_add_request_le_cap
    (P E L R : Slot -> Coord -> Nat)
    (d0 durable cap0 cap q : Nat) (s : Slot) (k : Coord)
    (hDurable : durable = d0 + totalE E k)
    (hPhase : totalE E k ≤ priorP P s k + E s k)
    (hEnvelope : L s k + E s k ≤ R s k)
    (hRequest : q ≤ L s k)
    (hDeadline : d0 + priorP P s k + R s k ≤ cap0)
    (hCap : cap = cap0) :
    durable + q ≤ cap := by
  omega

end Readiness

end AuthorityContinuity.PlanScheduleArithmetic
