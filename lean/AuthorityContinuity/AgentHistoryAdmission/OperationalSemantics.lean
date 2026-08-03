import AuthorityContinuity.AgentHistoryAdmission.HistoryStructure

/-!
# Installed operational semantics for Agent-history admission

This module joins the finite admission theorem to an installed runtime state.
It keeps bootstrap outside the installed-slice kernel and gives the kernel its
own guarded transition relation.  In particular, successful history edits are
not untyped assignments: each names one of the six `HistoryDerivation`
constructors, carries a greatest declarative realization, and atomically
replaces the active epoch.
-/

namespace AuthorityContinuity.AgentHistoryAdmission.OperationalSemantics

open AuthorityContinuity.AgentHistoryAdmission.FiniteCore
open AuthorityContinuity.AgentHistoryAdmission.HistoryStructure

universe uOutcome uLabel

abbrev Contract (Outcome : Type uOutcome) (Label : Type uLabel) :=
  Instance Outcome Occurrence Cell Label

/-! ## Registered input and deterministic names -/

structure NamespaceSeed where
  value : Nat
deriving DecidableEq, Repr

inductive RuntimeRole where
  | epoch
  | gate
  | handle
  | certificate
  | resultFuture
deriving DecidableEq, Repr

structure RuntimeName where
  seed : NamespaceSeed
  schemaVersion : Version
  viewVersion : Version
  request : RequestId
  role : RuntimeRole
deriving DecidableEq, Repr

def allocateRuntime (seed : NamespaceSeed)
    (schemaVersion viewVersion : Version) (request : RequestId)
    (role : RuntimeRole) : RuntimeName :=
  ⟨seed, schemaVersion, viewVersion, request, role⟩

structure Allocation where
  epoch : RuntimeName
  gate : RuntimeName
  handle : RuntimeName
  certificate : RuntimeName
  resultFuture : RuntimeName
deriving DecidableEq, Repr

def allocateBundle (seed : NamespaceSeed)
    (schemaVersion viewVersion : Version) (request : RequestId) :
    Allocation where
  epoch := allocateRuntime seed schemaVersion viewVersion request .epoch
  gate := allocateRuntime seed schemaVersion viewVersion request .gate
  handle :=
    allocateRuntime seed schemaVersion viewVersion request .handle
  certificate :=
    allocateRuntime seed schemaVersion viewVersion request .certificate
  resultFuture :=
    allocateRuntime seed schemaVersion viewVersion request .resultFuture

/-- Registration contains contracts, policy, schemas, and authenticated
identity rows only.  In particular it has no receipt ledger, cursor, outbox,
epoch, certificate, result future, monitor state, or installed cut. -/
structure RegisteredSlice (Outcome : Type uOutcome) (Label : Type uLabel) where
  base : List Occurrence
  promised : Finset Outcome
  linearizations : Outcome → Finset (List Occurrence)
  cellOf : Occurrence → Cell
  authority : Finset (List Label)
  labelOf : Cell → Label
  schemaVersion : Version
  viewVersion : Version
  policyVersion : Version
  registeredSchemas : Finset Nat
  authenticatedIdentityRows : Finset (Occurrence × Cell)

def contractAt (slice : RegisteredSlice Outcome Label)
    (durableReceiptCells : List Cell) : Contract Outcome Label where
  promised := slice.promised
  linearizations := slice.linearizations
  cellOf := slice.cellOf
  durableReceiptCells := durableReceiptCells
  authority := slice.authority
  labelOf := slice.labelOf

def rootRequest (seed : NamespaceSeed) : RequestId :=
  ⟨seed.value⟩

def rootBranchName (seed : NamespaceSeed) : BranchName :=
  allocate .branch ⟨0⟩ (rootRequest seed) .forkChoiceLeft

def initialHistory (slice : RegisteredSlice Outcome Label)
    (seed : NamespaceSeed) : History where
  version := ⟨0⟩
  frontier := .leaf {
    name := rootBranchName seed
    base := slice.base
    cursor := []
    residual := slice.base
  }
  checkpoints := []
  progress := []

def FullTargetLift (slice : RegisteredSlice Outcome Label) : Prop :=
  ∀ outcome ∈ slice.promised, (slice.linearizations outcome).Nonempty

/-- The finite occurrence support whose identity rows can affect this
registered slice.  Occurrences outside the base and promised linearizations
are not part of the slice and need no registry row. -/
def RegisteredSlice.InSupport
    [DecidableEq Outcome]
    (slice : RegisteredSlice Outcome Label) (occurrence : Occurrence) : Prop :=
  occurrence ∈ slice.base ∨
    ∃ outcome ∈ slice.promised,
      ∃ word ∈ slice.linearizations outcome, occurrence ∈ word

structure RegisteredSlice.Valid
    [DecidableEq Outcome] [DecidableEq Label]
    (slice : RegisteredSlice Outcome Label) : Prop where
  identityComplete :
    ∀ occurrence, slice.InSupport occurrence →
      (occurrence, slice.cellOf occurrence) ∈
        slice.authenticatedIdentityRows
  schemaRegistered : slice.registeredSchemas.Nonempty
  fullTargetLift : FullTargetLift slice
  contractValid : ValidInstance (contractAt slice [])
  greatestNonempty :
    (greatestPostfixed (contractAt slice [])).Nonempty

/-- Authenticated append-only control-plane growth.  The active contract's
topology, resolution map, and labels retain exactly their old meanings.
Schemas, identity rows, and policy words may only be added, and all three
authenticated versions advance together. -/
structure RegisteredSlice.StaticExtends
    (source target : RegisteredSlice Outcome Label) : Prop where
  base_eq : target.base = source.base
  promised_eq : target.promised = source.promised
  linearizations_eq : target.linearizations = source.linearizations
  cellOf_eq : target.cellOf = source.cellOf
  labelOf_eq : target.labelOf = source.labelOf
  schemas_mono :
    source.registeredSchemas ⊆ target.registeredSchemas
  identityRows_mono :
    source.authenticatedIdentityRows ⊆
      target.authenticatedIdentityRows
  authority_mono : source.authority ⊆ target.authority
  schemaVersion_next :
    target.schemaVersion = source.schemaVersion.next
  viewVersion_next :
    target.viewVersion = source.viewVersion.next
  policyVersion_next :
    target.policyVersion = source.policyVersion.next

theorem initialHistory_wellFormed
    (slice : RegisteredSlice Outcome Label) (seed : NamespaceSeed) :
    (initialHistory slice seed).WellFormed := by
  constructor <;> simp [initialHistory, rootBranchName, rootRequest,
    Frontier.branches, Frontier.groups, Branch.WellFormed,
    Branch.rawCursor, progressAt, allocate]

/-! ## Root/edit origins and their common cut specification -/

structure InitialDerivation
    [DecidableEq Outcome] [DecidableEq Label]
    (slice : RegisteredSlice Outcome Label) (seed : NamespaceSeed)
    (target : History) : Prop where
  target_eq : target = initialHistory slice seed
  registered : slice.Valid

/-- A checked live extension is not a seventh structural edit.  Its history
target is identity-on-frontier, while its registered slice is an authenticated
static extension of the currently installed slice. -/
structure LiveExtensionDerivation
    (sourceSlice targetSlice : RegisteredSlice Outcome Label)
    (source : History) (request : RequestId) (target : History) : Prop where
  staticExtends : sourceSlice.StaticExtends targetSlice
  target_eq : target = extensionHistory source

inductive CutOrigin
    [DecidableEq Outcome] [DecidableEq Label]
    (slice : RegisteredSlice Outcome Label) (seed : NamespaceSeed) :
    Option History → History → Prop
  | root {target}
      (derivation : InitialDerivation slice seed target) :
      CutOrigin slice seed none target
  | edit {source target request}
      (derivation : HistoryDerivation source request target) :
      CutOrigin slice seed (some source) target
  | extension {sourceSlice source target request}
      (derivation :
        LiveExtensionDerivation sourceSlice slice source request target) :
      CutOrigin slice seed (some source) target

def EditRequest.requestId : EditRequest → RequestId
  | .forkChoice request _ _ _ => request
  | .forkParallel request _ _ _ => request
  | .restoreReplace request _ _ _ => request
  | .restoreLive request _ _ => request
  | .mergeSelect request _ _ _ _ => request
  | .mergeJoin request _ _ => request

structure CutSpecification
    [DecidableEq Outcome] [DecidableEq Label] where
  slice : RegisteredSlice Outcome Label
  seed : NamespaceSeed
  source : Option History
  target : History
  request : RequestId
  origin : CutOrigin slice seed source target
  durableReceiptCells : List Cell
  contract : Contract Outcome Label
  contract_eq : contract = contractAt slice durableReceiptCells
  allocation : Allocation
  allocation_eq :
    allocation =
      allocateBundle seed slice.schemaVersion slice.viewVersion request
  indexedCompletions :
    Finset (Completion Outcome Occurrence Cell)
  generatedLanguage : Finset (List Event)
  indexed_eq :
    indexedCompletions = greatestPostfixed contract
  language_eq : generatedLanguage = Wof contract indexedCompletions
  contractValid : ValidInstance contract
  realizationNonempty : indexedCompletions.Nonempty
  semanticRealization :
    Realization contract generatedLanguage indexedCompletions
  targetWellFormed : target.WellFormed
  fullTargetLift : FullTargetLift slice

