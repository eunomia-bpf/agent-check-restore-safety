import Mathlib.Data.Finset.Card

/-!
# Operational authority commitments

This module gives a unit-normalized operational semantics for durable authority
commitments.  Safety is derived from rule-local state, not assumed by the
transition relation.

A semantic cell owns epoch-local spent state.  A fresh Prepare consumes one
held authority atom and marks that atom spent at the selected cell and epoch.
Receipt IDs come from a globally namespaced fresh-ID scheme (for example, a
collision-free cell prefix plus a cell-local counter): this assumption prevents
two independent cells from accidentally overwriting one analytic receipt name,
but it does not coordinate their spent states.  Consequently, an
unsafe aggregate that copies one logical atom into two private cells can still
produce two different commitments, as the fixtures demonstrate.

The model stops at durable authorization commitments.  It deliberately does
not claim that an external sink applies an effect exactly once.  `Crash` is an
atomic controller stutter; it does not model a crash inside a partially durable
write protocol.
-/

namespace AuthorityContinuity.RedemptionCommitment

universe uA uC uE uO uD uR

-- Several transport lemmas deliberately retain the common finite interface
-- even when an individual proof needs fewer decidable-equality instances.
set_option linter.unusedSectionVars false

/-! ## Names and state -/

inductive ExternalPhase where
  | prepared
  | settled
  deriving DecidableEq, Repr

namespace ExternalPhase

/-- The only allowed phase movement is stutter or prepared-to-settled. -/
inductive Advances : ExternalPhase → ExternalPhase → Prop where
  | refl (phase) : Advances phase phase
  | settle : Advances .prepared .settled

theorem Advances.trans {p q r : ExternalPhase}
    (hpq : Advances p q) (hqr : Advances q r) : Advances p r := by
  cases hpq with
  | refl _ => exact hqr
  | settle =>
      cases hqr with
      | refl _ => exact .settle

end ExternalPhase

/-- Immutable security-relevant content of one durable authorization receipt.
External phase is stored separately so settlement cannot rewrite this ledger.
-/
@[ext]
structure Binding (Cell : Type uC) (Epoch : Type uE) (Atom : Type uA)
    (Operation : Type uO) (Digest : Type uD) where
  cell : Cell
  epoch : Epoch
  atom : Atom
  operation : Operation
  digest : Digest
  deriving DecidableEq, Repr

/-- Aggregate execution state.  `Cell` values denote shared semantic
linearization points, not caller-chosen labels.  The `spent` map is explicitly
cell- and epoch-local. -/
@[ext]
structure State (Atom : Type uA) (Cell : Type uC) (Epoch : Type uE)
    (Operation : Type uO) (Digest : Type uD) (Receipt : Type uR) where
  issued : Finset Atom
  cellEpoch : Cell → Epoch
  cellOpen : Cell → Bool
  holds : Cell → Atom → Bool
  spent : Cell → Epoch → Atom → Bool
  ledger : Receipt → Option (Binding Cell Epoch Atom Operation Digest)
  idempotency : Cell → Operation → Option Receipt
  externalPhase : Receipt → Option ExternalPhase

namespace State

variable {Atom : Type uA} {Cell : Type uC} {Epoch : Type uE}
variable {Operation : Type uO} {Digest : Type uD} {Receipt : Type uR}

def committedReceipts [Fintype Receipt] [DecidableEq Receipt]
    (S : State Atom Cell Epoch Operation Digest Receipt) : Finset Receipt :=
  Finset.univ.filter fun receipt => (S.ledger receipt).isSome

def receiptAtom?
    (S : State Atom Cell Epoch Operation Digest Receipt) (receipt : Receipt) :
    Option Atom :=
  (S.ledger receipt).map Binding.atom

end State

/-! ## Independent invariants -/

/-- Receipt ledger and external phase have exactly the same domain. -/
def PhaseWF (S : State Atom Cell Epoch Operation Digest Receipt) : Prop :=
  ∀ receipt, (S.ledger receipt).isSome =
    (S.externalPhase receipt).isSome

/-- An issued atom has a unique live/committed disposition.  This predicate is
independent of `Step`.  It also connects durable bindings to cell-local spent
state and connects idempotency keys and external phases to the receipt ledger.
-/
structure Safe [DecidableEq Atom]
    (S : State Atom Cell Epoch Operation Digest Receipt) : Prop where
  heldIssued : ∀ cell atom, S.holds cell atom = true → atom ∈ S.issued
  heldOpen : ∀ cell atom, S.holds cell atom = true → S.cellOpen cell = true
  heldUnspent : ∀ cell atom, S.holds cell atom = true →
    S.spent cell (S.cellEpoch cell) atom = false
  committedIssued : ∀ receipt binding,
    S.ledger receipt = some binding → binding.atom ∈ S.issued
  uniqueHolder : ∀ cell₁ cell₂ atom,
    S.holds cell₁ atom = true → S.holds cell₂ atom = true → cell₁ = cell₂
  heldUncommitted : ∀ cell atom receipt binding,
    S.holds cell atom = true → S.ledger receipt = some binding →
      binding.atom ≠ atom
  uniqueReceiptPerAtom : ∀ receipt₁ receipt₂ binding₁ binding₂,
    S.ledger receipt₁ = some binding₁ →
    S.ledger receipt₂ = some binding₂ →
    binding₁.atom = binding₂.atom → receipt₁ = receipt₂
  ledgerSpent : ∀ receipt binding,
    S.ledger receipt = some binding →
      S.spent binding.cell binding.epoch binding.atom = true
  idempotencySound : ∀ cell operation receipt,
    S.idempotency cell operation = some receipt →
      ∃ binding, S.ledger receipt = some binding ∧
        binding.cell = cell ∧ binding.operation = operation
  ledgerIndexed : ∀ receipt binding,
    S.ledger receipt = some binding →
      S.idempotency binding.cell binding.operation = some receipt
  phaseWF : PhaseWF S

