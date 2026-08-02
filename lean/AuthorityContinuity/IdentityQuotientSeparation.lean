import AuthorityContinuity.ControllerCoverAdmission

/-!
# Independent identity quotients

One raw manifest contains two alternative handles and two gate uses.  The
handle future is exclusive, each gate use controls its matching handle, and
the two raw gate uses may be live together.  We normalize that *same* manifest
through two maps:

* `cellOf` folds copied handles to semantic redemption cells; and
* `controllerOf` folds gate uses to authoritative controller instances.

The four combinations form a 2-by-2 separation matrix.  Every combination is
deployment-ready except treating both handles and both gate uses as distinct.
Consequently, even after retaining the complete raw manifest and the other
quotient, erasing either quotient creates two indistinguishable views with
opposite readiness decisions.
-/

namespace AuthorityContinuity.IdentityQuotientSeparation

open ConfigurationCellQuotient
open ControllerCoverAdmission

namespace Fixtures

open ConfigurationCellQuotient.Fixtures

/-! ## One raw handle/gate manifest -/

/-- Alternative raw handles; the pair is not a legal semantic future. -/
def rawHandleFuture : Finset (Finset Bool) := exclusiveTarget

/-- Each raw gate use can choose no handle or its matching handle. -/
def rawGateLocal (use : Bool) : Finset (Finset Bool) :=
  ({use} : Finset Bool).powerset

/-- Any subset of the two raw gate uses may contribute in one epoch. -/
def rawGateCoLive : Finset (Finset Bool) := Finset.univ

/-- Map every configuration in a finite family through an identity quotient. -/
def quotientFamily (family : Finset (Finset Bool)) (quotient : Bool → Bool) :
    Finset (Finset Bool) :=
  family.image fun config => config.image quotient

def sharedCellOf (_handle : Bool) : Bool := false
def distinctCellOf (handle : Bool) : Bool := handle

def sharedControllerOf (_use : Bool) : Bool := false
def distinctControllerOf (use : Bool) : Bool := use

/-- The semantic future obtained after handle-to-cell normalization. -/
def normalizedFuture (cellOf : Bool → Bool) : Finset (Finset Bool) :=
  quotientFamily rawHandleFuture cellOf

/-- A normalized cell is accessible through a normalized controller exactly
when some raw gate use maps to both. -/
def normalizedAccess (cellOf controllerOf : Bool → Bool) :
    ControllerAccess Bool Bool :=
  fun cell controller =>
    ∃ use : Bool, cellOf use = cell ∧ controllerOf use = controller

/-- Normalize each raw gate-local family through cell identity, then union the
families of gate uses folded to the same controller.  Union—not product—is
intentional: alternative gate uses of one authority remain alternative local
choices, whereas gate uses assigned to distinct controllers may later combine
through co-liveness. -/
def normalizedLocal (cellOf controllerOf : Bool → Bool) :
    LocalControllerFamilies Bool Bool :=
  fun controller =>
    Finset.univ.biUnion fun use =>
      if controllerOf use = controller then
        quotientFamily (rawGateLocal use) cellOf
      else ∅

/-- Normalize raw gate-use co-liveness independently from cell identity. -/
def normalizedCoLive (controllerOf : Bool → Bool) : CoLiveFamily Bool :=
  quotientFamily rawGateCoLive controllerOf

def Ready (cellOf controllerOf : Bool → Bool) : Prop :=
  DeploymentReady
    (normalizedFuture cellOf)
    (normalizedFuture cellOf)
    (normalizedAccess cellOf controllerOf)
    (normalizedLocal cellOf controllerOf)
    (normalizedCoLive controllerOf)

/-! The following normalization equations expose the four finite products
without changing the raw manifest. -/

theorem normalizedFuture_shared :
    normalizedFuture sharedCellOf = ({false} : Finset Bool).powerset := by
  native_decide

theorem normalizedFuture_distinct :
    normalizedFuture distinctCellOf = rawHandleFuture := by
  native_decide

theorem normalizedCoLive_shared :
    normalizedCoLive sharedControllerOf = ({false} : Finset Bool).powerset := by
  native_decide

