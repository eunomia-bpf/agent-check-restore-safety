import AuthorityContinuity.PlanInvariantGrammar
import Mathlib.Tactic.FinCases

/-!
# Discrete plan-token linearity

Vector demand is deliberately not used as a proxy for a linear right.  A
finite immutable token names each initially schedulable unit.  Claim IDs are
only current witnesses for tokens and may change through an actual `rho` map.
At every checked controller state an initial token is in exactly one computed
class:

* `remaining`: exactly one selected current claim witnesses the token;
* `prepared`: no current claim remains and at most one durable operation
  binding witnesses the token; or
* `withdrawn`: neither witness exists.

Canonical transfer and Merge transport the immutable origin map through the
actual `rho`.  Their executable target checks inspect token-fiber cardinality,
not demand.  Thus a zero-demand source claim cannot be copied into two
schedulable descendants.  Splitting one reservation into several independently
preparable operations requires minting distinct tokens before plan creation.
-/

namespace AuthorityContinuity.PlanTokenLinearity

open AuthorityContinuity LifecycleState
open AuthorityContinuity.PlanInvariant
open AuthorityContinuity.PlanInvariant.PlanData

universe uC uI uB uG uO uS uT

variable {Coord : Type uC} {Claim : Type uI} {Branch : Type uB}
variable {Grant : Type uG} {Operation : Type uO} {Slot : Type uS}
variable {Token : Type uT}
variable [Fintype Coord] [DecidableEq Coord]
variable [Fintype Claim] [LinearOrder Claim]
variable [Fintype Branch] [LinearOrder Branch]
variable [DecidableEq Grant] [Fintype Operation] [DecidableEq Operation]
variable [Fintype Slot] [LinearOrder Slot]
variable [Fintype Token] [LinearOrder Token]

inductive TokenDisposition where
  | remaining
  | prepared
  | withdrawn
  deriving DecidableEq, Repr

/-- Durable ghost ledger. `origin` is immutable except for transport through an
actual checked refinement map. Claim IDs are not themselves tokens. -/
structure TokenLedger (Claim : Type uI) (Token : Type uT) where
  initial : Finset Token
  origin : Claim -> Option Token
  disposition : Token -> TokenDisposition

/-- Existing lifecycle/plan state paired with the discrete ledger. -/
structure TokenState where
  controller : InvariantState (Coord := Coord) (Claim := Claim)
    (Branch := Branch) (Grant := Grant) (Operation := Operation) (Slot := Slot)
  ledger : TokenLedger Claim Token

namespace TokenLedger

def currentFiber
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (l : TokenLedger Claim Token) (t : Token) : Finset Claim :=
  p.remaining.filter fun c => l.origin c = some t

def bindingFiber
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (l : TokenLedger Claim Token) (t : Token) : Finset Operation :=
  Finset.univ.filter fun e => (A.opClaim e).bind l.origin = some t

def computedDisposition
    (S : InvariantState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot))
    (l : TokenLedger Claim Token) (t : Token) : TokenDisposition :=
  if (l.currentFiber S.plan t).Nonempty then .remaining
  else if (l.bindingFiber S.lifecycle t).Nonempty then .prepared
  else .withdrawn

/-- Recompute disposition from the actual plan and durable operation bindings.
The initial-token set and origin map are unchanged. -/
def reclassify
    (S : InvariantState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot))
    (l : TokenLedger Claim Token) : TokenLedger Claim Token :=
  { l with disposition := l.computedDisposition S }

/-- Transport a current claim's immutable token through the actual `rho`.
Claims outside the transfer domain retain their old origin; this preserves
origins of already-durable ticket bindings. -/
def transportedOrigin (l : TokenLedger Claim Token)
    (tr : Transfer Claim Branch) (c' : Claim) : Option Token :=
  match tr.rho c' with
  | some c => l.origin c
  | none => l.origin c'

def afterTransfer
    (S' : InvariantState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot))
    (l : TokenLedger Claim Token) (tr : Transfer Claim Branch) :
    TokenLedger Claim Token :=
  let transported : TokenLedger Claim Token :=
    { l with origin := l.transportedOrigin tr }
  transported.reclassify S'

end TokenLedger

namespace TokenState

def currentFiber (S : TokenState (Coord := Coord) (Claim := Claim)
    (Branch := Branch) (Grant := Grant) (Operation := Operation)
    (Slot := Slot) (Token := Token)) (t : Token) : Finset Claim :=
  S.ledger.currentFiber S.controller.plan t

def bindingFiber (S : TokenState (Coord := Coord) (Claim := Claim)
    (Branch := Branch) (Grant := Grant) (Operation := Operation)
    (Slot := Slot) (Token := Token)) (t : Token) : Finset Operation :=
  S.ledger.bindingFiber S.controller.lifecycle t

/-- Semantic source invariant emitted by the executable checker. -/
structure LinearValid
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token)) : Prop where
  current_covered : forall c, c ∈ S.controller.plan.remaining ->
    exists t, t ∈ S.ledger.initial ∧ S.ledger.origin c = some t
  binding_covered : forall e c,
    S.controller.lifecycle.opClaim e = some c ->
      exists t, t ∈ S.ledger.initial ∧ S.ledger.origin c = some t
  current_linear : forall t, t ∈ S.ledger.initial ->
    (S.currentFiber t).card <= 1
  binding_linear : forall t, t ∈ S.ledger.initial ->
    (S.bindingFiber t).card <= 1
  exclusive : forall t, t ∈ S.ledger.initial ->
    ¬ ((S.currentFiber t).Nonempty ∧ (S.bindingFiber t).Nonempty)
  disposition_exact : forall t, t ∈ S.ledger.initial ->
    S.ledger.disposition t =
      S.ledger.computedDisposition S.controller t

def checkCurrentCovered
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token)) : Bool :=
  finiteAll S.controller.plan.remaining fun c =>
    match S.ledger.origin c with
    | none => false
    | some t => decide (t ∈ S.ledger.initial)

def checkCurrentLinear
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token)) : Bool :=
  finiteAll S.ledger.initial fun t => decide ((S.currentFiber t).card <= 1)

def checkBindingCovered
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token)) : Bool :=
  finiteAll Finset.univ fun e =>
    match S.controller.lifecycle.opClaim e with
    | none => true
    | some c =>
        match S.ledger.origin c with
        | none => false
        | some t => decide (t ∈ S.ledger.initial)

def checkBindingLinear
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token)) : Bool :=
  finiteAll S.ledger.initial fun t => decide ((S.bindingFiber t).card <= 1)

def checkExclusive
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token)) : Bool :=
  finiteAll S.ledger.initial fun t =>
    decide (¬ ((S.currentFiber t).Nonempty ∧ (S.bindingFiber t).Nonempty))

