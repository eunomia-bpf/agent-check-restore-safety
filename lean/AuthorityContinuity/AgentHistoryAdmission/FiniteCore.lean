import Mathlib

/-!
# General finite core for Agent-history admission

This file proves the paper's finite characterization core while keeping its
two decision routes independent:

* `SemanticAns` enumerates finite subfamilies and checks the declarative
  `ValidRealization` predicate.
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
histories.  The ordered `durableReceiptCells` ledger is the single source of
truth for both the initial receipt set and durable authority prefix.
`cellOf` resolves occurrences to semantic cells, and `labelOf` maps those
cells into the authority alphabet. -/
structure Instance (Outcome : Type uOutcome) (Occurrence : Type uOccurrence)
    (Cell : Type uCell) (Label : Type uLabel) where
  promised : Finset Outcome
  linearizations : Outcome → Finset (List Occurrence)
  cellOf : Occurrence → Cell
  durableReceiptCells : List Cell
  authority : Finset (List Label)
  labelOf : Cell → Label

/-- The resolver's initial receipt set is derived from the durable ledger. -/
def Instance.initialReceipted
    (input : Instance Outcome Occurrence Cell Label) [DecidableEq Cell] :
    Finset Cell :=
  input.durableReceiptCells.toFinset

/-- The durable authority prefix is the ordered label projection of the same
ledger that determines the resolver's initial receipt set. -/
def Instance.durablePrefix
    (input : Instance Outcome Occurrence Cell Label) : List Label :=
  input.durableReceiptCells.map input.labelOf

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

theorem finsetAny_eq_true {α : Type*} [DecidableEq α]
    (items : Finset α) (predicate : α → Bool) :
    finsetAny items predicate = true ↔
      ∃ item ∈ items, predicate item = true := by
  simp [finsetAny]

theorem finsetAll_eq_true {α : Type*} [DecidableEq α]
    (items : Finset α) (predicate : α → Bool) :
    finsetAll items predicate = true ↔
      ∀ item ∈ items, predicate item = true := by
  simp [finsetAll, Finset.card_filter_eq_iff]

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

/-- Receipt state after scanning a raw word. -/
def receiptsAfter (cellOf : Occurrence → Cell) :
    Finset Cell → List Occurrence → Finset Cell
  | receipted, [] => receipted
  | receipted, occurrence :: rest =>
      receiptsAfter cellOf (insert (cellOf occurrence) receipted) rest

/-- Independent small-step resolver judgment.  It records both the resolved
event word and the exact final receipt state. -/
inductive ResolvesFrom (cellOf : Occurrence → Cell) :
    Finset Cell → List Occurrence →
      List (ResolvedEvent Occurrence Cell) → Finset Cell → Prop
  | nil (receipted) :
      ResolvesFrom cellOf receipted [] [] receipted
  | aliasStep {receipted occurrence rest trace final}
      (hcell : cellOf occurrence ∈ receipted)
      (hrest : ResolvesFrom cellOf receipted rest trace final) :
      ResolvesFrom cellOf receipted (occurrence :: rest)
        (⟨occurrence, cellOf occurrence, .alias⟩ :: trace) final
  | freshStep {receipted occurrence rest trace final}
      (hcell : cellOf occurrence ∉ receipted)
      (hrest : ResolvesFrom cellOf (insert (cellOf occurrence) receipted)
        rest trace final) :
      ResolvesFrom cellOf receipted (occurrence :: rest)
        (⟨occurrence, cellOf occurrence, .fresh⟩ :: trace) final

theorem resolvesFrom_exact (cellOf : Occurrence → Cell)
    {receipted : Finset Cell} {word : List Occurrence}
    {trace : List (ResolvedEvent Occurrence Cell)} {final : Finset Cell}
    (hresolve : ResolvesFrom cellOf receipted word trace final) :
    trace = resolveFrom cellOf receipted word ∧
      final = receiptsAfter cellOf receipted word := by
  induction hresolve with
  | nil => exact ⟨rfl, rfl⟩
  | aliasStep hcell hrest ih =>
      rw [resolveFrom, if_pos hcell, receiptsAfter,
        Finset.insert_eq_self.mpr hcell]
      exact ⟨congrArg _ ih.1, ih.2⟩
  | freshStep hcell hrest ih =>
      rw [resolveFrom, if_neg hcell, receiptsAfter]
      exact ⟨congrArg _ ih.1, ih.2⟩

/-- The executable resolver always produces a derivation in the independent
small-step relation, including its exact final receipt state. -/
theorem resolvesFrom_resolveFrom (cellOf : Occurrence → Cell)
    (receipted : Finset Cell) (word : List Occurrence) :
    ResolvesFrom cellOf receipted word
      (resolveFrom cellOf receipted word)
      (receiptsAfter cellOf receipted word) := by
  induction word generalizing receipted with
  | nil =>
      exact .nil receipted
  | cons occurrence rest ih =>
      rw [resolveFrom, receiptsAfter]
      by_cases hcell : cellOf occurrence ∈ receipted
      · rw [if_pos hcell]
        apply ResolvesFrom.aliasStep hcell
        simpa [Finset.insert_eq_self.mpr hcell] using ih receipted
      · rw [if_neg hcell]
        exact ResolvesFrom.freshStep hcell
          (ih (insert (cellOf occurrence) receipted))

/-- The independent relation is exactly the graph of the executable
resolver, rather than an ornamental one-way simulation. -/
theorem resolvesFrom_iff (cellOf : Occurrence → Cell)
    {receipted : Finset Cell} {word : List Occurrence}
    {trace : List (ResolvedEvent Occurrence Cell)} {final : Finset Cell} :
    ResolvesFrom cellOf receipted word trace final ↔
      trace = resolveFrom cellOf receipted word ∧
        final = receiptsAfter cellOf receipted word := by
  constructor
  · exact resolvesFrom_exact cellOf
  · rintro ⟨rfl, rfl⟩
    exact resolvesFrom_resolveFrom cellOf receipted word

/-- The independent resolver judgment is deterministic in both its event
word and its final receipt state. -/
theorem resolve_deterministic (cellOf : Occurrence → Cell)
    {receipted : Finset Cell} {word : List Occurrence}
    {left right : List (ResolvedEvent Occurrence Cell)}
    {leftFinal rightFinal : Finset Cell}
    (hleft : ResolvesFrom cellOf receipted word left leftFinal)
    (hright : ResolvesFrom cellOf receipted word right rightFinal) :
    left = right ∧ leftFinal = rightFinal := by
  have hl := resolvesFrom_exact cellOf hleft
  have hr := resolvesFrom_exact cellOf hright
  exact ⟨hl.1.trans hr.1.symm, hl.2.trans hr.2.symm⟩

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

omit [DecidableEq Outcome] [DecidableEq Occurrence]
    [DecidableEq Label] in
/-- Resolution preserves the number of registered occurrences. -/
theorem resolve_length (input : Instance Outcome Occurrence Cell Label)
    (word : List Occurrence) :
    (resolve input word).length = word.length := by
  simpa [raw] using congrArg List.length (raw_resolve input word)

