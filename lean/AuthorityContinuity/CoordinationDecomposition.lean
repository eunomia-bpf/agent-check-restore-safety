import AuthorityContinuity.ConfigurationCellQuotient

/-!
# Exact coordination decomposition

This module formalizes the finite combinatorial criterion used by the
history-transformation compiler.  A downward-closed family records which
semantic redemption cells may become durable together.  A block labelling
proposes independently runnable controllers.  Their local views reconstruct
the source family exactly iff no minimal nonface is split across blocks.

The static factorization theorem is classical simplicial-complex/relation
factorization machinery, not a standalone novelty claim.  Its role here is to
produce a checked coordination certificate or an explicit newly admitted
configuration, which the configuration-morphism bridge then turns into an
additive authority-policy counterexample.
-/

namespace AuthorityContinuity.CoordinationDecomposition

open ConfigurationCellQuotient

set_option linter.unusedSectionVars false

universe uU uB

variable {U : Type uU} {B : Type uB}
variable [Fintype U] [DecidableEq U] [Fintype B] [DecidableEq B]

/-! ## Families, local views, and independent recombination -/

/-- Cells that occur in at least one source configuration. -/
def support (source : Finset (Finset U)) : Finset U :=
  source.biUnion id

/-- The part of configuration `C` controlled by block `b`. -/
def blockPart (blockOf : U -> B) (b : B) (C : Finset U) : Finset U :=
  C.filter fun u => blockOf u = b

/-- The maximal asynchronous recombination admitted when each independently
runnable block checks only its own restriction.  A concrete runtime must
separately establish that its controllers can jointly realize these local
choices; without that refinement, a cut witnesses failure of policy-oblivious
certificate inheritance rather than a necessarily reachable exploit.  The
powerset restriction prevents elements outside the declared support from
appearing solely because all of their block-local views are empty. -/
def localProduct (source : Finset (Finset U)) (blockOf : U -> B) :
    Finset (Finset U) :=
  (support source).powerset.filter fun C =>
    ∀ b : B, blockPart blockOf b C ∈ source

/-- Exact factorization means that independent block checks reconstruct the
source configurations, rather than silently adding a joint future. -/
def ExactFactorization (source : Finset (Finset U))
    (blockOf : U -> B) : Prop :=
  localProduct source blockOf = source

/-- A minimal nonface is a forbidden set on the source support all of whose
proper subsets are admitted. -/
def MinimalNonface (source : Finset (Finset U)) (K : Finset U) : Prop :=
  K ⊆ support source ∧ K ∉ source ∧
    ∀ L : Finset U, L ⊂ K -> L ∈ source

/-- All cells of a configuration are governed by one block. -/
def WithinBlock (blockOf : U -> B) (K : Finset U) : Prop :=
  ∃ b : B, ∀ u ∈ K, blockOf u = b

/-- Two cells directly require coordination when they occur in the same
minimal nonface. -/
def DirectlyCoupled (source : Finset (Finset U)) (u v : U) : Prop :=
  ∃ K : Finset U,
    MinimalNonface source K ∧ u ∈ K ∧ v ∈ K

/-- The equivalence closure of direct coupling is the connected-component
relation of the minimal-nonface hypergraph. -/
def MustCoordinate (source : Finset (Finset U)) (u v : U) : Prop :=
  Relation.EqvGen (DirectlyCoupled source) u v

theorem blockPart_subset (blockOf : U -> B) (b : B) (C : Finset U) :
    blockPart blockOf b C ⊆ C := by
  intro u hu
  exact (Finset.mem_filter.mp hu).1

theorem source_mem_support {source : Finset (Finset U)}
    {C : Finset U} (hC : C ∈ source) : C ⊆ support source := by
  intro u hu
  exact Finset.mem_biUnion.mpr ⟨C, hC, hu⟩

/-- Every source configuration passes all block-local checks. -/
theorem source_subset_localProduct
    (source : Finset (Finset U)) (blockOf : U -> B)
    (wf : SourceFamilyWellFormed source) :
    source ⊆ localProduct source blockOf := by
  intro C hC
  simp only [localProduct, Finset.mem_filter, Finset.mem_powerset]
  refine ⟨source_mem_support hC, ?_⟩
  intro b
  exact wf.downwardClosed hC (blockPart_subset blockOf b C)