def checkDisposition
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token)) : Bool :=
  finiteAll S.ledger.initial fun t =>
    decide (S.ledger.disposition t =
      S.ledger.computedDisposition S.controller t)

/-- Executable full discrete-linearity checker. Each atom is finite and
inspects actual plan membership or actual durable operation bindings. -/
def checkLinear
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token)) : Bool :=
  S.checkCurrentCovered &&
    (S.checkBindingCovered &&
      (S.checkCurrentLinear &&
        (S.checkBindingLinear && (S.checkExclusive && S.checkDisposition))))

theorem checkCurrentCovered_sound
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (h : S.checkCurrentCovered = true) :
    forall c, c ∈ S.controller.plan.remaining ->
      exists t, t ∈ S.ledger.initial ∧ S.ledger.origin c = some t := by
  intro c hc
  have hall := (finiteAll_eq_true S.controller.plan.remaining _).mp h c hc
  cases ho : S.ledger.origin c with
  | none => simp [ho] at hall
  | some t =>
      refine ⟨t, ?_, rfl⟩
      exact of_decide_eq_true (by simpa [checkCurrentCovered, ho] using hall)

theorem checkCurrentLinear_sound
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (h : S.checkCurrentLinear = true) :
    forall t, t ∈ S.ledger.initial -> (S.currentFiber t).card <= 1 := by
  intro t ht
  exact of_decide_eq_true
    ((finiteAll_eq_true S.ledger.initial _).mp h t ht)

theorem checkBindingCovered_sound
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (h : S.checkBindingCovered = true) :
    forall e c, S.controller.lifecycle.opClaim e = some c ->
      exists t, t ∈ S.ledger.initial ∧ S.ledger.origin c = some t := by
  intro e c he
  have hall := (finiteAll_eq_true Finset.univ _).mp h e (Finset.mem_univ e)
  rw [he] at hall
  cases ho : S.ledger.origin c with
  | none => simp [ho] at hall
  | some t =>
      refine ⟨t, ?_, rfl⟩
      exact of_decide_eq_true (by simpa [checkBindingCovered, ho] using hall)

theorem checkBindingLinear_sound
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (h : S.checkBindingLinear = true) :
    forall t, t ∈ S.ledger.initial -> (S.bindingFiber t).card <= 1 := by
  intro t ht
  exact of_decide_eq_true
    ((finiteAll_eq_true S.ledger.initial _).mp h t ht)

theorem checkExclusive_sound
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (h : S.checkExclusive = true) :
    forall t, t ∈ S.ledger.initial ->
      ¬ ((S.currentFiber t).Nonempty ∧ (S.bindingFiber t).Nonempty) := by
  intro t ht
  exact of_decide_eq_true
    ((finiteAll_eq_true S.ledger.initial _).mp h t ht)

theorem checkDisposition_sound
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (h : S.checkDisposition = true) :
    forall t, t ∈ S.ledger.initial ->
      S.ledger.disposition t =
        S.ledger.computedDisposition S.controller t := by
  intro t ht
  exact of_decide_eq_true
    ((finiteAll_eq_true S.ledger.initial _).mp h t ht)

/-- Main executable-checker soundness theorem. -/
theorem checkLinear_sound
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (h : S.checkLinear = true) : S.LinearValid := by
  have hp : S.checkCurrentCovered = true ∧
      S.checkBindingCovered = true ∧ S.checkCurrentLinear = true ∧
      S.checkBindingLinear = true ∧ S.checkExclusive = true ∧
      S.checkDisposition = true := by
    simpa [checkLinear, Bool.and_eq_true] using h
  exact {
    current_covered := checkCurrentCovered_sound S hp.1
    binding_covered := checkBindingCovered_sound S hp.2.1
    current_linear := checkCurrentLinear_sound S hp.2.2.1
    binding_linear := checkBindingLinear_sound S hp.2.2.2.1
    exclusive := checkExclusive_sound S hp.2.2.2.2.1
    disposition_exact := checkDisposition_sound S hp.2.2.2.2.2 }

theorem LinearValid.distinct_bindings
    {S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token)}
    (h : S.LinearValid) {t : Token} (ht : t ∈ S.ledger.initial)
    {e e' : Operation} {c c' : Claim}
    (he : S.controller.lifecycle.opClaim e = some c)
    (he' : S.controller.lifecycle.opClaim e' = some c')
    (hc : S.ledger.origin c = some t)
    (hc' : S.ledger.origin c' = some t) : e = e' := by
  apply Finset.card_le_one.mp (h.binding_linear t ht) e
  · simp [bindingFiber, TokenLedger.bindingFiber, he, hc]
  · simp [bindingFiber, TokenLedger.bindingFiber, he', hc']

theorem LinearValid.distinct_current_claims
    {S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token)}
    (h : S.LinearValid) {t : Token} (ht : t ∈ S.ledger.initial)
    {c c' : Claim} (hcRem : c ∈ S.controller.plan.remaining)
    (hc'Rem : c' ∈ S.controller.plan.remaining)
    (hc : S.ledger.origin c = some t)
    (hc' : S.ledger.origin c' = some t) : c = c' := by
  apply Finset.card_le_one.mp (h.current_linear t ht) c
  · simp [currentFiber, TokenLedger.currentFiber, hcRem, hc]
  · simp [currentFiber, TokenLedger.currentFiber, hc'Rem, hc']

/-- Exact three-way accounting for every initially minted token. Cardinality
one is a theorem, not an interpretation of positive demand. -/
theorem LinearValid.token_trichotomy
    {S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token)}
    (h : S.LinearValid) {t : Token} (ht : t ∈ S.ledger.initial) :
    (S.ledger.disposition t = .remaining ∧
        (S.currentFiber t).card = 1 ∧ (S.bindingFiber t).card = 0) ∨
      (S.ledger.disposition t = .prepared ∧
        (S.currentFiber t).card = 0 ∧ (S.bindingFiber t).card = 1) ∨
      (S.ledger.disposition t = .withdrawn ∧
        (S.currentFiber t).card = 0 ∧ (S.bindingFiber t).card = 0) := by
  by_cases hc : (S.currentFiber t).Nonempty
  · left
    have hb : ¬ (S.bindingFiber t).Nonempty := fun hb =>
      h.exclusive t ht ⟨hc, hb⟩
    have hc' : (TokenLedger.currentFiber S.controller.plan
        S.ledger t).Nonempty := by
      simpa [TokenState.currentFiber] using hc
    have hcOne : (S.currentFiber t).card = 1 := by
      have hpos := Finset.card_pos.mpr hc
      have hle := h.current_linear t ht
      omega
    have hbZero : (S.bindingFiber t).card = 0 := by
      rw [Finset.card_eq_zero]
      exact Finset.not_nonempty_iff_eq_empty.mp hb
    refine ⟨?_, hcOne, hbZero⟩
    have hd := h.disposition_exact t ht
    simpa [TokenLedger.computedDisposition, hc'] using hd
  · by_cases hb : (S.bindingFiber t).Nonempty
    · right; left
      have hc' : ¬ (TokenLedger.currentFiber S.controller.plan
          S.ledger t).Nonempty := by
        simpa [TokenState.currentFiber] using hc
      have hb' : (TokenLedger.bindingFiber S.controller.lifecycle
          S.ledger t).Nonempty := by
        simpa [TokenState.bindingFiber] using hb
      have hcZero : (S.currentFiber t).card = 0 := by
        rw [Finset.card_eq_zero]
        exact Finset.not_nonempty_iff_eq_empty.mp hc
      have hbOne : (S.bindingFiber t).card = 1 := by
        have hpos := Finset.card_pos.mpr hb
        have hle := h.binding_linear t ht
        omega
      refine ⟨?_, hcZero, hbOne⟩
      have hd := h.disposition_exact t ht
      simpa [TokenLedger.computedDisposition, hc', hb'] using hd
    · right; right
      have hc' : ¬ (TokenLedger.currentFiber S.controller.plan
          S.ledger t).Nonempty := by
        simpa [TokenState.currentFiber] using hc
      have hb' : ¬ (TokenLedger.bindingFiber S.controller.lifecycle
          S.ledger t).Nonempty := by
        simpa [TokenState.bindingFiber] using hb
      have hcZero : (S.currentFiber t).card = 0 := by
        rw [Finset.card_eq_zero]
        exact Finset.not_nonempty_iff_eq_empty.mp hc
      have hbZero : (S.bindingFiber t).card = 0 := by
        rw [Finset.card_eq_zero]
        exact Finset.not_nonempty_iff_eq_empty.mp hb
      refine ⟨?_, hcZero, hbZero⟩
      have hd := h.disposition_exact t ht
      simpa [TokenLedger.computedDisposition, hc', hb'] using hd