omit [DecidableEq Outcome] [DecidableEq Occurrence]
    [DecidableEq Label] in
/-- Projecting a resolved word back to occurrences returns exactly the
registered word. -/
theorem resolve_occurrence_projection
    (input : Instance Outcome Occurrence Cell Label)
    (word : List Occurrence) :
    (resolve input word).map (·.occurrence) = word :=
  raw_resolve input word

theorem receiptsAfter_append (cellOf : Occurrence → Cell)
    (receipted : Finset Cell) (left right : List Occurrence) :
    receiptsAfter cellOf receipted (left ++ right) =
      receiptsAfter cellOf (receiptsAfter cellOf receipted left) right := by
  induction left generalizing receipted with
  | nil => rfl
  | cons occurrence rest ih =>
      simp only [List.cons_append, receiptsAfter]
      exact ih (insert (cellOf occurrence) receipted)

theorem resolveFrom_streaming (cellOf : Occurrence → Cell)
    (receipted : Finset Cell) (left right : List Occurrence) :
    resolveFrom cellOf receipted (left ++ right) =
      resolveFrom cellOf receipted left ++
        resolveFrom cellOf (receiptsAfter cellOf receipted left) right := by
  induction left generalizing receipted with
  | nil => rfl
  | cons occurrence rest ih =>
      simp only [List.cons_append, resolveFrom, receiptsAfter]
      split
      · have hinsert :
            insert (cellOf occurrence) receipted = receipted :=
          Finset.insert_eq_self.mpr ‹cellOf occurrence ∈ receipted›
        rw [hinsert, ih]
        rfl
      · rw [ih]
        rfl

/-- Resolving a concatenation can be streamed: resolve the suffix from the
receipt state produced by the prefix. -/
theorem resolve_streaming (input : Instance Outcome Occurrence Cell Label)
    (left right : List Occurrence) :
    resolve input (left ++ right) =
      resolve input left ++
        resolveFrom input.cellOf
          (receiptsAfter input.cellOf input.initialReceipted left) right :=
  resolveFrom_streaming input.cellOf input.initialReceipted left right

/-- Cells introduced by Fresh events, in event order. -/
def freshCells (trace : List (ResolvedEvent Occurrence Cell)) : List Cell :=
  trace.filterMap fun event =>
    match event.mode with
    | .fresh => some event.cell
    | .alias => none

theorem freshCells_resolveFrom_nodup_and_fresh
    (cellOf : Occurrence → Cell) (receipted : Finset Cell)
    (word : List Occurrence) :
    (freshCells (resolveFrom cellOf receipted word)).Nodup ∧
      ∀ cell ∈ freshCells (resolveFrom cellOf receipted word),
        cell ∉ receipted := by
  induction word generalizing receipted with
  | nil =>
      simp [resolveFrom, freshCells]
  | cons occurrence rest ih =>
      rw [resolveFrom]
      split
      · simpa [freshCells] using ih receipted
      · have hsuffix := ih (insert (cellOf occurrence) receipted)
        constructor
        · simp only [freshCells, List.filterMap_cons, Option.some.injEq,
            List.nodup_cons]
          exact ⟨by
            intro hin
            exact (hsuffix.2 (cellOf occurrence) hin)
              (Finset.mem_insert_self _ _), hsuffix.1⟩
        · intro cell hcell
          simp only [freshCells, List.filterMap_cons, List.mem_cons] at hcell
          rcases hcell with rfl | hcell
          · exact ‹cellOf occurrence ∉ receipted›
          · exact fun hmem =>
              hsuffix.2 cell hcell (Finset.mem_insert_of_mem hmem)

/-- A semantic cell is minted at most once by the resolver, and no Fresh
event remints a cell already present at the durable receipt cut. -/
theorem resolve_fresh_cell_unique
    (input : Instance Outcome Occurrence Cell Label)
    (word : List Occurrence) :
    (freshCells (resolve input word)).Nodup ∧
      ∀ cell ∈ freshCells (resolve input word),
        cell ∉ input.initialReceipted :=
  freshCells_resolveFrom_nodup_and_fresh
    input.cellOf input.initialReceipted word

/-- The complete finite candidate family is constructionally derived from
promised outcome linearizations and the unique resolver. -/
def allCandidates (input : Instance Outcome Occurrence Cell Label) :
    Finset (Completion Outcome Occurrence Cell) :=
  input.promised.biUnion fun outcome =>
    (input.linearizations outcome).image fun word =>
      ⟨outcome, resolve input word⟩

/-- Relational candidate generation: the outcome and raw word are registered,
and the resolved trace is produced by the independent resolver judgment. -/
def RelationalCandidate
    (input : Instance Outcome Occurrence Cell Label)
    (completion : Completion Outcome Occurrence Cell) : Prop :=
  completion.outcome ∈ input.promised ∧
    ∃ word ∈ input.linearizations completion.outcome,
      ∃ final,
        ResolvesFrom input.cellOf input.initialReceipted word
          completion.trace final

/-- Membership in the executable candidate family is equivalent to the
independent relational generation contract. -/
theorem mem_allCandidates_iff_relationalCandidate
    (input : Instance Outcome Occurrence Cell Label)
    (completion : Completion Outcome Occurrence Cell) :
    completion ∈ allCandidates input ↔
      RelationalCandidate input completion := by
  constructor
  · intro hmember
    simp only [allCandidates, Finset.mem_biUnion, Finset.mem_image] at hmember
    obtain ⟨outcome, houtcome, word, hword, heq⟩ := hmember
    subst completion
    refine ⟨houtcome, word, hword, ?_⟩
    refine ⟨receiptsAfter input.cellOf input.initialReceipted word, ?_⟩
    exact resolvesFrom_resolveFrom input.cellOf input.initialReceipted word
  · rintro ⟨houtcome, word, hword, final, hresolve⟩
    have htrace := (resolvesFrom_iff input.cellOf).1 hresolve
    simp only [allCandidates, Finset.mem_biUnion, Finset.mem_image]
    refine ⟨completion.outcome, houtcome, word, hword, ?_⟩
    cases completion with
    | mk outcome trace =>
        simp only at htrace ⊢
        exact congrArg (Completion.mk outcome) htrace.1.symm

/-- Only Fresh events extend the authority word.  Alias events denote an
already-existing semantic cell and do not mint another authority label. -/
def authorityWord (input : Instance Outcome Occurrence Cell Label)
    (trace : List (ResolvedEvent Occurrence Cell)) : List Label :=
  trace.filterMap fun event =>
    match event.mode with
    | .fresh => some (input.labelOf event.cell)
    | .alias => none

omit [DecidableEq Outcome] [DecidableEq Occurrence]
    [DecidableEq Cell] [DecidableEq Label] in
/-- The authority projection is exactly the label projection of the uniquely
minted semantic cells; Alias events are silent. -/
theorem authorityWord_eq_map_freshCells
    (input : Instance Outcome Occurrence Cell Label)
    (trace : List (ResolvedEvent Occurrence Cell)) :
    authorityWord input trace = (freshCells trace).map input.labelOf := by
  induction trace with
  | nil => rfl
  | cons event rest ih =>
      cases event with
      | mk occurrence cell mode =>
          cases mode <;>
            simpa [authorityWord, freshCells] using ih

