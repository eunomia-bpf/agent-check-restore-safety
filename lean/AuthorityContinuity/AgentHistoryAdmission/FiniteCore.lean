import Mathlib

/-!
# Finite executable preflight for Agent-history admission

This file is a finite, executable preflight, not a proof of the paper's
general characterization theorem.  It keeps two decision routes independent:

* `SemanticAns` enumerates finite subfamilies and checks the declarative
  `Realization` predicate.
* `CompilerAns` starts from the individually safe base `B0`, repeatedly
  applies the executable pruning operator `Phi`, and inspects the bounded
  result.

The fixture is the paper's `X ∥ (Y ⊕ Z)` shared-prefix obstruction.
Outcome linearizations are `xy,yx` and `xz,zx`.  The authority policy admits
only candidate traces `yx` and `xz`.  At resolved prefix `[Fresh x]`, `xz`
remains compatible with the left outcome through raw linearization `xy`, but
no admitted left candidate supports that resolved prefix.  It is deleted;
then `yx` loses the right outcome at the root.  The pruning cardinalities are
therefore `[2, 1, 0]`.
-/

namespace AuthorityContinuity.AgentHistoryAdmission.FiniteCore

universe uOutcome uOccurrence uCell uLabel

inductive Mode where
  | fresh
  | alias
deriving DecidableEq, Repr

/-- A resolved event separates the syntactic occurrence, its semantic effect
cell, and whether this event creates that cell or aliases an existing one. -/
structure ResolvedEvent (Occurrence : Type uOccurrence) (Cell : Type uCell) where
  occurrence : Occurrence
  cell : Cell
  mode : Mode
deriving DecidableEq, Repr

/-- A finite candidate completion is indexed by one promised outcome. -/
structure Completion (Outcome : Type uOutcome)
    (Occurrence : Type uOccurrence) (Cell : Type uCell) where
  outcome : Outcome
  trace : List (ResolvedEvent Occurrence Cell)
deriving DecidableEq, Repr

/-- Finite input shared by the independent semantic and executable routes.

`linearizations` describe raw occurrence orders allowed for each outcome.
Candidates are derived from them by the resolver; callers cannot supply
arbitrary resolved traces.  `authority` contains complete authority-label
histories.  `durablePrefix` is stored separately from candidate traces,
`cellOf` resolves occurrences to semantic cells, and `labelOf` maps those
cells into the authority alphabet. -/
structure Instance (Outcome : Type uOutcome) (Occurrence : Type uOccurrence)
    (Cell : Type uCell) (Label : Type uLabel) where
  promised : Finset Outcome
  linearizations : Outcome → Finset (List Occurrence)
  cellOf : Occurrence → Cell
  initialReceipted : Finset Cell
  authority : Finset (List Label)
  durablePrefix : List Label
  labelOf : Cell → Label

section Generic

variable {Outcome : Type uOutcome} {Occurrence : Type uOccurrence}
variable {Cell : Type uCell} {Label : Type uLabel}
variable [DecidableEq Outcome] [DecidableEq Occurrence]
variable [DecidableEq Cell] [DecidableEq Label]

/-- Executable existential quantification over a finite set. -/
def finsetAny {α : Type*} [DecidableEq α]
    (items : Finset α) (predicate : α → Bool) : Bool :=
  (items.filter fun item => predicate item = true).card != 0

/-- Executable universal quantification over a finite set. -/
def finsetAll {α : Type*} [DecidableEq α]
    (items : Finset α) (predicate : α → Bool) : Bool :=
  (items.filter fun item => predicate item = true).card == items.card

/-- Forget cell identity and Fresh/Alias mode, retaining the occurrence word
used by the declared outcome language. -/
def raw (trace : List (ResolvedEvent Occurrence Cell)) : List Occurrence :=
  trace.map (·.occurrence)

/-- Resolve a raw occurrence word left-to-right.  A cell already present in
the receipt set is an Alias; the first unresolved occurrence of a cell is
Fresh and extends the receipt set for the remaining suffix. -/
def resolveFrom (cellOf : Occurrence → Cell) :
    Finset Cell → List Occurrence → List (ResolvedEvent Occurrence Cell)
  | _, [] => []
  | receipted, occurrence :: rest =>
      let cell := cellOf occurrence
      if cell ∈ receipted then
        ⟨occurrence, cell, .alias⟩ ::
          resolveFrom cellOf receipted rest
      else
        ⟨occurrence, cell, .fresh⟩ ::
          resolveFrom cellOf (insert cell receipted) rest

