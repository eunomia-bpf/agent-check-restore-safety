import AuthorityContinuity.PlanInvariant

/-!
# Computed plan transport for authority restriction

This module lifts the repository's exact `restrictLifecycle` transition to the
multi-slot controller.  Restriction terminalizes tentative claims excluded by
the retained owner/claim sets, but leaves capacity, demand, durable claims,
and the schedule ledger unchanged.  Consequently the computed controller
target only increments its compare-and-swap version and filters `remaining`
through the actual lifecycle target.

No target validity, readiness, load inequality, or caller-provided target plan
is a premise.  The cursor is recomputed from the filtered owner groups.
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

/-- Exact plan target paired with `restrictLifecycle A owners keep`.

The immutable root/schedule rows and durable baseline remain authoritative.
Only claims that are still tentative in the *actual* lifecycle target remain
in the selected batch. -/
def afterRestriction
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (owners : Finset Branch) (keep : Finset Claim) :
    PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot) :=
  let A' := restrictLifecycle A owners keep
  { p with
    version := p.version + 1
    remaining := p.remaining.filter fun c =>
      ∃ b, A'.auth.status c = .tentative b }

@[simp] theorem afterRestriction_version
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (owners : Finset Branch) (keep : Finset Claim) :
    (p.afterRestriction A owners keep).version = p.version + 1 := rfl

/-- A tentative target claim was tentative under the same owner at source. -/
theorem restrictLifecycle_tentative_source
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (owners : Finset Branch) (keep : Finset Claim)
    {c : Claim} {b : Branch}
    (h : (restrictLifecycle A owners keep).auth.status c = .tentative b) :
    A.auth.status c = .tentative b := by
  change (A.auth.restrictStateBy owners keep).status c = .tentative b at h
  exact (State.restrictStateBy_status_tentative_iff
    A.auth owners keep c b).1 h |>.1

/-- Filtering the selected batch never adds a claim. -/
theorem afterRestriction_remaining_subset
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (owners : Finset Branch) (keep : Finset Claim) :
    (p.afterRestriction A owners keep).remaining ⊆ p.remaining := by
  intro c hc
  simpa [afterRestriction] using (Finset.mem_filter.mp hc).1

/-- The target selected batch is a subset of the source batch in every root. -/
theorem afterRestriction_rootRemaining_subset
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (owners : Finset Branch) (keep : Finset Claim) (s : Slot) :
    (p.afterRestriction A owners keep).rootRemaining s ⊆
      p.rootRemaining s := by
  intro c hc
  simp only [rootRemaining, Finset.mem_filter] at hc ⊢
  exact ⟨afterRestriction_remaining_subset A p owners keep hc.1,
    by simpa [afterRestriction] using hc.2⟩

/-- Restriction can only remove live tentative claims from a root fiber. -/
theorem afterRestriction_tentativeRootClaims_subset
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (owners : Finset Branch) (keep : Finset Claim) (s : Slot) :
    (p.afterRestriction A owners keep).tentativeRootClaims
        (restrictLifecycle A owners keep) s ⊆
      p.tentativeRootClaims A s := by
  intro c hc
  simp only [tentativeRootClaims, Finset.mem_filter, Finset.mem_univ,
    true_and] at hc ⊢
  rcases hc with ⟨hroot, b, hstatus⟩
  exact ⟨by simpa [afterRestriction] using hroot,
    ⟨b, restrictLifecycle_tentative_source A owners keep hstatus⟩⟩

/-- Every target active `(slot, owner)` group was active at source. -/
theorem afterRestriction_activeGroups_subset
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (owners : Finset Branch) (keep : Finset Claim) :
    (p.afterRestriction A owners keep).activeGroups
        (restrictLifecycle A owners keep) ⊆
      p.activeGroups A := by
  intro sb hsb
  simp only [activeGroups, Finset.mem_filter, Finset.mem_univ,
    true_and] at hsb ⊢
  obtain ⟨c, hc⟩ := hsb
  simp only [ownerGroup, rootRemaining, Finset.mem_filter] at hc
  refine ⟨c, ?_⟩
  simp only [ownerGroup, rootRemaining, Finset.mem_filter]
  refine ⟨⟨?_, ?_⟩, ?_⟩
  · exact afterRestriction_remaining_subset A p owners keep hc.1.1
  · simpa [afterRestriction] using hc.1.2
  · exact restrictLifecycle_tentative_source A owners keep hc.2

/-- A nonempty active-group set gives an executable `firstGroup`. -/
theorem firstGroup_exists_of_active
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (hne : (p.activeGroups A).Nonempty) :
    ∃ g, p.firstGroup A = some g := by
  unfold firstGroup
  simp [hne]

/-- Recomputing the cursor after restriction cannot move it earlier. -/
theorem afterRestriction_firstSlot_mono
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (owners : Finset Branch) (keep : Finset Claim)
    {t : Slot} {b' : Branch}
    (hTarget : (p.afterRestriction A owners keep).firstGroup
      (restrictLifecycle A owners keep) = some (t, b')) :
    ∃ s b, p.firstGroup A = some (s, b) ∧ s <= t := by
  have hTargetMem := firstGroup_mem hTarget
  have hSourceMem := afterRestriction_activeGroups_subset
    A p owners keep hTargetMem
  obtain ⟨g, hg⟩ := firstGroup_exists_of_active A p
    ⟨toLex (t, b'), hSourceMem⟩
  rcases g with ⟨s, b⟩
  have hLex := firstGroup_le_active hg hSourceMem
  have hslot : s <= t := by
    simpa using Prod.Lex.monotone_fst
      (toLex (s, b)) (toLex (t, b')) hLex
  exact ⟨s, b, hg, hslot⟩

/-- Actual live load decreases pointwise under exact restriction. -/
theorem afterRestriction_L_le
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (owners : Finset Branch) (keep : Finset Claim)
    (s : Slot) (k : Coord) :
    (p.afterRestriction A owners keep).L
        (restrictLifecycle A owners keep) s k <= p.L A s k := by
  unfold L
  change
    (∑ c ∈ (p.afterRestriction A owners keep).tentativeRootClaims
        (restrictLifecycle A owners keep) s,
      A.auth.demand c k) <=
    ∑ c ∈ p.tentativeRootClaims A s, A.auth.demand c k
  exact Finset.sum_le_sum_of_subset
    (afterRestriction_tentativeRootClaims_subset A p owners keep s)

/-- Remaining selected-batch load decreases pointwise under restriction. -/
theorem afterRestriction_B_le
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (owners : Finset Branch) (keep : Finset Claim)
    (s : Slot) (k : Coord) :
    (p.afterRestriction A owners keep).B
        (restrictLifecycle A owners keep) s k <= p.B A s k := by
  unfold B Plan.batchLoad
  change
    (∑ c ∈ (p.afterRestriction A owners keep).rootRemaining s,
      A.auth.demand c k) <=
    ∑ c ∈ p.rootRemaining s, A.auth.demand c k
  exact Finset.sum_le_sum_of_subset
    (afterRestriction_rootRemaining_subset A p owners keep s)

/-- The exact restriction target preserves the complete controller invariant.
Every target field is reconstructed from source validity and subset facts. -/
theorem afterRestriction_preserves_valid
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (owners : Finset Branch) (keep : Finset Claim)
    (hv : p.Valid A) :
    (p.afterRestriction A owners keep).Valid
      (restrictLifecycle A owners keep) := by
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
    change A.auth.capacity k = p.cap0 k
    exact hv.capacity_eq k
  · intro c hc
    have hcFilter : c ∈ p.remaining ∧
        ∃ b, (restrictLifecycle A owners keep).auth.status c =
          .tentative b := by
      simpa [afterRestriction] using hc
    obtain ⟨b, hb⟩ := hcFilter.2
    obtain ⟨_, s, _, hs, hroot⟩ := hv.remaining_rooted c hcFilter.1
    exact ⟨b, s, hb, by simpa [afterRestriction] using hs,
      by simpa [afterRestriction] using hroot⟩
  · intro c c' b hc hc'
    change p.rootSlot c = p.rootSlot c'
    exact hv.owner_root_pure c c' b
      (restrictLifecycle_tentative_source A owners keep hc)
      (restrictLifecycle_tentative_source A owners keep hc')
  · intro c s hroot
    apply hv.root_mem c s
    simpa [afterRestriction] using hroot
  · intro s hs k
    exact hv.E_outside_zero s (by simpa [afterRestriction] using hs) k
  · intro s hs k
    exact hv.P_outside_zero s (by simpa [afterRestriction] using hs) k
  · intro k
    change (A.auth.restrictStateBy owners keep).durableLoad k =
      p.d0 k + p.totalE k
    rw [State.restrictStateBy_durableLoad]
    exact hv.durable_eq k
  · intro s hs k
    have hOld := hv.envelope s
      (by simpa [afterRestriction] using hs) k
    have hLoad := afterRestriction_L_le A p owners keep s k
    change
      (p.afterRestriction A owners keep).L
          (restrictLifecycle A owners keep) s k + p.E s k <= p.R s k
    omega
  · intro s hs k
    exact hv.deadline s (by simpa [afterRestriction] using hs) k
  · intro s hs k
    have hOld := hv.batch_bound s
      (by simpa [afterRestriction] using hs) k
    have hBatch := afterRestriction_B_le A p owners keep s k
    change
      (p.afterRestriction A owners keep).B
          (restrictLifecycle A owners keep) s k + p.E s k <= p.P s k
    omega
  · intro t b' hTarget u hu htu k
    obtain ⟨s, b, hSource, hst⟩ :=
      afterRestriction_firstSlot_mono A p owners keep hTarget
    have huSource : u ∈ p.slots := by
      simpa [afterRestriction] using hu
    have hZero := hv.cursor_phase s b hSource u huSource
      (lt_of_le_of_lt hst htu) k
    simpa [afterRestriction] using hZero

/-- Exact restriction is an actual transition of the sole paper-facing
lifecycle relation; no side condition or target certificate is admitted. -/
theorem afterRestriction_actual_step
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (owners : Finset Branch) (keep : Finset Claim) :
    Step A .tau (restrictLifecycle A owners keep) :=
  Step.core (CoreStep.restriction A owners keep)

/-- Full restriction gate, including lifecycle safety and exact activity. -/
theorem afterRestriction_preserves_all
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (owners : Finset Branch) (keep : Finset Claim)
    (hWF : A.LWF) (hAC : AC A.auth) (hActive : ActiveExact A)
    (hv : p.Valid A) :
    let A' := restrictLifecycle A owners keep
    A'.LWF ∧ AC A'.auth ∧ ActiveExact A' ∧
      (p.afterRestriction A owners keep).Valid A' ∧
      Step A .tau A' := by
  dsimp
  have hCore := restriction_lifecycle_preserves_wf_ac
    A owners keep hWF hAC
  have hExact := restriction_lifecycle_preserves_active_exact
    A owners keep hWF hActive
  exact ⟨hCore.1, hCore.2, hExact,
    afterRestriction_preserves_valid A p owners keep hv,
    afterRestriction_actual_step A owners keep⟩

/-! ## Actual Revoke specialization -/

/-- `Valid` depends on a lifecycle only through its authority projection.
This small congruence bridge is useful for operations, such as Revoke, that
also update controller epochs outside the plan arithmetic. -/
theorem Valid.transport_auth
    {A A' : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    (hv : p.Valid A) (hAuth : A'.auth = A.auth) : p.Valid A' := by
  refine {
    capacity_eq := ?_
    remaining_rooted := ?_
    owner_root_pure := ?_
    root_mem := hv.root_mem
    E_outside_zero := hv.E_outside_zero
    P_outside_zero := hv.P_outside_zero
    durable_eq := ?_
    envelope := ?_
    deadline := hv.deadline
    batch_bound := ?_
    cursor_phase := ?_ }
  · intro k
    rw [hAuth]
    exact hv.capacity_eq k
  · intro c hc
    obtain ⟨b, s, hb, hs, hroot⟩ := hv.remaining_rooted c hc
    exact ⟨b, s, by simpa [hAuth] using hb, hs, hroot⟩
  · intro c c' b hc hc'
    apply hv.owner_root_pure c c' b
    · simpa [hAuth] using hc
    · simpa [hAuth] using hc'
  · intro k
    simpa [DurableEq, hAuth] using hv.durable_eq k
  · simpa [Envelope, L, tentativeRootClaims, hAuth] using hv.envelope
  · simpa [BatchBound, B, Plan.batchLoad, rootRemaining, hAuth] using
      hv.batch_bound
  · simpa [CursorPhase, firstGroup, activeGroups, ownerGroup, rootRemaining,
      hAuth] using hv.cursor_phase

/-- Claims retained by the repository's exact grant-epoch Revoke. -/
def revokeKeep
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (g : Grant) : Finset Claim :=
  Finset.univ.filter fun c => A.grantOf c ≠ g

/-- Revoke has the same authority drop as unrestricted-owner restriction;
the actual lifecycle target additionally closes grant epoch `g`. -/
def afterRevoke
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (g : Grant) :
    PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot) :=
  p.afterRestriction A Finset.univ (revokeKeep A g)

@[simp] theorem afterRevoke_version
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (g : Grant) :
    (p.afterRevoke A g).version = p.version + 1 := rfl

/-- The controller certificate sees the exact Revoke authority target; the
additional grant-epoch update is carried by lifecycle well-formedness. -/
theorem afterRevoke_preserves_valid
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (g : Grant) (hv : p.Valid A) :
    (p.afterRevoke A g).Valid (revokeState A g) := by
  have hRestriction := afterRestriction_preserves_valid
    A p Finset.univ (revokeKeep A g) hv
  apply hRestriction.transport_auth
  rfl

/-- Revoke is an actual transition of the sole lifecycle relation. -/
theorem afterRevoke_actual_step
    (A : LifecycleState Coord Claim Branch Grant Operation) (g : Grant) :
    Step A .tau (revokeState A g) :=
  Step.core (CoreStep.revoke A g)

/-- Full actual-Revoke gate with computed plan transport. -/
theorem afterRevoke_preserves_all
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (g : Grant)
    (hWF : A.LWF) (hAC : AC A.auth) (hActive : ActiveExact A)
    (hv : p.Valid A) :
    let A' := revokeState A g
    A'.LWF ∧ AC A'.auth ∧ ActiveExact A' ∧
      (p.afterRevoke A g).Valid A' ∧ Step A .tau A' := by
  dsimp
  have hSafe := step_preserves_wf_ac (afterRevoke_actual_step A g)
    hWF hAC hActive
  exact ⟨hSafe.1, hSafe.2.1, hSafe.2.2,
    afterRevoke_preserves_valid A p g hv,
    afterRevoke_actual_step A g⟩

/-! ## Version-checked paper-facing restriction relation -/

def advanceRestriction
    (S : InvariantState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot))
    (owners : Finset Branch) (keep : Finset Claim) :
    InvariantState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot) where
  lifecycle := restrictLifecycle S.lifecycle owners keep
  plan := S.plan.afterRestriction S.lifecycle owners keep

/-- Authoritative restriction requires the durable plan version CAS and uses
only the computed lifecycle/controller target. -/
inductive RestrictionPlanned :
    InvariantState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot) ->
    Nat -> Finset Branch -> Finset Claim ->
    InvariantState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot) -> Prop where
  | mk {S offered owners keep}
      (hVersion : S.plan.checkVersion offered = true) :
      RestrictionPlanned S offered owners keep
        (advanceRestriction S owners keep)

theorem RestrictionPlanned.version_sound
    {S S' : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)}
    {offered : Nat} {owners : Finset Branch} {keep : Finset Claim}
    (h : RestrictionPlanned S offered owners keep S') :
    offered = S.plan.version := by
  cases h with
  | mk hVersion => exact checkVersion_sound _ _ hVersion

theorem RestrictionPlanned.version_succ
    {S S' : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)}
    {offered : Nat} {owners : Finset Branch} {keep : Finset Claim}
    (h : RestrictionPlanned S offered owners keep S') :
    S'.plan.version = S.plan.version + 1 := by
  cases h
  rfl

theorem RestrictionPlanned.actual_step
    {S S' : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)}
    {offered : Nat} {owners : Finset Branch} {keep : Finset Claim}
    (h : RestrictionPlanned S offered owners keep S') :
    Step S.lifecycle .tau S'.lifecycle := by
  cases h
  exact afterRestriction_actual_step _ _ _

theorem RestrictionPlanned.preserves_valid
    {S S' : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)}
    {offered : Nat} {owners : Finset Branch} {keep : Finset Claim}
    (h : RestrictionPlanned S offered owners keep S')
    (hv : S.plan.Valid S.lifecycle) :
    S'.plan.Valid S'.lifecycle := by
  cases h
  exact afterRestriction_preserves_valid _ _ _ _ hv

theorem RestrictionPlanned.preserves_all
    {S S' : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)}
    {offered : Nat} {owners : Finset Branch} {keep : Finset Claim}
    (h : RestrictionPlanned S offered owners keep S')
    (hWF : S.lifecycle.LWF) (hAC : AC S.lifecycle.auth)
    (hActive : ActiveExact S.lifecycle)
    (hv : S.plan.Valid S.lifecycle) :
    S'.lifecycle.LWF ∧ AC S'.lifecycle.auth ∧
      ActiveExact S'.lifecycle ∧ S'.plan.Valid S'.lifecycle ∧
      Step S.lifecycle .tau S'.lifecycle := by
  cases h
  simpa [advanceRestriction] using
    afterRestriction_preserves_all S.lifecycle S.plan owners keep
      hWF hAC hActive hv

/-! ## Version-checked actual Revoke relation -/

def advanceRevoke
    (S : InvariantState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot))
    (g : Grant) :
    InvariantState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot) where
  lifecycle := revokeState S.lifecycle g
  plan := S.plan.afterRevoke S.lifecycle g

/-- The actual grant-epoch Revoke also participates in the durable plan CAS;
there is no unversioned paper-facing mutation path. -/
inductive RevokePlanned :
    InvariantState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot) ->
    Nat -> Grant ->
    InvariantState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot) -> Prop where
  | mk {S offered g}
      (hVersion : S.plan.checkVersion offered = true) :
      RevokePlanned S offered g (advanceRevoke S g)

theorem RevokePlanned.version_sound
    {S S' : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)}
    {offered : Nat} {g : Grant} (h : RevokePlanned S offered g S') :
    offered = S.plan.version := by
  cases h with
  | mk hVersion => exact checkVersion_sound _ _ hVersion

theorem RevokePlanned.version_succ
    {S S' : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)}
    {offered : Nat} {g : Grant} (h : RevokePlanned S offered g S') :
    S'.plan.version = S.plan.version + 1 := by
  cases h
  rfl

theorem RevokePlanned.actual_step
    {S S' : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)}
    {offered : Nat} {g : Grant} (h : RevokePlanned S offered g S') :
    Step S.lifecycle .tau S'.lifecycle := by
  cases h
  exact afterRevoke_actual_step _ _

theorem RevokePlanned.preserves_valid
    {S S' : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)}
    {offered : Nat} {g : Grant} (h : RevokePlanned S offered g S')
    (hv : S.plan.Valid S.lifecycle) : S'.plan.Valid S'.lifecycle := by
  cases h
  exact afterRevoke_preserves_valid _ _ _ hv

theorem RevokePlanned.preserves_all
    {S S' : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)}
    {offered : Nat} {g : Grant} (h : RevokePlanned S offered g S')
    (hWF : S.lifecycle.LWF) (hAC : AC S.lifecycle.auth)
    (hActive : ActiveExact S.lifecycle)
    (hv : S.plan.Valid S.lifecycle) :
    S'.lifecycle.LWF ∧ AC S'.lifecycle.auth ∧
      ActiveExact S'.lifecycle ∧ S'.plan.Valid S'.lifecycle ∧
      Step S.lifecycle .tau S'.lifecycle := by
  cases h
  simpa [advanceRevoke] using
    afterRevoke_preserves_all S.lifecycle S.plan g hWF hAC hActive hv

#print axioms afterRestriction_preserves_valid
#print axioms afterRestriction_actual_step
#print axioms afterRestriction_preserves_all
#print axioms afterRevoke_preserves_valid
#print axioms afterRevoke_actual_step
#print axioms afterRevoke_preserves_all
#print axioms RestrictionPlanned.preserves_all
#print axioms RevokePlanned.preserves_all

end PlanData

end AuthorityContinuity.PlanInvariant
