import AuthorityContinuity.AgentHistoryAdmission.RegistrationRefinement
import AuthorityContinuity.AgentHistoryAdmission.CompilationBridge

/-!
# Paper-facing end-to-end theorems

This module packages the executable finite checker, typed registration,
six-edit derivation, atomic installation, and trace invariant into the theorem
spine used by the paper.  Each result is a direct composition of independently
defined semantic and executable objects from the five Agent-history-admission
modules.
-/

namespace AuthorityContinuity.AgentHistoryAdmission.PaperTheorems

open AuthorityContinuity.AgentHistoryAdmission.FiniteCore
open AuthorityContinuity.AgentHistoryAdmission.HistoryStructure
open AuthorityContinuity.AgentHistoryAdmission.OperationalSemantics
open AuthorityContinuity.AgentHistoryAdmission.RegistrationRefinement
open AuthorityContinuity.AgentHistoryAdmission.CompilationBridge

universe uOutcome uOccurrence uCell uLabel uInvocation

/-- The executable greatest-fixed-point checker is exact with respect to the
independently stated declarative realization predicate. -/
theorem exact_checker_iff_realization
    {Outcome : Type uOutcome} {Occurrence : Type uOccurrence}
    {Cell : Type uCell} {Label : Type uLabel}
    [DecidableEq Outcome] [DecidableEq Occurrence]
    [DecidableEq Cell] [DecidableEq Label]
    (input : Instance Outcome Occurrence Cell Label) :
    CompilerAns input = .admit ↔
      ∃ language family, ValidRealization input language family :=
  admit_iff_exists_validRealization input

/-- Typed compilation gives one end-to-end registered-workflow fact: the
registration checker accepts, mediation covers exactly the registered finite
support, and executable admission is equivalent to declarative realization. -/
theorem registered_workflow_exact_admission
    {Outcome : Type uOutcome} {Invocation : Type uInvocation}
    {Label : Type uLabel}
    [DecidableEq Outcome] [DecidableEq Invocation] [DecidableEq Label]
    (workflow : WorkflowIR Outcome Invocation Label)
    (wellFormed : workflow.WellFormed)
    (durableReceiptCells : List Cell) :
    checkRegistration workflow workflow.compile = true ∧
      (∀ occurrence,
        workflow.callFor occurrence ∈ workflow.mediatedCalls ↔
          (occurrence, workflow.compile.cellOf occurrence) ∈
            workflow.compile.authenticatedIdentityRows) ∧
      (CompilerAns
          (contractAt workflow.compile durableReceiptCells) = .admit ↔
        ∃ language family,
          ValidRealization (workflow.contract durableReceiptCells)
            language family) := by
  refine ⟨checkRegistration_compile workflow wellFormed, ?_, ?_⟩
  · exact compiled_mediation_exhaustive workflow
  · rw [contractAt_compile]
    exact admit_iff_exists_validRealization
      (workflow.contract durableReceiptCells)

/-- The executable derivation function is sound and complete for the six
typed execution-edit rules. -/
theorem six_edit_derivation_exact
    {history post : History} {request : EditRequest} :
    deriveEdit history request = some post ↔
      HistoryDerivation history request post :=
  deriveEdit_iff

/-- Compilation is an explicit kernel event: preloading records the candidate
in inactive metadata and preserves the complete installed-state invariant. -/
theorem compilation_preload_preserves_agentSec
    {Outcome : Type} {Label : Type}
    [DecidableEq Outcome] [DecidableEq Label]
    {state : InstalledState (Outcome := Outcome) (Label := Label)}
    (secure : AgentSec state)
    (candidate : InstallCandidate (Outcome := Outcome) (Label := Label)) :
    KernelStep state (.preload candidate) (preloadPost state candidate) ∧
      AgentSec (preloadPost state candidate) := by
  have step :
      KernelStep state (.preload candidate) (preloadPost state candidate) :=
    KernelStep.preload
  exact ⟨step, kernelStep_preserves_agentSec secure step⟩

/-- For a well-formed installed state, an executable six-edit derivation and
compiler admission construct an atomic installation whose successor and every
finite continuation satisfy `AgentSec`. -/
theorem exact_edit_installs_trace_safe_monitor
    {Outcome : Type} {Label : Type}
    [DecidableEq Outcome] [DecidableEq Label]
    (state : InstalledState (Outcome := Outcome) (Label := Label))
    (secure : AgentSec state)
    {request : RegisteredEditRequest} {target : History}
    {contract : Contract Outcome Label}
    (edited : editedContract state request target = some contract)
    (admitted : CompilerAns contract = .admit)
    (fresh : FreshEditAllocation state request)
    (running : state.availability = RuntimeAvailability.running) :
    ∃ (candidate : InstallCandidate (Outcome := Outcome) (Label := Label))
      (event : KernelEvent (Outcome := Outcome) (Label := Label)),
      candidate =
          compileInstallCandidate state secure
            edited admitted
            (historyDerivation_preserves_wellFormed secure.core_schema.1
              (editedContract_authenticatedDerivation state
                edited).structural) ∧
        candidate.ValidFor state ∧
        KernelStep state event (installPost state candidate) ∧
        ∀ post, KernelTrace (installPost state candidate) post →
          AgentSec post := by
  let derivation :
      AuthenticatedHistoryDerivation state.specification.slice state.history
        request target :=
    editedContract_authenticatedDerivation state edited
  have targetWellFormed : target.WellFormed :=
    historyDerivation_preserves_wellFormed secure.core_schema.1
      derivation.structural
  obtain ⟨candidate, event, candidateEq, valid, step, postSecure⟩ :=
    compiler_admit_exists_secure_install state secure edited admitted
      targetWellFormed fresh running
  refine ⟨candidate, event, ?_, valid, step, ?_⟩
  · simpa [derivation, targetWellFormed] using candidateEq
  · intro post trace
    exact kernelTrace_preserves_agentSec postSecure trace

/-- A protected use and an installation have exactly the two durable orders:
a prior Fresh or Alias makes the prepared installation stale, while a prior
installation closes the old epoch and turns the old use into a denial. -/
theorem fresh_alias_installation_serialized
    {Outcome : Type} {Label : Type}
    [DecidableEq Outcome] [DecidableEq Label]
    {state : InstalledState (Outcome := Outcome) (Label := Label)}
    {candidate : InstallCandidate (Outcome := Outcome) (Label := Label)}
    {token : UseToken}
    (valid : candidate.ValidFor state)
    (oldEpoch : token.epoch = state.activeEpoch) :
    (∀ post, KernelStep state (.freshUse token) post →
      ¬ candidate.ValidFor post) ∧
    (∀ post, KernelStep state (.aliasUse token) post →
      ¬ candidate.ValidFor post) ∧
    ¬ UseGuard (installPost state candidate) token ∧
    KernelStep (installPost state candidate) (.denial token)
      (denialPost (installPost state candidate) token) := by
  refine ⟨?_, ?_, install_before_old_use_denied valid oldEpoch⟩
  · intro post use
    exact fresh_before_install_stale use valid.1
  · intro post use
    exact alias_before_install_stale use valid.1

end AuthorityContinuity.AgentHistoryAdmission.PaperTheorems