/-- Resolve one registered raw linearization from the durable receipt cut. -/
def resolve (input : Instance Outcome Occurrence Cell Label)
    (word : List Occurrence) : List (ResolvedEvent Occurrence Cell) :=
  resolveFrom input.cellOf input.initialReceipted word

omit [DecidableEq Occurrence] in
/-- Resolution never changes the registered occurrence word. -/
theorem raw_resolveFrom (cellOf : Occurrence → Cell)
    (receipted : Finset Cell) (word : List Occurrence) :
    raw (resolveFrom cellOf receipted word) = word := by
  induction word generalizing receipted with
  | nil => rfl
  | cons occurrence rest ih =>
      rw [resolveFrom]
      split
      · simp only [raw, List.map_cons]
        exact congrArg (List.cons occurrence) (ih receipted)
      · simp only [raw, List.map_cons]
        exact congrArg (List.cons occurrence)
          (ih (insert (cellOf occurrence) receipted))

omit [DecidableEq Outcome] [DecidableEq Occurrence]
    [DecidableEq Label] in
theorem raw_resolve (input : Instance Outcome Occurrence Cell Label)
    (word : List Occurrence) :
    raw (resolve input word) = word :=
  raw_resolveFrom input.cellOf input.initialReceipted word

/-- The complete finite candidate family is constructionally derived from
promised outcome linearizations and the unique resolver. -/
def allCandidates (input : Instance Outcome Occurrence Cell Label) :
    Finset (Completion Outcome Occurrence Cell) :=
  input.promised.biUnion fun outcome =>
    (input.linearizations outcome).image fun word =>
      ⟨outcome, resolve input word⟩

/-- Only Fresh events extend the authority word.  Alias events denote an
already-existing semantic cell and do not mint another authority label. -/
def authorityWord (input : Instance Outcome Occurrence Cell Label)
    (trace : List (ResolvedEvent Occurrence Cell)) : List Label :=
  trace.filterMap fun event =>
    match event.mode with
    | .fresh => some (input.labelOf event.cell)
    | .alias => none

/-- The complete authority history checked for one candidate. -/
def authorityHistory (input : Instance Outcome Occurrence Cell Label)
    (completion : Completion Outcome Occurrence Cell) : List Label :=
  input.durablePrefix ++ authorityWord input completion.trace

/-- Individually authority-safe candidates, before relational pruning. -/
def B0 (input : Instance Outcome Occurrence Cell Label) :
    Finset (Completion Outcome Occurrence Cell) :=
  (allCandidates input).filter fun completion =>
    authorityHistory input completion ∈ input.authority

/-- All prefixes of a word, including the root and complete word. -/
def prefixes {α : Type*} (word : List α) : List (List α) :=
  (List.range (word.length + 1)).map word.take

/-- Executable well-formedness check for authority-prefix closure. -/
def policyPrefixClosed (input : Instance Outcome Occurrence Cell Label) : Bool :=
  finsetAll input.authority fun word =>
    (prefixes word).all fun pre =>
      decide (pre ∈ input.authority)

/-- Declarative compatibility, represented executably: the raw occurrence
word of this resolved prefix is a prefix of some declared linearization for
`outcome`. -/
def Compatible (input : Instance Outcome Occurrence Cell Label)
    (pre : List (ResolvedEvent Occurrence Cell))
    (outcome : Outcome) : Bool :=
  finsetAny (input.linearizations outcome) fun linearization =>
    decide (raw pre <+: linearization)

/-- Executable support in the current family for one resolved prefix and
outcome.  Support retains occurrence, cell, and Fresh/Alias identity. -/
def supportsAt (family : Finset (Completion Outcome Occurrence Cell))
    (pre : List (ResolvedEvent Occurrence Cell))
    (outcome : Outcome) : Bool :=
  finsetAny family fun completion =>
    decide (completion.outcome = outcome ∧ pre <+: completion.trace)

/-- A candidate survives exactly when every compatible promised outcome is
still supported at each of its resolved prefixes. -/
def prefixRobust (input : Instance Outcome Occurrence Cell Label)
    (family : Finset (Completion Outcome Occurrence Cell))
    (completion : Completion Outcome Occurrence Cell) : Bool :=
  (prefixes completion.trace).all fun pre =>
    finsetAll input.promised fun outcome =>
      !Compatible input pre outcome ||
        supportsAt family pre outcome