omit [DecidableEq Outcome] [DecidableEq Occurrence]
    [DecidableEq Cell] [DecidableEq Label] in
theorem authorityWord_append
    (input : Instance Outcome Occurrence Cell Label)
    (left right : List (ResolvedEvent Occurrence Cell)) :
    authorityWord input (left ++ right) =
      authorityWord input left ++ authorityWord input right := by
  induction left with
  | nil => rfl
  | cons event rest ih =>
      cases event with
      | mk occurrence cell mode =>
          cases mode <;> simp [authorityWord, ih]

omit [DecidableEq Outcome] [DecidableEq Occurrence]
    [DecidableEq Cell] [DecidableEq Label] in
theorem authorityWord_prefix
    (input : Instance Outcome Occurrence Cell Label)
    {pre trace : List (ResolvedEvent Occurrence Cell)}
    (hprefix : pre <+: trace) :
    authorityWord input pre <+: authorityWord input trace := by
  obtain ⟨suffix, rfl⟩ := hprefix
  rw [authorityWord_append]
  exact List.prefix_append _ _

/-- The authority projection obeys the same receipt-threaded streaming law as
the resolver itself. -/
theorem resolve_authority_word
    (input : Instance Outcome Occurrence Cell Label)
    (receipted : Finset Cell) (left right : List Occurrence) :
    authorityWord input (resolveFrom input.cellOf receipted (left ++ right)) =
      authorityWord input (resolveFrom input.cellOf receipted left) ++
        authorityWord input
          (resolveFrom input.cellOf
            (receiptsAfter input.cellOf receipted left) right) := by
  rw [resolveFrom_streaming, authorityWord_append]

/-- The complete authority history checked for one candidate. -/
def authorityHistory (input : Instance Outcome Occurrence Cell Label)
    (completion : Completion Outcome Occurrence Cell) : List Label :=
  input.durablePrefix ++ authorityWord input completion.trace

omit [DecidableEq Outcome] [DecidableEq Occurrence]
    [DecidableEq Cell] [DecidableEq Label] in
theorem authorityHistory_prefix
    (input : Instance Outcome Occurrence Cell Label)
    {pre : List (ResolvedEvent Occurrence Cell)}
    {completion : Completion Outcome Occurrence Cell}
    (hprefix : pre <+: completion.trace) :
    input.durablePrefix ++ authorityWord input pre
      <+: authorityHistory input completion := by
  simp only [authorityHistory]
  obtain ⟨suffix, hsuffix⟩ := authorityWord_prefix input hprefix
  exact ⟨suffix, by simp [hsuffix, List.append_assoc]⟩

/-- Individually authority-safe candidates, before relational pruning. -/
def B0 (input : Instance Outcome Occurrence Cell Label) :
    Finset (Completion Outcome Occurrence Cell) :=
  (allCandidates input).filter fun completion =>
    authorityHistory input completion ∈ input.authority

/-- All prefixes of a word, including the root and complete word. -/
def prefixes {α : Type*} (word : List α) : List (List α) :=
  (List.range (word.length + 1)).map word.take

/-- Executable well-formedness check for authority-prefix closure. -/
def PolicyPrefixClosed
    (input : Instance Outcome Occurrence Cell Label) : Prop :=
  ∀ word ∈ input.authority, ∀ pre ∈ prefixes word,
    pre ∈ input.authority

/-- Executable well-formedness check for authority-prefix closure. -/
def policyPrefixClosed (input : Instance Outcome Occurrence Cell Label) : Bool :=
  finsetAll input.authority fun word =>
    (prefixes word).all fun pre =>
      decide (pre ∈ input.authority)

theorem policyPrefixClosed_iff
    (input : Instance Outcome Occurrence Cell Label) :
    policyPrefixClosed input = true ↔ PolicyPrefixClosed input := by
  simp [policyPrefixClosed, PolicyPrefixClosed, finsetAll_eq_true]

theorem mem_prefixes_isPrefix {α : Type*} {word pre : List α}
    (hpre : pre ∈ prefixes word) : pre <+: word := by
  simp only [prefixes, List.mem_map] at hpre
  rcases hpre with ⟨index, hindex, rfl⟩
  exact List.take_prefix index word

theorem isPrefix_mem_prefixes {α : Type*} {word pre : List α}
    (hpre : pre <+: word) : pre ∈ prefixes word := by
  obtain ⟨suffix, rfl⟩ := hpre
  simp only [prefixes, List.mem_map]
  refine ⟨pre.length, ?_, ?_⟩ <;> simp

theorem policy_prefix_closure_well_formed
    (input : Instance Outcome Occurrence Cell Label) :
    policyPrefixClosed input = true ↔
      ∀ word ∈ input.authority, ∀ pre, pre <+: word →
        pre ∈ input.authority := by
  rw [policyPrefixClosed_iff]
  constructor
  · intro hclosed word hword pre hprefix
    exact hclosed word hword pre (isPrefix_mem_prefixes hprefix)
  · intro hclosed word hword pre hpre
    exact hclosed word hword pre (mem_prefixes_isPrefix hpre)

/-- Declarative raw-language compatibility. -/
def CompatibleP (input : Instance Outcome Occurrence Cell Label)
    (pre : List (ResolvedEvent Occurrence Cell))
    (outcome : Outcome) : Prop :=
  ∃ linearization ∈ input.linearizations outcome,
    raw pre <+: linearization

/-- Executable bridge for declarative compatibility. -/
def Compatible (input : Instance Outcome Occurrence Cell Label)
    (pre : List (ResolvedEvent Occurrence Cell))
    (outcome : Outcome) : Bool :=
  finsetAny (input.linearizations outcome) fun linearization =>
    decide (raw pre <+: linearization)

theorem compatible_iff (input : Instance Outcome Occurrence Cell Label)
    (pre : List (ResolvedEvent Occurrence Cell)) (outcome : Outcome) :
    Compatible input pre outcome = true ↔
      CompatibleP input pre outcome := by
  simp [Compatible, CompatibleP, finsetAny_eq_true]

/-- Declarative support by an outcome-indexed completion. -/
def SupportsP
    (family : Finset (Completion Outcome Occurrence Cell))
    (pre : List (ResolvedEvent Occurrence Cell))
    (outcome : Outcome) : Prop :=
  ∃ completion ∈ family,
    completion.outcome = outcome ∧ pre <+: completion.trace

/-- Executable bridge for declarative support. -/
def supportsAt (family : Finset (Completion Outcome Occurrence Cell))
    (pre : List (ResolvedEvent Occurrence Cell))
    (outcome : Outcome) : Bool :=
  finsetAny family fun completion =>
    decide (completion.outcome = outcome ∧ pre <+: completion.trace)