/-! ## Prepare, replay, retry, and settlement -/

/-- Rule-local checks for a new commitment.  The spent check consults only the
selected semantic cell and epoch.  Receipt freshness is a separate global
namespace premise; it does not serialize independent cell redemptions. -/
structure FreshOK
    (S : State Atom Cell Epoch Operation Digest Receipt)
    (cell : Cell) (epoch : Epoch) (atom : Atom)
    (operation : Operation) (receipt : Receipt) : Prop where
  currentEpoch : S.cellEpoch cell = epoch
  openCell : S.cellOpen cell = true
  heldRight : S.holds cell atom = true
  localUnspent : S.spent cell epoch atom = false
  keyUnbound : S.idempotency cell operation = none
  namespacedReceiptFresh : S.ledger receipt = none
  namespacedPhaseFresh : S.externalPhase receipt = none

/-- Atomic fresh Prepare target. -/
def afterFresh [DecidableEq Atom] [DecidableEq Cell] [DecidableEq Epoch]
    [DecidableEq Operation] [DecidableEq Receipt]
    (S : State Atom Cell Epoch Operation Digest Receipt)
    (cell : Cell) (epoch : Epoch) (atom : Atom)
    (operation : Operation) (digest : Digest) (receipt : Receipt) :
    State Atom Cell Epoch Operation Digest Receipt where
  issued := S.issued
  cellEpoch := S.cellEpoch
  cellOpen := S.cellOpen
  holds := Function.update S.holds cell
    (Function.update (S.holds cell) atom false)
  spent := Function.update S.spent cell
    (Function.update (S.spent cell) epoch
      (Function.update (S.spent cell epoch) atom true))
  ledger := Function.update S.ledger receipt (some {
    cell := cell
    epoch := epoch
    atom := atom
    operation := operation
    digest := digest })
  idempotency := Function.update S.idempotency cell
    (Function.update (S.idempotency cell) operation (some receipt))
  externalPhase := Function.update S.externalPhase receipt (some .prepared)

/-- Replay resolves a stable cell/operation key and checks the effect digest
before returning the already durable receipt. -/
structure ReplayOK
    (S : State Atom Cell Epoch Operation Digest Receipt)
    (cell : Cell) (operation : Operation) (digest : Digest)
    (receipt : Receipt) : Prop where
  keyBound : S.idempotency cell operation = some receipt
  bindingMatches : ∃ epoch atom,
    S.ledger receipt = some {
      cell := cell
      epoch := epoch
      atom := atom
      operation := operation
      digest := digest }

/-- Retry has the same stable-key and digest resolution obligation as replay;
it cannot name a guessed receipt. -/
abbrev RetryOK := @ReplayOK

structure SettleOK
    (S : State Atom Cell Epoch Operation Digest Receipt)
    (receipt : Receipt)
    (binding : Binding Cell Epoch Atom Operation Digest) : Prop where
  found : S.ledger receipt = some binding
  prepared : S.externalPhase receipt = some .prepared

def afterSettle [DecidableEq Receipt]
    (S : State Atom Cell Epoch Operation Digest Receipt)
    (receipt : Receipt) :
    State Atom Cell Epoch Operation Digest Receipt where
  issued := S.issued
  cellEpoch := S.cellEpoch
  cellOpen := S.cellOpen
  holds := S.holds
  spent := S.spent
  ledger := S.ledger
  idempotency := S.idempotency
  externalPhase := Function.update S.externalPhase receipt (some .settled)

/-- Labels retain the request identity used by replay and retry. -/
inductive Event (Cell : Type uC) (Operation : Type uO)
    (Digest : Type uD) (Receipt : Type uR) where
  | fresh (cell : Cell) (operation : Operation) (digest : Digest)
      (receipt : Receipt)
  | replay (cell : Cell) (operation : Operation) (digest : Digest)
      (receipt : Receipt)
  | retry (cell : Cell) (operation : Operation) (digest : Digest)
      (receipt : Receipt)
  | crash
  | settle (receipt : Receipt)
  deriving DecidableEq, Repr

namespace Event

/-- Number of newly minted receipts represented by one retained label. -/
def freshUnits : Event Cell Operation Digest Receipt → Nat
  | .fresh _ _ _ _ => 1
  | _ => 0

end Event

/-- Closed operational rules.  No constructor accepts target `Safe` or target
`PhaseWF`.  Crash is an atomic controller stutter only. -/
inductive Step [DecidableEq Atom] [DecidableEq Cell] [DecidableEq Epoch]
    [DecidableEq Operation] [DecidableEq Receipt] :
    State Atom Cell Epoch Operation Digest Receipt →
      Event Cell Operation Digest Receipt →
      State Atom Cell Epoch Operation Digest Receipt → Prop where
  | fresh {S cell epoch atom operation digest receipt}
      (ok : FreshOK S cell epoch atom operation receipt) :
      Step S (.fresh cell operation digest receipt)
        (afterFresh S cell epoch atom operation digest receipt)
  | replay {S cell operation digest receipt}
      (ok : ReplayOK S cell operation digest receipt) :
      Step S (.replay cell operation digest receipt) S
  | retry {S cell operation digest receipt}
      (ok : RetryOK S cell operation digest receipt) :
      Step S (.retry cell operation digest receipt) S
  | crash {S} : Step S .crash S
  | settle {S receipt binding}
      (ok : SettleOK S receipt binding) :
      Step S (.settle receipt) (afterSettle S receipt)

