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

/-- Removing controllers from a possible co-live set leaves another possible
co-live set. -/
def CoLiveDownwardClosed (coLive : CoLiveFamily G) : Prop :=
  ∀ active ∈ coLive, ∀ smaller ⊆ active, smaller ∈ coLive

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

/-! ## Canonical hereditary-safe co-liveness restriction -/

/-- Enlarging the co-live family can only add physical realizations. -/
theorem rawPhysicalCoverProduct_mono_coLive
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G)
    {left right : CoLiveFamily G}
    (hSubset : left ⊆ right) :
    rawPhysicalCoverProduct access families left ⊆
      rawPhysicalCoverProduct access families right := by
  intro C hC
  rw [mem_rawPhysicalCoverProduct_iff] at hC ⊢
  obtain ⟨plan, hValid⟩ := hC
  exact ⟨plan, ⟨hSubset hValid.1, hValid.2⟩⟩

/-- An active controller group is hereditarily safe when every physical
realization enabled by any subset of that group is admitted.  The powerset is
essential: checking only the group itself would not make safety survive later
controller removal when the input co-liveness manifest is not trusted to
encode all subsets correctly. -/
def SafeGroup (admitted : Finset (Finset U))
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G)
    (active : Finset G) : Prop :=
  rawPhysicalCoverProduct access families active.powerset ⊆ admitted

/-- Hereditary group safety itself is downward closed. -/
theorem safeGroup_of_subset
    (admitted : Finset (Finset U))
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G)
    {active smaller : Finset G}
    (hSafe : SafeGroup admitted access families active)
    (hSubset : smaller ⊆ active) :
    SafeGroup admitted access families smaller := by
  intro C hC
  apply hSafe
  refine rawPhysicalCoverProduct_mono_coLive access families
    (left := smaller.powerset) (right := active.powerset) ?_ hC
  intro group hGroup
  exact Finset.mem_powerset.mpr
    ((Finset.mem_powerset.mp hGroup).trans hSubset)

/-- The canonical repair removes exactly the co-live groups whose hereditary
physical behavior is not admitted. -/
noncomputable def hereditarySafeCoLiveRestriction
    (admitted : Finset (Finset U))
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G)
    (coLive : CoLiveFamily G) : CoLiveFamily G := by
  classical
  exact coLive.filter fun active => SafeGroup admitted access families active

theorem mem_hereditarySafeCoLiveRestriction_iff
    (admitted : Finset (Finset U))
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G)
    (coLive : CoLiveFamily G) (active : Finset G) :
    active ∈ hereditarySafeCoLiveRestriction admitted access families coLive ↔
      active ∈ coLive ∧ SafeGroup admitted access families active := by
  classical
  simp [hereditarySafeCoLiveRestriction]

/-- The canonical repair is a restriction of the supplied manifest. -/
theorem hereditarySafeCoLiveRestriction_subset
    (admitted : Finset (Finset U))
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G)
    (coLive : CoLiveFamily G) :
    hereditarySafeCoLiveRestriction admitted access families coLive ⊆ coLive := by
  intro active hActive
  exact ((mem_hereditarySafeCoLiveRestriction_iff
    admitted access families coLive active).1 hActive).1

/-- Filtering a downward-closed manifest by hereditary safety preserves
downward closure. -/
theorem hereditarySafeCoLiveRestriction_downwardClosed
    (admitted : Finset (Finset U))
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G)
    (coLive : CoLiveFamily G)
    (hDown : CoLiveDownwardClosed coLive) :
    CoLiveDownwardClosed
      (hereditarySafeCoLiveRestriction admitted access families coLive) := by
  intro active hActive smaller hSubset
  rw [mem_hereditarySafeCoLiveRestriction_iff] at hActive ⊢
  exact ⟨hDown active hActive.1 smaller hSubset,
    safeGroup_of_subset admitted access families hActive.2 hSubset⟩

/-- Every physical configuration left by the canonical repair is admitted. -/
theorem hereditarySafeCoLiveRestriction_rawPhysical_safe
    (admitted : Finset (Finset U))
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G)
    (coLive : CoLiveFamily G) :
    rawPhysicalCoverProduct access families
        (hereditarySafeCoLiveRestriction admitted access families coLive) ⊆
      admitted := by
  intro C hC
  rw [mem_rawPhysicalCoverProduct_iff] at hC
  obtain ⟨plan, hValid⟩ := hC
  have hActive := (mem_hereditarySafeCoLiveRestriction_iff
    admitted access families coLive plan.active).1 hValid.1
  apply hActive.2
  rw [mem_rawPhysicalCoverProduct_iff]
  exact ⟨plan, ⟨Finset.mem_powerset.mpr Finset.Subset.rfl, hValid.2⟩⟩

/-- Principality: every downward-closed, physically safe subfamily of the
supplied manifest is contained in the canonical repair. -/
theorem hereditarySafeCoLiveRestriction_greatest
    (admitted : Finset (Finset U))
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G)
    (coLive delta : CoLiveFamily G)
    (hDeltaDown : CoLiveDownwardClosed delta)
    (hDeltaSubset : delta ⊆ coLive)
    (hDeltaSafe : rawPhysicalCoverProduct access families delta ⊆ admitted) :
    delta ⊆ hereditarySafeCoLiveRestriction admitted access families coLive := by
  intro active hActive
  rw [mem_hereditarySafeCoLiveRestriction_iff]
  refine ⟨hDeltaSubset hActive, ?_⟩
  intro C hC
  apply hDeltaSafe
  refine rawPhysicalCoverProduct_mono_coLive access families
    (left := active.powerset) (right := delta) ?_ hC
  intro smaller hSmaller
  exact hDeltaDown active hActive smaller (Finset.mem_powerset.mp hSmaller)

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

/-- The canonical repair admits the required behaviors exactly when some
downward-closed safe restriction of the supplied manifest can do so.  Thus the
filter is not merely sound: it is the principal repair for deployment
readiness under controllable co-liveness pruning. -/
theorem required_subset_hereditarySafeCoLiveRestriction_iff_exists_deploymentReady
    (required admitted : Finset (Finset U))
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G)
    (coLive : CoLiveFamily G)
    (hCoLiveDown : CoLiveDownwardClosed coLive) :
    required ⊆ rawPhysicalCoverProduct access families
        (hereditarySafeCoLiveRestriction admitted access families coLive) ↔
      ∃ delta : CoLiveFamily G,
        CoLiveDownwardClosed delta ∧
          delta ⊆ coLive ∧
          DeploymentReady required admitted access families delta := by
  constructor
  · intro hRequired
    exact ⟨hereditarySafeCoLiveRestriction admitted access families coLive,
      hereditarySafeCoLiveRestriction_downwardClosed admitted access families
        coLive hCoLiveDown,
      hereditarySafeCoLiveRestriction_subset admitted access families coLive,
      hRequired,
      hereditarySafeCoLiveRestriction_rawPhysical_safe admitted access families
        coLive⟩
  · rintro ⟨delta, hDeltaDown, hDeltaSubset, hReady⟩
    exact Finset.Subset.trans hReady.1
      (rawPhysicalCoverProduct_mono_coLive access families
        (hereditarySafeCoLiveRestriction_greatest admitted access families
          coLive delta hDeltaDown hDeltaSubset hReady.2))

/-! ### Bridge to durable-prefix pruning -/

universe uS

variable {A : Type uS} [Fintype A] [DecidableEq A]