theorem normalizedCoLive_distinct :
    normalizedCoLive distinctControllerOf = rawGateCoLive := by
  native_decide

theorem normalizedLocal_shared_shared (controller : Bool) :
    normalizedLocal sharedCellOf sharedControllerOf controller =
      if controller = false then ({false} : Finset Bool).powerset else ∅ := by
  cases controller <;> native_decide

theorem normalizedLocal_shared_distinct (controller : Bool) :
    normalizedLocal sharedCellOf distinctControllerOf controller =
      ({false} : Finset Bool).powerset := by
  cases controller <;> native_decide

theorem normalizedLocal_distinct_shared (controller : Bool) :
    normalizedLocal distinctCellOf sharedControllerOf controller =
      if controller = false then rawHandleFuture else ∅ := by
  cases controller <;> native_decide

theorem normalizedLocal_distinct_distinct (controller : Bool) :
    normalizedLocal distinctCellOf distinctControllerOf controller =
      ({controller} : Finset Bool).powerset := by
  cases controller <;> native_decide

theorem normalizedAccess_shared_shared (cell controller : Bool) :
    normalizedAccess sharedCellOf sharedControllerOf cell controller ↔
      cell = false ∧ controller = false := by
  cases cell <;> cases controller <;>
    simp [normalizedAccess, sharedCellOf, sharedControllerOf]

theorem normalizedAccess_shared_distinct (cell controller : Bool) :
    normalizedAccess sharedCellOf distinctControllerOf cell controller ↔
      cell = false := by
  cases cell <;> cases controller <;>
    simp [normalizedAccess, sharedCellOf, distinctControllerOf]

theorem normalizedAccess_distinct_shared (cell controller : Bool) :
    normalizedAccess distinctCellOf sharedControllerOf cell controller ↔
      controller = false := by
  cases cell <;> cases controller <;>
    simp [normalizedAccess, distinctCellOf, sharedControllerOf]

theorem normalizedAccess_distinct_distinct (cell controller : Bool) :
    normalizedAccess distinctCellOf distinctControllerOf cell controller ↔
      cell = controller := by
  cases cell <;> cases controller <;>
    simp [normalizedAccess, distinctCellOf, distinctControllerOf]

/-! ## Well-structuredness of every quotient world -/

/-- The fixture assumptions used by deployment readiness are explicit: the
semantic future and every local/controller family are downward closed, and
local choices are both admitted and access-valid. -/
def WellStructured (cellOf controllerOf : Bool → Bool) : Prop :=
  SourceFamilyWellFormed (normalizedFuture cellOf) ∧
    LocalFamiliesDownwardClosed (normalizedLocal cellOf controllerOf) ∧
    LocalFamiliesSound
      (normalizedFuture cellOf)
      (normalizedAccess cellOf controllerOf)
      (normalizedLocal cellOf controllerOf) ∧
    CoLiveDownwardClosed (normalizedCoLive controllerOf)

theorem singletonFuture_wellFormed :
    SourceFamilyWellFormed (({false} : Finset Bool).powerset) := by
  refine ⟨⟨∅, by simp⟩, by simp, ?_⟩
  intro C K hC hSubset
  exact Finset.mem_powerset.mpr
    (hSubset.trans (Finset.mem_powerset.mp hC))

theorem rawHandleFuture_wellFormed :
    SourceFamilyWellFormed rawHandleFuture := by
  refine ⟨⟨∅, by simp [rawHandleFuture, exclusiveTarget]⟩,
    by simp [rawHandleFuture, exclusiveTarget], ?_⟩
  intro C K hC hSubset
  simp only [rawHandleFuture, exclusiveTarget, Finset.mem_insert,
    Finset.mem_singleton] at hC ⊢
  rcases hC with rfl | rfl | rfl
  · exact Or.inl (Finset.Subset.antisymm hSubset (Finset.empty_subset K))
  · by_cases hEmpty : K = ∅
    · exact Or.inl hEmpty
    · obtain ⟨cell, hCell⟩ := Finset.nonempty_iff_ne_empty.mpr hEmpty
      have hCellFalse : cell = false := by simpa using hSubset hCell
      subst cell
      exact Or.inr (Or.inl (Finset.Subset.antisymm hSubset (by simpa)))
  · by_cases hEmpty : K = ∅
    · exact Or.inl hEmpty
    · obtain ⟨cell, hCell⟩ := Finset.nonempty_iff_ne_empty.mpr hEmpty
      have hCellTrue : cell = true := by simpa using hSubset hCell
      subst cell
      exact Or.inr (Or.inr (Finset.Subset.antisymm hSubset (by simpa)))

