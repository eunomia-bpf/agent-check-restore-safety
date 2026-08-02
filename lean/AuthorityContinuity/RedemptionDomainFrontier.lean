import Mathlib.Data.Finset.Card

/-!
# Redemption-domain frontier

This module separates event identity, history occurrence, and redemption-cell
identity.  A `Domain` value denotes one shared, durable, linearizable one-shot
cell.  It is not a caller-provided label: two cloned databases with the same
textual label are different domains unless they coordinate through the same
linearization point.

The operational layer counts newly minted commitment receipts and
monotonically grows the set of spent cells.  The fixed-horizon layer then
proves a general upper
bound for lifecycle-feasible extensions.  Equality with the number of unused
active cells is deliberately conditional on solo availability and cross-cell
product independence.  Exclusive choices can make the upper bound strict.
-/

namespace AuthorityContinuity.RedemptionDomainFrontier

universe uA uO uD uK uR uS

/-! ## Operation keys, receipts, and API responses -/

/-- A linearizer-minted authorization receipt is identified by the semantic
cell and a cell-local sequence.  A production receipt would additionally bind
the token, operation digest, epoch, and fence generation. -/
structure AuthorizationReceipt (Domain : Type uD) (Sequence : Type uS) where
  cell : Domain
  localSequence : Sequence
  deriving DecidableEq

/-- A successful API response returns a receipt for a caller operation key.
Retries may produce several successful responses carrying the same receipt. -/
structure ApiSuccess (Operation : Type uK) (Receipt : Type uR) where
  operation : Operation
  receipt : Receipt

def distinctReceipts [DecidableEq Receipt]
    (responses : List (ApiSuccess Operation Receipt)) : Finset Receipt :=
  (responses.map ApiSuccess.receipt).toFinset

def distinctOperationKeys [DecidableEq Operation]
    (responses : List (ApiSuccess Operation Receipt)) : Finset Operation :=
  (responses.map ApiSuccess.operation).toFinset

namespace ResponseIdentity

abbrev Receipt := AuthorizationReceipt Bool Nat

def firstReceipt : Receipt := ⟨false, 0⟩
def secondCellReceipt : Receipt := ⟨true, 0⟩

def retryResponses : List (ApiSuccess Unit Receipt) :=
  [⟨(), firstReceipt⟩, ⟨(), firstReceipt⟩]

def crossCellResponses : List (ApiSuccess Unit Receipt) :=
  [⟨(), firstReceipt⟩, ⟨(), secondCellReceipt⟩]

/-- Two successful retry responses carrying one receipt are one authority
commitment, not two. -/
theorem retry_successes_share_one_commitment :
    (distinctReceipts retryResponses).card = 1 := by
  decide

/-- Reusing one caller operation key at two independent cells creates two
authorization commitments.  Deduplicating only by operation key would hide
the split. -/
theorem same_operation_two_cells_create_two_commitments :
    (distinctOperationKeys crossCellResponses).card = 1 ∧
      (distinctReceipts crossCellResponses).card = 2 ∧
      firstReceipt.cell ≠ secondCellReceipt.cell := by
  decide

end ResponseIdentity

/-! ## Operational one-shot redemption -/

section Operational

variable {Attempt : Type uA} {Domain : Type uD}
variable [DecidableEq Domain]

/-- A finite run of newly linearized authority commitments.  The list stores
linearizer-minted receipt/event identities, not all successful API responses:
a retry returning an existing receipt does not add a constructor.  Two fresh
commitments produced from one restored occurrence are still counted twice.
Each commit step atomically consumes a previously unspent semantic cell.
-/
inductive OneShotRun (cellOf : Attempt -> Domain) :
    Finset Domain -> List Attempt -> Finset Domain -> Prop
  | nil (spent) : OneShotRun cellOf spent [] spent
  | commit {spent : Finset Domain} {attempt : Attempt}
      {tail : List Attempt} {final : Finset Domain}
      (fresh : cellOf attempt ∉ spent)
      (rest : OneShotRun cellOf (insert (cellOf attempt) spent) tail final) :
      OneShotRun cellOf spent (attempt :: tail) final

