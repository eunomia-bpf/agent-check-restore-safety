import AuthorityContinuity.CoordinationDecomposition
import AuthorityContinuity.DurablePrefixTransport

/-!
# Relational controller covers and physical admission

This module separates semantic-cell identity from controller identity.  A cell
may be accessible through several controllers, each controller has a finite
family of local choices, and a co-live family says which controller sets may
run together.  A physical cover is the union of one local choice per active
controller.

There are two products.  `rawPhysicalCoverProduct` ranges over every finite
cell configuration and is the product used by deployment readiness.
`physicalCoverProduct` deliberately restricts that product to the support of
the admitted family and is used only for minimal-nonface analysis.  Keeping the
two levels separate prevents an outside-support runtime behavior from being
silently filtered before admission.

The static finite-set arguments below are supporting machinery.  In
particular, the minimal-nonface result only becomes a controller-correlation
witness after local-family soundness has ruled out a locally forbidden choice.
-/

namespace AuthorityContinuity.ControllerCoverAdmission

open ConfigurationCellQuotient
open CoordinationDecomposition
open DurablePrefixTransport

set_option linter.unusedSectionVars false

universe uU uG

variable {U : Type uU} {G : Type uG}
variable [Fintype U] [DecidableEq U] [Fintype G] [DecidableEq G]

/-! ## Relational controller model -/

/-- A semantic cell may be accessible through zero, one, or several
controllers.  This is intentionally a relation rather than a `U -> G`
partition. -/
abbrev ControllerAccess (U : Type uU) (G : Type uG) := U -> G -> Prop

/-- The configurations a controller may choose using only its local state. -/
abbrev LocalControllerFamilies (U : Type uU) (G : Type uG) :=
  G -> Finset (Finset U)

/-- Controller sets that the runtime may make live together. -/
abbrev CoLiveFamily (G : Type uG) := Finset (Finset G)

/-- Every cell in `piece` is accessible through controller `g`. -/
def PieceAccessible (access : ControllerAccess U G)
    (g : G) (piece : Finset U) : Prop :=
  ∀ u ∈ piece, access u g

/-- A concrete physical realization: the active controllers and the local
piece selected by each of them. -/
structure CoverPlan (U : Type uU) (G : Type uG) where
  active : Finset G
  piece : G -> Finset U

namespace CoverPlan

/-- A plan is valid when its controller set is co-live, every selected piece
belongs to that controller's local family and respects access, and the pieces
cover exactly `C`. -/
def Valid (plan : CoverPlan U G)
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G)
    (coLive : CoLiveFamily G) (C : Finset U) : Prop :=
  plan.active ∈ coLive ∧
    (∀ g ∈ plan.active, plan.piece g ∈ families g) ∧
    (∀ g ∈ plan.active, PieceAccessible access g (plan.piece g)) ∧
    plan.active.biUnion plan.piece = C

/-- Restrict every local choice to `K`, leaving the co-live controller set
unchanged. -/
def restrict (plan : CoverPlan U G) (K : Finset U) : CoverPlan U G where
  active := plan.active
  piece := fun g => plan.piece g ∩ K

end CoverPlan

/-- Local-family entries are admitted and access-valid.  Access validity is
also checked by `CoverPlan.Valid`; recording it here makes this predicate a
standalone adapter obligation. -/
def LocalFamiliesSound (admitted : Finset (Finset U))
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G) : Prop :=
  ∀ g piece, piece ∈ families g ->
    piece ∈ admitted ∧ PieceAccessible access g piece

/-- Each controller-local family is downward closed.  This is the condition
needed to shrink a physical overpermission to a physically realizable minimal
nonface. -/
def LocalFamiliesDownwardClosed
    (families : LocalControllerFamilies U G) : Prop :=
  ∀ g {C K : Finset U}, C ∈ families g -> K ⊆ C -> K ∈ families g

/-- The maximal local family induced by an admitted family and an access
relation. -/
noncomputable def inducedLocalFamilies
    (admitted : Finset (Finset U))
    (access : ControllerAccess U G) : LocalControllerFamilies U G :=
  by
    classical
    exact fun g => admitted.filter fun C => PieceAccessible access g C

theorem mem_inducedLocalFamilies_iff
    (admitted : Finset (Finset U))
    (access : ControllerAccess U G) (g : G) (C : Finset U) :
    C ∈ inducedLocalFamilies admitted access g ↔
      C ∈ admitted ∧ PieceAccessible access g C := by
  classical
  simp [inducedLocalFamilies]

theorem inducedLocalFamilies_sound
    (admitted : Finset (Finset U))
    (access : ControllerAccess U G) :
    LocalFamiliesSound admitted access
      (inducedLocalFamilies admitted access) := by
  intro g C hC
  exact (mem_inducedLocalFamilies_iff admitted access g C).1 hC

theorem inducedLocalFamilies_downwardClosed
    (admitted : Finset (Finset U))
    (access : ControllerAccess U G)
    (wf : SourceFamilyWellFormed admitted) :
    LocalFamiliesDownwardClosed (inducedLocalFamilies admitted access) := by
  intro g C K hC hSubset
  rw [mem_inducedLocalFamilies_iff] at hC ⊢
  refine ⟨wf.downwardClosed hC.1 hSubset, ?_⟩
  intro u hu
  exact hC.2 u (hSubset hu)

/-! ## Raw and fixed-support physical products -/

/-- All unions realized by a co-live valid plan, including configurations
outside the admitted support. -/
noncomputable def rawPhysicalCoverProduct
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G)
    (coLive : CoLiveFamily G) : Finset (Finset U) :=
  by
    classical
    exact (Finset.univ : Finset U).powerset.filter fun C =>
      ∃ plan : CoverPlan U G, plan.Valid access families coLive C