theorem normalizedFuture_shared_wellFormed :
    SourceFamilyWellFormed (normalizedFuture sharedCellOf) := by
  rw [normalizedFuture_shared]
  exact singletonFuture_wellFormed

theorem normalizedFuture_distinct_wellFormed :
    SourceFamilyWellFormed (normalizedFuture distinctCellOf) := by
  rw [normalizedFuture_distinct]
  exact rawHandleFuture_wellFormed

theorem normalizedCoLive_shared_downwardClosed :
    CoLiveDownwardClosed (normalizedCoLive sharedControllerOf) := by
  intro active hActive smaller hSubset
  rw [normalizedCoLive_shared] at hActive ⊢
  exact Finset.mem_powerset.mpr
    (hSubset.trans (Finset.mem_powerset.mp hActive))

theorem normalizedCoLive_distinct_downwardClosed :
    CoLiveDownwardClosed (normalizedCoLive distinctControllerOf) := by
  intro active hActive smaller hSubset
  rw [normalizedCoLive_distinct]
  simp [rawGateCoLive]

theorem normalizedLocal_shared_shared_downwardClosed :
    LocalFamiliesDownwardClosed
      (normalizedLocal sharedCellOf sharedControllerOf) := by
  intro controller C K hC hSubset
  rw [normalizedLocal_shared_shared] at hC ⊢
  by_cases hc : controller = false
  · simp only [hc, ↓reduceIte] at hC ⊢
    exact Finset.mem_powerset.mpr
      (hSubset.trans (Finset.mem_powerset.mp hC))
  · simp [hc] at hC

theorem normalizedLocal_shared_distinct_downwardClosed :
    LocalFamiliesDownwardClosed
      (normalizedLocal sharedCellOf distinctControllerOf) := by
  intro controller C K hC hSubset
  rw [normalizedLocal_shared_distinct] at hC ⊢
  exact Finset.mem_powerset.mpr
    (hSubset.trans (Finset.mem_powerset.mp hC))

theorem normalizedLocal_distinct_shared_downwardClosed :
    LocalFamiliesDownwardClosed
      (normalizedLocal distinctCellOf sharedControllerOf) := by
  intro controller C K hC hSubset
  rw [normalizedLocal_distinct_shared] at hC ⊢
  by_cases hc : controller = false
  · simp only [hc, ↓reduceIte] at hC ⊢
    exact rawHandleFuture_wellFormed.downwardClosed hC hSubset
  · simp [hc] at hC

theorem normalizedLocal_distinct_distinct_downwardClosed :
    LocalFamiliesDownwardClosed
      (normalizedLocal distinctCellOf distinctControllerOf) := by
  intro controller C K hC hSubset
  rw [normalizedLocal_distinct_distinct] at hC ⊢
  exact Finset.mem_powerset.mpr
    (hSubset.trans (Finset.mem_powerset.mp hC))

theorem normalizedLocal_shared_shared_sound :
    LocalFamiliesSound
      (normalizedFuture sharedCellOf)
      (normalizedAccess sharedCellOf sharedControllerOf)
      (normalizedLocal sharedCellOf sharedControllerOf) := by
  intro controller C hC
  rw [normalizedLocal_shared_shared] at hC
  by_cases hc : controller = false
  · subst controller
    simp only [↓reduceIte] at hC
    constructor
    · rw [normalizedFuture_shared]
      exact hC
    · intro cell hCell
      rw [normalizedAccess_shared_shared]
      have hSubset := Finset.mem_powerset.mp hC
      exact ⟨by simpa using hSubset hCell, rfl⟩
  · simp [hc] at hC

