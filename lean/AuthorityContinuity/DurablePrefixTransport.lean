import AuthorityContinuity.ConfigurationCellQuotient
import AuthorityContinuity.CoordinationDecomposition
import AuthorityContinuity.RedemptionCommitment

/-!
# Durable-prefix transport

An outstanding lease is not checked against a restored future in isolation.
It is checked against the receipts that have already become durable outside the
rollback domain.  This module characterizes policy-oblivious reuse for finite
additive authority policies: every candidate future is added to the actual
durable prefix, and the result must map injectively to an allowed source
configuration.

The theorem refines the classical configuration-morphism bridge with an
operationally visible prefix.  Its intended use is at a typed
Fork/Restore/Merge admission boundary; it does not infer the target future or
prove that a concrete runtime realizes it.

The target type `D` ranges only over prospective cells that may create a fresh
durable commitment.  A retry/replay already resolved by an existing receipt is
not another target occurrence; treating it as one would intentionally reject
legal idempotent replay as fresh authorization.
-/

namespace AuthorityContinuity.DurablePrefixTransport

open scoped BigOperators
open ConfigurationCellQuotient

set_option linter.unusedSectionVars false

universe uU uD

variable {U : Type uU} {D : Type uD}
variable [Fintype U] [DecidableEq U] [Fintype D] [DecidableEq D]

/-! ## Prefix-sensitive safety and morphisms -/

/-- Every target future, added to the already durable source atoms, respects
the same additive capacity.  The two sums are intentionally not deduplicated:
reusing an atom from `durable` is a second authority occurrence. -/
def PrefixTargetSafe (durable : Finset U) (target : Finset (Finset D))
    (ell : D -> U) (w : U -> Nat) (k : Nat) : Prop :=
  ∀ C ∈ target,
    (∑ u ∈ durable, w u) + (∑ d ∈ C, w (ell d)) <= k

/-- All additive source policies transport after accounting for the actual
durable prefix. -/
def UniversalPrefixTransport (source : Finset (Finset U))
    (durable : Finset U) (target : Finset (Finset D))
    (ell : D -> U) : Prop :=
  ∀ (w : U -> Nat) (k : Nat),
    SourceSafe source w k -> PrefixTargetSafe durable target ell w k

/-- Each target configuration is locally collision-free, does not resurrect a
durably committed atom, and extends the durable prefix to an admitted source
configuration. -/
def PrefixConfigMorphism (source : Finset (Finset U))
    (durable : Finset U) (target : Finset (Finset D))
    (ell : D -> U) : Prop :=
  durable ∈ source ∧
    ∀ C ∈ target,
      Set.InjOn ell (C : Set D) ∧
        Disjoint durable (C.image ell) ∧
        durable ∪ C.image ell ∈ source

theorem prefixConfigMorphism_implies_universalPrefixTransport
    (source : Finset (Finset U)) (durable : Finset U)
    (target : Finset (Finset D)) (ell : D -> U)
    (hMorphism : PrefixConfigMorphism source durable target ell) :
    UniversalPrefixTransport source durable target ell := by
  intro w k hSource C hC
  obtain ⟨hinj, hdisjoint, hUnion⟩ := hMorphism.2 C hC
  have hBound := hSource (durable ∪ C.image ell) hUnion
  rw [Finset.sum_union hdisjoint, Finset.sum_image hinj] at hBound
  exact hBound

/-! ## Necessity witnesses -/

theorem prefixTransport_implies_targetTransport
    (source : Finset (Finset U)) (durable : Finset U)
    (target : Finset (Finset D)) (ell : D -> U)
    (hTransport : UniversalPrefixTransport source durable target ell) :
    UniversalAdditiveTransport source target ell := by
  intro w k hSource C hC
  have hPrefix := hTransport w k hSource C hC
  omega