end TokenState

/-! ## Computed canonical transport and token-aware admission -/

def advanceCanonical
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (tr : Transfer Claim Branch) (op : CanonicalOp Branch) :
    TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token) :=
  let controller' := advanceCanonicalTransport S.controller tr op
  { controller := controller'
    ledger := S.ledger.afterTransfer controller' tr }

/-- Combined canonical checker. The old plan checker remains intact; the new
atom checks the fully computed target token fibers. -/
def checkCanonicalTokenPlan
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (tr : Transfer Claim Branch) (op : CanonicalOp Branch)
    (offered : Nat) : Bool :=
  checkCanonicalPlan S.controller.lifecycle S.controller.plan tr op offered &&
    (advanceCanonical S tr op).checkLinear

theorem checkCanonicalTokenPlan_parts
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (tr : Transfer Claim Branch) (op : CanonicalOp Branch) (offered : Nat)
    (h : checkCanonicalTokenPlan S tr op offered = true) :
    checkCanonicalPlan S.controller.lifecycle S.controller.plan tr op offered = true ∧
      (advanceCanonical S tr op).checkLinear = true := by
  simpa [checkCanonicalTokenPlan, Bool.and_eq_true] using h

theorem checkedCanonical_preserves_linearity
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (tr : Transfer Claim Branch) (op : CanonicalOp Branch) (offered : Nat)
    (_hSource : S.LinearValid)
    (h : checkCanonicalTokenPlan S tr op offered = true) :
    (advanceCanonical S tr op).LinearValid :=
  TokenState.checkLinear_sound _ (checkCanonicalTokenPlan_parts S tr op offered h).2

/-- Any two schedulable canonical descendants carrying the same immutable
token are the same claim. This includes choice and parallel forks and does not
mention demand. -/
theorem checkedCanonical_same_token_eq
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (tr : Transfer Claim Branch) (op : CanonicalOp Branch) (offered : Nat)
    (hSource : S.LinearValid)
    (h : checkCanonicalTokenPlan S tr op offered = true)
    {t : Token} (ht : t ∈ S.ledger.initial) {c c' : Claim}
    (hc : c ∈ (advanceCanonical S tr op).controller.plan.remaining)
    (hc' : c' ∈ (advanceCanonical S tr op).controller.plan.remaining)
    (ho : (advanceCanonical S tr op).ledger.origin c = some t)
    (ho' : (advanceCanonical S tr op).ledger.origin c' = some t) : c = c' :=
  (checkedCanonical_preserves_linearity S tr op offered hSource h).distinct_current_claims
    (by simpa [advanceCanonical] using ht) hc hc' ho ho'

/-! ## Computed Prepare and token-aware admission -/

def advancePrepare
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (assignment : Operation -> Option Claim) :
    TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token) :=
  let controller' :=
    _root_.AuthorityContinuity.PlanInvariant.PlanData.advancePrepare
      S.controller assignment
  { controller := controller'
    ledger := S.ledger.reclassify controller' }

/-- Prepare uses the actual computed head and assignment. The last atom checks
the reclassified target ledger, so unsupported-owner cleanup becomes
`withdrawn` rather than silently leaving a reusable current token. -/
def checkPrepareTokenPlan
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (offered : Nat) (assignment : Operation -> Option Claim) : Bool :=
  S.controller.plan.checkVersion offered &&
    (decide S.controller.plan.remaining.Nonempty &&
      (Plan.checkAssignment S.controller.lifecycle
        (S.controller.plan.headGroup S.controller.lifecycle) assignment &&
        (advancePrepare S assignment).checkLinear))

theorem checkPrepareTokenPlan_parts
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (offered : Nat) (assignment : Operation -> Option Claim)
    (h : checkPrepareTokenPlan S offered assignment = true) :
    S.controller.plan.checkVersion offered = true ∧
      S.controller.plan.remaining.Nonempty ∧
      Plan.checkAssignment S.controller.lifecycle
        (S.controller.plan.headGroup S.controller.lifecycle) assignment = true ∧
      (advancePrepare S assignment).checkLinear = true := by
  have hp : S.controller.plan.checkVersion offered = true ∧
      decide S.controller.plan.remaining.Nonempty = true ∧
      Plan.checkAssignment S.controller.lifecycle
        (S.controller.plan.headGroup S.controller.lifecycle) assignment = true ∧
      (advancePrepare S assignment).checkLinear = true := by
    simpa [checkPrepareTokenPlan, Bool.and_eq_true] using h
  exact ⟨hp.1, of_decide_eq_true hp.2.1, hp.2.2.1, hp.2.2.2⟩

theorem checkedPrepare_preserves_linearity
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (offered : Nat) (assignment : Operation -> Option Claim)
    (_hSource : S.LinearValid)
    (h : checkPrepareTokenPlan S offered assignment = true) :
    (advancePrepare S assignment).LinearValid :=
  TokenState.checkLinear_sound _
    (checkPrepareTokenPlan_parts S offered assignment h).2.2.2

theorem checkedPrepare_actual_step
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (offered : Nat) (assignment : Operation -> Option Claim)
    (hWF : S.controller.lifecycle.LWF)
    (hPlan : S.controller.plan.Valid S.controller.lifecycle)
    (h : checkPrepareTokenPlan S offered assignment = true) :
    Step S.controller.lifecycle .tau
      (advancePrepare S assignment).controller.lifecycle := by
  have hp := checkPrepareTokenPlan_parts S offered assignment h
  have planned : PreparePlanned S.controller offered assignment
      (_root_.AuthorityContinuity.PlanInvariant.PlanData.advancePrepare
        S.controller assignment) :=
    .mk hWF hPlan hp.2.1 hp.1 hp.2.2.1
  exact planned.actual_step

/-- A head claim's token becomes prepared using the actual assignment. The
returned operation is the durable ticket binding installed by `prepareState`.
No demand premise appears. -/
theorem checkedPrepare_head_token_prepared
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (offered : Nat) (assignment : Operation -> Option Claim)
    (hSource : S.LinearValid)
    (h : checkPrepareTokenPlan S offered assignment = true)
    {c : Claim} {t : Token}
    (hc : c ∈ S.controller.plan.headGroup S.controller.lifecycle)
    (ht : t ∈ S.ledger.initial) (horigin : S.ledger.origin c = some t) :
    (advancePrepare S assignment).ledger.disposition t = .prepared ∧
      ∃ e, (advancePrepare S assignment).controller.lifecycle.opClaim e = some c := by
  have hp := checkPrepareTokenPlan_parts S offered assignment h
  have hAssignment := Plan.checkAssignment_sound hp.2.2.1
  obtain ⟨e, he⟩ := hAssignment.covered c hc
  have hop : (advancePrepare S assignment).controller.lifecycle.opClaim e = some c := by
    have hBinding := prepareState_opClaim S.controller.lifecycle
      (S.controller.plan.headGroup S.controller.lifecycle) assignment e
    rw [he] at hBinding
    simpa [advancePrepare,
      _root_.AuthorityContinuity.PlanInvariant.PlanData.advancePrepare]
      using hBinding
  have hTarget := checkedPrepare_preserves_linearity S offered assignment hSource h
  have horigin' : (advancePrepare S assignment).ledger.origin c = some t := by
    simpa [advancePrepare, TokenLedger.reclassify] using horigin
  have hBinding : ((advancePrepare S assignment).bindingFiber t).Nonempty := by
    refine ⟨e, ?_⟩
    simp [TokenState.bindingFiber, TokenLedger.bindingFiber, hop, horigin']
  have hNoCurrent : ¬ ((advancePrepare S assignment).currentFiber t).Nonempty := by
    intro hCurrent
    exact hTarget.exclusive t (by simpa [advancePrepare] using ht)
      ⟨hCurrent, hBinding⟩
  constructor
  · rw [hTarget.disposition_exact t (by simpa [advancePrepare] using ht)]
    have hNoCurrent' : ¬ (TokenLedger.currentFiber
        (advancePrepare S assignment).controller.plan
        (advancePrepare S assignment).ledger t).Nonempty := by
      simpa [TokenState.currentFiber] using hNoCurrent
    have hBinding' : (TokenLedger.bindingFiber
        (advancePrepare S assignment).controller.lifecycle
        (advancePrepare S assignment).ledger t).Nonempty := by
      simpa [TokenState.bindingFiber] using hBinding
    simp [TokenLedger.computedDisposition, hNoCurrent', hBinding']
  · exact ⟨e, hop⟩

/-- Exact cleanup classification: if the computed Prepare target has neither a
current witness nor a durable binding for an initial token, the target ledger
marks it withdrawn. -/
theorem checkedPrepare_cleanup_withdrawn
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (offered : Nat) (assignment : Operation -> Option Claim)
    (hSource : S.LinearValid)
    (h : checkPrepareTokenPlan S offered assignment = true)
    {t : Token} (ht : t ∈ S.ledger.initial)
    (hNoCurrent : ¬ ((advancePrepare S assignment).currentFiber t).Nonempty)
    (hNoBinding : ¬ ((advancePrepare S assignment).bindingFiber t).Nonempty) :
    (advancePrepare S assignment).ledger.disposition t = .withdrawn := by
  have hTarget := checkedPrepare_preserves_linearity S offered assignment hSource h
  rw [hTarget.disposition_exact t (by simpa [advancePrepare] using ht)]
  have hNoCurrent' : ¬ (TokenLedger.currentFiber
      (advancePrepare S assignment).controller.plan
      (advancePrepare S assignment).ledger t).Nonempty := by
    simpa [TokenState.currentFiber] using hNoCurrent
  have hNoBinding' : ¬ (TokenLedger.bindingFiber
      (advancePrepare S assignment).controller.lifecycle
      (advancePrepare S assignment).ledger t).Nonempty := by
    simpa [TokenState.bindingFiber] using hNoBinding
  simp [TokenLedger.computedDisposition, hNoCurrent', hNoBinding']