theorem normalizedLocal_shared_distinct_sound :
    LocalFamiliesSound
      (normalizedFuture sharedCellOf)
      (normalizedAccess sharedCellOf distinctControllerOf)
      (normalizedLocal sharedCellOf distinctControllerOf) := by
  intro controller C hC
  rw [normalizedLocal_shared_distinct] at hC
  constructor
  · rw [normalizedFuture_shared]
    exact hC
  · intro cell hCell
    rw [normalizedAccess_shared_distinct]
    have hSubset := Finset.mem_powerset.mp hC
    simpa using hSubset hCell

theorem normalizedLocal_distinct_shared_sound :
    LocalFamiliesSound
      (normalizedFuture distinctCellOf)
      (normalizedAccess distinctCellOf sharedControllerOf)
      (normalizedLocal distinctCellOf sharedControllerOf) := by
  intro controller C hC
  rw [normalizedLocal_distinct_shared] at hC
  by_cases hc : controller = false
  · subst controller
    simp only [↓reduceIte] at hC
    constructor
    · rw [normalizedFuture_distinct]
      exact hC
    · intro cell hCell
      simp [normalizedAccess_distinct_shared]
  · simp [hc] at hC

theorem normalizedLocal_distinct_distinct_sound :
    LocalFamiliesSound
      (normalizedFuture distinctCellOf)
      (normalizedAccess distinctCellOf distinctControllerOf)
      (normalizedLocal distinctCellOf distinctControllerOf) := by
  intro controller C hC
  rw [normalizedLocal_distinct_distinct] at hC
  have hSubset := Finset.mem_powerset.mp hC
  constructor
  · rw [normalizedFuture_distinct]
    apply rawHandleFuture_wellFormed.downwardClosed
      (C := ({controller} : Finset Bool))
    · cases controller <;> native_decide
    · exact hSubset
  · intro cell hCell
    rw [normalizedAccess_distinct_distinct]
    simpa using hSubset hCell

/-- None of the four readiness outcomes is caused by a malformed future,
local family, access declaration, or co-liveness family. -/
theorem identityQuotient_worlds_wellStructured :
    WellStructured sharedCellOf sharedControllerOf ∧
      WellStructured sharedCellOf distinctControllerOf ∧
      WellStructured distinctCellOf sharedControllerOf ∧
      WellStructured distinctCellOf distinctControllerOf := by
  exact ⟨
    ⟨normalizedFuture_shared_wellFormed,
      normalizedLocal_shared_shared_downwardClosed,
      normalizedLocal_shared_shared_sound,
      normalizedCoLive_shared_downwardClosed⟩,
    ⟨normalizedFuture_shared_wellFormed,
      normalizedLocal_shared_distinct_downwardClosed,
      normalizedLocal_shared_distinct_sound,
      normalizedCoLive_distinct_downwardClosed⟩,
    ⟨normalizedFuture_distinct_wellFormed,
      normalizedLocal_distinct_shared_downwardClosed,
      normalizedLocal_distinct_shared_sound,
      normalizedCoLive_shared_downwardClosed⟩,
    ⟨normalizedFuture_distinct_wellFormed,
      normalizedLocal_distinct_distinct_downwardClosed,
      normalizedLocal_distinct_distinct_sound,
      normalizedCoLive_distinct_downwardClosed⟩⟩