def rootSpecification
    [DecidableEq Outcome] [DecidableEq Label]
    (slice : RegisteredSlice Outcome Label) (seed : NamespaceSeed)
    (valid : slice.Valid) :
    CutSpecification (Outcome := Outcome) (Label := Label) where
  slice := slice
  seed := seed
  source := none
  target := initialHistory slice seed
  request := rootRequest seed
  origin := .root ⟨rfl, valid⟩
  durableReceiptCells := []
  contract := contractAt slice []
  contract_eq := rfl
  allocation :=
    allocateBundle seed slice.schemaVersion slice.viewVersion
      (rootRequest seed)
  allocation_eq := rfl
  indexedCompletions := greatestPostfixed (contractAt slice [])
  generatedLanguage :=
    Wof (contractAt slice []) (greatestPostfixed (contractAt slice []))
  indexed_eq := rfl
  language_eq := rfl
  contractValid := valid.contractValid
  realizationNonempty := valid.greatestNonempty
  semanticRealization :=
    (greatestPostfixed_is_realization_iff_nonempty
      (contractAt slice []) valid.contractValid).2 valid.greatestNonempty
  targetWellFormed := initialHistory_wellFormed slice seed
  fullTargetLift := valid.fullTargetLift

theorem nonRootCut_hasLiveDerivation
    [DecidableEq Outcome] [DecidableEq Label]
    (specification : CutSpecification (Outcome := Outcome) (Label := Label))
    {source : History} (nonRoot : specification.source = some source) :
    (∃ request,
      HistoryDerivation source request specification.target) ∨
    (∃ sourceSlice request,
      LiveExtensionDerivation sourceSlice specification.slice source request
        specification.target) := by
  have origin := specification.origin
  rw [nonRoot] at origin
  cases origin with
  | edit derivation => exact Or.inl ⟨_, derivation⟩
  | extension derivation => exact Or.inr ⟨_, _, derivation⟩

structure OutcomeLineageAndHandoff
    (source target : History) : Prop where
  progressPreserved : target.progress = source.progress
  checkpointsPreserved : target.checkpoints = source.checkpoints
  versionAdvanced : target.version = source.version.next
  durableCellsPreserved :
    target.progress.map (·.event.cell) =
      source.progress.map (·.event.cell)
  inheritedProgress :
    ∀ progress ∈ source.progress, progress ∈ target.progress

theorem historyDerivation_preserves_outcomes_lineage_and_handoff
    {source target : History} {request : EditRequest}
    (derivation : HistoryDerivation source request target) :
    OutcomeLineageAndHandoff source target := by
  have progress :=
    historyDerivation_preserves_global_progress derivation
  constructor
  · exact progress
  · cases derivation <;> rfl
  · cases derivation <;> rfl
  · exact congrArg (List.map fun item => item.event.cell) progress
  · intro item member
    simpa [progress] using member

theorem liveExtensionDerivation_preserves_outcomes_lineage_and_handoff
    {sourceSlice targetSlice : RegisteredSlice Outcome Label}
    {source target : History} {request : RequestId}
    (derivation :
      LiveExtensionDerivation sourceSlice targetSlice source request target) :
    OutcomeLineageAndHandoff source target := by
  cases derivation with
  | mk staticExtends target_eq =>
      subst target
      constructor
      · rfl
      · rfl
      · rfl
      · rfl
      · intro progress member
        exact member

/-! ## Certificates, monitors, runtime rows, and AgentSec -/

structure CutKey where
  sourceVersion : Option Version
  targetVersion : Version
  schemaVersion : Version
  viewVersion : Version
  epoch : RuntimeName
  durableReceiptCells : List Cell
deriving DecidableEq, Repr

def CutSpecification.key
    [DecidableEq Outcome] [DecidableEq Label]
    (specification : CutSpecification (Outcome := Outcome) (Label := Label)) :
    CutKey where
  sourceVersion := specification.source.map (·.version)
  targetVersion := specification.target.version
  schemaVersion := specification.slice.schemaVersion
  viewVersion := specification.slice.viewVersion
  epoch := specification.allocation.epoch
  durableReceiptCells := specification.durableReceiptCells

structure Certificate (Outcome : Type uOutcome) where
  name : RuntimeName
  sourceKey : CutKey
  retained : Finset (Completion Outcome Occurrence Cell)
deriving DecidableEq

def certificateFor
    [DecidableEq Outcome] [DecidableEq Label]
    (specification : CutSpecification (Outcome := Outcome) (Label := Label)) :
    Certificate Outcome where
  name := specification.allocation.certificate
  sourceKey := specification.key
  retained := specification.indexedCompletions

def verifyCertificate
    [DecidableEq Outcome] [DecidableEq Label]
    (specification : CutSpecification (Outcome := Outcome) (Label := Label))
    (certificate : Certificate Outcome) : Prop :=
  certificate = certificateFor specification

structure MonitorProgram (Outcome : Type uOutcome) where
  sourceKey : CutKey
  language : Finset (List Event)
  indexed : Finset (Completion Outcome Occurrence Cell)
deriving DecidableEq

def canonicalMonitor
    [DecidableEq Outcome] [DecidableEq Label]
    (specification : CutSpecification (Outcome := Outcome) (Label := Label)) :
    MonitorProgram Outcome where
  sourceKey := specification.key
  language := specification.generatedLanguage
  indexed := specification.indexedCompletions

def ProgramIsomorphic (left right : MonitorProgram Outcome) : Prop :=
  left.sourceKey = right.sourceKey ∧
    left.language = right.language ∧ left.indexed = right.indexed

structure Receipt where
  cell : Cell
  creator : BranchName
  invocation : Nat
  future : RuntimeName
deriving DecidableEq, Repr

structure ResultRow where
  cell : Cell
  future : RuntimeName
  value : Nat
deriving DecidableEq, Repr

structure Binding where
  branch : BranchName
  occurrence : Occurrence
  epoch : RuntimeName
  authenticated : Bool
deriving DecidableEq, Repr

def canonicalBindings (history : History) (epoch : RuntimeName) :
    List Binding :=
  history.frontier.branches.flatMap fun branch =>
    branch.residual.map fun occurrence =>
      ⟨branch.name, occurrence, epoch, true⟩

structure UseToken where
  epoch : RuntimeName
  gate : RuntimeName
  handle : RuntimeName
  branch : BranchName
  occurrence : Occurrence
  cell : Cell
  invocation : Nat
deriving DecidableEq, Repr

structure SaveToken where
  epoch : RuntimeName
  gate : RuntimeName
  branch : BranchName
deriving DecidableEq, Repr

structure HandleBundle where
  epoch : RuntimeName
  gate : RuntimeName
  handle : RuntimeName
deriving DecidableEq, Repr

structure AuditLog where
  preloaded : List CutKey := []
  retries : List (Cell × Nat) := []
  retrievedBundles : List HandleBundle := []
  delivered : List Cell := []
  denials : List UseToken := []
  failedInstalls : Nat := 0
  crashes : Nat := 0
deriving DecidableEq, Repr

inductive RuntimeAvailability where
  | running
  | recovering
deriving DecidableEq, Repr

structure InstalledState
    [DecidableEq Outcome] [DecidableEq Label] where
  specification : CutSpecification (Outcome := Outcome) (Label := Label)
  history : History
  trace : List Event
  receipts : List Receipt
  outboxPrepared : List Cell
  outboxReleased : List Cell
  settled : List Cell
  results : List ResultRow
  saveLog : List Checkpoint
  authorityHistory : List Label
  certificate : Certificate Outcome
  program : MonitorProgram Outcome
  monitorState : List Event
  activeEpoch : RuntimeName
  activeEpochs : Finset RuntimeName
  closedEpochs : Finset RuntimeName
  bindings : List Binding
  handles : List HandleBundle
  audit : AuditLog
  availability : RuntimeAvailability

def saveHistory (history : History) (checkpoint : Checkpoint) : History where
  version := history.version.next
  frontier := history.frontier
  checkpoints := history.checkpoints ++ [checkpoint]
  progress := history.progress

inductive HistoryRun : History → List Event → History → Prop
  | nil (history) : HistoryRun history [] history
  | use {initial tracePrefix middle event target post}
      (run : HistoryRun initial tracePrefix middle)
      (step : HStep middle target event post) :
      HistoryRun initial (tracePrefix ++ [event]) post
  | save {initial trace current checkpoint}
      (run : HistoryRun initial trace current) :
      HistoryRun initial trace (saveHistory current checkpoint)

def CheckedCutOrigin
    [DecidableEq Outcome] [DecidableEq Label]
    (specification : CutSpecification (Outcome := Outcome) (Label := Label)) :
    Prop :=
  (specification.source = none ∧
    Nonempty
      (InitialDerivation specification.slice specification.seed
        specification.target)) ∨
  (∃ source request,
      specification.source = some source ∧
        HistoryDerivation source request specification.target) ∨
  ∃ sourceSlice source request,
    specification.source = some source ∧
      LiveExtensionDerivation sourceSlice specification.slice source request
        specification.target