/-- One executable descending pruning step. -/
def Phi (input : Instance Outcome Occurrence Cell Label)
    (family : Finset (Completion Outcome Occurrence Cell)) :
    Finset (Completion Outcome Occurrence Cell) :=
  (B0 input).filter fun completion =>
    prefixRobust input family completion = true

/-- The executable pruning sequence beginning at `B0`. -/
def pruningRound (input : Instance Outcome Occurrence Cell Label) :
    Nat → Finset (Completion Outcome Occurrence Cell)
  | 0 => B0 input
  | round + 1 => Phi input (pruningRound input round)

/-- A descending family over `B0` can make at most `|B0|` strict deletions.
This preflight executes that bound; a later general module must prove the
stabilization theorem rather than inheriting it from this fixture. -/
def boundedFixedPoint (input : Instance Outcome Occurrence Cell Label) :
    Finset (Completion Outcome Occurrence Cell) :=
  pruningRound input (B0 input).card

/-- Independent declarative meaning of a nonempty realization.  It uses
`Compatible`, but does not mention `Phi`, `pruningRound`, or
`boundedFixedPoint`. -/
def Realization (input : Instance Outcome Occurrence Cell Label)
    (family : Finset (Completion Outcome Occurrence Cell)) : Bool :=
  policyPrefixClosed input &&
    family.card != 0 &&
    decide (family ⊆ allCandidates input) &&
    finsetAll family fun completion =>
      (prefixes completion.trace).all fun pre =>
        decide
            (input.durablePrefix ++ authorityWord input pre ∈
              input.authority) &&
          finsetAll input.promised fun outcome =>
            !Compatible input pre outcome ||
              supportsAt family pre outcome

inductive Ans where
  | admit
  | reject
deriving DecidableEq, Repr

/-- Declarative finite answer obtained by enumerating every subfamily of the
constructionally derived candidates and checking `Realization`. -/
def SemanticAns (input : Instance Outcome Occurrence Cell Label) : Ans :=
  if finsetAny (allCandidates input).powerset fun family =>
      Realization input family then
    .admit
  else
    .reject

/-- Executable compiler answer obtained from policy validation and bounded
pruning.  A malformed non-prefix-closed policy is rejected before admission. -/
def CompilerAns (input : Instance Outcome Occurrence Cell Label) : Ans :=
  if policyPrefixClosed input then
    if (boundedFixedPoint input).Nonempty then .admit else .reject
  else
    .reject

end Generic

/-! ## The exact `X ∥ (Y ⊕ Z)` shared-prefix fixture -/

namespace SharedPrefixFixture

inductive Outcome where
  | left
  | right
deriving DecidableEq, Repr

inductive Occurrence where
  | x
  | y
  | z
deriving DecidableEq, Repr

inductive Cell where
  | x
  | y
  | z
deriving DecidableEq, Repr

inductive AuthorityLabel where
  | x
  | y
  | z
deriving DecidableEq, Repr

def cellOf : Occurrence → Cell
  | .x => .x
  | .y => .y
  | .z => .z

def labelOf : Cell → AuthorityLabel
  | .x => .x
  | .y => .y
  | .z => .z

def freshX : ResolvedEvent Occurrence Cell :=
  ⟨.x, .x, .fresh⟩

def freshY : ResolvedEvent Occurrence Cell :=
  ⟨.y, .y, .fresh⟩

def freshZ : ResolvedEvent Occurrence Cell :=
  ⟨.z, .z, .fresh⟩

def leftXY : Completion Outcome Occurrence Cell :=
  ⟨.left, [freshX, freshY]⟩

def leftYX : Completion Outcome Occurrence Cell :=
  ⟨.left, [freshY, freshX]⟩

def rightXZ : Completion Outcome Occurrence Cell :=
  ⟨.right, [freshX, freshZ]⟩

def rightZX : Completion Outcome Occurrence Cell :=
  ⟨.right, [freshZ, freshX]⟩

def linearizations : Outcome → Finset (List Occurrence)
  | .left => { [.x, .y], [.y, .x] }
  | .right => { [.x, .z], [.z, .x] }

/-- The literal paper policy `Pref {yx, xz}`. -/
def authority : Finset (List AuthorityLabel) := {
  [],
  [.y],
  [.y, .x],
  [.x],
  [.x, .z]
}

def fixture : Instance Outcome Occurrence Cell AuthorityLabel where
  promised := {.left, .right}
  linearizations := linearizations
  cellOf := cellOf
  initialReceipted := ∅
  authority := authority
  durablePrefix := []
  labelOf := labelOf