theorem universalPrefixTransport_implies_localInjective
    (source : Finset (Finset U)) (durable : Finset U)
    (target : Finset (Finset D)) (ell : D -> U)
    (wf : SourceFamilyWellFormed source)
    (hTransport : UniversalPrefixTransport source durable target ell) :
    ∀ C ∈ target, Set.InjOn ell (C : Set D) := by
  exact fun C hC =>
    (universalAdditiveTransport_implies_configMorphism source target ell wf
      (prefixTransport_implies_targetTransport
        source durable target ell hTransport) C hC).1

/-- A candidate future cannot reuse an atom already named by a durable
receipt.  The point weight at that atom gives a capacity-one witness. -/
theorem universalPrefixTransport_implies_disjoint
    (source : Finset (Finset U)) (durable : Finset U)
    (target : Finset (Finset D)) (ell : D -> U)
    (hTransport : UniversalPrefixTransport source durable target ell) :
    ∀ C ∈ target, Disjoint durable (C.image ell) := by
  intro C hC
  apply Finset.disjoint_left.mpr
  intro u huDurable huImage
  obtain ⟨d, hd, hdu⟩ := Finset.mem_image.mp huImage
  have hBound := hTransport (pointWeight u) 1
    (sourceSafe_pointWeight source u) C hC
  have hDurableOne :
      1 <= ∑ x ∈ durable, pointWeight u x := by
    have hOne := Finset.single_le_sum
      (s := durable) (f := pointWeight u)
      (fun _ _ => Nat.zero_le _) huDurable
    simpa [pointWeight] using hOne
  have hTargetOne :
      1 <= ∑ x ∈ C, pointWeight u (ell x) := by
    have hOne := Finset.single_le_sum
      (s := C) (f := fun x => pointWeight u (ell x))
      (fun _ _ => Nat.zero_le _) hd
    simpa [pointWeight, hdu] using hOne
  omega

/-- Once local collisions and prefix replay are excluded, any newly admitted
union is separated by the indicator policy of that union. -/
theorem universalPrefixTransport_implies_union_mem
    (source : Finset (Finset U)) (durable : Finset U)
    (target : Finset (Finset D)) (ell : D -> U)
    (wf : SourceFamilyWellFormed source)
    (hTransport : UniversalPrefixTransport source durable target ell) :
    ∀ C ∈ target, durable ∪ C.image ell ∈ source := by
  intro C hC
  have hinj := universalPrefixTransport_implies_localInjective
    source durable target ell wf hTransport C hC
  have hdisjoint := universalPrefixTransport_implies_disjoint
    source durable target ell hTransport C hC
  by_contra hForbidden
  let I : Finset U := durable ∪ C.image ell
  obtain ⟨w, hSource, hTargetFailure⟩ :=
    forbidden_image_indicator_witness source ({I} : Finset (Finset U)) id wf
      (C := I) (by simp) (by simp) (by simpa [I] using hForbidden)
  have hSourceI : SourceSafe source w (I.card - 1) := by
    simpa using hSource
  have hTargetFailureI :
      ¬TargetSafe ({I} : Finset (Finset U)) id w (I.card - 1) := by
    simpa using hTargetFailure
  apply hTargetFailureI
  intro J hJ
  have hJI : J = I := by simpa using hJ
  subst J
  have hPrefixBound := hTransport w (I.card - 1) hSourceI C hC
  change (∑ u ∈ I, w u) <= I.card - 1
  rw [show I = durable ∪ C.image ell by rfl,
    Finset.sum_union hdisjoint, Finset.sum_image hinj]
  exact hPrefixBound

