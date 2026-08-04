import AuthorityContinuity.AgentHistoryAdmission.OperationalSemantics

/-!
# Compilation bridge for installed Agent-history edits

This module connects authenticated execution editing, finite compiler
admission, and installed transition semantics.  Agent-facing requests contain
no workflow suffix or authorization Boolean.  The compiler checks the indexed
edited contract derived from the authenticated registry, and atomic
installation stores that same contract.
-/

namespace AuthorityContinuity.AgentHistoryAdmission.CompilationBridge

open AuthorityContinuity.AgentHistoryAdmission.FiniteCore
open AuthorityContinuity.AgentHistoryAdmission.HistoryStructure
open AuthorityContinuity.AgentHistoryAdmission.OperationalSemantics

universe uOutcome uLabel

/-- The finite pre-edit contract at the state's current durable receipt cut. -/
def currentContract
    [DecidableEq Outcome] [DecidableEq Label]
    (state :
      InstalledState (Outcome := Outcome) (Label := Label)) :
    Contract Outcome Label :=
  contractAt state.specification.slice (state.receipts.map (·.cell))

/-- The edited contract \(\mathcal C_u\) derived from authenticated state,
the public request, and its target history. -/
def editedContract
    [DecidableEq Outcome] [DecidableEq Label]
    (state :
      InstalledState (Outcome := Outcome) (Label := Label))
    (request : RegisteredEditRequest)
    (target : History) : Option (Contract Outcome Label) :=
  editedContractAt state.specification.slice
    (state.receipts.map (·.cell)) state.history request target

/-- The deterministic bundle allocated for a public edit request. -/
def editAllocation
    [DecidableEq Outcome] [DecidableEq Label]
    (state :
      InstalledState (Outcome := Outcome) (Label := Label))
    (request : RegisteredEditRequest) : Allocation :=
  allocateBundle state.specification.seed
    state.specification.slice.schemaVersion
    state.specification.slice.viewVersion request.requestId

/-- Independent epoch-freshness facts not already implied by `AgentSec`. -/
structure FreshEditAllocation
    [DecidableEq Outcome] [DecidableEq Label]
    (state :
      InstalledState (Outcome := Outcome) (Label := Label))
    (request : RegisteredEditRequest) : Prop where
  ne_active :
    (editAllocation state request).epoch ≠ state.activeEpoch
  not_closed :
    (editAllocation state request).epoch ∉ state.closedEpochs

/-- Successful contract editing carries the authenticated structural
derivation used by installation. -/
def editedContract_authenticatedDerivation
    [DecidableEq Outcome] [DecidableEq Label]
    (state :
      InstalledState (Outcome := Outcome) (Label := Label))
    {request : RegisteredEditRequest} {target : History}
    {contract : Contract Outcome Label}
    (edited : editedContract state request target = some contract) :
    AuthenticatedHistoryDerivation state.specification.slice state.history
      request target := by
  unfold editedContract editedContractAt at edited
  cases lookup : state.specification.slice.lookupEditRule request with
  | none =>
      simp [lookup] at edited
  | some rule =>
      cases derive : deriveEdit state.history rule.resolvedEdit with
      | none =>
          simp [lookup, derive] at edited
      | some derived =>
          have accepted :
              derived = target ∧
                checkEditObligations state.specification.slice rule target =
                  true := by
            by_contra rejected
            simp [lookup, derive, rejected] at edited
          cases accepted.1
          exact ⟨rule, lookup, deriveEdit_sound derive⟩

/-- Build the cut specification certified by admission of the edited contract,
not admission of the pre-edit contract. -/
def compileSpecification
    [DecidableEq Outcome] [DecidableEq Label]
    (state :
      InstalledState (Outcome := Outcome) (Label := Label))
    (secure : AgentSec state)
    {request : RegisteredEditRequest} {target : History}
    {contract : Contract Outcome Label}
    (edited : editedContract state request target = some contract)
    (admitted : CompilerAns contract = .admit)
    (targetWellFormed : target.WellFormed) :
    CutSpecification (Outcome := Outcome) (Label := Label) := by
  have accepted :
      ValidInstance contract ∧
        (greatestPostfixed contract).Nonempty :=
    (compilerAns_eq_admit_iff contract).1 admitted
  let derivation :=
    editedContract_authenticatedDerivation state edited
  exact {
    slice := state.specification.slice
    seed := state.specification.seed
    source := some state.history
    target := target
    request := request.requestId
    origin := .edit derivation.structural
    durableReceiptCells := state.receipts.map (·.cell)
    contract := contract
    contract_source := Or.inr ⟨state.history, request, rfl, by
      simpa [editedContract] using edited⟩
    allocation := editAllocation state request
    allocation_eq := rfl
    indexedCompletions := greatestPostfixed contract
    generatedLanguage := Wof contract (greatestPostfixed contract)
    indexed_eq := rfl
    language_eq := rfl
    contractValid := accepted.1
    realizationNonempty := accepted.2
    semanticRealization :=
      (greatestPostfixed_is_realization_iff_nonempty
        contract accepted.1).2 accepted.2
    targetWellFormed := targetWellFormed
    fullTargetLift := secure.core_schema.2.2.2
  }