/-- The physical product inside the fixed support of `admitted`.  This support
restriction is what makes every remaining forbidden union contain a minimal
nonface of `admitted`. -/
noncomputable def physicalCoverProduct
    (admitted : Finset (Finset U))
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G)
    (coLive : CoLiveFamily G) : Finset (Finset U) :=
  by
    classical
    exact (support admitted).powerset.filter fun C =>
      ∃ plan : CoverPlan U G, plan.Valid access families coLive C

theorem mem_rawPhysicalCoverProduct_iff
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G)
    (coLive : CoLiveFamily G) (C : Finset U) :
    C ∈ rawPhysicalCoverProduct access families coLive ↔
      ∃ plan : CoverPlan U G, plan.Valid access families coLive C := by
  classical
  simp [rawPhysicalCoverProduct]

theorem mem_physicalCoverProduct_iff
    (admitted : Finset (Finset U))
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G)
    (coLive : CoLiveFamily G) (C : Finset U) :
    C ∈ physicalCoverProduct admitted access families coLive ↔
      C ⊆ support admitted ∧
        ∃ plan : CoverPlan U G, plan.Valid access families coLive C := by
  classical
  simp [physicalCoverProduct]

theorem physicalCoverProduct_subset_raw
    (admitted : Finset (Finset U))
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G)
    (coLive : CoLiveFamily G) :
    physicalCoverProduct admitted access families coLive ⊆
      rawPhysicalCoverProduct access families coLive := by
  intro C hC
  rw [mem_rawPhysicalCoverProduct_iff]
  exact ((mem_physicalCoverProduct_iff admitted access families coLive C).1 hC).2

theorem CoverPlan.restrict_valid
    {access : ControllerAccess U G}
    {families : LocalControllerFamilies U G}
    {coLive : CoLiveFamily G} {C K : Finset U}
    {plan : CoverPlan U G}
    (hValid : plan.Valid access families coLive C)
    (hSubset : K ⊆ C)
    (hDown : LocalFamiliesDownwardClosed families) :
    (plan.restrict K).Valid access families coLive K := by
  rcases hValid with ⟨hCoLive, hLocal, hAccess, hUnion⟩
  refine ⟨hCoLive, ?_, ?_, ?_⟩
  · intro g hg
    exact hDown g (hLocal g hg) Finset.inter_subset_left
  · intro g hg u hu
    exact hAccess g hg u (Finset.mem_inter.mp hu).1
  · ext u
    constructor
    · intro hu
      obtain ⟨g, hg, huPiece⟩ := Finset.mem_biUnion.mp hu
      exact (Finset.mem_inter.mp huPiece).2
    · intro huK
      have huC : u ∈ C := hSubset huK
      have huUnion : u ∈ plan.active.biUnion plan.piece := by
        rw [hUnion]
        exact huC
      obtain ⟨g, hg, huPiece⟩ := Finset.mem_biUnion.mp huUnion
      exact Finset.mem_biUnion.mpr
        ⟨g, hg, Finset.mem_inter.mpr ⟨huPiece, huK⟩⟩

theorem physicalCoverProduct_downwardClosed
    (admitted : Finset (Finset U))
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G)
    (coLive : CoLiveFamily G)
    (hDown : LocalFamiliesDownwardClosed families)
    {C K : Finset U}
    (hC : C ∈ physicalCoverProduct admitted access families coLive)
    (hSubset : K ⊆ C) :
    K ∈ physicalCoverProduct admitted access families coLive := by
  rw [mem_physicalCoverProduct_iff] at hC ⊢
  obtain ⟨hSupport, plan, hValid⟩ := hC
  exact ⟨hSubset.trans hSupport, plan.restrict K,
    plan.restrict_valid hValid hSubset hDown⟩

theorem rawPhysicalCoverProduct_downwardClosed
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G)
    (coLive : CoLiveFamily G)
    (hDown : LocalFamiliesDownwardClosed families)
    {C K : Finset U}
    (hC : C ∈ rawPhysicalCoverProduct access families coLive)
    (hSubset : K ⊆ C) :
    K ∈ rawPhysicalCoverProduct access families coLive := by
  rw [mem_rawPhysicalCoverProduct_iff] at hC ⊢
  obtain ⟨plan, hValid⟩ := hC
  exact ⟨plan.restrict K, plan.restrict_valid hValid hSubset hDown⟩

/-! ## Readiness and failure decomposition -/

/-- Deployment readiness checks the raw physical product.  `required` records
the typed operation's mandatory behaviors; no outside-support behavior is
silently discarded before this sandwich check. -/
def DeploymentReady (required admitted : Finset (Finset U))
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G)
    (coLive : CoLiveFamily G) : Prop :=
  required ⊆ rawPhysicalCoverProduct access families coLive ∧
    rawPhysicalCoverProduct access families coLive ⊆ admitted

def Overpermission (admitted : Finset (Finset U))
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G)
  (coLive : CoLiveFamily G) : Prop :=
  ∃ C : Finset U,
    C ∈ rawPhysicalCoverProduct access families coLive ∧ C ∉ admitted

def MissingRequired (required : Finset (Finset U))
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G)
  (coLive : CoLiveFamily G) : Prop :=
  ∃ C : Finset U,
    C ∈ required ∧ C ∉ rawPhysicalCoverProduct access families coLive

