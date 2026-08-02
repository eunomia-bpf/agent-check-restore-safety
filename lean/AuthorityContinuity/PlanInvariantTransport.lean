import AuthorityContinuity.PlanInvariant
import AuthorityContinuity.PlanRootTransport

/-!
# Canonical transfer of a durable authority plan

The target plan in this module is computed only from the source plan and the
actual checked transfer map `rho`.  The canonical lifecycle target remains the
repository's `canonicalTarget`; no caller supplies a target root map, target
batch, target load bound, readiness fact, or target validity certificate.
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

/-- The only canonical target plan admitted by this bridge.  Tentative lineage
follows the actual `rho`; the selected batch is its computed preimage, and all
durable schedule/accounting fields remain unchanged because canonical transfer
does not promote a claim. -/
def afterCanonical
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (tr : Transfer Claim Branch) :
    PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot) :=
  { p with
    version := p.version + 1
    rootSlot := PlanRootTransport.transportedRoot p.rootSlot tr
    remaining := Plan.childBatch tr p.remaining }

@[simp] theorem afterCanonical_version
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (tr : Transfer Claim Branch) :
    (p.afterCanonical tr).version = p.version + 1 := rfl

@[simp] theorem afterCanonical_rootSlot
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (tr : Transfer Claim Branch) :
    (p.afterCanonical tr).rootSlot =
      PlanRootTransport.transportedRoot p.rootSlot tr := rfl

@[simp] theorem afterCanonical_remaining
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (tr : Transfer Claim Branch) :
    (p.afterCanonical tr).remaining = Plan.childBatch tr p.remaining := rfl

@[simp] theorem transportedRoot_eq_childRootSlot
    (root : Claim -> Option Slot) (tr : Transfer Claim Branch) :
    PlanRootTransport.transportedRoot root tr = Plan.childRootSlot root tr :=
  rfl

/-- `PlanData.L` is exactly the all-tentative lineage load used by the generic
root-transport theorem. -/
theorem L_eq_tentativeRootLoad
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (s : Slot) (k : Coord) :
    p.L A s k = PlanRootTransport.tentativeRootLoad
      A.auth p.rootSlot s k := by
  unfold L PlanRootTransport.tentativeRootLoad
    PlanRootTransport.tentativeLineageLoad
  apply Finset.sum_congr
  · ext c
    simp [tentativeRootClaims, PlanRootTransport.tentativeLineageClaims,
      and_comm]
  · intro c _
    rfl

/-- All tentative target demand at a scheduled root, including non-batch
claims, is bounded by the corresponding source load. -/
theorem afterCanonical_L_le
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (tr : Transfer Claim Branch) (op : CanonicalOp Branch)
    (valid : CanonicalValid A tr op) (s : Slot) (k : Coord) :
    (p.afterCanonical tr).L (canonicalTarget A tr op) s k <= p.L A s k := by
  rw [L_eq_tentativeRootLoad, L_eq_tentativeRootLoad]
  change
    PlanRootTransport.tentativeRootLoad (canonicalTarget A tr op).auth
        (PlanRootTransport.transportedRoot p.rootSlot tr) s k <=
      PlanRootTransport.tentativeRootLoad A.auth p.rootSlot s k
  exact PlanRootTransport.canonicalTarget_tentative_root_load_le
    A tr op p.rootSlot valid s k

/-- The selected target batch and roots are computed from `rho`; checked fiber
conservation therefore bounds every target root batch by its source batch. -/
theorem afterCanonical_B_le
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (tr : Transfer Claim Branch) (op : CanonicalOp Branch)
    (valid : CanonicalValid A tr op) (s : Slot) (k : Coord) :
    (p.afterCanonical tr).B (canonicalTarget A tr op) s k <= p.B A s k := by
  unfold B rootRemaining
  change
    Plan.rootBatchLoad A (Plan.childBatch tr p.remaining)
        (Plan.childRootSlot p.rootSlot tr) s k <=
      Plan.rootBatchLoad A p.remaining p.rootSlot s k
  exact Plan.computed_root_batch_load_le A tr p.remaining p.rootSlot
    valid.transfer.toCoreValid s k

