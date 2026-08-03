import AuthorityContinuity.AgentHistoryAdmission.OperationalSemantics

/-!
# Checked registration refinement for finite Agent workflow slices

This module closes a small, explicit part of the application-to-model
adequacy boundary.  A finite typed workflow IR declares promised raw
occurrence words and a canonical invocation for every occurrence.  Semantic
cells are not supplied independently: they are derived by an injective
encoding of canonical invocations.  Compilation constructs the existing
`RegisteredSlice` used by the installed semantics.

The finite checker compares an arbitrary registered slice with that
construction only on the workflow's finite semantic support.  The generic
theorems establish support and identity-row completeness, the exact
cell/canonical-invocation quotient, exhaustive protected-call mediation,
Fresh/Alias receipt fidelity, and preservation of the existing finite
admission instance.  This is a typed finite-slice refinement result, not a
claim about effect paths outside the compiled workflow boundary.
-/

namespace AuthorityContinuity.AgentHistoryAdmission.RegistrationRefinement

open AuthorityContinuity.AgentHistoryAdmission.FiniteCore
open AuthorityContinuity.AgentHistoryAdmission.HistoryStructure
open AuthorityContinuity.AgentHistoryAdmission.OperationalSemantics

universe uOutcome uInvocation uLabel

/-- A finite workflow registration surface.

`support` is derived below from promised outcome linearizations.  `base` is
the concrete registered root word and is checked to enumerate exactly that
support.  Most importantly, `cellCode` is injective and compilation defines
`cellOf x = cellCode (canonical x)`: the cell quotient is therefore derived
from, rather than independent of, canonical invocation identity. -/
structure WorkflowIR
    (Outcome : Type uOutcome) (Invocation : Type uInvocation)
    (Label : Type uLabel) where
  base : List Occurrence
  promised : Finset Outcome
  linearizations : Outcome → Finset (List Occurrence)
  canonical : Occurrence → Invocation
  cellCode : Invocation → Cell
  cellCode_injective : Function.Injective cellCode
  authority : Finset (List Label)
  labelOf : Cell → Label
  schemaVersion : Version
  viewVersion : Version
  policyVersion : Version
  registeredSchemas : Finset Nat

section Generic

variable {Outcome : Type uOutcome} {Invocation : Type uInvocation}
variable {Label : Type uLabel}
variable [DecidableEq Outcome] [DecidableEq Invocation] [DecidableEq Label]

/-- Every occurrence mentioned by a promised raw completion. -/
def WorkflowIR.support
    (workflow : WorkflowIR Outcome Invocation Label) : Finset Occurrence :=
  workflow.promised.biUnion fun outcome =>
    (workflow.linearizations outcome).biUnion fun word => word.toFinset

/-- The semantic cell derived from a canonical invocation. -/
def WorkflowIR.derivedCell
    (workflow : WorkflowIR Outcome Invocation Label)
    (occurrence : Occurrence) : Cell :=
  workflow.cellCode (workflow.canonical occurrence)

/-- Authenticated identity rows are generated for exactly the finite semantic
support, never for the ambient infinite occurrence namespace. -/
def WorkflowIR.identityRows
    (workflow : WorkflowIR Outcome Invocation Label) :
    Finset (Occurrence × Cell) :=
  workflow.support.image fun occurrence =>
    (occurrence, workflow.derivedCell occurrence)

/-- One protected boundary instruction.  There is deliberately no raw
durable-dispatch constructor in this finite lowering surface. -/
structure MediatedCall (Invocation : Type uInvocation) where
  occurrence : Occurrence
  canonical : Invocation
  cell : Cell
deriving DecidableEq, Repr

/-- The unique protected call generated for an occurrence. -/
def WorkflowIR.callFor
    (workflow : WorkflowIR Outcome Invocation Label)
    (occurrence : Occurrence) : MediatedCall Invocation where
  occurrence := occurrence
  canonical := workflow.canonical occurrence
  cell := workflow.derivedCell occurrence