/-- Universal prefix-sensitive transport is exactly the pointed
configuration-morphism condition.  The target-empty premise exposes the
durable prefix itself as one target completion and rules out vacuous targets. -/
theorem universalPrefixTransport_iff_prefixConfigMorphism
    (source : Finset (Finset U)) (durable : Finset U)
    (target : Finset (Finset D)) (ell : D -> U)
    (sourceWF : SourceFamilyWellFormed source)
    (targetEmpty : (∅ : Finset D) ∈ target) :
    UniversalPrefixTransport source durable target ell ↔
      PrefixConfigMorphism source durable target ell := by
  constructor
  · intro hTransport
    have hLocal := universalPrefixTransport_implies_localInjective
      source durable target ell sourceWF hTransport
    have hDisjoint := universalPrefixTransport_implies_disjoint
      source durable target ell hTransport
    have hUnion := universalPrefixTransport_implies_union_mem
      source durable target ell sourceWF hTransport
    refine ⟨?_, ?_⟩
    · simpa using hUnion ∅ targetEmpty
    · intro C hC
      exact ⟨hLocal C hC, hDisjoint C hC, hUnion C hC⟩
  · exact prefixConfigMorphism_implies_universalPrefixTransport
      source durable target ell

theorem empty_prefix_morphism_iff_configMorphism
    (source : Finset (Finset U)) (target : Finset (Finset D))
    (ell : D -> U) (sourceWF : SourceFamilyWellFormed source) :
    PrefixConfigMorphism source ∅ target ell ↔
      ConfigMorphism source target ell := by
  constructor
  · intro hPrefix C hC
    obtain ⟨hinj, _, hImage⟩ := hPrefix.2 C hC
    exact ⟨hinj, by simpa using hImage⟩
  · intro hConfig
    refine ⟨sourceWF.empty_mem, ?_⟩
    intro C hC
    obtain ⟨hinj, hImage⟩ := hConfig C hC
    exact ⟨hinj, by simp, by simpa using hImage⟩

theorem empty_prefix_universal_iff_universalAdditiveTransport
    (source : Finset (Finset U)) (target : Finset (Finset D))
    (ell : D -> U) :
    UniversalPrefixTransport source ∅ target ell ↔
      UniversalAdditiveTransport source target ell := by
  simp [UniversalPrefixTransport, PrefixTargetSafe,
    UniversalAdditiveTransport, TargetSafe]

/-! ## Greatest pointwise-safe subfamily -/

/-- Executable filter for the greatest prefix-safe subfamily of a fixed
candidate future under complete observation and controllable pruning. -/
def safeFuture (source : Finset (Finset U)) (durable : Finset U)
    (candidate : Finset (Finset D)) (ell : D -> U) :
    Finset (Finset D) :=
  candidate.filter fun C =>
    (C.image ell).card = C.card ∧
      Disjoint durable (C.image ell) ∧
      durable ∪ C.image ell ∈ source

theorem safeFuture_subset_candidate
    (source : Finset (Finset U)) (durable : Finset U)
    (candidate : Finset (Finset D)) (ell : D -> U) :
    safeFuture source durable candidate ell ⊆ candidate := by
  intro C hC
  exact (Finset.mem_filter.mp hC).1

theorem safeFuture_prefixConfigMorphism
    (source : Finset (Finset U)) (durable : Finset U)
    (candidate : Finset (Finset D)) (ell : D -> U)
    (hDurable : durable ∈ source) :
    PrefixConfigMorphism source durable
      (safeFuture source durable candidate ell) ell := by
  refine ⟨hDurable, ?_⟩
  intro C hC
  obtain ⟨_, hCard, hDisjoint, hUnion⟩ :=
    Finset.mem_filter.mp hC
  exact ⟨Finset.card_image_iff.mp hCard, hDisjoint, hUnion⟩

/-- Every prefix-safe subfamily of the same candidate is contained in the
computed filter. -/
theorem safeFuture_greatest
    (source : Finset (Finset U)) (durable : Finset U)
    (candidate admitted : Finset (Finset D)) (ell : D -> U)
    (hCandidate : admitted ⊆ candidate)
    (hSafe : PrefixConfigMorphism source durable admitted ell) :
    admitted ⊆ safeFuture source durable candidate ell := by
  intro C hC
  have hData := hSafe.2 C hC
  apply Finset.mem_filter.mpr
  exact ⟨hCandidate hC, Finset.card_image_iff.mpr hData.1,
    hData.2.1, hData.2.2⟩

