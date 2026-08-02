import AuthorityContinuity.PlanInvariant

/-!
# Complete source-to-target preservation for computed group Prepare

`PlanInvariant` proves the arithmetic, load, and cursor preservation lemmas.
This module closes the remaining structural fields and reconstructs the whole
target `Valid` certificate.  The target is the executable `prepareState` paired
with the computed `afterPrepareGroup`; target validity is never a premise.
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

/-- Filtering through the exact Prepare target preserves the immutable source
root witness of every surviving leaf. -/
theorem afterPrepareGroup_preserves_remaining_rooted
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    (hv : p.Valid A) (assignment : Operation -> Option Claim) :
    ∀ c ∈ (p.afterPrepareGroup A assignment).remaining,
      ∃ b s,
        (prepareState A (p.headGroup A) assignment).auth.status c =
            .tentative b ∧
          s ∈ (p.afterPrepareGroup A assignment).slots ∧
          (p.afterPrepareGroup A assignment).rootSlot c = some s := by
  intro c hc
  have hfilter : c ∈ p.remaining ∧
      ∃ b, (prepareState A (p.headGroup A) assignment).auth.status c =
        .tentative b := by
    simpa [afterPrepareGroup] using hc
  obtain ⟨b, hb⟩ := hfilter.2
  obtain ⟨_, s, _, hs, hroot⟩ := hv.remaining_rooted c hfilter.1
  exact ⟨b, s, hb, by simpa [afterPrepareGroup] using hs,
    by simpa [afterPrepareGroup] using hroot⟩

/-- Prepare never invents an owner or changes a root, so source owner purity
implies target owner purity. -/
theorem afterPrepareGroup_preserves_owner_root_pure
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    (hv : p.Valid A) (assignment : Operation -> Option Claim) :
    ∀ c c' b,
      (prepareState A (p.headGroup A) assignment).auth.status c =
          .tentative b ->
      (prepareState A (p.headGroup A) assignment).auth.status c' =
          .tentative b ->
      (p.afterPrepareGroup A assignment).rootSlot c =
        (p.afterPrepareGroup A assignment).rootSlot c' := by
  intro c c' b hc hc'
  have hs := prepareState_tentative_source_not_head
    (p := p) assignment hc
  have hs' := prepareState_tentative_source_not_head
    (p := p) assignment hc'
  simpa [afterPrepareGroup] using
    hv.owner_root_pure c c' b hs.1 hs'.1

/-- Exposure remains zero outside the fixed schedule because the only modified
row is the source head, which is itself a declared slot. -/
theorem afterPrepareGroup_preserves_E_outside_zero
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    (hv : p.Valid A) (hrem : p.remaining.Nonempty)
    (assignment : Operation -> Option Claim) :
    ∀ t, t ∉ (p.afterPrepareGroup A assignment).slots -> ∀ k,
      (p.afterPrepareGroup A assignment).E t k = 0 := by
  obtain ⟨g, hg⟩ := firstGroup_exists_of_remaining hv hrem
  rcases g with ⟨s, b⟩
  have hs : s ∈ p.slots := firstGroup_slot_mem hv hg
  intro t ht k
  have htSource : t ∉ p.slots := by
    simpa [afterPrepareGroup] using ht
  have hts : t ≠ s := by
    intro h
    exact htSource (h ▸ hs)
  rw [afterPrepareGroup_E_of_firstGroup assignment hg]
  simp [hts, hv.E_outside_zero t htSource k]

/-- Every field of the target certificate is reconstructed from the source
certificate and the executable Prepare target. -/
theorem afterPrepareGroup_target_valid
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    (hv : p.Valid A) (hrem : p.remaining.Nonempty)
    (assignment : Operation -> Option Claim) :
    (p.afterPrepareGroup A assignment).Valid
      (prepareState A (p.headGroup A) assignment) := by
  refine {
    capacity_eq := ?_
    remaining_rooted := afterPrepareGroup_preserves_remaining_rooted hv assignment
    owner_root_pure := afterPrepareGroup_preserves_owner_root_pure hv assignment
    root_mem := ?_
    E_outside_zero := afterPrepareGroup_preserves_E_outside_zero hv hrem assignment
    P_outside_zero := ?_
    durable_eq := afterPrepareGroup_preserves_durableEq hv hrem assignment
    envelope := afterPrepareGroup_preserves_envelope hv hrem assignment
    deadline := ?_
    batch_bound := afterPrepareGroup_preserves_batchBound hv hrem assignment
    cursor_phase := afterPrepareGroup_preserves_cursorPhase hv hrem assignment }
  · intro k
    change A.auth.capacity k = p.cap0 k
    exact hv.capacity_eq k
  · intro c s hroot
    apply hv.root_mem c s
    simpa [afterPrepareGroup] using hroot
  · intro s hs k
    exact hv.P_outside_zero s (by simpa [afterPrepareGroup] using hs) k
  · intro s hs k
    exact hv.deadline s (by simpa [afterPrepareGroup] using hs) k

/-- The derived head-phase theorem is available again after cursor
recomputation; it remains derived state rather than a certificate field. -/
theorem afterPrepareGroup_preserves_headPhaseBound
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    (hv : p.Valid A) (hrem : p.remaining.Nonempty)
    (assignment : Operation -> Option Claim) :
    (p.afterPrepareGroup A assignment).HeadPhaseBound
      (prepareState A (p.headGroup A) assignment) :=
  (afterPrepareGroup_target_valid hv hrem assignment).derived_head_phase_bound

/-- End-to-end Prepare gate: the executable assignment checker constructs the
actual lifecycle step, and that same computed target preserves lifecycle
well-formedness, authority continuity, exact branch activity, and the complete
plan certificate. -/
theorem current_group_prepare_preserves_all
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    (hWF : A.LWF) (hAC : AC A.auth) (hActive : ActiveExact A)
    (hv : p.Valid A) (hrem : p.remaining.Nonempty)
    (assignment : Operation -> Option Claim)
    (hAssignment :
      Plan.checkAssignment A (p.headGroup A) assignment = true) :
    let A' := prepareState A (p.headGroup A) assignment
    A'.LWF ∧ AC A'.auth ∧ ActiveExact A' ∧
      (p.afterPrepareGroup A assignment).Valid A' ∧ Step A .tau A' := by
  dsimp
  have hOK := current_group_prepare_ok hWF hv hrem assignment hAssignment
  have hCore := prepare_preserves_wf_ac A (p.headGroup A) assignment
    hWF hAC hOK
  have hActive' := prepare_preserves_active_exact A (p.headGroup A) assignment
    hWF hActive hOK
  exact ⟨hCore.1, hCore.2, hActive',
    afterPrepareGroup_target_valid hv hrem assignment,
    current_group_actual_step hWF hv hrem assignment hAssignment⟩

#print axioms afterPrepareGroup_target_valid
#print axioms afterPrepareGroup_preserves_headPhaseBound
#print axioms current_group_prepare_preserves_all

end PlanData

end AuthorityContinuity.PlanInvariant
