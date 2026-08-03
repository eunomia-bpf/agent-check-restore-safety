import AuthorityContinuity.AgentHistoryAdmission.FiniteCore

/-!
# Executable structure of authenticated Agent-history edits

This module isolates the structural part of the paper's history machine.
It deliberately gives the independent derivation relation and executable
editor separate definitions.  The finite word contracts here are the
linear-contract instance of the paper's registered residual contracts.
-/

namespace AuthorityContinuity.AgentHistoryAdmission.HistoryStructure

open AuthorityContinuity.AgentHistoryAdmission.FiniteCore

/-! ## Typed, deterministic names -/

structure Version where
  value : Nat
deriving DecidableEq, Repr

namespace Version

def next (version : Version) : Version :=
  ⟨version.value + 1⟩

@[simp] theorem next_value (version : Version) :
    version.next.value = version.value + 1 := rfl

end Version

structure RequestId where
  value : Nat
deriving DecidableEq, Repr

inductive NameSpace where
  | branch
  | group
deriving DecidableEq, Repr

/-- A role identifies both the edit row and an operand position. -/
inductive Role where
  | forkChoiceLeft
  | forkChoiceRight
  | forkChoiceGroup
  | forkParallelLeft
  | forkParallelRight
  | forkParallelGroup
  | restoreReplaceClone
  | restoreLiveClone
  | restoreLiveGroup
  | mergeSuffix
deriving DecidableEq, Repr

/-- Names are transparent tuples indexed by their namespace. -/
structure Name (space : NameSpace) where
  version : Version
  request : RequestId
  role : Role
deriving DecidableEq, Repr

abbrev BranchName := Name .branch
abbrev GroupName := Name .group

/-- The only allocator used by history edits. -/
def allocate (space : NameSpace) (version : Version)
    (request : RequestId) (role : Role) : Name space :=
  ⟨version, request, role⟩

@[simp] theorem allocate_version (space : NameSpace) (version : Version)
    (request : RequestId) (role : Role) :
    (allocate space version request role).version = version := rfl

theorem allocate_injective (space : NameSpace) :
    Function.Injective
      (fun input : Version × RequestId × Role =>
        allocate space input.1 input.2.1 input.2.2) := by
  rintro ⟨version₁, request₁, role₁⟩
    ⟨version₂, request₂, role₂⟩ equality
  cases equality
  rfl

/-! ## Finite contracts, branches, and structured frontiers -/

structure Occurrence where
  value : Nat
deriving DecidableEq, Repr

structure Cell where
  value : Nat
deriving DecidableEq, Repr

abbrev Event := ResolvedEvent Occurrence Cell

/-- A live continuation retains its immutable registered base word and stores
both the append-only resolved cursor and its exact current residual word. -/
structure Branch where
  name : BranchName
  base : List Occurrence
  cursor : List Event
  residual : List Occurrence
deriving DecidableEq, Repr

def Branch.rawCursor (branch : Branch) : List Occurrence :=
  branch.cursor.map (·.occurrence)

/-- The residual is derived, rather than caller-pruned. -/
def Branch.WellFormed (branch : Branch) : Prop :=
  branch.rawCursor ++ branch.residual = branch.base

inductive Side where
  | left
  | right
deriving DecidableEq, Repr

/-- Open and selected choice are separate constructors, so the type cannot
confuse them with a parallel group.  A join barrier carries no addressable
group name and therefore cannot be merged again. -/
inductive Frontier where
  | leaf (branch : Branch)
  | choiceOpen (group : GroupName) (left right : Frontier)
  | choiceSelected (group : GroupName) (winner : Side)
      (left right : Frontier)
  | parallel (group : GroupName) (left right : Frontier)
  | joinBarrier (left right : Frontier)
  | sequence (left right : Frontier)
deriving DecidableEq, Repr

def Frontier.branches : Frontier → List Branch
  | .leaf branch => [branch]
  | .choiceOpen _ left right
  | .choiceSelected _ _ left right
  | .parallel _ left right
  | .joinBarrier left right
  | .sequence left right => left.branches ++ right.branches

def Frontier.branchNames (frontier : Frontier) : List BranchName :=
  frontier.branches.map (·.name)

def Frontier.groups : Frontier → List GroupName
  | .leaf _ => []
  | .choiceOpen group left right
  | .choiceSelected group _ left right
  | .parallel group left right =>
      group :: (left.groups ++ right.groups)
  | .joinBarrier left right
  | .sequence left right => left.groups ++ right.groups

/-- Completion controls which sequence operand is exposed. -/
def Frontier.complete : Frontier → Bool
  | .leaf branch => branch.residual.isEmpty
  | .choiceOpen _ left right => left.complete && right.complete
  | .choiceSelected _ .left left _ => left.complete
  | .choiceSelected _ .right _ right => right.complete
  | .parallel _ left right
  | .joinBarrier left right
  | .sequence left right => left.complete && right.complete

/-! ## Checkpoints and append-only resolved progress -/

structure CheckpointId where
  value : Nat
deriving DecidableEq, Repr

/-- A checkpoint contains the immutable residual contract captured by Save. -/
structure Checkpoint where
  id : CheckpointId
  residual : List Occurrence
deriving DecidableEq, Repr

structure ProgressEvent where
  branch : BranchName
  event : Event
deriving DecidableEq, Repr

def progressAt (name : BranchName) : List ProgressEvent → List Event
  | [] => []
  | progress :: rest =>
      if progress.branch = name then
        progress.event :: progressAt name rest
      else
        progressAt name rest

structure History where
  version : Version
  frontier : Frontier
  checkpoints : List Checkpoint
  progress : List ProgressEvent
deriving DecidableEq, Repr

def History.lookupCheckpoint (history : History)
    (id : CheckpointId) : Option Checkpoint :=
  history.checkpoints.find? (·.id = id)