/-- The two-level principal repair first computes the greatest pointwise
prefix-safe candidate future, then computes the greatest hereditary-safe
co-liveness restriction against that admitted future. -/
noncomputable def prefixThenControllerRepair
    (source : Finset (Finset A)) (durable : Finset A)
    (candidate : Finset (Finset U)) (ell : U → A)
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G)
    (coLive : CoLiveFamily G) : CoLiveFamily G :=
  hereditarySafeCoLiveRestriction
    (safeFuture source durable candidate ell) access families coLive

/-- The second level admits only behavior that survived the first-level
durable-prefix filter. -/
theorem prefixThenControllerRepair_rawPhysical_safe
    (source : Finset (Finset A)) (durable : Finset A)
    (candidate : Finset (Finset U)) (ell : U → A)
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G)
    (coLive : CoLiveFamily G) :
    rawPhysicalCoverProduct access families
        (prefixThenControllerRepair source durable candidate ell
          access families coLive) ⊆
      safeFuture source durable candidate ell := by
  exact hereditarySafeCoLiveRestriction_rawPhysical_safe
    (safeFuture source durable candidate ell) access families coLive

/-- Joint principality of the two repair levels.  If `admitted` is any
prefix-safe pruning of `candidate`, and `delta` is any downward-closed
co-liveness pruning whose physical product stays within `admitted`, then
`delta` is contained in the repair obtained from the two greatest filters. -/
theorem prefixThenControllerRepair_greatest
    (source : Finset (Finset A)) (durable : Finset A)
    (candidate admitted : Finset (Finset U)) (ell : U → A)
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G)
    (coLive delta : CoLiveFamily G)
    (hAdmittedSubset : admitted ⊆ candidate)
    (hPrefixSafe : PrefixConfigMorphism source durable admitted ell)
    (hDeltaDown : CoLiveDownwardClosed delta)
    (hDeltaSubset : delta ⊆ coLive)
    (hDeltaPhysical : rawPhysicalCoverProduct access families delta ⊆ admitted) :
    delta ⊆ prefixThenControllerRepair source durable candidate ell
      access families coLive := by
  apply hereditarySafeCoLiveRestriction_greatest
    (safeFuture source durable candidate ell) access families
    coLive delta hDeltaDown hDeltaSubset
  exact Finset.Subset.trans hDeltaPhysical
    (safeFuture_greatest source durable candidate admitted ell
      hAdmittedSubset hPrefixSafe)

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

/-! ## Observation lower bounds -/

/-- The controller sets of size at most `arity` that can occur inside some
co-live set.  This is the complete low-arity projection of the controller
realization, not merely a graph extracted by one particular analyzer. -/
def coLiveProjection (arity : Nat)
    (coLive : CoLiveFamily G) : CoLiveFamily G :=
  (Finset.univ : Finset G).powerset.filter fun observed =>
    observed.card ≤ arity ∧
      ∃ active ∈ coLive, observed ⊆ active

/-- A checker is exact through an observation when that observation contains
all controller information on which its deployment decision depends. -/
def ExactThroughObservation {O : Type*}
    (observe : CoLiveFamily G → O)
    (check : Finset (Finset U) → Finset (Finset U) →
      ControllerAccess U G → LocalControllerFamilies U G → O → Bool) :
    Prop :=
  ∀ required admitted access families coLive,
    check required admitted access families (observe coLive) = true ↔
      DeploymentReady required admitted access families coLive

/-- Exactness restricted to the well-structured realization class used by the
observation-arity theorems: both controller-local choice families and global
co-liveness are downward closed. -/
def ExactThroughDownwardClosedObservation {O : Type*}
    (observe : CoLiveFamily G → O)
    (check : Finset (Finset U) → Finset (Finset U) →
      ControllerAccess U G → LocalControllerFamilies U G → O → Bool) :
    Prop :=
  ∀ required admitted access families coLive,
    LocalFamiliesDownwardClosed families →
      CoLiveDownwardClosed coLive →
      (check required admitted access families (observe coLive) = true ↔
        DeploymentReady required admitted access families coLive)

/-- An information-theoretic collision principle.  If two controller
realizations have the same observation but different readiness decisions,
no checker using only that observation can be both sound and complete. -/
theorem no_exact_checker_of_observation_collision {O : Type*}
    (observe : CoLiveFamily G → O)
    (check : Finset (Finset U) → Finset (Finset U) →
      ControllerAccess U G → LocalControllerFamilies U G → O → Bool)
    (required admitted : Finset (Finset U))
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G)
    (safeCoLive badCoLive : CoLiveFamily G)
    (hCollision : observe safeCoLive = observe badCoLive)
    (hSafe : DeploymentReady required admitted access families safeCoLive)
    (hUnsafe : ¬DeploymentReady required admitted access families badCoLive) :
    ¬ExactThroughObservation observe check := by
  intro hExact
  have hAcceptSafe :
      check required admitted access families (observe safeCoLive) = true :=
    (hExact required admitted access families safeCoLive).2 hSafe
  have hAcceptUnsafe :
      check required admitted access families (observe badCoLive) = true := by
    rw [← hCollision]
    exact hAcceptSafe
  exact hUnsafe
    ((hExact required admitted access families badCoLive).1 hAcceptUnsafe)

/-- The same collision argument inside the downward-closed realization class.
This form rules out exactness even after excluding malformed local and global
controller manifests. -/
theorem no_exact_downwardClosed_checker_of_observation_collision {O : Type*}
    (observe : CoLiveFamily G → O)
    (check : Finset (Finset U) → Finset (Finset U) →
      ControllerAccess U G → LocalControllerFamilies U G → O → Bool)
    (required admitted : Finset (Finset U))
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G)
    (safeCoLive badCoLive : CoLiveFamily G)
    (hFamiliesDown : LocalFamiliesDownwardClosed families)
    (hSafeDown : CoLiveDownwardClosed safeCoLive)
    (hBadDown : CoLiveDownwardClosed badCoLive)
    (hCollision : observe safeCoLive = observe badCoLive)
    (hSafe : DeploymentReady required admitted access families safeCoLive)
    (hUnsafe : ¬DeploymentReady required admitted access families badCoLive) :
    ¬ExactThroughDownwardClosedObservation observe check := by
  intro hExact
  have hAcceptSafe :
      check required admitted access families (observe safeCoLive) = true :=
    (hExact required admitted access families safeCoLive
      hFamiliesDown hSafeDown).2 hSafe
  have hAcceptUnsafe :
      check required admitted access families (observe badCoLive) = true := by
    rw [← hCollision]
    exact hAcceptSafe
  exact hUnsafe
    ((hExact required admitted access families badCoLive
      hFamiliesDown hBadDown).1 hAcceptUnsafe)

/-! ### Contract-indexed observation sufficiency -/

/-- For a downward-closed co-liveness family, the complete arity projection
contains exactly the genuinely co-live controller sets of that arity. -/
theorem mem_coLiveProjection_iff_of_downwardClosed
    (arity : Nat) (coLive : CoLiveFamily G)
    (hDown : CoLiveDownwardClosed coLive) (active : Finset G) :
    active ∈ coLiveProjection arity coLive ↔
      active.card ≤ arity ∧ active ∈ coLive := by
  constructor
  · intro hObserved
    obtain ⟨hCard, larger, hLarger, hSubset⟩ := by
      simpa [coLiveProjection] using hObserved
    exact ⟨hCard, hDown larger hLarger active hSubset⟩
  · rintro ⟨hCard, hActive⟩
    simp only [coLiveProjection, Finset.mem_filter, Finset.mem_powerset]
    exact ⟨Finset.subset_univ active, hCard, active, hActive,
      Finset.Subset.rfl⟩