theorem checkedCutOrigin_of_origin
    [DecidableEq Outcome] [DecidableEq Label]
    {slice : RegisteredSlice Outcome Label} {seed : NamespaceSeed}
    {source : Option History} {target : History}
    (origin : CutOrigin slice seed source target) :
    (source = none ∧
      Nonempty (InitialDerivation slice seed target)) ∨
    (∃ history request,
        source = some history ∧
          HistoryDerivation history request target) ∨
    ∃ sourceSlice history request,
      source = some history ∧
        LiveExtensionDerivation sourceSlice slice history request target := by
  cases origin with
  | root derivation =>
      exact Or.inl ⟨rfl, ⟨derivation⟩⟩
  | edit derivation =>
      exact Or.inr (Or.inl ⟨_, _, rfl, derivation⟩)
  | extension derivation =>
      exact Or.inr (Or.inr ⟨_, _, _, rfl, derivation⟩)

theorem cutOrigin_checked
    [DecidableEq Outcome] [DecidableEq Label]
    (specification : CutSpecification (Outcome := Outcome) (Label := Label)) :
    CheckedCutOrigin specification := by
  exact checkedCutOrigin_of_origin specification.origin

def CoreSchemaCoherence
    [DecidableEq Outcome] [DecidableEq Label]
    (state : InstalledState (Outcome := Outcome) (Label := Label)) : Prop :=
  state.history.WellFormed ∧
    verifyCertificate state.specification state.certificate ∧
    CheckedCutOrigin state.specification ∧
    FullTargetLift state.specification.slice

def PromiseCoherence
    [DecidableEq Outcome] [DecidableEq Label]
    (state : InstalledState (Outcome := Outcome) (Label := Label)) : Prop :=
  state.specification.indexedCompletions =
      greatestPostfixed state.specification.contract ∧
    state.specification.indexedCompletions.Nonempty ∧
    state.specification.generatedLanguage =
      Wof state.specification.contract
        state.specification.indexedCompletions ∧
    verifyCertificate state.specification state.certificate

def ResultFuturesStable
    (receipts : List Receipt) (settled : List Cell)
    (results : List ResultRow) : Prop :=
  results.map (·.cell) = settled ∧
    (results.map (·.cell)).Nodup ∧
    ∀ result ∈ results,
      ∃ receipt ∈ receipts,
        receipt.cell = result.cell ∧ receipt.future = result.future

def ExecutionCoherence
    [DecidableEq Outcome] [DecidableEq Label]
    (state : InstalledState (Outcome := Outcome) (Label := Label)) : Prop :=
  HistoryRun state.specification.target state.trace state.history ∧
    state.trace =
      resolveFrom state.specification.contract.cellOf
        state.specification.contract.initialReceipted
        (raw state.trace) ∧
    state.receipts.map (·.cell) =
      state.specification.durableReceiptCells ++ freshCells state.trace ∧
    (state.receipts.map (·.cell)).Nodup ∧
    state.outboxPrepared = state.receipts.map (·.cell) ∧
    state.outboxReleased <+: state.outboxPrepared ∧
    state.settled <+: state.outboxReleased ∧
    ResultFuturesStable state.receipts state.settled state.results ∧
    state.authorityHistory =
      state.specification.contract.durablePrefix ++
        authorityWord state.specification.contract state.trace ∧
    state.history.checkpoints =
      state.specification.target.checkpoints ++ state.saveLog

def MonitorCoherence
    [DecidableEq Outcome] [DecidableEq Label]
    (state : InstalledState (Outcome := Outcome) (Label := Label)) : Prop :=
  ProgramIsomorphic state.program
      (canonicalMonitor state.specification) ∧
    state.monitorState = state.trace ∧
    state.trace ∈ state.program.language

def EpochCoherence
    [DecidableEq Outcome] [DecidableEq Label]
    (state : InstalledState (Outcome := Outcome) (Label := Label)) : Prop :=
  state.activeEpochs = {state.activeEpoch} ∧
    state.activeEpoch ∉ state.closedEpochs ∧
    state.bindings = canonicalBindings state.history state.activeEpoch ∧
    (∀ binding ∈ state.bindings,
      binding.authenticated = true ∧
        binding.epoch = state.activeEpoch) ∧
    (∀ handle ∈ state.handles, handle.epoch = state.activeEpoch)

structure AgentSec
    [DecidableEq Outcome] [DecidableEq Label]
    (state : InstalledState (Outcome := Outcome) (Label := Label)) : Prop where
  core_schema : CoreSchemaCoherence state
  promise : PromiseCoherence state
  execution : ExecutionCoherence state
  monitor : MonitorCoherence state
  epoch : EpochCoherence state

theorem empty_mem_Wof_of_nonempty
    [DecidableEq Outcome] [DecidableEq Label]
    (input : Contract Outcome Label)
    {family : Finset (Completion Outcome Occurrence Cell)}
    (nonempty : family.Nonempty) :
    [] ∈ Wof input family := by
  obtain ⟨completion, member⟩ := nonempty
  exact (mem_Wof_iff input family []).2
    ⟨completion, member, isPrefix_mem_prefixes (by simp)⟩

def initialInstalled
    [DecidableEq Outcome] [DecidableEq Label]
    (slice : RegisteredSlice Outcome Label) (seed : NamespaceSeed)
    (valid : slice.Valid) :
    InstalledState (Outcome := Outcome) (Label := Label) :=
  let specification := rootSpecification slice seed valid
  {
    specification := specification
    history := specification.target
    trace := []
    receipts := []
    outboxPrepared := []
    outboxReleased := []
    settled := []
    results := []
    saveLog := []
    authorityHistory := []
    certificate := certificateFor specification
    program := canonicalMonitor specification
    monitorState := []
    activeEpoch := specification.allocation.epoch
    activeEpochs := {specification.allocation.epoch}
    closedEpochs := ∅
    bindings :=
      canonicalBindings specification.target specification.allocation.epoch
    handles := []
    audit := {}
    availability := .running
  }

theorem initialize_rootCut
    [DecidableEq Outcome] [DecidableEq Label]
    (slice : RegisteredSlice Outcome Label) (seed : NamespaceSeed)
    (valid : slice.Valid) :
    ∃ derivation : InitialDerivation slice seed
        (initialInstalled slice seed valid).specification.target,
      (initialInstalled slice seed valid).specification.origin =
        CutOrigin.root derivation := by
  dsimp only [initialInstalled]
  refine ⟨⟨rfl, valid⟩, ?_⟩
  rfl

theorem initialize_agentSec
    [DecidableEq Outcome] [DecidableEq Label]
    (slice : RegisteredSlice Outcome Label) (seed : NamespaceSeed)
    (valid : slice.Valid) :
    AgentSec (initialInstalled slice seed valid) := by
  dsimp only [initialInstalled]
  let specification := rootSpecification slice seed valid
  have emptyLanguage :
      [] ∈ specification.generatedLanguage := by
    rw [specification.language_eq]
    exact empty_mem_Wof_of_nonempty specification.contract
      specification.realizationNonempty
  constructor
  · refine ⟨specification.targetWellFormed, rfl,
      cutOrigin_checked specification, ?_⟩
    · exact specification.fullTargetLift
  · exact ⟨specification.indexed_eq,
      specification.realizationNonempty, specification.language_eq, rfl⟩
  · refine ⟨.nil _, ?_, ?_, by simp, rfl, by simp, by simp,
      ?_, ?_, by simp⟩
    · simp [resolveFrom, raw]
    · simp [rootSpecification, freshCells]
    · simp [ResultFuturesStable]
    · simp [rootSpecification, contractAt,
        Instance.durablePrefix, authorityWord]
  · exact ⟨⟨rfl, rfl, rfl⟩, rfl, emptyLanguage⟩
  · refine ⟨rfl, by simp, rfl, ?_, by simp⟩
    intro binding member
    simp only [canonicalBindings, List.mem_flatMap, List.mem_map] at member
    obtain ⟨branch, _, occurrence, _, rfl⟩ := member
    exact ⟨rfl, rfl⟩

/-! ## Bootstrap is outside the installed kernel -/

inductive BootstrapState (Outcome : Type uOutcome) (Label : Type uLabel) where
  | empty
  | registered (slice : RegisteredSlice Outcome Label)
      (seed : NamespaceSeed)

def genesis : BootstrapState Outcome Label := .empty

inductive SystemState
    [DecidableEq Outcome] [DecidableEq Label] where
  | bootstrap (state : BootstrapState Outcome Label)
  | installed
      (state : InstalledState (Outcome := Outcome) (Label := Label))

inductive BootstrapStep
    [DecidableEq Outcome] [DecidableEq Label] :
    SystemState (Outcome := Outcome) (Label := Label) →
      SystemState (Outcome := Outcome) (Label := Label) → Prop
  | register (slice : RegisteredSlice Outcome Label)
      (seed : NamespaceSeed) :
      BootstrapStep (.bootstrap genesis)
        (.bootstrap (.registered slice seed))
  | initialize (slice : RegisteredSlice Outcome Label)
      (seed : NamespaceSeed) (valid : slice.Valid) :
      BootstrapStep (.bootstrap (.registered slice seed))
        (.installed (initialInstalled slice seed valid))

/-! ## Installed-slice guards and concrete updates -/

def tokenEvent (token : UseToken) (mode : Mode) : Event :=
  ⟨token.occurrence, token.cell, mode⟩