namespace OneShotRun

/-- Durable spent history grows monotonically over every successful run. -/
theorem spent_mono {cellOf : Attempt -> Domain}
    {spent final : Finset Domain} {accepted : List Attempt}
    (run : OneShotRun cellOf spent accepted final) : spent ⊆ final := by
  induction run with
  | nil => exact Finset.Subset.rfl
  | commit _ rest ih =>
      exact (Finset.subset_insert _ _).trans ih

/-- New commitment count is exactly the growth of durable spent-cell state.
This theorem counts minted receipt events, not API responses or occurrences,
so rollback cannot hide a second commitment by collapsing it into an
occurrence set. -/
theorem final_card_eq_initial_add_commitment_length
    {cellOf : Attempt -> Domain} {spent final : Finset Domain}
    {accepted : List Attempt}
    (run : OneShotRun cellOf spent accepted final) :
    final.card = spent.card + accepted.length := by
  induction run with
  | nil => simp
  | commit fresh rest ih =>
      rw [ih, Finset.card_insert_of_notMem fresh]
      simp [Nat.add_comm, Nat.add_left_comm]

/-- If all new commitments came from one finite offered horizon, the final
spent set is contained in the old spent cells plus cells named by that
horizon. -/
theorem final_subset_initial_union_offered
    {cellOf : Attempt -> Domain} {spent final : Finset Domain}
    {accepted : List Attempt} (offered : Finset Attempt)
    [DecidableEq Attempt]
    (run : OneShotRun cellOf spent accepted final)
    (within : forall attempt, attempt ∈ accepted -> attempt ∈ offered) :
    final ⊆ spent ∪ offered.image cellOf := by
  induction run with
  | nil =>
      exact Finset.subset_union_left
  | @commit spent attempt tail final fresh rest ih =>
      have hAttempt : attempt ∈ offered := within attempt (by simp)
      have hTail : forall a, a ∈ tail -> a ∈ offered := by
        intro a ha
        exact within a (by simp [ha])
      have hSubset := ih hTail
      intro d hd
      have hd' := hSubset hd
      simp only [Finset.mem_union, Finset.mem_insert] at hd' ⊢
      rcases hd' with (rfl | hSpent) | hOffered
      · right
        exact Finset.mem_image.mpr ⟨attempt, hAttempt, rfl⟩
      · exact Or.inl hSpent
      · exact Or.inr hOffered

/-- Operational finite-horizon frontier.  Existing consumed cells are part
of the left-hand side; new commitment receipts cannot be hidden by restoring
the same occurrence and issuing a fresh receipt identifier. -/
theorem initial_card_add_commitment_length_le_reachable_card
    {cellOf : Attempt -> Domain} {spent final : Finset Domain}
    {accepted : List Attempt} (offered : Finset Attempt)
    [DecidableEq Attempt]
    (run : OneShotRun cellOf spent accepted final)
    (within : forall attempt, attempt ∈ accepted -> attempt ∈ offered) :
    spent.card + accepted.length <=
      (spent ∪ offered.image cellOf).card := by
  rw [← run.final_card_eq_initial_add_commitment_length]
  exact Finset.card_le_card
    (run.final_subset_initial_union_offered offered within)

end OneShotRun

end Operational

/-! ## Fixed-horizon lifecycle frontier -/

variable {Attempt : Type uA} {Occurrence : Type uO} {Domain : Type uD}
variable [DecidableEq Attempt] [DecidableEq Domain]

/-- A fixed analysis horizon.  `committed` records retained freshly minted
receipt/event identities, while `consumed` is the authoritative durable
spent-cell set and may also cover pruned event history or existing
ticket/receipt bindings.  It is a global controller log, not a local set
reconstructed by merging workspaces.  `offered` contains potential fresh
commitment-event identities, not ordinary retry responses.  Several events
may have the same `occurrenceOf` value after rollback, while `cellOf` resolves
the actual shared one-shot cell used by each event. -/
structure FixedHorizon (Attempt : Type uA) (Occurrence : Type uO)
    (Domain : Type uD) where
  committed : Finset Attempt
  consumed : Finset Domain
  offered : Finset Attempt
  occurrenceOf : Attempt -> Occurrence
  cellOf : Attempt -> Domain

