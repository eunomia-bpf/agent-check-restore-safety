import AuthorityContinuity.Checker

/-!
# Lifecycle semantics

This module adds the temporal state that is deliberately absent from a
reconstructable checkpoint: monotone branch/grant epochs and stable protected
operation tickets.  Authority-changing derived operations below compute their
target; only Reserve and direct-admission Merge use the executable target AC
checker.
-/

namespace AuthorityContinuity

inductive EpochStatus where
  | unissued
  | open
  | closed
  deriving DecidableEq, Repr

/-- Epoch evolution permits a fresh opening and irreversible closure. -/
def EpochStatus.Advances : EpochStatus → EpochStatus → Prop
  | .unissued, _ => True
  | .open, .open | .open, .closed => True
  | .closed, .closed => True
  | _, _ => False

theorem EpochStatus.Advances.refl (s : EpochStatus) : s.Advances s := by
  cases s <;> trivial

theorem EpochStatus.Advances.trans {s₁ s₂ s₃ : EpochStatus}
    (h₁₂ : s₁.Advances s₂) (h₂₃ : s₂.Advances s₃) :
    s₁.Advances s₃ := by
  cases s₁ <;> cases s₂ <;> cases s₃ <;>
    simp [EpochStatus.Advances] at h₁₂ h₂₃ ⊢

theorem EpochStatus.Advances.closed_eq {s : EpochStatus}
    (h : EpochStatus.closed.Advances s) : s = .closed := by
  cases s <;> simp [EpochStatus.Advances] at h ⊢

inductive TicketPhase where
  | prepared
  | inflight
  | uncertain
  deriving DecidableEq, Repr

structure Ticket (Claim : Type*) where
  claim : Claim
  phase : TicketPhase
  deriving DecidableEq, Repr

inductive ReceiptOutcome where
  | succeeded
  | failed
  | cancelled
  deriving DecidableEq, Repr

structure Receipt (Claim : Type*) where
  claim : Claim
  outcome : ReceiptOutcome
  deriving DecidableEq, Repr

/-- Durable controller state layered over the finite authority core. -/
structure LifecycleState
    (Coord Claim Branch Grant Operation : Type*) where
  auth : State Coord Claim Branch
  grantOf : Claim → Grant
  branchEpoch : Branch → EpochStatus
  grantEpoch : Grant → EpochStatus
  tickets : Operation → Option (Ticket Claim)
  receipts : Operation → Option (Receipt Claim)

namespace LifecycleState

variable {Coord Claim Branch Grant Operation : Type*}

def opClaim (A : LifecycleState Coord Claim Branch Grant Operation)
    (e : Operation) : Option Claim :=
  match A.tickets e with
  | some t => some t.claim
  | none => (A.receipts e).map Receipt.claim

def claimOpen (A : LifecycleState Coord Claim Branch Grant Operation)
    (c : Claim) : Prop :=
  A.grantEpoch (A.grantOf c) = .open