/-- Package an authenticated edit with its compiler-certified edited
contract. -/
def compileInstallCandidate
    [DecidableEq Outcome] [DecidableEq Label]
    (state :
      InstalledState (Outcome := Outcome) (Label := Label))
    (secure : AgentSec state)
    {request : RegisteredEditRequest} {target : History}
    {contract : Contract Outcome Label}
    (edited : editedContract state request target = some contract)
    (admitted : CompilerAns contract = .admit)
    (targetWellFormed : target.WellFormed) :
    InstallCandidate (Outcome := Outcome) (Label := Label) where
  capturedHistory := state.history
  parentEpoch := state.activeEpoch
  request := request
  specification :=
    compileSpecification state secure edited admitted targetWellFormed
  source_eq := rfl
  derivation := editedContract_authenticatedDerivation state edited

/-- The compiled candidate satisfies every installed-state validity guard. -/
theorem compileInstallCandidate_validFor
    [DecidableEq Outcome] [DecidableEq Label]
    (state :
      InstalledState (Outcome := Outcome) (Label := Label))
    (secure : AgentSec state)
    {request : RegisteredEditRequest} {target : History}
    {contract : Contract Outcome Label}
    (edited : editedContract state request target = some contract)
    (admitted : CompilerAns contract = .admit)
    (targetWellFormed : target.WellFormed)
    (fresh : FreshEditAllocation state request)
    (running : state.availability = .running) :
    (compileInstallCandidate state secure edited admitted
      targetWellFormed).ValidFor state := by
  refine ⟨rfl, rfl, rfl, rfl, rfl, ?_, ?_, ?_, ?_, running⟩
  · exact fresh.ne_active
  · change (editAllocation state request).epoch ∉ state.activeEpochs
    rw [secure.epoch.1]
    simpa using fresh.ne_active
  · exact fresh.not_closed
  · intro binding member
    have bindingEpoch :=
      (secure.epoch.2.2.2.1 binding member).2
    rw [bindingEpoch]
    exact Ne.symm fresh.ne_active

/-- Admission of the edited contract produces a valid six-edit installation
whose post-state still satisfies `AgentSec`. -/
theorem compiler_admit_exists_secure_install
    [DecidableEq Outcome] [DecidableEq Label]
    (state :
      InstalledState (Outcome := Outcome) (Label := Label))
    (secure : AgentSec state)
    {request : RegisteredEditRequest} {target : History}
    {contract : Contract Outcome Label}
    (edited : editedContract state request target = some contract)
    (admitted : CompilerAns contract = .admit)
    (targetWellFormed : target.WellFormed)
    (fresh : FreshEditAllocation state request)
    (running : state.availability = .running) :
    ∃ (candidate :
        InstallCandidate (Outcome := Outcome) (Label := Label))
      (event : KernelEvent (Outcome := Outcome) (Label := Label)),
      candidate =
          compileInstallCandidate state secure edited admitted
            targetWellFormed ∧
        candidate.ValidFor state ∧
        KernelStep state event (installPost state candidate) ∧
        AgentSec (installPost state candidate) := by
  let candidate :=
    compileInstallCandidate state secure edited admitted targetWellFormed
  have valid : candidate.ValidFor state := by
    dsimp only [candidate]
    exact compileInstallCandidate_validFor state secure edited admitted
      targetWellFormed fresh running
  obtain ⟨event, step⟩ := six_edits_closed candidate valid
  exact ⟨candidate, event, rfl, valid, step,
    installPost_agentSec secure valid⟩

/-- Atomic installation stores exactly the edited contract admitted above. -/
theorem compileInstallCandidate_installs_editedContract
    [DecidableEq Outcome] [DecidableEq Label]
    (state :
      InstalledState (Outcome := Outcome) (Label := Label))
    (secure : AgentSec state)
    {request : RegisteredEditRequest} {target : History}
    {contract : Contract Outcome Label}
    (edited : editedContract state request target = some contract)
    (admitted : CompilerAns contract = .admit)
    (targetWellFormed : target.WellFormed) :
    (installPost state
      (compileInstallCandidate state secure edited admitted
        targetWellFormed)).specification.contract = contract := by
  rfl

/-- Every cut specification carries a nonempty greatest fixed point. -/
theorem cutSpecification_greatestNonempty
    [DecidableEq Outcome] [DecidableEq Label]
    (specification :
      CutSpecification (Outcome := Outcome) (Label := Label)) :
    (greatestPostfixed specification.contract).Nonempty := by
  rw [← specification.indexed_eq]
  exact specification.realizationNonempty

/-- Every cut specification is accepted by the finite compiler. -/
theorem cutSpecification_compiler_admits
    [DecidableEq Outcome] [DecidableEq Label]
    (specification :
      CutSpecification (Outcome := Outcome) (Label := Label)) :
    CompilerAns specification.contract = .admit :=
  (compilerAns_eq_admit_iff specification.contract).2
    ⟨specification.contractValid,
      cutSpecification_greatestNonempty specification⟩

/-- Reverse bridge: a candidate valid for an installed state entails both
nonempty greatest-fixed-point semantics and finite compiler admission. -/
theorem validInstallCandidate_entails_admission
    [DecidableEq Outcome] [DecidableEq Label]
    {state :
      InstalledState (Outcome := Outcome) (Label := Label)}
    {candidate :
      InstallCandidate (Outcome := Outcome) (Label := Label)}
    (_valid : candidate.ValidFor state) :
    (greatestPostfixed candidate.specification.contract).Nonempty ∧
      CompilerAns candidate.specification.contract = .admit :=
  ⟨cutSpecification_greatestNonempty candidate.specification,
    cutSpecification_compiler_admits candidate.specification⟩

end AuthorityContinuity.AgentHistoryAdmission.CompilationBridge