theorem supportsAt_iff
    (family : Finset (Completion Outcome Occurrence Cell))
    (pre : List (ResolvedEvent Occurrence Cell)) (outcome : Outcome) :
    supportsAt family pre outcome = true ↔
      SupportsP family pre outcome := by
  simp [supportsAt, SupportsP, finsetAny_eq_true]

/-- Declarative relational robustness of one candidate in a family. -/
def PrefixRobustProp (input : Instance Outcome Occurrence Cell Label)
    (family : Finset (Completion Outcome Occurrence Cell))
    (completion : Completion Outcome Occurrence Cell) : Prop :=
  ∀ pre ∈ prefixes completion.trace, ∀ outcome ∈ input.promised,
    CompatibleP input pre outcome →
      SupportsP family pre outcome

/-- Executable bridge for relational robustness. -/
def prefixRobust (input : Instance Outcome Occurrence Cell Label)
    (family : Finset (Completion Outcome Occurrence Cell))
    (completion : Completion Outcome Occurrence Cell) : Bool :=
  (prefixes completion.trace).all fun pre =>
    finsetAll input.promised fun outcome =>
      !Compatible input pre outcome ||
        supportsAt family pre outcome

theorem prefixRobust_iff
    (input : Instance Outcome Occurrence Cell Label)
    (family : Finset (Completion Outcome Occurrence Cell))
    (completion : Completion Outcome Occurrence Cell) :
    prefixRobust input family completion = true ↔
      PrefixRobustProp input family completion := by
  simp only [prefixRobust, List.all_eq_true, finsetAll_eq_true]
  constructor
  · intro h pre hpre outcome houtcome hcompatible
    have hbool := h pre hpre outcome houtcome
    have hc : Compatible input pre outcome = true :=
      (compatible_iff input pre outcome).2 hcompatible
    rw [hc] at hbool
    have hs : supportsAt family pre outcome = true := by
      simpa using hbool
    exact (supportsAt_iff family pre outcome).1 hs
  · intro h pre hpre outcome houtcome
    by_cases hcompatible : CompatibleP input pre outcome
    · have hsupport := h pre hpre outcome houtcome hcompatible
      have hc : Compatible input pre outcome = true :=
        (compatible_iff input pre outcome).2 hcompatible
      have hs : supportsAt family pre outcome = true :=
        (supportsAt_iff family pre outcome).2 hsupport
      simp [hc, hs]
    · have hfalse : Compatible input pre outcome = false := by
        cases hvalue : Compatible input pre outcome
        · rfl
        · exact False.elim
            (hcompatible ((compatible_iff input pre outcome).1 hvalue))
      simp [hfalse]

/-- One executable descending pruning step. -/
def Phi (input : Instance Outcome Occurrence Cell Label)
    (family : Finset (Completion Outcome Occurrence Cell)) :
    Finset (Completion Outcome Occurrence Cell) :=
  (B0 input).filter fun completion =>
    prefixRobust input family completion = true

theorem supportsP_mono
    {left right : Finset (Completion Outcome Occurrence Cell)}
    (hsubset : left ⊆ right)
    {pre : List (ResolvedEvent Occurrence Cell)} {outcome : Outcome} :
    SupportsP left pre outcome → SupportsP right pre outcome := by
  rintro ⟨completion, hcompletion, houtcome, hprefix⟩
  exact ⟨completion, hsubset hcompletion, houtcome, hprefix⟩

theorem prefixRobustP_mono
    (input : Instance Outcome Occurrence Cell Label)
    {left right : Finset (Completion Outcome Occurrence Cell)}
    (hsubset : left ⊆ right)
    {completion : Completion Outcome Occurrence Cell}
    (hrobust : PrefixRobustProp input left completion) :
    PrefixRobustProp input right completion := by
  intro pre hpre outcome houtcome hcompatible
  exact supportsP_mono hsubset
    (hrobust pre hpre outcome houtcome hcompatible)

/-- The pruning transformer is monotone, although it is not contractive on
arbitrary families because every image is filtered from `B0`. -/
theorem phi_monotone (input : Instance Outcome Occurrence Cell Label)
    {left right : Finset (Completion Outcome Occurrence Cell)}
    (hsubset : left ⊆ right) :
    Phi input left ⊆ Phi input right := by
  intro completion hcompletion
  simp only [Phi, Finset.mem_filter] at hcompletion ⊢
  refine ⟨hcompletion.1, ?_⟩
  exact (prefixRobust_iff input right completion).2
    (prefixRobustP_mono input hsubset
      ((prefixRobust_iff input left completion).1 hcompletion.2))

/-- A postfixed family is individually safe and supports all of its own
prefix obligations. -/
def Postfixed (input : Instance Outcome Occurrence Cell Label)
    (family : Finset (Completion Outcome Occurrence Cell)) : Prop :=
  family ⊆ B0 input ∧ family ⊆ Phi input family

/-- The finite union of every postfixed subfamily of `B0`. -/
def greatestPostfixed (input : Instance Outcome Occurrence Cell Label) :
    Finset (Completion Outcome Occurrence Cell) :=
  ((B0 input).powerset.filter fun family =>
      decide (family ⊆ Phi input family)).biUnion id

theorem mem_greatestPostfixed_iff
    (input : Instance Outcome Occurrence Cell Label)
    (completion : Completion Outcome Occurrence Cell) :
    completion ∈ greatestPostfixed input ↔
      ∃ family, Postfixed input family ∧ completion ∈ family := by
  simp only [greatestPostfixed, Finset.mem_biUnion, Finset.mem_filter,
    Finset.mem_powerset, decide_eq_true_eq, id_eq]
  constructor
  · rintro ⟨family, ⟨hbase, hpost⟩, hcompletion⟩
    exact ⟨family, ⟨hbase, hpost⟩, hcompletion⟩
  · rintro ⟨family, ⟨hbase, hpost⟩, hcompletion⟩
    exact ⟨family, ⟨hbase, hpost⟩, hcompletion⟩

/-- Every postfixed family is contained in the finite greatest one. -/
theorem postfixed_subset (input : Instance Outcome Occurrence Cell Label)
    {family : Finset (Completion Outcome Occurrence Cell)}
    (hpost : Postfixed input family) :
    family ⊆ greatestPostfixed input := by
  intro completion hcompletion
  exact (mem_greatestPostfixed_iff input completion).2
    ⟨family, hpost, hcompletion⟩

theorem greatestPostfixed_postfixed
    (input : Instance Outcome Occurrence Cell Label) :
    Postfixed input (greatestPostfixed input) := by
  constructor
  · intro completion hcompletion
    obtain ⟨family, hfamily, hmember⟩ :=
      (mem_greatestPostfixed_iff input completion).1 hcompletion
    exact hfamily.1 hmember
  · intro completion hcompletion
    obtain ⟨family, hfamily, hmember⟩ :=
      (mem_greatestPostfixed_iff input completion).1 hcompletion
    exact phi_monotone input (postfixed_subset input hfamily)
      (hfamily.2 hmember)