/-- Every computed target batch leaf has a checked tentative target owner and
inherits the scheduled root of its actual source leaf. -/
theorem afterCanonical_preserves_remaining_rooted
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    {tr : Transfer Claim Branch} {op : CanonicalOp Branch}
    (hv : p.Valid A) (valid : CanonicalValid A tr op) :
    ∀ c' ∈ (p.afterCanonical tr).remaining,
      ∃ b s, (canonicalTarget A tr op).auth.status c' = .tentative b ∧
        s ∈ (p.afterCanonical tr).slots ∧
        (p.afterCanonical tr).rootSlot c' = some s := by
  intro c' hc'
  have hchild : c' ∈ Plan.childBatch tr p.remaining := by
    simpa [afterCanonical] using hc'
  obtain ⟨c, hc, hrho⟩ : ∃ c ∈ p.remaining, tr.rho c' = some c := by
    simpa [Plan.childBatch] using hchild
  obtain ⟨_, s, _, hs, hroot⟩ := hv.remaining_rooted c hc
  obtain ⟨b, htarget⟩ :=
    (Transfer.targetStatus_tentative_exists_iff A tr
      valid.transfer.toCoreValid c').2 ⟨c, hrho⟩
  refine ⟨b, s, ?_, by simpa [afterCanonical] using hs, ?_⟩
  · exact htarget
  · change PlanRootTransport.transportedRoot p.rootSlot tr c' = some s
    rw [PlanRootTransport.transportedRoot_of_rho p.rootSlot tr hrho, hroot]

/-- The explicit executable checker is the only extra admission atom needed
for target owner/root purity; it ranges over every target tentative claim and
also rejects `some`/`none` mixing. -/
theorem afterCanonical_preserves_owner_root_pure
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    {tr : Transfer Claim Branch} {op : CanonicalOp Branch}
    (hOwner : PlanRootTransport.checkTargetOwnerRootPure A tr
      (canonicalAllowed A op) p.rootSlot = true) :
    ∀ c c' b,
      (canonicalTarget A tr op).auth.status c = .tentative b ->
      (canonicalTarget A tr op).auth.status c' = .tentative b ->
      (p.afterCanonical tr).rootSlot c =
        (p.afterCanonical tr).rootSlot c' := by
  have hpure := PlanRootTransport.checkTargetOwnerRootPure_sound hOwner
  intro c c' b hc hc'
  exact hpure c c' b hc hc'

/-- Any scheduled target root came through an actual `rho` edge from a source
root already admitted by the source plan. -/
theorem afterCanonical_preserves_root_mem
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    {tr : Transfer Claim Branch}
    (hrootMem : ∀ c s, p.rootSlot c = some s -> s ∈ p.slots) :
    ∀ c s, (p.afterCanonical tr).rootSlot c = some s ->
      s ∈ (p.afterCanonical tr).slots := by
  intro c s hroot
  change PlanRootTransport.transportedRoot p.rootSlot tr c = some s at hroot
  unfold PlanRootTransport.transportedRoot at hroot
  cases hrho : tr.rho c with
  | none => simp [hrho] at hroot
  | some source =>
      have hs : p.rootSlot source = some s := by
        simpa [hrho] using hroot
      simpa [afterCanonical] using hrootMem source s hs

theorem afterCanonical_preserves_durableEq
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    {tr : Transfer Claim Branch} {op : CanonicalOp Branch}
    (hv : p.Valid A) (valid : CanonicalValid A tr op) :
    (p.afterCanonical tr).DurableEq (canonicalTarget A tr op) := by
  intro k
  change
    (tr.targetCore A (canonicalAllowed A op)).durableLoad k =
      p.d0 k + p.totalE k
  rw [Transfer.targetCore_durableLoad A tr valid.transfer.toCoreValid
    (canonicalAllowed A op) k]
  exact hv.durable_eq k

theorem afterCanonical_preserves_envelope
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    {tr : Transfer Claim Branch} {op : CanonicalOp Branch}
    (hv : p.Valid A) (valid : CanonicalValid A tr op) :
    (p.afterCanonical tr).Envelope (canonicalTarget A tr op) := by
  intro s hs k
  have hsource : s ∈ p.slots := by
    simpa [afterCanonical] using hs
  have hOld := hv.envelope s hsource k
  have hLoad := afterCanonical_L_le A p tr op valid s k
  change
    (p.afterCanonical tr).L (canonicalTarget A tr op) s k + p.E s k <=
      p.R s k
  omega

theorem afterCanonical_preserves_batchBound
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    {tr : Transfer Claim Branch} {op : CanonicalOp Branch}
    (hv : p.Valid A) (valid : CanonicalValid A tr op) :
    (p.afterCanonical tr).BatchBound (canonicalTarget A tr op) := by
  intro s hs k
  have hsource : s ∈ p.slots := by
    simpa [afterCanonical] using hs
  have hOld := hv.batch_bound s hsource k
  have hBatch := afterCanonical_B_le A p tr op valid s k
  change
    (p.afterCanonical tr).B (canonicalTarget A tr op) s k + p.E s k <=
      p.P s k
  omega

/-- A target active group may have a different owner and different claim IDs,
but its scheduled slot has a real source active group at exactly the same root.
This is the slot-level fact needed for cursor monotonicity. -/
theorem afterCanonical_activeGroup_has_source_at_slot
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    {tr : Transfer Claim Branch} {op : CanonicalOp Branch}
    (valid : CanonicalValid A tr op) {t : Slot} {b' : Branch}
    (hactive : toLex (t, b') ∈
      (p.afterCanonical tr).activeGroups (canonicalTarget A tr op)) :
    ∃ b, toLex (t, b) ∈ p.activeGroups A := by
  have hgroup : ((p.afterCanonical tr).ownerGroup
      (canonicalTarget A tr op) t b').Nonempty := by
    simpa [activeGroups] using hactive
  obtain ⟨c', hc'⟩ := hgroup
  simp only [ownerGroup, rootRemaining, Finset.mem_filter] at hc'
  have hchild : c' ∈ Plan.childBatch tr p.remaining := by
    simpa [afterCanonical] using hc'.1.1
  obtain ⟨c, hc, hrho⟩ : ∃ c ∈ p.remaining, tr.rho c' = some c := by
    simpa [Plan.childBatch] using hchild
  obtain ⟨b, hsource⟩ := valid.transfer.source_tentative c' c hrho
  have htargetRoot :
      PlanRootTransport.transportedRoot p.rootSlot tr c' = some t := by
    simpa [afterCanonical] using hc'.1.2
  have hsourceRoot : p.rootSlot c = some t := by
    simpa [PlanRootTransport.transportedRoot, hrho] using htargetRoot
  refine ⟨b, ?_⟩
  simp only [activeGroups, Finset.mem_filter, Finset.mem_univ, true_and]
  refine ⟨c, ?_⟩
  simp [ownerGroup, rootRemaining, hc, hsourceRoot, hsource]

/-- Canonical transfer cannot move the executable cursor to an earlier slot.
Target owners may change, so the proof compares slots through an actual source
group witness rather than assuming inclusion of `(slot, owner)` pairs. -/
theorem afterCanonical_preserves_cursorPhase
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    {tr : Transfer Claim Branch} {op : CanonicalOp Branch}
    (hv : p.Valid A) (valid : CanonicalValid A tr op) :
    (p.afterCanonical tr).CursorPhase (canonicalTarget A tr op) := by
  intro t b' hTarget u hu htu k
  have hTargetMem := firstGroup_mem hTarget
  obtain ⟨sourceOwner, hSourceActive⟩ :=
    afterCanonical_activeGroup_has_source_at_slot valid hTargetMem
  have hSourceGroup : (p.ownerGroup A t sourceOwner).Nonempty := by
    simpa [activeGroups] using hSourceActive
  obtain ⟨c, hc⟩ := hSourceGroup
  have hcRoot : c ∈ p.rootRemaining t := (Finset.mem_filter.mp hc).1
  have hcRemaining : c ∈ p.remaining :=
    (Finset.mem_filter.mp hcRoot).1
  obtain ⟨g, hg⟩ := firstGroup_exists_of_remaining hv ⟨c, hcRemaining⟩
  rcases g with ⟨s, b⟩
  have hLex := firstGroup_le_active hg hSourceActive
  have hst : s <= t := by
    simpa using Prod.Lex.monotone_fst
      (toLex (s, b)) (toLex (t, sourceOwner)) hLex
  have hsu : s < u := lt_of_le_of_lt hst htu
  have huSource : u ∈ p.slots := by
    simpa [afterCanonical] using hu
  have hzero := hv.cursor_phase s b hg u huSource hsu k
  simpa [afterCanonical] using hzero

/-! ## Projection-free target-core bridge

The following theorem exposes the plan argument below the canonical wrapper.
It needs only an actual lifecycle whose authority field is the checked
`targetCore`; this is the shape reusable by simulation-certified Merge.
-/

theorem afterTransferCore_L_le
    (A A' : LifecycleState Coord Claim Branch Grant Operation)
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (tr : Transfer Claim Branch) (allowed : Finset (Finset Branch))
    (hAuth : A'.auth = tr.targetCore A allowed)
    (valid : Transfer.CoreValid A tr) (s : Slot) (k : Coord) :
    (p.afterCanonical tr).L A' s k <= p.L A s k := by
  rw [L_eq_tentativeRootLoad, L_eq_tentativeRootLoad, hAuth]
  exact PlanRootTransport.targetCore_tentative_root_load_le
    A tr allowed p.rootSlot valid s k

theorem afterTransferCore_B_le
    (A A' : LifecycleState Coord Claim Branch Grant Operation)
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (tr : Transfer Claim Branch) (allowed : Finset (Finset Branch))
    (hAuth : A'.auth = tr.targetCore A allowed)
    (valid : Transfer.CoreValid A tr) (s : Slot) (k : Coord) :
    (p.afterCanonical tr).B A' s k <= p.B A s k := by
  unfold B rootRemaining Plan.batchLoad
  rw [hAuth]
  change
    Plan.rootBatchLoad A (Plan.childBatch tr p.remaining)
        (Plan.childRootSlot p.rootSlot tr) s k <=
      Plan.rootBatchLoad A p.remaining p.rootSlot s k
  exact Plan.computed_root_batch_load_le A tr p.remaining p.rootSlot
    valid s k

theorem afterTransferCore_preserves_remaining_rooted
    {A A' : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    {tr : Transfer Claim Branch} {allowed : Finset (Finset Branch)}
    (hAuth : A'.auth = tr.targetCore A allowed)
    (hv : p.Valid A) (valid : Transfer.CoreValid A tr) :
    ∀ c' ∈ (p.afterCanonical tr).remaining,
      ∃ b s, A'.auth.status c' = .tentative b ∧
        s ∈ (p.afterCanonical tr).slots ∧
        (p.afterCanonical tr).rootSlot c' = some s := by
  intro c' hc'
  have hchild : c' ∈ Plan.childBatch tr p.remaining := by
    simpa [afterCanonical] using hc'
  obtain ⟨c, hc, hrho⟩ : ∃ c ∈ p.remaining, tr.rho c' = some c := by
    simpa [Plan.childBatch] using hchild
  obtain ⟨_, s, _, hs, hroot⟩ := hv.remaining_rooted c hc
  obtain ⟨b, htarget⟩ :=
    (Transfer.targetStatus_tentative_exists_iff A tr valid c').2
      ⟨c, hrho⟩
  refine ⟨b, s, ?_, by simpa [afterCanonical] using hs, ?_⟩
  · rw [hAuth]
    exact htarget
  · change PlanRootTransport.transportedRoot p.rootSlot tr c' = some s
    rw [PlanRootTransport.transportedRoot_of_rho p.rootSlot tr hrho, hroot]

theorem afterTransferCore_activeGroup_has_source_at_slot
    {A A' : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    {tr : Transfer Claim Branch} {allowed : Finset (Finset Branch)}
    (_hAuth : A'.auth = tr.targetCore A allowed)
    (valid : Transfer.CoreValid A tr) {t : Slot} {b' : Branch}
    (hactive : toLex (t, b') ∈ (p.afterCanonical tr).activeGroups A') :
    ∃ b, toLex (t, b) ∈ p.activeGroups A := by
  have hgroup : ((p.afterCanonical tr).ownerGroup A' t b').Nonempty := by
    simpa [activeGroups] using hactive
  obtain ⟨c', hc'⟩ := hgroup
  simp only [ownerGroup, rootRemaining, Finset.mem_filter] at hc'
  have hchild : c' ∈ Plan.childBatch tr p.remaining := by
    simpa [afterCanonical] using hc'.1.1
  obtain ⟨c, hc, hrho⟩ : ∃ c ∈ p.remaining, tr.rho c' = some c := by
    simpa [Plan.childBatch] using hchild
  obtain ⟨b, hsource⟩ := valid.source_tentative c' c hrho
  have htargetRoot :
      PlanRootTransport.transportedRoot p.rootSlot tr c' = some t := by
    simpa [afterCanonical] using hc'.1.2
  have hsourceRoot : p.rootSlot c = some t := by
    simpa [PlanRootTransport.transportedRoot, hrho] using htargetRoot
  refine ⟨b, ?_⟩
  simp only [activeGroups, Finset.mem_filter, Finset.mem_univ, true_and]
  refine ⟨c, ?_⟩
  simp [ownerGroup, rootRemaining, hc, hsourceRoot, hsource]

theorem afterTransferCore_preserves_cursorPhase
    {A A' : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    {tr : Transfer Claim Branch} {allowed : Finset (Finset Branch)}
    (hAuth : A'.auth = tr.targetCore A allowed)
    (hv : p.Valid A) (valid : Transfer.CoreValid A tr) :
    (p.afterCanonical tr).CursorPhase A' := by
  intro t b' hTarget u hu htu k
  have hTargetMem := firstGroup_mem hTarget
  obtain ⟨sourceOwner, hSourceActive⟩ :=
    afterTransferCore_activeGroup_has_source_at_slot hAuth valid hTargetMem
  have hSourceGroup : (p.ownerGroup A t sourceOwner).Nonempty := by
    simpa [activeGroups] using hSourceActive
  obtain ⟨c, hc⟩ := hSourceGroup
  have hcRoot : c ∈ p.rootRemaining t := (Finset.mem_filter.mp hc).1
  have hcRemaining : c ∈ p.remaining :=
    (Finset.mem_filter.mp hcRoot).1
  obtain ⟨g, hg⟩ := firstGroup_exists_of_remaining hv ⟨c, hcRemaining⟩
  rcases g with ⟨s, b⟩
  have hLex := firstGroup_le_active hg hSourceActive
  have hst : s <= t := by
    simpa using Prod.Lex.monotone_fst
      (toLex (s, b)) (toLex (t, sourceOwner)) hLex
  have hsu : s < u := lt_of_le_of_lt hst htu
  have huSource : u ∈ p.slots := by
    simpa [afterCanonical] using hu
  have hzero := hv.cursor_phase s b hg u huSource hsu k
  simpa [afterCanonical] using hzero

/-- Generic plan preservation for any actual checked `targetCore`.  Canonical
operations instantiate `allowed = canonicalAllowed A op`; a simulation Merge
can reuse this theorem once it exposes the same authority equality. -/
theorem afterTransferCore_preserves_valid
    {A A' : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    {tr : Transfer Claim Branch} {allowed : Finset (Finset Branch)}
    (hAuth : A'.auth = tr.targetCore A allowed)
    (hv : p.Valid A) (valid : Transfer.CoreValid A tr)
    (hOwner : PlanRootTransport.checkTargetOwnerRootPure A tr allowed
      p.rootSlot = true) :
    (p.afterCanonical tr).Valid A' := by
  refine {
    capacity_eq := ?_
    remaining_rooted :=
      afterTransferCore_preserves_remaining_rooted hAuth hv valid
    owner_root_pure := ?_
    root_mem := afterCanonical_preserves_root_mem hv.root_mem
    E_outside_zero := ?_
    P_outside_zero := ?_
    durable_eq := ?_
    envelope := ?_
    deadline := ?_
    batch_bound := ?_
    cursor_phase := afterTransferCore_preserves_cursorPhase hAuth hv valid }
  · intro k
    rw [hAuth]
    exact hv.capacity_eq k
  · have hpure := PlanRootTransport.checkTargetOwnerRootPure_sound hOwner
    intro c c' b hc hc'
    apply hpure c c' b
    · rw [← hAuth]
      exact hc
    · rw [← hAuth]
      exact hc'
  · intro s hs k
    exact hv.E_outside_zero s (by simpa [afterCanonical] using hs) k
  · intro s hs k
    exact hv.P_outside_zero s (by simpa [afterCanonical] using hs) k
  · intro k
    change A'.auth.durableLoad k = p.d0 k + p.totalE k
    rw [hAuth, Transfer.targetCore_durableLoad A tr valid allowed k]
    exact hv.durable_eq k
  · intro s hs k
    have hsSource : s ∈ p.slots := by
      simpa [afterCanonical] using hs
    have hOld := hv.envelope s hsSource k
    have hLoad := afterTransferCore_L_le A A' p tr allowed hAuth valid s k
    change (p.afterCanonical tr).L A' s k + p.E s k <= p.R s k
    omega
  · intro s hs k
    exact hv.deadline s (by simpa [afterCanonical] using hs) k
  · intro s hs k
    have hsSource : s ∈ p.slots := by
      simpa [afterCanonical] using hs
    have hOld := hv.batch_bound s hsSource k
    have hBatch := afterTransferCore_B_le A A' p tr allowed hAuth valid s k
    change (p.afterCanonical tr).B A' s k + p.E s k <= p.P s k
    omega

/-- Complete plan preservation from source evidence and executable admission
atoms.  `checkCanonical` supplies the actual transfer facts; the separate
owner/root checker supplies precisely the property absent from that topology
checker.  No target invariant or target load proposition is an argument. -/
theorem afterCanonical_preserves_valid
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    {tr : Transfer Claim Branch} {op : CanonicalOp Branch}
    (hv : p.Valid A) (hCanonical : checkCanonical A tr op = true)
    (hOwner : PlanRootTransport.checkTargetOwnerRootPure A tr
      (canonicalAllowed A op) p.rootSlot = true) :
    (p.afterCanonical tr).Valid (canonicalTarget A tr op) := by
  have valid := checkCanonical_sound A tr op hCanonical
  refine {
    capacity_eq := ?_
    remaining_rooted := afterCanonical_preserves_remaining_rooted hv valid
    owner_root_pure := afterCanonical_preserves_owner_root_pure hOwner
    root_mem := afterCanonical_preserves_root_mem hv.root_mem
    E_outside_zero := ?_
    P_outside_zero := ?_
    durable_eq := afterCanonical_preserves_durableEq hv valid
    envelope := afterCanonical_preserves_envelope hv valid
    deadline := ?_
    batch_bound := afterCanonical_preserves_batchBound hv valid
    cursor_phase := afterCanonical_preserves_cursorPhase hv valid }
  · intro k
    change A.auth.capacity k = p.cap0 k
    exact hv.capacity_eq k
  · intro s hs k
    exact hv.E_outside_zero s (by simpa [afterCanonical] using hs) k
  · intro s hs k
    exact hv.P_outside_zero s (by simpa [afterCanonical] using hs) k
  · intro s hs k
    exact hv.deadline s (by simpa [afterCanonical] using hs) k

/-- The target current-head phase bound remains derived, rather than admitted
as an extra transfer certificate. -/
theorem afterCanonical_preserves_headPhaseBound
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    {tr : Transfer Claim Branch} {op : CanonicalOp Branch}
    (hv : p.Valid A) (hCanonical : checkCanonical A tr op = true)
    (hOwner : PlanRootTransport.checkTargetOwnerRootPure A tr
      (canonicalAllowed A op) p.rootSlot = true) :
    (p.afterCanonical tr).HeadPhaseBound (canonicalTarget A tr op) :=
  (afterCanonical_preserves_valid hv hCanonical hOwner).derived_head_phase_bound

/-- Executable controller admission for canonical plan transport.  The three
atoms are intentionally visible: durable version CAS, the repository's actual
canonical topology checker, and target owner/root purity on the computed
target/root map. -/
def checkCanonicalPlan
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (tr : Transfer Claim Branch) (op : CanonicalOp Branch)
    (offered : Nat) : Bool :=
  p.checkVersion offered &&
    (checkCanonical A tr op &&
      PlanRootTransport.checkTargetOwnerRootPure A tr
        (canonicalAllowed A op) p.rootSlot)

theorem checkCanonicalPlan_parts
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (tr : Transfer Claim Branch) (op : CanonicalOp Branch)
    (offered : Nat) (hcheck :
      checkCanonicalPlan A p tr op offered = true) :
    p.checkVersion offered = true ∧
      checkCanonical A tr op = true ∧
      PlanRootTransport.checkTargetOwnerRootPure A tr
        (canonicalAllowed A op) p.rootSlot = true := by
  simpa [checkCanonicalPlan, Bool.and_eq_true] using hcheck

/-- The offered version is checked against the source durable plan; the
computed target advances it exactly once. -/
theorem afterCanonical_version_of_check
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (tr : Transfer Claim Branch) (offered : Nat)
    (hVersion : p.checkVersion offered = true) :
    (p.afterCanonical tr).version = offered + 1 := by
  rw [afterCanonical_version, checkVersion_sound p offered hVersion]

/-- Top-level checked plan result, including the load-bearing version CAS.
The CAS is not smuggled into `Valid`, whose fields do not mention version. -/
theorem afterCanonical_checked_valid
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    {tr : Transfer Claim Branch} {op : CanonicalOp Branch} {offered : Nat}
    (hv : p.Valid A) (hVersion : p.checkVersion offered = true)
    (hCanonical : checkCanonical A tr op = true)
    (hOwner : PlanRootTransport.checkTargetOwnerRootPure A tr
      (canonicalAllowed A op) p.rootSlot = true) :
    (p.afterCanonical tr).Valid (canonicalTarget A tr op) ∧
      (p.afterCanonical tr).version = offered + 1 :=
  ⟨afterCanonical_preserves_valid hv hCanonical hOwner,
    afterCanonical_version_of_check p tr offered hVersion⟩

/-- Soundness of the single executable controller check. -/
theorem checkCanonicalPlan_sound
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    {tr : Transfer Claim Branch} {op : CanonicalOp Branch} {offered : Nat}
    (hv : p.Valid A) (hcheck :
      checkCanonicalPlan A p tr op offered = true) :
    (p.afterCanonical tr).Valid (canonicalTarget A tr op) ∧
      (p.afterCanonical tr).version = offered + 1 := by
  have hparts := checkCanonicalPlan_parts A p tr op offered hcheck
  exact afterCanonical_checked_valid hv hparts.1 hparts.2.1 hparts.2.2

/-- The lifecycle projection is the repository's authoritative canonical
constructor, not a parallel plan-specific transition relation. -/
theorem afterCanonical_actual_step
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch) (op : CanonicalOp Branch)
    (hCanonical : checkCanonical A tr op = true) :
    Step A .tau (canonicalTarget A tr op) :=
  Step.canonical tr op hCanonical

/-- End-to-end canonical gate: the same executable checks derive lifecycle
safety, complete plan validity, the actual `Step`, and single version advance. -/
theorem checkedCanonical_preserves_all
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    {tr : Transfer Claim Branch} {op : CanonicalOp Branch} {offered : Nat}
    (hWF : A.LWF) (hAC : AC A.auth) (hActive : ActiveExact A)
    (hv : p.Valid A) (hVersion : p.checkVersion offered = true)
    (hCanonical : checkCanonical A tr op = true)
    (hOwner : PlanRootTransport.checkTargetOwnerRootPure A tr
      (canonicalAllowed A op) p.rootSlot = true) :
    let A' := canonicalTarget A tr op
    let p' := p.afterCanonical tr
    A'.LWF ∧ AC A'.auth ∧ ActiveExact A' ∧ p'.Valid A' ∧
      Step A .tau A' ∧ p'.version = offered + 1 := by
  dsimp
  have hLifecycle := canonical_preserves_wf_ac A tr op hWF hAC hActive
    hCanonical
  exact ⟨hLifecycle.1, hLifecycle.2.1, hLifecycle.2.2,
    afterCanonical_preserves_valid hv hCanonical hOwner,
    afterCanonical_actual_step A tr op hCanonical,
    afterCanonical_version_of_check p tr offered hVersion⟩

#print axioms afterTransferCore_preserves_valid
#print axioms afterCanonical_preserves_valid
#print axioms afterCanonical_preserves_headPhaseBound
#print axioms afterCanonical_checked_valid
#print axioms checkCanonicalPlan_sound
#print axioms checkedCanonical_preserves_all

end PlanData

end AuthorityContinuity.PlanInvariant