/-- Two distinct durable operations in any checked Prepare target cannot have
claims from the same initial token. -/
theorem checkedPrepare_distinct_tickets
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (offered : Nat) (assignment : Operation -> Option Claim)
    (hSource : S.LinearValid)
    (h : checkPrepareTokenPlan S offered assignment = true)
    {t : Token} (ht : t ∈ S.ledger.initial)
    {e e' : Operation} {c c' : Claim}
    (he : (advancePrepare S assignment).controller.lifecycle.opClaim e = some c)
    (he' : (advancePrepare S assignment).controller.lifecycle.opClaim e' = some c')
    (hc : (advancePrepare S assignment).ledger.origin c = some t)
    (hc' : (advancePrepare S assignment).ledger.origin c' = some t) : e = e' :=
  (checkedPrepare_preserves_linearity S offered assignment hSource h).distinct_bindings
    (by simpa [advancePrepare] using ht) he he' hc hc'

/-! ## Merge transport -/

def advanceSimulationMergeToken
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (d : MergeDescriptor Claim Branch) :
    TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token) :=
  let controller' :=
    _root_.AuthorityContinuity.PlanInvariant.PlanData.advanceSimulationMerge
      S.controller d
  { controller := controller'
    ledger := S.ledger.afterTransfer controller' d.transfer }

def advanceDirectMergeToken
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (d : MergeDescriptor Claim Branch) :
    TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token) :=
  let controller' :=
    _root_.AuthorityContinuity.PlanInvariant.PlanData.advanceDirectMerge
      S.controller d
  { controller := controller'
    ledger := S.ledger.afterTransfer controller' d.transfer }

/-- Simulation Merge keeps its existing admission mode and additionally scans
the computed target's immutable-token fibers. -/
def checkSimulationMergeTokenPlan
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (d : MergeDescriptor Claim Branch)
    (project : Finset Branch -> Finset Branch) (offered : Nat) : Bool :=
  checkSimulationMergePlan S.controller.lifecycle S.controller.plan
      d project offered &&
    (advanceSimulationMergeToken S d).checkLinear

def checkDirectMergeTokenPlan
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (d : MergeDescriptor Claim Branch) (offered : Nat) : Bool :=
  checkDirectMergePlan S.controller.lifecycle S.controller.plan d offered &&
    (advanceDirectMergeToken S d).checkLinear

theorem checkSimulationMergeTokenPlan_parts
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (d : MergeDescriptor Claim Branch)
    (project : Finset Branch -> Finset Branch) (offered : Nat)
    (h : checkSimulationMergeTokenPlan S d project offered = true) :
    checkSimulationMergePlan S.controller.lifecycle S.controller.plan
        d project offered = true ∧
      (advanceSimulationMergeToken S d).checkLinear = true := by
  simpa [checkSimulationMergeTokenPlan, Bool.and_eq_true] using h

theorem checkDirectMergeTokenPlan_parts
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (d : MergeDescriptor Claim Branch) (offered : Nat)
    (h : checkDirectMergeTokenPlan S d offered = true) :
    checkDirectMergePlan S.controller.lifecycle S.controller.plan
        d offered = true ∧
      (advanceDirectMergeToken S d).checkLinear = true := by
  simpa [checkDirectMergeTokenPlan, Bool.and_eq_true] using h

theorem checkedSimulationMerge_preserves_linearity
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (d : MergeDescriptor Claim Branch)
    (project : Finset Branch -> Finset Branch) (offered : Nat)
    (_hSource : S.LinearValid)
    (h : checkSimulationMergeTokenPlan S d project offered = true) :
    (advanceSimulationMergeToken S d).LinearValid :=
  TokenState.checkLinear_sound _
    (checkSimulationMergeTokenPlan_parts S d project offered h).2

theorem checkedDirectMerge_preserves_linearity
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (d : MergeDescriptor Claim Branch) (offered : Nat)
    (_hSource : S.LinearValid)
    (h : checkDirectMergeTokenPlan S d offered = true) :
    (advanceDirectMergeToken S d).LinearValid :=
  TokenState.checkLinear_sound _
    (checkDirectMergeTokenPlan_parts S d offered h).2

theorem checkedSimulationMerge_same_token_eq
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (d : MergeDescriptor Claim Branch)
    (project : Finset Branch -> Finset Branch) (offered : Nat)
    (hSource : S.LinearValid)
    (h : checkSimulationMergeTokenPlan S d project offered = true)
    {t : Token} (ht : t ∈ S.ledger.initial) {c c' : Claim}
    (hc : c ∈ (advanceSimulationMergeToken S d).controller.plan.remaining)
    (hc' : c' ∈ (advanceSimulationMergeToken S d).controller.plan.remaining)
    (ho : (advanceSimulationMergeToken S d).ledger.origin c = some t)
    (ho' : (advanceSimulationMergeToken S d).ledger.origin c' = some t) :
    c = c' :=
  (checkedSimulationMerge_preserves_linearity S d project offered hSource h).distinct_current_claims
      (by simpa [advanceSimulationMergeToken] using ht) hc hc' ho ho'

theorem checkedDirectMerge_same_token_eq
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (d : MergeDescriptor Claim Branch) (offered : Nat)
    (hSource : S.LinearValid)
    (h : checkDirectMergeTokenPlan S d offered = true)
    {t : Token} (ht : t ∈ S.ledger.initial) {c c' : Claim}
    (hc : c ∈ (advanceDirectMergeToken S d).controller.plan.remaining)
    (hc' : c' ∈ (advanceDirectMergeToken S d).controller.plan.remaining)
    (ho : (advanceDirectMergeToken S d).ledger.origin c = some t)
    (ho' : (advanceDirectMergeToken S d).ledger.origin c' = some t) :
    c = c' :=
  (checkedDirectMerge_preserves_linearity S d offered hSource h).distinct_current_claims
      (by simpa [advanceDirectMergeToken] using ht) hc hc' ho ho'

/-! ## Restriction and actual Revoke -/

def advanceRestrictionToken
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (owners : Finset Branch) (keep : Finset Claim) :
    TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token) :=
  let controller' :=
    _root_.AuthorityContinuity.PlanInvariant.PlanData.advanceRestriction
      S.controller owners keep
  { controller := controller'
    ledger := S.ledger.reclassify controller' }

def advanceRevokeToken
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (g : Grant) :
    TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token) :=
  let controller' :=
    _root_.AuthorityContinuity.PlanInvariant.PlanData.advanceRevoke
      S.controller g
  { controller := controller'
    ledger := S.ledger.reclassify controller' }

/-- Restriction is admitted by the same durable version equality as the base
relation and a finite scan of the computed target. Removed token witnesses are
therefore classified from the actual target, not from an asserted drop set. -/
def checkRestrictionTokenPlan
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (owners : Finset Branch) (keep : Finset Claim) (offered : Nat) : Bool :=
  S.controller.plan.checkVersion offered &&
    (advanceRestrictionToken S owners keep).checkLinear

def checkRevokeTokenPlan
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (g : Grant) (offered : Nat) : Bool :=
  S.controller.plan.checkVersion offered &&
    (advanceRevokeToken S g).checkLinear

theorem checkRestrictionTokenPlan_parts
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (owners : Finset Branch) (keep : Finset Claim) (offered : Nat)
    (h : checkRestrictionTokenPlan S owners keep offered = true) :
    S.controller.plan.checkVersion offered = true ∧
      (advanceRestrictionToken S owners keep).checkLinear = true := by
  simpa [checkRestrictionTokenPlan, Bool.and_eq_true] using h

theorem checkRevokeTokenPlan_parts
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (g : Grant) (offered : Nat)
    (h : checkRevokeTokenPlan S g offered = true) :
    S.controller.plan.checkVersion offered = true ∧
      (advanceRevokeToken S g).checkLinear = true := by
  simpa [checkRevokeTokenPlan, Bool.and_eq_true] using h

theorem checkedRestriction_preserves_linearity
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (owners : Finset Branch) (keep : Finset Claim) (offered : Nat)
    (_hSource : S.LinearValid)
    (h : checkRestrictionTokenPlan S owners keep offered = true) :
    (advanceRestrictionToken S owners keep).LinearValid :=
  TokenState.checkLinear_sound _
    (checkRestrictionTokenPlan_parts S owners keep offered h).2

theorem checkedRevoke_preserves_linearity
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (g : Grant) (offered : Nat) (_hSource : S.LinearValid)
    (h : checkRevokeTokenPlan S g offered = true) :
    (advanceRevokeToken S g).LinearValid :=
  TokenState.checkLinear_sound _
    (checkRevokeTokenPlan_parts S g offered h).2

/-- A checked restriction computes withdrawal from absence of both kinds of
actual target witness. -/
theorem checkedRestriction_withdrawn
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (owners : Finset Branch) (keep : Finset Claim) (offered : Nat)
    (hSource : S.LinearValid)
    (h : checkRestrictionTokenPlan S owners keep offered = true)
    {t : Token} (ht : t ∈ S.ledger.initial)
    (hNoCurrent : ¬ ((advanceRestrictionToken S owners keep).currentFiber t).Nonempty)
    (hNoBinding : ¬ ((advanceRestrictionToken S owners keep).bindingFiber t).Nonempty) :
    (advanceRestrictionToken S owners keep).ledger.disposition t = .withdrawn := by
  have hTarget := checkedRestriction_preserves_linearity
    S owners keep offered hSource h
  rw [hTarget.disposition_exact t
    (by simpa [advanceRestrictionToken] using ht)]
  have hNoCurrent' : ¬ (TokenLedger.currentFiber
      (advanceRestrictionToken S owners keep).controller.plan
      (advanceRestrictionToken S owners keep).ledger t).Nonempty := by
    simpa [TokenState.currentFiber] using hNoCurrent
  have hNoBinding' : ¬ (TokenLedger.bindingFiber
      (advanceRestrictionToken S owners keep).controller.lifecycle
      (advanceRestrictionToken S owners keep).ledger t).Nonempty := by
    simpa [TokenState.bindingFiber] using hNoBinding
  simp [TokenLedger.computedDisposition, hNoCurrent', hNoBinding']

/-- The same computed-withdrawal statement for actual grant Revoke. -/
theorem checkedRevoke_withdrawn
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (g : Grant) (offered : Nat) (hSource : S.LinearValid)
    (h : checkRevokeTokenPlan S g offered = true)
    {t : Token} (ht : t ∈ S.ledger.initial)
    (hNoCurrent : ¬ ((advanceRevokeToken S g).currentFiber t).Nonempty)
    (hNoBinding : ¬ ((advanceRevokeToken S g).bindingFiber t).Nonempty) :
    (advanceRevokeToken S g).ledger.disposition t = .withdrawn := by
  have hTarget := checkedRevoke_preserves_linearity S g offered hSource h
  rw [hTarget.disposition_exact t (by simpa [advanceRevokeToken] using ht)]
  have hNoCurrent' : ¬ (TokenLedger.currentFiber
      (advanceRevokeToken S g).controller.plan
      (advanceRevokeToken S g).ledger t).Nonempty := by
    simpa [TokenState.currentFiber] using hNoCurrent
  have hNoBinding' : ¬ (TokenLedger.bindingFiber
      (advanceRevokeToken S g).controller.lifecycle
      (advanceRevokeToken S g).ledger t).Nonempty := by
    simpa [TokenState.bindingFiber] using hNoBinding
  simp [TokenLedger.computedDisposition, hNoCurrent', hNoBinding']