/-- The finite greatest postfixed family is a genuine fixed point. -/
theorem greatestPostfixed_fixed
    (input : Instance Outcome Occurrence Cell Label) :
    Phi input (greatestPostfixed input) = greatestPostfixed input := by
  apply Finset.Subset.antisymm
  · apply postfixed_subset input
    constructor
    · intro completion hcompletion
      exact (Finset.mem_filter.mp hcompletion).1
    · exact phi_monotone input (greatestPostfixed_postfixed input).2
  · exact (greatestPostfixed_postfixed input).2

/-- Iteration of `Phi` from an arbitrary finite seed. -/
def iteratePhi (input : Instance Outcome Occurrence Cell Label)
    (seed : Finset (Completion Outcome Occurrence Cell)) :
    Nat → Finset (Completion Outcome Occurrence Cell)
  | 0 => seed
  | round + 1 => Phi input (iteratePhi input seed round)

/-- The executable pruning sequence beginning at `B0`. -/
def pruningRound (input : Instance Outcome Occurrence Cell Label)
    (round : Nat) : Finset (Completion Outcome Occurrence Cell) :=
  iteratePhi input (B0 input) round

theorem iteratePhi_succ (input : Instance Outcome Occurrence Cell Label)
    (seed : Finset (Completion Outcome Occurrence Cell)) (round : Nat) :
    iteratePhi input seed (round + 1) =
      Phi input (iteratePhi input seed round) := rfl

theorem iteratePhi_succ_seed
    (input : Instance Outcome Occurrence Cell Label)
    (seed : Finset (Completion Outcome Occurrence Cell)) (round : Nat) :
    iteratePhi input seed (round + 1) =
      iteratePhi input (Phi input seed) round := by
  induction round with
  | zero => rfl
  | succ round ih =>
      simp only [iteratePhi]
      exact congrArg (Phi input) ih

theorem pruningRound_descending
    (input : Instance Outcome Occurrence Cell Label) (round : Nat) :
    pruningRound input (round + 1) ⊆ pruningRound input round := by
  induction round with
  | zero =>
      intro completion hcompletion
      exact (Finset.mem_filter.mp hcompletion).1
  | succ round ih =>
      exact phi_monotone input ih

theorem iteratePhi_stabilizes
    (input : Instance Outcome Occurrence Cell Label)
    (seed : Finset (Completion Outcome Occurrence Cell))
    (hcontractive : Phi input seed ⊆ seed) :
    ∃ round ≤ seed.card,
      Phi input (iteratePhi input seed round) =
        iteratePhi input seed round := by
  induction seed using Finset.strongInduction with
  | H seed ih =>
      by_cases hfixed : Phi input seed = seed
      · exact ⟨0, Nat.zero_le _, by simpa [iteratePhi] using hfixed⟩
      · have hstrict : Phi input seed ⊂ seed :=
          Finset.ssubset_iff_subset_ne.2 ⟨hcontractive, hfixed⟩
        have hnext :
            Phi input (Phi input seed) ⊆ Phi input seed :=
          phi_monotone input hcontractive
        obtain ⟨round, hround, hstable⟩ :=
          ih (Phi input seed) hstrict hnext
        refine ⟨round + 1, ?_, ?_⟩
        · have hcard := Finset.card_lt_card hstrict
          omega
        · calc
            Phi input (iteratePhi input seed (round + 1)) =
                Phi input (iteratePhi input (Phi input seed) round) :=
              congrArg (Phi input)
                (iteratePhi_succ_seed input seed round)
            _ = iteratePhi input (Phi input seed) round := hstable
            _ = iteratePhi input seed (round + 1) :=
              (iteratePhi_succ_seed input seed round).symm

theorem iteratePhi_fixed_after
    (input : Instance Outcome Occurrence Cell Label)
    (seed : Finset (Completion Outcome Occurrence Cell))
    {round : Nat}
    (hfixed : Phi input (iteratePhi input seed round) =
      iteratePhi input seed round) :
    ∀ extra,
      iteratePhi input seed (round + extra) =
        iteratePhi input seed round := by
  intro extra
  induction extra with
  | zero => rfl
  | succ extra ih =>
      rw [Nat.add_succ, iteratePhi, ih, hfixed]

/-- The bounded iteration is stable for every finite instance. -/
theorem pruningRound_stabilizes
    (input : Instance Outcome Occurrence Cell Label) :
    Phi input (pruningRound input (B0 input).card) =
      pruningRound input (B0 input).card := by
  have hfirst : Phi input (B0 input) ⊆ B0 input := by
    intro completion hcompletion
    exact (Finset.mem_filter.mp hcompletion).1
  obtain ⟨round, hround, hfixed⟩ :=
    iteratePhi_stabilizes input (B0 input) hfirst
  obtain ⟨extra, hextra⟩ := Nat.exists_eq_add_of_le hround
  rw [hextra]
  have hsame := iteratePhi_fixed_after input (B0 input) hfixed extra
  simp only [pruningRound] at hsame ⊢
  rw [hsame, hfixed]

/-- A descending family over `B0` makes at most `|B0|` strict deletions. -/
def boundedFixedPoint (input : Instance Outcome Occurrence Cell Label) :
    Finset (Completion Outcome Occurrence Cell) :=
  pruningRound input (B0 input).card

theorem greatestPostfixed_subset_pruningRound
    (input : Instance Outcome Occurrence Cell Label) (round : Nat) :
    greatestPostfixed input ⊆ pruningRound input round := by
  induction round with
  | zero =>
      exact (greatestPostfixed_postfixed input).1
  | succ round ih =>
      rw [pruningRound, iteratePhi]
      rw [← greatestPostfixed_fixed input]
      exact phi_monotone input ih

/-- Executing exactly `|B0|` pruning rounds computes the finite greatest
fixed point. -/
theorem boundedFixedPoint_eq_greatestPostfixed
    (input : Instance Outcome Occurrence Cell Label) :
    boundedFixedPoint input = greatestPostfixed input := by
  apply Finset.Subset.antisymm
  · apply postfixed_subset input
    have hfixed := pruningRound_stabilizes input
    constructor
    · intro completion hcompletion
      simp only [boundedFixedPoint] at hcompletion
      rw [← hfixed] at hcompletion
      exact (Finset.mem_filter.mp hcompletion).1
    · intro completion hcompletion
      simp only [boundedFixedPoint] at hcompletion ⊢
      rw [hfixed]
      exact hcompletion
  · exact greatestPostfixed_subset_pruningRound input (B0 input).card

/-- Complete resolved event words of a family. -/
def words (family : Finset (Completion Outcome Occurrence Cell)) :
    Finset (List (ResolvedEvent Occurrence Cell)) :=
  family.image Completion.trace

/-- Finite prefix closure of a finite word language. -/
def prefClosure
    (language : Finset (List (ResolvedEvent Occurrence Cell))) :
    Finset (List (ResolvedEvent Occurrence Cell)) :=
  language.biUnion fun word => (prefixes word).toFinset

/-- The uniquely generated monitor language for a completion family. -/
def Wof (input : Instance Outcome Occurrence Cell Label)
    (family : Finset (Completion Outcome Occurrence Cell)) :
    Finset (List (ResolvedEvent Occurrence Cell)) :=
  prefClosure (words family)