/-- Complete bounded projection is itself downward closed, independently of
whether the hidden family is downward closed. -/
theorem coLiveProjection_downwardClosed
    (arity : Nat) (coLive : CoLiveFamily G) :
    CoLiveDownwardClosed (coLiveProjection arity coLive) := by
  intro active hActive smaller hSubset
  rw [coLiveProjection] at hActive ⊢
  simp only [Finset.mem_filter, Finset.mem_powerset] at hActive ⊢
  rcases hActive with
    ⟨_hUniv, hCard, larger, hLarger, hActiveSubset⟩
  exact ⟨Finset.subset_univ smaller,
    (Finset.card_le_card hSubset).trans hCard,
    larger, hLarger, hSubset.trans hActiveSubset⟩

/-- Projecting a complete bounded projection again at the same arity changes
nothing. -/
theorem coLiveProjection_idempotent
    (arity : Nat) (coLive : CoLiveFamily G) :
    coLiveProjection arity (coLiveProjection arity coLive) =
      coLiveProjection arity coLive := by
  ext active
  rw [mem_coLiveProjection_iff_of_downwardClosed
    arity (coLiveProjection arity coLive)
    (coLiveProjection_downwardClosed arity coLive) active]
  constructor
  · exact And.right
  · intro hActive
    have hShape := hActive
    rw [coLiveProjection] at hShape
    have hCard : active.card ≤ arity :=
      (Finset.mem_filter.mp hShape).2.1
    exact ⟨hCard, hActive⟩

/-- Equal complete arity projections of two downward-closed co-liveness
families imply agreement on every controller set within the arity bound. -/
theorem coLive_membership_iff_of_projection_eq
    (arity : Nat) (left right : CoLiveFamily G)
    (hLeftDown : CoLiveDownwardClosed left)
    (hRightDown : CoLiveDownwardClosed right)
    (hProjection : coLiveProjection arity left =
      coLiveProjection arity right)
    {active : Finset G} (hCard : active.card ≤ arity) :
    active ∈ left ↔ active ∈ right := by
  have hObserved :
      active ∈ coLiveProjection arity left ↔
        active ∈ coLiveProjection arity right := by
    rw [hProjection]
  rw [mem_coLiveProjection_iff_of_downwardClosed
      arity left hLeftDown active,
    mem_coLiveProjection_iff_of_downwardClosed
      arity right hRightDown active] at hObserved
  simpa [hCard] using hObserved