/-! ## Phase and ledger transport -/

section Transport

variable [DecidableEq Atom] [DecidableEq Cell] [DecidableEq Epoch]
variable [DecidableEq Operation] [DecidableEq Receipt]

theorem fresh_preserves_phaseWF
    {S : State Atom Cell Epoch Operation Digest Receipt}
    {cell : Cell} {epoch : Epoch} {atom : Atom}
    {operation : Operation} {digest : Digest} {receipt : Receipt}
    (hWF : PhaseWF S) :
    PhaseWF (afterFresh S cell epoch atom operation digest receipt) := by
  intro otherReceipt
  by_cases hr : otherReceipt = receipt
  · subst otherReceipt
    simp [afterFresh]
  · simpa [afterFresh, hr] using hWF otherReceipt

theorem settle_preserves_phaseWF
    {S : State Atom Cell Epoch Operation Digest Receipt}
    {receipt : Receipt} {binding : Binding Cell Epoch Atom Operation Digest}
    (hWF : PhaseWF S) (ok : SettleOK S receipt binding) :
    PhaseWF (afterSettle S receipt) := by
  intro otherReceipt
  by_cases hr : otherReceipt = receipt
  · subst otherReceipt
    simp [afterSettle, ok.found]
  · simpa [afterSettle, hr] using hWF otherReceipt