/-- The ordered durable receipt ledger must not repeat a semantic cell.  This
is the binding well-formedness premise that makes its list order and derived
receipt set describe the same cut without duplicate entries. -/
def ReceiptCutWellFormed
    (input : Instance Outcome Occurrence Cell Label) : Prop :=
  input.durableReceiptCells.Nodup

/-- Binding well-formedness needed by admission: authority policies are
prefix-closed and the single-source durable receipt ledger has no duplicates. -/
def ValidInstance (input : Instance Outcome Occurrence Cell Label) : Prop :=
  PolicyPrefixClosed input ∧ ReceiptCutWellFormed input

/-- Executable validity check used by both decision routes. -/
def validInstance (input : Instance Outcome Occurrence Cell Label) : Bool :=
  policyPrefixClosed input &&
    decide input.durableReceiptCells.Nodup

theorem validInstance_iff
    (input : Instance Outcome Occurrence Cell Label) :
    validInstance input = true ↔ ValidInstance input := by
  simp [validInstance, ValidInstance, ReceiptCutWellFormed,
    policyPrefixClosed_iff]

/-- Paper-level declarative realization.  The generated language `language`,
candidate fidelity, prefix safety, exact language equality, and
outcome-indexed support obligations are explicit; the definition does not
mention `Phi`. -/
def Realization (input : Instance Outcome Occurrence Cell Label)
    (language : Finset (List (ResolvedEvent Occurrence Cell)))
    (family : Finset (Completion Outcome Occurrence Cell)) : Prop :=
  family.Nonempty ∧
    family ⊆ allCandidates input ∧
    language ⊆ Wof input (allCandidates input) ∧
    (∀ pre ∈ language,
      input.durablePrefix ++ authorityWord input pre ∈ input.authority) ∧
    language = Wof input family ∧
    ∀ pre ∈ language, ∀ outcome ∈ input.promised,
      CompatibleP input pre outcome →
        SupportsP family pre outcome

/-- Admission quantifies over realizations of valid registered instances.
Keeping this wrapper separate leaves the frozen mathematical core
`Realization` free of policy-closure or receipt-ledger premises. -/
def ValidRealization (input : Instance Outcome Occurrence Cell Label)
    (language : Finset (List (ResolvedEvent Occurrence Cell)))
    (family : Finset (Completion Outcome Occurrence Cell)) : Prop :=
  ValidInstance input ∧ Realization input language family

/-- Executable check used by the finite enumeration route.  Its conditions
are the Boolean counterparts of the declarative realization obligations. -/
def RealizationCheck (input : Instance Outcome Occurrence Cell Label)
    (family : Finset (Completion Outcome Occurrence Cell)) : Bool :=
  validInstance input &&
    family.card != 0 &&
    decide (family ⊆ allCandidates input) &&
    (finsetAll family fun completion =>
      (prefixes completion.trace).all fun pre =>
        decide
            (input.durablePrefix ++ authorityWord input pre ∈
              input.authority) &&
          finsetAll input.promised fun outcome =>
            !Compatible input pre outcome ||
              supportsAt family pre outcome)

theorem mem_Wof_iff
    (input : Instance Outcome Occurrence Cell Label)
    (family : Finset (Completion Outcome Occurrence Cell))
    (pre : List (ResolvedEvent Occurrence Cell)) :
    pre ∈ Wof input family ↔
      ∃ completion ∈ family, pre ∈ prefixes completion.trace := by
  simp [Wof, prefClosure, words]

theorem Wof_mono
    (input : Instance Outcome Occurrence Cell Label)
    {left right : Finset (Completion Outcome Occurrence Cell)}
    (hsubset : left ⊆ right) :
    Wof input left ⊆ Wof input right := by
  intro pre hpre
  obtain ⟨completion, hcompletion, hpref⟩ :=
    (mem_Wof_iff input left pre).1 hpre
  exact (mem_Wof_iff input right pre).2
    ⟨completion, hsubset hcompletion, hpref⟩

theorem realizationCheck_iff
    (input : Instance Outcome Occurrence Cell Label)
    (family : Finset (Completion Outcome Occurrence Cell)) :
    RealizationCheck input family = true ↔
      ValidRealization input (Wof input family) family := by
  simp only [RealizationCheck, Bool.and_eq_true, validInstance_iff,
    bne_iff_ne, decide_eq_true_eq, finsetAll_eq_true, List.all_eq_true]
  constructor
  · rintro ⟨⟨⟨hvalid, hnonemptySet⟩, hfidelity⟩, hsafety⟩
    have hnonempty : family.Nonempty :=
      Finset.card_ne_zero.mp hnonemptySet
    refine ⟨hvalid, hnonempty, hfidelity, Wof_mono input hfidelity,
      ?_, rfl, ?_⟩
    · intro pre hpre
      obtain ⟨completion, hcompletion, hpref⟩ :=
        (mem_Wof_iff input family pre).1 hpre
      exact (hsafety completion hcompletion pre hpref).1
    · intro pre hpre outcome houtcome hcompatible
      obtain ⟨completion, hcompletion, hpref⟩ :=
        (mem_Wof_iff input family pre).1 hpre
      have hbool := (hsafety completion hcompletion pre hpref).2
        outcome houtcome
      have hc : Compatible input pre outcome = true :=
        (compatible_iff input pre outcome).2 hcompatible
      rw [hc] at hbool
      have hs : supportsAt family pre outcome = true := by
        simpa using hbool
      exact (supportsAt_iff family pre outcome).1 hs
  · rintro ⟨hvalid, hrealization⟩
    refine ⟨⟨⟨hvalid, ?_⟩, hrealization.2.1⟩, ?_⟩
    · exact Finset.card_ne_zero.mpr hrealization.1
    · intro completion hcompletion pre hpref
      have hpreW : pre ∈ Wof input family :=
        (mem_Wof_iff input family pre).2
          ⟨completion, hcompletion, hpref⟩
      constructor
      · exact hrealization.2.2.2.1 pre hpreW
      · intro outcome houtcome
        by_cases hcompatible : CompatibleP input pre outcome
        · have hsupport := hrealization.2.2.2.2.2 pre hpreW
            outcome houtcome hcompatible
          have hc := (compatible_iff input pre outcome).2 hcompatible
          have hs := (supportsAt_iff family pre outcome).2 hsupport
          simp [hc, hs]
        · have hc : Compatible input pre outcome = false := by
            cases hvalue : Compatible input pre outcome
            · rfl
            · exact False.elim
                (hcompatible ((compatible_iff input pre outcome).1 hvalue))
          simp [hc]

