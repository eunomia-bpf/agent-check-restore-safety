import AuthorityContinuity.Plan
import AuthorityContinuity.PlanScheduleArithmetic
import Mathlib.Data.Finset.Max
import Mathlib.Data.Fintype.Prod
import Mathlib.Data.Prod.Lex

/-!
# Multi-slot authority-plan invariant

This module closes the first multi-Prepare vertical gate without accepting a
per-edge target-validity or readiness oracle.  `PlanValid` is an invariant of
the source controller.  The current slot and owner group are executable
functions of the real lifecycle plus the remaining batch.
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

/-- Raw durable controller data.  `rootSlot` covers the whole claim namespace;
unrelated owners may remain in the `none` lineage.  The fixed batch is the
separate `remaining` set. -/
structure PlanData where
  version : Nat
  d0 : Coord -> Nat
  cap0 : Coord -> Nat
  slots : Finset Slot
  rootSlot : Claim -> Option Slot
  remaining : Finset Claim
  R : Slot -> Coord -> Nat
  P : Slot -> Coord -> Nat
  E : Slot -> Coord -> Nat

namespace PlanData

/-- Executable compare-and-swap check for the durable plan head. -/
def checkVersion
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (offered : Nat) : Bool := decide (offered = p.version)

theorem checkVersion_sound
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (offered : Nat) (h : p.checkVersion offered = true) :
    offered = p.version := by
  exact of_decide_eq_true (by simpa [checkVersion] using h)

def rootRemaining
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (s : Slot) : Finset Claim :=
  p.remaining.filter fun c => p.rootSlot c = some s

def ownerGroup
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (s : Slot) (b : Branch) : Finset Claim :=
  p.rootRemaining s |>.filter fun c => A.auth.status c = .tentative b

def activeGroups
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)) :
    Finset (Slot ×ₗ Branch) :=
  Finset.univ.filter fun sb =>
    (p.ownerGroup A (ofLex sb).1 (ofLex sb).2).Nonempty

/-- Lexicographically first nonempty `(slot, owner)` group. -/
def firstGroup
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)) :
    Option (Slot × Branch) :=
  if h : (p.activeGroups A).Nonempty then
    some (ofLex ((p.activeGroups A).min' h))
  else none

def cursor
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)) :
    Option Slot := (p.firstGroup A).map Prod.fst

def headGroup
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)) :
    Finset Claim :=
  match p.firstGroup A with
  | none => ∅
  | some (s, b) => p.ownerGroup A s b

def tentativeRootClaims
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (s : Slot) : Finset Claim :=
  Finset.univ.filter fun c =>
    p.rootSlot c = some s ∧ ∃ b, A.auth.status c = .tentative b

/-- All actual live tentative load in a slot, including non-batch claims. -/
def L
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (s : Slot) (k : Coord) : Nat :=
  ∑ c ∈ p.tentativeRootClaims A s, A.auth.demand c k

/-- Remaining selected-batch load. -/
def B
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (s : Slot) (k : Coord) : Nat :=
  Plan.batchLoad A (p.rootRemaining s) k

def totalE
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (k : Coord) : Nat :=
  PlanScheduleArithmetic.totalE p.E k

def priorP
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (s : Slot) (k : Coord) : Nat :=
  PlanScheduleArithmetic.priorP p.P s k

def DurableEq
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)) : Prop :=
  ∀ k, A.auth.durableLoad k = p.d0 k + p.totalE k

def Envelope
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)) : Prop :=
  ∀ s ∈ p.slots, ∀ k, p.L A s k + p.E s k <= p.R s k

def Deadline
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)) : Prop :=
  ∀ s ∈ p.slots, ∀ k,
    p.d0 k + p.priorP s k + p.R s k <= p.cap0 k

/-- The inequality needed from exact `B+E+W=P` accounting.  The complete plan
implies it, and this first vertical gate preserves it directly. -/
def BatchBound
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)) : Prop :=
  ∀ s ∈ p.slots, ∀ k, p.B A s k + p.E s k <= p.P s k

/-- No later slot has been Prepared.  The cursor itself is computed from the
first nonempty owner group, so it cannot be restored from a workspace image. -/
def CursorPhase
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)) : Prop :=
  ∀ s b, p.firstGroup A = some (s, b) ->
    ∀ t ∈ p.slots, s < t -> ∀ k, p.E t k = 0

def HeadPhaseBound
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)) : Prop :=
  ∀ s b, p.firstGroup A = some (s, b) -> ∀ k,
    PlanScheduleArithmetic.PhaseBound p.P p.E s k

/-- Complete source invariant used by the Prepare simulation. -/
structure Valid
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)) : Prop where
  capacity_eq : ∀ k, A.auth.capacity k = p.cap0 k
  remaining_rooted : ∀ c ∈ p.remaining,
    ∃ b s, A.auth.status c = .tentative b ∧
      s ∈ p.slots ∧ p.rootSlot c = some s
  owner_root_pure : ∀ c c' b,
    A.auth.status c = .tentative b ->
    A.auth.status c' = .tentative b ->
    p.rootSlot c = p.rootSlot c'
  root_mem : ∀ c s, p.rootSlot c = some s -> s ∈ p.slots
  E_outside_zero : ∀ s, s ∉ p.slots -> ∀ k, p.E s k = 0
  P_outside_zero : ∀ s, s ∉ p.slots -> ∀ k, p.P s k = 0
  durable_eq : p.DurableEq A
  envelope : p.Envelope A
  deadline : p.Deadline
  batch_bound : p.BatchBound A
  cursor_phase : p.CursorPhase A