def receiptFor
    [DecidableEq Outcome] [DecidableEq Label]
    (state : InstalledState (Outcome := Outcome) (Label := Label))
    (token : UseToken) : Receipt where
  cell := token.cell
  creator := token.branch
  invocation := token.invocation
  future :=
    allocateRuntime state.specification.seed
      state.specification.slice.schemaVersion
      state.specification.slice.viewVersion
      ⟨token.invocation⟩ .resultFuture

def UseGuard
    [DecidableEq Outcome] [DecidableEq Label]
    (state : InstalledState (Outcome := Outcome) (Label := Label))
    (token : UseToken) : Prop :=
  state.availability = .running ∧
    token.epoch = state.activeEpoch ∧
    token.gate = state.specification.allocation.gate ∧
    token.handle = state.specification.allocation.handle ∧
    token.cell = state.specification.contract.cellOf token.occurrence ∧
    ⟨token.branch, token.occurrence, state.activeEpoch, true⟩ ∈ state.bindings

def SaveGuard
    [DecidableEq Outcome] [DecidableEq Label]
    (state : InstalledState (Outcome := Outcome) (Label := Label))
    (token : SaveToken) : Prop :=
  state.availability = .running ∧
    token.epoch = state.activeEpoch ∧
    token.gate = state.specification.allocation.gate ∧
    token.branch ∈ state.history.frontier.branchNames

def RetryGuard
    [DecidableEq Outcome] [DecidableEq Label]
    (state : InstalledState (Outcome := Outcome) (Label := Label))
    (token : UseToken) : Prop :=
  UseGuard state token ∧
    ∃ receipt ∈ state.receipts,
      receipt.cell = token.cell ∧
        receipt.invocation = token.invocation

def FreshUseGuard
    [DecidableEq Outcome] [DecidableEq Label]
    (state : InstalledState (Outcome := Outcome) (Label := Label))
    (token : UseToken) : Prop :=
  UseGuard state token ∧
    token.cell ∉ state.receipts.map (·.cell) ∧
    state.trace ++ [tokenEvent token .fresh] ∈ state.program.language ∧
    state.trace ++ [tokenEvent token .fresh] =
      resolveFrom state.specification.contract.cellOf
        state.specification.contract.initialReceipted
        (raw (state.trace ++ [tokenEvent token .fresh]))

def AliasUseGuard
    [DecidableEq Outcome] [DecidableEq Label]
    (state : InstalledState (Outcome := Outcome) (Label := Label))
    (token : UseToken) : Prop :=
  RetryGuard state token ∧
    state.trace ++ [tokenEvent token .alias] ∈ state.program.language ∧
    state.trace ++ [tokenEvent token .alias] =
      resolveFrom state.specification.contract.cellOf
        state.specification.contract.initialReceipted
        (raw (state.trace ++ [tokenEvent token .alias]))

def freshUsePost
    [DecidableEq Outcome] [DecidableEq Label]
    (state : InstalledState (Outcome := Outcome) (Label := Label))
    (token : UseToken) (postHistory : History) :
    InstalledState (Outcome := Outcome) (Label := Label) :=
  { state with
    history := postHistory
    trace := state.trace ++ [tokenEvent token .fresh]
    receipts := state.receipts ++ [receiptFor state token]
    outboxPrepared := state.outboxPrepared ++ [token.cell]
    authorityHistory :=
      state.authorityHistory ++
        [state.specification.contract.labelOf token.cell]
    monitorState := state.monitorState ++ [tokenEvent token .fresh]
    bindings := canonicalBindings postHistory state.activeEpoch
  }

def aliasUsePost
    [DecidableEq Outcome] [DecidableEq Label]
    (state : InstalledState (Outcome := Outcome) (Label := Label))
    (token : UseToken) (postHistory : History) :
    InstalledState (Outcome := Outcome) (Label := Label) :=
  { state with
    history := postHistory
    trace := state.trace ++ [tokenEvent token .alias]
    monitorState := state.monitorState ++ [tokenEvent token .alias]
    bindings := canonicalBindings postHistory state.activeEpoch
  }

def savePost
    [DecidableEq Outcome] [DecidableEq Label]
    (state : InstalledState (Outcome := Outcome) (Label := Label))
    (checkpoint : Checkpoint) :
    InstalledState (Outcome := Outcome) (Label := Label) :=
  { state with
    history := saveHistory state.history checkpoint
    saveLog := state.saveLog ++ [checkpoint]
    bindings :=
      canonicalBindings (saveHistory state.history checkpoint)
        state.activeEpoch
  }

structure InstallCandidate
    [DecidableEq Outcome] [DecidableEq Label] where
  capturedHistory : History
  parentEpoch : RuntimeName
  request : EditRequest
  specification :
    CutSpecification (Outcome := Outcome) (Label := Label)
  source_eq : specification.source = some capturedHistory
  derivation :
    HistoryDerivation capturedHistory request specification.target

def InstallCandidate.ValidFor
    [DecidableEq Outcome] [DecidableEq Label]
    (candidate :
      InstallCandidate (Outcome := Outcome) (Label := Label))
    (state : InstalledState (Outcome := Outcome) (Label := Label)) : Prop :=
  candidate.capturedHistory = state.history ∧
    candidate.parentEpoch = state.activeEpoch ∧
    candidate.specification.slice = state.specification.slice ∧
    candidate.specification.seed = state.specification.seed ∧
    candidate.specification.durableReceiptCells =
      state.receipts.map (·.cell) ∧
    candidate.specification.allocation.epoch ≠ state.activeEpoch ∧
    candidate.specification.allocation.epoch ∉ state.activeEpochs ∧
    candidate.specification.allocation.epoch ∉ state.closedEpochs ∧
    (∀ binding ∈ state.bindings,
      binding.epoch ≠ candidate.specification.allocation.epoch) ∧
    state.availability = .running

/-- A separately typed live-extension candidate.  Keeping this distinct from
`InstallCandidate` ensures the six structural edit constructors and their
derivation relation remain unchanged. -/
structure LiveExtensionCandidate
    [DecidableEq Outcome] [DecidableEq Label] where
  capturedHistory : History
  parentEpoch : RuntimeName
  request : RequestId
  sourceSlice : RegisteredSlice Outcome Label
  specification :
    CutSpecification (Outcome := Outcome) (Label := Label)
  request_eq : specification.request = request
  source_eq : specification.source = some capturedHistory
  derivation :
    LiveExtensionDerivation sourceSlice specification.slice capturedHistory
      request specification.target
  origin_eq :
    HEq specification.origin
      (CutOrigin.extension (seed := specification.seed) derivation)

def LiveExtensionCandidate.ValidFor
    [DecidableEq Outcome] [DecidableEq Label]
    (candidate :
      LiveExtensionCandidate (Outcome := Outcome) (Label := Label))
    (state : InstalledState (Outcome := Outcome) (Label := Label)) : Prop :=
  candidate.capturedHistory = state.history ∧
    candidate.parentEpoch = state.activeEpoch ∧
    candidate.sourceSlice = state.specification.slice ∧
    candidate.specification.seed = state.specification.seed ∧
    candidate.specification.durableReceiptCells =
      state.receipts.map (·.cell) ∧
    candidate.specification.allocation.epoch ≠ state.activeEpoch ∧
    candidate.specification.allocation.epoch ∉ state.activeEpochs ∧
    candidate.specification.allocation.epoch ∉ state.closedEpochs ∧
    (∀ binding ∈ state.bindings,
      binding.epoch ≠ candidate.specification.allocation.epoch) ∧
    state.availability = .running

def installPost
    [DecidableEq Outcome] [DecidableEq Label]
    (state : InstalledState (Outcome := Outcome) (Label := Label))
    (candidate :
      InstallCandidate (Outcome := Outcome) (Label := Label)) :
    InstalledState (Outcome := Outcome) (Label := Label) :=
  let specification := candidate.specification
  { state with
    specification := specification
    history := specification.target
    trace := []
    saveLog := []
    authorityHistory := specification.contract.durablePrefix
    certificate := certificateFor specification
    program := canonicalMonitor specification
    monitorState := []
    activeEpoch := specification.allocation.epoch
    activeEpochs := {specification.allocation.epoch}
    closedEpochs := insert state.activeEpoch state.closedEpochs
    bindings :=
      canonicalBindings specification.target specification.allocation.epoch
    handles := []
    availability := .running
  }

/-- Live extension uses exactly the same atomic epoch replacement as a
structural edit, but its specification has an extension origin and an
identity-on-frontier target. -/
def liveExtensionPost
    [DecidableEq Outcome] [DecidableEq Label]
    (state : InstalledState (Outcome := Outcome) (Label := Label))
    (candidate :
      LiveExtensionCandidate (Outcome := Outcome) (Label := Label)) :
    InstalledState (Outcome := Outcome) (Label := Label) :=
  let specification := candidate.specification
  { state with
    specification := specification
    history := specification.target
    trace := []
    saveLog := []
    authorityHistory := specification.contract.durablePrefix
    certificate := certificateFor specification
    program := canonicalMonitor specification
    monitorState := []
    activeEpoch := specification.allocation.epoch
    activeEpochs := {specification.allocation.epoch}
    closedEpochs := insert state.activeEpoch state.closedEpochs
    bindings :=
      canonicalBindings specification.target specification.allocation.epoch
    handles := []
    availability := .running
  }