theorem step_preserves_phaseWF
    {S S' : State Atom Cell Epoch Operation Digest Receipt}
    {event : Event Cell Operation Digest Receipt}
    (step : Step S event S') (hWF : PhaseWF S) : PhaseWF S' := by
  cases step with
  | fresh _ => exact fresh_preserves_phaseWF hWF
  | replay _ => exact hWF
  | retry _ => exact hWF
  | crash => exact hWF
  | settle ok => exact settle_preserves_phaseWF hWF ok

/-- Every previously durable receipt retains exactly the same immutable
binding. -/
def LedgerMonotone
    (S S' : State Atom Cell Epoch Operation Digest Receipt) : Prop :=
  ∀ receipt binding, S.ledger receipt = some binding →
    S'.ledger receipt = some binding

theorem LedgerMonotone.refl
    (S : State Atom Cell Epoch Operation Digest Receipt) :
    LedgerMonotone S S := by
  intro receipt binding h
  exact h

theorem LedgerMonotone.trans
    {S₁ S₂ S₃ : State Atom Cell Epoch Operation Digest Receipt}
    (h₁₂ : LedgerMonotone S₁ S₂)
    (h₂₃ : LedgerMonotone S₂ S₃) : LedgerMonotone S₁ S₃ := by
  intro receipt binding h
  exact h₂₃ receipt binding (h₁₂ receipt binding h)

theorem step_ledger_mono
    {S S' : State Atom Cell Epoch Operation Digest Receipt}
    {event : Event Cell Operation Digest Receipt}
    (step : Step S event S') : LedgerMonotone S S' := by
  cases step with
  | @fresh cell epoch atom operation digest receipt ok =>
      intro oldReceipt oldBinding hOld
      by_cases hr : oldReceipt = receipt
      · subst oldReceipt
        rw [ok.namespacedReceiptFresh] at hOld
        simp at hOld
      · simpa [afterFresh, hr] using hOld
  | replay _ => exact LedgerMonotone.refl _
  | retry _ => exact LedgerMonotone.refl _
  | crash => exact LedgerMonotone.refl _
  | settle _ => exact LedgerMonotone.refl _

/-- Phase monotonicity is separate from phase-domain well-formedness. -/
def PhaseMonotone
    (S S' : State Atom Cell Epoch Operation Digest Receipt) : Prop :=
  ∀ receipt phase, S.externalPhase receipt = some phase →
    ∃ phase', S'.externalPhase receipt = some phase' ∧
      ExternalPhase.Advances phase phase'

theorem PhaseMonotone.refl
    (S : State Atom Cell Epoch Operation Digest Receipt) :
    PhaseMonotone S S := by
  intro receipt phase h
  exact ⟨phase, h, .refl phase⟩

theorem PhaseMonotone.trans
    {S₁ S₂ S₃ : State Atom Cell Epoch Operation Digest Receipt}
    (h₁₂ : PhaseMonotone S₁ S₂) (h₂₃ : PhaseMonotone S₂ S₃) :
    PhaseMonotone S₁ S₃ := by
  intro receipt phase h
  obtain ⟨phase₂, h₂, ha₂⟩ := h₁₂ receipt phase h
  obtain ⟨phase₃, h₃, ha₃⟩ := h₂₃ receipt phase₂ h₂
  exact ⟨phase₃, h₃, ha₂.trans ha₃⟩

theorem step_phase_mono
    {S S' : State Atom Cell Epoch Operation Digest Receipt}
    {event : Event Cell Operation Digest Receipt}
    (step : Step S event S') : PhaseMonotone S S' := by
  cases step with
  | @fresh cell epoch atom operation digest receipt ok =>
      intro oldReceipt phase hOld
      by_cases hr : oldReceipt = receipt
      · subst oldReceipt
        rw [ok.namespacedPhaseFresh] at hOld
        simp at hOld
      · exact ⟨phase, by simpa [afterFresh, hr] using hOld, .refl phase⟩
  | replay _ => exact PhaseMonotone.refl _
  | retry _ => exact PhaseMonotone.refl _
  | crash => exact PhaseMonotone.refl _
  | @settle receipt binding ok =>
      intro oldReceipt phase hOld
      by_cases hr : oldReceipt = receipt
      · subst oldReceipt
        have hp : phase = .prepared :=
          Option.some.inj (hOld.symm.trans ok.prepared)
        subst phase
        exact ⟨.settled, by simp [afterSettle], .settle⟩
      · exact ⟨phase, by simpa [afterSettle, hr] using hOld, .refl phase⟩

theorem step_issued_eq
    {S S' : State Atom Cell Epoch Operation Digest Receipt}
    {event : Event Cell Operation Digest Receipt}
    (step : Step S event S') : S'.issued = S.issued := by
  cases step <;> rfl

end Transport

/-! ## Safety preservation -/

section Preservation

variable [DecidableEq Atom] [DecidableEq Cell] [DecidableEq Epoch]
variable [DecidableEq Operation] [DecidableEq Receipt]

theorem fresh_preserves_safe
    {S : State Atom Cell Epoch Operation Digest Receipt}
    {cell : Cell} {epoch : Epoch} {atom : Atom}
    {operation : Operation} {digest : Digest} {receipt : Receipt}
    (hSafe : Safe S) (ok : FreshOK S cell epoch atom operation receipt) :
    Safe (afterFresh S cell epoch atom operation digest receipt) := by
  let newBinding : Binding Cell Epoch Atom Operation Digest := {
    cell := cell
    epoch := epoch
    atom := atom
    operation := operation
    digest := digest }
  have hNoOldAtom : ∀ oldReceipt oldBinding,
      S.ledger oldReceipt = some oldBinding → oldBinding.atom ≠ atom := by
    intro oldReceipt oldBinding hOld
    exact hSafe.heldUncommitted cell atom oldReceipt oldBinding
      ok.heldRight hOld
  have oldHeldOfNew : ∀ otherCell otherAtom,
      (afterFresh S cell epoch atom operation digest receipt).holds
          otherCell otherAtom = true →
        S.holds otherCell otherAtom = true := by
    intro otherCell otherAtom hHeld
    by_cases hc : otherCell = cell
    · subst otherCell
      by_cases ha : otherAtom = atom
      · subst otherAtom
        simp [afterFresh] at hHeld
      · simpa [afterFresh, ha] using hHeld
    · simpa [afterFresh, hc] using hHeld
  have spentTrueMono : ∀ otherCell otherEpoch otherAtom,
      S.spent otherCell otherEpoch otherAtom = true →
      (afterFresh S cell epoch atom operation digest receipt).spent
        otherCell otherEpoch otherAtom = true := by
    intro otherCell otherEpoch otherAtom hSpent
    by_cases hc : otherCell = cell
    · subst otherCell
      by_cases he : otherEpoch = epoch
      · subst otherEpoch
        by_cases ha : otherAtom = atom
        · subst otherAtom
          simp [afterFresh]
        · simpa [afterFresh, ha] using hSpent
      · simpa [afterFresh, he] using hSpent
    · simpa [afterFresh, hc] using hSpent
  refine {
    heldIssued := ?_
    heldOpen := ?_
    heldUnspent := ?_
    committedIssued := ?_
    uniqueHolder := ?_
    heldUncommitted := ?_
    uniqueReceiptPerAtom := ?_
    ledgerSpent := ?_
    idempotencySound := ?_
    ledgerIndexed := ?_
    phaseWF := fresh_preserves_phaseWF hSafe.phaseWF }
  · intro otherCell otherAtom hHeld
    exact hSafe.heldIssued otherCell otherAtom
      (oldHeldOfNew otherCell otherAtom hHeld)
  · intro otherCell otherAtom hHeld
    exact hSafe.heldOpen otherCell otherAtom
      (oldHeldOfNew otherCell otherAtom hHeld)
  · intro otherCell otherAtom hHeld
    have hOldHeld := oldHeldOfNew otherCell otherAtom hHeld
    have hOldUnspent := hSafe.heldUnspent otherCell otherAtom hOldHeld
    by_cases hc : otherCell = cell
    · subst otherCell
      by_cases ha : otherAtom = atom
      · subst otherAtom
        simp [afterFresh] at hHeld
      · simpa [afterFresh, ok.currentEpoch, ha] using hOldUnspent
    · simpa [afterFresh, hc] using hOldUnspent
  · intro otherReceipt binding hLedger
    by_cases hr : otherReceipt = receipt
    · subst otherReceipt
      have hb : newBinding = binding := by
        simpa [afterFresh, newBinding] using hLedger
      subst binding
      exact hSafe.heldIssued cell atom ok.heldRight
    · exact hSafe.committedIssued otherReceipt binding
        (by simpa [afterFresh, hr] using hLedger)
  · intro cell₁ cell₂ heldAtom h₁ h₂
    exact hSafe.uniqueHolder cell₁ cell₂ heldAtom
      (oldHeldOfNew cell₁ heldAtom h₁)
      (oldHeldOfNew cell₂ heldAtom h₂)
  · intro heldCell heldAtom otherReceipt binding hHeld hLedger
    have hOldHeld := oldHeldOfNew heldCell heldAtom hHeld
    by_cases hr : otherReceipt = receipt
    · subst otherReceipt
      have hb : newBinding = binding := by
        simpa [afterFresh, newBinding] using hLedger
      subst binding
      intro hAtom
      have ha : heldAtom = atom := by simpa [newBinding] using hAtom.symm
      rw [ha] at hOldHeld hHeld
      have hc := hSafe.uniqueHolder heldCell cell atom hOldHeld ok.heldRight
      subst heldCell
      simp [afterFresh] at hHeld
    · exact hSafe.heldUncommitted heldCell heldAtom otherReceipt binding
        hOldHeld (by simpa [afterFresh, hr] using hLedger)
  · intro receipt₁ receipt₂ binding₁ binding₂ h₁ h₂ hAtom
    by_cases h1r : receipt₁ = receipt
    · subst receipt₁
      have hb₁ : newBinding = binding₁ := by
        simpa [afterFresh, newBinding] using h₁
      subst binding₁
      by_cases h2r : receipt₂ = receipt
      · exact h2r.symm
      · have hOld₂ : S.ledger receipt₂ = some binding₂ := by
          simpa [afterFresh, h2r] using h₂
        exact False.elim ((hNoOldAtom receipt₂ binding₂ hOld₂) hAtom.symm)
    · by_cases h2r : receipt₂ = receipt
      · subst receipt₂
        have hb₂ : newBinding = binding₂ := by
          simpa [afterFresh, newBinding] using h₂
        subst binding₂
        have hOld₁ : S.ledger receipt₁ = some binding₁ := by
          simpa [afterFresh, h1r] using h₁
        exact False.elim ((hNoOldAtom receipt₁ binding₁ hOld₁) hAtom)
      · exact hSafe.uniqueReceiptPerAtom receipt₁ receipt₂ binding₁ binding₂
          (by simpa [afterFresh, h1r] using h₁)
          (by simpa [afterFresh, h2r] using h₂) hAtom
  · intro otherReceipt binding hLedger
    by_cases hr : otherReceipt = receipt
    · subst otherReceipt
      have hb : newBinding = binding := by
        simpa [afterFresh, newBinding] using hLedger
      subst binding
      simp [afterFresh, newBinding]
    · have hOld : S.ledger otherReceipt = some binding := by
        simpa [afterFresh, hr] using hLedger
      exact spentTrueMono binding.cell binding.epoch binding.atom
        (hSafe.ledgerSpent otherReceipt binding hOld)
  · intro otherCell otherOperation otherReceipt hIndex
    by_cases hc : otherCell = cell
    · subst otherCell
      by_cases ho : otherOperation = operation
      · subst otherOperation
        have hr : otherReceipt = receipt :=
          (by simpa [afterFresh] using hIndex : receipt = otherReceipt).symm
        subst otherReceipt
        exact ⟨newBinding, by simp [afterFresh, newBinding], rfl, rfl⟩
      · have hOld : S.idempotency cell otherOperation = some otherReceipt := by
          simpa [afterFresh, ho] using hIndex
        obtain ⟨binding, hLedger, hCell, hOperation⟩ :=
          hSafe.idempotencySound cell otherOperation otherReceipt hOld
        have hne : otherReceipt ≠ receipt := by
          intro hr
          subst otherReceipt
          rw [ok.namespacedReceiptFresh] at hLedger
          simp at hLedger
        exact ⟨binding, by simpa [afterFresh, hne] using hLedger,
          hCell, hOperation⟩
    · have hOld : S.idempotency otherCell otherOperation = some otherReceipt := by
        simpa [afterFresh, hc] using hIndex
      obtain ⟨binding, hLedger, hCell, hOperation⟩ :=
        hSafe.idempotencySound otherCell otherOperation otherReceipt hOld
      have hne : otherReceipt ≠ receipt := by
        intro hr
        subst otherReceipt
        rw [ok.namespacedReceiptFresh] at hLedger
        simp at hLedger
      exact ⟨binding, by simpa [afterFresh, hne] using hLedger,
        hCell, hOperation⟩
  · intro otherReceipt binding hLedger
    by_cases hr : otherReceipt = receipt
    · subst otherReceipt
      have hb : newBinding = binding := by
        simpa [afterFresh, newBinding] using hLedger
      subst binding
      simp [afterFresh, newBinding]
    · have hOld : S.ledger otherReceipt = some binding := by
        simpa [afterFresh, hr] using hLedger
      have hIndex := hSafe.ledgerIndexed otherReceipt binding hOld
      by_cases hc : binding.cell = cell
      · subst cell
        by_cases ho : binding.operation = operation
        · subst operation
          rw [ok.keyUnbound] at hIndex
          simp at hIndex
        · simpa [afterFresh, ho] using hIndex
      · simpa [afterFresh, hc] using hIndex

theorem settle_preserves_safe
    {S : State Atom Cell Epoch Operation Digest Receipt}
    {receipt : Receipt} {binding : Binding Cell Epoch Atom Operation Digest}
    (hSafe : Safe S) (ok : SettleOK S receipt binding) :
    Safe (afterSettle S receipt) := by
  exact {
    heldIssued := by simpa [afterSettle] using hSafe.heldIssued
    heldOpen := by simpa [afterSettle] using hSafe.heldOpen
    heldUnspent := by simpa [afterSettle] using hSafe.heldUnspent
    committedIssued := by simpa [afterSettle] using hSafe.committedIssued
    uniqueHolder := by simpa [afterSettle] using hSafe.uniqueHolder
    heldUncommitted := by simpa [afterSettle] using hSafe.heldUncommitted
    uniqueReceiptPerAtom := by
      simpa [afterSettle] using hSafe.uniqueReceiptPerAtom
    ledgerSpent := by simpa [afterSettle] using hSafe.ledgerSpent
    idempotencySound := by simpa [afterSettle] using hSafe.idempotencySound
    ledgerIndexed := by simpa [afterSettle] using hSafe.ledgerIndexed
    phaseWF := settle_preserves_phaseWF hSafe.phaseWF ok }

theorem step_preserves_safe
    {S S' : State Atom Cell Epoch Operation Digest Receipt}
    {event : Event Cell Operation Digest Receipt}
    (step : Step S event S') (hSafe : Safe S) : Safe S' := by
  cases step with
  | fresh ok => exact fresh_preserves_safe hSafe ok
  | replay _ => exact hSafe
  | retry _ => exact hSafe
  | crash => exact hSafe
  | settle ok => exact settle_preserves_safe hSafe ok

def ClosedStep
    (S S' : State Atom Cell Epoch Operation Digest Receipt) : Prop :=
  ∃ event, Step S event S'

theorem rtc_preserves_safe
    {S S' : State Atom Cell Epoch Operation Digest Receipt}
    (trace : Relation.ReflTransGen ClosedStep S S') (hSafe : Safe S) :
    Safe S' := by
  induction trace with
  | refl => exact hSafe
  | tail _ hStep ih =>
      obtain ⟨event, hStep⟩ := hStep
      exact step_preserves_safe hStep ih

theorem rtc_preserves_phaseWF
    {S S' : State Atom Cell Epoch Operation Digest Receipt}
    (trace : Relation.ReflTransGen ClosedStep S S') (hWF : PhaseWF S) :
    PhaseWF S' := by
  induction trace with
  | refl => exact hWF
  | tail _ hStep ih =>
      obtain ⟨event, hStep⟩ := hStep
      exact step_preserves_phaseWF hStep ih

theorem rtc_ledger_mono
    {S S' : State Atom Cell Epoch Operation Digest Receipt}
    (trace : Relation.ReflTransGen ClosedStep S S') : LedgerMonotone S S' := by
  induction trace with
  | refl => exact LedgerMonotone.refl _
  | tail _ hStep ih =>
      obtain ⟨event, hStep⟩ := hStep
      exact ih.trans (step_ledger_mono hStep)

theorem rtc_phase_mono
    {S S' : State Atom Cell Epoch Operation Digest Receipt}
    (trace : Relation.ReflTransGen ClosedStep S S') : PhaseMonotone S S' := by
  induction trace with
  | refl => exact PhaseMonotone.refl _
  | tail _ hStep ih =>
      obtain ⟨event, hStep⟩ := hStep
      exact ih.trans (step_phase_mono hStep)

theorem rtc_issued_eq
    {S S' : State Atom Cell Epoch Operation Digest Receipt}
    (trace : Relation.ReflTransGen ClosedStep S S') :
    S'.issued = S.issued := by
  induction trace with
  | refl => rfl
  | tail _ hStep ih =>
      obtain ⟨event, hStep⟩ := hStep
      exact (step_issued_eq hStep).trans ih

end Preservation

/-! ## Label-retaining finite traces -/

inductive Trace [DecidableEq Atom] [DecidableEq Cell] [DecidableEq Epoch]
    [DecidableEq Operation] [DecidableEq Receipt] :
    State Atom Cell Epoch Operation Digest Receipt →
      List (Event Cell Operation Digest Receipt) →
      State Atom Cell Epoch Operation Digest Receipt → Prop where
  | nil (S) : Trace S [] S
  | cons {S M T event events} :
      Step S event M → Trace M events T → Trace S (event :: events) T

namespace Trace

section

variable [DecidableEq Atom] [DecidableEq Cell] [DecidableEq Epoch]
variable [DecidableEq Operation] [DecidableEq Receipt]

theorem preserves_safe
    {S T : State Atom Cell Epoch Operation Digest Receipt}
    {events : List (Event Cell Operation Digest Receipt)}
    (trace : Trace S events T) (hSafe : Safe S) : Safe T := by
  induction trace with
  | nil => exact hSafe
  | cons step _ ih => exact ih (step_preserves_safe step hSafe)

theorem preserves_phaseWF
    {S T : State Atom Cell Epoch Operation Digest Receipt}
    {events : List (Event Cell Operation Digest Receipt)}
    (trace : Trace S events T) (hWF : PhaseWF S) : PhaseWF T := by
  induction trace with
  | nil => exact hWF
  | cons step _ ih => exact ih (step_preserves_phaseWF step hWF)

end

end Trace

/-! ## Commitment counting -/

section Counting

variable [Fintype Receipt] [DecidableEq Receipt]
variable [DecidableEq Atom] [DecidableEq Cell] [DecidableEq Epoch]
variable [DecidableEq Operation]

theorem committed_card_le_issued_card
    (S : State Atom Cell Epoch Operation Digest Receipt) (hSafe : Safe S) :
    S.committedReceipts.card ≤ S.issued.card := by
  have hBound : S.committedReceipts.card ≤
      (S.issued.image some).card := by
    apply Finset.card_le_card_of_injOn S.receiptAtom?
    · intro receipt hReceipt
      simp [State.committedReceipts] at hReceipt
      cases hLedger : S.ledger receipt with
      | none => simp [hLedger] at hReceipt
      | some binding =>
          simpa [State.receiptAtom?, hLedger] using
            hSafe.committedIssued receipt binding hLedger
    · intro receipt₁ h₁ receipt₂ h₂ hEq
      simp [State.committedReceipts] at h₁ h₂
      cases hLedger₁ : S.ledger receipt₁ with
      | none => simp [hLedger₁] at h₁
      | some binding₁ =>
          cases hLedger₂ : S.ledger receipt₂ with
          | none => simp [hLedger₂] at h₂
          | some binding₂ =>
              simp only [State.receiptAtom?, hLedger₁, hLedger₂,
                Option.map_some, Option.some.injEq] at hEq
              exact hSafe.uniqueReceiptPerAtom receipt₁ receipt₂
                binding₁ binding₂ hLedger₁ hLedger₂ hEq
  rw [Finset.card_image_of_injective S.issued (Option.some_injective Atom)] at hBound
  exact hBound

theorem committedReceipts_afterFresh
    (S : State Atom Cell Epoch Operation Digest Receipt)
    (cell : Cell) (epoch : Epoch) (atom : Atom)
    (operation : Operation) (digest : Digest) (receipt : Receipt) :
    (afterFresh S cell epoch atom operation digest receipt).committedReceipts =
      insert receipt S.committedReceipts := by
  ext otherReceipt
  by_cases hr : otherReceipt = receipt
  · subst otherReceipt
    simp [State.committedReceipts, afterFresh]
  · simp [State.committedReceipts, afterFresh, hr]

theorem fresh_receipt_not_mem
    (S : State Atom Cell Epoch Operation Digest Receipt)
    {cell : Cell} {epoch : Epoch} {atom : Atom}
    {operation : Operation} {receipt : Receipt}
    (ok : FreshOK S cell epoch atom operation receipt) :
    receipt ∉ S.committedReceipts := by
  simp [State.committedReceipts, ok.namespacedReceiptFresh]

theorem step_committed_card
    {S S' : State Atom Cell Epoch Operation Digest Receipt}
    {event : Event Cell Operation Digest Receipt}
    (step : Step S event S') :
    S'.committedReceipts.card =
      S.committedReceipts.card + event.freshUnits := by
  cases step with
  | @fresh cell epoch atom operation digest receipt ok =>
      rw [committedReceipts_afterFresh _ _ _ _ _ _ _,
        Finset.card_insert_of_notMem (fresh_receipt_not_mem _ ok)]
      simp [Event.freshUnits, Nat.add_comm]
  | replay _ => simp [Event.freshUnits]
  | retry _ => simp [Event.freshUnits]
  | crash => simp [Event.freshUnits]
  | settle _ => simp [Event.freshUnits, State.committedReceipts, afterSettle]

def freshCount (events : List (Event Cell Operation Digest Receipt)) : Nat :=
  (events.map Event.freshUnits).sum

theorem Trace.committed_card_growth
    {S T : State Atom Cell Epoch Operation Digest Receipt}
    {events : List (Event Cell Operation Digest Receipt)}
    (trace : Trace S events T) :
    T.committedReceipts.card = S.committedReceipts.card + freshCount events := by
  induction trace with
  | nil => simp [freshCount]
  | cons step _ ih =>
      rw [ih, step_committed_card step]
      simp [freshCount, Nat.add_assoc]

end Counting

/-! ## Digest conflict -/

theorem replay_digest_unique
    {S : State Atom Cell Epoch Operation Digest Receipt}
    {cell : Cell} {operation : Operation} {receipt : Receipt}
    {digest₁ digest₂ : Digest}
    (h₁ : ReplayOK S cell operation digest₁ receipt)
    (h₂ : ReplayOK S cell operation digest₂ receipt) : digest₁ = digest₂ := by
  obtain ⟨epoch₁, atom₁, hb₁⟩ := h₁.bindingMatches
  obtain ⟨epoch₂, atom₂, hb₂⟩ := h₂.bindingMatches
  have hBinding := Option.some.inj (hb₁.symm.trans hb₂)
  exact congrArg Binding.digest hBinding

theorem conflicting_digest_has_no_replay
    {S : State Atom Cell Epoch Operation Digest Receipt}
    {cell : Cell} {operation : Operation} {receipt : Receipt}
    {digest₁ digest₂ : Digest} (hne : digest₁ ≠ digest₂)
    (h : ReplayOK S cell operation digest₁ receipt) :
    ¬ ReplayOK S cell operation digest₂ receipt := by
  intro h₂
  exact hne (replay_digest_unique h h₂)

theorem conflicting_digest_has_no_retry
    {S : State Atom Cell Epoch Operation Digest Receipt}
    {cell : Cell} {operation : Operation} {receipt : Receipt}
    {digest₁ digest₂ : Digest} (hne : digest₁ ≠ digest₂)
    (h : RetryOK S cell operation digest₁ receipt) :
    ¬ RetryOK S cell operation digest₂ receipt :=
  conflicting_digest_has_no_replay hne h

/-! ## Executable fixtures -/

namespace Fixtures

abbrev Atom := Unit
abbrev Cell := Bool
abbrev Epoch := Unit
abbrev Operation := Bool
abbrev Digest := Bool
abbrev Receipt := Bool
abbrev TestState := State Atom Cell Epoch Operation Digest Receipt

def capacityOne : TestState where
  issued := {()}
  cellEpoch := fun _ => ()
  cellOpen := fun cell => !cell
  holds := fun cell _ => !cell
  spent := fun _ _ _ => false
  ledger := fun _ => none
  idempotency := fun _ _ => none
  externalPhase := fun _ => none

def firstOK : FreshOK capacityOne false () () false false := by
  exact ⟨rfl, rfl, rfl, rfl, rfl, rfl, rfl⟩

def afterFirst : TestState :=
  afterFresh capacityOne false () () false false false

def capacityOneSafe : Safe capacityOne := by
  refine {
    heldIssued := ?_
    heldOpen := ?_
    heldUnspent := ?_
    committedIssued := ?_
    uniqueHolder := ?_
    heldUncommitted := ?_
    uniqueReceiptPerAtom := ?_
    ledgerSpent := ?_
    idempotencySound := ?_
    ledgerIndexed := ?_
    phaseWF := ?_ } <;>
    simp [capacityOne, PhaseWF]

theorem after_first_safe : Safe afterFirst :=
  fresh_preserves_safe capacityOneSafe firstOK

theorem same_cell_capacity_one_blocks_second_fresh :
    ¬ FreshOK afterFirst false () () true true := by
  intro ok
  simpa [afterFirst, afterFresh] using ok.heldRight

theorem first_prepare_one_commitment :
    afterFirst.committedReceipts = {false} := by
  decide

def firstReplay : ReplayOK afterFirst false false false false := by
  refine ⟨?_, ⟨(), (), ?_⟩⟩ <;>
    simp [afterFirst, afterFresh]

def firstRetry : RetryOK afterFirst false false false false := firstReplay

def retryEvent : Event Cell Operation Digest Receipt :=
  .retry false false false false

/-- Three actual retry transitions, not merely a list of response IDs. -/
theorem three_retries_trace :
    Trace afterFirst [retryEvent, retryEvent, retryEvent] afterFirst := by
  exact .cons (.retry firstRetry) (.cons (.retry firstRetry)
    (.cons (.retry firstRetry) (.nil afterFirst)))

theorem three_retry_trace_one_commitment :
    afterFirst.committedReceipts.card =
        afterFirst.committedReceipts.card +
          freshCount [retryEvent, retryEvent, retryEvent] ∧
      freshCount [retryEvent, retryEvent, retryEvent] = 0 ∧
      afterFirst.committedReceipts.card = 1 := by
  exact ⟨Trace.committed_card_growth three_retries_trace,
    by decide, by decide⟩

/-- One atom copied into two private semantic cells.  Each has independent
epoch-local spent state, so the aggregate is explicitly unsafe. -/
def duplicatedAtom : TestState where
  issued := {()}
  cellEpoch := fun _ => ()
  cellOpen := fun _ => true
  holds := fun _ _ => true
  spent := fun _ _ _ => false
  ledger := fun _ => none
  idempotency := fun _ _ => none
  externalPhase := fun _ => none

theorem duplicated_atom_is_unsafe : ¬ Safe duplicatedAtom := by
  intro h
  have hc := h.uniqueHolder false true () rfl rfl
  cases hc

def cloneFirstOK : FreshOK duplicatedAtom false () () false false := by
  exact ⟨rfl, rfl, rfl, rfl, rfl, rfl, rfl⟩

def afterCloneFirst : TestState :=
  afterFresh duplicatedAtom false () () false false false

def cloneSecondOK : FreshOK afterCloneFirst true () () false true := by
  refine ⟨rfl, rfl, ?_, ?_, ?_, ?_, ?_⟩ <;>
    simp [afterCloneFirst, afterFresh, duplicatedAtom]

def afterCloneSecond : TestState :=
  afterFresh afterCloneFirst true () () false false true

theorem cloned_private_cells_two_commitments :
    Step duplicatedAtom (.fresh false false false false) afterCloneFirst ∧
      Step afterCloneFirst (.fresh true false false true) afterCloneSecond ∧
      afterCloneSecond.committedReceipts = {false, true} := by
  exact ⟨.fresh cloneFirstOK, .fresh cloneSecondOK, by decide⟩

/-- The first receipt remains globally visible while an unsafe local restore
reintroduces the snapshot right in a fresh private cell. -/
def rollbackRestored : TestState where
  issued := afterFirst.issued
  cellEpoch := fun _ => ()
  cellOpen := fun _ => true
  holds := fun cell _ => cell
  spent := fun cell _ _ => !cell
  ledger := afterFirst.ledger
  idempotency := fun cell operation =>
    if cell = false ∧ operation = false then some false else none
  externalPhase := afterFirst.externalPhase

theorem rollback_restored_is_unsafe : ¬ Safe rollbackRestored := by
  intro h
  have hHeld : rollbackRestored.holds true () = true := by rfl
  have hLedger : rollbackRestored.ledger false = some {
      cell := false
      epoch := ()
      atom := ()
      operation := false
      digest := false } := by
    simp [rollbackRestored, afterFirst, afterFresh]
  exact h.heldUncommitted true () false _ hHeld hLedger rfl

def restoredFreshOK : FreshOK rollbackRestored true () () false true := by
  refine ⟨rfl, rfl, rfl, rfl, ?_, ?_, ?_⟩
  · simp [rollbackRestored]
  · decide
  · decide

def afterRollbackFresh : TestState :=
  afterFresh rollbackRestored true () () false false true

theorem rollback_local_restore_yields_two_receipts :
    Step rollbackRestored (.fresh true false false true) afterRollbackFresh ∧
      afterRollbackFresh.committedReceipts = {false, true} := by
  exact ⟨.fresh restoredFreshOK, by decide⟩

theorem digest_rebinding_rejected :
    (¬ ReplayOK afterFirst false false true false) ∧
      (¬ RetryOK afterFirst false false true false) := by
  exact ⟨conflicting_digest_has_no_replay (by decide) firstReplay,
    conflicting_digest_has_no_retry (by decide) firstRetry⟩

end Fixtures

#print axioms fresh_preserves_safe
#print axioms step_preserves_phaseWF
#print axioms step_phase_mono
#print axioms rtc_preserves_safe
#print axioms rtc_preserves_phaseWF
#print axioms rtc_phase_mono
#print axioms rtc_ledger_mono
#print axioms committed_card_le_issued_card
#print axioms Trace.committed_card_growth
#print axioms Fixtures.three_retries_trace
#print axioms Fixtures.cloned_private_cells_two_commitments
#print axioms Fixtures.rollback_local_restore_yields_two_receipts

end AuthorityContinuity.RedemptionCommitment
