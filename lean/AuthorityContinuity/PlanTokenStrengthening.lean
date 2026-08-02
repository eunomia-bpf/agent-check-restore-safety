import AuthorityContinuity.PlanTokenLinearity

/-!
# Source-derived token transport

The complete target `checkLinear` scan remains the executable defense in
depth.  This module exposes the smaller reason why canonical and Merge
transfers are admissible: the actual `rho` preimage of the selected source
batch must not amplify one source token into two current target witnesses.
It also derives the stable durable-operation part from source lifecycle facts
rather than from a target invariant premise.
-/

namespace AuthorityContinuity.PlanTokenStrengthening

open AuthorityContinuity LifecycleState
open AuthorityContinuity.PlanInvariant
open AuthorityContinuity.PlanInvariant.PlanData
open AuthorityContinuity.PlanTokenLinearity

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

/-- Current target witnesses computed solely from the source selected batch,
the source origin ledger, and the actual transfer map. -/
def transferCurrentFiber
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (tr : Transfer Claim Branch) (t : Token) : Finset Claim :=
  (Plan.childBatch tr S.controller.plan.remaining).filter fun c' =>
    S.ledger.transportedOrigin tr c' = some t

/-- Transfer-local, demand-independent non-amplification. -/
def TransferTokenNonAmplifying
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (tr : Transfer Claim Branch) : Prop :=
  forall t, t ∈ S.ledger.initial -> (transferCurrentFiber S tr t).card <= 1

/-- Executable local atom.  Unlike `checkLinear`, it reads no target lifecycle
state and no demand coordinate. -/
def checkTransferTokenNonAmplifying
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (tr : Transfer Claim Branch) : Bool :=
  finiteAll S.ledger.initial fun t =>
    decide ((transferCurrentFiber S tr t).card <= 1)

theorem checkTransferTokenNonAmplifying_sound
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (tr : Transfer Claim Branch)
    (h : checkTransferTokenNonAmplifying S tr = true) :
    TransferTokenNonAmplifying S tr := by
  intro t ht
  exact of_decide_eq_true
    ((finiteAll_eq_true S.ledger.initial _).mp h t ht)

theorem checkTransferTokenNonAmplifying_complete
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (tr : Transfer Claim Branch)
    (h : TransferTokenNonAmplifying S tr) :
    checkTransferTokenNonAmplifying S tr = true := by
  unfold checkTransferTokenNonAmplifying
  rw [finiteAll_eq_true]
  intro t ht
  exact decide_eq_true (h t ht)