def preloadPost
    [DecidableEq Outcome] [DecidableEq Label]
    (state : InstalledState (Outcome := Outcome) (Label := Label))
    (candidate :
      InstallCandidate (Outcome := Outcome) (Label := Label)) :
    InstalledState (Outcome := Outcome) (Label := Label) :=
  { state with
    audit := { state.audit with
      preloaded := state.audit.preloaded ++ [candidate.specification.key] }
  }

def retryPost
    [DecidableEq Outcome] [DecidableEq Label]
    (state : InstalledState (Outcome := Outcome) (Label := Label))
    (token : UseToken) :
    InstalledState (Outcome := Outcome) (Label := Label) :=
  { state with
    audit := { state.audit with
      retries := state.audit.retries ++ [(token.cell, token.invocation)] }
  }

def currentBundle
    [DecidableEq Outcome] [DecidableEq Label]
    (state : InstalledState (Outcome := Outcome) (Label := Label)) :
    HandleBundle :=
  ⟨state.activeEpoch, state.specification.allocation.gate,
    state.specification.allocation.handle⟩

def retrieveBundlePost
    [DecidableEq Outcome] [DecidableEq Label]
    (state : InstalledState (Outcome := Outcome) (Label := Label)) :
    InstalledState (Outcome := Outcome) (Label := Label) :=
  { state with
    handles := state.handles ++ [currentBundle state]
    audit := { state.audit with
      retrievedBundles :=
        state.audit.retrievedBundles ++ [currentBundle state] }
  }

def deliverPost
    [DecidableEq Outcome] [DecidableEq Label]
    (state : InstalledState (Outcome := Outcome) (Label := Label))
    (cell : Cell) :
    InstalledState (Outcome := Outcome) (Label := Label) :=
  { state with
    audit := { state.audit with
      delivered := state.audit.delivered ++ [cell] }
  }

def denialPost
    [DecidableEq Outcome] [DecidableEq Label]
    (state : InstalledState (Outcome := Outcome) (Label := Label))
    (token : UseToken) :
    InstalledState (Outcome := Outcome) (Label := Label) :=
  { state with
    audit := { state.audit with
      denials := state.audit.denials ++ [token] }
  }

def dispatchPost
    [DecidableEq Outcome] [DecidableEq Label]
    (state : InstalledState (Outcome := Outcome) (Label := Label))
    (cell : Cell) :
    InstalledState (Outcome := Outcome) (Label := Label) :=
  { state with outboxReleased := state.outboxReleased ++ [cell] }

def settlementPost
    [DecidableEq Outcome] [DecidableEq Label]
    (state : InstalledState (Outcome := Outcome) (Label := Label))
    (result : ResultRow) :
    InstalledState (Outcome := Outcome) (Label := Label) :=
  { state with
    settled := state.settled ++ [result.cell]
    results := state.results ++ [result]
  }

def failedInstallPost
    [DecidableEq Outcome] [DecidableEq Label]
    (state : InstalledState (Outcome := Outcome) (Label := Label)) :
    InstalledState (Outcome := Outcome) (Label := Label) :=
  { state with
    audit := { state.audit with
      failedInstalls := state.audit.failedInstalls + 1 }
  }

def crashPost
    [DecidableEq Outcome] [DecidableEq Label]
    (state : InstalledState (Outcome := Outcome) (Label := Label)) :
    InstalledState (Outcome := Outcome) (Label := Label) :=
  { state with
    audit := { state.audit with crashes := state.audit.crashes + 1 }
    availability := .recovering
  }

def recoveryPost
    [DecidableEq Outcome] [DecidableEq Label]
    (state : InstalledState (Outcome := Outcome) (Label := Label)) :
    InstalledState (Outcome := Outcome) (Label := Label) :=
  { state with availability := .running }

/-! ## Preservation lemmas for primitive updates -/

theorem canonicalBindings_authenticated
    (history : History) (epoch : RuntimeName) :
    ∀ binding ∈ canonicalBindings history epoch,
      binding.authenticated = true ∧ binding.epoch = epoch := by
  intro binding member
  simp only [canonicalBindings, List.mem_flatMap, List.mem_map] at member
  obtain ⟨branch, _, occurrence, _, rfl⟩ := member
  exact ⟨rfl, rfl⟩

theorem saveHistory_wellFormed {history : History}
    (wellFormed : history.WellFormed) (checkpoint : Checkpoint) :
    (saveHistory history checkpoint).WellFormed := by
  constructor
  · intro branch member
    have bound := wellFormed.branchVersionBound branch member
    simp only [saveHistory, Version.next_value]
    omega
  · intro group member
    have bound := wellFormed.groupVersionBound group member
    simp only [saveHistory, Version.next_value]
    omega
  · intro progress member
    have bound := wellFormed.progressVersionBound progress member
    simp only [saveHistory, Version.next_value]
    omega
  · exact wellFormed.branchResiduals
  · exact wellFormed.cursorFromGlobal

theorem freshUsePost_agentSec
    [DecidableEq Outcome] [DecidableEq Label]
    {state : InstalledState (Outcome := Outcome) (Label := Label)}
    {token : UseToken} {postHistory : History}
    (secure : AgentSec state)
    (guard : FreshUseGuard state token)
    (step :
      HStep state.history token.branch (tokenEvent token .fresh) postHistory)
    (postWellFormed : postHistory.WellFormed) :
    AgentSec (freshUsePost state token postHistory) := by
  rcases secure with ⟨core, promise, execution, monitor, epoch⟩
  rcases core with ⟨historyWF, certificate, origin, lift⟩
  rcases execution with
    ⟨run, resolved, receiptCells, receiptNodup, prepared,
      releasePrefix, settledPrefix, futures, authority, saves⟩
  rcases monitor with ⟨program, monitorState, allowed⟩
  rcases epoch with
    ⟨activeSingleton, activeOpen, bindings, bindingAuth, handles⟩
  rcases guard with
    ⟨useGuard, unseen, nextAllowed, nextResolved⟩
  constructor
  · exact ⟨postWellFormed, certificate, origin, lift⟩
  · exact promise
  · refine ⟨.use run step, nextResolved, ?_, ?_, ?_, ?_, settledPrefix,
      ?_, ?_, ?_⟩
    · simpa [freshUsePost, receiptFor, tokenEvent, freshCells,
        receiptCells, List.append_assoc]
    · have appended :=
        List.Nodup.concat unseen receiptNodup
      simpa [freshUsePost, receiptFor, List.concat_eq_append] using appended
    · simp [freshUsePost, prepared, receiptFor]
    · exact releasePrefix.trans
        (List.prefix_append state.outboxPrepared [token.cell])
    · rcases futures with ⟨resultCells, resultNodup, stable⟩
      refine ⟨resultCells, resultNodup, ?_⟩
      intro result member
      obtain ⟨receipt, receiptMember, cell, future⟩ :=
        stable result member
      exact ⟨receipt, by simp [freshUsePost, receiptMember], cell, future⟩
    · rw [freshUsePost, authority, authorityWord_append]
      simp [authorityWord, tokenEvent]
    · cases step
      simpa [freshUsePost, protectedPost, saves, List.append_assoc]
  · refine ⟨program, ?_, ?_⟩
    · simp [freshUsePost, monitorState]
    · exact nextAllowed
  · refine ⟨activeSingleton, activeOpen, rfl,
      canonicalBindings_authenticated _ _, ?_⟩
    intro handle member
    exact handles handle (by simpa [freshUsePost] using member)

theorem aliasUsePost_agentSec
    [DecidableEq Outcome] [DecidableEq Label]
    {state : InstalledState (Outcome := Outcome) (Label := Label)}
    {token : UseToken} {postHistory : History}
    (secure : AgentSec state)
    (guard : AliasUseGuard state token)
    (step :
      HStep state.history token.branch (tokenEvent token .alias) postHistory)
    (postWellFormed : postHistory.WellFormed) :
    AgentSec (aliasUsePost state token postHistory) := by
  rcases secure with ⟨core, promise, execution, monitor, epoch⟩
  rcases core with ⟨historyWF, certificate, origin, lift⟩
  rcases execution with
    ⟨run, resolved, receiptCells, receiptNodup, prepared,
      releasePrefix, settledPrefix, futures, authority, saves⟩
  rcases monitor with ⟨program, monitorState, allowed⟩
  rcases epoch with
    ⟨activeSingleton, activeOpen, bindings, bindingAuth, handles⟩
  rcases guard with ⟨retryGuard, nextAllowed, nextResolved⟩
  constructor
  · exact ⟨postWellFormed, certificate, origin, lift⟩
  · exact promise
  · refine ⟨.use run step, nextResolved, ?_, receiptNodup, prepared,
      releasePrefix, settledPrefix, futures, ?_, ?_⟩
    · simpa [aliasUsePost, tokenEvent, freshCells, List.append_assoc]
        using receiptCells
    · rw [aliasUsePost, authority, authorityWord_append]
      simp [authorityWord, tokenEvent]
    · cases step
      simpa [aliasUsePost, protectedPost, saves]
  · exact ⟨program, by simp [aliasUsePost, monitorState], nextAllowed⟩
  · refine ⟨activeSingleton, activeOpen, rfl,
      canonicalBindings_authenticated _ _, ?_⟩
    intro handle member
    exact handles handle (by simpa [aliasUsePost] using member)