/-- `HeadPhaseBound` is derived state, not an accepted plan certificate.  A
slot before the executable head has `E <= P` by `BatchBound`; a slot after the
head has zero exposure by `CursorPhase`; and exposure outside the declared
schedule is zero. -/
theorem Valid.derived_head_phase_bound
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    (hv : p.Valid A) : p.HeadPhaseBound A := by
  intro s b hHead k
  apply PlanScheduleArithmetic.phaseBound_of_before_le_and_after_zero
  · intro t hlt
    by_cases ht : t ∈ p.slots
    · have hBound := hv.batch_bound t ht k
      omega
    · simp [hv.E_outside_zero t ht k]
  · intro t hgt
    by_cases ht : t ∈ p.slots
    · exact hv.cursor_phase s b hHead t ht hgt k
    · exact hv.E_outside_zero t ht k

/-- Computed target plan of the current owner-group Prepare.  Cleanup is read
from the exact `prepareState`: only leaves still tentative there remain in the
batch.  The cursor is not a field and is therefore recomputed by `firstGroup`
from this target. -/
def afterPrepareGroup
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (assignment : Operation -> Option Claim) :
    PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot) :=
  let U := p.headGroup A
  let A' := prepareState A U assignment
  let E' :=
    match p.firstGroup A with
    | none => p.E
    | some (s, _) => fun t k =>
        if t = s then p.E t k + Plan.batchLoad A U k else p.E t k
  { p with
    version := p.version + 1
    remaining := p.remaining.filter fun c =>
      ∃ b, A'.auth.status c = .tentative b
    E := E' }

@[simp] theorem afterPrepareGroup_E_of_firstGroup
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    (assignment : Operation -> Option Claim)
    {s : Slot} {b : Branch} (h : p.firstGroup A = some (s, b))
    (t : Slot) (k : Coord) :
    (p.afterPrepareGroup A assignment).E t k =
      if t = s then p.E t k + Plan.batchLoad A (p.headGroup A) k
      else p.E t k := by
  simp [afterPrepareGroup, h]

theorem afterPrepareGroup_totalE
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    (assignment : Operation -> Option Claim)
    {s : Slot} {b : Branch} (h : p.firstGroup A = some (s, b))
    (k : Coord) :
    (p.afterPrepareGroup A assignment).totalE k =
      p.totalE k + Plan.batchLoad A (p.headGroup A) k := by
  classical
  simp only [totalE, PlanScheduleArithmetic.totalE,
    afterPrepareGroup_E_of_firstGroup assignment h]
  let q := Plan.batchLoad A (p.headGroup A) k
  calc
    (∑ x : Slot, if x = s then p.E x k + q else p.E x k) =
        ∑ x : Slot, (p.E x k + if x = s then q else 0) := by
      apply Finset.sum_congr rfl
      intro x _
      by_cases hxs : x = s <;> simp [hxs]
    _ = (∑ x : Slot, p.E x k) + (∑ x : Slot, if x = s then q else 0) := by
      exact Finset.sum_add_distrib
    _ = (∑ x : Slot, p.E x k) + q := by simp

theorem firstGroup_mem
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    {g : Slot × Branch} (h : p.firstGroup A = some g) :
    toLex g ∈ p.activeGroups A := by
  unfold firstGroup at h
  split at h
  next hne =>
    injection h with hg
    subst g
    simpa using Finset.min'_mem (p.activeGroups A) hne
  next => simp at h

theorem firstGroup_exists_of_remaining
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    (hv : p.Valid A) (hrem : p.remaining.Nonempty) :
    ∃ g, p.firstGroup A = some g := by
  obtain ⟨c, hc⟩ := hrem
  obtain ⟨b, s, hb, hs, hroot⟩ := hv.remaining_rooted c hc
  have hgroup : (p.ownerGroup A s b).Nonempty := by
    refine ⟨c, ?_⟩
    simp [ownerGroup, rootRemaining, hc, hroot, hb]
  have hactive : (p.activeGroups A).Nonempty := by
    refine ⟨toLex (s, b), ?_⟩
    simp [activeGroups, hgroup]
  unfold firstGroup
  simp [hactive]

theorem headGroup_nonempty_of_firstGroup
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    {s : Slot} {b : Branch} (h : p.firstGroup A = some (s, b)) :
    (p.headGroup A).Nonempty := by
  have hm := firstGroup_mem h
  have hg : (p.ownerGroup A s b).Nonempty := by
    simpa [activeGroups] using hm
  simpa [headGroup, h] using hg

theorem firstGroup_slot_mem
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    (hv : p.Valid A) {s : Slot} {b : Branch}
    (h : p.firstGroup A = some (s, b)) : s ∈ p.slots := by
  obtain ⟨c, hc⟩ := headGroup_nonempty_of_firstGroup h
  have hc' : c ∈ p.ownerGroup A s b := by
    simpa [headGroup, h] using hc
  have hroot : p.rootSlot c = some s := by
    simp only [ownerGroup, rootRemaining, Finset.mem_filter] at hc'
    exact hc'.1.2
  exact hv.root_mem c s hroot

theorem headGroup_subset_tentativeRootClaims
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    {s : Slot} {b : Branch} (h : p.firstGroup A = some (s, b)) :
    p.headGroup A ⊆ p.tentativeRootClaims A s := by
  intro c hc
  have hc' : c ∈ p.ownerGroup A s b := by
    simpa [headGroup, h] using hc
  simp only [ownerGroup, rootRemaining, Finset.mem_filter] at hc'
  exact Finset.mem_filter.mpr ⟨Finset.mem_univ c,
    hc'.1.2, ⟨b, hc'.2⟩⟩

theorem headGroup_load_le_L
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    {s : Slot} {b : Branch} (h : p.firstGroup A = some (s, b))
    (k : Coord) :
    Plan.batchLoad A (p.headGroup A) k <= p.L A s k := by
  unfold Plan.batchLoad L
  exact Finset.sum_le_sum_of_subset (headGroup_subset_tentativeRootClaims h)

/-- The actual capacity guard for the current group is a consequence of the
preserved schedule invariant.  No request bound or readiness proposition is an
argument. -/
theorem current_group_promotedLoad_le_capacity
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    (hv : p.Valid A) (hrem : p.remaining.Nonempty) (k : Coord) :
    promotedLoad A.auth (p.headGroup A) k <= A.auth.capacity k := by
  obtain ⟨g, hg⟩ := firstGroup_exists_of_remaining hv hrem
  rcases g with ⟨s, b⟩
  have hs : s ∈ p.slots := firstGroup_slot_mem hv hg
  have hrequest := headGroup_load_le_L hg k
  have hready := PlanScheduleArithmetic.durable_add_request_le_cap
    p.P p.E (fun s k => p.L A s k) p.R
    (p.d0 k) (A.auth.durableLoad k) (p.cap0 k) (A.auth.capacity k)
    (Plan.batchLoad A (p.headGroup A) k) s k
    (hv.durable_eq k) (hv.derived_head_phase_bound s b hg k)
    (hv.envelope s hs k) hrequest (hv.deadline s hs k)
    (hv.capacity_eq k)
  exact hready

theorem headGroup_member_tentative
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    {c : Claim} (hc : c ∈ p.headGroup A) :
    ∃ b, A.auth.status c = .tentative b := by
  unfold headGroup at hc
  cases hfg : p.firstGroup A with
  | none => simp [hfg] at hc
  | some g =>
    rcases g with ⟨s, b⟩
    have hc' : c ∈ p.ownerGroup A s b := by
      simpa [hfg] using hc
    exact ⟨b, (Finset.mem_filter.mp hc').2⟩

/-- Exact durable-load delta of the repository's real `prepareState` for the
computed head group.  Owner cleanup does not alter the newly durable row. -/
theorem prepareState_headGroup_durableLoad
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    (assignment : Operation -> Option Claim) (k : Coord) :
    (prepareState A (p.headGroup A) assignment).auth.durableLoad k =
      A.auth.durableLoad k + Plan.batchLoad A (p.headGroup A) k := by
  rw [show (prepareState A (p.headGroup A) assignment).auth =
      preparedCore A.auth (p.headGroup A) from rfl]
  rw [preparedCore_durableLoad,
    rawPromotion_durableLoad_eq_promotedLoad A.auth (p.headGroup A)
      (fun c hc => headGroup_member_tentative hc) k]
  rfl

theorem prepareState_tentative_source_not_head
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    (assignment : Operation -> Option Claim) {c : Claim} {b : Branch}
    (h : (prepareState A (p.headGroup A) assignment).auth.status c =
      .tentative b) :
    A.auth.status c = .tentative b ∧ c ∉ p.headGroup A := by
  change preparedStatus A.auth (p.headGroup A) c = .tentative b at h
  rw [preparedStatus_tentative_iff,
    rawPromotion_status_tentative_iff] at h
  exact h.1

/-- Every tentative claim after the real Prepare was already tentative in the
same root slot and was not part of the promoted owner group. -/
theorem afterPrepareGroup_tentativeRootClaims_subset_sdiff
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    (assignment : Operation -> Option Claim) (t : Slot) :
    (p.afterPrepareGroup A assignment).tentativeRootClaims
        (prepareState A (p.headGroup A) assignment) t ⊆
      p.tentativeRootClaims A t \ p.headGroup A := by
  intro c hc
  simp only [tentativeRootClaims, Finset.mem_filter, Finset.mem_univ,
    Finset.mem_sdiff, true_and] at hc ⊢
  rcases hc with ⟨hroot, b, hstatus⟩
  have hs := prepareState_tentative_source_not_head assignment hstatus
  exact ⟨⟨by simpa [afterPrepareGroup] using hroot, ⟨b, hs.1⟩⟩, hs.2⟩

/-- `firstGroup` is no greater than any active group. -/
theorem firstGroup_le_active
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    {g : Slot × Branch} (h : p.firstGroup A = some g)
    {x : Slot ×ₗ Branch} (hx : x ∈ p.activeGroups A) :
    toLex g <= x := by
  unfold firstGroup at h
  split at h
  next hne =>
    injection h with hg
    subst g
    simpa using Finset.min'_le (p.activeGroups A) x hx
  next => simp at h

/-- Cleanup and promotion can only remove active remaining owner groups. -/
theorem afterPrepareGroup_activeGroups_subset
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    (assignment : Operation -> Option Claim) :
    (p.afterPrepareGroup A assignment).activeGroups
        (prepareState A (p.headGroup A) assignment) ⊆
      p.activeGroups A := by
  intro sb hsb
  simp only [activeGroups, Finset.mem_filter, Finset.mem_univ,
    true_and] at hsb ⊢
  obtain ⟨c, hc⟩ := hsb
  simp only [ownerGroup, rootRemaining, Finset.mem_filter] at hc
  have hsource := prepareState_tentative_source_not_head assignment hc.2
  refine ⟨c, ?_⟩
  simp only [ownerGroup, rootRemaining, Finset.mem_filter]
  refine ⟨⟨?_, ?_⟩, hsource.1⟩
  · have hcRemaining := hc.1.1
    simpa [afterPrepareGroup] using (Finset.mem_filter.mp hcRemaining).1
  · simpa [afterPrepareGroup] using hc.1.2

/-- Recomputing the cursor after Prepare never moves it to an earlier slot. -/
theorem afterPrepareGroup_firstSlot_mono
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    (assignment : Operation -> Option Claim)
    {s t : Slot} {b b' : Branch}
    (hSource : p.firstGroup A = some (s, b))
    (hTarget : (p.afterPrepareGroup A assignment).firstGroup
      (prepareState A (p.headGroup A) assignment) = some (t, b')) :
    s <= t := by
  have hTargetMem := firstGroup_mem hTarget
  have hSourceMem := afterPrepareGroup_activeGroups_subset assignment hTargetMem
  have hLex := firstGroup_le_active hSource hSourceMem
  simpa using Prod.Lex.monotone_fst (toLex (s, b)) (toLex (t, b')) hLex

theorem afterPrepareGroup_L_le
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    (assignment : Operation -> Option Claim) (t : Slot) (k : Coord) :
    (p.afterPrepareGroup A assignment).L
        (prepareState A (p.headGroup A) assignment) t k <= p.L A t k := by
  unfold L
  change
    (∑ c ∈ (p.afterPrepareGroup A assignment).tentativeRootClaims
        (prepareState A (p.headGroup A) assignment) t,
      A.auth.demand c k) <=
    ∑ c ∈ p.tentativeRootClaims A t, A.auth.demand c k
  exact Finset.sum_le_sum_of_subset
    ((afterPrepareGroup_tentativeRootClaims_subset_sdiff assignment t).trans
      Finset.sdiff_subset)

/-- The post-Prepare remaining batch is the old batch minus at least the
promoted head group (and possibly additional claims removed by cleanup). -/
theorem afterPrepareGroup_rootRemaining_subset_sdiff
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    (assignment : Operation -> Option Claim) (t : Slot) :
    (p.afterPrepareGroup A assignment).rootRemaining t ⊆
      p.rootRemaining t \ p.headGroup A := by
  intro c hc
  simp only [rootRemaining, Finset.mem_filter, Finset.mem_sdiff] at hc ⊢
  have hcRemaining : c ∈ p.remaining ∧
      ∃ b, (prepareState A (p.headGroup A) assignment).auth.status c =
        .tentative b := by
    simpa [afterPrepareGroup] using hc.1
  obtain ⟨b, hstatus⟩ := hcRemaining.2
  have hsource := prepareState_tentative_source_not_head assignment hstatus
  exact ⟨⟨hcRemaining.1, by simpa [afterPrepareGroup] using hc.2⟩,
    hsource.2⟩

theorem afterPrepareGroup_B_le
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    (assignment : Operation -> Option Claim) (t : Slot) (k : Coord) :
    (p.afterPrepareGroup A assignment).B
        (prepareState A (p.headGroup A) assignment) t k <= p.B A t k := by
  unfold B Plan.batchLoad
  change
    (∑ c ∈ (p.afterPrepareGroup A assignment).rootRemaining t,
      A.auth.demand c k) <=
    ∑ c ∈ p.rootRemaining t, A.auth.demand c k
  exact Finset.sum_le_sum_of_subset
    ((afterPrepareGroup_rootRemaining_subset_sdiff assignment t).trans
      Finset.sdiff_subset)

theorem headGroup_subset_rootRemaining
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    {s : Slot} {b : Branch} (h : p.firstGroup A = some (s, b)) :
    p.headGroup A ⊆ p.rootRemaining s := by
  intro c hc
  have hc' : c ∈ p.ownerGroup A s b := by
    simpa [headGroup, h] using hc
  exact (Finset.mem_filter.mp hc').1

theorem afterPrepareGroup_B_add_batchLoad_le
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    (assignment : Operation -> Option Claim)
    {s : Slot} {b : Branch} (h : p.firstGroup A = some (s, b))
    (k : Coord) :
    (p.afterPrepareGroup A assignment).B
        (prepareState A (p.headGroup A) assignment) s k +
      Plan.batchLoad A (p.headGroup A) k <= p.B A s k := by
  have hTarget :
      (∑ c ∈ (p.afterPrepareGroup A assignment).rootRemaining s,
        A.auth.demand c k) <=
      ∑ c ∈ p.rootRemaining s \ p.headGroup A,
        A.auth.demand c k :=
    Finset.sum_le_sum_of_subset
      (afterPrepareGroup_rootRemaining_subset_sdiff
        (A := A) (p := p) assignment s)
  have hHead := headGroup_subset_rootRemaining h
  unfold B Plan.batchLoad at *
  change
    (∑ c ∈ (p.afterPrepareGroup A assignment).rootRemaining s,
      A.auth.demand c k) +
      (∑ c ∈ p.headGroup A, A.auth.demand c k) <=
    ∑ c ∈ p.rootRemaining s, A.auth.demand c k
  calc
    _ <= (∑ c ∈ p.rootRemaining s \ p.headGroup A,
        A.auth.demand c k) +
        (∑ c ∈ p.headGroup A, A.auth.demand c k) :=
      Nat.add_le_add_right hTarget _
    _ = _ := by rw [Finset.sum_sdiff hHead]

theorem afterPrepareGroup_preserves_batchBound
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    (hv : p.Valid A) (hrem : p.remaining.Nonempty)
    (assignment : Operation -> Option Claim) :
    (p.afterPrepareGroup A assignment).BatchBound
      (prepareState A (p.headGroup A) assignment) := by
  obtain ⟨g, hg⟩ := firstGroup_exists_of_remaining hv hrem
  rcases g with ⟨s, b⟩
  intro t ht k
  have hOld := hv.batch_bound t (by simpa [afterPrepareGroup] using ht) k
  by_cases hts : t = s
  · subst t
    have hBatch := afterPrepareGroup_B_add_batchLoad_le assignment hg k
    rw [afterPrepareGroup_E_of_firstGroup assignment hg]
    simp only [ite_true]
    change
      (p.afterPrepareGroup A assignment).B
          (prepareState A (p.headGroup A) assignment) s k +
          (p.E s k + Plan.batchLoad A (p.headGroup A) k) <= p.P s k
    omega
  · have hBatch := afterPrepareGroup_B_le
      (A := A) (p := p) assignment t k
    rw [afterPrepareGroup_E_of_firstGroup assignment hg]
    simp only [hts, if_false]
    change
      (p.afterPrepareGroup A assignment).B
          (prepareState A (p.headGroup A) assignment) t k + p.E t k <=
        p.P t k
    omega

/-- At the source head slot, the residual live load plus the exact promoted
group is no larger than the old live load. -/
theorem afterPrepareGroup_L_add_batchLoad_le
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    (assignment : Operation -> Option Claim)
    {s : Slot} {b : Branch} (h : p.firstGroup A = some (s, b))
    (k : Coord) :
    (p.afterPrepareGroup A assignment).L
        (prepareState A (p.headGroup A) assignment) s k +
      Plan.batchLoad A (p.headGroup A) k <= p.L A s k := by
  have hTarget :
      (∑ c ∈ (p.afterPrepareGroup A assignment).tentativeRootClaims
          (prepareState A (p.headGroup A) assignment) s,
        A.auth.demand c k) <=
      ∑ c ∈ p.tentativeRootClaims A s \ p.headGroup A,
        A.auth.demand c k :=
    Finset.sum_le_sum_of_subset
      (afterPrepareGroup_tentativeRootClaims_subset_sdiff
        (A := A) (p := p) assignment s)
  have hHead := headGroup_subset_tentativeRootClaims h
  unfold L Plan.batchLoad at *
  change
    (∑ c ∈ (p.afterPrepareGroup A assignment).tentativeRootClaims
        (prepareState A (p.headGroup A) assignment) s,
      A.auth.demand c k) +
      (∑ c ∈ p.headGroup A, A.auth.demand c k) <=
    ∑ c ∈ p.tentativeRootClaims A s, A.auth.demand c k
  calc
    _ <= (∑ c ∈ p.tentativeRootClaims A s \ p.headGroup A,
        A.auth.demand c k) +
        (∑ c ∈ p.headGroup A, A.auth.demand c k) :=
      Nat.add_le_add_right hTarget _
    _ = _ := by rw [Finset.sum_sdiff hHead]

/-- The live-load reservation envelope survives the exact Prepare/cleanup
target.  The current row trades live load for equal durable exposure; every
other row only loses tentative claims. -/
theorem afterPrepareGroup_preserves_envelope
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    (hv : p.Valid A) (hrem : p.remaining.Nonempty)
    (assignment : Operation -> Option Claim) :
    (p.afterPrepareGroup A assignment).Envelope
      (prepareState A (p.headGroup A) assignment) := by
  obtain ⟨g, hg⟩ := firstGroup_exists_of_remaining hv hrem
  rcases g with ⟨s, b⟩
  intro t ht k
  have hOld := hv.envelope t (by simpa [afterPrepareGroup] using ht) k
  by_cases hts : t = s
  · subst t
    have hLoad := afterPrepareGroup_L_add_batchLoad_le assignment hg k
    rw [afterPrepareGroup_E_of_firstGroup assignment hg]
    simp only [ite_true]
    change
      (p.afterPrepareGroup A assignment).L
          (prepareState A (p.headGroup A) assignment) s k +
          (p.E s k + Plan.batchLoad A (p.headGroup A) k) <= p.R s k
    omega
  · have hLoad := afterPrepareGroup_L_le
      (A := A) (p := p) assignment t k
    rw [afterPrepareGroup_E_of_firstGroup assignment hg]
    simp only [hts, if_false]
    change
      (p.afterPrepareGroup A assignment).L
          (prepareState A (p.headGroup A) assignment) t k + p.E t k <=
        p.R t k
    omega

/-- The executable cursor/phase discipline survives Prepare.  This is a
derived monotonicity fact about the filtered active-group set, not a target
validity premise. -/
theorem afterPrepareGroup_preserves_cursorPhase
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    (hv : p.Valid A) (hrem : p.remaining.Nonempty)
    (assignment : Operation -> Option Claim) :
    (p.afterPrepareGroup A assignment).CursorPhase
      (prepareState A (p.headGroup A) assignment) := by
  obtain ⟨g, hg⟩ := firstGroup_exists_of_remaining hv hrem
  rcases g with ⟨s, b⟩
  intro t b' hTarget u hu htu k
  have hst : s <= t :=
    afterPrepareGroup_firstSlot_mono assignment hg hTarget
  have hsu : s < u := lt_of_le_of_lt hst htu
  have huSource : u ∈ p.slots := by
    simpa [afterPrepareGroup] using hu
  have hZero := hv.cursor_phase s b hg u huSource hsu k
  rw [afterPrepareGroup_E_of_firstGroup assignment hg]
  simp [hsu.ne', hZero]

/-- The computed `E` update is exactly the real durable-state update. -/
theorem afterPrepareGroup_preserves_durableEq
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    (hv : p.Valid A) (hrem : p.remaining.Nonempty)
    (assignment : Operation -> Option Claim) :
    (p.afterPrepareGroup A assignment).DurableEq
      (prepareState A (p.headGroup A) assignment) := by
  obtain ⟨g, hg⟩ := firstGroup_exists_of_remaining hv hrem
  rcases g with ⟨s, b⟩
  intro k
  change
    (prepareState A (p.headGroup A) assignment).auth.durableLoad k =
      p.d0 k + (p.afterPrepareGroup A assignment).totalE k
  rw [prepareState_headGroup_durableLoad assignment k,
    afterPrepareGroup_totalE assignment hg k, hv.durable_eq k]
  omega

/-- All controller fields, including the computed cursor discipline and exact
batch accounting, are preserved by the real Prepare target. -/
theorem afterPrepareGroup_preserves_valid
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    (hv : p.Valid A) (hrem : p.remaining.Nonempty)
    (assignment : Operation -> Option Claim) :
    (p.afterPrepareGroup A assignment).Valid
      (prepareState A (p.headGroup A) assignment) := by
  obtain ⟨g, hg⟩ := firstGroup_exists_of_remaining hv hrem
  rcases g with ⟨s, b⟩
  have hs : s ∈ p.slots := firstGroup_slot_mem hv hg
  refine {
    capacity_eq := ?_
    remaining_rooted := ?_
    owner_root_pure := ?_
    root_mem := ?_
    E_outside_zero := ?_
    P_outside_zero := ?_
    durable_eq := afterPrepareGroup_preserves_durableEq hv hrem assignment
    envelope := afterPrepareGroup_preserves_envelope hv hrem assignment
    deadline := ?_
    batch_bound := afterPrepareGroup_preserves_batchBound hv hrem assignment
    cursor_phase := afterPrepareGroup_preserves_cursorPhase hv hrem assignment }
  · intro k
    change A.auth.capacity k = p.cap0 k
    exact hv.capacity_eq k
  · intro c hc
    have hcTarget : c ∈ p.remaining ∧
        ∃ owner,
          (prepareState A (p.headGroup A) assignment).auth.status c =
            .tentative owner := by
      simpa [afterPrepareGroup] using hc
    obtain ⟨owner, howner⟩ := hcTarget.2
    obtain ⟨_, t, _, ht, hroot⟩ :=
      hv.remaining_rooted c hcTarget.1
    refine ⟨owner, t, howner, ?_, ?_⟩
    · simpa [afterPrepareGroup] using ht
    · simpa [afterPrepareGroup] using hroot
  · intro c c' owner hc hc'
    have hsource := prepareState_tentative_source_not_head assignment hc
    have hsource' := prepareState_tentative_source_not_head assignment hc'
    change p.rootSlot c = p.rootSlot c'
    exact hv.owner_root_pure c c' owner hsource.1 hsource'.1
  · intro c t hroot
    change p.rootSlot c = some t at hroot
    change t ∈ p.slots
    exact hv.root_mem c t hroot
  · intro t ht k
    have htSource : t ∉ p.slots := by
      simpa [afterPrepareGroup] using ht
    rw [afterPrepareGroup_E_of_firstGroup assignment hg]
    have hne : t ≠ s := fun hts => htSource (hts ▸ hs)
    simp [hne, hv.E_outside_zero t htSource k]
  · intro t ht k
    have htSource : t ∉ p.slots := by
      simpa [afterPrepareGroup] using ht
    exact hv.P_outside_zero t htSource k
  · intro t ht k
    have htSource : t ∈ p.slots := by
      simpa [afterPrepareGroup] using ht
    change p.d0 k + p.priorP t k + p.R t k <= p.cap0 k
    exact hv.deadline t htSource k

/-- Every field of the real `PrepareOK` is constructed from source lifecycle
well-formedness, the preserved plan invariant, and the executable assignment
checker. -/
theorem current_group_prepare_ok
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    (hWF : A.LWF) (hv : p.Valid A) (hrem : p.remaining.Nonempty)
    (assignment : Operation -> Option Claim)
    (hAssignment :
      Plan.checkAssignment A (p.headGroup A) assignment = true) :
    PrepareOK A (p.headGroup A) assignment := by
  obtain ⟨g, hg⟩ := firstGroup_exists_of_remaining hv hrem
  rcases g with ⟨s, b⟩
  have ha := Plan.checkAssignment_sound hAssignment
  refine {
    nonempty := headGroup_nonempty_of_firstGroup hg
    member_open := ?_
    base := current_group_promotedLoad_le_capacity hv hrem
    assigned_mem := ha.assigned_mem
    covered := ha.covered
    assignment_injective := ha.assignment_injective
    fresh := ha.fresh }
  intro c hc
  obtain ⟨owner, hstatus⟩ := headGroup_member_tentative hc
  exact ⟨owner, hstatus, hWF.owner_open c owner hstatus,
    hWF.grant_open c owner hstatus⟩

/-- The noncircular schedule theorem reaches the repository's sole actual
lifecycle relation and exact `prepareState`. -/
theorem current_group_actual_step
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    (hWF : A.LWF) (hv : p.Valid A) (hrem : p.remaining.Nonempty)
    (assignment : Operation -> Option Claim)
    (hAssignment :
      Plan.checkAssignment A (p.headGroup A) assignment = true) :
    Step A .tau (prepareState A (p.headGroup A) assignment) :=
  Step.core (CoreStep.prepare
    (current_group_prepare_ok hWF hv hrem assignment hAssignment))

/-! ## Authoritative planned Prepare and arbitrary finite traces -/

structure InvariantState where
  lifecycle : LifecycleState Coord Claim Branch Grant Operation
  plan : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)

def advancePrepare
    (S : InvariantState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot))
    (assignment : Operation -> Option Claim) :
    InvariantState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot) where
  lifecycle := prepareState S.lifecycle (S.plan.headGroup S.lifecycle) assignment
  plan := S.plan.afterPrepareGroup S.lifecycle assignment

/-- Paper-facing Prepare relation.  Unlike the lower-level readiness lemma,
this relation accepts only an executable version CAS and assignment check. -/
inductive PreparePlanned :
    InvariantState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot) ->
    Nat -> (Operation -> Option Claim) ->
    InvariantState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot) -> Prop where
  | mk {S offered assignment}
      (hWF : S.lifecycle.LWF)
      (hValid : S.plan.Valid S.lifecycle)
      (hRemaining : S.plan.remaining.Nonempty)
      (hVersion : S.plan.checkVersion offered = true)
      (hAssignment : Plan.checkAssignment S.lifecycle
        (S.plan.headGroup S.lifecycle) assignment = true) :
      PreparePlanned S offered assignment (advancePrepare S assignment)

theorem PreparePlanned.version_sound
    {S S' : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)}
    {offered : Nat} {assignment : Operation -> Option Claim}
    (h : PreparePlanned S offered assignment S') :
    offered = S.plan.version := by
  cases h with
  | mk _ _ _ hVersion _ => exact checkVersion_sound _ _ hVersion

theorem PreparePlanned.actual_step
    {S S' : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)}
    {offered : Nat} {assignment : Operation -> Option Claim}
    (h : PreparePlanned S offered assignment S') :
    Step S.lifecycle .tau S'.lifecycle := by
  cases h with
  | mk hWF hValid hRemaining _ hAssignment =>
      simpa [advancePrepare] using
        current_group_actual_step hWF hValid hRemaining assignment hAssignment

theorem PreparePlanned.preserves_valid
    {S S' : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)}
    {offered : Nat} {assignment : Operation -> Option Claim}
    (h : PreparePlanned S offered assignment S') :
    S'.plan.Valid S'.lifecycle := by
  cases h with
  | mk _ hValid hRemaining _ _ =>
      simpa [advancePrepare] using
        afterPrepareGroup_preserves_valid hValid hRemaining assignment

theorem PreparePlanned.preserves_wf_ac
    {S S' : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)}
    {offered : Nat} {assignment : Operation -> Option Claim}
    (h : PreparePlanned S offered assignment S')
    (hAC : AC S.lifecycle.auth) :
    S'.lifecycle.LWF ∧ AC S'.lifecycle.auth := by
  cases h with
  | mk hWF hValid hRemaining _ hAssignment =>
      have hOK := current_group_prepare_ok hWF hValid hRemaining
        assignment hAssignment
      simpa [advancePrepare] using
        AuthorityContinuity.prepare_preserves_wf_ac S.lifecycle
          (S.plan.headGroup S.lifecycle) assignment hWF hAC hOK

theorem PreparePlanned.version_succ
    {S S' : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)}
    {offered : Nat} {assignment : Operation -> Option Claim}
    (h : PreparePlanned S offered assignment S') :
    S'.plan.version = S.plan.version + 1 := by
  cases h
  rfl

theorem prepareState_headGroup_status_durable
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    (assignment : Operation -> Option Claim) {c : Claim}
    (hc : c ∈ p.headGroup A) :
    (prepareState A (p.headGroup A) assignment).auth.status c = .durable := by
  change preparedStatus A.auth (p.headGroup A) c = .durable
  rw [preparedStatus_durable_iff]
  simp [rawPromotion, hc]

theorem afterPrepareGroup_remaining_subset
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    (assignment : Operation -> Option Claim) :
    (p.afterPrepareGroup A assignment).remaining ⊆ p.remaining := by
  intro c hc
  simpa [afterPrepareGroup] using (Finset.mem_filter.mp hc).1

/-- Each enabled Prepare removes at least its nonempty promoted owner group;
therefore the executable Prepare-only scheduler cannot livelock. -/
theorem afterPrepareGroup_remaining_card_lt
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    (hv : p.Valid A) (hrem : p.remaining.Nonempty)
    (assignment : Operation -> Option Claim) :
    (p.afterPrepareGroup A assignment).remaining.card < p.remaining.card := by
  obtain ⟨g, hg⟩ := firstGroup_exists_of_remaining hv hrem
  rcases g with ⟨s, b⟩
  obtain ⟨c, hcHead⟩ := headGroup_nonempty_of_firstGroup hg
  have hcOwner : c ∈ p.ownerGroup A s b := by
    simpa [headGroup, hg] using hcHead
  have hcRemaining : c ∈ p.remaining :=
    (Finset.mem_filter.mp (Finset.mem_filter.mp hcOwner).1).1
  apply Finset.card_lt_card
  rw [Finset.ssubset_iff_of_subset
    (afterPrepareGroup_remaining_subset assignment)]
  refine ⟨c, hcRemaining, ?_⟩
  intro hcTarget
  have hcFiltered := Finset.mem_filter.mp hcTarget
  obtain ⟨owner, htentative⟩ := hcFiltered.2
  have hdurable := prepareState_headGroup_status_durable assignment hcHead
  rw [hdurable] at htentative
  simp at htentative

theorem PreparePlanned.remaining_card_lt
    {S S' : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)}
    {offered : Nat} {assignment : Operation -> Option Claim}
    (h : PreparePlanned S offered assignment S') :
    S'.plan.remaining.card < S.plan.remaining.card := by
  cases h with
  | mk _ hValid hRemaining _ _ =>
      simpa [advancePrepare] using
        afterPrepareGroup_remaining_card_lt hValid hRemaining assignment

def PlannedPrepareEdge
    (S S' : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)) : Prop :=
  ∃ offered assignment, PreparePlanned S offered assignment S'

abbrev PlannedPrepareTrace
    (S S' : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)) : Prop :=
  Relation.ReflTransGen PlannedPrepareEdge S S'

/-- Reverse execution order is well founded under remaining-batch cardinality.
This is the scheduler's termination argument for Prepare-only runs. -/
theorem plannedPrepareEdge_wellFounded :
    WellFounded
      (fun S' S : InvariantState (Coord := Coord) (Claim := Claim)
        (Branch := Branch) (Grant := Grant) (Operation := Operation)
        (Slot := Slot) => PlannedPrepareEdge S S') := by
  apply Subrelation.wf ?_ (measure fun S :
    InvariantState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot) =>
      S.plan.remaining.card).wf
  intro S' S hstep
  obtain ⟨offered, assignment, hplanned⟩ := hstep
  exact hplanned.remaining_card_lt

/-- Arbitrarily many authoritative Prepare steps preserve lifecycle safety and
the complete multi-slot controller invariant. -/
theorem planned_prepare_trace_preserves
    {S S' : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)}
    (htrace : PlannedPrepareTrace S S')
    (hWF : S.lifecycle.LWF) (hAC : AC S.lifecycle.auth)
    (hValid : S.plan.Valid S.lifecycle) :
    S'.lifecycle.LWF ∧ AC S'.lifecycle.auth ∧
      S'.plan.Valid S'.lifecycle := by
  induction htrace with
  | refl => exact ⟨hWF, hAC, hValid⟩
  | tail _ hstep ih =>
      obtain ⟨offered, assignment, hplanned⟩ := hstep
      have hbase := hplanned.preserves_wf_ac ih.2.1
      exact ⟨hbase.1, hbase.2, hplanned.preserves_valid⟩

/-- The controller-only trace erases to the repository's sole lifecycle
relation. -/
theorem planned_prepare_trace_projects
    {S S' : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)}
    (htrace : PlannedPrepareTrace S S') :
    Relation.ReflTransGen
      (fun A A' : LifecycleState Coord Claim Branch Grant Operation =>
        ∃ eta, Step A eta A') S.lifecycle S'.lifecycle := by
  induction htrace with
  | refl => exact .refl
  | tail _ hstep ih =>
      obtain ⟨offered, assignment, hplanned⟩ := hstep
      exact ih.tail ⟨.tau, hplanned.actual_step⟩

theorem planned_prepare_trace_version_mono
    {S S' : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)}
    (htrace : PlannedPrepareTrace S S') :
    S.plan.version <= S'.plan.version := by
  induction htrace with
  | refl => exact le_rfl
  | tail _ hstep ih =>
      obtain ⟨offered, assignment, hplanned⟩ := hstep
      rw [hplanned.version_succ]
      omega

theorem planned_prepare_trace_remaining_card_mono
    {S S' : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)}
    (htrace : PlannedPrepareTrace S S') :
    S'.plan.remaining.card <= S.plan.remaining.card := by
  induction htrace with
  | refl => exact le_rfl
  | tail _ hstep ih =>
      obtain ⟨offered, assignment, hplanned⟩ := hstep
      exact (Nat.le_of_lt hplanned.remaining_card_lt).trans ih

/-- A two-Prepare vertical gate: after the first checked Prepare, its derived
target invariants justify a second checked Prepare without any target-validity
or readiness premise. -/
theorem two_prepare_gate
    (S : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot))
    (hWF : S.lifecycle.LWF) (hAC : AC S.lifecycle.auth)
    (hValid : S.plan.Valid S.lifecycle)
    (hRemaining₁ : S.plan.remaining.Nonempty)
    (assignment₁ : Operation -> Option Claim)
    (hAssignment₁ : Plan.checkAssignment S.lifecycle
      (S.plan.headGroup S.lifecycle) assignment₁ = true)
    (hRemaining₂ : (advancePrepare S assignment₁).plan.remaining.Nonempty)
    (assignment₂ : Operation -> Option Claim)
    (hAssignment₂ : Plan.checkAssignment
      (advancePrepare S assignment₁).lifecycle
      ((advancePrepare S assignment₁).plan.headGroup
        (advancePrepare S assignment₁).lifecycle) assignment₂ = true) :
    ∃ S₁ S₂,
      PreparePlanned S S.plan.version assignment₁ S₁ ∧
      PreparePlanned S₁ S₁.plan.version assignment₂ S₂ ∧
      Step S.lifecycle .tau S₁.lifecycle ∧
      Step S₁.lifecycle .tau S₂.lifecycle ∧
      S₂.plan.Valid S₂.lifecycle := by
  let S₁ := advancePrepare S assignment₁
  let S₂ := advancePrepare S₁ assignment₂
  have hVersion₁ : S.plan.checkVersion S.plan.version = true := by
    simp [checkVersion]
  have hFirst : PreparePlanned S S.plan.version assignment₁ S₁ :=
    PreparePlanned.mk hWF hValid hRemaining₁ hVersion₁ hAssignment₁
  have hBase₁ := hFirst.preserves_wf_ac hAC
  have hValid₁ := hFirst.preserves_valid
  have hVersion₂ : S₁.plan.checkVersion S₁.plan.version = true := by
    simp [checkVersion]
  have hSecond : PreparePlanned S₁ S₁.plan.version assignment₂ S₂ :=
    PreparePlanned.mk hBase₁.1 hValid₁ hRemaining₂ hVersion₂ hAssignment₂
  exact ⟨S₁, S₂, hFirst, hSecond, hFirst.actual_step,
    hSecond.actual_step, hSecond.preserves_valid⟩

#print axioms current_group_promotedLoad_le_capacity
#print axioms current_group_prepare_ok
#print axioms current_group_actual_step
#print axioms afterPrepareGroup_preserves_valid
#print axioms PreparePlanned.actual_step
#print axioms planned_prepare_trace_preserves
#print axioms planned_prepare_trace_projects
#print axioms plannedPrepareEdge_wellFounded
#print axioms two_prepare_gate

end PlanData

end AuthorityContinuity.PlanInvariant