/-- Readiness fails for at least one of two semantic reasons: the physical
implementation adds behavior, it cannot realize a required behavior, or both
failures occur together. -/
theorem not_deploymentReady_iff_overpermission_or_missingRequired
    (required admitted : Finset (Finset U))
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G)
    (coLive : CoLiveFamily G) :
    ¬DeploymentReady required admitted access families coLive ↔
      Overpermission admitted access families coLive ∨
        MissingRequired required access families coLive := by
  classical
  constructor
  · intro hNotReady
    by_cases hRequired :
        required ⊆ rawPhysicalCoverProduct access families coLive
    · left
      have hNotSafe :
          ¬rawPhysicalCoverProduct access families coLive ⊆ admitted := by
        intro hSafe
        exact hNotReady ⟨hRequired, hSafe⟩
      by_contra hNoWitness
      apply hNotSafe
      intro C hPhysical
      by_contra hForbidden
      exact hNoWitness ⟨C, hPhysical, hForbidden⟩
    · right
      by_contra hNoWitness
      apply hRequired
      intro C hC
      by_contra hNotPhysical
      exact hNoWitness ⟨C, hC, hNotPhysical⟩
  · rintro (hOver | hMissing) hReady
    · obtain ⟨C, hPhysical, hForbidden⟩ := hOver
      exact hForbidden (hReady.2 hPhysical)
    · obtain ⟨C, hRequired, hNotPhysical⟩ := hMissing
      exact hNotPhysical (hReady.1 hRequired)

/-! ## Runtime refinement through the physical envelope -/

/-- A runtime need not realize every behavior in the conservative physical
product.  If its actual family preserves the required behaviors and refines
that product, deployment readiness places every actual behavior inside the
admitted family. -/
theorem actual_sandwich_of_deploymentReady
    (required admitted actual : Finset (Finset U))
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G)
    (coLive : CoLiveFamily G)
    (hReady : DeploymentReady required admitted access families coLive)
    (hActual :
      required ⊆ actual ∧
        actual ⊆ rawPhysicalCoverProduct access families coLive) :
    required ⊆ actual ∧ actual ⊆ admitted :=
  ⟨hActual.1, hActual.2.trans hReady.2⟩

universe uA

/-- Prefix configuration morphisms are closed under restricting the target
family.  This elementary bridge lets a runtime prove only
`actual ⊆ RawPhysical`: readiness and an admitted-family certificate then yield
the same durable-prefix safety certificate for the actual trace family. -/
theorem prefixConfigMorphism_mono_target
    {A : Type uA} [Fintype A] [DecidableEq A]
    (authority : Finset (Finset A)) (durable : Finset A)
    (admitted actual : Finset (Finset U)) (lineage : U -> A)
    (hActual : actual ⊆ admitted)
    (hAdmitted : PrefixConfigMorphism authority durable admitted lineage) :
    PrefixConfigMorphism authority durable actual lineage := by
  refine ⟨hAdmitted.1, ?_⟩
  intro C hC
  exact hAdmitted.2 C (hActual hC)

theorem actual_prefixConfigMorphism_of_deploymentReady
    {A : Type uA} [Fintype A] [DecidableEq A]
    (authority : Finset (Finset A)) (durable : Finset A)
    (required admitted actual : Finset (Finset U)) (lineage : U -> A)
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G)
    (coLive : CoLiveFamily G)
    (hReady : DeploymentReady required admitted access families coLive)
    (hActual :
      required ⊆ actual ∧
        actual ⊆ rawPhysicalCoverProduct access families coLive)
    (hAdmitted : PrefixConfigMorphism authority durable admitted lineage) :
    PrefixConfigMorphism authority durable actual lineage :=
  prefixConfigMorphism_mono_target authority durable admitted actual lineage
    (actual_sandwich_of_deploymentReady
      required admitted actual access families coLive hReady hActual).2
    hAdmitted

/-! ## Bridge to functional controller partitions -/

/-- Canonical access relation induced by a functional block assignment. -/
def partitionAccess (blockOf : U -> G) : ControllerAccess U G :=
  fun u g => blockOf u = g

/-- Canonical controller-local families: admitted configurations containing
only cells assigned to the selected block. -/
noncomputable def partitionLocalFamilies
    (admitted : Finset (Finset U)) (blockOf : U -> G) :
    LocalControllerFamilies U G :=
  inducedLocalFamilies admitted (partitionAccess blockOf)

/-- The canonical partition adapter runs all block controllers together. -/
def partitionCoLive : CoLiveFamily G :=
  {(Finset.univ : Finset G)}

/-- The canonical cover plan chooses the block restriction of `C` at each
controller. -/
def partitionCoverPlan (blockOf : U -> G) (C : Finset U) : CoverPlan U G where
  active := Finset.univ
  piece := fun g => blockPart blockOf g C

theorem mem_partitionLocalFamilies_iff
    (admitted : Finset (Finset U)) (blockOf : U -> G)
    (g : G) (C : Finset U) :
    C ∈ partitionLocalFamilies admitted blockOf g ↔
      C ∈ admitted ∧ ∀ u ∈ C, blockOf u = g := by
  simpa [partitionLocalFamilies, partitionAccess, PieceAccessible] using
    (mem_inducedLocalFamilies_iff
      admitted (partitionAccess blockOf) g C)

theorem partitionLocalFamilies_sound
    (admitted : Finset (Finset U)) (blockOf : U -> G) :
    LocalFamiliesSound admitted (partitionAccess blockOf)
      (partitionLocalFamilies admitted blockOf) :=
  inducedLocalFamilies_sound admitted (partitionAccess blockOf)

theorem partitionLocalFamilies_downwardClosed
    (admitted : Finset (Finset U)) (blockOf : U -> G)
    (wf : SourceFamilyWellFormed admitted) :
    LocalFamiliesDownwardClosed (partitionLocalFamilies admitted blockOf) :=
  inducedLocalFamilies_downwardClosed
    admitted (partitionAccess blockOf) wf