/-! ## Minimal forbidden witnesses -/

/-- Every forbidden set on the finite support contains a minimal nonface. -/
theorem exists_minimalNonface_subset
    (source : Finset (Finset U)) {C : Finset U}
    (hSupport : C ⊆ support source) (hForbidden : C ∉ source) :
    ∃ K : Finset U, K ⊆ C ∧ MinimalNonface source K := by
  classical
  let bad : Finset (Finset U) :=
    C.powerset.filter fun K => K ∉ source
  have hBadNonempty : bad.Nonempty := by
    refine ⟨C, ?_⟩
    simp [bad, hForbidden]
  obtain ⟨K, hKBad, hKMin⟩ :=
    bad.exists_min_image (fun K : Finset U => K.card) hBadNonempty
  have hKData : K ⊆ C ∧ K ∉ source := by
    simpa [bad] using hKBad
  refine ⟨K, hKData.1, hKData.1.trans hSupport, hKData.2, ?_⟩
  intro L hL
  by_contra hLForbidden
  have hLBad : L ∈ bad := by
    simp [bad, hL.subset.trans hKData.1, hLForbidden]
  have hCardMin := hKMin L hLBad
  have hCardStrict := Finset.card_lt_card hL
  omega

theorem minimalNonface_nonempty
    (source : Finset (Finset U)) (wf : SourceFamilyWellFormed source)
    {K : Finset U} (hK : MinimalNonface source K) : K.Nonempty := by
  by_contra hEmpty
  have hEq : K = ∅ := Finset.not_nonempty_iff_eq_empty.mp hEmpty
  apply hK.2.1
  simpa [hEq] using wf.empty_mem

/-! ## Exact factorization and separating policies -/

/-- Splitting a minimal nonface across independently checked blocks admits that
forbidden union even though every local restriction is source-admissible. -/
theorem cut_minimalNonface_witness
    (source : Finset (Finset U)) (blockOf : U -> B)
    {K : Finset U} (hK : MinimalNonface source K)
    (hCut : ¬WithinBlock blockOf K) :
    K ∈ localProduct source blockOf ∧ K ∉ source := by
  constructor
  · simp only [localProduct, Finset.mem_filter, Finset.mem_powerset]
    refine ⟨hK.1, ?_⟩
    intro b
    apply hK.2.2 (blockPart blockOf b K)
    refine Finset.ssubset_iff_subset_ne.mpr
      ⟨blockPart_subset blockOf b K, ?_⟩
    intro hEq
    apply hCut
    refine ⟨b, ?_⟩
    intro u hu
    have hPart : u ∈ blockPart blockOf b K := by
      rw [hEq]
      exact hu
    exact (Finset.mem_filter.mp hPart).2
  · exact hK.2.1

/-- Independent block checks reconstruct the source family exactly iff every
minimal nonface remains inside one block. -/
theorem exactFactorization_iff_minimalNonfaces_withinBlocks
    (source : Finset (Finset U)) (blockOf : U -> B)
    (wf : SourceFamilyWellFormed source) :
    ExactFactorization source blockOf ↔
      ∀ K : Finset U, MinimalNonface source K -> WithinBlock blockOf K := by
  constructor
  · intro hFactor K hK
    by_contra hCut
    obtain ⟨hLocal, hForbidden⟩ :=
      cut_minimalNonface_witness source blockOf hK hCut
    rw [hFactor] at hLocal
    exact hForbidden hLocal
  · intro hWithin
    apply Finset.Subset.antisymm
    · intro C hLocal
      have hLocalData :
          C ⊆ support source ∧
            ∀ b : B, blockPart blockOf b C ∈ source := by
        simpa [localProduct] using hLocal
      by_contra hForbidden
      obtain ⟨K, hKSubset, hK⟩ :=
        exists_minimalNonface_subset source hLocalData.1 hForbidden
      obtain ⟨b, hWithinBlock⟩ := hWithin K hK
      have hBlockSource := hLocalData.2 b
      apply hK.2.1
      apply wf.downwardClosed hBlockSource
      intro u hu
      exact Finset.mem_filter.mpr
        ⟨hKSubset hu, hWithinBlock u hu⟩
    · exact source_subset_localProduct source blockOf wf