theorem savePost_agentSec
    [DecidableEq Outcome] [DecidableEq Label]
    {state : InstalledState (Outcome := Outcome) (Label := Label)}
    (secure : AgentSec state) (checkpoint : Checkpoint) :
    AgentSec (savePost state checkpoint) := by
  rcases secure with ⟨core, promise, execution, monitor, epoch⟩
  rcases core with ⟨historyWF, certificate, origin, lift⟩
  rcases execution with
    ⟨run, resolved, receiptCells, receiptNodup, prepared,
      releasePrefix, settledPrefix, futures, authority, saves⟩
  rcases epoch with
    ⟨activeSingleton, activeOpen, bindings, bindingAuth, handles⟩
  constructor
  · exact ⟨saveHistory_wellFormed historyWF checkpoint,
      certificate, origin, lift⟩
  · exact promise
  · refine ⟨.save run, resolved, receiptCells, receiptNodup, prepared,
      releasePrefix, settledPrefix, futures, authority, ?_⟩
    simp [savePost, saveHistory, saves, List.append_assoc]
  · exact monitor
  · refine ⟨activeSingleton, activeOpen, rfl,
      canonicalBindings_authenticated _ _, ?_⟩
    intro handle member
    exact handles handle (by simpa [savePost] using member)

theorem installPost_agentSec
    [DecidableEq Outcome] [DecidableEq Label]
    {state : InstalledState (Outcome := Outcome) (Label := Label)}
    {candidate :
      InstallCandidate (Outcome := Outcome) (Label := Label)}
    (secure : AgentSec state) (valid : candidate.ValidFor state) :
    AgentSec (installPost state candidate) := by
  rcases secure with ⟨core, promise, execution, monitor, epoch⟩
  rcases execution with
    ⟨run, resolved, receiptCells, receiptNodup, prepared,
      releasePrefix, settledPrefix, futures, authority, saves⟩
  rcases valid with
    ⟨captured, parent, sameSlice, sameSeed, durable, newEpoch,
      inactive, notClosed, unbound, running⟩
  let specification := candidate.specification
  have emptyLanguage :
      [] ∈ specification.generatedLanguage := by
    rw [specification.language_eq]
    exact empty_mem_Wof_of_nonempty specification.contract
      specification.realizationNonempty
  constructor
  · exact ⟨specification.targetWellFormed, rfl,
      cutOrigin_checked specification, specification.fullTargetLift⟩
  · exact ⟨specification.indexed_eq,
      specification.realizationNonempty, specification.language_eq, rfl⟩
  · refine ⟨.nil _, ?_, ?_, receiptNodup,
      prepared, releasePrefix, settledPrefix, futures, ?_, ?_⟩
    · simp [installPost, resolveFrom, raw]
    · change
        state.receipts.map (·.cell) =
          candidate.specification.durableReceiptCells ++ freshCells []
      simpa [freshCells] using durable.symm
    · simp [installPost, authorityWord]
    · simp [installPost]
  · exact ⟨⟨rfl, rfl, rfl⟩, rfl, emptyLanguage⟩
  · refine ⟨rfl, ?_, rfl, canonicalBindings_authenticated _ _, ?_⟩
    · change
        candidate.specification.allocation.epoch ∉
          insert state.activeEpoch state.closedEpochs
      simp only [Finset.mem_insert, not_or]
      exact ⟨newEpoch, notClosed⟩
    · intro handle member
      exact (by simpa [installPost] using member : False).elim

theorem liveExtensionPost_agentSec
    [DecidableEq Outcome] [DecidableEq Label]
    {state : InstalledState (Outcome := Outcome) (Label := Label)}
    {candidate :
      LiveExtensionCandidate (Outcome := Outcome) (Label := Label)}
    (secure : AgentSec state) (valid : candidate.ValidFor state) :
    AgentSec (liveExtensionPost state candidate) := by
  rcases secure with ⟨core, promise, execution, monitor, epoch⟩
  rcases execution with
    ⟨run, resolved, receiptCells, receiptNodup, prepared,
      releasePrefix, settledPrefix, futures, authority, saves⟩
  rcases valid with
    ⟨captured, parent, sourceSlice, sameSeed, durable, newEpoch,
      inactive, notClosed, unbound, running⟩
  let specification := candidate.specification
  have emptyLanguage :
      [] ∈ specification.generatedLanguage := by
    rw [specification.language_eq]
    exact empty_mem_Wof_of_nonempty specification.contract
      specification.realizationNonempty
  constructor
  · exact ⟨specification.targetWellFormed, rfl,
      cutOrigin_checked specification, specification.fullTargetLift⟩
  · exact ⟨specification.indexed_eq,
      specification.realizationNonempty, specification.language_eq, rfl⟩
  · refine ⟨.nil _, ?_, ?_, receiptNodup,
      prepared, releasePrefix, settledPrefix, futures, ?_, ?_⟩
    · simp [liveExtensionPost, resolveFrom, raw]
    · change
        state.receipts.map (·.cell) =
          candidate.specification.durableReceiptCells ++ freshCells []
      simpa [freshCells] using durable.symm
    · simp [liveExtensionPost, authorityWord]
    · simp [liveExtensionPost]
  · exact ⟨⟨rfl, rfl, rfl⟩, rfl, emptyLanguage⟩
  · refine ⟨rfl, ?_, rfl, canonicalBindings_authenticated _ _, ?_⟩
    · change
        candidate.specification.allocation.epoch ∉
          insert state.activeEpoch state.closedEpochs
      simp only [Finset.mem_insert, not_or]
      exact ⟨newEpoch, notClosed⟩
    · intro handle member
      exact (by simpa [liveExtensionPost] using member : False).elim

theorem dispatchPost_agentSec
    [DecidableEq Outcome] [DecidableEq Label]
    {state : InstalledState (Outcome := Outcome) (Label := Label)}
    (secure : AgentSec state) (cell : Cell) (tail : List Cell)
    (next :
      state.outboxPrepared = state.outboxReleased ++ cell :: tail) :
    AgentSec (dispatchPost state cell) := by
  rcases secure with ⟨core, promise, execution, monitor, epoch⟩
  rcases execution with
    ⟨run, resolved, receipts, nodup, prepared, released, settled,
      futures, authority, saves⟩
  constructor
  · exact core
  · exact promise
  · refine ⟨run, resolved, receipts, nodup, prepared, ?_, ?_, futures,
      authority, saves⟩
    · rw [dispatchPost, next]
      exact ⟨tail, by simp [List.append_assoc]⟩
    · exact settled.trans (List.prefix_append _ [cell])
  · exact monitor
  · exact epoch

theorem settlementPost_agentSec
    [DecidableEq Outcome] [DecidableEq Label]
    {state : InstalledState (Outcome := Outcome) (Label := Label)}
    (secure : AgentSec state) (result : ResultRow) (tail : List Cell)
    (next :
      state.outboxReleased = state.settled ++ result.cell :: tail)
    (freshResult : result.cell ∉ state.settled)
    (receiptMatch :
      ∃ receipt ∈ state.receipts,
        receipt.cell = result.cell ∧ receipt.future = result.future) :
    AgentSec (settlementPost state result) := by
  rcases secure with ⟨core, promise, execution, monitor, epoch⟩
  rcases execution with
    ⟨run, resolved, receipts, receiptNodup, prepared, released, settled,
      futures, authority, saves⟩
  rcases futures with ⟨resultCells, resultNodup, stable⟩
  constructor
  · exact core
  · exact promise
  · refine ⟨run, resolved, receipts, receiptNodup, prepared, released,
      ?_, ?_, authority, saves⟩
    · rw [settlementPost, next]
      exact ⟨tail, by simp [List.append_assoc]⟩
    · refine ⟨?_, ?_, ?_⟩
      · simpa [settlementPost, resultCells]
      ·
        have settledNodup : state.settled.Nodup := by
          rw [← resultCells]
          exact resultNodup
        have appended :=
          List.Nodup.concat freshResult settledNodup
        simpa [settlementPost, List.concat_eq_append, resultCells] using
          appended
      · intro candidate member
        simp only [settlementPost, List.mem_append, List.mem_singleton]
          at member
        rcases member with old | rfl
        · exact stable candidate old
        · exact receiptMatch
  · exact monitor
  · exact epoch

theorem retrieveBundlePost_agentSec
    [DecidableEq Outcome] [DecidableEq Label]
    {state : InstalledState (Outcome := Outcome) (Label := Label)}
    (secure : AgentSec state) :
    AgentSec (retrieveBundlePost state) := by
  rcases secure with ⟨core, promise, execution, monitor, epoch⟩
  rcases epoch with
    ⟨activeSingleton, activeOpen, bindings, bindingAuth, handles⟩
  refine ⟨core, promise, execution, monitor,
    activeSingleton, activeOpen, bindings, bindingAuth, ?_⟩
  intro handle member
  simp only [retrieveBundlePost, List.mem_append, List.mem_singleton]
    at member
  rcases member with old | rfl
  · exact handles handle old
  · rfl

theorem metadataUpdate_agentSec
    [DecidableEq Outcome] [DecidableEq Label]
    {state : InstalledState (Outcome := Outcome) (Label := Label)}
    (secure : AgentSec state) (audit : AuditLog)
    (availability : RuntimeAvailability) :
    AgentSec { state with audit := audit, availability := availability } :=
  ⟨secure.core_schema, secure.promise, secure.execution,
    secure.monitor, secure.epoch⟩