/-- Cells already consumed by durable tickets, receipts, or accepted events.
-/
def consumedCells (H : FixedHorizon Attempt Occurrence Domain) :
    Finset Domain :=
  H.consumed

/-- Cells mentioned by offered attempts that are not already consumed. -/
def unusedActiveCells (H : FixedHorizon Attempt Occurrence Domain) :
    Finset Domain :=
  H.offered.image H.cellOf \ consumedCells H

/-- All consumed or offered cells visible in this fixed horizon. -/
def reachableCells (H : FixedHorizon Attempt Occurrence Domain) :
    Finset Domain :=
  consumedCells H ∪ H.offered.image H.cellOf

/-- Current history occurrences, intentionally distinct from attempt-event
identities and semantic redemption-cell identities. -/
def activeOccurrences (H : FixedHorizon Attempt Occurrence Domain)
    [DecidableEq Occurrence] : Finset Occurrence :=
  H.offered.image H.occurrenceOf

/-- Retained committed events have distinct cells and are covered by the
authoritative durable consumed-cell history.  The consumed set may contain
additional cells whose event records were pruned. -/
structure HistoryValid
    (H : FixedHorizon Attempt Occurrence Domain) : Prop where
  committedSinglePerCell :
    Set.InjOn H.cellOf (H.committed : Set Attempt)
  committedCellsConsumed :
    H.committed.image H.cellOf ⊆ consumedCells H

/-- Lifecycle feasibility is supplied independently of one-shot safety.  In
particular, choice branches may be mutually exclusive even when they use
different cells.  `singlePerCell` and `avoidsConsumed` are explicit refinement
premises expected from a shared linearizable one-shot CAS; the cardinality
lemmas below do not by themselves derive that runtime property. -/
structure AdmissibleExtension
    (H : FixedHorizon Attempt Occurrence Domain)
    (LifecycleFeasible : Finset Attempt -> Prop)
    (accepted : Finset Attempt) : Prop where
  withinOffered : accepted ⊆ H.offered
  freshAttempts : Disjoint accepted H.committed
  singlePerCell : Set.InjOn H.cellOf (accepted : Set Attempt)
  avoidsConsumed :
    Disjoint (accepted.image H.cellOf) (consumedCells H)
  lifecycleFeasible : LifecycleFeasible accepted

theorem acceptedCells_subset_unusedActiveCells
    {H : FixedHorizon Attempt Occurrence Domain}
    {LifecycleFeasible : Finset Attempt -> Prop}
    {accepted : Finset Attempt}
    (h : AdmissibleExtension H LifecycleFeasible accepted) :
    accepted.image H.cellOf ⊆ unusedActiveCells H := by
  intro d hd
  obtain ⟨attempt, hAttempt, rfl⟩ := Finset.mem_image.mp hd
  apply Finset.mem_sdiff.mpr
  constructor
  · exact Finset.mem_image.mpr
      ⟨attempt, h.withinOffered hAttempt, rfl⟩
  · intro hConsumed
    exact Finset.disjoint_left.mp h.avoidsConsumed
      (Finset.mem_image.mpr ⟨attempt, hAttempt, rfl⟩) hConsumed

/-- General fixed-horizon upper bound.  No availability or independence
assumption is required, and no equality is claimed. -/
theorem admissible_card_le_unusedActiveCells_card
    {H : FixedHorizon Attempt Occurrence Domain}
    {LifecycleFeasible : Finset Attempt -> Prop}
    {accepted : Finset Attempt}
    (h : AdmissibleExtension H LifecycleFeasible accepted) :
    accepted.card <= (unusedActiveCells H).card := by
  calc
    accepted.card = (accepted.image H.cellOf).card :=
      (Finset.card_image_iff.mpr h.singlePerCell).symm
    _ <= (unusedActiveCells H).card :=
      Finset.card_le_card (acceptedCells_subset_unusedActiveCells h)