/-- Required behaviors fit inside some prefix-safe pruning exactly when they
all survive the greatest safe filter.  This is relative required-behavior
preservation: silently pruning a behavior promised by the typed operation is
not a successful compilation.  Meaningful non-vacuity additionally requires
the typed operator generator to supply a complete, nontrivial `required`
family. -/
theorem required_subset_safeFuture_iff_exists_admitted
    (source : Finset (Finset U)) (durable : Finset U)
    (candidate required : Finset (Finset D)) (ell : D -> U)
    (hDurable : durable ∈ source) :
    required ⊆ safeFuture source durable candidate ell ↔
      ∃ admitted : Finset (Finset D),
        required ⊆ admitted ∧
          admitted ⊆ candidate ∧
          PrefixConfigMorphism source durable admitted ell := by
  constructor
  · intro hRequired
    exact ⟨safeFuture source durable candidate ell,
      hRequired,
      safeFuture_subset_candidate source durable candidate ell,
      safeFuture_prefixConfigMorphism source durable candidate ell hDurable⟩
  · rintro ⟨admitted, hRequired, hCandidate, hSafe⟩
    exact Finset.Subset.trans hRequired
      (safeFuture_greatest source durable candidate admitted ell
        hCandidate hSafe)

theorem safeFuture_universalPrefixTransport
    (source : Finset (Finset U)) (durable : Finset U)
    (candidate : Finset (Finset D)) (ell : D -> U)
    (hDurable : durable ∈ source) :
    UniversalPrefixTransport source durable
      (safeFuture source durable candidate ell) ell :=
  prefixConfigMorphism_implies_universalPrefixTransport
    source durable (safeFuture source durable candidate ell) ell
    (safeFuture_prefixConfigMorphism
      source durable candidate ell hDurable)

/-- Semantic maximality: any universally safe rooted pruning of the fixed
candidate is contained in `safeFuture`. -/
theorem universallySafe_subfamily_subset_safeFuture
    (source : Finset (Finset U)) (durable : Finset U)
    (candidate admitted : Finset (Finset D)) (ell : D -> U)
    (sourceWF : SourceFamilyWellFormed source)
    (admittedEmpty : (∅ : Finset D) ∈ admitted)
    (hCandidate : admitted ⊆ candidate)
    (hTransport : UniversalPrefixTransport source durable admitted ell) :
    admitted ⊆ safeFuture source durable candidate ell := by
  apply safeFuture_greatest source durable candidate admitted ell hCandidate
  exact (universalPrefixTransport_iff_prefixConfigMorphism
    source durable admitted ell sourceWF admittedEmpty).1 hTransport

theorem safeFuture_wellFormed
    (source : Finset (Finset U)) (durable : Finset U)
    (candidate : Finset (Finset D)) (ell : D -> U)
    (sourceWF : SourceFamilyWellFormed source)
    (candidateWF : SourceFamilyWellFormed candidate)
    (hDurable : durable ∈ source) :
    SourceFamilyWellFormed (safeFuture source durable candidate ell) := by
  have hEmpty :
      (∅ : Finset D) ∈ safeFuture source durable candidate ell := by
    simp [safeFuture, candidateWF.empty_mem, hDurable]
  refine ⟨⟨∅, hEmpty⟩, hEmpty, ?_⟩
  intro C C' hC hSubset
  obtain ⟨hCandidate, hCard, hDisjoint, hUnion⟩ :=
    Finset.mem_filter.mp hC
  apply Finset.mem_filter.mpr
  refine ⟨candidateWF.downwardClosed hCandidate hSubset, ?_, ?_, ?_⟩
  · apply Finset.card_image_iff.mpr
    have hinj := Finset.card_image_iff.mp hCard
    intro d₁ hd₁ d₂ hd₂ hLineage
    exact hinj (hSubset hd₁) (hSubset hd₂) hLineage
  · apply Finset.disjoint_left.mpr
    intro u huDurable huImage
    apply Finset.disjoint_left.mp hDisjoint huDurable
    obtain ⟨d, hd, rfl⟩ := Finset.mem_image.mp huImage
    exact Finset.mem_image.mpr ⟨d, hSubset hd, rfl⟩
  · apply sourceWF.downwardClosed hUnion
    intro u hu
    simp only [Finset.mem_union] at hu ⊢
    rcases hu with hu | hu
    · exact Or.inl hu
    · obtain ⟨d, hd, rfl⟩ := Finset.mem_image.mp hu
      exact Or.inr (Finset.mem_image.mpr ⟨d, hSubset hd, rfl⟩)