/-! ## Ticket-phase stutter and unified checked grammar -/

/-- Ticket dispatch/retry/crash/settle changes lifecycle metadata but neither
the plan nor the immutable ledger. Stable `opClaim` makes this a semantic
token stutter even when a ticket moves into a receipt. -/
def advanceTicketToken
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (A' : LifecycleState Coord Claim Branch Grant Operation) :
    TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token) :=
  { controller := { lifecycle := A', plan := S.controller.plan }
    ledger := S.ledger }

@[simp] theorem advanceTicketToken_version
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (A' : LifecycleState Coord Claim Branch Grant Operation) :
    (advanceTicketToken S A').controller.plan.version =
      S.controller.plan.version := rfl

@[simp] theorem advanceTicketToken_ledger
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (A' : LifecycleState Coord Claim Branch Grant Operation) :
    (advanceTicketToken S A').ledger = S.ledger := rfl

theorem ticket_preserves_linearity
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    {A' : LifecycleState Coord Claim Branch Grant Operation}
    {eta : Label Operation Claim}
    (h : TicketStep S.controller.lifecycle eta A')
    (hSource : S.LinearValid) :
    (advanceTicketToken S A').LinearValid := by
  have hop : A'.opClaim = S.controller.lifecycle.opClaim :=
    funext (ticketStep_binding_eq h)
  rcases hSource with
    ⟨hCovered, hBindingCovered, hCurrent, hBinding, hExclusive, hDisposition⟩
  refine ⟨?_, ?_, ?_, ?_, ?_, ?_⟩
  · simpa [advanceTicketToken] using hCovered
  · intro e c he
    apply hBindingCovered e c
    simpa [advanceTicketToken, hop] using he
  · simpa [TokenState.currentFiber, TokenLedger.currentFiber,
      advanceTicketToken] using hCurrent
  · simpa [TokenState.bindingFiber, TokenLedger.bindingFiber,
      advanceTicketToken, hop] using hBinding
  · simpa [TokenState.currentFiber, TokenState.bindingFiber,
      TokenLedger.currentFiber, TokenLedger.bindingFiber,
      advanceTicketToken, hop] using hExclusive
  · simpa [TokenLedger.computedDisposition, TokenLedger.currentFiber,
      TokenLedger.bindingFiber, advanceTicketToken, hop] using hDisposition

/-- Coupled source safety used by arbitrary token-aware controller histories. -/
structure TokenSafe
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token)) : Prop where
  controllerSafe : Safe S.controller
  tokenLinear : S.LinearValid

/-- One token-aware positive edge. Mutating cases reuse the existing planned
relation and demand a successful executable scan of their exact computed
target. Checkpoint and ticket phases stutter the ledger. -/
inductive TokenPositiveStep :
    TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token) ->
    Label Operation Claim ->
    TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token) -> Prop where
  | checkpoint (S) : TokenPositiveStep S .tau S
  | prepare {S offered assignment}
      (hPlan : PreparePlanned S.controller offered assignment
        (advancePrepare S assignment).controller)
      (hToken : (advancePrepare S assignment).checkLinear = true) :
      TokenPositiveStep S .tau (advancePrepare S assignment)
  | canonical {S offered tr op}
      (hPlan : CanonicalTransportPlanned S.controller offered tr op
        (advanceCanonical S tr op).controller)
      (hToken : (advanceCanonical S tr op).checkLinear = true) :
      TokenPositiveStep S .tau (advanceCanonical S tr op)
  | restriction {S offered owners keep}
      (hPlan : RestrictionPlanned S.controller offered owners keep
        (advanceRestrictionToken S owners keep).controller)
      (hToken : (advanceRestrictionToken S owners keep).checkLinear = true) :
      TokenPositiveStep S .tau (advanceRestrictionToken S owners keep)
  | revoke {S offered g}
      (hPlan : RevokePlanned S.controller offered g
        (advanceRevokeToken S g).controller)
      (hToken : (advanceRevokeToken S g).checkLinear = true) :
      TokenPositiveStep S .tau (advanceRevokeToken S g)
  | simulationMerge {S offered d project}
      (hPlan : SimulationMergePlanned S.controller offered d project
        (advanceSimulationMergeToken S d).controller)
      (hToken : (advanceSimulationMergeToken S d).checkLinear = true) :
      TokenPositiveStep S .tau (advanceSimulationMergeToken S d)
  | directMerge {S offered d}
      (hPlan : DirectMergePlanned S.controller offered d
        (advanceDirectMergeToken S d).controller)
      (hToken : (advanceDirectMergeToken S d).checkLinear = true) :
      TokenPositiveStep S .tau (advanceDirectMergeToken S d)
  | ticket (S) {A' : LifecycleState Coord Claim Branch Grant Operation}
      {eta : Label Operation Claim}
      (h : TicketStep S.controller.lifecycle eta A') :
      TokenPositiveStep S eta (advanceTicketToken S A')

/-! The following bridge the executable Boolean admissions above to the
unified relation. No semantic target invariant is accepted as a premise. -/

theorem checkedPrepare_token_step
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (offered : Nat) (assignment : Operation -> Option Claim)
    (hSafe : Safe S.controller)
    (h : checkPrepareTokenPlan S offered assignment = true) :
    TokenPositiveStep S .tau (advancePrepare S assignment) := by
  have hp := checkPrepareTokenPlan_parts S offered assignment h
  exact .prepare
    (.mk hSafe.lwf hSafe.planValid hp.2.1 hp.1 hp.2.2.1)
    hp.2.2.2

theorem checkedCanonical_token_step
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (tr : Transfer Claim Branch) (op : CanonicalOp Branch) (offered : Nat)
    (hSafe : Safe S.controller)
    (h : checkCanonicalTokenPlan S tr op offered = true) :
    TokenPositiveStep S .tau (advanceCanonical S tr op) := by
  have hp := checkCanonicalTokenPlan_parts S tr op offered h
  exact .canonical
    (canonicalTransportPlanned_of_check hSafe.lwf hSafe.ac
      hSafe.activeExact hSafe.planValid hp.1)
    hp.2

theorem checkedRestriction_token_step
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (owners : Finset Branch) (keep : Finset Claim) (offered : Nat)
    (_hSafe : Safe S.controller)
    (h : checkRestrictionTokenPlan S owners keep offered = true) :
    TokenPositiveStep S .tau (advanceRestrictionToken S owners keep) := by
  have hp := checkRestrictionTokenPlan_parts S owners keep offered h
  exact .restriction (.mk hp.1) hp.2

theorem checkedRevoke_token_step
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (g : Grant) (offered : Nat) (_hSafe : Safe S.controller)
    (h : checkRevokeTokenPlan S g offered = true) :
    TokenPositiveStep S .tau (advanceRevokeToken S g) := by
  have hp := checkRevokeTokenPlan_parts S g offered h
  exact .revoke (.mk hp.1) hp.2

theorem checkedSimulationMerge_token_step
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (d : MergeDescriptor Claim Branch)
    (project : Finset Branch -> Finset Branch) (offered : Nat)
    (hSafe : Safe S.controller)
    (h : checkSimulationMergeTokenPlan S d project offered = true) :
    TokenPositiveStep S .tau (advanceSimulationMergeToken S d) := by
  have hp := checkSimulationMergeTokenPlan_parts S d project offered h
  exact .simulationMerge
    (simulationMergePlanned_of_check hSafe.lwf hSafe.ac
      hSafe.activeExact hSafe.planValid hp.1)
    hp.2

theorem checkedDirectMerge_token_step
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (d : MergeDescriptor Claim Branch) (offered : Nat)
    (hSafe : Safe S.controller)
    (h : checkDirectMergeTokenPlan S d offered = true) :
    TokenPositiveStep S .tau (advanceDirectMergeToken S d) := by
  have hp := checkDirectMergeTokenPlan_parts S d offered h
  exact .directMerge
    (directMergePlanned_of_check hSafe.lwf hSafe.planValid hp.1)
    hp.2

theorem TokenPositiveStep.toPositiveStep
    {S S' : TokenState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot) (Token := Token)}
    {eta : Label Operation Claim} (h : TokenPositiveStep S eta S') :
    PositiveStep S.controller eta S'.controller := by
  cases h with
  | checkpoint => exact .checkpoint _
  | prepare hPlan _ => exact .prepare hPlan
  | canonical hPlan _ => exact .canonical hPlan
  | restriction hPlan _ => exact .restriction hPlan
  | revoke hPlan _ => exact .revoke hPlan
  | simulationMerge hPlan _ => exact .simulationMerge hPlan
  | directMerge hPlan _ => exact .directMerge hPlan
  | ticket h => exact .ticket _ h

theorem TokenPositiveStep.preserves_linearity
    {S S' : TokenState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot) (Token := Token)}
    {eta : Label Operation Claim} (h : TokenPositiveStep S eta S')
    (hSource : S.LinearValid) : S'.LinearValid := by
  cases h with
  | checkpoint => exact hSource
  | prepare _ hToken => exact TokenState.checkLinear_sound _ hToken
  | canonical _ hToken => exact TokenState.checkLinear_sound _ hToken
  | restriction _ hToken => exact TokenState.checkLinear_sound _ hToken
  | revoke _ hToken => exact TokenState.checkLinear_sound _ hToken
  | simulationMerge _ hToken => exact TokenState.checkLinear_sound _ hToken
  | directMerge _ hToken => exact TokenState.checkLinear_sound _ hToken
  | ticket h => exact ticket_preserves_linearity _ h hSource

theorem TokenPositiveStep.preserves_safe
    {S S' : TokenState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot) (Token := Token)}
    {eta : Label Operation Claim} (h : TokenPositiveStep S eta S')
    (hSafe : TokenSafe S) : TokenSafe S' :=
  ⟨h.toPositiveStep.preserves_safe hSafe.controllerSafe,
    h.preserves_linearity hSafe.tokenLinear⟩

theorem TokenPositiveStep.actual_step
    {S S' : TokenState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot) (Token := Token)}
    {eta : Label Operation Claim} (h : TokenPositiveStep S eta S') :
    Step S.controller.lifecycle eta S'.controller.lifecycle :=
  h.toPositiveStep.actual_step

theorem TokenPositiveStep.version_mono
    {S S' : TokenState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot) (Token := Token)}
    {eta : Label Operation Claim} (h : TokenPositiveStep S eta S') :
    S.controller.plan.version <= S'.controller.plan.version :=
  h.toPositiveStep.version_mono

/-- No edge mints tokens after plan creation. A quantitative split must place
several distinct tokens in `initial` before entering this grammar. -/
theorem TokenPositiveStep.initial_eq
    {S S' : TokenState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot) (Token := Token)}
    {eta : Label Operation Claim} (h : TokenPositiveStep S eta S') :
    S.ledger.initial = S'.ledger.initial := by
  cases h <;> rfl

def TokenPositiveEdge
    (S S' : TokenState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot) (Token := Token)) : Prop :=
  ∃ eta, TokenPositiveStep S eta S'

abbrev TokenPositiveTrace
    (S S' : TokenState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot) (Token := Token)) : Prop :=
  Relation.ReflTransGen TokenPositiveEdge S S'

theorem token_positive_trace_preserves
    {S S' : TokenState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot) (Token := Token)}
    (hTrace : TokenPositiveTrace S S') (hSafe : TokenSafe S) :
    TokenSafe S' := by
  induction hTrace with
  | refl => exact hSafe
  | tail _ hEdge ih =>
      obtain ⟨eta, hStep⟩ := hEdge
      exact hStep.preserves_safe ih

/-- Erasing only the token ledger yields the existing positive controller
grammar, so the token theorem is conservative over the actual semantics. -/
theorem token_positive_trace_projects
    {S S' : TokenState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot) (Token := Token)}
    (hTrace : TokenPositiveTrace S S') :
    PositiveTrace S.controller S'.controller := by
  induction hTrace with
  | refl => exact .refl
  | tail _ hEdge ih =>
      obtain ⟨eta, hStep⟩ := hEdge
      exact ih.tail ⟨eta, hStep.toPositiveStep⟩

theorem token_positive_trace_projects_actual
    {S S' : TokenState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot) (Token := Token)}
    (hTrace : TokenPositiveTrace S S') :
    AbstractTrace S.controller.lifecycle S'.controller.lifecycle :=
  positive_trace_projects (token_positive_trace_projects hTrace)

theorem token_positive_trace_version_mono
    {S S' : TokenState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot) (Token := Token)}
    (hTrace : TokenPositiveTrace S S') :
    S.controller.plan.version <= S'.controller.plan.version :=
  positive_trace_version_mono (token_positive_trace_projects hTrace)

theorem token_positive_trace_initial_eq
    {S S' : TokenState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot) (Token := Token)}
    (hTrace : TokenPositiveTrace S S') :
    S.ledger.initial = S'.ledger.initial := by
  induction hTrace with
  | refl => rfl
  | tail _ hEdge ih =>
      obtain ⟨eta, hStep⟩ := hEdge
      exact ih.trans hStep.initial_eq

/-! ## Executable regression: zero-demand duplication -/

namespace ZeroDemandRegression

abbrev ZCoord := Fin 1
abbrev ZClaim := Fin 3
abbrev ZBranch := Fin 3
abbrev ZGrant := Fin 1
abbrev ZOperation := Fin 2
abbrev ZSlot := Fin 1
abbrev ZToken := Fin 1

def source : LifecycleState ZCoord ZClaim ZBranch ZGrant ZOperation where
  auth := {
    capacity := fun _ => 0
    demand := fun _ _ => 0
    status := fun c => if c = 0 then .tentative 0 else .unissued
    allowed := ({0} : Finset ZBranch).powerset }
  grantOf := fun _ => 0
  branchEpoch := fun b => if b = 0 then .open else .unissued
  grantEpoch := fun _ => .open
  tickets := fun _ => none
  receipts := fun _ => none

def split : Transfer ZClaim ZBranch where
  owner := fun c => if c = 1 then some 1 else if c = 2 then some 2 else none
  rho := fun c => if c = 1 ∨ c = 2 then some 0 else none

def fork : CanonicalOp ZBranch := .parallelFork 0 1 2

def plan : PlanData (Coord := ZCoord) (Claim := ZClaim) (Slot := ZSlot) where
  version := 0
  d0 := fun _ => 0
  cap0 := fun _ => 0
  slots := Finset.univ
  rootSlot := fun c => if c = 0 then some 0 else none
  remaining := {0}
  R := fun _ _ => 0
  P := fun _ _ => 0
  E := fun _ _ => 0

def ledger : TokenLedger ZClaim ZToken where
  initial := {0}
  origin := fun c => if c = 0 then some 0 else none
  disposition := fun _ => .remaining

def state : TokenState (Coord := ZCoord) (Claim := ZClaim)
    (Branch := ZBranch) (Grant := ZGrant) (Operation := ZOperation)
    (Slot := ZSlot) (Token := ZToken) where
  controller := { lifecycle := source, plan := plan }
  ledger := ledger

theorem source_token_check_accepts : state.checkLinear = true := by
  decide

theorem base_plan_check_accepts :
    checkCanonicalPlan source plan split fork 0 = true := by
  decide

/-- The old demand-based checker accepts, while the discrete token checker
rejects the two-child fiber even though every coordinate has demand zero. -/
theorem zero_demand_parallelFork_rejected :
    checkCanonicalPlan source plan split fork 0 = true ∧
      checkCanonicalTokenPlan state split fork 0 = false := by
  decide

theorem duplicated_token_fiber_cardinality :
    ((advanceCanonical state split fork).currentFiber 0).card = 2 := by
  decide

end ZeroDemandRegression

#print axioms TokenState.checkLinear_sound
#print axioms TokenState.LinearValid.token_trichotomy
#print axioms checkedCanonical_same_token_eq
#print axioms checkedPrepare_head_token_prepared
#print axioms checkedPrepare_distinct_tickets
#print axioms checkedSimulationMerge_same_token_eq
#print axioms checkedRestriction_withdrawn
#print axioms ticket_preserves_linearity
#print axioms TokenPositiveStep.preserves_safe
#print axioms token_positive_trace_preserves
#print axioms token_positive_trace_projects_actual
#print axioms token_positive_trace_initial_eq
#print axioms ZeroDemandRegression.zero_demand_parallelFork_rejected

end AuthorityContinuity.PlanTokenLinearity