theorem cumulative_singlePerCell
    {H : FixedHorizon Attempt Occurrence Domain}
    {LifecycleFeasible : Finset Attempt -> Prop}
    {accepted : Finset Attempt}
    (hHistory : HistoryValid H)
    (h : AdmissibleExtension H LifecycleFeasible accepted) :
    Set.InjOn H.cellOf
      ((H.committed ∪ accepted : Finset Attempt) : Set Attempt) := by
  intro a ha b hb hCell
  simp only [Finset.mem_coe, Finset.mem_union] at ha hb
  rcases ha with haCommitted | haAccepted <;>
    rcases hb with hbCommitted | hbAccepted
  · exact hHistory.committedSinglePerCell
      haCommitted hbCommitted hCell
  · exfalso
    exact Finset.disjoint_left.mp h.avoidsConsumed
      (Finset.mem_image.mpr ⟨b, hbAccepted, rfl⟩)
      (hHistory.committedCellsConsumed
        (Finset.mem_image.mpr ⟨a, haCommitted, hCell⟩))
  · exfalso
    exact Finset.disjoint_left.mp h.avoidsConsumed
      (Finset.mem_image.mpr ⟨a, haAccepted, rfl⟩)
      (hHistory.committedCellsConsumed
        (Finset.mem_image.mpr ⟨b, hbCommitted, hCell.symm⟩))
  · exact h.singlePerCell haAccepted hbAccepted hCell

theorem cumulativeEvents_card_eq_committed_add_accepted
    {H : FixedHorizon Attempt Occurrence Domain}
    {LifecycleFeasible : Finset Attempt -> Prop}
    {accepted : Finset Attempt}
    (h : AdmissibleExtension H LifecycleFeasible accepted) :
    (H.committed ∪ accepted).card =
      H.committed.card + accepted.card := by
  exact Finset.card_union_of_disjoint h.freshAttempts.symm

/-- The upper bound with durable history included.  Its left side counts
event identities already committed plus newly accepted event identities. -/
theorem committed_add_accepted_card_le_reachableCells_card
    {H : FixedHorizon Attempt Occurrence Domain}
    {LifecycleFeasible : Finset Attempt -> Prop}
    {accepted : Finset Attempt}
    (hHistory : HistoryValid H)
    (h : AdmissibleExtension H LifecycleFeasible accepted) :
    H.committed.card + accepted.card <= (reachableCells H).card := by
  rw [← cumulativeEvents_card_eq_committed_add_accepted h]
  calc
    (H.committed ∪ accepted).card =
        ((H.committed ∪ accepted).image H.cellOf).card :=
      (Finset.card_image_iff.mpr
        (cumulative_singlePerCell hHistory h)).symm
    _ <= (reachableCells H).card := by
      apply Finset.card_le_card
      intro d hd
      obtain ⟨attempt, hAttempt, rfl⟩ := Finset.mem_image.mp hd
      simp only [Finset.mem_union] at hAttempt
      rcases hAttempt with hCommitted | hAccepted
      · exact Finset.mem_union_left _
          (hHistory.committedCellsConsumed
            (Finset.mem_image.mpr ⟨attempt, hCommitted, rfl⟩))
      · exact Finset.mem_union_right _
          (Finset.mem_image.mpr
            ⟨attempt, h.withinOffered hAccepted, rfl⟩)

/-! ## Conditional tightness -/

/-- Every unused active cell has some offered attempt that is feasible alone.
-/
def SoloAvailable (H : FixedHorizon Attempt Occurrence Domain)
    (LifecycleFeasible : Finset Attempt -> Prop) : Prop :=
  forall d, d ∈ unusedActiveCells H ->
    Exists fun attempt =>
      attempt ∈ H.offered ∧ H.cellOf attempt = d ∧
        LifecycleFeasible {attempt}

/-- Feasible singleton attempts on distinct, unconsumed cells compose.  This
is an explicit workload assumption, not a consequence of one-shot cells. -/
def ProductIndependent (H : FixedHorizon Attempt Occurrence Domain)
    (LifecycleFeasible : Finset Attempt -> Prop) : Prop :=
  forall accepted,
    accepted ⊆ H.offered ->
    Set.InjOn H.cellOf (accepted : Set Attempt) ->
    Disjoint (accepted.image H.cellOf) (consumedCells H) ->
    (forall attempt, attempt ∈ accepted ->
      LifecycleFeasible {attempt}) ->
    LifecycleFeasible accepted

