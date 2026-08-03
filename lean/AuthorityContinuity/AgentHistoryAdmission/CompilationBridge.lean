import AuthorityContinuity.AgentHistoryAdmission.OperationalSemantics

/-!
# Compilation bridge for installed Agent-history edits

This module connects finite compiler admission to the installed transition
semantics.  It does not add a second compiler or an untyped installation
path: the constructed candidate retains the supplied `HistoryDerivation`,
uses the current authenticated slice and durable receipt cells, and installs
through one of the six existing kernel transitions.
-/

namespace AuthorityContinuity.AgentHistoryAdmission.CompilationBridge

open AuthorityContinuity.AgentHistoryAdmission.FiniteCore
open AuthorityContinuity.AgentHistoryAdmission.HistoryStructure
open AuthorityContinuity.AgentHistoryAdmission.OperationalSemantics

universe uOutcome uLabel

/-- The finite contract compiled at the state's current durable receipt cut. -/
def currentContract
    [DecidableEq Outcome] [DecidableEq Label]
    (state :
      InstalledState (Outcome := Outcome) (Label := Label)) :
    Contract Outcome Label :=
  contractAt state.specification.slice (state.receipts.map (·.cell))

/-- The deterministic bundle allocated for an edit from the current slice. -/
def editAllocation
    [DecidableEq Outcome] [DecidableEq Label]
    (state :
      InstalledState (Outcome := Outcome) (Label := Label))
    (request : EditRequest) : Allocation :=
  allocateBundle state.specification.seed
    state.specification.slice.schemaVersion
    state.specification.slice.viewVersion
      (OperationalSemantics.EditRequest.requestId request)

/-- Independent epoch-freshness facts not already implied by `AgentSec`. -/
structure FreshEditAllocation
    [DecidableEq Outcome] [DecidableEq Label]
    (state :
      InstalledState (Outcome := Outcome) (Label := Label))
    (request : EditRequest) : Prop where
  ne_active :
    (editAllocation state request).epoch ≠ state.activeEpoch
  not_closed :
    (editAllocation state request).epoch ∉ state.closedEpochs

/-- Build the exact cut specification certified by compiler admission. -/
def compileSpecification
    [DecidableEq Outcome] [DecidableEq Label]
    (state :
      InstalledState (Outcome := Outcome) (Label := Label))
    (secure : AgentSec state)
    {request : EditRequest} {target : History}
    (derivation : HistoryDerivation state.history request target)
    (admitted : CompilerAns (currentContract state) = .admit)
    (targetWellFormed : target.WellFormed) :
    CutSpecification (Outcome := Outcome) (Label := Label) := by
  have accepted :
      ValidInstance (currentContract state) ∧
        (greatestPostfixed (currentContract state)).Nonempty :=
    (compilerAns_eq_admit_iff (currentContract state)).1 admitted
  exact {
    slice := state.specification.slice
    seed := state.specification.seed
    source := some state.history
    target := target
    request := OperationalSemantics.EditRequest.requestId request
    origin := .edit derivation
    durableReceiptCells := state.receipts.map (·.cell)
    contract := currentContract state
    contract_eq := rfl
    allocation := editAllocation state request
    allocation_eq := rfl
    indexedCompletions := greatestPostfixed (currentContract state)
    generatedLanguage :=
      Wof (currentContract state) (greatestPostfixed (currentContract state))
    indexed_eq := rfl
    language_eq := rfl
    contractValid := accepted.1
    realizationNonempty := accepted.2
    semanticRealization :=
      (greatestPostfixed_is_realization_iff_nonempty
        (currentContract state) accepted.1).2 accepted.2
    targetWellFormed := targetWellFormed
    fullTargetLift := secure.core_schema.2.2.2
  }

/-- Package a derived edit with its compiler-certified cut specification. -/
def compileInstallCandidate
    [DecidableEq Outcome] [DecidableEq Label]
    (state :
      InstalledState (Outcome := Outcome) (Label := Label))
    (secure : AgentSec state)
    {request : EditRequest} {target : History}
    (derivation : HistoryDerivation state.history request target)
    (admitted : CompilerAns (currentContract state) = .admit)
    (targetWellFormed : target.WellFormed) :
    InstallCandidate (Outcome := Outcome) (Label := Label) where
  capturedHistory := state.history
  parentEpoch := state.activeEpoch
  request := request
  specification :=
    compileSpecification state secure derivation admitted targetWellFormed
  source_eq := rfl
  derivation := derivation

/-- The compiled candidate satisfies every installed-state validity guard. -/
theorem compileInstallCandidate_validFor
    [DecidableEq Outcome] [DecidableEq Label]
    (state :
      InstalledState (Outcome := Outcome) (Label := Label))
    (secure : AgentSec state)
    {request : EditRequest} {target : History}
    (derivation : HistoryDerivation state.history request target)
    (admitted : CompilerAns (currentContract state) = .admit)
    (targetWellFormed : target.WellFormed)
    (fresh : FreshEditAllocation state request)
    (running : state.availability = .running) :
    (compileInstallCandidate state secure derivation admitted
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

/-- Compiler admission produces a valid six-edit installation step whose
post-state still satisfies `AgentSec`. -/
theorem compiler_admit_exists_secure_install
    [DecidableEq Outcome] [DecidableEq Label]
    (state :
      InstalledState (Outcome := Outcome) (Label := Label))
    (secure : AgentSec state)
    {request : EditRequest} {target : History}
    (derivation : HistoryDerivation state.history request target)
    (admitted : CompilerAns (currentContract state) = .admit)
    (targetWellFormed : target.WellFormed)
    (fresh : FreshEditAllocation state request)
    (running : state.availability = .running) :
    ∃ (candidate :
        InstallCandidate (Outcome := Outcome) (Label := Label))
      (event : KernelEvent (Outcome := Outcome) (Label := Label)),
      candidate =
          compileInstallCandidate state secure derivation admitted
            targetWellFormed ∧
        candidate.ValidFor state ∧
        KernelStep state event (installPost state candidate) ∧
        AgentSec (installPost state candidate) := by
  let candidate :=
    compileInstallCandidate state secure derivation admitted
      targetWellFormed
  have valid : candidate.ValidFor state := by
    dsimp only [candidate]
    exact compileInstallCandidate_validFor state secure derivation admitted
      targetWellFormed fresh running
  obtain ⟨event, step⟩ := six_edits_closed candidate valid
  exact ⟨candidate, event, rfl, valid, step,
    installPost_agentSec secure valid⟩

/-- Every cut specification already carries a nonempty greatest fixed point. -/
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