/-- Exact characterization of the local fiber as the current fiber of any
computed transfer target with the standard child batch. -/
theorem afterTransfer_currentFiber_eq
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (tr : Transfer Claim Branch)
    (controller' : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot))
    (hRemaining : controller'.plan.remaining =
      Plan.childBatch tr S.controller.plan.remaining)
    (t : Token) :
    (TokenState.mk controller'
      (S.ledger.afterTransfer controller' tr)).currentFiber t =
      transferCurrentFiber S tr t := by
  ext c
  simp [TokenState.currentFiber, TokenLedger.currentFiber,
    transferCurrentFiber, TokenLedger.afterTransfer,
    TokenLedger.reclassify, TokenLedger.transportedOrigin, hRemaining]

/-- Generic transport law: for any controller target whose current plan is the
computed child batch, the actual-`rho` local atom is exactly current-token
linearity in the reclassified target.  Coverage, binding linearity,
current/bound exclusivity, and disposition exactness remain separate
obligations of the complete target invariant. -/
theorem afterTransfer_nonAmplifying_iff_target_current_linear
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (tr : Transfer Claim Branch)
    (controller' : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot))
    (hRemaining : controller'.plan.remaining =
      Plan.childBatch tr S.controller.plan.remaining) :
    TransferTokenNonAmplifying S tr ↔
      forall t,
        t ∈ (S.ledger.afterTransfer controller' tr).initial ->
        ((TokenState.mk controller'
          (S.ledger.afterTransfer controller' tr)).currentFiber t).card <= 1 := by
  simp only [TransferTokenNonAmplifying]
  constructor <;> intro h t ht
  · rw [afterTransfer_currentFiber_eq S tr controller' hRemaining]
    exact h t (by simpa [TokenLedger.afterTransfer,
      TokenLedger.reclassify] using ht)
  · rw [← afterTransfer_currentFiber_eq S tr controller' hRemaining t]
    exact h t (by simpa [TokenLedger.afterTransfer,
      TokenLedger.reclassify] using ht)

theorem canonical_currentFiber_eq
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (tr : Transfer Claim Branch) (op : CanonicalOp Branch) (t : Token) :
    (advanceCanonical S tr op).currentFiber t =
      transferCurrentFiber S tr t := by
  apply afterTransfer_currentFiber_eq
  rfl

theorem simulationMerge_currentFiber_eq
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (d : MergeDescriptor Claim Branch) (t : Token) :
    (advanceSimulationMergeToken S d).currentFiber t =
      transferCurrentFiber S d.transfer t := by
  apply afterTransfer_currentFiber_eq
  rfl

theorem directMerge_currentFiber_eq
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (d : MergeDescriptor Claim Branch) (t : Token) :
    (advanceDirectMergeToken S d).currentFiber t =
      transferCurrentFiber S d.transfer t := by
  apply afterTransfer_currentFiber_eq
  rfl

/-- Precise characterization: the local atom is exactly target current-fiber
linearity for the computed canonical target. -/
theorem canonical_nonAmplifying_iff_target_current_linear
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (tr : Transfer Claim Branch) (op : CanonicalOp Branch) :
    TransferTokenNonAmplifying S tr ↔
      forall t, t ∈ (advanceCanonical S tr op).ledger.initial ->
        ((advanceCanonical S tr op).currentFiber t).card <= 1 := by
  simpa [advanceCanonical] using
    (afterTransfer_nonAmplifying_iff_target_current_linear S tr
      (advanceCanonicalTransport S.controller tr op) (by rfl))

theorem simulationMerge_nonAmplifying_iff_target_current_linear
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (d : MergeDescriptor Claim Branch) :
    TransferTokenNonAmplifying S d.transfer ↔
      forall t, t ∈ (advanceSimulationMergeToken S d).ledger.initial ->
        ((advanceSimulationMergeToken S d).currentFiber t).card <= 1 := by
  simpa [advanceSimulationMergeToken] using
    (afterTransfer_nonAmplifying_iff_target_current_linear S d.transfer
      (_root_.AuthorityContinuity.PlanInvariant.PlanData.advanceSimulationMerge
        S.controller d) (by rfl))

theorem directMerge_nonAmplifying_iff_target_current_linear
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (d : MergeDescriptor Claim Branch) :
    TransferTokenNonAmplifying S d.transfer ↔
      forall t, t ∈ (advanceDirectMergeToken S d).ledger.initial ->
        ((advanceDirectMergeToken S d).currentFiber t).card <= 1 := by
  simpa [advanceDirectMergeToken] using
    (afterTransfer_nonAmplifying_iff_target_current_linear S d.transfer
      (_root_.AuthorityContinuity.PlanInvariant.PlanData.advanceDirectMerge
        S.controller d) (by rfl))

/-- Existing durable operation claims are outside every valid `rho` domain. -/
theorem bound_durable_rho_none
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (tr : Transfer Claim Branch) (hWF : A.LWF)
    (hCore : Transfer.CoreValid A tr) {e : Operation} {c : Claim}
    (hop : A.opClaim e = some c) : tr.rho c = none :=
  Transfer.rho_eq_none_of_durable A tr hCore c
    (hWF.bound_durable e c hop)

/-- Explicit durable operation-origin stability for the ledger transfer. -/
theorem bound_durable_origin_afterTransfer
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (controller' : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot))
    (ledger : TokenLedger Claim Token) (tr : Transfer Claim Branch)
    (hWF : A.LWF) (hCore : Transfer.CoreValid A tr)
    {e : Operation} {c : Claim} (hop : A.opClaim e = some c) :
    (ledger.afterTransfer controller' tr).origin c = ledger.origin c := by
  have hrho := bound_durable_rho_none A tr hWF hCore hop
  simp [TokenLedger.afterTransfer, TokenLedger.reclassify,
    TokenLedger.transportedOrigin, hrho]

/-- Stable durable bindings induce exactly the same token fiber after a valid
computed transfer. -/
theorem afterTransfer_bindingFiber_eq
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (controller' : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot))
    (tr : Transfer Claim Branch)
    (hOpClaim : controller'.lifecycle.opClaim =
      S.controller.lifecycle.opClaim)
    (hWF : S.controller.lifecycle.LWF)
    (hCore : Transfer.CoreValid S.controller.lifecycle tr)
    (t : Token) :
    (TokenState.mk controller'
      (S.ledger.afterTransfer controller' tr)).bindingFiber t =
      S.bindingFiber t := by
  ext e
  simp only [TokenState.bindingFiber, TokenLedger.bindingFiber,
    Finset.mem_filter, Finset.mem_univ, true_and]
  have hopEq : controller'.lifecycle.opClaim e =
      S.controller.lifecycle.opClaim e := congrFun hOpClaim e
  cases hop : S.controller.lifecycle.opClaim e with
  | none => simp [hopEq, hop]
  | some c =>
      have hrho : tr.rho c = none :=
        bound_durable_rho_none S.controller.lifecycle tr hWF hCore hop
      simp [hopEq, hop, TokenLedger.afterTransfer, TokenLedger.reclassify,
        TokenLedger.transportedOrigin, hrho]

/-- Source-derived transfer theorem.  `checkLinear` is not used: current
linearity comes from the local non-amplification atom; all prior durable
bindings come from source `LWF`, transfer provenance, and stable `opClaim`.
The ledger's disposition is exact because the target is reclassified. -/
theorem afterTransfer_preserves_linearity_source
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (controller' : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot))
    (tr : Transfer Claim Branch)
    (hRemaining : controller'.plan.remaining =
      Plan.childBatch tr S.controller.plan.remaining)
    (hOpClaim : controller'.lifecycle.opClaim =
      S.controller.lifecycle.opClaim)
    (hWF : S.controller.lifecycle.LWF)
    (hCore : Transfer.CoreValid S.controller.lifecycle tr)
    (hSource : S.LinearValid)
    (hNonAmplifying : TransferTokenNonAmplifying S tr) :
    (TokenState.mk controller'
      (S.ledger.afterTransfer controller' tr)).LinearValid := by
  let T : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token) :=
    TokenState.mk controller' (S.ledger.afterTransfer controller' tr)
  have hBindingFiber : forall t, T.bindingFiber t = S.bindingFiber t := by
    intro t
    exact afterTransfer_bindingFiber_eq S controller' tr hOpClaim hWF hCore t
  refine {
    current_covered := ?_
    binding_covered := ?_
    current_linear := ?_
    binding_linear := ?_
    exclusive := ?_
    disposition_exact := ?_ }
  · intro c' hc'
    have hcChild : c' ∈ Plan.childBatch tr S.controller.plan.remaining := by
      simpa [T, hRemaining] using hc'
    obtain ⟨c, hc, hrho⟩ :
        ∃ c ∈ S.controller.plan.remaining, tr.rho c' = some c := by
      simpa [Plan.childBatch] using hcChild
    obtain ⟨t, ht, horigin⟩ := hSource.current_covered c hc
    refine ⟨t, ?_, ?_⟩
    · simpa [T, TokenLedger.afterTransfer] using ht
    · simp [T, TokenLedger.afterTransfer, TokenLedger.reclassify,
        TokenLedger.transportedOrigin, hrho, horigin]
  · intro e c he
    have heSource : S.controller.lifecycle.opClaim e = some c := by
      have hopEq := congrFun hOpClaim e
      rw [hopEq] at he
      exact he
    obtain ⟨t, ht, horigin⟩ := hSource.binding_covered e c heSource
    refine ⟨t, ?_, ?_⟩
    · simpa [T, TokenLedger.afterTransfer] using ht
    · rw [show T.ledger.origin c = S.ledger.origin c by
        simpa [T] using bound_durable_origin_afterTransfer
          S.controller.lifecycle controller' S.ledger tr hWF hCore heSource]
      exact horigin
  · intro t ht
    rw [afterTransfer_currentFiber_eq S tr controller' hRemaining]
    apply hNonAmplifying t
    simpa [T, TokenLedger.afterTransfer] using ht
  · intro t ht
    rw [hBindingFiber t]
    apply hSource.binding_linear t
    simpa [T, TokenLedger.afterTransfer] using ht
  · intro t ht hBoth
    apply hSource.exclusive t
      (by simpa [T, TokenLedger.afterTransfer] using ht)
    constructor
    · rw [afterTransfer_currentFiber_eq S tr controller' hRemaining] at hBoth
      obtain ⟨c', hc'⟩ := hBoth.1
      have hcData :
          c' ∈ Plan.childBatch tr S.controller.plan.remaining ∧
            S.ledger.transportedOrigin tr c' = some t := by
        simpa [transferCurrentFiber] using hc'
      obtain ⟨c, hc, hrho⟩ :
          ∃ c ∈ S.controller.plan.remaining, tr.rho c' = some c := by
        simpa [Plan.childBatch] using hcData.1
      have horigin : S.ledger.origin c = some t := by
        simpa [TokenLedger.transportedOrigin, hrho] using hcData.2
      refine ⟨c, ?_⟩
      simp [TokenState.currentFiber, TokenLedger.currentFiber, hc, horigin]
    · rw [← hBindingFiber t]
      exact hBoth.2
  · intro t ht
    simp [T, TokenLedger.afterTransfer, TokenLedger.reclassify,
      TokenLedger.computedDisposition, TokenLedger.currentFiber,
      TokenLedger.bindingFiber]

/-! ## Source gate plus defense-in-depth target scan -/

/-- The explanatory canonical gate: existing canonical admission plus the
transfer-local token atom. -/
def checkCanonicalTokenSource
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (tr : Transfer Claim Branch) (op : CanonicalOp Branch)
    (offered : Nat) : Bool :=
  checkCanonicalPlan S.controller.lifecycle S.controller.plan tr op offered &&
    checkTransferTokenNonAmplifying S tr

/-- Production gate: the source/local proof obligation and the original full
target scan.  The latter is retained as defense in depth. -/
def checkCanonicalTokenDefended
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (tr : Transfer Claim Branch) (op : CanonicalOp Branch)
    (offered : Nat) : Bool :=
  checkCanonicalTokenSource S tr op offered &&
    (advanceCanonical S tr op).checkLinear

theorem checkCanonicalTokenSource_parts
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (tr : Transfer Claim Branch) (op : CanonicalOp Branch)
    (offered : Nat) (h : checkCanonicalTokenSource S tr op offered = true) :
    checkCanonicalPlan S.controller.lifecycle S.controller.plan tr op offered = true ∧
      checkTransferTokenNonAmplifying S tr = true := by
  simpa [checkCanonicalTokenSource, Bool.and_eq_true] using h

theorem checkCanonicalTokenDefended_parts
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (tr : Transfer Claim Branch) (op : CanonicalOp Branch)
    (offered : Nat) (h : checkCanonicalTokenDefended S tr op offered = true) :
    checkCanonicalTokenSource S tr op offered = true ∧
      (advanceCanonical S tr op).checkLinear = true := by
  simpa [checkCanonicalTokenDefended, Bool.and_eq_true] using h

/-- Canonical preservation from source facts and the local atom.  No target
`LinearValid` or target `checkLinear` result is used. -/
theorem checkedCanonical_preserves_linearity_source
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (tr : Transfer Claim Branch) (op : CanonicalOp Branch)
    (offered : Nat) (hSafe : Safe S.controller) (hSource : S.LinearValid)
    (h : checkCanonicalTokenSource S tr op offered = true) :
    (advanceCanonical S tr op).LinearValid := by
  have hp := checkCanonicalTokenSource_parts S tr op offered h
  have hCanonical := (checkCanonicalPlan_parts S.controller.lifecycle
    S.controller.plan tr op offered hp.1).2.1
  have hCore := (checkCanonical_sound S.controller.lifecycle tr op
    hCanonical).transfer.toCoreValid
  exact afterTransfer_preserves_linearity_source S
    (advanceCanonical S tr op).controller tr rfl rfl hSafe.lwf hCore
    hSource (checkTransferTokenNonAmplifying_sound S tr hp.2)

/-- The full target scan is present in admission but is not used to establish
the preservation conclusion. -/
theorem checkedCanonicalDefended_preserves_linearity_source
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (tr : Transfer Claim Branch) (op : CanonicalOp Branch)
    (offered : Nat) (hSafe : Safe S.controller) (hSource : S.LinearValid)
    (h : checkCanonicalTokenDefended S tr op offered = true) :
    (advanceCanonical S tr op).LinearValid :=
  checkedCanonical_preserves_linearity_source S tr op offered hSafe hSource
    (checkCanonicalTokenDefended_parts S tr op offered h).1

/-- The explicit local-first defended gate is extensionally equal to the
legacy base-plus-full-target gate: a successful full scan already entails the
local atom.  The operational value is decomposition and early local checking,
not a larger accepted language. -/
theorem checkCanonicalTokenDefended_eq_tokenPlan
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (tr : Transfer Claim Branch) (op : CanonicalOp Branch)
    (offered : Nat) :
    checkCanonicalTokenDefended S tr op offered =
      checkCanonicalTokenPlan S tr op offered := by
  unfold checkCanonicalTokenDefended checkCanonicalTokenSource
    checkCanonicalTokenPlan
  cases hBase : checkCanonicalPlan S.controller.lifecycle S.controller.plan
      tr op offered <;> simp [hBase]
  cases hTarget : (advanceCanonical S tr op).checkLinear <;> simp [hTarget]
  have hLinear := TokenState.checkLinear_sound _ hTarget
  have hLocal : checkTransferTokenNonAmplifying S tr = true :=
    checkTransferTokenNonAmplifying_complete S tr
      ((canonical_nonAmplifying_iff_target_current_linear S tr op).2
        hLinear.current_linear)
  simp [hLocal]

/-- Executing the local-first defended checker produces an edge in the
existing semantic grammar. -/
theorem checkedCanonicalDefended_token_step
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (tr : Transfer Claim Branch) (op : CanonicalOp Branch) (offered : Nat)
    (hSafe : Safe S.controller)
    (h : checkCanonicalTokenDefended S tr op offered = true) :
    TokenPositiveStep S .tau (advanceCanonical S tr op) := by
  apply checkedCanonical_token_step S tr op offered hSafe
  rw [← checkCanonicalTokenDefended_eq_tokenPlan S tr op offered]
  exact h

/-- Shared source/local gate for either Merge admission mode. -/
def checkSimulationMergeTokenSource
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (d : MergeDescriptor Claim Branch)
    (project : Finset Branch -> Finset Branch) (offered : Nat) : Bool :=
  checkSimulationMergePlan S.controller.lifecycle S.controller.plan
      d project offered &&
    checkTransferTokenNonAmplifying S d.transfer

def checkSimulationMergeTokenDefended
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (d : MergeDescriptor Claim Branch)
    (project : Finset Branch -> Finset Branch) (offered : Nat) : Bool :=
  checkSimulationMergeTokenSource S d project offered &&
    (advanceSimulationMergeToken S d).checkLinear

def checkDirectMergeTokenSource
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (d : MergeDescriptor Claim Branch) (offered : Nat) : Bool :=
  checkDirectMergePlan S.controller.lifecycle S.controller.plan d offered &&
    checkTransferTokenNonAmplifying S d.transfer

def checkDirectMergeTokenDefended
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (d : MergeDescriptor Claim Branch) (offered : Nat) : Bool :=
  checkDirectMergeTokenSource S d offered &&
    (advanceDirectMergeToken S d).checkLinear

theorem checkedSimulationMerge_preserves_linearity_source
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (d : MergeDescriptor Claim Branch)
    (project : Finset Branch -> Finset Branch) (offered : Nat)
    (hSafe : Safe S.controller) (hSource : S.LinearValid)
    (h : checkSimulationMergeTokenSource S d project offered = true) :
    (advanceSimulationMergeToken S d).LinearValid := by
  have hp : checkSimulationMergePlan S.controller.lifecycle S.controller.plan
        d project offered = true ∧
      checkTransferTokenNonAmplifying S d.transfer = true := by
    simpa [checkSimulationMergeTokenSource, Bool.and_eq_true] using h
  have hAdmission := (checkSimulationMergePlan_parts S.controller.lifecycle
    S.controller.plan d project offered hp.1).2.1
  have hStructure := simulationAdmission_structural
    S.controller.lifecycle d project hAdmission
  have hCore := (MergeCheck.checkMergeStructure_sound
    S.controller.lifecycle d hStructure).transfer
  exact afterTransfer_preserves_linearity_source S
    (advanceSimulationMergeToken S d).controller d.transfer rfl rfl
    hSafe.lwf hCore hSource
    (checkTransferTokenNonAmplifying_sound S d.transfer hp.2)

theorem checkedSimulationMergeDefended_preserves_linearity_source
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (d : MergeDescriptor Claim Branch)
    (project : Finset Branch -> Finset Branch) (offered : Nat)
    (hSafe : Safe S.controller) (hSource : S.LinearValid)
    (h : checkSimulationMergeTokenDefended S d project offered = true) :
    (advanceSimulationMergeToken S d).LinearValid := by
  have hp : checkSimulationMergeTokenSource S d project offered = true ∧
      (advanceSimulationMergeToken S d).checkLinear = true := by
    simpa [checkSimulationMergeTokenDefended, Bool.and_eq_true] using h
  exact checkedSimulationMerge_preserves_linearity_source S d project offered
    hSafe hSource hp.1

theorem checkedDirectMerge_preserves_linearity_source
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (d : MergeDescriptor Claim Branch) (offered : Nat)
    (hSafe : Safe S.controller) (hSource : S.LinearValid)
    (h : checkDirectMergeTokenSource S d offered = true) :
    (advanceDirectMergeToken S d).LinearValid := by
  have hp : checkDirectMergePlan S.controller.lifecycle S.controller.plan
        d offered = true ∧
      checkTransferTokenNonAmplifying S d.transfer = true := by
    simpa [checkDirectMergeTokenSource, Bool.and_eq_true] using h
  have hAdmission := (checkDirectMergePlan_parts S.controller.lifecycle
    S.controller.plan d offered hp.1).2.1
  have hStructure := directAdmission_structural
    S.controller.lifecycle d hAdmission
  have hCore := (MergeCheck.checkMergeStructure_sound
    S.controller.lifecycle d hStructure).transfer
  exact afterTransfer_preserves_linearity_source S
    (advanceDirectMergeToken S d).controller d.transfer rfl rfl hSafe.lwf
    hCore hSource
    (checkTransferTokenNonAmplifying_sound S d.transfer hp.2)

theorem checkedDirectMergeDefended_preserves_linearity_source
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (d : MergeDescriptor Claim Branch) (offered : Nat)
    (hSafe : Safe S.controller) (hSource : S.LinearValid)
    (h : checkDirectMergeTokenDefended S d offered = true) :
    (advanceDirectMergeToken S d).LinearValid := by
  have hp : checkDirectMergeTokenSource S d offered = true ∧
      (advanceDirectMergeToken S d).checkLinear = true := by
    simpa [checkDirectMergeTokenDefended, Bool.and_eq_true] using h
  exact checkedDirectMerge_preserves_linearity_source S d offered hSafe
    hSource hp.1

theorem checkSimulationMergeTokenDefended_eq_tokenPlan
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (d : MergeDescriptor Claim Branch)
    (project : Finset Branch -> Finset Branch) (offered : Nat) :
    checkSimulationMergeTokenDefended S d project offered =
      checkSimulationMergeTokenPlan S d project offered := by
  unfold checkSimulationMergeTokenDefended checkSimulationMergeTokenSource
    checkSimulationMergeTokenPlan
  cases hBase : checkSimulationMergePlan S.controller.lifecycle
      S.controller.plan d project offered <;> simp [hBase]
  cases hTarget : (advanceSimulationMergeToken S d).checkLinear <;>
    simp [hTarget]
  have hLinear := TokenState.checkLinear_sound _ hTarget
  have hLocal : checkTransferTokenNonAmplifying S d.transfer = true :=
    checkTransferTokenNonAmplifying_complete S d.transfer
      ((simulationMerge_nonAmplifying_iff_target_current_linear S d).2
        hLinear.current_linear)
  simp [hLocal]

theorem checkDirectMergeTokenDefended_eq_tokenPlan
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (d : MergeDescriptor Claim Branch) (offered : Nat) :
    checkDirectMergeTokenDefended S d offered =
      checkDirectMergeTokenPlan S d offered := by
  unfold checkDirectMergeTokenDefended checkDirectMergeTokenSource
    checkDirectMergeTokenPlan
  cases hBase : checkDirectMergePlan S.controller.lifecycle S.controller.plan
      d offered <;> simp [hBase]
  cases hTarget : (advanceDirectMergeToken S d).checkLinear <;> simp [hTarget]
  have hLinear := TokenState.checkLinear_sound _ hTarget
  have hLocal : checkTransferTokenNonAmplifying S d.transfer = true :=
    checkTransferTokenNonAmplifying_complete S d.transfer
      ((directMerge_nonAmplifying_iff_target_current_linear S d).2
        hLinear.current_linear)
  simp [hLocal]

theorem checkedSimulationMergeDefended_token_step
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (d : MergeDescriptor Claim Branch)
    (project : Finset Branch -> Finset Branch) (offered : Nat)
    (hSafe : Safe S.controller)
    (h : checkSimulationMergeTokenDefended S d project offered = true) :
    TokenPositiveStep S .tau (advanceSimulationMergeToken S d) := by
  apply checkedSimulationMerge_token_step S d project offered hSafe
  rw [← checkSimulationMergeTokenDefended_eq_tokenPlan S d project offered]
  exact h

theorem checkedDirectMergeDefended_token_step
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (d : MergeDescriptor Claim Branch) (offered : Nat)
    (hSafe : Safe S.controller)
    (h : checkDirectMergeTokenDefended S d offered = true) :
    TokenPositiveStep S .tau (advanceDirectMergeToken S d) := by
  apply checkedDirectMerge_token_step S d offered hSafe
  rw [← checkDirectMergeTokenDefended_eq_tokenPlan S d offered]
  exact h

/-! ## Source-derived monotone drops -/

/-- Reclassification preserves token linearity when a transition only removes
current claims, keeps `opClaim`, and keeps the origin map. -/
theorem reclassify_preserves_linearity_of_subset
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (controller' : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot))
    (hRemaining : controller'.plan.remaining ⊆
      S.controller.plan.remaining)
    (hOpClaim : controller'.lifecycle.opClaim =
      S.controller.lifecycle.opClaim)
    (hSource : S.LinearValid) :
    (TokenState.mk controller' (S.ledger.reclassify controller')).LinearValid := by
  let T : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token) :=
    TokenState.mk controller' (S.ledger.reclassify controller')
  have hCurrentSubset : forall t, T.currentFiber t ⊆ S.currentFiber t := by
    intro t c hc
    simp only [TokenState.currentFiber, TokenLedger.currentFiber,
      Finset.mem_filter] at hc ⊢
    exact ⟨hRemaining hc.1, by simpa [T, TokenLedger.reclassify] using hc.2⟩
  have hBindingEq : forall t, T.bindingFiber t = S.bindingFiber t := by
    intro t
    ext e
    simp [T, TokenState.bindingFiber, TokenLedger.bindingFiber,
      TokenLedger.reclassify, hOpClaim]
  refine {
    current_covered := ?_
    binding_covered := ?_
    current_linear := ?_
    binding_linear := ?_
    exclusive := ?_
    disposition_exact := ?_ }
  · intro c hc
    obtain ⟨t, ht, ho⟩ := hSource.current_covered c (hRemaining hc)
    exact ⟨t, by simpa [T, TokenLedger.reclassify] using ht,
      by simpa [T, TokenLedger.reclassify] using ho⟩
  · intro e c he
    have heSource : S.controller.lifecycle.opClaim e = some c := by
      have hopEq := congrFun hOpClaim e
      rw [hopEq] at he
      exact he
    obtain ⟨t, ht, ho⟩ := hSource.binding_covered e c heSource
    exact ⟨t, by simpa [T, TokenLedger.reclassify] using ht,
      by simpa [T, TokenLedger.reclassify] using ho⟩
  · intro t ht
    exact (Finset.card_le_card (hCurrentSubset t)).trans
      (hSource.current_linear t
        (by simpa [T, TokenLedger.reclassify] using ht))
  · intro t ht
    rw [hBindingEq t]
    exact hSource.binding_linear t
      (by simpa [T, TokenLedger.reclassify] using ht)
  · intro t ht hBoth
    exact hSource.exclusive t
      (by simpa [T, TokenLedger.reclassify] using ht)
      ⟨hBoth.1.mono (hCurrentSubset t), by
        rw [← hBindingEq t]
        exact hBoth.2⟩
  · intro t ht
    change S.ledger.computedDisposition controller' t =
      (S.ledger.reclassify controller').computedDisposition controller' t
    rfl

theorem restriction_preserves_linearity_source
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (owners : Finset Branch) (keep : Finset Claim)
    (hSource : S.LinearValid) :
    (advanceRestrictionToken S owners keep).LinearValid := by
  apply reclassify_preserves_linearity_of_subset S
  · exact afterRestriction_remaining_subset S.controller.lifecycle
      S.controller.plan owners keep
  · rfl
  · exact hSource

theorem revoke_preserves_linearity_source
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (g : Grant) (hSource : S.LinearValid) :
    (advanceRevokeToken S g).LinearValid := by
  apply reclassify_preserves_linearity_of_subset S
  · simpa [afterRevoke] using
      (afterRestriction_remaining_subset S.controller.lifecycle
        S.controller.plan Finset.univ (revokeKeep S.controller.lifecycle g))
  · rfl
  · exact hSource

/-! ## Source-derived Prepare -/

theorem headGroup_subset_remaining
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)) :
    p.headGroup A ⊆ p.remaining := by
  intro c hc
  unfold PlanData.headGroup at hc
  cases hfirst : p.firstGroup A with
  | none => simp [hfirst] at hc
  | some g =>
      rcases g with ⟨s, b⟩
      have hcOwner : c ∈ p.ownerGroup A s b := by
        simpa [hfirst] using hc
      exact (Finset.mem_filter.mp
        (Finset.mem_filter.mp hcOwner).1).1

theorem advancePrepare_currentFiber_subset
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (assignment : Operation -> Option Claim) (t : Token) :
    (PlanTokenLinearity.advancePrepare S assignment).currentFiber t ⊆
      S.currentFiber t := by
  intro c hc
  simp only [TokenState.currentFiber, TokenLedger.currentFiber,
    Finset.mem_filter] at hc ⊢
  refine ⟨afterPrepareGroup_remaining_subset assignment hc.1, ?_⟩
  simpa [PlanTokenLinearity.advancePrepare, TokenLedger.reclassify] using hc.2

theorem advancePrepare_current_not_head
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (assignment : Operation -> Option Claim) {c : Claim}
    (hc : c ∈ (PlanTokenLinearity.advancePrepare S assignment).controller.plan.remaining) :
    c ∉ S.controller.plan.headGroup S.controller.lifecycle := by
  have hcData : c ∈ S.controller.plan.remaining ∧
      ∃ b, (prepareState S.controller.lifecycle
        (S.controller.plan.headGroup S.controller.lifecycle)
        assignment).auth.status c = .tentative b := by
    simpa [PlanTokenLinearity.advancePrepare,
      _root_.AuthorityContinuity.PlanInvariant.PlanData.advancePrepare,
      PlanData.afterPrepareGroup] using hc
  obtain ⟨b, hb⟩ := hcData.2
  exact (prepareState_tentative_source_not_head assignment hb).2

/-- Every target Prepare binding is either newly assigned in this Prepare or
is an unchanged pre-existing binding. -/
theorem advancePrepare_binding_cases
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (assignment : Operation -> Option Claim) {e : Operation} {c : Claim}
    (hop : (PlanTokenLinearity.advancePrepare S assignment).controller.lifecycle.opClaim e =
      some c) :
    assignment e = some c ∨
      (assignment e = none ∧ S.controller.lifecycle.opClaim e = some c) := by
  change (prepareState S.controller.lifecycle
    (S.controller.plan.headGroup S.controller.lifecycle)
    assignment).opClaim e = some c at hop
  rw [prepareState_opClaim] at hop
  cases ha : assignment e with
  | none =>
      right
      exact ⟨rfl, by simpa [ha] using hop⟩
  | some assigned =>
      left
      have : assigned = c := by simpa [ha] using hop
      simpa [this] using ha

/-- Prepare token preservation is fully source-derived from assignment
membership/freshness/injectivity and source linearity.  The complete target
scan is not a proof premise. -/
theorem prepare_preserves_linearity_source
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (assignment : Operation -> Option Claim)
    (hSource : S.LinearValid)
    (hAssignment : Plan.AssignmentValid S.controller.lifecycle
      (S.controller.plan.headGroup S.controller.lifecycle) assignment) :
    (PlanTokenLinearity.advancePrepare S assignment).LinearValid := by
  let T := PlanTokenLinearity.advancePrepare S assignment
  have hCurrentSubset : forall t, T.currentFiber t ⊆ S.currentFiber t :=
    advancePrepare_currentFiber_subset S assignment
  refine {
    current_covered := ?_
    binding_covered := ?_
    current_linear := ?_
    binding_linear := ?_
    exclusive := ?_
    disposition_exact := ?_ }
  · intro c hc
    obtain ⟨t, ht, ho⟩ := hSource.current_covered c
      (afterPrepareGroup_remaining_subset assignment hc)
    exact ⟨t,
      by simpa [T, PlanTokenLinearity.advancePrepare,
        TokenLedger.reclassify] using ht,
      by simpa [T, PlanTokenLinearity.advancePrepare,
        TokenLedger.reclassify] using ho⟩
  · intro e c he
    rcases advancePrepare_binding_cases S assignment he with
      hNew | ⟨_, hOld⟩
    · have hcHead := hAssignment.assigned_mem e c hNew
      have hcRemaining := headGroup_subset_remaining
        S.controller.lifecycle S.controller.plan hcHead
      obtain ⟨t, ht, ho⟩ := hSource.current_covered c hcRemaining
      exact ⟨t,
        by simpa [T, PlanTokenLinearity.advancePrepare,
          TokenLedger.reclassify] using ht,
        by simpa [T, PlanTokenLinearity.advancePrepare,
          TokenLedger.reclassify] using ho⟩
    · obtain ⟨t, ht, ho⟩ := hSource.binding_covered e c hOld
      exact ⟨t,
        by simpa [T, PlanTokenLinearity.advancePrepare,
          TokenLedger.reclassify] using ht,
        by simpa [T, PlanTokenLinearity.advancePrepare,
          TokenLedger.reclassify] using ho⟩
  · intro t ht
    exact (Finset.card_le_card (hCurrentSubset t)).trans
      (hSource.current_linear t
        (by simpa [T, PlanTokenLinearity.advancePrepare,
          TokenLedger.reclassify] using ht))
  · intro t ht
    apply Finset.card_le_one.mpr
    intro e he e' he'
    have bindingWitness : forall {x : Operation}, x ∈ T.bindingFiber t ->
        ∃ c, T.controller.lifecycle.opClaim x = some c ∧
          T.ledger.origin c = some t := by
      intro x hx
      simp only [TokenState.bindingFiber, TokenLedger.bindingFiber,
        Finset.mem_filter, Finset.mem_univ, true_and] at hx
      cases hop : T.controller.lifecycle.opClaim x with
      | none => simp [hop] at hx
      | some c =>
          refine ⟨c, rfl, ?_⟩
          simpa [hop] using hx
    obtain ⟨c, heClaim, hcOriginTarget⟩ := bindingWitness he
    obtain ⟨c', he'Claim, hc'OriginTarget⟩ := bindingWitness he'
    have hcOrigin : S.ledger.origin c = some t := by
      simpa [T, PlanTokenLinearity.advancePrepare,
        TokenLedger.reclassify] using hcOriginTarget
    have hc'Origin : S.ledger.origin c' = some t := by
      simpa [T, PlanTokenLinearity.advancePrepare,
        TokenLedger.reclassify] using hc'OriginTarget
    have heClaim' :
        (PlanTokenLinearity.advancePrepare S assignment).controller.lifecycle.opClaim e =
          some c := by simpa [T] using heClaim
    have he'Claim' :
        (PlanTokenLinearity.advancePrepare S assignment).controller.lifecycle.opClaim e' =
          some c' := by simpa [T] using he'Claim
    rcases advancePrepare_binding_cases S assignment heClaim' with
      heNew | ⟨_, heOld⟩
    · rcases advancePrepare_binding_cases S assignment he'Claim' with
        he'New | ⟨_, he'Old⟩
      · have hcHead := hAssignment.assigned_mem e c heNew
        have hc'Head := hAssignment.assigned_mem e' c' he'New
        have hcc' := hSource.distinct_current_claims
          (by simpa [T, PlanTokenLinearity.advancePrepare,
            TokenLedger.reclassify] using ht)
          (headGroup_subset_remaining S.controller.lifecycle
            S.controller.plan hcHead)
          (headGroup_subset_remaining S.controller.lifecycle
            S.controller.plan hc'Head)
          hcOrigin hc'Origin
        subst c'
        exact hAssignment.assignment_injective e e' c heNew he'New
      · exfalso
        exact hSource.exclusive t
          (by simpa [T, PlanTokenLinearity.advancePrepare,
            TokenLedger.reclassify] using ht)
          ⟨⟨c, by simp [TokenState.currentFiber, TokenLedger.currentFiber,
              headGroup_subset_remaining S.controller.lifecycle
                S.controller.plan (hAssignment.assigned_mem e c heNew),
              hcOrigin]⟩,
            ⟨e', by simp [TokenState.bindingFiber, TokenLedger.bindingFiber,
              he'Old, hc'Origin]⟩⟩
    · rcases advancePrepare_binding_cases S assignment he'Claim' with
        he'New | ⟨_, he'Old⟩
      · exfalso
        exact hSource.exclusive t
          (by simpa [T, PlanTokenLinearity.advancePrepare,
            TokenLedger.reclassify] using ht)
          ⟨⟨c', by simp [TokenState.currentFiber, TokenLedger.currentFiber,
              headGroup_subset_remaining S.controller.lifecycle
                S.controller.plan (hAssignment.assigned_mem e' c' he'New),
              hc'Origin]⟩,
            ⟨e, by simp [TokenState.bindingFiber, TokenLedger.bindingFiber,
              heOld, hcOrigin]⟩⟩
      · exact hSource.distinct_bindings
          (by simpa [T, PlanTokenLinearity.advancePrepare,
            TokenLedger.reclassify] using ht)
          heOld he'Old hcOrigin hc'Origin
  · intro t ht hBoth
    obtain ⟨c, hcTarget⟩ := hBoth.1
    have hcData : c ∈ T.controller.plan.remaining ∧
        T.ledger.origin c = some t := by
      simpa [TokenState.currentFiber, TokenLedger.currentFiber] using hcTarget
    have hcSourceRemaining : c ∈ S.controller.plan.remaining :=
      afterPrepareGroup_remaining_subset assignment hcData.1
    have hcNotHead : c ∉
        S.controller.plan.headGroup S.controller.lifecycle :=
      advancePrepare_current_not_head S assignment hcData.1
    have hcOrigin : S.ledger.origin c = some t := by
      simpa [T, PlanTokenLinearity.advancePrepare,
        TokenLedger.reclassify] using hcData.2
    obtain ⟨e, heTarget⟩ := hBoth.2
    simp only [TokenState.bindingFiber, TokenLedger.bindingFiber,
      Finset.mem_filter, Finset.mem_univ, true_and] at heTarget
    obtain ⟨bound, hop, hBoundOriginTarget⟩ :=
      Option.bind_eq_some_iff.mp heTarget
    have hBoundOrigin : S.ledger.origin bound = some t := by
      simpa [T, PlanTokenLinearity.advancePrepare,
        TokenLedger.reclassify] using hBoundOriginTarget
    have hop' :
        (PlanTokenLinearity.advancePrepare S assignment).controller.lifecycle.opClaim e =
          some bound := by simpa [T] using hop
    rcases advancePrepare_binding_cases S assignment hop' with
      hNew | ⟨_, hOld⟩
    · have hBoundHead := hAssignment.assigned_mem e bound hNew
      have hEq := hSource.distinct_current_claims
        (by simpa [T, PlanTokenLinearity.advancePrepare,
          TokenLedger.reclassify] using ht)
        hcSourceRemaining
        (headGroup_subset_remaining S.controller.lifecycle
          S.controller.plan hBoundHead)
        hcOrigin hBoundOrigin
      exact hcNotHead (hEq ▸ hBoundHead)
    · exact hSource.exclusive t
        (by simpa [T, PlanTokenLinearity.advancePrepare,
          TokenLedger.reclassify] using ht)
        ⟨⟨c, by simp [TokenState.currentFiber, TokenLedger.currentFiber,
            hcSourceRemaining, hcOrigin]⟩,
          ⟨e, by simp [TokenState.bindingFiber, TokenLedger.bindingFiber,
            hOld, hBoundOrigin]⟩⟩
  · intro t ht
    change S.ledger.computedDisposition
        (PlanTokenLinearity.advancePrepare S assignment).controller t =
      (S.ledger.reclassify
        (PlanTokenLinearity.advancePrepare S assignment).controller).computedDisposition
        (PlanTokenLinearity.advancePrepare S assignment).controller t
    rfl

/-- Existing production Prepare admission retains the full target scan, but
source-derived token preservation uses only its assignment atom. -/
theorem checkedPrepare_preserves_linearity_source
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (offered : Nat) (assignment : Operation -> Option Claim)
    (hSource : S.LinearValid)
    (h : checkPrepareTokenPlan S offered assignment = true) :
    (PlanTokenLinearity.advancePrepare S assignment).LinearValid := by
  have hp := checkPrepareTokenPlan_parts S offered assignment h
  exact prepare_preserves_linearity_source S assignment hSource
    (Plan.checkAssignment_sound hp.2.2.1)

/-! ## Decomposed preservation for the production grammar -/

/-- Re-proves linearity preservation for the existing production relation.
Prepare, Restriction, and Revoke do not use their target scan at all.
Canonical and Merge use the target scan only to recover the one local
non-amplification atom; every other target field is derived from the source.
Thus the retained whole-target scan is auditable defense in depth rather than
an opaque postcondition standing in for transition reasoning. -/
theorem tokenPositiveStep_preserves_linearity_source_decomposed
    {S S' : TokenState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot) (Token := Token)}
    {eta : Label Operation Claim} (h : TokenPositiveStep S eta S')
    (hSource : S.LinearValid) : S'.LinearValid := by
  cases h with
  | checkpoint => exact hSource
  | prepare hPlan _ =>
      cases hPlan with
      | mk _ _ _ _ hAssignment =>
          exact prepare_preserves_linearity_source S _ hSource
            (Plan.checkAssignment_sound hAssignment)
  | @canonical offered tr op hPlan hToken =>
      cases hPlan with
      | mk hWF _ _ _ _ hCanonical _ =>
          have hCore := (checkCanonical_sound S.controller.lifecycle tr op
            hCanonical).transfer.toCoreValid
          have hTarget := TokenState.checkLinear_sound _ hToken
          have hLocal : TransferTokenNonAmplifying S tr :=
            (canonical_nonAmplifying_iff_target_current_linear S tr op).2
              hTarget.current_linear
          exact afterTransfer_preserves_linearity_source S
            (advanceCanonical S tr op).controller tr rfl rfl hWF hCore
            hSource hLocal
  | restriction _ _ => exact restriction_preserves_linearity_source S _ _ hSource
  | revoke _ _ => exact revoke_preserves_linearity_source S _ hSource
  | @simulationMerge offered d project hPlan hToken =>
      cases hPlan with
      | mk hWF _ _ _ _ hAdmission _ =>
          have hStructure := simulationAdmission_structural
            S.controller.lifecycle d project hAdmission
          have hCore := (MergeCheck.checkMergeStructure_sound
            S.controller.lifecycle d hStructure).transfer
          have hTarget := TokenState.checkLinear_sound _ hToken
          have hLocal : TransferTokenNonAmplifying S d.transfer :=
            (simulationMerge_nonAmplifying_iff_target_current_linear S d).2
              hTarget.current_linear
          exact afterTransfer_preserves_linearity_source S
            (advanceSimulationMergeToken S d).controller d.transfer rfl rfl
            hWF hCore hSource hLocal
  | @directMerge offered d hPlan hToken =>
      cases hPlan with
      | mk hWF _ _ hAdmission _ =>
          have hStructure := directAdmission_structural
            S.controller.lifecycle d hAdmission
          have hCore := (MergeCheck.checkMergeStructure_sound
            S.controller.lifecycle d hStructure).transfer
          have hTarget := TokenState.checkLinear_sound _ hToken
          have hLocal : TransferTokenNonAmplifying S d.transfer :=
            (directMerge_nonAmplifying_iff_target_current_linear S d).2
              hTarget.current_linear
          exact afterTransfer_preserves_linearity_source S
            (advanceDirectMergeToken S d).controller d.transfer rfl rfl
            hWF hCore hSource hLocal
  | ticket hTicket => exact ticket_preserves_linearity _ hTicket hSource

theorem tokenPositiveStep_preserves_safe_source_decomposed
    {S S' : TokenState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot) (Token := Token)}
    {eta : Label Operation Claim} (h : TokenPositiveStep S eta S')
    (hSafe : TokenSafe S) : TokenSafe S' :=
  ⟨h.toPositiveStep.preserves_safe hSafe.controllerSafe,
    tokenPositiveStep_preserves_linearity_source_decomposed h
      hSafe.tokenLinear⟩

theorem token_positive_trace_preserves_source_decomposed
    {S S' : TokenState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot) (Token := Token)}
    (hTrace : TokenPositiveTrace S S') (hSafe : TokenSafe S) :
    TokenSafe S' := by
  induction hTrace with
  | refl => exact hSafe
  | tail _ hEdge ih =>
      obtain ⟨eta, hStep⟩ := hEdge
      exact tokenPositiveStep_preserves_safe_source_decomposed hStep ih

/-! ## Existing operation-token stability -/

/-- An actual durable operation binding together with its immutable token. -/
def OperationTokenBound
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (e : Operation) (c : Claim) (t : Token) : Prop :=
  S.controller.lifecycle.opClaim e = some c ∧
    S.ledger.origin c = some t

/-- Every token-positive edge preserves every binding that already existed at
its source, including its origin token.  Prepare may create additional fresh
bindings; it cannot replace an existing one. -/
theorem tokenPositiveStep_preserves_existing_operation_token
    {S S' : TokenState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot) (Token := Token)}
    {eta : Label Operation Claim} (h : TokenPositiveStep S eta S')
    (hSafe : TokenSafe S) {e : Operation} {c : Claim} {t : Token}
    (hBound : OperationTokenBound S e c t) :
    OperationTokenBound S' e c t := by
  refine ⟨step_preserves_existing_binding h.actual_step e c hBound.1, ?_⟩
  cases h with
  | checkpoint => exact hBound.2
  | prepare hPlan hToken =>
      simpa [PlanTokenLinearity.advancePrepare, TokenLedger.reclassify]
        using hBound.2
  | @canonical offered tr op hPlan hToken =>
      cases hPlan with
      | mk hWF hAC hActive hValid hVersion hCanonical hOwner =>
          have hCore := (checkCanonical_sound S.controller.lifecycle tr op
            hCanonical).transfer.toCoreValid
          simpa [advanceCanonical] using
            ((bound_durable_origin_afterTransfer S.controller.lifecycle
              (advanceCanonical S tr op).controller S.ledger tr
              hSafe.controllerSafe.lwf hCore hBound.1).trans hBound.2)
  | restriction hPlan hToken =>
      simpa [advanceRestrictionToken, TokenLedger.reclassify] using hBound.2
  | revoke hPlan hToken =>
      simpa [advanceRevokeToken, TokenLedger.reclassify] using hBound.2
  | @simulationMerge offered d project hPlan hToken =>
      cases hPlan with
      | mk hWF hAC hActive hValid hVersion hAdmission hOwner =>
          have hStructure := simulationAdmission_structural
            S.controller.lifecycle d project hAdmission
          have hCore := (MergeCheck.checkMergeStructure_sound
            S.controller.lifecycle d hStructure).transfer
          simpa [advanceSimulationMergeToken] using
            ((bound_durable_origin_afterTransfer S.controller.lifecycle
              (advanceSimulationMergeToken S d).controller S.ledger d.transfer
              hSafe.controllerSafe.lwf hCore hBound.1).trans hBound.2)
  | @directMerge offered d hPlan hToken =>
      cases hPlan with
      | mk hWF hValid hVersion hAdmission hOwner =>
          have hStructure := directAdmission_structural
            S.controller.lifecycle d hAdmission
          have hCore := (MergeCheck.checkMergeStructure_sound
            S.controller.lifecycle d hStructure).transfer
          simpa [advanceDirectMergeToken] using
            ((bound_durable_origin_afterTransfer S.controller.lifecycle
              (advanceDirectMergeToken S d).controller S.ledger d.transfer
              hSafe.controllerSafe.lwf hCore hBound.1).trans hBound.2)
  | ticket hTicket => exact hBound.2

/-- Target Prepare bindings are partitioned explicitly into fresh assignment
bindings and preserved source bindings. -/
theorem prepare_binding_new_or_preserved
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := Token))
    (assignment : Operation -> Option Claim) {e : Operation} {c : Claim}
    (h : (PlanTokenLinearity.advancePrepare S assignment).controller.lifecycle.opClaim e =
      some c) :
    assignment e = some c ∨
      (assignment e = none ∧ S.controller.lifecycle.opClaim e = some c) :=
  advancePrepare_binding_cases S assignment h

theorem token_positive_trace_preserves_existing_operation_token
    {S S' : TokenState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot) (Token := Token)}
    (hTrace : TokenPositiveTrace S S') (hSafe : TokenSafe S)
    {e : Operation} {c : Claim} {t : Token}
    (hBound : OperationTokenBound S e c t) :
    OperationTokenBound S' e c t := by
  have hBoth : TokenSafe S' ∧ OperationTokenBound S' e c t := by
    induction hTrace with
    | refl => exact ⟨hSafe, hBound⟩
    | tail _ hEdge ih =>
        obtain ⟨eta, hStep⟩ := hEdge
        exact ⟨hStep.preserves_safe ih.1,
          tokenPositiveStep_preserves_existing_operation_token
            hStep ih.1 ih.2⟩
  exact hBoth.2

/-- Honest within-plan-epoch name for the fixed-initial-set theorem.  This is
not a dynamic epoch-installation or minting theorem. -/
theorem within_plan_epoch_initial_tokens_fixed
    {S S' : TokenState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot) (Token := Token)}
    (hTrace : TokenPositiveTrace S S') :
    S.ledger.initial = S'.ledger.initial :=
  token_positive_trace_initial_eq hTrace

theorem within_plan_epoch_existing_operation_token_fixed
    {S S' : TokenState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot) (Token := Token)}
    (hTrace : TokenPositiveTrace S S') (hSafe : TokenSafe S)
    {e : Operation} {c : Claim} {t : Token}
    (hBound : OperationTokenBound S e c t) :
    OperationTokenBound S' e c t :=
  token_positive_trace_preserves_existing_operation_token hTrace hSafe hBound

#print axioms checkTransferTokenNonAmplifying_sound
#print axioms canonical_nonAmplifying_iff_target_current_linear
#print axioms simulationMerge_nonAmplifying_iff_target_current_linear
#print axioms directMerge_nonAmplifying_iff_target_current_linear
#print axioms bound_durable_origin_afterTransfer
#print axioms afterTransfer_preserves_linearity_source
#print axioms checkCanonicalTokenDefended_eq_tokenPlan
#print axioms checkSimulationMergeTokenDefended_eq_tokenPlan
#print axioms checkDirectMergeTokenDefended_eq_tokenPlan
#print axioms checkedCanonicalDefended_token_step
#print axioms checkedSimulationMergeDefended_token_step
#print axioms checkedDirectMergeDefended_token_step
#print axioms prepare_preserves_linearity_source
#print axioms restriction_preserves_linearity_source
#print axioms revoke_preserves_linearity_source
#print axioms tokenPositiveStep_preserves_linearity_source_decomposed
#print axioms token_positive_trace_preserves_source_decomposed
#print axioms tokenPositiveStep_preserves_existing_operation_token
#print axioms prepare_binding_new_or_preserved
#print axioms token_positive_trace_preserves_existing_operation_token
#print axioms within_plan_epoch_initial_tokens_fixed

end AuthorityContinuity.PlanTokenStrengthening