/-- Exact controller decompositions are exactly the labellings that identify
every directly coupled pair. -/
theorem exactFactorization_iff_respectsDirectCoupling
    (source : Finset (Finset U)) (blockOf : U -> B)
    (wf : SourceFamilyWellFormed source) :
    ExactFactorization source blockOf ↔
      ∀ u v : U, DirectlyCoupled source u v -> blockOf u = blockOf v := by
  rw [exactFactorization_iff_minimalNonfaces_withinBlocks source blockOf wf]
  constructor
  · intro hWithin u v hCoupled
    obtain ⟨K, hK, hu, hv⟩ := hCoupled
    obtain ⟨b, hBlock⟩ := hWithin K hK
    exact (hBlock u hu).trans (hBlock v hv).symm
  · intro hRespect K hK
    obtain ⟨u0, hu0⟩ := minimalNonface_nonempty source wf hK
    refine ⟨blockOf u0, ?_⟩
    intro u hu
    exact hRespect u u0 ⟨K, hK, hu, hu0⟩

theorem respectsMustCoordinate_of_respectsDirectCoupling
    (source : Finset (Finset U)) (blockOf : U -> B)
    (hRespect :
      ∀ u v : U, DirectlyCoupled source u v -> blockOf u = blockOf v) :
    ∀ u v : U, MustCoordinate source u v -> blockOf u = blockOf v := by
  intro u v hClosure
  induction hClosure with
  | rel x y hxy => exact hRespect x y hxy
  | refl _ => rfl
  | symm _ _ _ ih => exact ih.symm
  | trans _ _ _ _ _ ih₁ ih₂ => exact ih₁.trans ih₂

/-- `MustCoordinate` is the least equivalence relation containing every direct
co-location requirement.  Its classes induce the finest exact block partition,
unique up to block-label renaming: an exact labelling must be constant on those
classes, and any such labelling factorizes the source exactly. -/
theorem exactFactorization_iff_constant_on_mustCoordinate
    (source : Finset (Finset U)) (blockOf : U -> B)
    (wf : SourceFamilyWellFormed source) :
    ExactFactorization source blockOf ↔
      ∀ u v : U, MustCoordinate source u v -> blockOf u = blockOf v := by
  constructor
  · intro hFactor
    apply respectsMustCoordinate_of_respectsDirectCoupling source blockOf
    exact (exactFactorization_iff_respectsDirectCoupling
      source blockOf wf).1 hFactor
  · intro hClosure
    apply (exactFactorization_iff_respectsDirectCoupling
      source blockOf wf).2
    intro u v hDirect
    exact hClosure u v (Relation.EqvGen.rel u v hDirect)

theorem not_exactFactorization_of_cut_minimalNonface
    (source : Finset (Finset U)) (blockOf : U -> B)
    (wf : SourceFamilyWellFormed source)
    {K : Finset U} (hK : MinimalNonface source K)
    (hCut : ¬WithinBlock blockOf K) :
    ¬ExactFactorization source blockOf := by
  rw [exactFactorization_iff_minimalNonfaces_withinBlocks source blockOf wf]
  intro hAll
  exact hCut (hAll K hK)

/-- The cut itself induces a concrete additive capacity policy that is safe for
the source but violated by independently recombining the block-local views. -/
theorem cut_minimalNonface_additive_witness
    (source : Finset (Finset U)) (blockOf : U -> B)
    (wf : SourceFamilyWellFormed source)
    {K : Finset U} (hK : MinimalNonface source K)
    (hCut : ¬WithinBlock blockOf K) :
    ∃ w : U -> Nat,
      SourceSafe source w (K.card - 1) ∧
        ¬TargetSafe (localProduct source blockOf) id w (K.card - 1) := by
  obtain ⟨hLocal, hForbidden⟩ :=
    cut_minimalNonface_witness source blockOf hK hCut
  simpa using
    (forbidden_image_indicator_witness source
      (localProduct source blockOf) id wf hLocal (by simp) (by simpa using hForbidden))