theorem partition_blockParts_union
    (blockOf : U -> G) (C : Finset U) :
    (Finset.univ : Finset G).biUnion
        (fun g => blockPart blockOf g C) = C := by
  ext u
  constructor
  · intro hu
    obtain ⟨g, _, huPart⟩ := Finset.mem_biUnion.mp hu
    exact (Finset.mem_filter.mp huPart).1
  · intro hu
    exact Finset.mem_biUnion.mpr
      ⟨blockOf u, Finset.mem_univ _,
        Finset.mem_filter.mpr ⟨hu, rfl⟩⟩

theorem partitionCoverPlan_valid_of_mem_localProduct
    (admitted : Finset (Finset U)) (blockOf : U -> G)
    {C : Finset U} (hC : C ∈ localProduct admitted blockOf) :
    (partitionCoverPlan blockOf C).Valid
      (partitionAccess blockOf)
      (partitionLocalFamilies admitted blockOf)
      partitionCoLive C := by
  have hData :
      C ⊆ support admitted ∧
        ∀ g : G, blockPart blockOf g C ∈ admitted := by
    simpa [localProduct] using hC
  have hLocal := hData.2
  refine ⟨by simp [partitionCoverPlan, partitionCoLive], ?_, ?_, ?_⟩
  · intro g _
    rw [mem_partitionLocalFamilies_iff]
    refine ⟨hLocal g, ?_⟩
    intro u hu
    exact (Finset.mem_filter.mp hu).2
  · intro g _ u hu
    exact (Finset.mem_filter.mp hu).2
  · exact partition_blockParts_union blockOf C

/-- The canonical relation adapter is not merely analogous to functional
partitioning: its raw physical product is extensionally the existing
`localProduct`. -/
theorem rawPhysical_partition_eq_localProduct
    (admitted : Finset (Finset U)) (blockOf : U -> G)
    (wf : SourceFamilyWellFormed admitted) :
    rawPhysicalCoverProduct
        (partitionAccess blockOf)
        (partitionLocalFamilies admitted blockOf)
        partitionCoLive =
      localProduct admitted blockOf := by
  apply Finset.Subset.antisymm
  · intro C hRaw
    obtain ⟨plan, hValid⟩ :=
      (mem_rawPhysicalCoverProduct_iff
        (partitionAccess blockOf)
        (partitionLocalFamilies admitted blockOf)
        partitionCoLive C).1 hRaw
    rcases hValid with ⟨hActiveMem, hPlanLocal, hAccess, hUnion⟩
    have hActive : plan.active = (Finset.univ : Finset G) := by
      simpa [partitionCoLive] using hActiveMem
    have hPieceAdmitted : ∀ g ∈ plan.active, plan.piece g ∈ admitted := by
      intro g hg
      exact ((mem_partitionLocalFamilies_iff
        admitted blockOf g (plan.piece g)).1 (hPlanLocal g hg)).1
    have hSupport : C ⊆ support admitted := by
      intro u huC
      have huUnion : u ∈ plan.active.biUnion plan.piece := by
        rw [hUnion]
        exact huC
      obtain ⟨g, hg, huPiece⟩ := Finset.mem_biUnion.mp huUnion
      exact source_mem_support (hPieceAdmitted g hg) huPiece
    simp only [localProduct, Finset.mem_filter, Finset.mem_powerset]
    refine ⟨hSupport, ?_⟩
    intro g
    have hgActive : g ∈ plan.active := by
      rw [hActive]
      exact Finset.mem_univ g
    have hPartSubset : blockPart blockOf g C ⊆ plan.piece g := by
      intro u huPart
      have huC := (Finset.mem_filter.mp huPart).1
      have hBlock := (Finset.mem_filter.mp huPart).2
      have huUnion : u ∈ plan.active.biUnion plan.piece := by
        rw [hUnion]
        exact huC
      obtain ⟨g', hg', huPiece⟩ := Finset.mem_biUnion.mp huUnion
      have hAssigned : blockOf u = g' := hAccess g' hg' u huPiece
      have hEq : g' = g := hAssigned.symm.trans hBlock
      simpa [hEq] using huPiece
    exact wf.downwardClosed (hPieceAdmitted g hgActive) hPartSubset
  · intro C hLocal
    rw [mem_rawPhysicalCoverProduct_iff]
    exact ⟨partitionCoverPlan blockOf C,
      partitionCoverPlan_valid_of_mem_localProduct
        admitted blockOf hLocal⟩

/-- A concrete relational-controller adapter refines the older functional
partition model when its raw physical product is exactly that partition's
maximal asynchronous `localProduct`.  This equality is an explicit runtime
refinement obligation; it is not inferred merely from an access relation. -/
def FunctionalPartitionRefinement
    (admitted : Finset (Finset U)) (blockOf : U -> G)
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G)
    (coLive : CoLiveFamily G) : Prop :=
  rawPhysicalCoverProduct access families coLive =
    localProduct admitted blockOf

theorem canonicalFunctionalPartitionRefinement
    (admitted : Finset (Finset U)) (blockOf : U -> G)
    (wf : SourceFamilyWellFormed admitted) :
    FunctionalPartitionRefinement admitted blockOf
      (partitionAccess blockOf)
      (partitionLocalFamilies admitted blockOf)
      partitionCoLive :=
  rawPhysical_partition_eq_localProduct admitted blockOf wf

