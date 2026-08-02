import AuthorityContinuity.ControllerCoverAdmission
import AuthorityContinuity.TypedHistoryAdmission

/-!
# Independent identity quotients

The history-admission interface normalizes two different kinds of identity:
copied handles to semantic redemption cells, and gate uses to authoritative
controller instances.  This module gives two finite separation results.  If
either normalization is erased, two manifests have the same remaining raw
view but require opposite admission decisions.
-/

namespace AuthorityContinuity.IdentityQuotientSeparation

open ConfigurationCellQuotient
open ControllerCoverAdmission
open CoordinationDecomposition

namespace Fixtures

open ConfigurationCellQuotient.Fixtures
open TypedHistoryAdmission.Fixtures.SharedLease

/-! ## Cell-identity erasure -/

/-- The raw handle view deliberately excludes the handle-to-cell quotient. -/
structure CellErasedView where
  handles : Finset Bool
  future : Finset (Finset Bool)
  deriving DecidableEq

def rawHandleView : CellErasedView where
  handles := Finset.univ
  future := parallelTarget

/-- Erasing cell identity makes every proposed quotient of the same handle
future observationally identical. -/
def eraseCellIdentity {Cell : Type*} (_cellOf : Bool → Cell) : CellErasedView :=
  rawHandleView

/-- Normalize every handle configuration through a proposed semantic-cell
map. -/
def quotientHandleFamily {Cell : Type*} [DecidableEq Cell]
    (future : Finset (Finset Bool)) (cellOf : Bool → Cell) :
    Finset (Finset Cell) :=
  future.image fun handles => handles.image cellOf

def sharedCellOf (_handle : Bool) : Unit := ()
def distinctCellOf (handle : Bool) : Bool := handle

theorem sharedCell_future_eq :
    quotientHandleFamily parallelTarget sharedCellOf = unitSource := by
  decide

theorem distinctCell_future_eq :
    quotientHandleFamily parallelTarget distinctCellOf = parallelTarget := by
  decide

theorem sharedCell_admitted :
    ConfigMorphism unitSource
      (quotientHandleFamily parallelTarget sharedCellOf) id := by
  rw [sharedCell_future_eq]
  intro C hC
  exact ⟨Function.injective_id.injOn, by simpa using hC⟩

theorem distinctCell_rejected :
    ¬ConfigMorphism unitSource
      (quotientHandleFamily parallelTarget distinctCellOf)
      collapseLineage := by
  rw [distinctCell_future_eq]
  exact parallel_shared_lineage_is_not_morphism

/-- Without the cell quotient the two manifests have the same handle-level
view, although folding the handles to one redemption cell is admissible and
treating them as two cells is not. -/
theorem cellQuotient_erasure_collision :
    eraseCellIdentity sharedCellOf = eraseCellIdentity distinctCellOf ∧
      ConfigMorphism unitSource
        (quotientHandleFamily parallelTarget sharedCellOf) id ∧
      ¬ConfigMorphism unitSource
        (quotientHandleFamily parallelTarget distinctCellOf)
        collapseLineage :=
  ⟨rfl, sharedCell_admitted, distinctCell_rejected⟩

/-! ## Controller-identity erasure -/

/-- The raw gate-use view deliberately excludes the use-to-controller
quotient. -/
structure ControllerErasedView where
  gateUses : Finset Bool
  admitted : Finset (Finset Bool)
  deriving DecidableEq

def rawGateUseView : ControllerErasedView where
  gateUses := Finset.univ
  admitted := exclusiveTarget

def eraseControllerIdentity {Controller : Type*}
    (_controllerOf : Bool → Controller) : ControllerErasedView :=
  rawGateUseView

def sharedControllerOf (_use : Bool) : Unit := ()
def distinctControllerOf (use : Bool) : Bool := use

theorem canonicalPartition_ready_iff_exact
    {G : Type*} [Fintype G] [DecidableEq G]
    (blockOf : Bool → G) :
    DeploymentReady exclusiveTarget exclusiveTarget
        (partitionAccess blockOf)
        (partitionLocalFamilies exclusiveTarget blockOf)
        partitionCoLive ↔
      ExactFactorization exclusiveTarget blockOf := by
  have hWF : SourceFamilyWellFormed exclusiveTarget := by
    simpa [choice_candidate_eq_target] using
      (TypedHistoryAdmission.HistoryOp.candidate_wellFormed
        TypedHistoryAdmission.Fixtures.choiceOp
        TypedHistoryAdmission.Fixtures.choiceOp_valid)
  rw [canonicalPartition_deploymentReady_iff_mustCoordinate
    exclusiveTarget exclusiveTarget blockOf hWF]
  rw [exactFactorization_iff_constant_on_mustCoordinate
    exclusiveTarget blockOf hWF]
  simp

theorem distinctControllers_rejected :
    ¬DeploymentReady exclusiveTarget exclusiveTarget
      (partitionAccess distinctControllerOf)
      (partitionLocalFamilies exclusiveTarget distinctControllerOf)
      partitionCoLive := by
  rw [canonicalPartition_ready_iff_exact]
  simpa [choice_candidate_eq_target] using choice_split_controllers_not_exact

theorem sharedController_admitted :
    DeploymentReady exclusiveTarget exclusiveTarget
      (partitionAccess sharedControllerOf)
      (partitionLocalFamilies exclusiveTarget sharedControllerOf)
      partitionCoLive := by
  rw [canonicalPartition_ready_iff_exact]
  simpa [choice_candidate_eq_target] using choice_shared_controller_exact

/-- Without the controller quotient the two manifests have the same gate-use
view, although one shared authoritative controller preserves exclusive choice
and two independent controllers product-compose the forbidden pair. -/
theorem controllerQuotient_erasure_collision :
    eraseControllerIdentity sharedControllerOf =
        eraseControllerIdentity distinctControllerOf ∧
      DeploymentReady exclusiveTarget exclusiveTarget
        (partitionAccess sharedControllerOf)
        (partitionLocalFamilies exclusiveTarget sharedControllerOf)
        partitionCoLive ∧
      ¬DeploymentReady exclusiveTarget exclusiveTarget
        (partitionAccess distinctControllerOf)
        (partitionLocalFamilies exclusiveTarget distinctControllerOf)
        partitionCoLive :=
  ⟨rfl, sharedController_admitted, distinctControllers_rejected⟩

/-- The two quotient maps are independently necessary: erasing either one
admits an observation collision with opposite security decisions. -/
theorem identityQuotients_independently_necessary :
    (eraseCellIdentity sharedCellOf = eraseCellIdentity distinctCellOf ∧
      ConfigMorphism unitSource
        (quotientHandleFamily parallelTarget sharedCellOf) id ∧
      ¬ConfigMorphism unitSource
        (quotientHandleFamily parallelTarget distinctCellOf)
        collapseLineage) ∧
    (eraseControllerIdentity sharedControllerOf =
        eraseControllerIdentity distinctControllerOf ∧
      DeploymentReady exclusiveTarget exclusiveTarget
        (partitionAccess sharedControllerOf)
        (partitionLocalFamilies exclusiveTarget sharedControllerOf)
        partitionCoLive ∧
      ¬DeploymentReady exclusiveTarget exclusiveTarget
        (partitionAccess distinctControllerOf)
        (partitionLocalFamilies exclusiveTarget distinctControllerOf)
        partitionCoLive) :=
  ⟨cellQuotient_erasure_collision, controllerQuotient_erasure_collision⟩

end Fixtures

end AuthorityContinuity.IdentityQuotientSeparation