/-- Besides local residual correctness, live branch cursors must be exactly
the branch projection of the single global append-only resolved-event log. -/
structure History.WellFormed (history : History) : Prop where
  branchVersionBound :
    ∀ branch ∈ history.frontier.branches,
      branch.name.version.value ≤ history.version.value
  groupVersionBound :
    ∀ group ∈ history.frontier.groups,
      group.version.value ≤ history.version.value
  progressVersionBound :
    ∀ progress ∈ history.progress,
      progress.branch.version.value ≤ history.version.value
  branchResiduals :
    ∀ branch ∈ history.frontier.branches, branch.WellFormed
  cursorFromGlobal :
    ∀ branch ∈ history.frontier.branches,
      branch.cursor = progressAt branch.name history.progress

/-! ## The six registered edit forms -/

/-- There are exactly six history-rewrite requests.  Save and protected use
are transitions, but are intentionally not edit-request constructors. -/
inductive EditRequest where
  | forkChoice (request : RequestId) (target : BranchName)
      (leftSuffix rightSuffix : List Occurrence)
  | forkParallel (request : RequestId) (target : BranchName)
      (leftSuffix rightSuffix : List Occurrence)
  | restoreReplace (request : RequestId) (target : BranchName)
      (checkpoint : CheckpointId) (retirementAuthorized : Bool)
  | restoreLive (request : RequestId) (target : BranchName)
      (checkpoint : CheckpointId)
  | mergeSelect (request : RequestId) (target : GroupName)
      (winner : Side) (joinSuffix : List Occurrence)
      (retirementAuthorized : Bool)
  | mergeJoin (request : RequestId) (target : GroupName)
      (joinSuffix : List Occurrence)
deriving DecidableEq, Repr

def rootBranch : Frontier → BranchName → Option Branch
  | .leaf branch, target =>
      if branch.name = target then some branch else none
  | _, _ => none

theorem rootBranch_eq_some_iff {frontier : Frontier}
    {target : BranchName} {branch : Branch} :
    rootBranch frontier target = some branch ↔
      frontier = .leaf branch ∧ branch.name = target := by
  cases frontier <;> simp [rootBranch]
  case leaf candidate =>
    by_cases equality : candidate.name = target
    · constructor
      · intro result
        have same : candidate = branch := result.2
        subst branch
        exact ⟨rfl, equality⟩
      · rintro ⟨shape, _⟩
        cases shape
        simp [equality]
    · constructor
      · intro result
        simp [equality] at result
      · rintro ⟨shape, nameMatch⟩
        cases shape
        exact (equality nameMatch).elim

/-- Independent structural selection relation for MergeSelect. -/
inductive ChoiceSelection :
    Frontier → GroupName → Side → Frontier → Prop
  | openLeft (group : GroupName) (left right : Frontier) :
      ChoiceSelection (.choiceOpen group left right) group .left left
  | openRight (group : GroupName) (left right : Frontier) :
      ChoiceSelection (.choiceOpen group left right) group .right right
  | selectedLeft (group : GroupName) (left right : Frontier) :
      ChoiceSelection (.choiceSelected group .left left right)
        group .left left
  | selectedRight (group : GroupName) (left right : Frontier) :
      ChoiceSelection (.choiceSelected group .right left right)
        group .right right

def selectChoice : Frontier → GroupName → Side → Option Frontier
  | .choiceOpen group left right, target, side =>
      if group = target then
        match side with
        | .left => some left
        | .right => some right
      else
        none
  | .choiceSelected group selected left right, target, side =>
      if group = target && selected = side then
        match side with
        | .left => some left
        | .right => some right
      else
        none
  | _, _, _ => none

theorem selectChoice_eq_some_iff {frontier : Frontier}
    {target : GroupName} {side : Side} {winner : Frontier} :
    selectChoice frontier target side = some winner ↔
      ChoiceSelection frontier target side winner := by
  constructor
  · intro selected
    cases frontier with
    | leaf branch => simp [selectChoice] at selected
    | choiceOpen group left right =>
        by_cases groupMatch : group = target
        · subst target
          cases side with
          | left =>
              simp [selectChoice] at selected
              subst winner
              exact .openLeft group left right
          | right =>
              simp [selectChoice] at selected
              subst winner
              exact .openRight group left right
        · simp [selectChoice, groupMatch] at selected
    | choiceSelected group selectedSide left right =>
        by_cases groupMatch : group = target
        · subst target
          cases selectedSide <;> cases side <;>
            simp [selectChoice] at selected
          · subst winner
            exact .selectedLeft group left right
          · subst winner
            exact .selectedRight group left right
        · simp [selectChoice, groupMatch] at selected
    | parallel group left right => simp [selectChoice] at selected
    | joinBarrier left right => simp [selectChoice] at selected
    | sequence left right => simp [selectChoice] at selected
  · intro relation
    cases relation <;> simp [selectChoice]

def clonePending (name : BranchName) (source : Branch)
    (suffix : List Occurrence := []) : Branch where
  name := name
  base := source.residual ++ suffix
  cursor := []
  residual := source.residual ++ suffix

def cloneCheckpoint (name : BranchName) (checkpoint : Checkpoint) : Branch where
  name := name
  base := checkpoint.residual
  cursor := []
  residual := checkpoint.residual

def suffixBranch (name : BranchName) (suffix : List Occurrence) : Branch where
  name := name
  base := suffix
  cursor := []
  residual := suffix

@[simp] theorem clonePending_wellFormed (name : BranchName)
    (source : Branch) (suffix : List Occurrence) :
    (clonePending name source suffix).WellFormed := by
  simp [clonePending, Branch.WellFormed, Branch.rawCursor]

@[simp] theorem cloneCheckpoint_wellFormed (name : BranchName)
    (checkpoint : Checkpoint) :
    (cloneCheckpoint name checkpoint).WellFormed := by
  simp [cloneCheckpoint, Branch.WellFormed, Branch.rawCursor]

@[simp] theorem suffixBranch_wellFormed (name : BranchName)
    (suffix : List Occurrence) :
    (suffixBranch name suffix).WellFormed := by
  simp [suffixBranch, Branch.WellFormed, Branch.rawCursor]

def History.editVersion (history : History) : Version :=
  history.version.next

def branchName (history : History) (request : RequestId)
    (role : Role) : BranchName :=
  allocate .branch history.editVersion request role