/-! ## Exhaustive installed-slice event relation -/

inductive KernelEvent
    [DecidableEq Outcome] [DecidableEq Label] where
  | freshUse (token : UseToken)
  | aliasUse (token : UseToken)
  | installForkChoice
      (candidate :
        InstallCandidate (Outcome := Outcome) (Label := Label))
  | installForkParallel
      (candidate :
        InstallCandidate (Outcome := Outcome) (Label := Label))
  | installRestoreReplace
      (candidate :
        InstallCandidate (Outcome := Outcome) (Label := Label))
  | installRestoreLive
      (candidate :
        InstallCandidate (Outcome := Outcome) (Label := Label))
  | installMergeSelect
      (candidate :
        InstallCandidate (Outcome := Outcome) (Label := Label))
  | installMergeJoin
      (candidate :
        InstallCandidate (Outcome := Outcome) (Label := Label))
  | installLiveExtension
      (candidate :
        LiveExtensionCandidate (Outcome := Outcome) (Label := Label))
  | save (checkpoint : Checkpoint)
  | preload
      (candidate :
        InstallCandidate (Outcome := Outcome) (Label := Label))
  | authenticatedRetry (token : UseToken)
  | retrieveReplacementHandleBundle
  | resultDelivery (cell : Cell)
  | denial (token : UseToken)
  | dispatch (cell : Cell)
  | settlement (result : ResultRow)
  | failedOrStaleInstallation
      (candidate :
        InstallCandidate (Outcome := Outcome) (Label := Label))
  | failedOrStaleLiveExtension
      (candidate :
        LiveExtensionCandidate (Outcome := Outcome) (Label := Label))
  | crash
  | recovery

inductive KernelStep
    [DecidableEq Outcome] [DecidableEq Label] :
    InstalledState (Outcome := Outcome) (Label := Label) →
      KernelEvent (Outcome := Outcome) (Label := Label) →
      InstalledState (Outcome := Outcome) (Label := Label) → Prop
  | freshUse {state token postHistory}
      (guard : FreshUseGuard state token)
      (historyStep :
        HStep state.history token.branch (tokenEvent token .fresh)
          postHistory)
      (postWellFormed : postHistory.WellFormed) :
      KernelStep state (.freshUse token)
        (freshUsePost state token postHistory)
  | aliasUse {state token postHistory}
      (guard : AliasUseGuard state token)
      (historyStep :
        HStep state.history token.branch (tokenEvent token .alias)
          postHistory)
      (postWellFormed : postHistory.WellFormed) :
      KernelStep state (.aliasUse token)
        (aliasUsePost state token postHistory)
  | installForkChoice
      {state candidate request target leftSuffix rightSuffix}
      (shape :
        candidate.request =
          .forkChoice request target leftSuffix rightSuffix)
      (valid : candidate.ValidFor state) :
      KernelStep state (.installForkChoice candidate)
        (installPost state candidate)
  | installForkParallel
      {state candidate request target leftSuffix rightSuffix}
      (shape :
        candidate.request =
          .forkParallel request target leftSuffix rightSuffix)
      (valid : candidate.ValidFor state) :
      KernelStep state (.installForkParallel candidate)
        (installPost state candidate)
  | installRestoreReplace
      {state candidate request target checkpoint retirementAuthorized}
      (shape :
        candidate.request =
          .restoreReplace request target checkpoint retirementAuthorized)
      (valid : candidate.ValidFor state) :
      KernelStep state (.installRestoreReplace candidate)
        (installPost state candidate)
  | installRestoreLive
      {state candidate request target checkpoint}
      (shape :
        candidate.request =
          .restoreLive request target checkpoint)
      (valid : candidate.ValidFor state) :
      KernelStep state (.installRestoreLive candidate)
        (installPost state candidate)
  | installMergeSelect
      {state candidate request target winner suffix retirementAuthorized}
      (shape :
        candidate.request =
          .mergeSelect request target winner suffix retirementAuthorized)
      (valid : candidate.ValidFor state) :
      KernelStep state (.installMergeSelect candidate)
        (installPost state candidate)
  | installMergeJoin
      {state candidate request target suffix}
      (shape :
        candidate.request = .mergeJoin request target suffix)
      (valid : candidate.ValidFor state) :
      KernelStep state (.installMergeJoin candidate)
        (installPost state candidate)
  | installLiveExtension
      {state candidate}
      (valid : candidate.ValidFor state) :
      KernelStep state (.installLiveExtension candidate)
        (liveExtensionPost state candidate)
  | save {state checkpoint token}
      (authenticated : SaveGuard state token)
      (freshId : state.history.lookupCheckpoint checkpoint.id = none) :
      KernelStep state (.save checkpoint) (savePost state checkpoint)
  | preload {state candidate} :
      KernelStep state (.preload candidate) (preloadPost state candidate)
  | authenticatedRetry {state token}
      (guard : RetryGuard state token) :
      KernelStep state (.authenticatedRetry token) (retryPost state token)
  | retrieveReplacementHandleBundle {state}
      (running : state.availability = .running) :
      KernelStep state .retrieveReplacementHandleBundle
        (retrieveBundlePost state)
  | resultDelivery {state cell}
      (settled :
        ∃ result ∈ state.results, result.cell = cell) :
      KernelStep state (.resultDelivery cell) (deliverPost state cell)
  | denialUse {state token}
      (failed : ¬ UseGuard state token) :
      KernelStep state (.denial token) (denialPost state token)
  | denialRetry {state token}
      (useValid : UseGuard state token)
      (retryFailed : ¬ RetryGuard state token) :
      KernelStep state (.denial token) (denialPost state token)
  | denialFresh {state token}
      (baseValid : UseGuard state token)
      (freshFailed : ¬ FreshUseGuard state token) :
      KernelStep state (.denial token) (denialPost state token)
  | denialAlias {state token}
      (retryValid : RetryGuard state token)
      (aliasFailed : ¬ AliasUseGuard state token) :
      KernelStep state (.denial token) (denialPost state token)
  | dispatch {state cell tail}
      (next :
        state.outboxPrepared = state.outboxReleased ++ cell :: tail) :
      KernelStep state (.dispatch cell) (dispatchPost state cell)
  | settlement {state result tail}
      (next :
        state.outboxReleased = state.settled ++ result.cell :: tail)
      (freshResult : result.cell ∉ state.settled)
      (receiptMatch :
        ∃ receipt ∈ state.receipts,
          receipt.cell = result.cell ∧ receipt.future = result.future) :
      KernelStep state (.settlement result) (settlementPost state result)
  | failedOrStaleInstallation {state candidate}
      (failed : ¬ candidate.ValidFor state) :
      KernelStep state (.failedOrStaleInstallation candidate)
        (failedInstallPost state)
  | failedOrStaleLiveExtension {state candidate}
      (failed : ¬ candidate.ValidFor state) :
      KernelStep state (.failedOrStaleLiveExtension candidate)
        (failedInstallPost state)
  | crash {state} (running : state.availability = .running) :
      KernelStep state .crash (crashPost state)
  | recovery {state} (recovering : state.availability = .recovering) :
      KernelStep state .recovery (recoveryPost state)

theorem kernelStep_preserves_agentSec
    [DecidableEq Outcome] [DecidableEq Label]
    {state post :
      InstalledState (Outcome := Outcome) (Label := Label)}
    {event : KernelEvent (Outcome := Outcome) (Label := Label)}
    (secure : AgentSec state) (step : KernelStep state event post) :
    AgentSec post := by
  cases step with
  | freshUse guard historyStep postWellFormed =>
      exact freshUsePost_agentSec secure guard historyStep postWellFormed
  | aliasUse guard historyStep postWellFormed =>
      exact aliasUsePost_agentSec secure guard historyStep postWellFormed
  | installForkChoice shape valid
  | installForkParallel shape valid
  | installRestoreReplace shape valid
  | installRestoreLive shape valid
  | installMergeSelect shape valid
  | installMergeJoin shape valid =>
      exact installPost_agentSec secure valid
  | installLiveExtension valid =>
      exact liveExtensionPost_agentSec secure valid
  | save authenticated freshId =>
      exact savePost_agentSec secure _
  | preload =>
      apply metadataUpdate_agentSec secure
  | authenticatedRetry guard =>
      apply metadataUpdate_agentSec secure
  | retrieveReplacementHandleBundle running =>
      exact retrieveBundlePost_agentSec secure
  | resultDelivery settled =>
      apply metadataUpdate_agentSec secure
  | denialUse failed
  | denialRetry _ failed
  | denialFresh _ failed
  | denialAlias _ failed =>
      apply metadataUpdate_agentSec secure
  | dispatch next =>
      exact dispatchPost_agentSec secure _ _ next
  | settlement next freshResult receiptMatch =>
      exact settlementPost_agentSec secure _ _ next freshResult receiptMatch
  | failedOrStaleInstallation failed =>
      apply metadataUpdate_agentSec secure
  | failedOrStaleLiveExtension failed =>
      apply metadataUpdate_agentSec secure
  | crash running =>
      apply metadataUpdate_agentSec secure
  | recovery recovering =>
      apply metadataUpdate_agentSec secure