/-- The paper fixture uses the empty durable cut, but that cut remains a field
separate from future traces.  Occurrence-to-cell and cell-to-label maps are
explicit. -/
theorem separate_cut_and_maps :
    fixture.durablePrefix = [] ∧
      fixture.initialReceipted = ∅ ∧
      cellOf .x = .x ∧ cellOf .y = .y ∧ cellOf .z = .z ∧
      leftYX.trace = [freshY, freshX] ∧
      rightXZ.trace = [freshX, freshZ] ∧
      labelOf .x = .x ∧ labelOf .y = .y ∧ labelOf .z = .z := by
  native_decide

/-- Each registered linearization is resolved into its constructional
completion; no caller-supplied resolved candidate is involved. -/
theorem resolutions_are_exact :
    resolve fixture [.x, .y] = leftXY.trace ∧
      resolve fixture [.y, .x] = leftYX.trace ∧
      resolve fixture [.x, .z] = rightXZ.trace ∧
      resolve fixture [.z, .x] = rightZX.trace := by
  native_decide

/-- The resolver preserves each fixture occurrence word. -/
theorem raw_resolutions_are_exact :
    raw (resolve fixture [.x, .y]) = [.x, .y] ∧
      raw (resolve fixture [.y, .x]) = [.y, .x] ∧
      raw (resolve fixture [.x, .z]) = [.x, .z] ∧
      raw (resolve fixture [.z, .x]) = [.z, .x] := by
  native_decide

/-- The derived family is exactly the four outcome-indexed linearizations. -/
theorem candidates_are_exact :
    allCandidates fixture = {leftXY, leftYX, rightXZ, rightZX} := by
  native_decide

/-- The literal `Pref {yx,xz}` policy passes the executable closure check. -/
theorem policy_prefix_closed :
    policyPrefixClosed fixture = true := by
  native_decide

/-- Raw compatibility uses occurrence linearizations, independently of the
authority filter. -/
theorem declared_linearizations :
    Compatible fixture [freshX] .left = true ∧
      Compatible fixture [freshX] .right = true ∧
      Compatible fixture [freshY] .left = true ∧
      Compatible fixture [freshY] .right = false := by
  native_decide

/-- The authority-prefix check admits exactly `yx` and `xz`. -/
theorem base_is_exact :
    B0 fixture = {leftYX, rightXZ} := by
  native_decide

/-- This is the first paper obstruction: at `[Fresh x]`, raw compatibility
still includes left linearization `xy`, but the current base has no left
completion supporting that resolved prefix. -/
theorem xz_obstruction_at_fresh_x :
    Compatible fixture [freshX] .left = true ∧
      supportsAt (B0 fixture) [freshX] .left = false := by
  native_decide

/-- Consequently `xz` is removed in the first pruning round. -/
theorem xz_is_deleted_first :
    rightXZ ∈ B0 fixture ∧
      rightXZ ∉ Phi fixture (B0 fixture) := by
  native_decide

/-- This is the second deletion cause: after round one, the root is still
compatible with the right outcome, but that outcome has no remaining support. -/
theorem yx_obstruction_at_root :
    Compatible fixture [] .right = true ∧
      supportsAt (Phi fixture (B0 fixture)) [] .right = false := by
  native_decide

/-- `yx` survives that round, then loses the compatible right outcome at the
root once `xz` has disappeared. -/
theorem yx_is_deleted_second :
    leftYX ∈ Phi fixture (B0 fixture) ∧
      leftYX ∉ Phi fixture (Phi fixture (B0 fixture)) := by
  native_decide

/-- Exact executable pruning trace for the paper fixture. -/
theorem pruning_cardinalities :
    [
      (B0 fixture).card,
      (Phi fixture (B0 fixture)).card,
      (Phi fixture (Phi fixture (B0 fixture))).card
    ] = [2, 1, 0] := by
  native_decide

/-- The independent declarative enumeration and executable compiler agree on
this fixture. -/
theorem compiler_eq_semantic :
    CompilerAns fixture = SemanticAns fixture := by
  native_decide

/-- Both decision routes reject the fixture. -/
theorem both_reject :
    CompilerAns fixture = .reject ∧
      SemanticAns fixture = .reject := by
  native_decide

end SharedPrefixFixture

end AuthorityContinuity.AgentHistoryAdmission.FiniteCore