def groupName (history : History) (request : RequestId)
    (role : Role) : GroupName :=
  allocate .group history.editVersion request role

def History.withFrontier (history : History) (frontier : Frontier) : History where
  version := history.editVersion
  frontier := frontier
  checkpoints := history.checkpoints
  progress := history.progress

/-- A live schema/registry/policy extension is identity-on-frontier.  It
advances the authenticated history view while retaining every checkpoint and
every append-only progress record. -/
def extensionHistory (history : History) : History where
  version := history.version.next
  frontier := history.frontier
  checkpoints := history.checkpoints
  progress := history.progress

@[simp] theorem extensionHistory_version (history : History) :
    (extensionHistory history).version = history.version.next := rfl

@[simp] theorem extensionHistory_frontier (history : History) :
    (extensionHistory history).frontier = history.frontier := rfl

@[simp] theorem extensionHistory_checkpoints (history : History) :
    (extensionHistory history).checkpoints = history.checkpoints := rfl

@[simp] theorem extensionHistory_progress (history : History) :
    (extensionHistory history).progress = history.progress := rfl

theorem extensionHistory_wellFormed {history : History}
    (wellFormed : history.WellFormed) :
    (extensionHistory history).WellFormed := by
  constructor
  · intro branch member
    have old := wellFormed.branchVersionBound branch member
    simp only [extensionHistory, Version.next_value]
    omega
  · intro group member
    have old := wellFormed.groupVersionBound group member
    simp only [extensionHistory, Version.next_value]
    omega
  · intro progress member
    have old := wellFormed.progressVersionBound progress member
    simp only [extensionHistory, Version.next_value]
    omega
  · exact wellFormed.branchResiduals
  · exact wellFormed.cursorFromGlobal

def forkChoicePost (history : History) (request : RequestId)
    (source : Branch) (leftSuffix rightSuffix : List Occurrence) : History :=
  history.withFrontier <|
    .choiceOpen
      (groupName history request .forkChoiceGroup)
      (.leaf (clonePending
        (branchName history request .forkChoiceLeft) source leftSuffix))
      (.leaf (clonePending
        (branchName history request .forkChoiceRight) source rightSuffix))

def forkParallelPost (history : History) (request : RequestId)
    (source : Branch) (leftSuffix rightSuffix : List Occurrence) : History :=
  history.withFrontier <|
    .parallel
      (groupName history request .forkParallelGroup)
      (.leaf (clonePending
        (branchName history request .forkParallelLeft) source leftSuffix))
      (.leaf (clonePending
        (branchName history request .forkParallelRight) source rightSuffix))

def restoreReplacePost (history : History) (request : RequestId)
    (checkpoint : Checkpoint) : History :=
  history.withFrontier <|
    .leaf (cloneCheckpoint
      (branchName history request .restoreReplaceClone) checkpoint)

def restoreLivePost (history : History) (request : RequestId)
    (source : Branch) (checkpoint : Checkpoint) : History :=
  history.withFrontier <|
    .parallel
      (groupName history request .restoreLiveGroup)
      (.leaf source)
      (.leaf (cloneCheckpoint
        (branchName history request .restoreLiveClone) checkpoint))

def mergeSelectPost (history : History) (request : RequestId)
    (winner : Frontier) (joinSuffix : List Occurrence) : History :=
  history.withFrontier <|
    .sequence winner
      (.leaf (suffixBranch
        (branchName history request .mergeSuffix) joinSuffix))

def mergeJoinPost (history : History) (request : RequestId)
    (left right : Frontier) (joinSuffix : List Occurrence) : History :=
  history.withFrontier <|
    .sequence (.joinBarrier left right)
      (.leaf (suffixBranch
        (branchName history request .mergeSuffix) joinSuffix))

/-! ## Independent derivation and executable editor -/

/-- This relation is not defined from `deriveEdit`; its six constructors are
the six schema rows. -/
inductive HistoryDerivation : History → EditRequest → History → Prop
  | forkChoice {history request target source leftSuffix rightSuffix}
      (root : rootBranch history.frontier target = some source) :
      HistoryDerivation history
        (.forkChoice request target leftSuffix rightSuffix)
        (forkChoicePost history request source leftSuffix rightSuffix)
  | forkParallel {history request target source leftSuffix rightSuffix}
      (root : rootBranch history.frontier target = some source) :
      HistoryDerivation history
        (.forkParallel request target leftSuffix rightSuffix)
        (forkParallelPost history request source leftSuffix rightSuffix)
  | restoreReplace
      {history request target source checkpointId checkpoint}
      (root : rootBranch history.frontier target = some source)
      (saved : history.lookupCheckpoint checkpointId = some checkpoint) :
      HistoryDerivation history
        (.restoreReplace request target checkpointId true)
        (restoreReplacePost history request checkpoint)
  | restoreLive {history request target source checkpointId checkpoint}
      (root : rootBranch history.frontier target = some source)
      (saved : history.lookupCheckpoint checkpointId = some checkpoint) :
      HistoryDerivation history
        (.restoreLive request target checkpointId)
        (restoreLivePost history request source checkpoint)
  | mergeSelect
      {history request target winnerSide winner joinSuffix}
      (selected :
        ChoiceSelection history.frontier target winnerSide winner) :
      HistoryDerivation history
        (.mergeSelect request target winnerSide joinSuffix true)
        (mergeSelectPost history request winner joinSuffix)
  | mergeJoin {history request target left right joinSuffix}
      (root : history.frontier = .parallel target left right) :
      HistoryDerivation history
        (.mergeJoin request target joinSuffix)
        (mergeJoinPost history request left right joinSuffix)