/-- All and only protected calls generated for registered semantic support. -/
def WorkflowIR.mediatedCalls
    (workflow : WorkflowIR Outcome Invocation Label) :
    Finset (MediatedCall Invocation) :=
  workflow.support.image workflow.callFor

/-- Compile the typed workflow into the installed semantics' existing
registration record. -/
def WorkflowIR.compile
    (workflow : WorkflowIR Outcome Invocation Label) :
    RegisteredSlice Outcome Label where
  base := workflow.base
  promised := workflow.promised
  linearizations := workflow.linearizations
  cellOf := workflow.derivedCell
  authority := workflow.authority
  labelOf := workflow.labelOf
  schemaVersion := workflow.schemaVersion
  viewVersion := workflow.viewVersion
  policyVersion := workflow.policyVersion
  registeredSchemas := workflow.registeredSchemas
  authenticatedIdentityRows := workflow.identityRows

/-- The admission instance denoted directly by the typed workflow. -/
def WorkflowIR.contract
    (workflow : WorkflowIR Outcome Invocation Label)
    (durableReceiptCells : List Cell) : Contract Outcome Label where
  promised := workflow.promised
  linearizations := workflow.linearizations
  cellOf := workflow.derivedCell
  durableReceiptCells := durableReceiptCells
  authority := workflow.authority
  labelOf := workflow.labelOf

/-- The finite structural conditions checked before comparing a candidate
registration. -/
def WorkflowIR.WellFormed
    (workflow : WorkflowIR Outcome Invocation Label) : Prop :=
  workflow.promised.Nonempty ∧
    workflow.registeredSchemas.Nonempty ∧
    workflow.base.Nodup ∧
    workflow.base.toFinset = workflow.support

/-- A candidate registration agrees with the workflow on every semantic field
that is observable over the finite registered support. -/
def RegistrationRefines
    (workflow : WorkflowIR Outcome Invocation Label)
    (registered : RegisteredSlice Outcome Label) : Prop :=
  workflow.WellFormed ∧
    registered.base = workflow.base ∧
    registered.promised = workflow.promised ∧
    (∀ outcome ∈ workflow.promised,
      registered.linearizations outcome = workflow.linearizations outcome) ∧
    (∀ occurrence ∈ workflow.support,
      registered.cellOf occurrence = workflow.derivedCell occurrence) ∧
    registered.authority = workflow.authority ∧
    (∀ occurrence ∈ workflow.support,
      registered.labelOf (workflow.derivedCell occurrence) =
        workflow.labelOf (workflow.derivedCell occurrence)) ∧
    registered.schemaVersion = workflow.schemaVersion ∧
    registered.viewVersion = workflow.viewVersion ∧
    registered.policyVersion = workflow.policyVersion ∧
    registered.registeredSchemas = workflow.registeredSchemas ∧
    registered.authenticatedIdentityRows = workflow.identityRows

/-- Executable finite registration checker. -/
def checkRegistration
    (workflow : WorkflowIR Outcome Invocation Label)
    (registered : RegisteredSlice Outcome Label) : Bool :=
  decide workflow.promised.Nonempty &&
  decide workflow.registeredSchemas.Nonempty &&
  decide workflow.base.Nodup &&
  decide (workflow.base.toFinset = workflow.support) &&
  decide (registered.base = workflow.base) &&
  decide (registered.promised = workflow.promised) &&
  finsetAll workflow.promised (fun outcome =>
    decide
      (registered.linearizations outcome =
        workflow.linearizations outcome)) &&
  finsetAll workflow.support (fun occurrence =>
    decide
      (registered.cellOf occurrence = workflow.derivedCell occurrence)) &&
  decide (registered.authority = workflow.authority) &&
  finsetAll workflow.support (fun occurrence =>
    decide
      (registered.labelOf (workflow.derivedCell occurrence) =
        workflow.labelOf (workflow.derivedCell occurrence))) &&
  decide (registered.schemaVersion = workflow.schemaVersion) &&
  decide (registered.viewVersion = workflow.viewVersion) &&
  decide (registered.policyVersion = workflow.policyVersion) &&
  decide (registered.registeredSchemas = workflow.registeredSchemas) &&
  decide
    (registered.authenticatedIdentityRows = workflow.identityRows)