/-- Under the explicit functional-refinement obligation, relational physical
readiness is exactly required-behavior inclusion plus the existing
`MustCoordinate` criterion.  The relation model records additional runtime
structure while reusing the classical partition theorem. -/
theorem functionalPartition_deploymentReady_iff_mustCoordinate
    (required admitted : Finset (Finset U)) (blockOf : U -> G)
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G)
    (coLive : CoLiveFamily G)
    (wf : SourceFamilyWellFormed admitted)
    (hRefines : FunctionalPartitionRefinement
      admitted blockOf access families coLive) :
    DeploymentReady required admitted access families coLive ↔
      required ⊆ admitted ∧
        ∀ u v : U, MustCoordinate admitted u v -> blockOf u = blockOf v := by
  constructor
  · intro hReady
    have hAdmittedSubsetRaw :
        admitted ⊆ rawPhysicalCoverProduct access families coLive := by
      rw [hRefines]
      exact source_subset_localProduct admitted blockOf wf
    have hRawEq :
        rawPhysicalCoverProduct access families coLive = admitted :=
      Finset.Subset.antisymm hReady.2 hAdmittedSubsetRaw
    have hExact : ExactFactorization admitted blockOf := by
      unfold ExactFactorization
      exact hRefines.symm.trans hRawEq
    exact ⟨hReady.1.trans hReady.2,
      (exactFactorization_iff_constant_on_mustCoordinate
        admitted blockOf wf).1 hExact⟩
  · rintro ⟨hRequired, hCoordinate⟩
    have hExact : ExactFactorization admitted blockOf :=
      (exactFactorization_iff_constant_on_mustCoordinate
        admitted blockOf wf).2 hCoordinate
    have hRawEq :
        rawPhysicalCoverProduct access families coLive = admitted :=
      hRefines.trans hExact
    unfold DeploymentReady
    rw [hRawEq]
    exact ⟨hRequired, fun _ h => h⟩

/-- For the canonical adapter, the equality premise above is discharged by
construction. -/
theorem canonicalPartition_deploymentReady_iff_mustCoordinate
    (required admitted : Finset (Finset U)) (blockOf : U -> G)
    (wf : SourceFamilyWellFormed admitted) :
    DeploymentReady required admitted
        (partitionAccess blockOf)
        (partitionLocalFamilies admitted blockOf)
        partitionCoLive ↔
      required ⊆ admitted ∧
        ∀ u v : U, MustCoordinate admitted u v -> blockOf u = blockOf v :=
  functionalPartition_deploymentReady_iff_mustCoordinate
    required admitted blockOf
    (partitionAccess blockOf)
    (partitionLocalFamilies admitted blockOf)
    partitionCoLive wf
    (canonicalFunctionalPartitionRefinement admitted blockOf wf)

/-! ## Honest causes of a raw physical overpermission -/

/-- The raw cover leaves the declared admitted support. -/
def OutsideSupport (admitted : Finset (Finset U)) (C : Finset U) : Prop :=
  C ∉ admitted ∧ ¬C ⊆ support admitted

/-- The union stays on the admitted support, but at least one controller has
already made a locally forbidden choice. -/
def LocalOverpermission (admitted : Finset (Finset U))
    (plan : CoverPlan U G) (C : Finset U) : Prop :=
  C ∉ admitted ∧ C ⊆ support admitted ∧
    ∃ g ∈ plan.active, plan.piece g ∉ admitted

/-- Every selected local piece is admitted, but their physically co-live union
is forbidden.  Only this third case is a genuine controller-correlation cut. -/
def CorrelationCut (admitted : Finset (Finset U))
    (plan : CoverPlan U G) (C : Finset U) : Prop :=
  C ∉ admitted ∧ C ⊆ support admitted ∧
    ∀ g ∈ plan.active, plan.piece g ∈ admitted

/-- Every forbidden raw valid cover has one of three causes.  The definitions
make the cases pairwise exclusive by giving support failure precedence over a
local violation, and local violation precedence over correlation. -/
theorem forbidden_valid_cover_cases
    (admitted : Finset (Finset U))
    {access : ControllerAccess U G}
    {families : LocalControllerFamilies U G}
    {coLive : CoLiveFamily G} {C : Finset U}
    {plan : CoverPlan U G}
    (_hValid : plan.Valid access families coLive C)
    (hForbidden : C ∉ admitted) :
    OutsideSupport admitted C ∨
      LocalOverpermission admitted plan C ∨
      CorrelationCut admitted plan C := by
  classical
  by_cases hSupport : C ⊆ support admitted
  · by_cases hLocal : ∀ g ∈ plan.active, plan.piece g ∈ admitted
    · exact Or.inr (Or.inr ⟨hForbidden, hSupport, hLocal⟩)
    · right
      left
      refine ⟨hForbidden, hSupport, ?_⟩
      push Not at hLocal
      exact hLocal
  · exact Or.inl ⟨hForbidden, hSupport⟩

theorem forbidden_cover_causes_pairwise
    (admitted : Finset (Finset U))
    (plan : CoverPlan U G) (C : Finset U) :
    (OutsideSupport admitted C ->
      ¬LocalOverpermission admitted plan C ∧
        ¬CorrelationCut admitted plan C) ∧
    (LocalOverpermission admitted plan C ->
      ¬OutsideSupport admitted C ∧
        ¬CorrelationCut admitted plan C) ∧
    (CorrelationCut admitted plan C ->
      ¬OutsideSupport admitted C ∧
        ¬LocalOverpermission admitted plan C) := by
  constructor
  · rintro ⟨_, hOutside⟩
    exact ⟨fun h => hOutside h.2.1, fun h => hOutside h.2.1⟩
  constructor
  · rintro ⟨_, hSupport, g, hg, hLocalForbidden⟩
    refine ⟨fun h => h.2 hSupport, ?_⟩
    intro hCorrelation
    exact hLocalForbidden (hCorrelation.2.2 g hg)
  · rintro ⟨_, hSupport, hLocal⟩
    refine ⟨fun h => h.2 hSupport, ?_⟩
    rintro ⟨_, _, g, hg, hLocalForbidden⟩
    exact hLocalForbidden (hLocal g hg)