theorem realization_postfixed
    (input : Instance Outcome Occurrence Cell Label)
    {language : Finset (List (ResolvedEvent Occurrence Cell))}
    {family : Finset (Completion Outcome Occurrence Cell)}
    (hrealization : Realization input language family) :
    Postfixed input family := by
  rcases hrealization with
    ⟨hnonempty, hfidelity, hlanguageBound, hauthority, hlanguage, hrobust⟩
  constructor
  · intro completion hcompletion
    simp only [B0, Finset.mem_filter]
    refine ⟨hfidelity hcompletion, ?_⟩
    apply hauthority completion.trace
    rw [hlanguage]
    exact (mem_Wof_iff input family completion.trace).2
      ⟨completion, hcompletion,
        isPrefix_mem_prefixes (List.prefix_refl _)⟩
  · intro completion hcompletion
    simp only [Phi, Finset.mem_filter]
    refine ⟨?_, (prefixRobust_iff input family completion).2 ?_⟩
    · simp only [B0, Finset.mem_filter]
      exact ⟨hfidelity hcompletion,
        hauthority completion.trace (by
          rw [hlanguage]
          exact (mem_Wof_iff input family completion.trace).2
            ⟨completion, hcompletion,
              isPrefix_mem_prefixes (List.prefix_refl _)⟩)⟩
    · intro pre hpre outcome houtcome hcompatible
      apply hrobust pre
      · rw [hlanguage]
        exact (mem_Wof_iff input family pre).2
          ⟨completion, hcompletion, hpre⟩
      · exact houtcome
      · exact hcompatible

theorem postfixed_realization
    (input : Instance Outcome Occurrence Cell Label)
    (hvalid : ValidInstance input)
    {family : Finset (Completion Outcome Occurrence Cell)}
    (hpost : Postfixed input family) (hnonempty : family.Nonempty) :
    Realization input (Wof input family) family := by
  refine ⟨hnonempty, ?_, ?_, ?_, rfl, ?_⟩
  · intro completion hcompletion
    exact (Finset.mem_filter.mp (hpost.1 hcompletion)).1
  · intro pre hpre
    obtain ⟨completion, hcompletion, hprefix⟩ :=
      (mem_Wof_iff input family pre).1 hpre
    exact (mem_Wof_iff input (allCandidates input) pre).2
      ⟨completion, (Finset.mem_filter.mp (hpost.1 hcompletion)).1,
        hprefix⟩
  · intro pre hpre
    obtain ⟨completion, hcompletion, hprefix⟩ :=
      (mem_Wof_iff input family pre).1 hpre
    have hbase := hpost.1 hcompletion
    have hwhole :
        authorityHistory input completion ∈ input.authority :=
      (Finset.mem_filter.mp hbase).2
    have hpref :
        input.durablePrefix ++ authorityWord input pre
          <+: authorityHistory input completion :=
      authorityHistory_prefix input
        (mem_prefixes_isPrefix hprefix)
    exact hvalid.1 (authorityHistory input completion) hwhole
      (input.durablePrefix ++ authorityWord input pre)
      (isPrefix_mem_prefixes hpref)
  · intro pre hpre outcome houtcome hcompatible
    obtain ⟨completion, hcompletion, hprefix⟩ :=
      (mem_Wof_iff input family pre).1 hpre
    have hrobust :
        PrefixRobustProp input family completion :=
      (prefixRobust_iff input family completion).1
        (Finset.mem_filter.mp (hpost.2 hcompletion)).2
    exact hrobust pre hprefix outcome houtcome hcompatible

/-- Every declarative realization is contained in the greatest compiled
family. -/
theorem realization_subset_greatestPostfixed
    (input : Instance Outcome Occurrence Cell Label)
    {language : Finset (List (ResolvedEvent Occurrence Cell))}
    {family : Finset (Completion Outcome Occurrence Cell)}
    (hrealization : Realization input language family) :
    language ⊆ Wof input (greatestPostfixed input) ∧
      family ⊆ greatestPostfixed input := by
  have hfamily :=
    postfixed_subset input (realization_postfixed input hrealization)
  constructor
  · rw [hrealization.2.2.2.2.1]
    exact Wof_mono input hfamily
  · exact hfamily

/-- Under the binding finite-instance premises, the greatest fixed point is a
declarative realization exactly when it is nonempty. -/
theorem greatestPostfixed_is_realization_iff_nonempty
    (input : Instance Outcome Occurrence Cell Label)
    (hvalid : ValidInstance input) :
    Realization input (Wof input (greatestPostfixed input))
        (greatestPostfixed input) ↔
      (greatestPostfixed input).Nonempty := by
  constructor
  · exact fun hrealization => hrealization.1
  · exact postfixed_realization input hvalid
      (greatestPostfixed_postfixed input)

/-- A declarative realization exists iff the greatest compiled family is
nonempty. -/
theorem exists_realization_iff_greatestPostfixed_nonempty
    (input : Instance Outcome Occurrence Cell Label)
    (hvalid : ValidInstance input) :
    (∃ language family, Realization input language family) ↔
      (greatestPostfixed input).Nonempty := by
  constructor
  · rintro ⟨language, family, hrealization⟩
    obtain ⟨completion, hcompletion⟩ := hrealization.1
    exact ⟨completion,
      (realization_subset_greatestPostfixed input hrealization).2
        hcompletion⟩
  · intro hnonempty
    exact ⟨Wof input (greatestPostfixed input), greatestPostfixed input,
      (greatestPostfixed_is_realization_iff_nonempty input hvalid).2
        hnonempty⟩

/-- Without assuming validity externally, a valid declarative realization
exists exactly when the registered instance is valid and the greatest
compiled family is nonempty. -/
theorem exists_validRealization_iff
    (input : Instance Outcome Occurrence Cell Label) :
    (∃ language family, ValidRealization input language family) ↔
      ValidInstance input ∧ (greatestPostfixed input).Nonempty := by
  constructor
  · rintro ⟨language, family, hvalid, hrealization⟩
    exact ⟨hvalid,
      (exists_realization_iff_greatestPostfixed_nonempty input hvalid).1
        ⟨language, family, hrealization⟩⟩
  · rintro ⟨hvalid, hnonempty⟩
    obtain ⟨language, family, hrealization⟩ :=
      (exists_realization_iff_greatestPostfixed_nonempty input hvalid).2
        hnonempty
    exact ⟨language, family, hvalid, hrealization⟩

/-- Componentwise maximality of both the monitor language and completion
family among declarative realizations. -/
def GreatestRealization (input : Instance Outcome Occurrence Cell Label)
    (language : Finset (List (ResolvedEvent Occurrence Cell)))
    (family : Finset (Completion Outcome Occurrence Cell)) : Prop :=
  Realization input language family ∧
    ∀ otherLanguage otherFamily,
      Realization input otherLanguage otherFamily →
        otherLanguage ⊆ language ∧ otherFamily ⊆ family

theorem greatestPostfixed_is_greatestRealization
    (input : Instance Outcome Occurrence Cell Label)
    (hvalid : ValidInstance input)
    (hnonempty : (greatestPostfixed input).Nonempty) :
    GreatestRealization input
      (Wof input (greatestPostfixed input))
      (greatestPostfixed input) := by
  constructor
  · exact (greatestPostfixed_is_realization_iff_nonempty
      input hvalid).2 hnonempty
  · intro otherLanguage otherFamily hrealization
    exact realization_subset_greatestPostfixed input hrealization