/-- The separately executable editor fails closed on the wrong root shape,
missing checkpoint, wrong group/winner, or missing retirement authority. -/
def deriveEdit (history : History) : EditRequest → Option History
  | .forkChoice request target leftSuffix rightSuffix => do
      let source ← rootBranch history.frontier target
      pure (forkChoicePost history request source leftSuffix rightSuffix)
  | .forkParallel request target leftSuffix rightSuffix => do
      let source ← rootBranch history.frontier target
      pure (forkParallelPost history request source leftSuffix rightSuffix)
  | .restoreReplace request target checkpointId retirementAuthorized =>
      if retirementAuthorized then do
        let _ ← rootBranch history.frontier target
        let checkpoint ← history.lookupCheckpoint checkpointId
        pure (restoreReplacePost history request checkpoint)
      else
        none
  | .restoreLive request target checkpointId => do
      let source ← rootBranch history.frontier target
      let checkpoint ← history.lookupCheckpoint checkpointId
      pure (restoreLivePost history request source checkpoint)
  | .mergeSelect request target winner joinSuffix retirementAuthorized =>
      if retirementAuthorized then do
        let selected ← selectChoice history.frontier target winner
        pure (mergeSelectPost history request selected joinSuffix)
      else
        none
  | .mergeJoin request target joinSuffix =>
      match history.frontier with
      | .parallel group left right =>
          if group = target then
            some (mergeJoinPost history request left right joinSuffix)
          else
            none
      | _ => none

theorem deriveEdit_sound {history : History} {request : EditRequest}
    {post : History} (derived : deriveEdit history request = some post) :
    HistoryDerivation history request post := by
  cases request with
  | forkChoice request target leftSuffix rightSuffix =>
      simp only [deriveEdit, Option.bind_eq_bind] at derived
      cases root : rootBranch history.frontier target with
      | none => simp [root] at derived
      | some source =>
          simp [root] at derived
          subst post
          exact .forkChoice root
  | forkParallel request target leftSuffix rightSuffix =>
      cases root : rootBranch history.frontier target with
      | none => simp [deriveEdit, root] at derived
      | some source =>
          simp [deriveEdit, root] at derived
          subst post
          exact .forkParallel root
  | restoreReplace request target checkpointId authorized =>
      cases authorized with
      | false => simp [deriveEdit] at derived
      | true =>
          cases root : rootBranch history.frontier target with
          | none => simp [deriveEdit, root] at derived
          | some source =>
              cases saved : history.lookupCheckpoint checkpointId with
              | none => simp [deriveEdit, root, saved] at derived
              | some checkpoint =>
                  simp [deriveEdit, root, saved] at derived
                  subst post
                  exact .restoreReplace root saved
  | restoreLive request target checkpointId =>
      cases root : rootBranch history.frontier target with
      | none => simp [deriveEdit, root] at derived
      | some source =>
          cases saved : history.lookupCheckpoint checkpointId with
          | none => simp [deriveEdit, root, saved] at derived
          | some checkpoint =>
              simp [deriveEdit, root, saved] at derived
              subst post
              exact .restoreLive root saved
  | mergeSelect request target winner joinSuffix authorized =>
      cases authorized with
      | false => simp [deriveEdit] at derived
      | true =>
          cases selected : selectChoice history.frontier target winner with
          | none => simp [deriveEdit, selected] at derived
          | some chosen =>
              simp [deriveEdit, selected] at derived
              subst post
              exact .mergeSelect
                (selectChoice_eq_some_iff.mp selected)
  | mergeJoin request target joinSuffix =>
      cases shape : history.frontier with
      | parallel group left right =>
          by_cases groupMatch : group = target
          · subst target
            simp [deriveEdit, shape] at derived
            subst post
            exact .mergeJoin shape
          · simp [deriveEdit, shape, groupMatch] at derived
      | leaf branch => simp [deriveEdit, shape] at derived
      | choiceOpen group left right => simp [deriveEdit, shape] at derived
      | choiceSelected group side left right =>
          simp [deriveEdit, shape] at derived
      | joinBarrier left right => simp [deriveEdit, shape] at derived
      | sequence left right => simp [deriveEdit, shape] at derived

theorem deriveEdit_complete {history : History} {request : EditRequest}
    {post : History} (derived : HistoryDerivation history request post) :
    deriveEdit history request = some post := by
  cases derived with
  | forkChoice root => simp [deriveEdit, root]
  | forkParallel root => simp [deriveEdit, root]
  | restoreReplace root saved => simp [deriveEdit, root, saved]
  | restoreLive root saved => simp [deriveEdit, root, saved]
  | mergeSelect selected =>
      simp [deriveEdit, selectChoice_eq_some_iff.mpr selected]
  | mergeJoin root => simp [deriveEdit, root]

theorem deriveEdit_iff {history : History} {request : EditRequest}
    {post : History} :
    deriveEdit history request = some post ↔
      HistoryDerivation history request post :=
  ⟨deriveEdit_sound, deriveEdit_complete⟩

theorem deriveEdit_deterministic {history : History}
    {request : EditRequest} {left right : History}
    (leftRun : deriveEdit history request = some left)
    (rightRun : deriveEdit history request = some right) :
    left = right := by
  rw [leftRun] at rightRun
  exact Option.some.inj rightRun

theorem historyDerivation_deterministic {history : History}
    {request : EditRequest} {left right : History}
    (leftDerivation : HistoryDerivation history request left)
    (rightDerivation : HistoryDerivation history request right) :
    left = right := by
  have leftRun := deriveEdit_complete leftDerivation
  have rightRun := deriveEdit_complete rightDerivation
  exact deriveEdit_deterministic leftRun rightRun

theorem historyDerivation_preserves_global_progress
    {history post : History} {request : EditRequest}
    (derived : HistoryDerivation history request post) :
    post.progress = history.progress := by
  cases derived <;>
    rfl

/-! ## Edit preservation -/

theorem progressAt_eq_nil_of_newer {progress : List ProgressEvent}
    {name : BranchName} {version : Nat}
    (bounded :
      ∀ item ∈ progress, item.branch.version.value ≤ version)
    (newer : version < name.version.value) :
    progressAt name progress = [] := by
  induction progress with
  | nil => rfl
  | cons item rest induction =>
      have itemBound : item.branch.version.value ≤ version :=
        bounded item (by simp)
      have tailBound :
          ∀ candidate ∈ rest,
            candidate.branch.version.value ≤ version := by
        intro candidate member
        exact bounded candidate (by simp [member])
      have different : item.branch ≠ name := by
        intro equality
        rw [equality] at itemBound
        omega
      simp [progressAt, different, induction tailBound]