theorem raw_overpermission_has_cause
    (admitted : Finset (Finset U))
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G)
    (coLive : CoLiveFamily G)
    (hOver : Overpermission admitted access families coLive) :
    ∃ C : Finset U, ∃ plan : CoverPlan U G,
      C ∈ rawPhysicalCoverProduct access families coLive ∧
        plan.Valid access families coLive C ∧
        (OutsideSupport admitted C ∨
          LocalOverpermission admitted plan C ∨
          CorrelationCut admitted plan C) := by
  obtain ⟨C, hRaw, hForbidden⟩ := hOver
  obtain ⟨plan, hValid⟩ :=
    (mem_rawPhysicalCoverProduct_iff access families coLive C).1 hRaw
  exact ⟨C, plan, hRaw, hValid,
    forbidden_valid_cover_cases admitted hValid hForbidden⟩

/-- No raw behavior leaves the fixed admitted support. -/
def AvoidsOutsideSupport (admitted : Finset (Finset U))
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G)
    (coLive : CoLiveFamily G) : Prop :=
  ∀ C ∈ rawPhysicalCoverProduct access families coLive,
    C ⊆ support admitted

/-- No minimal nonface is physically realizable. -/
def AvoidsMinimalNonfaces (admitted : Finset (Finset U))
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G)
    (coLive : CoLiveFamily G) : Prop :=
  ∀ K : Finset U, MinimalNonface admitted K ->
    K ∉ rawPhysicalCoverProduct access families coLive

/-- For downward-closed local families, raw physical safety has an exact
obstruction characterization: avoid support escape and every physically
realizable minimal nonface. -/
theorem rawPhysical_subset_admitted_iff_avoids_obstructions
    (admitted : Finset (Finset U))
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G)
    (coLive : CoLiveFamily G)
    (hDown : LocalFamiliesDownwardClosed families) :
    rawPhysicalCoverProduct access families coLive ⊆ admitted ↔
      AvoidsOutsideSupport admitted access families coLive ∧
        AvoidsMinimalNonfaces admitted access families coLive := by
  constructor
  · intro hSafe
    constructor
    · intro C hRaw
      exact source_mem_support (hSafe hRaw)
    · intro K hMinimal hRaw
      exact hMinimal.2.1 (hSafe hRaw)
  · rintro ⟨hSupport, hAvoids⟩ C hRaw
    by_contra hForbidden
    obtain ⟨K, hSubset, hMinimal⟩ :=
      exists_minimalNonface_subset admitted (hSupport C hRaw) hForbidden
    exact hAvoids K hMinimal
      (rawPhysicalCoverProduct_downwardClosed
        access families coLive hDown hRaw hSubset)

/-- Compiler-facing readiness criterion: required coverage plus absence of the
two complete raw-product obstructions. -/
theorem deploymentReady_iff_required_coverage_and_avoids_obstructions
    (required admitted : Finset (Finset U))
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G)
    (coLive : CoLiveFamily G)
    (hDown : LocalFamiliesDownwardClosed families) :
    DeploymentReady required admitted access families coLive ↔
      required ⊆ rawPhysicalCoverProduct access families coLive ∧
        AvoidsOutsideSupport admitted access families coLive ∧
        AvoidsMinimalNonfaces admitted access families coLive := by
  constructor
  · rintro ⟨hRequired, hSafe⟩
    obtain ⟨hOutside, hMinimal⟩ :=
      (rawPhysical_subset_admitted_iff_avoids_obstructions
        admitted access families coLive hDown).1 hSafe
    exact ⟨hRequired, hOutside, hMinimal⟩
  · rintro ⟨hRequired, hOutside, hMinimal⟩
    exact ⟨hRequired,
      (rawPhysical_subset_admitted_iff_avoids_obstructions
        admitted access families coLive hDown).2 ⟨hOutside, hMinimal⟩⟩

/-- The fixed-support physical product rules out the first raw failure cause. -/
theorem physicalCoverProduct_not_outsideSupport
    (admitted : Finset (Finset U))
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G)
    (coLive : CoLiveFamily G)
    {C : Finset U}
    (hPhysical : C ∈ physicalCoverProduct admitted access families coLive) :
    ¬OutsideSupport admitted C := by
  intro hOutside
  exact hOutside.2
    ((mem_physicalCoverProduct_iff admitted access families coLive C).1 hPhysical).1

/-- Local-family soundness rules out the second raw failure cause for a valid
plan. -/
theorem validPlan_not_localOverpermission
    (admitted : Finset (Finset U))
    {access : ControllerAccess U G}
    {families : LocalControllerFamilies U G}
    {coLive : CoLiveFamily G} {C : Finset U}
    {plan : CoverPlan U G}
    (hSound : LocalFamiliesSound admitted access families)
    (hValid : plan.Valid access families coLive C) :
    ¬LocalOverpermission admitted plan C := by
  rintro ⟨_, _, g, hg, hForbidden⟩
  exact hForbidden (hSound g (plan.piece g) (hValid.2.1 g hg)).1

/-- With locally sound controller families, a raw physical overpermission is
either an outside-support adapter failure or a genuine in-support correlation
cut. -/
theorem raw_overpermission_under_localSound
    (admitted : Finset (Finset U))
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G)
    (coLive : CoLiveFamily G)
    (hSound : LocalFamiliesSound admitted access families)
    (hOver : Overpermission admitted access families coLive) :
    ∃ C : Finset U, ∃ plan : CoverPlan U G,
      C ∈ rawPhysicalCoverProduct access families coLive ∧
        plan.Valid access families coLive C ∧
        (OutsideSupport admitted C ∨ CorrelationCut admitted plan C) := by
  obtain ⟨C, plan, hRaw, hValid, hCause⟩ :=
    raw_overpermission_has_cause admitted access families coLive hOver
  refine ⟨C, plan, hRaw, hValid, ?_⟩
  rcases hCause with hOutside | hLocal | hCorrelation
  · exact Or.inl hOutside
  · exact (validPlan_not_localOverpermission admitted hSound hValid hLocal).elim
  · exact Or.inr hCorrelation