/-- Valid componentwise maximality packages instance validity with the frozen
core greatest-realization theorem. -/
def ValidGreatestRealization
    (input : Instance Outcome Occurrence Cell Label)
    (language : Finset (List (ResolvedEvent Occurrence Cell)))
    (family : Finset (Completion Outcome Occurrence Cell)) : Prop :=
  ValidInstance input ∧ GreatestRealization input language family

theorem greatestPostfixed_is_validGreatestRealization
    (input : Instance Outcome Occurrence Cell Label)
    (hvalid : ValidInstance input)
    (hnonempty : (greatestPostfixed input).Nonempty) :
    ValidGreatestRealization input
      (Wof input (greatestPostfixed input))
      (greatestPostfixed input) :=
  ⟨hvalid,
    greatestPostfixed_is_greatestRealization input hvalid hnonempty⟩

inductive Ans where
  | admit
  | reject
deriving DecidableEq, Repr

/-- Declarative finite answer obtained by enumerating every subfamily of the
constructionally derived candidates and checking `ValidRealization`. -/
def SemanticAns (input : Instance Outcome Occurrence Cell Label) : Ans :=
  if finsetAny (allCandidates input).powerset fun family =>
      RealizationCheck input family then
    .admit
  else
    .reject

/-- Executable compiler answer obtained from full instance validation and
bounded pruning.  Malformed policies or durable receipt ledgers fail closed. -/
def CompilerAns (input : Instance Outcome Occurrence Cell Label) : Ans :=
  if validInstance input then
    if (boundedFixedPoint input).Nonempty then .admit else .reject
  else
    .reject

/-- The independent finite semantic enumeration admits exactly when some
valid declarative realization exists. -/
theorem semanticEnumeration_iff_exists_validRealization
    (input : Instance Outcome Occurrence Cell Label) :
    finsetAny (allCandidates input).powerset
        (fun family => RealizationCheck input family) = true ↔
      ∃ language family, ValidRealization input language family := by
  constructor
  · intro hsemantic
    obtain ⟨family, hfamily, hcheck⟩ :=
      (finsetAny_eq_true _ _).1 hsemantic
    exact ⟨Wof input family, family,
      (realizationCheck_iff input family).1 hcheck⟩
  · rintro ⟨language, family, hvalid, hrealization⟩
    apply (finsetAny_eq_true _ _).2
    refine ⟨family, ?_, ?_⟩
    · rw [Finset.mem_powerset]
      exact hrealization.2.1
    · apply (realizationCheck_iff input family).2
      refine ⟨hvalid, ?_⟩
      simpa [hrealization.2.2.2.2.1] using hrealization

/-- The semantic route's public answer is exactly existential valid
realizability. -/
theorem semanticAns_eq_admit_iff_exists_validRealization
    (input : Instance Outcome Occurrence Cell Label) :
    SemanticAns input = .admit ↔
      ∃ language family, ValidRealization input language family := by
  rw [← semanticEnumeration_iff_exists_validRealization input]
  unfold SemanticAns
  split <;> simp_all

/-- The executable compiler admits exactly valid instances with a nonempty
greatest fixed point. -/
theorem compilerAns_eq_admit_iff
    (input : Instance Outcome Occurrence Cell Label) :
    CompilerAns input = .admit ↔
      ValidInstance input ∧ (greatestPostfixed input).Nonempty := by
  unfold CompilerAns
  cases hvalidBool : validInstance input with
  | false =>
      have hnotValid : ¬ ValidInstance input := by
        intro hvalid
        have : validInstance input = true :=
          (validInstance_iff input).2 hvalid
        simp [hvalidBool] at this
      simp [hvalidBool, hnotValid]
  | true =>
      have hvalid : ValidInstance input :=
        (validInstance_iff input).1 hvalidBool
      rw [boundedFixedPoint_eq_greatestPostfixed]
      by_cases hnonempty : (greatestPostfixed input).Nonempty
      · simp [hvalidBool, hvalid, hnonempty]
      · simp [hvalidBool, hvalid, hnonempty]

/-- Public admission is precisely existence of a valid declarative
realization. -/
theorem admit_iff_exists_validRealization
    (input : Instance Outcome Occurrence Cell Label) :
    CompilerAns input = .admit ↔
      ∃ language family, ValidRealization input language family := by
  rw [compilerAns_eq_admit_iff, exists_validRealization_iff]

/-- The executable compiler and independent finite semantic enumeration agree
for every finite input, including malformed policies and receipt ledgers. -/
theorem compiler_eq_semantic
    (input : Instance Outcome Occurrence Cell Label) :
    CompilerAns input = SemanticAns input := by
  cases hcompiler : CompilerAns input <;>
    cases hsemantic : SemanticAns input
  · rfl
  · exfalso
    have hexists :
        ∃ language family, ValidRealization input language family :=
      (admit_iff_exists_validRealization input).1 hcompiler
    have : SemanticAns input = .admit :=
      (semanticAns_eq_admit_iff_exists_validRealization input).2 hexists
    simp [hsemantic] at this
  · exfalso
    have hexists :
        ∃ language family, ValidRealization input language family :=
      (semanticAns_eq_admit_iff_exists_validRealization input).1 hsemantic
    have : CompilerAns input = .admit :=
      (admit_iff_exists_validRealization input).2 hexists
    simp [hcompiler] at this
  · rfl

/-- Invalid registered instances fail closed on the compiler route. -/
theorem compiler_rejects_invalid_instance
    (input : Instance Outcome Occurrence Cell Label)
    (hinvalid : ¬ ValidInstance input) :
    CompilerAns input = .reject := by
  cases hanswer : CompilerAns input with
  | admit =>
      exfalso
      obtain ⟨language, family, hvalid, hrealization⟩ :=
        (admit_iff_exists_validRealization input).1 hanswer
      exact hinvalid hvalid
  | reject =>
      rfl

/-- Invalid registered instances also fail closed on the independent semantic
route. -/
theorem semantic_rejects_invalid_instance
    (input : Instance Outcome Occurrence Cell Label)
    (hinvalid : ¬ ValidInstance input) :
    SemanticAns input = .reject := by
  rw [← compiler_eq_semantic input]
  exact compiler_rejects_invalid_instance input hinvalid

/-- In particular, a duplicate semantic cell in the durable receipt ledger is
rejected by both routes, independently of the fixed-point result. -/
theorem malformed_receipt_cut_fails_closed
    (input : Instance Outcome Occurrence Cell Label)
    (hmalformed : ¬ input.durableReceiptCells.Nodup) :
    CompilerAns input = .reject ∧ SemanticAns input = .reject := by
  have hinvalid : ¬ ValidInstance input := by
    intro hvalid
    exact hmalformed hvalid.2
  exact ⟨compiler_rejects_invalid_instance input hinvalid,
    semantic_rejects_invalid_instance input hinvalid⟩

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
  durableReceiptCells := []
  authority := authority
  labelOf := labelOf

/-- The paper fixture uses one empty ordered durable ledger, from which both
the empty receipt set and empty authority prefix are derived.
Occurrence-to-cell and cell-to-label maps are explicit. -/
theorem single_source_cut_and_maps :
    fixture.durableReceiptCells = [] ∧
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