/-- The Boolean checker is exactly the finite refinement predicate. -/
theorem checkRegistration_iff
    (workflow : WorkflowIR Outcome Invocation Label)
    (registered : RegisteredSlice Outcome Label) :
    checkRegistration workflow registered = true ↔
      RegistrationRefines workflow registered := by
  simp [checkRegistration, RegistrationRefines, WorkflowIR.WellFormed,
    finsetAll_eq_true]
  tauto

/-- Compilation passes the relational checker whenever the workflow's finite
root support is well formed. -/
theorem compile_refines
    (workflow : WorkflowIR Outcome Invocation Label)
    (wellFormed : workflow.WellFormed) :
    RegistrationRefines workflow workflow.compile := by
  simp [RegistrationRefines, WorkflowIR.compile, wellFormed]

/-- Executable acceptance of the compiler-produced registration. -/
theorem checkRegistration_compile
    (workflow : WorkflowIR Outcome Invocation Label)
    (wellFormed : workflow.WellFormed) :
    checkRegistration workflow workflow.compile = true :=
  (checkRegistration_iff workflow workflow.compile).2
    (compile_refines workflow wellFormed)

/-! ## Finite support and identity completeness -/

/-- Membership in support has an explicit promised-outcome/raw-word witness. -/
theorem mem_support_iff
    (workflow : WorkflowIR Outcome Invocation Label)
    (occurrence : Occurrence) :
    occurrence ∈ workflow.support ↔
      ∃ outcome ∈ workflow.promised,
        ∃ word ∈ workflow.linearizations outcome, occurrence ∈ word := by
  simp [WorkflowIR.support]

/-- Generated identity rows are complete and exact on finite semantic
support. -/
theorem mem_identityRows_iff
    (workflow : WorkflowIR Outcome Invocation Label)
    (occurrence : Occurrence) :
    (occurrence, workflow.derivedCell occurrence) ∈ workflow.identityRows ↔
      occurrence ∈ workflow.support := by
  simp [WorkflowIR.identityRows]

/-- The compiled `RegisteredSlice` contains the correct row for every and only
supported occurrence. -/
theorem compiled_identity_rows_complete
    (workflow : WorkflowIR Outcome Invocation Label)
    (occurrence : Occurrence) :
    (occurrence, workflow.compile.cellOf occurrence) ∈
        workflow.compile.authenticatedIdentityRows ↔
      occurrence ∈ workflow.support := by
  simpa [WorkflowIR.compile] using
    mem_identityRows_iff workflow occurrence

/-! ## Canonical invocation quotient and mediation -/

/-- Cell equality is exactly canonical-invocation equality. -/
theorem derivedCell_eq_iff_canonical_eq
    (workflow : WorkflowIR Outcome Invocation Label)
    (left right : Occurrence) :
    workflow.derivedCell left = workflow.derivedCell right ↔
      workflow.canonical left = workflow.canonical right := by
  constructor
  · intro equality
    exact workflow.cellCode_injective
      (by simpa [WorkflowIR.derivedCell] using equality)
  · intro equality
    exact congrArg workflow.cellCode equality

/-- The same quotient theorem stated through the compiled registry. -/
theorem compiled_cell_eq_iff_canonical_eq
    (workflow : WorkflowIR Outcome Invocation Label)
    (left right : Occurrence) :
    workflow.compile.cellOf left = workflow.compile.cellOf right ↔
      workflow.canonical left = workflow.canonical right := by
  simpa [WorkflowIR.compile] using
    derivedCell_eq_iff_canonical_eq workflow left right

/-- Every mediated call has a supported source occurrence, canonical
invocation, and derived cell, and every supported occurrence contributes such
a call. -/
theorem mem_mediatedCalls_iff
    (workflow : WorkflowIR Outcome Invocation Label)
    (call : MediatedCall Invocation) :
    call ∈ workflow.mediatedCalls ↔
      ∃ occurrence ∈ workflow.support,
        workflow.callFor occurrence = call := by
  exact Finset.mem_image