/-- After maximal safe pruning, the previous `localProduct` theorem gives the
least common-coordination equivalence for an exact implementation with no
cross-block protocol.  It does not require physical co-location: a shared
durable controller, distributed lock, or consensus service may implement one
coordination component. -/
theorem safeFuture_exactFactorization_iff_mustCoordinate
    (source : Finset (Finset U)) (durable : Finset U)
    (candidate : Finset (Finset D)) (ell : D -> U)
    {B : Type*} [Fintype B] [DecidableEq B]
    (blockOf : D -> B)
    (sourceWF : SourceFamilyWellFormed source)
    (candidateWF : SourceFamilyWellFormed candidate)
    (hDurable : durable ∈ source) :
    CoordinationDecomposition.ExactFactorization
        (safeFuture source durable candidate ell) blockOf ↔
      ∀ d₁ d₂ : D,
        CoordinationDecomposition.MustCoordinate
            (safeFuture source durable candidate ell) d₁ d₂ ->
          blockOf d₁ = blockOf d₂ :=
  CoordinationDecomposition.exactFactorization_iff_constant_on_mustCoordinate
    (safeFuture source durable candidate ell) blockOf
    (safeFuture_wellFormed source durable candidate ell
      sourceWF candidateWF hDurable)

/-! ## Durable receipts supply the prefix -/

open RedemptionCommitment

universe uA uC uE uO uG uR

/-- Source atoms named by immutable durable receipt bindings.  An application
must instantiate `Atom` with an indivisible authority-unit identity (including
its authority root/issuer, relevant scope, and version/nonce or unit index),
rather than an unqualified local resource name.  `biUnion` deduplicates the
set representation, so this is a faithful unit prefix only behind a separately checked
`RedemptionCommitment.Safe` ledger gate; that invariant prevents two distinct
receipts from naming the same qualified unit.  To use the result as
`PrefixConfigMorphism.durable`, the adapter must also prove the separate
cross-model fact `committedAtoms S ∈ source`; `Safe S` does not imply it. -/
def committedAtoms
    {Atom : Type uA} {Cell : Type uC} {Epoch : Type uE}
    {Operation : Type uO} {Digest : Type uG} {Receipt : Type uR}
    [DecidableEq Atom] [Fintype Receipt] [DecidableEq Receipt]
    (S : State Atom Cell Epoch Operation Digest Receipt) : Finset Atom :=
  Finset.univ.biUnion fun receipt =>
    match S.ledger receipt with
    | none => ∅
    | some binding => {binding.atom}

theorem binding_atom_mem_committedAtoms
    {Atom : Type uA} {Cell : Type uC} {Epoch : Type uE}
    {Operation : Type uO} {Digest : Type uG} {Receipt : Type uR}
    [DecidableEq Atom] [Fintype Receipt] [DecidableEq Receipt]
    {S : State Atom Cell Epoch Operation Digest Receipt}
    {receipt : Receipt}
    {binding : Binding Cell Epoch Atom Operation Digest}
    (hBinding : S.ledger receipt = some binding) :
    binding.atom ∈ committedAtoms S := by
  simp only [committedAtoms, Finset.mem_biUnion]
  exact ⟨receipt, Finset.mem_univ receipt, by simp [hBinding]⟩