def EpochMonotone
    (A A' : LifecycleState Coord Claim Branch Grant Operation) : Prop :=
  (∀ b, (A.branchEpoch b).Advances (A'.branchEpoch b)) ∧
  (∀ g, (A.grantEpoch g).Advances (A'.grantEpoch g))

def TerminalMonotone
    (A A' : LifecycleState Coord Claim Branch Grant Operation) : Prop :=
  ∀ c, A.auth.status c = .terminal → A'.auth.status c = .terminal

/-- Lifecycle well-formedness extends core well-formedness with open-owner and
stable one-shot effect binding obligations. -/
structure LWF
    [Fintype Claim] [DecidableEq Claim] [DecidableEq Branch]
    (A : LifecycleState Coord Claim Branch Grant Operation) : Prop where
  core : WF A.auth
  configuration_open : ∀ C ∈ A.auth.allowed, ∀ b ∈ C,
    A.branchEpoch b = .open
  owner_open : ∀ c b, A.auth.status c = .tentative b →
    A.branchEpoch b = .open
  grant_open : ∀ c b, A.auth.status c = .tentative b →
    A.claimOpen c
  ticket_receipt_disjoint : ∀ e t r,
    A.tickets e = some t → A.receipts e = some r → False
  bound_durable : ∀ e c, A.opClaim e = some c →
    A.auth.status c = .durable
  binding_injective : ∀ e e' c,
    A.opClaim e = some c → A.opClaim e' = some c → e = e'

variable [Fintype Coord] [DecidableEq Coord]
variable [Fintype Claim] [DecidableEq Claim]
variable [Fintype Branch] [DecidableEq Branch]

/-- Status after moving exactly `U` from tentative to durable, before cleanup. -/
def rawPromotion (A : State Coord Claim Branch) (U : Finset Claim) :
    State Coord Claim Branch where
  capacity := A.capacity
  demand := A.demand
  status c := if c ∈ U then .durable else A.status c
  allowed := A.allowed

/-- The exact frozen promotion row: retain precisely source configurations
solvent after the whole batch has become durable. -/
def guardedAllowed (A : State Coord Claim Branch) (U : Finset Claim) :
    Finset (Finset Branch) :=
  AuthorityContinuity.guardedAllowed A U

/-- Owners with a remaining nonempty tentative bundle but no configuration in
the exact guarded contract.  This is a deterministic finite computation. -/
def unsupportedOwners (A : State Coord Claim Branch) (U : Finset Claim) :
    Finset Branch :=
  Finset.univ.filter fun b =>
    (∃ c, (rawPromotion A U).status c = .tentative b) ∧
    ¬ ∃ C ∈ guardedAllowed A U, b ∈ C

def preparedStatus (A : State Coord Claim Branch) (U : Finset Claim)
    (c : Claim) : ClaimStatus Branch :=
  match (rawPromotion A U).status c with
  | .tentative b => if b ∈ unsupportedOwners A U then .terminal else .tentative b
  | s => s

/-- Explicit contract restriction away from unsupported owners. -/
def cleanedAllowed (A : State Coord Claim Branch) (U : Finset Claim) :
    Finset (Finset Branch) :=
  (guardedAllowed A U).filter fun C =>
    Disjoint C (unsupportedOwners A U)

/-- Exact Prepare/cleanup authority target. -/
def preparedCore (A : State Coord Claim Branch) (U : Finset Claim) :
    State Coord Claim Branch where
  capacity := A.capacity
  demand := A.demand
  status := preparedStatus A U
  allowed := cleanedAllowed A U

@[simp]
theorem rawPromotion_capacity (A : State Coord Claim Branch)
    (U : Finset Claim) : (rawPromotion A U).capacity = A.capacity := rfl

@[simp]
theorem rawPromotion_demand (A : State Coord Claim Branch)
    (U : Finset Claim) : (rawPromotion A U).demand = A.demand := rfl

@[simp]
theorem mem_guardedAllowed_iff (A : State Coord Claim Branch)
    (U : Finset Claim) (C : Finset Branch) :
    C ∈ guardedAllowed A U ↔
      C ∈ A.allowed ∧
      ∀ k, promotedLoad A U k + remainingConditionalLoad A U C k ≤
        A.capacity k := by
  exact guardClosure_iff A U C

theorem guarded_configuration_excludes_unsupported
    (A : State Coord Claim Branch) (U : Finset Claim)
    {C : Finset Branch} (hC : C ∈ guardedAllowed A U) :
    Disjoint C (unsupportedOwners A U) := by
  rw [Finset.disjoint_left]
  intro b hbC hbZ
  have hz := (Finset.mem_filter.mp hbZ).2
  exact hz.2 ⟨C, hC, hbC⟩

@[simp]
theorem cleanedAllowed_eq_guardedAllowed
    (A : State Coord Claim Branch) (U : Finset Claim) :
    cleanedAllowed A U = guardedAllowed A U := by
  ext C
  constructor
  · intro h
    exact (Finset.mem_filter.mp h).1
  · intro h
    exact Finset.mem_filter.mpr
      ⟨h, guarded_configuration_excludes_unsupported A U h⟩

@[simp]
theorem rawPromotion_durableLoad_eq_promotedLoad
    (A : State Coord Claim Branch) (U : Finset Claim)
    (hU : ∀ c ∈ U, ∃ b, A.status c = .tentative b) (k : Coord) :
    (rawPromotion A U).durableLoad k = promotedLoad A U k := by
  have hclaims : (rawPromotion A U).durableClaims = A.durableClaims ∪ U := by
    ext c
    by_cases hc : c ∈ U <;> simp [State.durableClaims, rawPromotion, hc]
  have hdisj : Disjoint A.durableClaims U := by
    rw [Finset.disjoint_left]
    intro c hcD hcU
    obtain ⟨b, htent⟩ := hU c hcU
    have hdurable : A.status c = .durable := by
      simpa [State.durableClaims] using hcD
    simp [htent] at hdurable
  unfold State.durableLoad promotedLoad
  rw [hclaims, Finset.sum_union hdisj]
  rfl

@[simp]
theorem rawPromotion_conditionalLoad_eq_remaining
    (A : State Coord Claim Branch) (U : Finset Claim)
    (C : Finset Branch) (k : Coord) :
    (rawPromotion A U).conditionalLoad C k =
      remainingConditionalLoad A U C k := by
  have hclaims : (rawPromotion A U).conditionalClaims C =
      A.conditionalClaims C \ U := by
    ext c
    by_cases hc : c ∈ U
    · simp [State.conditionalClaims, rawPromotion, hc]
    · cases hs : A.status c <;>
        simp [State.conditionalClaims, rawPromotion, hc, hs]
  unfold State.conditionalLoad remainingConditionalLoad
  rw [hclaims]
  rfl

theorem rawPromotion_status_tentative_iff
    (A : State Coord Claim Branch) (U : Finset Claim) (c : Claim) (b : Branch) :
    (rawPromotion A U).status c = .tentative b ↔
      A.status c = .tentative b ∧ c ∉ U := by
  by_cases hc : c ∈ U <;> simp [rawPromotion, hc]

theorem preparedStatus_tentative_iff
    (A : State Coord Claim Branch) (U : Finset Claim) (c : Claim) (b : Branch) :
    preparedStatus A U c = .tentative b ↔
      (rawPromotion A U).status c = .tentative b ∧
      b ∉ unsupportedOwners A U := by
  cases hs : (rawPromotion A U).status c with
  | unissued => simp [preparedStatus, hs]
  | durable => simp [preparedStatus, hs]
  | terminal => simp [preparedStatus, hs]
  | tentative owner =>
      by_cases ho : owner ∈ unsupportedOwners A U <;>
        simp [preparedStatus, hs, ho] <;> aesop

theorem preparedStatus_durable_iff
    (A : State Coord Claim Branch) (U : Finset Claim) (c : Claim) :
    preparedStatus A U c = .durable ↔
      (rawPromotion A U).status c = .durable := by
  cases hs : (rawPromotion A U).status c with
  | unissued => simp [preparedStatus, hs]
  | durable => simp [preparedStatus, hs]
  | terminal => simp [preparedStatus, hs]
  | tentative owner =>
      by_cases ho : owner ∈ unsupportedOwners A U <;>
        simp [preparedStatus, hs, ho]

@[simp]
theorem preparedCore_durableLoad (A : State Coord Claim Branch)
    (U : Finset Claim) (k : Coord) :
    (preparedCore A U).durableLoad k = (rawPromotion A U).durableLoad k := by
  unfold State.durableLoad State.durableClaims
  apply Finset.sum_congr
  · ext c
    simp only [Finset.mem_filter, Finset.mem_univ, true_and]
    exact preparedStatus_durable_iff A U c
  · intro c hc
    rfl

theorem preparedCore_conditionalLoad_le (A : State Coord Claim Branch)
    (U : Finset Claim) (C : Finset Branch) (k : Coord) :
    (preparedCore A U).conditionalLoad C k ≤
      (rawPromotion A U).conditionalLoad C k := by
  apply Finset.sum_le_sum_of_subset
  intro c hc
  simp only [State.conditionalClaims, Finset.mem_filter, Finset.mem_univ,
    true_and] at hc ⊢
  cases hs : (rawPromotion A U).status c with
  | unissued => simp [preparedCore, preparedStatus, hs] at hc
  | durable => simp [preparedCore, preparedStatus, hs] at hc
  | terminal => simp [preparedCore, preparedStatus, hs] at hc
  | tentative b =>
      by_cases hb : b ∈ unsupportedOwners A U
      · simp [preparedCore, preparedStatus, hs, hb] at hc
      · simpa [preparedCore, preparedStatus, hs, hb] using hc

/-- Exact promotion guard plus deterministic unsupported-owner cleanup derives
core WF and AC.  `base` is the paper's `a_U ≤ G` premise. -/
theorem preparedCore_preserves_wf_ac
    (A : State Coord Claim Branch) (U : Finset Claim)
    (hWF : WF A) (_hAC : AC A)
    (hU : ∀ c ∈ U, ∃ b, A.status c = .tentative b)
    (base : ∀ k, promotedLoad A U k ≤ A.capacity k) :
    WF (preparedCore A U) ∧ AC (preparedCore A U) := by
  classical
  constructor
  · constructor
    · change ∅ ∈ cleanedAllowed A U
      rw [cleanedAllowed_eq_guardedAllowed]
      rw [mem_guardedAllowed_iff]
      refine ⟨hWF.empty_mem, ?_⟩
      intro k
      have hzero : remainingConditionalLoad A U ∅ k = 0 := by
        unfold remainingConditionalLoad State.conditionalClaims
        apply Finset.sum_eq_zero
        intro c hc
        simp only [Finset.mem_sdiff, Finset.mem_filter, Finset.mem_univ,
          true_and] at hc
        cases hs : A.status c <;> simp [hs] at hc
      simpa [hzero] using base k
    · intro C C' hC hsub
      change C ∈ cleanedAllowed A U at hC
      change C' ∈ cleanedAllowed A U
      rw [cleanedAllowed_eq_guardedAllowed] at hC ⊢
      rw [mem_guardedAllowed_iff] at hC ⊢
      refine ⟨hWF.downward hC.1 hsub, ?_⟩
      intro k
      have hmono : remainingConditionalLoad A U C' k ≤
          remainingConditionalLoad A U C k := by
        simpa [rawPromotion_conditionalLoad_eq_remaining] using
          State.conditionalLoad_mono (rawPromotion A U) hsub k
      exact le_trans
        (Nat.add_le_add_left hmono _)
        (hC.2 k)
    · intro c b hstatus
      rw [preparedCore, preparedStatus_tentative_iff] at hstatus
      refine Classical.byContradiction fun hnone => ?_
      change ¬ ∃ C ∈ cleanedAllowed A U, b ∈ C at hnone
      rw [cleanedAllowed_eq_guardedAllowed] at hnone
      have hbUnsupported : b ∈ unsupportedOwners A U := by
        simp only [unsupportedOwners, Finset.mem_filter, Finset.mem_univ, true_and]
        exact ⟨⟨c, hstatus.1⟩, hnone⟩
      exact hstatus.2 hbUnsupported
  · intro C hC k
    change C ∈ cleanedAllowed A U at hC
    rw [cleanedAllowed_eq_guardedAllowed] at hC
    change (preparedCore A U).durableLoad k +
      (preparedCore A U).conditionalLoad C k ≤ A.capacity k
    rw [mem_guardedAllowed_iff] at hC
    rw [preparedCore_durableLoad,
      rawPromotion_durableLoad_eq_promotedLoad A U hU k]
    exact le_trans
      (Nat.add_le_add_left (preparedCore_conditionalLoad_le A U C k) _)
      (by simpa [rawPromotion_conditionalLoad_eq_remaining] using hC.2 k)

variable {Grant Operation : Type*}
variable [DecidableEq Grant] [DecidableEq Operation]

@[simp]
theorem opClaim_eq_none_iff
    (A : LifecycleState Coord Claim Branch Grant Operation) (e : Operation) :
    A.opClaim e = none ↔ A.tickets e = none ∧ A.receipts e = none := by
  unfold opClaim
  cases ht : A.tickets e with
  | some t => simp [ht]
  | none =>
      cases hr : A.receipts e with
      | none => simp [ht, hr]
      | some r => simp [ht, hr]

/-- Exact lifecycle target of atomic Prepare.  The assignment is installed in
the same durable step as promotion, the frozen guard, and owner cleanup. -/
def prepareState
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (U : Finset Claim) (assignment : Operation → Option Claim) :
    LifecycleState Coord Claim Branch Grant Operation where
  auth := preparedCore A.auth U
  grantOf := A.grantOf
  branchEpoch b :=
    if b ∈ unsupportedOwners A.auth U then .closed else A.branchEpoch b
  grantEpoch := A.grantEpoch
  tickets e :=
    match assignment e with
    | some c => some ⟨c, .prepared⟩
    | none => A.tickets e
  receipts := A.receipts

/-- Rule-local premises of Prepare.  In particular, this contains no target
WF or target AC proposition. -/
structure PrepareOK
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (U : Finset Claim) (assignment : Operation → Option Claim) : Prop where
  nonempty : U.Nonempty
  member_open : ∀ c ∈ U, ∃ b,
    A.auth.status c = .tentative b ∧
    A.branchEpoch b = .open ∧ A.claimOpen c
  base : ∀ k, promotedLoad A.auth U k ≤ A.auth.capacity k
  assigned_mem : ∀ e c, assignment e = some c → c ∈ U
  covered : ∀ c ∈ U, ∃ e, assignment e = some c
  assignment_injective : ∀ e e' c,
    assignment e = some c → assignment e' = some c → e = e'
  fresh : ∀ e c, assignment e = some c → A.opClaim e = none

theorem prepareState_opClaim
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (U : Finset Claim) (assignment : Operation → Option Claim)
    (e : Operation) :
    (prepareState A U assignment).opClaim e =
      match assignment e with
      | some c => some c
      | none => A.opClaim e := by
  unfold opClaim prepareState
  cases ha : assignment e <;> simp [ha, opClaim]

/-- Atomic Prepare with exact cleanup preserves both lifecycle well-formedness
and authority continuity without assuming either property of its target. -/
theorem prepare_preserves_wf_ac
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (U : Finset Claim) (assignment : Operation → Option Claim)
    (hWF : LWF A) (hAC : AC A.auth)
    (hOK : PrepareOK A U assignment) :
    LWF (prepareState A U assignment) ∧
      AC (prepareState A U assignment).auth := by
  classical
  have hmembers : ∀ c ∈ U, ∃ b, A.auth.status c = .tentative b := by
    intro c hc
    obtain ⟨b, hs, -, -⟩ := hOK.member_open c hc
    exact ⟨b, hs⟩
  have hcore := preparedCore_preserves_wf_ac A.auth U hWF.core hAC
    hmembers hOK.base
  constructor
  · refine ⟨hcore.1, ?_, ?_, ?_, ?_, ?_, ?_⟩
    · intro C hC b hbC
      change C ∈ cleanedAllowed A.auth U at hC
      have hdisj := (Finset.mem_filter.mp hC).2
      have hbNot : b ∉ unsupportedOwners A.auth U :=
        Finset.disjoint_left.mp hdisj hbC
      have hguard : C ∈ guardedAllowed A.auth U :=
        (Finset.mem_filter.mp hC).1
      have hsource : C ∈ A.auth.allowed :=
        (mem_guardedAllowed_iff A.auth U C).1 hguard |>.1
      change (if b ∈ unsupportedOwners A.auth U then .closed
        else A.branchEpoch b) = .open
      simp [hbNot, hWF.configuration_open C hsource b hbC]
    · intro c b hs
      change preparedStatus A.auth U c = .tentative b at hs
      rw [preparedStatus_tentative_iff,
        rawPromotion_status_tentative_iff] at hs
      change (if b ∈ unsupportedOwners A.auth U then EpochStatus.closed
        else A.branchEpoch b) = EpochStatus.open
      simp [hs.2, hWF.owner_open c b hs.1.1]
    · intro c b hs
      change preparedStatus A.auth U c = .tentative b at hs
      rw [preparedStatus_tentative_iff,
        rawPromotion_status_tentative_iff] at hs
      exact hWF.grant_open c b hs.1.1
    · intro e t r ht hr
      cases ha : assignment e with
      | none =>
          apply hWF.ticket_receipt_disjoint e t r
          · simpa [prepareState, ha] using ht
          · exact hr
      | some c =>
          have hfresh := (opClaim_eq_none_iff A e).1 (hOK.fresh e c ha)
          have himpossible : (none : Option (Receipt Claim)) = some r :=
            hfresh.2.symm.trans hr
          simp at himpossible
    · intro e c hop
      rw [prepareState_opClaim] at hop
      cases ha : assignment e with
      | some assigned =>
          simp [ha] at hop
          subst assigned
          change preparedStatus A.auth U c = .durable
          rw [preparedStatus_durable_iff]
          simp [rawPromotion, hOK.assigned_mem e c ha]
      | none =>
          simp [ha] at hop
          have hdurable := hWF.bound_durable e c hop
          change preparedStatus A.auth U c = .durable
          rw [preparedStatus_durable_iff]
          by_cases hc : c ∈ U <;> simp [rawPromotion, hc, hdurable]
    · intro e e' c he he'
      rw [prepareState_opClaim] at he he'
      cases ha : assignment e with
      | some c₁ =>
          simp [ha] at he
          subst c₁
          cases ha' : assignment e' with
          | some c₂ =>
              simp [ha'] at he'
              subst c₂
              exact hOK.assignment_injective e e' c ha ha'
          | none =>
              simp [ha'] at he'
              have hdurable := hWF.bound_durable e' c he'
              obtain ⟨b, htent, -, -⟩ :=
                hOK.member_open c (hOK.assigned_mem e c ha)
              simp [htent] at hdurable
      | none =>
          simp [ha] at he
          cases ha' : assignment e' with
          | some c₂ =>
              simp [ha'] at he'
              subst c₂
              have hdurable := hWF.bound_durable e c he
              obtain ⟨b, htent, -, -⟩ :=
                hOK.member_open c (hOK.assigned_mem e' c ha')
              simp [htent] at hdurable
          | none =>
              simp [ha'] at he'
              exact hWF.binding_injective e e' c he he'
  · exact hcore.2

inductive Label (Operation Claim : Type*) where
  | tau
  | attempt (operation : Operation) (claim : Claim)
  deriving DecidableEq, Repr

def setTicketPhase
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (e : Operation) (c : Claim) (phase : TicketPhase) :
    LifecycleState Coord Claim Branch Grant Operation :=
  { A with tickets := Function.update A.tickets e (some ⟨c, phase⟩) }

def crashState
    (A : LifecycleState Coord Claim Branch Grant Operation) :
    LifecycleState Coord Claim Branch Grant Operation :=
  { A with tickets := fun e =>
      match A.tickets e with
      | some ⟨c, .inflight⟩ => some ⟨c, .uncertain⟩
      | t => t }

def settleState
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (e : Operation) (c : Claim) (outcome : ReceiptOutcome) :
    LifecycleState Coord Claim Branch Grant Operation :=
  { A with
    tickets := Function.update A.tickets e none
    receipts := Function.update A.receipts e (some ⟨c, outcome⟩) }

/-- Exact ticket-only subrelation.  Retry reuses the same stable `(e,c)` pair;
crash changes only inflight phases; Settle moves the same binding to a receipt. -/
inductive TicketStep :
    LifecycleState Coord Claim Branch Grant Operation →
    Label Operation Claim →
    LifecycleState Coord Claim Branch Grant Operation → Prop where
  | dispatch {A e c} (h : A.tickets e = some ⟨c, .prepared⟩) :
      TicketStep A (.attempt e c) (setTicketPhase A e c .inflight)
  | retry {A e c phase}
      (h : A.tickets e = some ⟨c, phase⟩)
      (hphase : phase = .inflight ∨ phase = .uncertain) :
      TicketStep A (.attempt e c) (setTicketPhase A e c .inflight)
  | crash {A} : TicketStep A .tau (crashState A)
  | settle {A e c phase outcome}
      (h : A.tickets e = some ⟨c, phase⟩)
      (hphase : phase = .inflight ∨ phase = .uncertain ∨
        (phase = .prepared ∧ outcome = .cancelled)) :
      TicketStep A .tau (settleState A e c outcome)

theorem ticketStep_binding_eq
    {A A' : LifecycleState Coord Claim Branch Grant Operation}
    {eta : Label Operation Claim} (hstep : TicketStep A eta A') :
    ∀ e, A'.opClaim e = A.opClaim e := by
  intro x
  cases hstep with
  | @dispatch e c h =>
      by_cases hx : x = e
      · subst x
        simp [setTicketPhase, opClaim, h]
      · simp [setTicketPhase, opClaim, hx]
  | @retry e c phase h hphase =>
      by_cases hx : x = e
      · subst x
        simp [setTicketPhase, opClaim, h]
      · simp [setTicketPhase, opClaim, hx]
  | crash =>
      unfold crashState opClaim
      cases ht : A.tickets x with
      | none => simp [ht]
      | some t =>
          cases t with
          | mk c phase => cases phase <;> simp [ht]
  | @settle e c phase outcome h hphase =>
      by_cases hx : x = e
      · subst x
        simp [settleState, opClaim, h]
      · simp [settleState, opClaim, hx]

theorem ticketStep_auth_eq
    {A A' : LifecycleState Coord Claim Branch Grant Operation}
    {eta : Label Operation Claim} (hstep : TicketStep A eta A') :
    A'.auth = A.auth := by
  cases hstep <;> rfl

/-- Ticket phase/recovery steps preserve authority fields and stable bindings. -/
theorem ticket_step_preserves_wf_ac
    {A A' : LifecycleState Coord Claim Branch Grant Operation}
    {eta : Label Operation Claim} (hstep : TicketStep A eta A')
    (hWF : LWF A) (hAC : AC A.auth) :
    LWF A' ∧ AC A'.auth ∧ ∀ e, A'.opClaim e = A.opClaim e := by
  classical
  have hbinding := ticketStep_binding_eq hstep
  have hauth := ticketStep_auth_eq hstep
  constructor
  · refine ⟨?_, ?_, ?_, ?_, ?_, ?_, ?_⟩
    · cases hstep <;> exact hWF.core
    · cases hstep <;> exact hWF.configuration_open
    · cases hstep <;> exact hWF.owner_open
    · cases hstep <;> exact hWF.grant_open
    · intro e t r ht hr
      cases hstep with
      | @dispatch dispatchE c h =>
          by_cases he : e = dispatchE
          · subst e
            have hnone : A.receipts dispatchE = none := by
              by_contra hne
              obtain ⟨r', hr'⟩ := Option.ne_none_iff_exists'.mp hne
              exact hWF.ticket_receipt_disjoint dispatchE
                ⟨c, .prepared⟩ r' h hr'
            simpa [setTicketPhase, hnone] using hr
          · apply hWF.ticket_receipt_disjoint e t r
            · simpa [setTicketPhase, he] using ht
            · exact hr
      | @retry retryE c phase h hphase =>
          by_cases he : e = retryE
          · subst e
            have hnone : A.receipts retryE = none := by
              by_contra hne
              obtain ⟨r', hr'⟩ := Option.ne_none_iff_exists'.mp hne
              exact hWF.ticket_receipt_disjoint retryE
                ⟨c, phase⟩ r' h hr'
            simpa [setTicketPhase, hnone] using hr
          · apply hWF.ticket_receipt_disjoint e t r
            · simpa [setTicketPhase, he] using ht
            · exact hr
      | crash =>
          unfold crashState at ht
          cases hs : A.tickets e with
          | none => simp [hs] at ht
          | some ticket =>
              exact hWF.ticket_receipt_disjoint e ticket r hs hr
      | @settle settleE c phase outcome h hphase =>
          by_cases he : e = settleE
          · subst e
            simp [settleState] at ht
          · apply hWF.ticket_receipt_disjoint e t r
            · simpa [settleState, he] using ht
            · simpa [settleState, he] using hr
    · intro e c he
      rw [hauth]
      exact hWF.bound_durable e c ((hbinding e).symm.trans he)
    · intro e e' c he he'
      exact hWF.binding_injective e e' c
        ((hbinding e).symm.trans he) ((hbinding e').symm.trans he')
  · constructor
    · cases hstep <;> exact hAC
    · exact hbinding

/-- Exact owner/claim restriction lifted to the durable lifecycle state. -/
def restrictLifecycle
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (S : Finset Branch) (keep : Finset Claim) :
    LifecycleState Coord Claim Branch Grant Operation where
  auth := A.auth.restrictStateBy S keep
  grantOf := A.grantOf
  branchEpoch b := if b ∈ S then A.branchEpoch b else .closed
  grantEpoch := A.grantEpoch
  tickets := A.tickets
  receipts := A.receipts

@[simp]
theorem restrictLifecycle_opClaim
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (S : Finset Branch) (keep : Finset Claim) (e : Operation) :
    (restrictLifecycle A S keep).opClaim e = A.opClaim e := rfl

theorem restrictLifecycle_status_durable_iff
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (S : Finset Branch) (keep : Finset Claim) (c : Claim) :
    (restrictLifecycle A S keep).auth.status c = .durable ↔
      A.auth.status c = .durable := by
  cases hs : A.auth.status c with
  | unissued => simp [restrictLifecycle, State.restrictStateBy, hs]
  | durable => simp [restrictLifecycle, State.restrictStateBy, hs]
  | terminal => simp [restrictLifecycle, State.restrictStateBy, hs]
  | tentative b =>
      by_cases hkeep : b ∈ S ∧ c ∈ keep <;>
        simp [restrictLifecycle, State.restrictStateBy, hs, hkeep]

/-- Select/Abort/Revoke's authority restriction derives target lifecycle WF
and AC; no target property is a premise. -/
theorem restriction_lifecycle_preserves_wf_ac
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (S : Finset Branch) (keep : Finset Claim)
    (hWF : LWF A) (hAC : AC A.auth) :
    LWF (restrictLifecycle A S keep) ∧
      AC (restrictLifecycle A S keep).auth := by
  have hcore := restriction_preserves_wf_ac A.auth S keep hWF.core hAC
  constructor
  · refine ⟨hcore.1, ?_, ?_, ?_, ?_, ?_, ?_⟩
    · intro C hC b hbC
      have hc := (State.mem_restrictStateBy_allowed_iff
        A.auth S keep C).1 hC
      change (if b ∈ S then A.branchEpoch b else .closed) = .open
      simp [hc.2 hbC, hWF.configuration_open C hc.1 b hbC]
    · intro c b hs
      change (A.auth.restrictStateBy S keep).status c = .tentative b at hs
      rw [State.restrictStateBy_status_tentative_iff] at hs
      change (if b ∈ S then A.branchEpoch b else .closed) = .open
      simp [restrictLifecycle, hs.2.1, hWF.owner_open c b hs.1]
    · intro c b hs
      change (A.auth.restrictStateBy S keep).status c = .tentative b at hs
      rw [State.restrictStateBy_status_tentative_iff] at hs
      change A.claimOpen c
      exact hWF.grant_open c b hs.1
    · exact hWF.ticket_receipt_disjoint
    · intro e c he
      rw [restrictLifecycle_opClaim] at he
      rw [restrictLifecycle_status_durable_iff]
      exact hWF.bound_durable e c he
    · intro e e' c he he'
      rw [restrictLifecycle_opClaim] at he he'
      exact hWF.binding_injective e e' c he he'
  · exact hcore.2

/-- Revoking grant epoch `g` closes it and terminalizes exactly its remaining
tentative claims; durable tickets and receipts are retained. -/
def revokeState
    (A : LifecycleState Coord Claim Branch Grant Operation) (g : Grant) :
    LifecycleState Coord Claim Branch Grant Operation :=
  let keep := Finset.univ.filter fun c => A.grantOf c ≠ g
  { restrictLifecycle A Finset.univ keep with
    grantEpoch := Function.update A.grantEpoch g .closed }

theorem revoke_preserves_wf_ac
    (A : LifecycleState Coord Claim Branch Grant Operation) (g : Grant)
    (hWF : LWF A) (hAC : AC A.auth) :
    LWF (revokeState A g) ∧ AC (revokeState A g).auth := by
  classical
  let keep : Finset Claim := Finset.univ.filter fun c => A.grantOf c ≠ g
  have hrestrict := restriction_lifecycle_preserves_wf_ac A Finset.univ keep hWF hAC
  constructor
  · refine ⟨hrestrict.1.core, ?_, ?_, ?_, ?_, ?_, ?_⟩
    · simpa [revokeState, keep] using hrestrict.1.configuration_open
    · simpa [revokeState, keep] using hrestrict.1.owner_open
    · intro c b hs
      have hs' : (restrictLifecycle A Finset.univ keep).auth.status c =
          .tentative b := by simpa [revokeState, keep] using hs
      have hkeep := (State.restrictStateBy_status_tentative_iff
        A.auth Finset.univ keep c b).1 hs'
      have hne : A.grantOf c ≠ g := by simpa [keep] using hkeep.2.2
      have hopen := hWF.grant_open c b hkeep.1
      unfold claimOpen at hopen ⊢
      change Function.update A.grantEpoch g .closed (A.grantOf c) = .open
      simp [hne, hopen]
    · simpa [revokeState, keep] using hrestrict.1.ticket_receipt_disjoint
    · simpa [revokeState, keep] using hrestrict.1.bound_durable
    · simpa [revokeState, keep] using hrestrict.1.binding_injective
  · exact hrestrict.2

/-- Exact finite Reserve target.  Only an `unissued` ID may enter a tentative
bundle; terminal IDs are never a freshness pool. -/
def reserveCore (A : State Coord Claim Branch) (b : Branch) (c : Claim) :
    State Coord Claim Branch :=
  { A with status := Function.update A.status c (.tentative b) }

def reserveState
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (b : Branch) (c : Claim) :
    LifecycleState Coord Claim Branch Grant Operation :=
  { A with auth := reserveCore A.auth b c }

structure ReserveOK
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (b : Branch) (c : Claim) : Prop where
  fresh : A.auth.status c = .unissued
  owner_open : A.branchEpoch b = .open
  grant_open : A.claimOpen c
  supported : ∃ C ∈ A.auth.allowed, b ∈ C
  checked : checkAC (reserveState A b c).auth = true

theorem reserve_preserves_wf_ac
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (b : Branch) (c : Claim) (hWF : LWF A)
    (hOK : ReserveOK A b c) :
    LWF (reserveState A b c) ∧ AC (reserveState A b c).auth := by
  classical
  have hcore : WF (reserveState A b c).auth := by
    refine ⟨hWF.core.empty_mem, hWF.core.downward, ?_⟩
    intro c' b' hs
    by_cases hc : c' = c
    · subst c'
      have hbb : b = b' := by
        simpa [reserveState, reserveCore] using hs
      subst b'
      exact hOK.supported
    · have hs' : A.auth.status c' = .tentative b' := by
        simpa [reserveState, reserveCore, hc] using hs
      exact hWF.core.supported c' b' hs'
  constructor
  · refine ⟨hcore, ?_, ?_, ?_, ?_, ?_, ?_⟩
    · exact hWF.configuration_open
    · intro c' b' hs
      by_cases hc : c' = c
      · subst c'
        have hbb : b = b' := by
          simpa [reserveState, reserveCore] using hs
        simpa [hbb] using hOK.owner_open
      · apply hWF.owner_open c' b'
        simpa [reserveState, reserveCore, hc] using hs
    · intro c' b' hs
      by_cases hc : c' = c
      · subst c'
        exact hOK.grant_open
      · apply hWF.grant_open c' b'
        simpa [reserveState, reserveCore, hc] using hs
    · exact hWF.ticket_receipt_disjoint
    · intro e c' he
      have hd := hWF.bound_durable e c' he
      by_cases hc : c' = c
      · subst c'
        simp [hOK.fresh] at hd
      · simpa [reserveState, reserveCore, hc] using hd
    · exact hWF.binding_injective
  · exact checkAC_sound _ hOK.checked

/-- Explicit non-circular structural evidence for topology targets.  The
mechanized core omits fragment issuance: unissued IDs remain unissued, and a
tentative claim may only move owner or become terminal. -/
structure TopologyShape
    (A A' : LifecycleState Coord Claim Branch Grant Operation) : Prop where
  capacity : A'.auth.capacity = A.auth.capacity
  demand : A'.auth.demand = A.auth.demand
  grant_metadata : A'.grantOf = A.grantOf
  tickets : A'.tickets = A.tickets
  receipts : A'.receipts = A.receipts
  empty_mem : ∅ ∈ A'.auth.allowed
  downward : ∀ ⦃C C' : Finset Branch⦄, C ∈ A'.auth.allowed →
    C' ⊆ C → C' ∈ A'.auth.allowed
  supported : ∀ c b, A'.auth.status c = .tentative b →
    ∃ C ∈ A'.auth.allowed, b ∈ C
  configuration_open : ∀ C ∈ A'.auth.allowed, ∀ b ∈ C,
    A'.branchEpoch b = .open
  owner_open : ∀ c b, A'.auth.status c = .tentative b →
    A'.branchEpoch b = .open
  grant_open : ∀ c b, A'.auth.status c = .tentative b →
    A'.claimOpen c
  terminal : A.TerminalMonotone A'
  epochs : A.EpochMonotone A'
  durable : ∀ c, A.auth.status c = .durable →
    A'.auth.status c = .durable
  unissued : ∀ c, A.auth.status c = .unissued →
    A'.auth.status c = .unissued
  tentative : ∀ c b, A.auth.status c = .tentative b →
    (∃ b', A'.auth.status c = .tentative b') ∨
      A'.auth.status c = .terminal

theorem TopologyShape.opClaim_eq
    {A A' : LifecycleState Coord Claim Branch Grant Operation}
    (h : TopologyShape A A') (e : Operation) :
    A'.opClaim e = A.opClaim e := by
  unfold opClaim
  rw [h.tickets, h.receipts]

theorem TopologyShape.target_lwf
    {A A' : LifecycleState Coord Claim Branch Grant Operation}
    (h : TopologyShape A A') (hWF : LWF A) : LWF A' := by
  refine ⟨⟨h.empty_mem, h.downward, h.supported⟩,
    h.configuration_open, h.owner_open, h.grant_open,
    ?_, ?_, ?_⟩
  · intro e t r ht hr
    rw [h.tickets] at ht
    rw [h.receipts] at hr
    exact hWF.ticket_receipt_disjoint e t r ht hr
  · intro e c he
    have hs := hWF.bound_durable e c ((h.opClaim_eq e).symm.trans he)
    exact h.durable c hs
  · intro e e' c he he'
    exact hWF.binding_injective e e' c
      ((h.opClaim_eq e).symm.trans he) ((h.opClaim_eq e').symm.trans he')

theorem simulated_topology_preserves_wf_ac
    (A A' : LifecycleState Coord Claim Branch Grant Operation)
    (project : Finset Branch → Finset Branch)
    (shape : TopologyShape A A') (hWF : LWF A) (hAC : AC A.auth)
    (hsim : ∀ C' ∈ A'.auth.allowed,
      project C' ∈ A.auth.allowed ∧ ∀ k,
        A'.auth.durableLoad k + A'.auth.conditionalLoad C' k ≤
          A.auth.durableLoad k + A.auth.conditionalLoad (project C') k) :
    LWF A' ∧ AC A'.auth := by
  exact ⟨shape.target_lwf hWF,
    simulation_preserves_ac A.auth A'.auth project shape.capacity hAC hsim⟩

theorem direct_merge_preserves_wf_ac
    (A A' : LifecycleState Coord Claim Branch Grant Operation)
    (shape : TopologyShape A A') (hWF : LWF A)
    (hcheck : checkAC A'.auth = true) :
    LWF A' ∧ AC A'.auth :=
  ⟨shape.target_lwf hWF, checkAC_sound A'.auth hcheck⟩

end LifecycleState

open LifecycleState

variable {Coord Claim Branch Grant Operation : Type*}
variable [Fintype Coord] [DecidableEq Coord]
variable [Fintype Claim] [DecidableEq Claim]
variable [Fintype Branch] [DecidableEq Branch]
variable [DecidableEq Grant] [DecidableEq Operation]

/-- Closed abstract one-step kernel.  The topology constructor mechanizes the
identity-preserving certificate obligations above, not concrete syntax-level
Fork/Restore shapes or fragmentation. -/
inductive Step :
    LifecycleState Coord Claim Branch Grant Operation →
    Label Operation Claim →
    LifecycleState Coord Claim Branch Grant Operation → Prop where
  | checkpoint (A) : Step A .tau A
  | reserve {A b c} (ok : ReserveOK A b c) :
      Step A .tau (reserveState A b c)
  | restriction (A) (S : Finset Branch) (keep : Finset Claim) :
      Step A .tau (restrictLifecycle A S keep)
  | revoke (A) (g : Grant) : Step A .tau (revokeState A g)
  | topology {A A'} (project : Finset Branch → Finset Branch)
      (shape : TopologyShape A A')
      (simulates : ∀ C' ∈ A'.auth.allowed,
        project C' ∈ A.auth.allowed ∧ ∀ k,
          A'.auth.durableLoad k + A'.auth.conditionalLoad C' k ≤
            A.auth.durableLoad k + A.auth.conditionalLoad (project C') k) :
      Step A .tau A'
  | directMerge {A A'} (shape : TopologyShape A A')
      (checked : checkAC A'.auth = true) : Step A .tau A'
  | prepare {A U assignment} (ok : PrepareOK A U assignment) :
      Step A .tau (prepareState A U assignment)
  | ticket {A A' eta} (ticketStep : TicketStep A eta A') :
      Step A eta A'

/-- Root paper-facing alias for the exact Prepare preservation theorem. -/
theorem prepare_preserves_wf_ac
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (U : Finset Claim) (assignment : Operation → Option Claim)
    (hWF : LWF A) (hAC : AC A.auth)
    (hOK : PrepareOK A U assignment) :
    LWF (prepareState A U assignment) ∧
      AC (prepareState A U assignment).auth :=
  LifecycleState.prepare_preserves_wf_ac A U assignment hWF hAC hOK

/-- Root paper-facing alias for exact ticket-step preservation. -/
theorem ticket_step_preserves_wf_ac
    {A A' : LifecycleState Coord Claim Branch Grant Operation}
    {eta : Label Operation Claim} (hstep : TicketStep A eta A')
    (hWF : LWF A) (hAC : AC A.auth) :
    LWF A' ∧ AC A'.auth ∧ ∀ e, A'.opClaim e = A.opClaim e :=
  LifecycleState.ticket_step_preserves_wf_ac hstep hWF hAC

/-- Every generated transition preserves lifecycle WF and authority
continuity.  Only Reserve/direct Merge appeal to the executable target AC
checker; all other cases use computed targets or simulation inequalities. -/
theorem step_preserves_wf_ac
    {A A' : LifecycleState Coord Claim Branch Grant Operation}
    {eta : Label Operation Claim} (hstep : Step A eta A')
    (hWF : LWF A) (hAC : AC A.auth) : LWF A' ∧ AC A'.auth := by
  cases hstep with
  | checkpoint => exact ⟨hWF, hAC⟩
  | reserve ok => exact reserve_preserves_wf_ac _ _ _ hWF ok
  | restriction S keep =>
      exact restriction_lifecycle_preserves_wf_ac _ S keep hWF hAC
  | revoke g => exact revoke_preserves_wf_ac _ g hWF hAC
  | topology project shape simulates =>
      exact simulated_topology_preserves_wf_ac _ _ project shape hWF hAC simulates
  | directMerge shape checked =>
      exact direct_merge_preserves_wf_ac _ _ shape hWF checked
  | prepare ok => exact prepare_preserves_wf_ac _ _ _ hWF hAC ok
  | ticket ticketStep =>
      have h := ticket_step_preserves_wf_ac ticketStep hWF hAC
      exact ⟨h.1, h.2.1⟩

/-- Temporal terminality invariant: no admitted step resurrects a tombstoned
claim.  Reserve's only source is explicitly `unissued`. -/
theorem step_terminal_mono
    {A A' : LifecycleState Coord Claim Branch Grant Operation}
    {eta : Label Operation Claim} (hstep : Step A eta A') :
    A.TerminalMonotone A' := by
  intro c hc
  cases hstep with
  | checkpoint => exact hc
  | @reserve b reserved ok =>
      by_cases hcr : c = reserved
      · subst c
        have hfresh := ok.fresh
        rw [hc] at hfresh
        simp at hfresh
      · simpa [reserveState, reserveCore, hcr] using hc
  | restriction S keep =>
      simp [restrictLifecycle, State.restrictStateBy, hc]
  | revoke g =>
      simp [revokeState, restrictLifecycle, State.restrictStateBy, hc]
  | topology project shape simulates => exact shape.terminal c hc
  | directMerge shape checked => exact shape.terminal c hc
  | @prepare U assignment ok =>
      have hcNot : c ∉ U := by
        intro hcU
        obtain ⟨b, htent, -, -⟩ := ok.member_open c hcU
        rw [hc] at htent
        simp at htent
      change preparedStatus A.auth U c = .terminal
      simp [preparedStatus, rawPromotion, hcNot, hc]
  | ticket ticketStep =>
      rw [LifecycleState.ticketStep_auth_eq ticketStep]
      exact hc

/-- Epoch closure is temporal: a closed branch or grant epoch never reopens;
new openings are possible only from `unissued` through `Advances`. -/
theorem step_epoch_mono
    {A A' : LifecycleState Coord Claim Branch Grant Operation}
    {eta : Label Operation Claim} (hstep : Step A eta A') :
    A.EpochMonotone A' := by
  cases hstep with
  | checkpoint =>
      exact ⟨fun b => EpochStatus.Advances.refl _,
        fun g => EpochStatus.Advances.refl _⟩
  | reserve ok =>
      exact ⟨fun b => EpochStatus.Advances.refl _,
        fun g => EpochStatus.Advances.refl _⟩
  | @restriction S keep =>
      constructor
      · intro b
        by_cases hb : b ∈ S
        · simpa [restrictLifecycle, hb] using
            EpochStatus.Advances.refl (A.branchEpoch b)
        · cases hs : A.branchEpoch b <;>
            simp [restrictLifecycle, hb, EpochStatus.Advances]
      · intro g
        exact EpochStatus.Advances.refl _
  | @revoke g =>
      constructor
      · intro b
        simpa [revokeState, restrictLifecycle] using
          EpochStatus.Advances.refl (A.branchEpoch b)
      · intro g'
        by_cases hgg : g' = g
        · subst g'
          cases hs : A.grantEpoch g <;>
            simp [revokeState, hs, EpochStatus.Advances]
        · simpa [revokeState, hgg] using
            EpochStatus.Advances.refl (A.grantEpoch g')
  | topology project shape simulates => exact shape.epochs
  | directMerge shape checked => exact shape.epochs
  | @prepare U assignment ok =>
      constructor
      · intro b
        by_cases hb : b ∈ unsupportedOwners A.auth U
        · cases hs : A.branchEpoch b <;>
            simp [prepareState, hb, hs, EpochStatus.Advances]
        · simpa [prepareState, hb] using
            EpochStatus.Advances.refl (A.branchEpoch b)
      · intro g
        exact EpochStatus.Advances.refl _
  | ticket ticketStep =>
      cases ticketStep <;>
        exact ⟨fun b => EpochStatus.Advances.refl _,
          fun g => EpochStatus.Advances.refl _⟩

/-- Every emitted attempt is the dispatch or retry of the same stable
operation/claim binding, and that claim was already durable in the pre-state. -/
theorem attempt_uses_durable_ticket
    {A A' : LifecycleState Coord Claim Branch Grant Operation}
    {e : Operation} {c : Claim}
    (hstep : Step A (.attempt e c) A') (hWF : LWF A) :
    A.opClaim e = some c ∧ A.auth.status c = .durable ∧
      A'.opClaim e = some c := by
  cases hstep with
  | ticket ticketStep =>
      have hbinding := LifecycleState.ticketStep_binding_eq ticketStep
      cases ticketStep with
      | dispatch ht =>
          have hop : A.opClaim e = some c := by simp [LifecycleState.opClaim, ht]
          exact ⟨hop, hWF.bound_durable e c hop,
            (hbinding e).trans hop⟩
      | retry ht hphase =>
          have hop : A.opClaim e = some c := by simp [LifecycleState.opClaim, ht]
          exact ⟨hop, hWF.bound_durable e c hop,
            (hbinding e).trans hop⟩

/-- Audited paper-facing name for the attempt-label safety clause. -/
theorem step_attempt_safe
    {A A' : LifecycleState Coord Claim Branch Grant Operation}
    {e : Operation} {c : Claim}
    (hstep : Step A (.attempt e c) A') (hWF : LWF A) :
    A.opClaim e = some c ∧ A.auth.status c = .durable ∧
      A'.opClaim e = some c :=
  attempt_uses_durable_ticket hstep hWF

end AuthorityContinuity