/-! ## A genuinely higher-order coordination fixture -/

namespace Fixtures

/-- Every subset of three cells of size at most two is allowed. -/
def rankTwoFamily : Finset (Finset (Fin 3)) :=
  Finset.univ.filter fun C => C.card ≤ 2

/-- One cell is assigned to the left block and the other two to the right. -/
def splitBlock (u : Fin 3) : Bool :=
  if u = 0 then false else true

def triple : Finset (Fin 3) :=
  Finset.univ

theorem rankTwoFamily_wellFormed :
    SourceFamilyWellFormed rankTwoFamily := by
  refine ⟨⟨∅, by simp [rankTwoFamily]⟩, by simp [rankTwoFamily], ?_⟩
  intro C C' hC hSubset
  simp only [rankTwoFamily, Finset.mem_filter, Finset.mem_univ, true_and] at hC ⊢
  exact (Finset.card_le_card hSubset).trans hC

theorem rankTwoFamily_support :
    support rankTwoFamily = (Finset.univ : Finset (Fin 3)) := by
  apply Finset.Subset.antisymm
  · exact Finset.subset_univ _
  · intro u _
    exact Finset.mem_biUnion.mpr
      ⟨{u}, by simp [rankTwoFamily], by simp⟩

/-- Pairwise analysis sees no conflict at all. -/
theorem every_pair_allowed (u v : Fin 3) :
    ({u, v} : Finset (Fin 3)) ∈ rankTwoFamily := by
  simp only [rankTwoFamily, Finset.mem_filter, Finset.mem_univ, true_and]
  simpa using Finset.card_insert_le u ({v} : Finset (Fin 3))

/-- The three-way combination is forbidden although all proper subsets are
allowed. -/
theorem triple_minimalNonface :
    MinimalNonface rankTwoFamily triple := by
  refine ⟨?_, ?_, ?_⟩
  · rw [rankTwoFamily_support]
    exact Finset.subset_univ _
  · simp [rankTwoFamily, triple]
  · intro L hL
    simp only [rankTwoFamily, Finset.mem_filter, Finset.mem_univ, true_and]
    have hCard := Finset.card_lt_card hL
    simp [triple] at hCard
    omega

theorem splitBlock_cuts_triple :
    ¬WithinBlock splitBlock triple := by
  rintro ⟨b, hBlock⟩
  have hZero := hBlock (0 : Fin 3) (by simp [triple])
  have hOne := hBlock (1 : Fin 3) (by simp [triple])
  have hEq : splitBlock (0 : Fin 3) = splitBlock (1 : Fin 3) :=
    hZero.trans hOne.symm
  simp [splitBlock] at hEq

theorem splitBlock_admits_forbidden_triple :
    triple ∈ localProduct rankTwoFamily splitBlock ∧
      triple ∉ rankTwoFamily :=
  cut_minimalNonface_witness rankTwoFamily splitBlock
    triple_minimalNonface splitBlock_cuts_triple

theorem rankTwoFamily_not_exactly_factorized :
    ¬ExactFactorization rankTwoFamily splitBlock :=
  not_exactFactorization_of_cut_minimalNonface
    rankTwoFamily splitBlock rankTwoFamily_wellFormed
    triple_minimalNonface splitBlock_cuts_triple

/-- Splitting the ternary constraint produces an explicit additive policy that
accepts every source configuration and rejects the recombined triple. -/
theorem rankTwoFamily_additive_counterexample :
    ∃ w : Fin 3 -> Nat,
      SourceSafe rankTwoFamily w (triple.card - 1) ∧
        ¬TargetSafe (localProduct rankTwoFamily splitBlock) id w
          (triple.card - 1) :=
  cut_minimalNonface_additive_witness
    rankTwoFamily splitBlock rankTwoFamily_wellFormed
    triple_minimalNonface splitBlock_cuts_triple

end Fixtures

end AuthorityContinuity.CoordinationDecomposition