/-- A monotone ledger makes the durable authority prefix monotone. -/
theorem committedAtoms_mono_of_ledgerMonotone
    {Atom : Type uA} {Cell : Type uC} {Epoch : Type uE}
    {Operation : Type uO} {Digest : Type uG} {Receipt : Type uR}
    [DecidableEq Atom] [Fintype Receipt] [DecidableEq Receipt]
    {S T : State Atom Cell Epoch Operation Digest Receipt}
    (hLedger : LedgerMonotone S T) :
    committedAtoms S ⊆ committedAtoms T := by
  intro atom hAtom
  simp only [committedAtoms, Finset.mem_biUnion] at hAtom ⊢
  obtain ⟨receipt, _, hReceipt⟩ := hAtom
  by_cases hNone : S.ledger receipt = none
  · simp [hNone] at hReceipt
  · obtain ⟨binding, hBinding⟩ := Option.ne_none_iff_exists'.mp hNone
    refine ⟨receipt, Finset.mem_univ receipt, ?_⟩
    have hTargetBinding := hLedger receipt binding hBinding
    simpa [hBinding, hTargetBinding] using hReceipt

/-- If a future cell names an atom already in the durable prefix, no
policy-oblivious reuse certificate exists.  The past is outside the target
cell domain, so quotienting or aliasing only future cells cannot repair this
collision. -/
theorem durable_atom_in_future_forbids_universal_reuse
    (source : Finset (Finset U)) (durable : Finset U)
    (target : Finset (Finset D)) (ell : D -> U)
    {C : Finset D} (hC : C ∈ target) {d : D} (hd : d ∈ C)
    (hDurable : ell d ∈ durable) :
    ¬UniversalPrefixTransport source durable target ell := by
  intro hTransport
  have hDisjoint := universalPrefixTransport_implies_disjoint
    source durable target ell hTransport C hC
  exact Finset.disjoint_left.mp hDisjoint hDurable
    (Finset.mem_image.mpr ⟨d, hd, rfl⟩)

/-! ## Executable prefix-sensitive fixtures -/

namespace Fixtures

open ConfigurationCellQuotient.Fixtures
open RedemptionCommitment.Fixtures

def durableAfterFirst : Finset Unit :=
  committedAtoms afterFirst

theorem durableAfterFirst_eq : durableAfterFirst = {()} := by
  decide

def restoredFuture : Finset (Finset Bool) :=
  {∅, {true}}

/-- Ignoring the receipt prefix, the restored cell still maps to the one-unit
source configuration and therefore appears safe. -/
theorem snapshot_only_restored_future_transports :
    UniversalAdditiveTransport unitSource restoredFuture collapseLineage := by
  apply configMorphism_implies_universalAdditiveTransport
  intro C hC
  simp [restoredFuture] at hC
  rcases hC with rfl | rfl <;> simp [unitSource, collapseLineage]

/-- The actual durable receipt consumes the same source atom, so the restored
future is rejected by the pointed transport theorem. -/
theorem durable_receipt_blocks_restored_future :
    ¬UniversalPrefixTransport unitSource durableAfterFirst
      restoredFuture collapseLineage := by
  apply durable_atom_in_future_forbids_universal_reuse
    unitSource durableAfterFirst restoredFuture collapseLineage
    (C := {true}) (d := true)
  · simp [restoredFuture]
  · simp
  · simp [durableAfterFirst_eq, collapseLineage]

def boolSource : Finset (Finset Bool) :=
  Finset.univ

def freshOtherFuture : Finset (Finset Bool) :=
  {∅, {true}}

/-- A receipt for `false` does not make a future for the distinct atom `true`
fail this structural transport invariant.  This fixture does not model a
lease, version, or refinement certificate; those are separate typed-compiler
obligations. -/
theorem distinct_atom_future_remains_transportable :
    UniversalPrefixTransport boolSource {false} freshOtherFuture id := by
  apply prefixConfigMorphism_implies_universalPrefixTransport
  refine ⟨by simp [boolSource], ?_⟩
  intro C hC
  simp [freshOtherFuture] at hC
  rcases hC with rfl | rfl <;> simp [boolSource]

end Fixtures

end AuthorityContinuity.DurablePrefixTransport