/-- Exhaustive mediation and identity-row registration coincide on the finite
support. -/
theorem compiled_mediation_exhaustive
    (workflow : WorkflowIR Outcome Invocation Label)
    (occurrence : Occurrence) :
    workflow.callFor occurrence ∈ workflow.mediatedCalls ↔
      (occurrence, workflow.compile.cellOf occurrence) ∈
        workflow.compile.authenticatedIdentityRows := by
  constructor
  · intro mediated
    rw [mem_mediatedCalls_iff] at mediated
    obtain ⟨source, sourceMember, equality⟩ := mediated
    have occurrenceEquality :
        source = occurrence :=
      congrArg MediatedCall.occurrence equality
    subst source
    exact (compiled_identity_rows_complete workflow occurrence).2 sourceMember
  · intro registered
    have supportMember :=
      (compiled_identity_rows_complete workflow occurrence).1 registered
    exact Finset.mem_image.mpr ⟨occurrence, supportMember, rfl⟩

/-! ## Receipt resolution fidelity -/

/-- A receipted derived cell resolves as `Alias` and does not extend the
receipt set for the suffix. -/
theorem compiled_receipt_alias
    (workflow : WorkflowIR Outcome Invocation Label)
    (receipted : Finset Cell) (occurrence : Occurrence)
    (rest : List Occurrence)
    (alreadyReceipted : workflow.derivedCell occurrence ∈ receipted) :
    resolveFrom workflow.compile.cellOf receipted (occurrence :: rest) =
      ⟨occurrence, workflow.derivedCell occurrence, .alias⟩ ::
        resolveFrom workflow.compile.cellOf receipted rest := by
  simp [resolveFrom, WorkflowIR.compile, alreadyReceipted]

/-- The first occurrence of an unreceipted derived cell resolves as `Fresh`
and inserts exactly that cell before resolving the suffix. -/
theorem compiled_receipt_fresh
    (workflow : WorkflowIR Outcome Invocation Label)
    (receipted : Finset Cell) (occurrence : Occurrence)
    (rest : List Occurrence)
    (notReceipted : workflow.derivedCell occurrence ∉ receipted) :
    resolveFrom workflow.compile.cellOf receipted (occurrence :: rest) =
      ⟨occurrence, workflow.derivedCell occurrence, .fresh⟩ ::
        resolveFrom workflow.compile.cellOf
          (insert (workflow.derivedCell occurrence) receipted) rest := by
  simp [resolveFrom, WorkflowIR.compile, notReceipted]

/-- Global receipt fidelity inherited by the compiled contract: Fresh cells
are unique and never remint a cell from the durable receipt cut. -/
theorem compiled_fresh_receipts_unique
    (workflow : WorkflowIR Outcome Invocation Label)
    (durableReceiptCells : List Cell) (word : List Occurrence) :
    (freshCells
        (resolve (contractAt workflow.compile durableReceiptCells) word)).Nodup ∧
      ∀ cell ∈
          freshCells
            (resolve (contractAt workflow.compile durableReceiptCells) word),
        cell ∉
          (contractAt workflow.compile durableReceiptCells).initialReceipted :=
  resolve_fresh_cell_unique
    (contractAt workflow.compile durableReceiptCells) word

/-! ## Contract and admission preservation -/

/-- Compilation preserves the complete finite admission instance exactly. -/
theorem contractAt_compile
    (workflow : WorkflowIR Outcome Invocation Label)
    (durableReceiptCells : List Cell) :
    contractAt workflow.compile durableReceiptCells =
      workflow.contract durableReceiptCells := by
  rfl

/-- Candidate generation is unchanged by passage through `RegisteredSlice`. -/
theorem compiled_candidates_preserved
    (workflow : WorkflowIR Outcome Invocation Label)
    (durableReceiptCells : List Cell) :
    allCandidates (contractAt workflow.compile durableReceiptCells) =
      allCandidates (workflow.contract durableReceiptCells) := by
  rw [contractAt_compile]