theorem newBranch_has_no_old_progress (history : History)
    (wellFormed : history.WellFormed) (request : RequestId)
    (role : Role) :
    progressAt (branchName history request role) history.progress = [] := by
  apply progressAt_eq_nil_of_newer wellFormed.progressVersionBound
  simp [branchName, History.editVersion, Version.next, allocate]

theorem progress_bound_after_edit (history : History)
    (wellFormed : history.WellFormed) :
    ∀ item ∈ history.progress,
      item.branch.version.value ≤ history.editVersion.value := by
  intro item member
  have old := wellFormed.progressVersionBound item member
  simp [History.editVersion, Version.next]
  omega

theorem forkChoicePost_wellFormed (history : History)
    (wellFormed : history.WellFormed) (request : RequestId)
    (source : Branch) (leftSuffix rightSuffix : List Occurrence) :
    (forkChoicePost history request source
      leftSuffix rightSuffix).WellFormed := by
  constructor
  · intro branch member
    simp [forkChoicePost, History.withFrontier,
      Frontier.branches] at member
    rcases member with rfl | rfl
    · change
        (branchName history request .forkChoiceLeft).version.value ≤
          history.editVersion.value
      simp [branchName, History.editVersion, Version.next, allocate]
    · change
        (branchName history request .forkChoiceRight).version.value ≤
          history.editVersion.value
      simp [branchName, History.editVersion, Version.next, allocate]
  · intro group member
    have equality :
        group = groupName history request .forkChoiceGroup := by
      simpa [forkChoicePost, History.withFrontier,
        Frontier.groups] using member
    subst group
    change
      (groupName history request .forkChoiceGroup).version.value ≤
        history.editVersion.value
    simp [groupName, History.editVersion, Version.next, allocate]
  · exact progress_bound_after_edit history wellFormed
  · intro branch member
    simp [forkChoicePost, History.withFrontier,
      Frontier.branches] at member
    rcases member with (rfl | rfl) <;> simp
  · intro branch member
    simp [forkChoicePost, History.withFrontier,
      Frontier.branches] at member
    rcases member with (rfl | rfl)
    · simpa [clonePending] using
        (newBranch_has_no_old_progress history wellFormed request
          .forkChoiceLeft)
    · simpa [clonePending] using
        (newBranch_has_no_old_progress history wellFormed request
          .forkChoiceRight)

theorem forkParallelPost_wellFormed (history : History)
    (wellFormed : history.WellFormed) (request : RequestId)
    (source : Branch) (leftSuffix rightSuffix : List Occurrence) :
    (forkParallelPost history request source
      leftSuffix rightSuffix).WellFormed := by
  constructor
  · intro branch member
    simp [forkParallelPost, History.withFrontier,
      Frontier.branches] at member
    rcases member with rfl | rfl
    · change
        (branchName history request .forkParallelLeft).version.value ≤
          history.editVersion.value
      simp [branchName, History.editVersion, Version.next, allocate]
    · change
        (branchName history request .forkParallelRight).version.value ≤
          history.editVersion.value
      simp [branchName, History.editVersion, Version.next, allocate]
  · intro group member
    have equality :
        group = groupName history request .forkParallelGroup := by
      simpa [forkParallelPost, History.withFrontier,
        Frontier.groups] using member
    subst group
    change
      (groupName history request .forkParallelGroup).version.value ≤
        history.editVersion.value
    simp [groupName, History.editVersion, Version.next, allocate]
  · exact progress_bound_after_edit history wellFormed
  · intro branch member
    simp [forkParallelPost, History.withFrontier,
      Frontier.branches] at member
    rcases member with (rfl | rfl) <;> simp
  · intro branch member
    simp [forkParallelPost, History.withFrontier,
      Frontier.branches] at member
    rcases member with (rfl | rfl)
    · simpa [clonePending] using
        (newBranch_has_no_old_progress history wellFormed request
          .forkParallelLeft)
    · simpa [clonePending] using
        (newBranch_has_no_old_progress history wellFormed request
          .forkParallelRight)

theorem restoreReplacePost_wellFormed (history : History)
    (wellFormed : history.WellFormed) (request : RequestId)
    (checkpoint : Checkpoint) :
    (restoreReplacePost history request checkpoint).WellFormed := by
  constructor
  · intro branch member
    have equality :
        branch = cloneCheckpoint
          (branchName history request .restoreReplaceClone) checkpoint := by
      simpa [restoreReplacePost, History.withFrontier,
        Frontier.branches] using member
    subst branch
    simp [cloneCheckpoint, branchName, History.editVersion,
      restoreReplacePost, History.withFrontier, Version.next, allocate]
  · intro group member
    simp [restoreReplacePost, History.withFrontier, Frontier.groups] at member
  · exact progress_bound_after_edit history wellFormed
  · intro branch member
    have equality :
        branch = cloneCheckpoint
          (branchName history request .restoreReplaceClone) checkpoint := by
      simpa [restoreReplacePost, History.withFrontier,
        Frontier.branches] using member
    subst branch
    simp
  · intro branch member
    have equality :
        branch = cloneCheckpoint
          (branchName history request .restoreReplaceClone) checkpoint := by
      simpa [restoreReplacePost, History.withFrontier,
        Frontier.branches] using member
    subst branch
    simpa [cloneCheckpoint] using
      (newBranch_has_no_old_progress history wellFormed request
        .restoreReplaceClone)