/-- Any physical realization of a cell configuration `C` has a subplan using
at most `|C|` active controllers.  Choose one contributing controller per
cell and discard all other active controllers.  Downward-closed co-liveness
is exactly what makes the smaller controller set executable. -/
theorem rawPhysicalCoverProduct_has_card_bounded_plan
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G)
    (coLive : CoLiveFamily G)
    (hCoLiveDown : CoLiveDownwardClosed coLive)
    {C : Finset U}
    (hRaw : C ∈ rawPhysicalCoverProduct access families coLive) :
    ∃ plan : CoverPlan U G,
      plan.Valid access families coLive C ∧
        plan.active.card ≤ C.card := by
  classical
  obtain ⟨plan, hValid⟩ :=
    (mem_rawPhysicalCoverProduct_iff access families coLive C).1 hRaw
  have hCovered : ∀ u : {u // u ∈ C},
      ∃ g : G, g ∈ plan.active ∧ u.1 ∈ plan.piece g := by
    intro u
    have huUnion : u.1 ∈ plan.active.biUnion plan.piece := by
      rw [hValid.2.2.2]
      exact u.2
    exact Finset.mem_biUnion.mp huUnion
  let chooseController : {u // u ∈ C} → G :=
    fun u => Classical.choose (hCovered u)
  have hChooseController : ∀ u : {u // u ∈ C},
      chooseController u ∈ plan.active ∧
        u.1 ∈ plan.piece (chooseController u) := by
    intro u
    exact Classical.choose_spec (hCovered u)
  let selected : Finset G := C.attach.image chooseController
  have hSelectedSubset : selected ⊆ plan.active := by
    intro g hg
    obtain ⟨u, _huAttach, rfl⟩ := Finset.mem_image.mp hg
    exact (hChooseController u).1
  have hSelectedCoLive : selected ∈ coLive :=
    hCoLiveDown plan.active hValid.1 selected hSelectedSubset
  have hSelectedCard : selected.card ≤ C.card := by
    have hImage : (C.attach.image chooseController).card ≤ C.attach.card :=
      Finset.card_image_le
    simpa [selected] using hImage
  let compressed : CoverPlan U G :=
    { active := selected
      piece := plan.piece }
  refine ⟨compressed, ?_, hSelectedCard⟩
  refine ⟨hSelectedCoLive, ?_, ?_, ?_⟩
  · intro g hg
    exact hValid.2.1 g (hSelectedSubset hg)
  · intro g hg
    exact hValid.2.2.1 g (hSelectedSubset hg)
  · ext u
    constructor
    · intro hu
      obtain ⟨g, hgSelected, huPiece⟩ := Finset.mem_biUnion.mp hu
      have huOriginal : u ∈ plan.active.biUnion plan.piece :=
        Finset.mem_biUnion.mpr
          ⟨g, hSelectedSubset hgSelected, huPiece⟩
      rw [hValid.2.2.2] at huOriginal
      exact huOriginal
    · intro huC
      let uC : {u // u ∈ C} := ⟨u, huC⟩
      have hgSelected : chooseController uC ∈ selected := by
        apply Finset.mem_image.mpr
        exact ⟨uC, Finset.mem_attach C uC, rfl⟩
      exact Finset.mem_biUnion.mpr
        ⟨chooseController uC, hgSelected, (hChooseController uC).2⟩

/-- Complete co-liveness observations through arity `k` determine physical
membership for every cell configuration of size at most `k`. -/
theorem rawPhysical_membership_iff_of_projection_eq
    (arity : Nat)
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G)
    (left right : CoLiveFamily G)
    (hLeftDown : CoLiveDownwardClosed left)
    (hRightDown : CoLiveDownwardClosed right)
    (hProjection : coLiveProjection arity left =
      coLiveProjection arity right)
    {C : Finset U} (hCard : C.card ≤ arity) :
    C ∈ rawPhysicalCoverProduct access families left ↔
      C ∈ rawPhysicalCoverProduct access families right := by
  constructor
  · intro hRaw
    obtain ⟨plan, hValid, hPlanCard⟩ :=
      rawPhysicalCoverProduct_has_card_bounded_plan
        access families left hLeftDown hRaw
    rw [mem_rawPhysicalCoverProduct_iff]
    refine ⟨plan, ?_⟩
    refine ⟨?_, hValid.2⟩
    exact (coLive_membership_iff_of_projection_eq
      arity left right hLeftDown hRightDown hProjection
      (hPlanCard.trans hCard)).1 hValid.1
  · intro hRaw
    obtain ⟨plan, hValid, hPlanCard⟩ :=
      rawPhysicalCoverProduct_has_card_bounded_plan
        access families right hRightDown hRaw
    rw [mem_rawPhysicalCoverProduct_iff]
    refine ⟨plan, ?_⟩
    refine ⟨?_, hValid.2⟩
    exact (coLive_membership_iff_of_projection_eq
      arity left right hLeftDown hRightDown hProjection
      (hPlanCard.trans hCard)).2 hValid.1

/-- A contract-relative upper bound on the co-liveness facts needed for an
exact readiness decision.  Required configurations bound missing-behavior
witnesses; minimal nonfaces bound in-support overpermissions; and each cell
outside the admitted support contributes a unary support-escape witness. -/
def ContractObservationBound
    (required admitted : Finset (Finset U)) (arity : Nat) : Prop :=
  (∀ C ∈ required, C.card ≤ arity) ∧
    (∀ K : Finset U, MinimalNonface admitted K → K.card ≤ arity) ∧
    (∀ u : U, u ∉ support admitted → 1 ≤ arity)

/-- The finite family of all minimal nonfaces of an admitted contract. -/
noncomputable def minimalNonfacesOf
    (admitted : Finset (Finset U)) : Finset (Finset U) := by
  classical
  exact (support admitted).powerset.filter fun K =>
    MinimalNonface admitted K

/-- The least syntactic maximum exposed by the three classes of bounded
witnesses.  The support-escape component is zero for full support and one
otherwise. -/
noncomputable def contractObservationArity
    (required admitted : Finset (Finset U)) : Nat := by
  classical
  exact max (required.sup fun C => C.card)
    (max ((minimalNonfacesOf admitted).sup fun K => K.card)
      (if support admitted = (Finset.univ : Finset U) then 0 else 1))

theorem contractObservationArity_is_bound
    (required admitted : Finset (Finset U)) :
    ContractObservationBound required admitted
      (contractObservationArity required admitted) := by
  classical
  refine ⟨?_, ?_, ?_⟩
  · intro C hC
    have hRequired := Finset.le_sup
      (f := fun C : Finset U => C.card) hC
    simpa [contractObservationArity] using hRequired.trans
      (le_max_left
        (required.sup fun C : Finset U => C.card)
        (max ((minimalNonfacesOf admitted).sup fun K : Finset U => K.card)
          (if support admitted = (Finset.univ : Finset U) then 0 else 1)))
  · intro K hMinimal
    have hKMem : K ∈ minimalNonfacesOf admitted := by
      simp [minimalNonfacesOf, hMinimal.1, hMinimal]
    have hMinimalSup := Finset.le_sup
      (f := fun K : Finset U => K.card) hKMem
    have hInner :
        (minimalNonfacesOf admitted).sup (fun K : Finset U => K.card) ≤
          max ((minimalNonfacesOf admitted).sup fun K : Finset U => K.card)
            (if support admitted = (Finset.univ : Finset U) then 0 else 1) :=
      le_max_left _ _
    have hOuter :
        max ((minimalNonfacesOf admitted).sup fun K : Finset U => K.card)
            (if support admitted = (Finset.univ : Finset U) then 0 else 1) ≤
          max (required.sup fun C : Finset U => C.card)
            (max ((minimalNonfacesOf admitted).sup fun K : Finset U => K.card)
              (if support admitted = (Finset.univ : Finset U) then 0 else 1)) :=
      le_max_right _ _
    simpa [contractObservationArity] using
      hMinimalSup.trans (hInner.trans hOuter)
  · intro u huOutside
    have hNotFull : support admitted ≠ (Finset.univ : Finset U) := by
      intro hFull
      apply huOutside
      rw [hFull]
      exact Finset.mem_univ u
    have hUnary :
        1 ≤ max ((minimalNonfacesOf admitted).sup fun K => K.card)
          (if support admitted = (Finset.univ : Finset U) then 0 else 1) := by
      simp [hNotFull]
    have hOuter :
        max ((minimalNonfacesOf admitted).sup fun K : Finset U => K.card)
            (if support admitted = (Finset.univ : Finset U) then 0 else 1) ≤
          max (required.sup fun C : Finset U => C.card)
            (max ((minimalNonfacesOf admitted).sup fun K : Finset U => K.card)
              (if support admitted = (Finset.univ : Finset U) then 0 else 1)) :=
      le_max_right _ _
    simpa [contractObservationArity] using hUnary.trans hOuter

/-- Under downward-closed local families, equality of contract-bounded
co-liveness observations preserves physical safety. -/
theorem rawPhysical_subset_admitted_of_projection_eq
    (arity : Nat) (admitted : Finset (Finset U))
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G)
    (left right : CoLiveFamily G)
    (hFamiliesDown : LocalFamiliesDownwardClosed families)
    (hLeftDown : CoLiveDownwardClosed left)
    (hRightDown : CoLiveDownwardClosed right)
    (hProjection : coLiveProjection arity left =
      coLiveProjection arity right)
    (hMinimalBound : ∀ K : Finset U,
      MinimalNonface admitted K → K.card ≤ arity)
    (hOutsideBound : ∀ u : U, u ∉ support admitted → 1 ≤ arity)
    (hSafe : rawPhysicalCoverProduct access families left ⊆ admitted) :
    rawPhysicalCoverProduct access families right ⊆ admitted := by
  intro C hRaw
  by_contra hForbidden
  by_cases hSupport : C ⊆ support admitted
  · obtain ⟨K, hKSubset, hMinimal⟩ :=
      exists_minimalNonface_subset admitted hSupport hForbidden
    have hKRawRight := rawPhysicalCoverProduct_downwardClosed
      access families right hFamiliesDown hRaw hKSubset
    have hKRawLeft :=
      (rawPhysical_membership_iff_of_projection_eq
        arity access families left right hLeftDown hRightDown hProjection
        (hMinimalBound K hMinimal)).2 hKRawRight
    exact hMinimal.2.1 (hSafe hKRawLeft)
  · have hOutside : ∃ u : U, u ∈ C ∧ u ∉ support admitted := by
      simpa [Finset.subset_iff] using hSupport
    obtain ⟨u, huC, huOutside⟩ := hOutside
    have hSingletonSubset : ({u} : Finset U) ⊆ C := by
      simpa using huC
    have hSingletonRawRight := rawPhysicalCoverProduct_downwardClosed
      access families right hFamiliesDown hRaw hSingletonSubset
    have hSingletonRawLeft :=
      (rawPhysical_membership_iff_of_projection_eq
        arity access families left right hLeftDown hRightDown hProjection
        (by simpa using hOutsideBound u huOutside)).2 hSingletonRawRight
    have hSingletonAdmitted := hSafe hSingletonRawLeft
    exact huOutside (source_mem_support hSingletonAdmitted (by simp))

/-- Physical safety is therefore invariant under equal observations at every
arity satisfying the admitted contract's obstruction bounds. -/
theorem rawPhysical_subset_admitted_iff_of_projection_eq
    (arity : Nat) (admitted : Finset (Finset U))
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G)
    (left right : CoLiveFamily G)
    (hFamiliesDown : LocalFamiliesDownwardClosed families)
    (hLeftDown : CoLiveDownwardClosed left)
    (hRightDown : CoLiveDownwardClosed right)
    (hProjection : coLiveProjection arity left =
      coLiveProjection arity right)
    (hMinimalBound : ∀ K : Finset U,
      MinimalNonface admitted K → K.card ≤ arity)
    (hOutsideBound : ∀ u : U, u ∉ support admitted → 1 ≤ arity) :
    rawPhysicalCoverProduct access families left ⊆ admitted ↔
      rawPhysicalCoverProduct access families right ⊆ admitted := by
  constructor
  · exact rawPhysical_subset_admitted_of_projection_eq
      arity admitted access families left right hFamiliesDown
      hLeftDown hRightDown hProjection hMinimalBound hOutsideBound
  · exact rawPhysical_subset_admitted_of_projection_eq
      arity admitted access families right left hFamiliesDown
      hRightDown hLeftDown hProjection.symm hMinimalBound hOutsideBound

/-- Main observation-arity upper bound: for fixed access and local families,
the required-family maximum, admitted minimal-nonface maximum, and unary
outside-support witnesses contain all co-liveness information needed to
decide deployment readiness. -/
theorem deploymentReady_iff_of_contract_observation
    (arity : Nat) (required admitted : Finset (Finset U))
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G)
    (left right : CoLiveFamily G)
    (hFamiliesDown : LocalFamiliesDownwardClosed families)
    (hLeftDown : CoLiveDownwardClosed left)
    (hRightDown : CoLiveDownwardClosed right)
    (hProjection : coLiveProjection arity left =
      coLiveProjection arity right)
    (hBound : ContractObservationBound required admitted arity) :
    DeploymentReady required admitted access families left ↔
      DeploymentReady required admitted access families right := by
  have hRequired :
      required ⊆ rawPhysicalCoverProduct access families left ↔
        required ⊆ rawPhysicalCoverProduct access families right := by
    constructor <;> intro hSubset C hC
    · exact (rawPhysical_membership_iff_of_projection_eq
        arity access families left right hLeftDown hRightDown hProjection
        (hBound.1 C hC)).1 (hSubset hC)
    · exact (rawPhysical_membership_iff_of_projection_eq
        arity access families left right hLeftDown hRightDown hProjection
        (hBound.1 C hC)).2 (hSubset hC)
  have hSafe := rawPhysical_subset_admitted_iff_of_projection_eq
    arity admitted access families left right hFamiliesDown
    hLeftDown hRightDown hProjection hBound.2.1 hBound.2.2
  unfold DeploymentReady
  exact and_congr hRequired hSafe