theorem raw_sharedCell_sharedController :
    rawPhysicalCoverProduct
        (normalizedAccess sharedCellOf sharedControllerOf)
        (normalizedLocal sharedCellOf sharedControllerOf)
        (normalizedCoLive sharedControllerOf) =
      ({false} : Finset Bool).powerset := by
  apply Finset.Subset.antisymm
  · intro C hC
    rw [mem_rawPhysicalCoverProduct_iff] at hC
    obtain ⟨plan, hCoLive, hLocal, hAccess, hUnion⟩ := hC
    apply Finset.mem_powerset.mpr
    intro cell hCell
    have hCellUnion : cell ∈ plan.active.biUnion plan.piece := by
      rw [hUnion]
      exact hCell
    obtain ⟨controller, hController, hPiece⟩ :=
      Finset.mem_biUnion.mp hCellUnion
    have hAccessible := hAccess controller hController cell hPiece
    exact by
      have hCellFalse :=
        (normalizedAccess_shared_shared cell controller).1 hAccessible |>.1
      simpa using hCellFalse
  · intro C hC
    rw [mem_rawPhysicalCoverProduct_iff]
    let plan : CoverPlan Bool Bool :=
      { active := {false}
        piece := fun controller => if controller = false then C else ∅ }
    refine ⟨plan, ?_⟩
    refine ⟨?_, ?_, ?_, ?_⟩
    · rw [normalizedCoLive_shared]
      simp [plan]
    · intro controller hController
      have hc : controller = false := by simpa [plan] using hController
      subst controller
      simpa [plan, normalizedLocal_shared_shared] using hC
    · intro controller hController cell hCell
      have hc : controller = false := by simpa [plan] using hController
      subst controller
      rw [normalizedAccess_shared_shared]
      refine ⟨?_, rfl⟩
      exact by
        have hSubset := Finset.mem_powerset.mp hC
        simpa using hSubset (by simpa [plan] using hCell)
    · ext cell
      simp [plan]

theorem raw_sharedCell_distinctControllers :
    rawPhysicalCoverProduct
        (normalizedAccess sharedCellOf distinctControllerOf)
        (normalizedLocal sharedCellOf distinctControllerOf)
        (normalizedCoLive distinctControllerOf) =
      ({false} : Finset Bool).powerset := by
  apply Finset.Subset.antisymm
  · intro C hC
    rw [mem_rawPhysicalCoverProduct_iff] at hC
    obtain ⟨plan, _hCoLive, _hLocal, hAccess, hUnion⟩ := hC
    apply Finset.mem_powerset.mpr
    intro cell hCell
    have hCellUnion : cell ∈ plan.active.biUnion plan.piece := by
      rw [hUnion]
      exact hCell
    obtain ⟨controller, hController, hPiece⟩ :=
      Finset.mem_biUnion.mp hCellUnion
    have hAccessible := hAccess controller hController cell hPiece
    simpa using (normalizedAccess_shared_distinct cell controller).1 hAccessible
  · intro C hC
    rw [mem_rawPhysicalCoverProduct_iff]
    let plan : CoverPlan Bool Bool :=
      { active := {false}
        piece := fun controller => if controller = false then C else ∅ }
    refine ⟨plan, ?_⟩
    refine ⟨?_, ?_, ?_, ?_⟩
    · rw [normalizedCoLive_distinct]
      simp [rawGateCoLive, plan]
    · intro controller hController
      have hc : controller = false := by simpa [plan] using hController
      subst controller
      simpa [plan, normalizedLocal_shared_distinct] using hC
    · intro controller hController cell hCell
      have hc : controller = false := by simpa [plan] using hController
      subst controller
      rw [normalizedAccess_shared_distinct]
      have hSubset := Finset.mem_powerset.mp hC
      exact by
        have hCellC : cell ∈ C := by simpa [plan] using hCell
        simpa using hSubset hCellC
    · ext cell
      simp [plan]