section TightRepresentatives

variable (H : FixedHorizon Attempt Occurrence Domain)
variable (LifecycleFeasible : Finset Attempt -> Prop)
variable (hSolo : SoloAvailable H LifecycleFeasible)

/-- A solo-feasible offered attempt for one unused active cell. -/
noncomputable def productiveRepresentative
    (d : {d // d ∈ unusedActiveCells H}) : Attempt :=
  Classical.choose (hSolo d d.property)

theorem productiveRepresentative_mem_offered
    (d : {d // d ∈ unusedActiveCells H}) :
    productiveRepresentative H LifecycleFeasible hSolo d ∈ H.offered :=
  (Classical.choose_spec (hSolo d d.property)).1

theorem cellOf_productiveRepresentative
    (d : {d // d ∈ unusedActiveCells H}) :
    H.cellOf (productiveRepresentative H LifecycleFeasible hSolo d) = d.1 :=
  (Classical.choose_spec (hSolo d d.property)).2.1

theorem productiveRepresentative_soloFeasible
    (d : {d // d ∈ unusedActiveCells H}) :
    LifecycleFeasible
      {productiveRepresentative H LifecycleFeasible hSolo d} :=
  (Classical.choose_spec (hSolo d d.property)).2.2

noncomputable def productiveRepresentativeSet : Finset Attempt :=
  (unusedActiveCells H).attach.image
    (productiveRepresentative H LifecycleFeasible hSolo)

theorem productiveRepresentative_injective :
    Function.Injective
      (productiveRepresentative H LifecycleFeasible hSolo) := by
  intro d1 d2 h
  apply Subtype.ext
  rw [← cellOf_productiveRepresentative H LifecycleFeasible hSolo d1,
    ← cellOf_productiveRepresentative H LifecycleFeasible hSolo d2, h]

theorem productiveRepresentativeSet_card :
    (productiveRepresentativeSet H LifecycleFeasible hSolo).card =
      (unusedActiveCells H).card := by
  classical
  rw [productiveRepresentativeSet,
    Finset.card_image_of_injective _
      (productiveRepresentative_injective H LifecycleFeasible hSolo),
    Finset.card_attach]

theorem productiveRepresentativeSet_withinOffered :
    productiveRepresentativeSet H LifecycleFeasible hSolo ⊆ H.offered := by
  classical
  intro attempt hAttempt
  obtain ⟨d, _hd, rfl⟩ := Finset.mem_image.mp hAttempt
  exact productiveRepresentative_mem_offered H LifecycleFeasible hSolo d

theorem productiveRepresentativeSet_singlePerCell :
    Set.InjOn H.cellOf
      (productiveRepresentativeSet H LifecycleFeasible hSolo :
        Set Attempt) := by
  classical
  intro a ha b hb hCell
  obtain ⟨d1, _hd1, rfl⟩ := Finset.mem_image.mp ha
  obtain ⟨d2, _hd2, rfl⟩ := Finset.mem_image.mp hb
  apply congrArg (productiveRepresentative H LifecycleFeasible hSolo)
  apply Subtype.ext
  simpa only [cellOf_productiveRepresentative] using hCell

theorem productiveRepresentativeSet_avoidsConsumed :
    Disjoint
      ((productiveRepresentativeSet H LifecycleFeasible hSolo).image H.cellOf)
      (consumedCells H) := by
  classical
  apply Finset.disjoint_left.mpr
  intro d hd hConsumed
  obtain ⟨attempt, hAttempt, rfl⟩ := Finset.mem_image.mp hd
  obtain ⟨active, _hActive, hRepresentative⟩ :=
    Finset.mem_image.mp hAttempt
  subst attempt
  have hUnused := active.property
  exact (Finset.mem_sdiff.mp hUnused).2
    (by simpa only [cellOf_productiveRepresentative] using hConsumed)

theorem productiveRepresentativeSet_freshAttempts :
    HistoryValid H ->
    Disjoint
      (productiveRepresentativeSet H LifecycleFeasible hSolo) H.committed := by
  classical
  intro hHistory
  apply Finset.disjoint_left.mpr
  intro attempt hAttempt hCommitted
  exact Finset.disjoint_left.mp
    (productiveRepresentativeSet_avoidsConsumed H LifecycleFeasible hSolo)
    (Finset.mem_image.mpr ⟨attempt, hAttempt, rfl⟩)
    (hHistory.committedCellsConsumed
      (Finset.mem_image.mpr ⟨attempt, hCommitted, rfl⟩))

theorem productiveRepresentativeSet_each_soloFeasible :
    forall attempt,
      attempt ∈ productiveRepresentativeSet H LifecycleFeasible hSolo ->
        LifecycleFeasible {attempt} := by
  classical
  intro attempt hAttempt
  obtain ⟨d, _hd, rfl⟩ := Finset.mem_image.mp hAttempt
  exact productiveRepresentative_soloFeasible H LifecycleFeasible hSolo d

end TightRepresentatives

/-- Conditional tightness: equality requires both solo availability and
cross-cell product independence. -/
theorem exists_tight_admissible_of_soloAvailable_productIndependent
    (H : FixedHorizon Attempt Occurrence Domain)
    (LifecycleFeasible : Finset Attempt -> Prop)
    (hHistory : HistoryValid H)
    (hSolo : SoloAvailable H LifecycleFeasible)
    (hProduct : ProductIndependent H LifecycleFeasible) :
    Exists fun accepted =>
      AdmissibleExtension H LifecycleFeasible accepted ∧
        accepted.card = (unusedActiveCells H).card := by
  classical
  let accepted := productiveRepresentativeSet H LifecycleFeasible hSolo
  have hWithin :=
    productiveRepresentativeSet_withinOffered H LifecycleFeasible hSolo
  have hSingle :=
    productiveRepresentativeSet_singlePerCell H LifecycleFeasible hSolo
  have hAvoids :=
    productiveRepresentativeSet_avoidsConsumed H LifecycleFeasible hSolo
  have hFeasible : LifecycleFeasible accepted :=
    hProduct accepted hWithin hSingle hAvoids
      (productiveRepresentativeSet_each_soloFeasible
        H LifecycleFeasible hSolo)
  exact ⟨accepted,
    ⟨hWithin,
      productiveRepresentativeSet_freshAttempts H LifecycleFeasible hSolo
        hHistory,
      hSingle, hAvoids, hFeasible⟩,
    productiveRepresentativeSet_card H LifecycleFeasible hSolo⟩

/-- Exact budget frontier, now explicitly conditional on availability and
independence.  Without those assumptions only the forward upper-bound
theorem above is valid. -/
theorem all_admissible_card_le_iff_unusedActiveCells_card_le_of_independent
    (H : FixedHorizon Attempt Occurrence Domain)
    (LifecycleFeasible : Finset Attempt -> Prop)
    (hHistory : HistoryValid H)
    (hSolo : SoloAvailable H LifecycleFeasible)
    (hProduct : ProductIndependent H LifecycleFeasible)
    (budget : Nat) :
    (forall accepted,
      AdmissibleExtension H LifecycleFeasible accepted ->
        accepted.card <= budget) ↔
      (unusedActiveCells H).card <= budget := by
  constructor
  · intro h
    obtain ⟨accepted, hAdmissible, hCard⟩ :=
      exists_tight_admissible_of_soloAvailable_productIndependent
        H LifecycleFeasible hHistory hSolo hProduct
    rw [← hCard]
    exact h accepted hAdmissible
  · intro hActive accepted hAdmissible
    exact (admissible_card_le_unusedActiveCells_card hAdmissible).trans
      hActive

theorem all_admissible_card_le_one_iff_unusedActiveCells_card_le_one_of_independent
    (H : FixedHorizon Attempt Occurrence Domain)
    (LifecycleFeasible : Finset Attempt -> Prop)
    (hHistory : HistoryValid H)
    (hSolo : SoloAvailable H LifecycleFeasible)
    (hProduct : ProductIndependent H LifecycleFeasible) :
    (forall accepted,
      AdmissibleExtension H LifecycleFeasible accepted ->
        accepted.card <= 1) ↔
      (unusedActiveCells H).card <= 1 :=
  all_admissible_card_le_iff_unusedActiveCells_card_le_of_independent
    H LifecycleFeasible hHistory hSolo hProduct 1

/-! ## Reduction to occurrence linearity -/

/-- With one offered event per current occurrence, distinct cells for every
offered event, and no already-consumed offered cell, the unused-cell frontier
has exactly the old current-occurrence cardinality. -/
theorem unusedActiveCells_card_eq_activeOccurrences_card_of_independent
    (H : FixedHorizon Attempt Occurrence Domain)
    [DecidableEq Occurrence]
    (hOccurrence : Set.InjOn H.occurrenceOf (H.offered : Set Attempt))
    (hCell : Set.InjOn H.cellOf (H.offered : Set Attempt))
    (hUnconsumed :
      Disjoint (H.offered.image H.cellOf) (consumedCells H)) :
    (unusedActiveCells H).card = (activeOccurrences H).card := by
  have hSdiff : unusedActiveCells H = H.offered.image H.cellOf := by
    exact Finset.sdiff_eq_self_of_disjoint hUnconsumed
  rw [hSdiff, activeOccurrences,
    Finset.card_image_iff.mpr hCell,
    Finset.card_image_iff.mpr hOccurrence]

/-- Under the explicit availability/independence assumptions above, and only
when occurrence and cell maps are injective on the offered horizon, the exact
single-redemption test reduces to `|current occurrences| <= 1`. -/
theorem independentOccurrences_single_redemption_iff_current_card_le_one
    (H : FixedHorizon Attempt Occurrence Domain)
    [DecidableEq Occurrence]
    (LifecycleFeasible : Finset Attempt -> Prop)
    (hHistory : HistoryValid H)
    (hSolo : SoloAvailable H LifecycleFeasible)
    (hProduct : ProductIndependent H LifecycleFeasible)
    (hOccurrence : Set.InjOn H.occurrenceOf (H.offered : Set Attempt))
    (hCell : Set.InjOn H.cellOf (H.offered : Set Attempt))
    (hUnconsumed :
      Disjoint (H.offered.image H.cellOf) (consumedCells H)) :
    (forall accepted,
      AdmissibleExtension H LifecycleFeasible accepted ->
        accepted.card <= 1) ↔
      (activeOccurrences H).card <= 1 := by
  rw [all_admissible_card_le_one_iff_unusedActiveCells_card_le_one_of_independent
      H LifecycleFeasible hHistory hSolo hProduct,
    unusedActiveCells_card_eq_activeOccurrences_card_of_independent
      H hOccurrence hCell hUnconsumed]

/-! ## Separating examples -/

namespace SharedCellAliases

def horizon : FixedHorizon Bool Bool Unit where
  committed := ∅
  consumed := ∅
  offered := {false, true}
  occurrenceOf := id
  cellOf := fun _ => ()

def feasible (_ : Finset Bool) : Prop := True

theorem two_current_aliases : (activeOccurrences horizon).card = 2 := by
  decide

theorem one_unused_shared_cell : (unusedActiveCells horizon).card = 1 := by
  decide

/-- Strict witness against universal necessity of occurrence linearity: two
history aliases share one actual one-shot cell, so every admissible accepted
event set still has cardinality at most one. -/
theorem shared_cell_aliases_safe_but_not_occurrence_linear :
    (forall accepted,
      AdmissibleExtension horizon feasible accepted -> accepted.card <= 1) ∧
      Not ((activeOccurrences horizon).card <= 1) := by
  constructor
  · intro accepted h
    exact (admissible_card_le_unusedActiveCells_card h).trans (by decide)
  · decide

end SharedCellAliases

namespace DurableConsumedHistory

/-- The accepted event record itself has been pruned, but its durable spent
cell remains.  A restored attempt still cannot reopen that cell. -/
def horizon : FixedHorizon Bool Unit Unit where
  committed := ∅
  consumed := {()}
  offered := {false}
  occurrenceOf := fun _ => ()
  cellOf := fun _ => ()

def feasible (_ : Finset Bool) : Prop := True

theorem restored_attempt_blocked_by_pruned_consumed_history :
    forall accepted,
      AdmissibleExtension horizon feasible accepted -> accepted.card = 0 := by
  intro accepted h
  have hBound := admissible_card_le_unusedActiveCells_card h
  have hZero : (unusedActiveCells horizon).card = 0 := by
    decide
  omega

end DurableConsumedHistory

namespace ExclusiveChoice

def horizon : FixedHorizon Bool Bool Bool where
  committed := ∅
  consumed := ∅
  offered := {false, true}
  occurrenceOf := id
  cellOf := id

def feasible (accepted : Finset Bool) : Prop := accepted.card <= 1

theorem two_unused_choice_cells :
    (unusedActiveCells horizon).card = 2 := by
  decide

theorem every_choice_cell_soloAvailable :
    SoloAvailable horizon feasible := by
  intro d _hd
  refine ⟨d, ?_, rfl, ?_⟩
  · cases d <;> simp [horizon]
  · simp [feasible]

/-- Two different cells do not imply two jointly reachable successes: choice
feasibility makes the general upper bound strict. -/
theorem two_cells_but_choice_accepts_at_most_one :
    (unusedActiveCells horizon).card = 2 ∧
      (forall accepted,
        AdmissibleExtension horizon feasible accepted ->
          accepted.card <= 1) := by
  refine ⟨two_unused_choice_cells, ?_⟩
  intro accepted h
  exact h.lifecycleFeasible

theorem choice_is_not_productIndependent :
    Not (ProductIndependent horizon feasible) := by
  intro hProduct
  have hNotFeasible : Not (feasible horizon.offered) := by
    simp [feasible, horizon]
  apply hNotFeasible
  apply hProduct horizon.offered Finset.Subset.rfl
  · intro a _ha b _hb hCell
    simpa [horizon] using hCell
  · simp [horizon, consumedCells]
  · intro attempt _hAttempt
    simp [feasible]

end ExclusiveChoice

namespace RollbackClonedCells

/-- Two distinct attempt events arise from one restored occurrence.  The two
cells are physically independent clones even though their textual label is
the same. -/
def horizon : FixedHorizon Bool Unit Bool where
  committed := ∅
  consumed := ∅
  offered := {false, true}
  occurrenceOf := fun _ => ()
  cellOf := id

def sameLabel (_ : Bool) : Unit := ()

/-- Both fresh commitment attempts were submitted under the same caller
operation key.  The key does not replace a linearizer-minted receipt ID. -/
def sameOperationKey (_ : Bool) : Unit := ()

def feasible (_ : Finset Bool) : Prop := True

theorem one_occurrence_two_attempt_events :
    (activeOccurrences horizon).card = 1 ∧ horizon.offered.card = 2 := by
  decide

theorem same_label_but_two_semantic_cells :
    (horizon.offered.image sameLabel).card = 1 ∧
      (unusedActiveCells horizon).card = 2 := by
  decide

/-- A shared label is not a shared linearization point.  Both event IDs can
be accepted because the cloned cells have different semantic identities. -/
theorem rollback_clone_double_accept_counterexample :
    Exists fun accepted =>
      AdmissibleExtension horizon feasible accepted ∧
        accepted.card = 2 ∧
        (accepted.image horizon.occurrenceOf).card = 1 ∧
        (accepted.image sameLabel).card = 1 ∧
        (accepted.image sameOperationKey).card = 1 := by
  refine ⟨horizon.offered, ?_, by decide, by decide, by decide, by decide⟩
  refine ⟨Finset.Subset.rfl, ?_, ?_, ?_, trivial⟩
  · simp [horizon]
  · intro a _ha b _hb hCell
    simpa [horizon] using hCell
  · simp [horizon, consumedCells]

end RollbackClonedCells

end AuthorityContinuity.RedemptionDomainFrontier