/-- Inside the support-restricted analysis product, local-family soundness is
the remaining premise needed to classify a forbidden union as a correlation
cut. -/
theorem physical_overpermission_is_correlationCut
    (admitted : Finset (Finset U))
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G)
    (coLive : CoLiveFamily G)
    (hSound : LocalFamiliesSound admitted access families)
    {C : Finset U}
    (hPhysical : C ∈ physicalCoverProduct admitted access families coLive)
    (hForbidden : C ∉ admitted) :
    ∃ plan : CoverPlan U G,
      plan.Valid access families coLive C ∧ CorrelationCut admitted plan C := by
  obtain ⟨hSupport, plan, hValid⟩ :=
    (mem_physicalCoverProduct_iff admitted access families coLive C).1 hPhysical
  refine ⟨plan, hValid, hForbidden, hSupport, ?_⟩
  intro g hg
  exact (hSound g (plan.piece g) (hValid.2.1 g hg)).1

/-! ## Minimal nonfaces and GateCut witnesses -/

/-- A physically realized minimal nonface whose active local pieces are all
admitted.  The local-admittedness conjunct prevents a single locally
overpermissive controller from being mislabeled as a GateCut. -/
def GateCutWitness (admitted : Finset (Finset U))
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G)
    (coLive : CoLiveFamily G) (K : Finset U) : Prop :=
  MinimalNonface admitted K ∧
    ∃ plan : CoverPlan U G,
      plan.Valid access families coLive K ∧
        ∀ g ∈ plan.active, plan.piece g ∈ admitted

/-- Every fixed-support physical overpermission contains a minimal nonface.
This theorem alone does not say that the subconfiguration is physically
realizable. -/
theorem physical_overpermission_contains_minimalNonface
    (admitted : Finset (Finset U))
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G)
    (coLive : CoLiveFamily G)
    {C : Finset U}
    (hPhysical : C ∈ physicalCoverProduct admitted access families coLive)
    (hForbidden : C ∉ admitted) :
    ∃ K : Finset U, K ⊆ C ∧ MinimalNonface admitted K := by
  have hSupport :=
    ((mem_physicalCoverProduct_iff admitted access families coLive C).1 hPhysical).1
  exact exists_minimalNonface_subset admitted hSupport hForbidden

/-- With downward-closed local families, the minimal nonface can be obtained
by restricting the same cover plan, so it is an actual physical GateCut
witness rather than merely a forbidden subset. -/
theorem physical_overpermission_has_gateCutWitness
    (admitted : Finset (Finset U))
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G)
    (coLive : CoLiveFamily G)
    (hDown : LocalFamiliesDownwardClosed families)
    (hSound : LocalFamiliesSound admitted access families)
    {C : Finset U}
    (hPhysical : C ∈ physicalCoverProduct admitted access families coLive)
    (hForbidden : C ∉ admitted) :
    ∃ K : Finset U, K ⊆ C ∧
      GateCutWitness admitted access families coLive K := by
  obtain ⟨K, hSubset, hMinimal⟩ :=
    physical_overpermission_contains_minimalNonface
      admitted access families coLive hPhysical hForbidden
  have hKPhysical := physicalCoverProduct_downwardClosed
    admitted access families coLive hDown hPhysical hSubset
  obtain ⟨_, plan, hValid⟩ :=
    (mem_physicalCoverProduct_iff admitted access families coLive K).1 hKPhysical
  refine ⟨K, hSubset, hMinimal, plan, hValid, ?_⟩
  intro g hg
  exact (hSound g (plan.piece g) (hValid.2.1 g hg)).1

theorem gateCutWitness_overpermission
    (admitted : Finset (Finset U))
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G)
    (coLive : CoLiveFamily G)
    {K : Finset U}
    (hGateCut : GateCutWitness admitted access families coLive K) :
    K ∈ physicalCoverProduct admitted access families coLive ∧ K ∉ admitted := by
  obtain ⟨hMinimal, plan, hValid, _hLocal⟩ := hGateCut
  constructor
  · rw [mem_physicalCoverProduct_iff]
    exact ⟨hMinimal.1, plan, hValid⟩
  · exact hMinimal.2.1

/-- For a genuine correlation cut, every active controller contributes only a
proper subset of the forbidden minimal nonface. -/
theorem gateCut_each_active_piece_proper
    (admitted : Finset (Finset U))
    {access : ControllerAccess U G}
    {families : LocalControllerFamilies U G}
    {coLive : CoLiveFamily G} {K : Finset U}
    {plan : CoverPlan U G}
    (hSound : LocalFamiliesSound admitted access families)
    (hMinimal : MinimalNonface admitted K)
    (hValid : plan.Valid access families coLive K) :
    ∀ g ∈ plan.active, plan.piece g ⊂ K := by
  rcases hValid with ⟨_, hLocal, _, hUnion⟩
  intro g hg
  have hSubset : plan.piece g ⊆ K := by
    intro u hu
    have huUnion : u ∈ plan.active.biUnion plan.piece :=
      Finset.mem_biUnion.mpr ⟨g, hg, hu⟩
    rw [hUnion] at huUnion
    exact huUnion
  refine Finset.ssubset_iff_subset_ne.mpr ⟨hSubset, ?_⟩
  intro hEq
  apply hMinimal.2.1
  rw [← hEq]
  exact (hSound g (plan.piece g) (hLocal g hg)).1