/-- Canonical corollary using the maximum computed directly from the required
and admitted contract families. -/
theorem deploymentReady_iff_of_contractObservationArity_projection_eq
    (required admitted : Finset (Finset U))
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G)
    (left right : CoLiveFamily G)
    (hFamiliesDown : LocalFamiliesDownwardClosed families)
    (hLeftDown : CoLiveDownwardClosed left)
    (hRightDown : CoLiveDownwardClosed right)
    (hProjection :
      coLiveProjection (contractObservationArity required admitted) left =
        coLiveProjection (contractObservationArity required admitted) right) :
    DeploymentReady required admitted access families left ↔
      DeploymentReady required admitted access families right :=
  deploymentReady_iff_of_contract_observation
    (contractObservationArity required admitted) required admitted
    access families left right hFamiliesDown hLeftDown hRightDown hProjection
    (contractObservationArity_is_bound required admitted)

/-- Tool-facing corollary: evaluating the complete contract-indexed projection
itself gives exactly the hidden downward-closed family's readiness bit. -/
theorem deploymentReady_iff_contractProjection
    (required admitted : Finset (Finset U))
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G)
    (coLive : CoLiveFamily G)
    (hFamiliesDown : LocalFamiliesDownwardClosed families)
    (hCoLiveDown : CoLiveDownwardClosed coLive) :
    DeploymentReady required admitted access families
        (coLiveProjection (contractObservationArity required admitted) coLive) ↔
      DeploymentReady required admitted access families coLive :=
  deploymentReady_iff_of_contractObservationArity_projection_eq
    required admitted access families
    (coLiveProjection (contractObservationArity required admitted) coLive)
    coLive hFamiliesDown
    (coLiveProjection_downwardClosed
      (contractObservationArity required admitted) coLive)
    hCoLiveDown
    (coLiveProjection_idempotent
      (contractObservationArity required admitted) coLive)

/-- Adapter-facing form: exactness of submitted `P` is an explicit premise. -/
theorem deploymentReady_iff_of_attested_exact_projection
    (required admitted : Finset (Finset U))
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G)
    (submitted hidden : CoLiveFamily G)
    (hFamiliesDown : LocalFamiliesDownwardClosed families)
    (hHiddenDown : CoLiveDownwardClosed hidden)
    (hExact : submitted =
      coLiveProjection (contractObservationArity required admitted) hidden) :
    DeploymentReady required admitted access families submitted ↔
      DeploymentReady required admitted access families hidden := by
  subst submitted
  exact deploymentReady_iff_contractProjection
    required admitted access families hidden hFamiliesDown hHiddenDown

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

/-- The canonical partition adapter may run any subset of block controllers;
an omitted controller contributes the empty local choice. -/
def partitionCoLive : CoLiveFamily G :=
  (Finset.univ : Finset G).powerset