theorem raw_distinctCells_sharedController :
    rawPhysicalCoverProduct
        (normalizedAccess distinctCellOf sharedControllerOf)
        (normalizedLocal distinctCellOf sharedControllerOf)
        (normalizedCoLive sharedControllerOf) = rawHandleFuture := by
  apply Finset.Subset.antisymm
  · intro C hC
    rw [mem_rawPhysicalCoverProduct_iff] at hC
    obtain ⟨plan, hCoLive, hLocal, _hAccess, hUnion⟩ := hC
    rw [normalizedCoLive_shared] at hCoLive
    have hActiveSubset : plan.active ⊆ ({false} : Finset Bool) :=
      Finset.mem_powerset.mp hCoLive
    by_cases hFalse : false ∈ plan.active
    · have hActive : plan.active = {false} := by
        apply Finset.Subset.antisymm hActiveSubset
        simpa using hFalse
      have hPiece : plan.piece false ∈ rawHandleFuture := by
        simpa [normalizedLocal_distinct_shared] using hLocal false hFalse
      have hEq : C = plan.piece false := by
        rw [← hUnion, hActive]
        ext cell
        simp
      simpa [hEq] using hPiece
    · have hActive : plan.active = ∅ := by
        apply Finset.eq_empty_iff_forall_notMem.mpr
        intro controller hController
        have hc : controller = false := by
          simpa using hActiveSubset hController
        exact hFalse (hc ▸ hController)
      have hEq : C = ∅ := by simpa [hActive] using hUnion.symm
      simp [hEq, rawHandleFuture, exclusiveTarget]
  · intro C hC
    rw [mem_rawPhysicalCoverProduct_iff]
    let plan : CoverPlan Bool Bool :=
      { active := {false}
        piece := fun controller => if controller = false then C else ∅ }
    refine ⟨plan, ?_⟩
    refine ⟨?_, ?_, ?_, ?_⟩
    · rw [normalizedCoLive_shared]
      simp [plan]
    · intro controller hController
      have hc : controller = false := by simpa [plan] using hController
      subst controller
      simpa [plan, normalizedLocal_distinct_shared] using hC
    · intro controller hController cell hCell
      have hc : controller = false := by simpa [plan] using hController
      subst controller
      simp [normalizedAccess_distinct_shared]
    · ext cell
      simp [plan]

theorem raw_distinctCells_distinctControllers :
    rawPhysicalCoverProduct
        (normalizedAccess distinctCellOf distinctControllerOf)
        (normalizedLocal distinctCellOf distinctControllerOf)
        (normalizedCoLive distinctControllerOf) = Finset.univ := by
  apply Finset.eq_univ_of_forall
  intro C
  rw [mem_rawPhysicalCoverProduct_iff]
  let plan : CoverPlan Bool Bool :=
    { active := C
      piece := fun controller => {controller} }
  refine ⟨plan, ?_⟩
  refine ⟨?_, ?_, ?_, ?_⟩
  · rw [normalizedCoLive_distinct]
    simp [rawGateCoLive]
  · intro controller hController
    rw [normalizedLocal_distinct_distinct]
    simp [plan]
  · intro controller hController cell hCell
    rw [normalizedAccess_distinct_distinct]
    simpa [plan] using hCell
  · ext cell
    simp [plan]

/-! ## Exact 2-by-2 decision matrix -/

theorem sharedCell_sharedController_ready :
    Ready sharedCellOf sharedControllerOf := by
  unfold Ready DeploymentReady
  rw [normalizedFuture_shared, raw_sharedCell_sharedController]
  exact ⟨Finset.Subset.rfl, Finset.Subset.rfl⟩

theorem sharedCell_distinctControllers_ready :
    Ready sharedCellOf distinctControllerOf := by
  unfold Ready DeploymentReady
  rw [normalizedFuture_shared, raw_sharedCell_distinctControllers]
  exact ⟨Finset.Subset.rfl, Finset.Subset.rfl⟩

theorem distinctCells_sharedController_ready :
    Ready distinctCellOf sharedControllerOf := by
  unfold Ready DeploymentReady
  rw [normalizedFuture_distinct, raw_distinctCells_sharedController]
  exact ⟨Finset.Subset.rfl, Finset.Subset.rfl⟩

theorem distinctCells_distinctControllers_rejected :
    ¬Ready distinctCellOf distinctControllerOf := by
  intro hReady
  unfold Ready DeploymentReady at hReady
  have hPairRaw : ({false, true} : Finset Bool) ∈
      rawPhysicalCoverProduct
        (normalizedAccess distinctCellOf distinctControllerOf)
        (normalizedLocal distinctCellOf distinctControllerOf)
        (normalizedCoLive distinctControllerOf) := by
    rw [raw_distinctCells_distinctControllers]
    simp
  have hPairAdmitted := hReady.2 hPairRaw
  rw [normalizedFuture_distinct] at hPairAdmitted
  exact (by native_decide :
    ({false, true} : Finset Bool) ∉ rawHandleFuture) hPairAdmitted