theorem restoreLivePost_wellFormed (history : History)
    (wellFormed : history.WellFormed) (request : RequestId)
    (source : Branch) (sourceLive : source ∈ history.frontier.branches)
    (checkpoint : Checkpoint) :
    (restoreLivePost history request source checkpoint).WellFormed := by
  have sourceBound := wellFormed.branchVersionBound source sourceLive
  have sourceResidual := wellFormed.branchResiduals source sourceLive
  have sourceCursor := wellFormed.cursorFromGlobal source sourceLive
  constructor
  · intro branch member
    simp [restoreLivePost, History.withFrontier,
      Frontier.branches] at member
    rcases member with equality | equality
    · subst branch
      change source.name.version.value ≤ history.editVersion.value
      simp [History.editVersion, Version.next]
      omega
    · subst branch
      change
        (branchName history request .restoreLiveClone).version.value ≤
          history.editVersion.value
      simp [branchName, History.editVersion, Version.next, allocate]
  · intro group member
    have equality :
        group = groupName history request .restoreLiveGroup := by
      simpa [restoreLivePost, History.withFrontier,
        Frontier.groups] using member
    subst group
    change
      (groupName history request .restoreLiveGroup).version.value ≤
        history.editVersion.value
    simp [groupName, History.editVersion, Version.next, allocate]
  · exact progress_bound_after_edit history wellFormed
  · intro branch member
    simp [restoreLivePost, History.withFrontier,
      Frontier.branches] at member
    rcases member with (rfl | rfl)
    · exact sourceResidual
    · simp
  · intro branch member
    simp [restoreLivePost, History.withFrontier,
      Frontier.branches] at member
    rcases member with (rfl | rfl)
    · exact sourceCursor
    · simpa [cloneCheckpoint] using
        (newBranch_has_no_old_progress history wellFormed request
          .restoreLiveClone)

/-- Generic preservation for retaining a source subfrontier and appending a
new schema suffix behind sequence. -/
theorem sequenceSuffix_wellFormed (history : History)
    (wellFormed : history.WellFormed) (request : RequestId)
    (retained : Frontier)
    (branchSubset :
      ∀ branch ∈ retained.branches,
        branch ∈ history.frontier.branches)
    (groupSubset :
      ∀ group ∈ retained.groups,
        group ∈ history.frontier.groups)
    (suffix : List Occurrence) :
    (history.withFrontier
      (.sequence retained
        (.leaf (suffixBranch
          (branchName history request .mergeSuffix) suffix)))).WellFormed := by
  constructor
  · intro branch member
    simp only [History.withFrontier, Frontier.branches,
      List.mem_append, List.mem_singleton] at member
    rcases member with retainedMember | rfl
    · have old :=
        wellFormed.branchVersionBound branch
          (branchSubset branch retainedMember)
      change branch.name.version.value ≤ history.editVersion.value
      simp [History.editVersion, Version.next]
      omega
    · change
        (branchName history request .mergeSuffix).version.value ≤
          history.editVersion.value
      simp [branchName, History.editVersion, Version.next, allocate]
  · intro group member
    have retainedMember : group ∈ retained.groups := by
      simpa [History.withFrontier, Frontier.groups] using member
    have old :=
      wellFormed.groupVersionBound group
        (groupSubset group retainedMember)
    change group.version.value ≤ history.editVersion.value
    simp [History.editVersion, Version.next]
    omega
  · exact progress_bound_after_edit history wellFormed
  · intro branch member
    simp only [History.withFrontier, Frontier.branches,
      List.mem_append, List.mem_singleton] at member
    rcases member with retainedMember | rfl
    · exact wellFormed.branchResiduals branch
        (branchSubset branch retainedMember)
    · simp
  · intro branch member
    simp only [History.withFrontier, Frontier.branches,
      List.mem_append, List.mem_singleton] at member
    rcases member with retainedMember | rfl
    · exact wellFormed.cursorFromGlobal branch
        (branchSubset branch retainedMember)
    · simpa [suffixBranch] using
        (newBranch_has_no_old_progress history wellFormed request
          .mergeSuffix)

theorem ChoiceSelection.branch_subset {frontier : Frontier}
    {target : GroupName} {side : Side} {winner : Frontier}
    (selected : ChoiceSelection frontier target side winner) :
    ∀ branch ∈ winner.branches, branch ∈ frontier.branches := by
  intro branch member
  cases selected <;>
    simp only [Frontier.branches, List.mem_append] at *
  all_goals aesop

theorem ChoiceSelection.group_subset {frontier : Frontier}
    {target : GroupName} {side : Side} {winner : Frontier}
    (selected : ChoiceSelection frontier target side winner) :
    ∀ group ∈ winner.groups, group ∈ frontier.groups := by
  intro group member
  cases selected <;>
    simp only [Frontier.groups, List.mem_cons, List.mem_append] at *
  all_goals aesop

theorem mergeSelectPost_wellFormed (history : History)
    (wellFormed : history.WellFormed) (request : RequestId)
    {target : GroupName} {side : Side} {winner : Frontier}
    (selected :
      ChoiceSelection history.frontier target side winner)
    (suffix : List Occurrence) :
    (mergeSelectPost history request winner suffix).WellFormed := by
  apply sequenceSuffix_wellFormed history wellFormed request winner
  · exact selected.branch_subset
  · exact selected.group_subset

theorem mergeJoinPost_wellFormed (history : History)
    (wellFormed : history.WellFormed) (request : RequestId)
    {target : GroupName} {left right : Frontier}
    (root : history.frontier = .parallel target left right)
    (suffix : List Occurrence) :
    (mergeJoinPost history request left right suffix).WellFormed := by
  apply sequenceSuffix_wellFormed history wellFormed request
    (.joinBarrier left right)
  · intro branch member
    rw [root]
    simpa [Frontier.branches] using member
  · intro group member
    rw [root]
    simp only [Frontier.groups, List.mem_cons, List.mem_append]
    right
    simpa [Frontier.groups] using member

/-- All six independently specified edits preserve structural well-formedness. -/
theorem historyDerivation_preserves_wellFormed {history post : History}
    {request : EditRequest} (wellFormed : history.WellFormed)
    (derived : HistoryDerivation history request post) :
    post.WellFormed := by
  cases derived with
  | forkChoice root =>
      exact forkChoicePost_wellFormed _ wellFormed _ _ _ _
  | forkParallel root =>
      exact forkParallelPost_wellFormed _ wellFormed _ _ _ _
  | restoreReplace root saved =>
      exact restoreReplacePost_wellFormed _ wellFormed _ _
  | restoreLive root saved =>
      apply restoreLivePost_wellFormed history wellFormed
      ·
        have shape := (rootBranch_eq_some_iff.mp root).1
        rw [shape]
        simp [Frontier.branches]
  | mergeSelect selected =>
      exact mergeSelectPost_wellFormed _ wellFormed _ selected _
  | mergeJoin root =>
      exact mergeJoinPost_wellFormed _ wellFormed _ root _