/-- The existing executable admission answer is exactly preserved by typed
registration compilation. -/
theorem compiled_admission_preserved
    (workflow : WorkflowIR Outcome Invocation Label)
    (durableReceiptCells : List Cell) :
    CompilerAns (contractAt workflow.compile durableReceiptCells) =
      CompilerAns (workflow.contract durableReceiptCells) := by
  rw [contractAt_compile]

end Generic

/-! ## Closed positive and negative fixtures -/

namespace Fixtures

inductive Outcome where
  | completed
deriving DecidableEq, Repr

inductive Invocation where
  | approve
deriving DecidableEq, Repr

inductive Label where
  | spend
deriving DecidableEq, Repr

def first : Occurrence := ⟨10⟩
def replay : Occurrence := ⟨11⟩
def approveCell : Cell := ⟨20⟩

def canonical (_ : Occurrence) : Invocation := .approve

def cellCode : Invocation → Cell
  | .approve => approveCell

theorem cellCode_injective : Function.Injective cellCode := by
  intro left right _
  cases left
  cases right
  rfl

def linearizations : Outcome → Finset (List Occurrence)
  | .completed => {[first, replay]}

/-- Two logical occurrences intentionally share one canonical invocation and
therefore one derived semantic cell. -/
def acceptedWorkflow : WorkflowIR Outcome Invocation Label where
  base := [first, replay]
  promised := {.completed}
  linearizations := linearizations
  canonical := canonical
  cellCode := cellCode
  cellCode_injective := cellCode_injective
  authority := {[], [.spend]}
  labelOf := fun _ => .spend
  schemaVersion := ⟨0⟩
  viewVersion := ⟨0⟩
  policyVersion := ⟨0⟩
  registeredSchemas := {7}

theorem acceptedWorkflow_wellFormed : acceptedWorkflow.WellFormed := by
  simp [WorkflowIR.WellFormed, acceptedWorkflow, WorkflowIR.support,
    linearizations, first, replay]

theorem accepted_registration :
    checkRegistration acceptedWorkflow acceptedWorkflow.compile = true :=
  checkRegistration_compile acceptedWorkflow acceptedWorkflow_wellFormed

theorem accepted_identity_support :
    acceptedWorkflow.identityRows =
      {(first, approveCell), (replay, approveCell)} := by
  decide

theorem accepted_fresh_then_alias :
    resolve (acceptedWorkflow.contract []) [first, replay] =
      [⟨first, approveCell, .fresh⟩,
       ⟨replay, approveCell, .alias⟩] := by
  decide

theorem accepted_admission_not_reject :
    CompilerAns (acceptedWorkflow.contract []) ≠ .reject := by
  decide

/-- Mutation control: deleting one generated identity row is rejected. -/
def missingIdentityRow : RegisteredSlice Outcome Label :=
  { acceptedWorkflow.compile with
    authenticatedIdentityRows := {(first, approveCell)} }

theorem rejects_missing_identity_row :
    checkRegistration acceptedWorkflow missingIdentityRow = false := by
  decide

/-- Mutation control: rebinding one supported occurrence to a different cell
is rejected even though every other registration field is retained. -/
def wrongCellBinding : RegisteredSlice Outcome Label :=
  { acceptedWorkflow.compile with
    cellOf := fun occurrence =>
      if occurrence = replay then ⟨999⟩ else
        acceptedWorkflow.derivedCell occurrence }

theorem rejects_wrong_cell_binding :
    checkRegistration acceptedWorkflow wrongCellBinding = false := by
  decide

/-- Mutation control: omitting the promised outcome is rejected. -/
def missingPromise : RegisteredSlice Outcome Label :=
  { acceptedWorkflow.compile with promised := ∅ }

theorem rejects_missing_promise :
    checkRegistration acceptedWorkflow missingPromise = false := by
  decide

end Fixtures

end AuthorityContinuity.AgentHistoryAdmission.RegistrationRefinement