theorem identityQuotient_decision_matrix :
    Ready sharedCellOf sharedControllerOf ∧
      Ready sharedCellOf distinctControllerOf ∧
      Ready distinctCellOf sharedControllerOf ∧
      ¬Ready distinctCellOf distinctControllerOf :=
  ⟨sharedCell_sharedController_ready,
    sharedCell_distinctControllers_ready,
    distinctCells_sharedController_ready,
    distinctCells_distinctControllers_rejected⟩

/-! ## Partial-observation collisions -/

/-- This view retains the complete raw manifest and controller quotient, but
erases only the handle-to-cell quotient.  Function maps are represented by
their two finite coordinates. -/
structure CellQuotientErasedView where
  handleFuture : Finset (Finset Bool)
  gateLocalFalse : Finset (Finset Bool)
  gateLocalTrue : Finset (Finset Bool)
  gateCoLive : Finset (Finset Bool)
  controllerMap : Bool × Bool
  deriving DecidableEq

def eraseCellQuotient (_cellOf controllerOf : Bool → Bool) :
    CellQuotientErasedView where
  handleFuture := rawHandleFuture
  gateLocalFalse := rawGateLocal false
  gateLocalTrue := rawGateLocal true
  gateCoLive := rawGateCoLive
  controllerMap := (controllerOf false, controllerOf true)

/-- With controller identity fixed, removing only cell identity equates a safe
aliased-cell interpretation with the unsafe distinct-cell interpretation. -/
theorem noCellQuotient_collision :
    eraseCellQuotient sharedCellOf distinctControllerOf =
        eraseCellQuotient distinctCellOf distinctControllerOf ∧
      Ready sharedCellOf distinctControllerOf ∧
      ¬Ready distinctCellOf distinctControllerOf :=
  ⟨rfl, sharedCell_distinctControllers_ready,
    distinctCells_distinctControllers_rejected⟩

/-- This view retains the complete raw manifest and cell quotient, but erases
only the gate-use-to-controller quotient. -/
structure ControllerQuotientErasedView where
  handleFuture : Finset (Finset Bool)
  gateLocalFalse : Finset (Finset Bool)
  gateLocalTrue : Finset (Finset Bool)
  gateCoLive : Finset (Finset Bool)
  cellMap : Bool × Bool
  deriving DecidableEq

def eraseControllerQuotient (cellOf _controllerOf : Bool → Bool) :
    ControllerQuotientErasedView where
  handleFuture := rawHandleFuture
  gateLocalFalse := rawGateLocal false
  gateLocalTrue := rawGateLocal true
  gateCoLive := rawGateCoLive
  cellMap := (cellOf false, cellOf true)

/-- With cell identity fixed, removing only controller identity equates the
safe shared-controller interpretation with the unsafe split-controller one. -/
theorem noControllerQuotient_collision :
    eraseControllerQuotient distinctCellOf sharedControllerOf =
        eraseControllerQuotient distinctCellOf distinctControllerOf ∧
      Ready distinctCellOf sharedControllerOf ∧
      ¬Ready distinctCellOf distinctControllerOf :=
  ⟨rfl, distinctCells_sharedController_ready,
    distinctCells_distinctControllers_rejected⟩

/-- Both quotient maps are independently necessary for an exact readiness
decision over this raw-manifest class: keeping all raw fields and the other
quotient does not remove either observation collision. -/
theorem identityQuotients_independently_necessary :
    (eraseCellQuotient sharedCellOf distinctControllerOf =
        eraseCellQuotient distinctCellOf distinctControllerOf ∧
      Ready sharedCellOf distinctControllerOf ∧
      ¬Ready distinctCellOf distinctControllerOf) ∧
    (eraseControllerQuotient distinctCellOf sharedControllerOf =
        eraseControllerQuotient distinctCellOf distinctControllerOf ∧
      Ready distinctCellOf sharedControllerOf ∧
      ¬Ready distinctCellOf distinctControllerOf) :=
  ⟨noCellQuotient_collision, noControllerQuotient_collision⟩

end Fixtures

end AuthorityContinuity.IdentityQuotientSeparation