/-! ## Atomic protected use -/

/-- The one atomic leaf update: the immutable base is retained, the resolved
event is appended to the local cursor, and the matching residual head is
removed. -/
def Branch.afterUse (branch : Branch) (event : Event)
    (tail : List Occurrence) : Branch where
  name := branch.name
  base := branch.base
  cursor := branch.cursor ++ [event]
  residual := tail

/-- Independent structural protected-use relation.  Open choice records the
arm whose event made durable progress.  Sequence exposes its right operand
only after observable completion of the left. -/
inductive FrontierUse :
    Frontier → BranchName → Event → Frontier → Prop
  | leaf {branch : Branch} {event : Event} {tail : List Occurrence}
      (head : branch.residual = event.occurrence :: tail) :
      FrontierUse (.leaf branch) branch.name event
        (.leaf (branch.afterUse event tail))
  | choiceOpenLeft {group target event left left' right}
      (step : FrontierUse left target event left') :
      FrontierUse (.choiceOpen group left right) target event
        (.choiceSelected group .left left' right)
  | choiceOpenRight {group target event left right right'}
      (step : FrontierUse right target event right') :
      FrontierUse (.choiceOpen group left right) target event
        (.choiceSelected group .right left right')
  | choiceSelectedLeft {group target event left left' right}
      (step : FrontierUse left target event left') :
      FrontierUse (.choiceSelected group .left left right) target event
        (.choiceSelected group .left left' right)
  | choiceSelectedRight {group target event left right right'}
      (step : FrontierUse right target event right') :
      FrontierUse (.choiceSelected group .right left right) target event
        (.choiceSelected group .right left right')
  | parallelLeft {group target event left left' right}
      (step : FrontierUse left target event left') :
      FrontierUse (.parallel group left right) target event
        (.parallel group left' right)
  | parallelRight {group target event left right right'}
      (step : FrontierUse right target event right') :
      FrontierUse (.parallel group left right) target event
        (.parallel group left right')
  | barrierLeft {target event left left' right}
      (step : FrontierUse left target event left') :
      FrontierUse (.joinBarrier left right) target event
        (.joinBarrier left' right)
  | barrierRight {target event left right right'}
      (step : FrontierUse right target event right') :
      FrontierUse (.joinBarrier left right) target event
        (.joinBarrier left right')
  | sequenceLeft {target event left left' right}
      (notComplete : left.complete = false)
      (step : FrontierUse left target event left') :
      FrontierUse (.sequence left right) target event
        (.sequence left' right)
  | sequenceRight {target event left right right'}
      (complete : left.complete = true)
      (step : FrontierUse right target event right') :
      FrontierUse (.sequence left right) target event
        (.sequence left right')

def protectedPost (history : History) (target : BranchName)
    (event : Event) (frontier : Frontier) : History where
  version := history.version.next
  frontier := frontier
  checkpoints := history.checkpoints
  progress := history.progress ++ [⟨target, event⟩]

/-- A protected use requires the target name to identify exactly one branch
in the current frontier.  Its single transition performs the frontier
residual and both local/global progress appends atomically. -/
inductive HStep : History → BranchName → Event → History → Prop
  | protectedUse {history target event frontier}
      (unique : history.frontier.branchNames.count target = 1)
      (use : FrontierUse history.frontier target event frontier) :
      HStep history target event
        (protectedPost history target event frontier)

/-- A structural use exposes the exact before/after branch records. -/
theorem frontierUse_cursor_sync {frontier frontier' : Frontier}
    {target : BranchName} {event : Event}
    (use : FrontierUse frontier target event frontier') :
    ∃ before after,
      before ∈ frontier.branches ∧
      after ∈ frontier'.branches ∧
      before.name = target ∧
      after.name = target ∧
      after.base = before.base ∧
      before.residual = event.occurrence :: after.residual ∧
      after.cursor = before.cursor ++ [event] := by
  induction use
  case leaf head =>
    simp [Frontier.branches, Branch.afterUse, head]
  all_goals
    simp only [Frontier.branches, List.mem_append] at *
    aesop

/-- The paper's missing synchronization fact: one HStep appends the same
resolved event to the unique branch cursor and the global history log while
removing exactly that event's occurrence from the residual. -/
theorem advance_cursor_sync {history post : History}
    {target : BranchName} {event : Event}
    (step : HStep history target event post) :
    ∃ before after,
      before ∈ history.frontier.branches ∧
      after ∈ post.frontier.branches ∧
      before.name = target ∧
      after.name = target ∧
      after.base = before.base ∧
      before.residual = event.occurrence :: after.residual ∧
      after.cursor = before.cursor ++ [event] ∧
      post.progress = history.progress ++ [⟨target, event⟩] := by
  cases step with
  | protectedUse uniqueness use =>
      rcases frontierUse_cursor_sync use with
        ⟨before, after, beforeMember, afterMember,
          beforeName, afterName, base, residual, cursor⟩
      exact ⟨before, after, beforeMember, afterMember,
        beforeName, afterName, base, residual, cursor, rfl⟩

/-! ## Kernel-checked fixtures -/

namespace Fixtures

def version0 : Version := ⟨0⟩
def request0 : RequestId := ⟨0⟩
def request1 : RequestId := ⟨1⟩

def occurrenceA : Occurrence := ⟨10⟩
def occurrenceB : Occurrence := ⟨11⟩
def cellA : Cell := ⟨20⟩

def oldBranchName : BranchName :=
  allocate .branch version0 request0 .restoreReplaceClone

def oldGroupName : GroupName :=
  allocate .group version0 request0 .forkChoiceGroup

def source : Branch where
  name := oldBranchName
  base := [occurrenceA]
  cursor := []
  residual := [occurrenceA]

def rightSource : Branch where
  name := allocate .branch version0 request0 .restoreLiveClone
  base := [occurrenceB]
  cursor := []
  residual := [occurrenceB]

def checkpoint0 : Checkpoint :=
  ⟨⟨0⟩, [occurrenceB]⟩

def leafHistory : History where
  version := version0
  frontier := .leaf source
  checkpoints := [checkpoint0]
  progress := []

def choiceHistory : History where
  version := version0
  frontier :=
    .choiceOpen oldGroupName (.leaf source) (.leaf rightSource)
  checkpoints := [checkpoint0]
  progress := []

def parallelHistory : History where
  version := version0
  frontier :=
    .parallel oldGroupName (.leaf source) (.leaf rightSource)
  checkpoints := [checkpoint0]
  progress := []

theorem leafHistory_wellFormed : leafHistory.WellFormed := by
  constructor <;>
    simp [leafHistory, source, oldBranchName, version0, request0,
      Frontier.branches, Frontier.groups, Branch.WellFormed,
      Branch.rawCursor, progressAt, allocate]

theorem choiceHistory_wellFormed : choiceHistory.WellFormed := by
  constructor <;>
    simp [choiceHistory, source, rightSource, oldBranchName, oldGroupName,
      version0, request0, Frontier.branches, Frontier.groups,
      Branch.WellFormed, Branch.rawCursor, progressAt, allocate]

theorem parallelHistory_wellFormed : parallelHistory.WellFormed := by
  constructor <;>
    simp [parallelHistory, source, rightSource, oldBranchName, oldGroupName,
      version0, request0, Frontier.branches, Frontier.groups,
      Branch.WellFormed, Branch.rawCursor, progressAt, allocate]

theorem forkChoice_fixture :
    deriveEdit leafHistory
      (.forkChoice request1 oldBranchName [] [occurrenceB]) =
      some (forkChoicePost leafHistory request1 source []
        [occurrenceB]) := by
  native_decide

theorem forkParallel_fixture :
    deriveEdit leafHistory
      (.forkParallel request1 oldBranchName [] [occurrenceB]) =
      some (forkParallelPost leafHistory request1 source []
        [occurrenceB]) := by
  native_decide

theorem restoreReplace_fixture :
    deriveEdit leafHistory
      (.restoreReplace request1 oldBranchName checkpoint0.id true) =
      some (restoreReplacePost leafHistory request1 checkpoint0) := by
  native_decide

theorem restoreLive_fixture :
    deriveEdit leafHistory
      (.restoreLive request1 oldBranchName checkpoint0.id) =
      some (restoreLivePost leafHistory request1 source checkpoint0) := by
  native_decide

theorem mergeSelect_fixture :
    deriveEdit choiceHistory
      (.mergeSelect request1 oldGroupName .left [occurrenceB] true) =
      some (mergeSelectPost choiceHistory request1
        (.leaf source) [occurrenceB]) := by
  native_decide

theorem mergeJoin_fixture :
    deriveEdit parallelHistory
      (.mergeJoin request1 oldGroupName [occurrenceB]) =
      some (mergeJoinPost parallelHistory request1
        (.leaf source) (.leaf rightSource) [occurrenceB]) := by
  native_decide

def freshA : Event :=
  ⟨occurrenceA, cellA, .fresh⟩

def aliasA : Event :=
  ⟨occurrenceA, cellA, .alias⟩

def freshPost : History :=
  protectedPost leafHistory oldBranchName freshA
    (.leaf (source.afterUse freshA []))

def aliasPost : History :=
  protectedPost leafHistory oldBranchName aliasA
    (.leaf (source.afterUse aliasA []))

theorem fresh_HStep :
    HStep leafHistory oldBranchName freshA freshPost := by
  apply HStep.protectedUse
  · native_decide
  · apply FrontierUse.leaf
    rfl

theorem alias_HStep :
    HStep leafHistory oldBranchName aliasA aliasPost := by
  apply HStep.protectedUse
  · native_decide
  · apply FrontierUse.leaf
    rfl

theorem fresh_advances_local_and_global :
    freshPost.frontier.branches.map (·.cursor) = [[freshA]] ∧
      freshPost.progress = [⟨oldBranchName, freshA⟩] := by
  native_decide

theorem alias_advances_local_and_global :
    aliasPost.frontier.branches.map (·.cursor) = [[aliasA]] ∧
      aliasPost.progress = [⟨oldBranchName, aliasA⟩] := by
  native_decide

theorem every_fixture_post_is_wellFormed :
    (forkChoicePost leafHistory request1 source []
      [occurrenceB]).WellFormed ∧
    (forkParallelPost leafHistory request1 source []
      [occurrenceB]).WellFormed ∧
    (restoreReplacePost leafHistory request1 checkpoint0).WellFormed ∧
    (restoreLivePost leafHistory request1 source checkpoint0).WellFormed ∧
    (mergeSelectPost choiceHistory request1
      (.leaf source) [occurrenceB]).WellFormed ∧
    (mergeJoinPost parallelHistory request1
      (.leaf source) (.leaf rightSource) [occurrenceB]).WellFormed := by
  repeat' apply And.intro
  · exact forkChoicePost_wellFormed _ leafHistory_wellFormed _ _ _ _
  · exact forkParallelPost_wellFormed _ leafHistory_wellFormed _ _ _ _
  · exact restoreReplacePost_wellFormed _ leafHistory_wellFormed _ _
  · exact restoreLivePost_wellFormed _ leafHistory_wellFormed _ _
      (by simp [leafHistory, source, Frontier.branches]) _
  · exact mergeSelectPost_wellFormed _ choiceHistory_wellFormed _
      (.openLeft oldGroupName (.leaf source) (.leaf rightSource)) _
  · exact mergeJoinPost_wellFormed _ parallelHistory_wellFormed _
      (by rfl) _

end Fixtures

end AuthorityContinuity.AgentHistoryAdmission.HistoryStructure