theorem partitionCoLive_downwardClosed :
    CoLiveDownwardClosed (partitionCoLive (G := G)) := by
  simp [CoLiveDownwardClosed, partitionCoLive]

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
    by_cases hgActive : g ∈ plan.active
    · have hPartSubset : blockPart blockOf g C ⊆ plan.piece g := by
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
    · have hPartEmpty : blockPart blockOf g C = ∅ := by
        ext u
        constructor
        · intro huPart
          exfalso
          have huC := (Finset.mem_filter.mp huPart).1
          have hBlock := (Finset.mem_filter.mp huPart).2
          have huUnion : u ∈ plan.active.biUnion plan.piece := by
            rw [hUnion]
            exact huC
          obtain ⟨g', hg', huPiece⟩ := Finset.mem_biUnion.mp huUnion
          have hAssigned : blockOf u = g' := hAccess g' hg' u huPiece
          have hEq : g' = g := hAssigned.symm.trans hBlock
          exact hgActive (hEq ▸ hg')
        · intro huEmpty
          simp at huEmpty
      simpa [hPartEmpty] using wf.empty_mem
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

/-! ## Minimal nonfaces and correlation-cut witnesses -/

/-- A physically realized minimal nonface whose active local pieces are all
admitted.  The local-admittedness conjunct prevents a single locally
overpermissive controller from being mislabeled as a correlation cut. -/
def CorrelationCutWitness (admitted : Finset (Finset U))
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
by restricting the same cover plan, so it is an actual physical correlation-
cut witness rather than merely a forbidden subset. -/
theorem physical_overpermission_has_correlationCutWitness
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
      CorrelationCutWitness admitted access families coLive K := by
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

theorem correlationCutWitness_overpermission
    (admitted : Finset (Finset U))
    (access : ControllerAccess U G)
    (families : LocalControllerFamilies U G)
    (coLive : CoLiveFamily G)
    {K : Finset U}
    (hCut : CorrelationCutWitness admitted access families coLive K) :
    K ∈ physicalCoverProduct admitted access families coLive ∧ K ∉ admitted := by
  obtain ⟨hMinimal, plan, hValid, _hLocal⟩ := hCut
  constructor
  · rw [mem_physicalCoverProduct_iff]
    exact ⟨hMinimal.1, plan, hValid⟩
  · exact hMinimal.2.1

/-- For a genuine correlation cut, every active controller contributes only a
proper subset of the forbidden minimal nonface. -/
theorem correlationCut_each_active_piece_proper
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

/-- A locally sound correlation cut of a well-formed family necessarily uses at least
two distinct controllers with nonempty contributions. -/
theorem correlationCut_uses_distinct_contributing_controllers
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
  have hProper := correlationCut_each_active_piece_proper admitted
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

/-! ## A relational U(2,3) correlation-cut fixture -/

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

theorem triple_correlationCutWitness :
    CorrelationCutWitness rankTwoFamily sharedAccess splitLocal splitCoLive triple := by
  refine ⟨triple_minimalNonface, splitCoverPlan, splitCoverPlan_valid, ?_⟩
  intro g hg
  exact (splitLocal_sound g (splitCoverPlan.piece g)
    (splitCoverPlan_valid.2.1 g hg)).1

theorem split_controllers_admit_forbidden_triple :
    triple ∈ physicalCoverProduct
        rankTwoFamily sharedAccess splitLocal splitCoLive ∧
      triple ∉ rankTwoFamily :=
  correlationCutWitness_overpermission
    rankTwoFamily sharedAccess splitLocal splitCoLive triple_correlationCutWitness

theorem split_correlationCut_uses_two_controllers :
    ∃ g1 g2 : Bool,
      g1 ∈ splitCoverPlan.active ∧ g2 ∈ splitCoverPlan.active ∧ g1 ≠ g2 ∧
        (splitCoverPlan.piece g1).Nonempty ∧
        (splitCoverPlan.piece g2).Nonempty :=
  correlationCut_uses_distinct_contributing_controllers
    rankTwoFamily rankTwoFamily_wellFormed splitLocal_sound
    triple_minimalNonface splitCoverPlan_valid

theorem each_cell_has_shared_access (u : Fin 3) :
    sharedAccess u false ∧ sharedAccess u true := by
  simp [sharedAccess]

/-! ### Pairwise observation is insufficient -/

/-- Three controller identities and three redemption cells are kept distinct;
every controller can name every cell, while its local family may select only
its own singleton. -/
def completeAccess3 (_u : Fin 3) (_g : Fin 3) : Prop := True

def singletonLocal3 (g : Fin 3) : Finset (Finset (Fin 3)) :=
  ({g} : Finset (Fin 3)).powerset

/-- The safe realization may co-schedule any controller set of size at most
two. -/
def pairwiseCoLive3 : CoLiveFamily (Fin 3) :=
  (Finset.univ : Finset (Fin 3)).powerset.filter fun active =>
    active.card ≤ 2

/-- The unsafe realization allows every controller subset, including all
three controllers together. -/
def tripleCoLive3 : CoLiveFamily (Fin 3) :=
  (Finset.univ : Finset (Fin 3)).powerset

theorem pairwiseCoLive3_downwardClosed :
    CoLiveDownwardClosed pairwiseCoLive3 := by
  intro active hActive smaller hSubset
  have hActiveCard : active.card ≤ 2 := by
    simpa [pairwiseCoLive3] using hActive
  have hSmallerCard : smaller.card ≤ 2 :=
    (Finset.card_le_card hSubset).trans hActiveCard
  simpa [pairwiseCoLive3] using hSmallerCard

theorem tripleCoLive3_downwardClosed :
    CoLiveDownwardClosed tripleCoLive3 := by
  intro active hActive smaller hSubset
  simp [tripleCoLive3]

theorem singletonLocal3_sound :
    LocalFamiliesSound rankTwoFamily completeAccess3 singletonLocal3 := by
  intro g C hC
  constructor
  · simp only [rankTwoFamily, Finset.mem_filter, Finset.mem_univ, true_and]
    have hCard := Finset.card_le_card (Finset.mem_powerset.mp hC)
    have hSingleton : ({g} : Finset (Fin 3)).card = 1 := by simp
    rw [hSingleton] at hCard
    omega
  · simp [PieceAccessible, completeAccess3]

/-- Every physical configuration in the pairwise realization is admitted:
local singleton choices make the chosen cells a subset of the active
controllers, whose cardinality is at most two. -/
theorem pairwise_raw_subset_rankTwo :
    rawPhysicalCoverProduct completeAccess3 singletonLocal3 pairwiseCoLive3
      ⊆ rankTwoFamily := by
  intro C hC
  obtain ⟨plan, hValid⟩ :=
    (mem_rawPhysicalCoverProduct_iff
      completeAccess3 singletonLocal3 pairwiseCoLive3 C).1 hC
  have hActiveCard : plan.active.card ≤ 2 := by
    simpa [pairwiseCoLive3] using hValid.1
  have hSubset : C ⊆ plan.active := by
    intro u huC
    have huUnion : u ∈ plan.active.biUnion plan.piece := by
      rw [hValid.2.2.2]
      exact huC
    obtain ⟨g, hgActive, huPiece⟩ := Finset.mem_biUnion.mp huUnion
    have hPieceSubset : plan.piece g ⊆ ({g} : Finset (Fin 3)) :=
      Finset.mem_powerset.mp (hValid.2.1 g hgActive)
    have hug : u = g := by
      simpa using hPieceSubset huPiece
    simpa [hug] using hgActive
  simp only [rankTwoFamily, Finset.mem_filter, Finset.mem_univ, true_and]
  exact (Finset.card_le_card hSubset).trans hActiveCard

/-- Every admitted rank-two configuration is also realizable by activating
exactly its singleton controllers. -/
theorem rankTwo_subset_pairwise_raw :
    rankTwoFamily ⊆
      rawPhysicalCoverProduct completeAccess3 singletonLocal3 pairwiseCoLive3 := by
  intro C hC
  rw [mem_rawPhysicalCoverProduct_iff]
  let plan : CoverPlan (Fin 3) (Fin 3) :=
    { active := C
      piece := fun g => {g} }
  refine ⟨plan, ?_⟩
  refine ⟨?_, ?_, ?_, ?_⟩
  · simp only [rankTwoFamily, Finset.mem_filter, Finset.mem_univ, true_and] at hC
    simpa [plan, pairwiseCoLive3] using hC
  · intro g hg
    simp [plan, singletonLocal3]
  · intro g hg
    simp [plan, PieceAccessible, completeAccess3]
  · ext u
    simp [plan]

theorem pairwise_raw_eq_rankTwo :
    rawPhysicalCoverProduct completeAccess3 singletonLocal3 pairwiseCoLive3 =
      rankTwoFamily :=
  Finset.Subset.antisymm pairwise_raw_subset_rankTwo
    rankTwo_subset_pairwise_raw

theorem pairwise_realization_ready :
    DeploymentReady rankTwoFamily rankTwoFamily
      completeAccess3 singletonLocal3 pairwiseCoLive3 :=
  ⟨rankTwo_subset_pairwise_raw, pairwise_raw_subset_rankTwo⟩

def tripleSingletonCoverPlan : CoverPlan (Fin 3) (Fin 3) where
  active := Finset.univ
  piece := fun g => {g}

theorem tripleSingletonCoverPlan_valid :
    tripleSingletonCoverPlan.Valid
      completeAccess3 singletonLocal3 tripleCoLive3 triple := by
  refine ⟨by simp [tripleSingletonCoverPlan, tripleCoLive3], ?_, ?_, ?_⟩
  · intro g hg
    simp [tripleSingletonCoverPlan, singletonLocal3]
  · intro g hg
    simp [tripleSingletonCoverPlan, PieceAccessible, completeAccess3]
  · ext u
    constructor
    · intro hu
      exact Finset.mem_univ u
    · intro hu
      exact Finset.mem_biUnion.mpr
        ⟨u, Finset.mem_univ u, by simp [tripleSingletonCoverPlan]⟩

theorem triple_realization_correlationCutWitness :
    CorrelationCutWitness rankTwoFamily completeAccess3 singletonLocal3
      tripleCoLive3 triple := by
  refine ⟨triple_minimalNonface, tripleSingletonCoverPlan,
    tripleSingletonCoverPlan_valid, ?_⟩
  intro g hg
  exact (singletonLocal3_sound g (tripleSingletonCoverPlan.piece g)
    (tripleSingletonCoverPlan_valid.2.1 g hg)).1

theorem triple_realization_admits_forbidden_triple :
    triple ∈ rawPhysicalCoverProduct
        completeAccess3 singletonLocal3 tripleCoLive3 ∧
      triple ∉ rankTwoFamily := by
  constructor
  · rw [mem_rawPhysicalCoverProduct_iff]
    exact ⟨tripleSingletonCoverPlan, tripleSingletonCoverPlan_valid⟩
  · exact triple_minimalNonface.2.1

theorem triple_realization_not_ready :
    ¬DeploymentReady rankTwoFamily rankTwoFamily
      completeAccess3 singletonLocal3 tripleCoLive3 := by
  intro hReady
  exact triple_realization_admits_forbidden_triple.2
    (hReady.2 triple_realization_admits_forbidden_triple.1)

/-- The two realizations have exactly the same complete pairwise projection.
Thus the collision is not an artifact of a lossy heuristic graph. -/
theorem pairwise_projection_collision :
    coLiveProjection 2 pairwiseCoLive3 =
      coLiveProjection 2 tripleCoLive3 := by
  decide

/-- No checker that receives the required/admitted families, the complete
access relation, every controller-local family, and the complete pairwise
co-liveness projection can exactly decide deployment readiness.  The missing
ternary fact changes the answer. -/
theorem no_pairwise_observation_checker_exact
    (check : Finset (Finset (Fin 3)) → Finset (Finset (Fin 3)) →
      ControllerAccess (Fin 3) (Fin 3) →
      LocalControllerFamilies (Fin 3) (Fin 3) →
      CoLiveFamily (Fin 3) → Bool) :
    ¬ExactThroughObservation (coLiveProjection 2) check :=
  no_exact_checker_of_observation_collision
    (coLiveProjection 2) check rankTwoFamily rankTwoFamily
    completeAccess3 singletonLocal3 pairwiseCoLive3 tripleCoLive3
    pairwise_projection_collision pairwise_realization_ready
    triple_realization_not_ready

/-! ### Arbitrary observation arity is sometimes necessary -/

namespace ArbitraryArity

/-- `U(k,k+1)`: every cell configuration of size at most `k` is admitted over
`k+1` cells. -/
def rankFamily (k : Nat) : Finset (Finset (Fin (k + 1))) :=
  (Finset.univ : Finset (Fin (k + 1))).powerset.filter fun C =>
    C.card ≤ k

def completeAccess (k : Nat)
    (_u : Fin (k + 1)) (_g : Fin (k + 1)) : Prop := True

/-- Controller `g` may contribute either nothing or its matching singleton. -/
def singletonLocal (k : Nat) (g : Fin (k + 1)) :
    Finset (Finset (Fin (k + 1))) :=
  ({g} : Finset (Fin (k + 1))).powerset

/-- The safe realization co-schedules at most `k` controllers. -/
def boundedCoLive (k : Nat) : CoLiveFamily (Fin (k + 1)) :=
  (Finset.univ : Finset (Fin (k + 1))).powerset.filter fun active =>
    active.card ≤ k

/-- The unsafe realization may co-schedule all `k+1` controllers. -/
def fullCoLive (k : Nat) : CoLiveFamily (Fin (k + 1)) :=
  (Finset.univ : Finset (Fin (k + 1))).powerset

theorem singletonLocal_downwardClosed (k : Nat) :
    LocalFamiliesDownwardClosed (singletonLocal k) := by
  intro g C K hC hSubset
  exact Finset.mem_powerset.mpr
    (hSubset.trans (Finset.mem_powerset.mp hC))

theorem singletonLocal_sound (k : Nat) (hk : 1 ≤ k) :
    LocalFamiliesSound (rankFamily k) (completeAccess k)
      (singletonLocal k) := by
  intro g C hC
  constructor
  · have hCard : C.card ≤ 1 := by
      have hSubset := Finset.mem_powerset.mp hC
      simpa using Finset.card_le_card hSubset
    simp only [rankFamily, Finset.mem_filter, Finset.mem_powerset]
    exact ⟨Finset.subset_univ C, hCard.trans hk⟩
  · simp [PieceAccessible, completeAccess]

theorem boundedCoLive_downwardClosed (k : Nat) :
    CoLiveDownwardClosed (boundedCoLive k) := by
  intro active hActive smaller hSubset
  have hActiveCard : active.card ≤ k := by
    simpa [boundedCoLive] using hActive
  have hSmallerCard : smaller.card ≤ k :=
    (Finset.card_le_card hSubset).trans hActiveCard
  simpa [boundedCoLive] using hSmallerCard

theorem fullCoLive_downwardClosed (k : Nat) :
    CoLiveDownwardClosed (fullCoLive k) := by
  intro active hActive smaller hSubset
  simp [fullCoLive]

/-- Singleton local choices make every realized cell set a subset of the
active-controller set.  Hence the bounded realization adds no behavior beyond
`U(k,k+1)`. -/
theorem bounded_raw_subset_rankFamily (k : Nat) :
    rawPhysicalCoverProduct (completeAccess k) (singletonLocal k)
        (boundedCoLive k) ⊆
      rankFamily k := by
  intro C hC
  obtain ⟨plan, hValid⟩ :=
    (mem_rawPhysicalCoverProduct_iff
      (completeAccess k) (singletonLocal k) (boundedCoLive k) C).1 hC
  have hActiveCard : plan.active.card ≤ k := by
    simpa [boundedCoLive] using hValid.1
  have hSubset : C ⊆ plan.active := by
    intro u huC
    have huUnion : u ∈ plan.active.biUnion plan.piece := by
      rw [hValid.2.2.2]
      exact huC
    obtain ⟨g, hgActive, huPiece⟩ := Finset.mem_biUnion.mp huUnion
    have hPieceSubset : plan.piece g ⊆ ({g} : Finset (Fin (k + 1))) :=
      Finset.mem_powerset.mp (hValid.2.1 g hgActive)
    have hug : u = g := by
      simpa using hPieceSubset huPiece
    simpa [hug] using hgActive
  simp only [rankFamily, Finset.mem_filter, Finset.mem_powerset]
  exact ⟨Finset.subset_univ C,
    (Finset.card_le_card hSubset).trans hActiveCard⟩

/-- Every admitted configuration is realized by activating exactly its
matching singleton controllers. -/
theorem rankFamily_subset_bounded_raw (k : Nat) :
    rankFamily k ⊆
      rawPhysicalCoverProduct (completeAccess k) (singletonLocal k)
        (boundedCoLive k) := by
  intro C hC
  rw [mem_rawPhysicalCoverProduct_iff]
  let plan : CoverPlan (Fin (k + 1)) (Fin (k + 1)) :=
    { active := C
      piece := fun g => {g} }
  refine ⟨plan, ?_⟩
  refine ⟨?_, ?_, ?_, ?_⟩
  · have hCard : C.card ≤ k := by
      simpa [rankFamily] using hC
    simpa [plan, boundedCoLive] using hCard
  · intro g hg
    simp [plan, singletonLocal]
  · intro g hg
    simp [plan, PieceAccessible, completeAccess]
  · ext u
    simp [plan]

theorem bounded_raw_eq_rankFamily (k : Nat) :
    rawPhysicalCoverProduct (completeAccess k) (singletonLocal k)
        (boundedCoLive k) =
      rankFamily k :=
  Finset.Subset.antisymm (bounded_raw_subset_rankFamily k)
    (rankFamily_subset_bounded_raw k)

theorem bounded_realization_ready (k : Nat) :
    DeploymentReady (rankFamily k) (rankFamily k)
      (completeAccess k) (singletonLocal k) (boundedCoLive k) :=
  ⟨rankFamily_subset_bounded_raw k, bounded_raw_subset_rankFamily k⟩

def fullCoverPlan (k : Nat) :
    CoverPlan (Fin (k + 1)) (Fin (k + 1)) where
  active := Finset.univ
  piece := fun g => {g}

theorem fullCoverPlan_valid (k : Nat) :
    (fullCoverPlan k).Valid (completeAccess k) (singletonLocal k)
      (fullCoLive k) (Finset.univ : Finset (Fin (k + 1))) := by
  refine ⟨by simp [fullCoverPlan, fullCoLive], ?_, ?_, ?_⟩
  · intro g hg
    simp [fullCoverPlan, singletonLocal]
  · intro g hg
    simp [fullCoverPlan, PieceAccessible, completeAccess]
  · ext u
    simp [fullCoverPlan]

theorem full_configuration_forbidden (k : Nat) :
    (Finset.univ : Finset (Fin (k + 1))) ∉ rankFamily k := by
  simp [rankFamily]

theorem support_rankFamily_eq_univ (k : Nat) (hk : 1 ≤ k) :
    support (rankFamily k) =
      (Finset.univ : Finset (Fin (k + 1))) := by
  apply Finset.eq_univ_of_forall
  intro u
  apply Finset.mem_biUnion.mpr
  refine ⟨({u} : Finset (Fin (k + 1))), ?_, by simp⟩
  simp [rankFamily, hk]

/-- For positive `k`, the new `(k+1)`-cell configuration is precisely a
minimal nonface, rather than merely some forbidden behavior. -/
theorem full_configuration_minimalNonface
    (k : Nat) (hk : 1 ≤ k) :
    MinimalNonface (rankFamily k)
      (Finset.univ : Finset (Fin (k + 1))) := by
  refine ⟨?_, full_configuration_forbidden k, ?_⟩
  · rw [support_rankFamily_eq_univ k hk]
  · intro L hProper
    have hCardLt := Finset.card_lt_card hProper
    have hCard : L.card ≤ k := by
      simpa using hCardLt
    simp [rankFamily, hCard]

theorem full_configuration_correlationCutWitness
    (k : Nat) (hk : 1 ≤ k) :
    CorrelationCutWitness (rankFamily k) (completeAccess k)
      (singletonLocal k) (fullCoLive k)
      (Finset.univ : Finset (Fin (k + 1))) := by
  refine ⟨full_configuration_minimalNonface k hk,
    fullCoverPlan k, fullCoverPlan_valid k, ?_⟩
  intro g hg
  exact (singletonLocal_sound k hk g ((fullCoverPlan k).piece g)
    ((fullCoverPlan_valid k).2.1 g hg)).1

/-- The contract maximum from the sufficiency theorem is exactly `k+1` on
the positive-rank `U(k,k+1)` family used by the lower bound. -/
theorem contractObservationArity_rankFamily
    (k : Nat) (hk : 1 ≤ k) :
    contractObservationArity (rankFamily k) (rankFamily k) = k + 1 := by
  apply Nat.le_antisymm
  · unfold contractObservationArity
    apply max_le
    · apply Finset.sup_le
      intro C hC
      exact (Finset.card_le_card (Finset.subset_univ C)).trans_eq (by simp)
    · apply max_le
      · apply Finset.sup_le
        intro K hK
        have hSubset : K ⊆ (Finset.univ : Finset (Fin (k + 1))) :=
          Finset.subset_univ K
        exact (Finset.card_le_card hSubset).trans_eq (by simp)
      · split <;> simp
  · have hBound := contractObservationArity_is_bound
      (rankFamily k) (rankFamily k)
    have hMinimalBound := hBound.2.1
      (Finset.univ : Finset (Fin (k + 1)))
      (full_configuration_minimalNonface k hk)
    simpa using hMinimalBound

theorem full_realization_not_ready (k : Nat) :
    ¬DeploymentReady (rankFamily k) (rankFamily k)
      (completeAccess k) (singletonLocal k) (fullCoLive k) := by
  intro hReady
  apply full_configuration_forbidden k
  apply hReady.2
  rw [mem_rawPhysicalCoverProduct_iff]
  exact ⟨fullCoverPlan k, fullCoverPlan_valid k⟩

/-- The safe and unsafe realizations agree on the complete observation of
every controller set through arity `k`. -/
theorem projection_collision (k : Nat) :
    coLiveProjection k (boundedCoLive k) =
      coLiveProjection k (fullCoLive k) := by
  ext active
  rw [mem_coLiveProjection_iff_of_downwardClosed
      k (boundedCoLive k) (boundedCoLive_downwardClosed k) active,
    mem_coLiveProjection_iff_of_downwardClosed
      k (fullCoLive k) (fullCoLive_downwardClosed k) active]
  simp [boundedCoLive, fullCoLive]

/-- For every `k`, no checker using only co-liveness observations of arity at
most `k` can be exact on all downward-closed realizations: `U(k,k+1)` gives a
safe realization and an indistinguishable unsafe one whose sole new maximal
configuration has size `k+1`. -/
theorem no_lower_arity_observation_checker_exact
    (k : Nat)
    (check : Finset (Finset (Fin (k + 1))) →
      Finset (Finset (Fin (k + 1))) →
      ControllerAccess (Fin (k + 1)) (Fin (k + 1)) →
      LocalControllerFamilies (Fin (k + 1)) (Fin (k + 1)) →
      CoLiveFamily (Fin (k + 1)) → Bool) :
    ¬ExactThroughObservation (coLiveProjection k) check :=
  no_exact_checker_of_observation_collision
    (coLiveProjection k) check (rankFamily k) (rankFamily k)
    (completeAccess k) (singletonLocal k) (boundedCoLive k) (fullCoLive k)
    (projection_collision k) (bounded_realization_ready k)
    (full_realization_not_ready k)

/-- The arbitrary-`k` lower bound still holds when exactness is required only
for downward-closed local families and downward-closed co-liveness families. -/
theorem no_lower_arity_downwardClosed_observation_checker_exact
    (k : Nat)
    (check : Finset (Finset (Fin (k + 1))) →
      Finset (Finset (Fin (k + 1))) →
      ControllerAccess (Fin (k + 1)) (Fin (k + 1)) →
      LocalControllerFamilies (Fin (k + 1)) (Fin (k + 1)) →
      CoLiveFamily (Fin (k + 1)) → Bool) :
    ¬ExactThroughDownwardClosedObservation (coLiveProjection k) check :=
  no_exact_downwardClosed_checker_of_observation_collision
    (coLiveProjection k) check (rankFamily k) (rankFamily k)
    (completeAccess k) (singletonLocal k) (boundedCoLive k) (fullCoLive k)
    (singletonLocal_downwardClosed k)
    (boundedCoLive_downwardClosed k) (fullCoLive_downwardClosed k)
    (projection_collision k) (bounded_realization_ready k)
    (full_realization_not_ready k)

end ArbitraryArity

end Fixtures

end AuthorityContinuity.ControllerCoverAdmission