/-- The reflexive-transitive closure of the installed event relation. -/
inductive KernelTrace
    [DecidableEq Outcome] [DecidableEq Label] :
    InstalledState (Outcome := Outcome) (Label := Label) →
      InstalledState (Outcome := Outcome) (Label := Label) → Prop
  | refl (state) : KernelTrace state state
  | tail {initial middle post event}
      (trace : KernelTrace initial middle)
      (step : KernelStep middle event post) :
      KernelTrace initial post

theorem kernelTrace_preserves_agentSec
    [DecidableEq Outcome] [DecidableEq Label]
    {initial post :
      InstalledState (Outcome := Outcome) (Label := Label)}
    (secure : AgentSec initial) (trace : KernelTrace initial post) :
    AgentSec post := by
  induction trace with
  | refl => exact secure
  | tail trace step induction =>
      exact kernelStep_preserves_agentSec induction step

theorem six_edits_closed
    [DecidableEq Outcome] [DecidableEq Label]
    {state : InstalledState (Outcome := Outcome) (Label := Label)}
    (candidate :
      InstallCandidate (Outcome := Outcome) (Label := Label))
    (valid : candidate.ValidFor state) :
    ∃ event, KernelStep state event (installPost state candidate) := by
  cases shape : candidate.request with
  | forkChoice request target leftSuffix rightSuffix =>
      exact ⟨.installForkChoice candidate,
        .installForkChoice shape valid⟩
  | forkParallel request target leftSuffix rightSuffix =>
      exact ⟨.installForkParallel candidate,
        .installForkParallel shape valid⟩
  | restoreReplace request target checkpoint retirementAuthorized =>
      exact ⟨.installRestoreReplace candidate,
        .installRestoreReplace shape valid⟩
  | restoreLive request target checkpoint =>
      exact ⟨.installRestoreLive candidate,
        .installRestoreLive shape valid⟩
  | mergeSelect request target winner suffix retirementAuthorized =>
      exact ⟨.installMergeSelect candidate,
        .installMergeSelect shape valid⟩
  | mergeJoin request target suffix =>
      exact ⟨.installMergeJoin candidate,
        .installMergeJoin shape valid⟩

theorem live_extension_closed
    [DecidableEq Outcome] [DecidableEq Label]
    {state : InstalledState (Outcome := Outcome) (Label := Label)}
    (candidate :
      LiveExtensionCandidate (Outcome := Outcome) (Label := Label))
    (valid : candidate.ValidFor state) :
    KernelStep state (.installLiveExtension candidate)
      (liveExtensionPost state candidate) :=
  .installLiveExtension valid

theorem live_extension_preserves_agentSec
    [DecidableEq Outcome] [DecidableEq Label]
    {state : InstalledState (Outcome := Outcome) (Label := Label)}
    (candidate :
      LiveExtensionCandidate (Outcome := Outcome) (Label := Label))
    (secure : AgentSec state) (valid : candidate.ValidFor state) :
    AgentSec (liveExtensionPost state candidate) :=
  kernelStep_preserves_agentSec secure (.installLiveExtension valid)

/-! ## Linearization races at use/install -/

theorem hStep_version_next {history post : History}
    {target : BranchName} {event : Event}
    (step : HStep history target event post) :
    post.version = history.version.next := by
  cases step
  rfl

theorem hStep_changes_history {history post : History}
    {target : BranchName} {event : Event}
    (step : HStep history target event post) :
    history ≠ post := by
  intro same
  have versionSame :
      history.version.value = post.version.value :=
    congrArg (fun candidate => candidate.version.value) same
  have versionNext := congrArg Version.value (hStep_version_next step)
  simp only [Version.next_value] at versionNext
  omega

theorem fresh_before_install_stale
    [DecidableEq Outcome] [DecidableEq Label]
    {state post :
      InstalledState (Outcome := Outcome) (Label := Label)}
    {token : UseToken}
    {candidate :
      InstallCandidate (Outcome := Outcome) (Label := Label)}
    (use : KernelStep state (.freshUse token) post)
    (captured : candidate.capturedHistory = state.history) :
    ¬ candidate.ValidFor post := by
  intro validAfter
  cases use with
  | freshUse guard historyStep postWellFormed =>
      have sourceEqualsPost :
          state.history =
            (freshUsePost state token _).history :=
        captured.symm.trans validAfter.1
      apply hStep_changes_history historyStep
      simpa [freshUsePost] using sourceEqualsPost

theorem alias_before_install_stale
    [DecidableEq Outcome] [DecidableEq Label]
    {state post :
      InstalledState (Outcome := Outcome) (Label := Label)}
    {token : UseToken}
    {candidate :
      InstallCandidate (Outcome := Outcome) (Label := Label)}
    (use : KernelStep state (.aliasUse token) post)
    (captured : candidate.capturedHistory = state.history) :
    ¬ candidate.ValidFor post := by
  intro validAfter
  cases use with
  | aliasUse guard historyStep postWellFormed =>
      have sourceEqualsPost :
          state.history =
            (aliasUsePost state token _).history :=
        captured.symm.trans validAfter.1
      apply hStep_changes_history historyStep
      simpa [aliasUsePost] using sourceEqualsPost

theorem fresh_before_live_extension_stale
    [DecidableEq Outcome] [DecidableEq Label]
    {state post :
      InstalledState (Outcome := Outcome) (Label := Label)}
    {token : UseToken}
    {candidate :
      LiveExtensionCandidate (Outcome := Outcome) (Label := Label)}
    (use : KernelStep state (.freshUse token) post)
    (captured : candidate.capturedHistory = state.history) :
    ¬ candidate.ValidFor post := by
  intro validAfter
  cases use with
  | freshUse guard historyStep postWellFormed =>
      have sourceEqualsPost :
          state.history =
            (freshUsePost state token _).history :=
        captured.symm.trans validAfter.1
      apply hStep_changes_history historyStep
      simpa [freshUsePost] using sourceEqualsPost

theorem alias_before_live_extension_stale
    [DecidableEq Outcome] [DecidableEq Label]
    {state post :
      InstalledState (Outcome := Outcome) (Label := Label)}
    {token : UseToken}
    {candidate :
      LiveExtensionCandidate (Outcome := Outcome) (Label := Label)}
    (use : KernelStep state (.aliasUse token) post)
    (captured : candidate.capturedHistory = state.history) :
    ¬ candidate.ValidFor post := by
  intro validAfter
  cases use with
  | aliasUse guard historyStep postWellFormed =>
      have sourceEqualsPost :
          state.history =
            (aliasUsePost state token _).history :=
        captured.symm.trans validAfter.1
      apply hStep_changes_history historyStep
      simpa [aliasUsePost] using sourceEqualsPost

theorem install_before_old_use_denied
    [DecidableEq Outcome] [DecidableEq Label]
    {state : InstalledState (Outcome := Outcome) (Label := Label)}
    {candidate :
      InstallCandidate (Outcome := Outcome) (Label := Label)}
    {token : UseToken}
    (valid : candidate.ValidFor state)
    (oldEpoch : token.epoch = state.activeEpoch) :
    ¬ UseGuard (installPost state candidate) token ∧
      KernelStep (installPost state candidate) (.denial token)
        (denialPost (installPost state candidate) token) := by
  rcases valid with
    ⟨captured, parent, sameSlice, sameSeed, durable, freshEpoch,
      inactive, notClosed, unbound, running⟩
  have denied : ¬ UseGuard (installPost state candidate) token := by
    intro guard
    have tokenNew :
        token.epoch = candidate.specification.allocation.epoch := by
      simpa [UseGuard, installPost] using guard.2.1
    apply freshEpoch
    exact tokenNew.symm.trans oldEpoch
  exact ⟨denied, .denialUse denied⟩

theorem live_extension_before_old_use_denied
    [DecidableEq Outcome] [DecidableEq Label]
    {state : InstalledState (Outcome := Outcome) (Label := Label)}
    {candidate :
      LiveExtensionCandidate (Outcome := Outcome) (Label := Label)}
    {token : UseToken}
    (valid : candidate.ValidFor state)
    (oldEpoch : token.epoch = state.activeEpoch) :
    ¬ UseGuard (liveExtensionPost state candidate) token ∧
      KernelStep (liveExtensionPost state candidate) (.denial token)
        (denialPost (liveExtensionPost state candidate) token) := by
  rcases valid with
    ⟨captured, parent, sourceSlice, sameSeed, durable, freshEpoch,
      inactive, notClosed, unbound, running⟩
  have denied : ¬ UseGuard (liveExtensionPost state candidate) token := by
    intro guard
    have tokenNew :
        token.epoch = candidate.specification.allocation.epoch := by
      simpa [UseGuard, liveExtensionPost] using guard.2.1
    apply freshEpoch
    exact tokenNew.symm.trans oldEpoch
  exact ⟨denied, .denialUse denied⟩

inductive SystemStep
    [DecidableEq Outcome] [DecidableEq Label] :
    SystemState (Outcome := Outcome) (Label := Label) →
      SystemState (Outcome := Outcome) (Label := Label) → Prop
  | bootstrap {left right} (step : BootstrapStep left right) :
      SystemStep left right
  | installed {left right event} (step : KernelStep left event right) :
      SystemStep (.installed left) (.installed right)

end AuthorityContinuity.AgentHistoryAdmission.OperationalSemantics