/-- A locally sound GateCut of a well-formed family necessarily uses at least
two distinct controllers with nonempty contributions. -/
theorem gateCut_uses_distinct_contributing_controllers
    (admitted : Finset (Finset U))
    {access : ControllerAccess U G}
    {families : LocalControllerFamilies U G}
    {coLive : CoLiveFamily G} {K : Finset U}
    {plan : CoverPlan U G}
    (wf : SourceFamilyWellFormed admitted)
    (hSound : LocalFamiliesSound admitted access families)
    (hMinimal : MinimalNonface admitted K)
    (hValid : plan.Valid access families coLive K) :
    ∃ g1 g2 : G,
      g1 ∈ plan.active ∧ g2 ∈ plan.active ∧ g1 ≠ g2 ∧
        (plan.piece g1).Nonempty ∧ (plan.piece g2).Nonempty := by
  obtain ⟨u, huK⟩ := minimalNonface_nonempty admitted wf hMinimal
  have hUnion := hValid.2.2.2
  have huUnion : u ∈ plan.active.biUnion plan.piece := by
    rw [hUnion]
    exact huK
  obtain ⟨g1, hg1, huPiece⟩ := Finset.mem_biUnion.mp huUnion
  have hProper := gateCut_each_active_piece_proper admitted
    hSound hMinimal hValid g1 hg1
  have hMissing : ∃ v : U, v ∈ K ∧ v ∉ plan.piece g1 := by
    by_contra hNoMissing
    have hKSubset : K ⊆ plan.piece g1 := by
      intro v hvK
      by_contra hvNotPiece
      exact hNoMissing ⟨v, hvK, hvNotPiece⟩
    have hEq : plan.piece g1 = K :=
      Finset.Subset.antisymm hProper.subset hKSubset
    exact (Finset.ssubset_iff_subset_ne.mp hProper).2 hEq
  obtain ⟨v, hvK, hvNotPiece⟩ := hMissing
  have hvUnion : v ∈ plan.active.biUnion plan.piece := by
    rw [hUnion]
    exact hvK
  obtain ⟨g2, hg2, hvPiece⟩ := Finset.mem_biUnion.mp hvUnion
  have hDistinct : g1 ≠ g2 := by
    intro hEq
    subst g2
    exact hvNotPiece hvPiece
  exact ⟨g1, g2, hg1, hg2, hDistinct,
    ⟨u, huPiece⟩, ⟨v, hvPiece⟩⟩

/-! ## A relational U(2,3) GateCut fixture -/

namespace Fixtures

open CoordinationDecomposition.Fixtures

/-- Both controllers can access every semantic cell.  Thus controller identity
is genuinely independent from semantic-cell identity; this fixture does not
model or claim a common controller origin. -/
def sharedAccess (_u : Fin 3) (_g : Bool) : Prop := True

def splitPiece (g : Bool) : Finset (Fin 3) :=
  if g then {1, 2} else {0}

/-- Each controller locally admits every subset of its selected proper face. -/
def splitLocal (g : Bool) : Finset (Finset (Fin 3)) :=
  (splitPiece g).powerset

/-- The two controller instances may be live together. -/
def splitCoLive : Finset (Finset Bool) :=
  {{false, true}}

def splitCoverPlan : CoverPlan (Fin 3) Bool where
  active := {false, true}
  piece := splitPiece

theorem splitLocal_sound :
    LocalFamiliesSound rankTwoFamily sharedAccess splitLocal := by
  intro g C hC
  constructor
  · simp only [rankTwoFamily, Finset.mem_filter, Finset.mem_univ, true_and]
    have hCard := Finset.card_le_card (Finset.mem_powerset.mp hC)
    cases g <;> simp [splitPiece] at hCard ⊢ <;> omega
  · simp [PieceAccessible, sharedAccess]

theorem splitLocal_downwardClosed :
    LocalFamiliesDownwardClosed splitLocal := by
  intro g C K hC hSubset
  exact Finset.mem_powerset.mpr
    (hSubset.trans (Finset.mem_powerset.mp hC))

theorem splitCoverPlan_valid :
    splitCoverPlan.Valid sharedAccess splitLocal splitCoLive triple := by
  refine ⟨by simp [splitCoverPlan, splitCoLive], ?_, ?_, ?_⟩
  · intro g hg
    simp [splitCoverPlan, splitLocal]
  · intro g hg
    simp [splitCoverPlan, PieceAccessible, sharedAccess]
  · ext u
    fin_cases u <;> simp [splitCoverPlan, splitPiece, triple]

theorem triple_gateCutWitness :
    GateCutWitness rankTwoFamily sharedAccess splitLocal splitCoLive triple := by
  refine ⟨triple_minimalNonface, splitCoverPlan, splitCoverPlan_valid, ?_⟩
  intro g hg
  exact (splitLocal_sound g (splitCoverPlan.piece g)
    (splitCoverPlan_valid.2.1 g hg)).1

theorem split_controllers_admit_forbidden_triple :
    triple ∈ physicalCoverProduct
        rankTwoFamily sharedAccess splitLocal splitCoLive ∧
      triple ∉ rankTwoFamily :=
  gateCutWitness_overpermission
    rankTwoFamily sharedAccess splitLocal splitCoLive triple_gateCutWitness

theorem split_gateCut_uses_two_controllers :
    ∃ g1 g2 : Bool,
      g1 ∈ splitCoverPlan.active ∧ g2 ∈ splitCoverPlan.active ∧ g1 ≠ g2 ∧
        (splitCoverPlan.piece g1).Nonempty ∧
        (splitCoverPlan.piece g2).Nonempty :=
  gateCut_uses_distinct_contributing_controllers
    rankTwoFamily rankTwoFamily_wellFormed splitLocal_sound
    triple_minimalNonface splitCoverPlan_valid

theorem each_cell_has_shared_access (u : Fin 3) :
    sharedAccess u false ∧ sharedAccess u true := by
  simp [sharedAccess]

end Fixtures

end AuthorityContinuity.ControllerCoverAdmission
