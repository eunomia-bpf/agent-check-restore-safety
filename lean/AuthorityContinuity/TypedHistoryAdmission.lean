import AuthorityContinuity.DurablePrefixTransport

/-!
# Typed history-transformation admission

This module makes the candidate future an output of a typed history operator,
rather than an unconstrained premise supplied to the safety theorem.  Choice
operators preserve alternatives; concurrent/live/join operators close their
arms under joint durability.  The distinction is semantic: it concerns fresh
durable commitments, not copied workspace handles.

The module also defines structural certificate inheritance.  An already
admitted source envelope may be transported through a target-to-source
configuration morphism whose lineage diagram commutes.  When structural
inheritance fails, the durable-prefix filter gives the exact pruning boundary
for the fixed generated family.  No theorem here claims that a concrete
runtime realizes the generated family; that is an adapter refinement premise.
The leaf/arm contracts also remain explicit inputs: the typed constructor
derives their choice-versus-joint composition, not their workload semantics.
-/

namespace AuthorityContinuity.TypedHistoryAdmission

open ConfigurationCellQuotient
open DurablePrefixTransport

set_option linter.unusedSectionVars false

universe uU uS uD uE uV

variable {U : Type uU} {S : Type uS} {D : Type uD} {E : Type uE}
variable [Fintype U] [DecidableEq U]
variable [Fintype S] [DecidableEq S]
variable [Fintype D] [DecidableEq D]
variable [Fintype E] [DecidableEq E]

/-! ## Finite future-family algebra -/

/-- Exclusive alternatives: either arm may supply the fresh commitments. -/
def familyChoice (left right : Finset (Finset D)) : Finset (Finset D) :=
  left ∪ right

/-- Joint durability: independently selected arm configurations may coexist.

`D` is a namespace of already-normalized *semantic commitment cells*, not a
namespace of physical controllers or resource names.  Thus the same `d` in
both arms denotes one deliberately shared obligation and is counted once by
the union.  Two independent obligation occurrences must have distinct `D`
identities, even when a runtime places them on the same controller.  Assigning
those identities (normally by arm tagging) and justifying any intentional
cross-arm alias are adapter obligations; this algebra does not infer aliases
from resource equality. -/
def familyTensor (left right : Finset (Finset D)) : Finset (Finset D) :=
  (left.product right).image fun pair => pair.1 ∪ pair.2

theorem mem_familyTensor_iff
    (left right : Finset (Finset D)) (C : Finset D) :
    C ∈ familyTensor left right ↔
      ∃ A ∈ left, ∃ B ∈ right, C = A ∪ B := by
  constructor
  · intro hC
    obtain ⟨pair, hPair, hEq⟩ := Finset.mem_image.mp hC
    obtain ⟨hLeft, hRight⟩ := Finset.mem_product.mp hPair
    exact ⟨pair.1, hLeft, pair.2, hRight, hEq.symm⟩
  · rintro ⟨A, hA, B, hB, rfl⟩
    exact Finset.mem_image.mpr
      ⟨(A, B), Finset.mem_product.mpr ⟨hA, hB⟩, rfl⟩

theorem familyChoice_mono
    {left left' right right' : Finset (Finset D)}
    (hLeft : left ⊆ left') (hRight : right ⊆ right') :
    familyChoice left right ⊆ familyChoice left' right' := by
  intro C hC
  simp only [familyChoice, Finset.mem_union] at hC ⊢
  exact hC.elim (fun h => Or.inl (hLeft h)) (fun h => Or.inr (hRight h))

theorem familyTensor_mono
    {left left' right right' : Finset (Finset D)}
    (hLeft : left ⊆ left') (hRight : right ⊆ right') :
    familyTensor left right ⊆ familyTensor left' right' := by
  intro C hC
  obtain ⟨A, hA, B, hB, rfl⟩ :=
    (mem_familyTensor_iff left right C).mp hC
  exact (mem_familyTensor_iff left' right' (A ∪ B)).mpr
    ⟨A, hLeft hA, B, hRight hB, rfl⟩

theorem familyChoice_wellFormed
    (left right : Finset (Finset D))
    (leftWF : SourceFamilyWellFormed left)
    (rightWF : SourceFamilyWellFormed right) :
    SourceFamilyWellFormed (familyChoice left right) := by
  refine ⟨?_, ?_, ?_⟩
  · exact ⟨∅, by simp [familyChoice, leftWF.empty_mem]⟩
  · simp [familyChoice, leftWF.empty_mem]
  · intro C C' hC hSubset
    simp only [familyChoice, Finset.mem_union] at hC ⊢
    exact hC.elim
      (fun h => Or.inl (leftWF.downwardClosed h hSubset))
      (fun h => Or.inr (rightWF.downwardClosed h hSubset))

theorem familyTensor_wellFormed
    (left right : Finset (Finset D))
    (leftWF : SourceFamilyWellFormed left)
    (rightWF : SourceFamilyWellFormed right) :
    SourceFamilyWellFormed (familyTensor left right) := by
  have hEmpty : (∅ : Finset D) ∈ familyTensor left right :=
    (mem_familyTensor_iff left right ∅).mpr
      ⟨∅, leftWF.empty_mem, ∅, rightWF.empty_mem, by simp⟩
  refine ⟨⟨∅, hEmpty⟩, hEmpty, ?_⟩
  intro C C' hC hSubset
  obtain ⟨A, hA, B, hB, hCAB⟩ :=
    (mem_familyTensor_iff left right C).mp hC
  have hSubsetAB : C' ⊆ A ∪ B := by simpa [hCAB] using hSubset
  let A' : Finset D := C' ∩ A
  let B' : Finset D := C' ∩ B
  have hSplit : C' = A' ∪ B' := by
    ext d
    simp only [A', B', Finset.mem_union, Finset.mem_inter]
    constructor
    · intro hd
      rcases Finset.mem_union.mp (hSubsetAB hd) with hdA | hdB
      · exact Or.inl ⟨hd, hdA⟩
      · exact Or.inr ⟨hd, hdB⟩
    · rintro (⟨hd, _⟩ | ⟨hd, _⟩) <;> exact hd
  apply (mem_familyTensor_iff left right C').mpr
  exact ⟨A', leftWF.downwardClosed hA Finset.inter_subset_right,
    B', rightWF.downwardClosed hB Finset.inter_subset_right, hSplit⟩

/-! ## Typed operations generate may/required futures -/

structure FutureContract (D : Type uD) where
  may : Finset (Finset D)
  required : Finset (Finset D)

namespace FutureContract

structure Valid (contract : FutureContract D) : Prop where
  mayWF : SourceFamilyWellFormed contract.may
  requiredWF : SourceFamilyWellFormed contract.required
  required_subset_may : contract.required ⊆ contract.may

end FutureContract

inductive HistoryOp (D : Type uD) where
  | forkChoice (left right : FutureContract D)
  | forkParallel (left right : FutureContract D)
  | restoreReplace (checkpoint : FutureContract D)
  | restoreLive (current checkpoint : FutureContract D)
  | mergeSelect (left right : FutureContract D)
  | mergeJoin (left right : FutureContract D)

namespace HistoryOp

def candidate : HistoryOp D -> Finset (Finset D)
  | .forkChoice left right => familyChoice left.may right.may
  | .forkParallel left right => familyTensor left.may right.may
  | .restoreReplace checkpoint => checkpoint.may
  | .restoreLive current checkpoint =>
      familyTensor current.may checkpoint.may
  | .mergeSelect left right => familyChoice left.may right.may
  | .mergeJoin left right => familyTensor left.may right.may

def required : HistoryOp D -> Finset (Finset D)
  | .forkChoice left right => familyChoice left.required right.required
  | .forkParallel left right => familyTensor left.required right.required
  | .restoreReplace checkpoint => checkpoint.required
  | .restoreLive current checkpoint =>
      familyTensor current.required checkpoint.required
  | .mergeSelect left right => familyChoice left.required right.required
  | .mergeJoin left right => familyTensor left.required right.required

def Valid : HistoryOp D -> Prop
  | .forkChoice left right
  | .forkParallel left right
  | .restoreLive left right
  | .mergeSelect left right
  | .mergeJoin left right => left.Valid ∧ right.Valid
  | .restoreReplace checkpoint => checkpoint.Valid

theorem candidate_wellFormed (op : HistoryOp D) (hValid : op.Valid) :
    SourceFamilyWellFormed op.candidate := by
  cases op with
  | forkChoice left right =>
      exact familyChoice_wellFormed left.may right.may
        hValid.1.mayWF hValid.2.mayWF
  | forkParallel left right =>
      exact familyTensor_wellFormed left.may right.may
        hValid.1.mayWF hValid.2.mayWF
  | restoreReplace checkpoint => exact hValid.mayWF
  | restoreLive current checkpoint =>
      exact familyTensor_wellFormed current.may checkpoint.may
        hValid.1.mayWF hValid.2.mayWF
  | mergeSelect left right =>
      exact familyChoice_wellFormed left.may right.may
        hValid.1.mayWF hValid.2.mayWF
  | mergeJoin left right =>
      exact familyTensor_wellFormed left.may right.may
        hValid.1.mayWF hValid.2.mayWF

theorem required_wellFormed (op : HistoryOp D) (hValid : op.Valid) :
    SourceFamilyWellFormed op.required := by
  cases op with
  | forkChoice left right =>
      exact familyChoice_wellFormed left.required right.required
        hValid.1.requiredWF hValid.2.requiredWF
  | forkParallel left right =>
      exact familyTensor_wellFormed left.required right.required
        hValid.1.requiredWF hValid.2.requiredWF
  | restoreReplace checkpoint => exact hValid.requiredWF
  | restoreLive current checkpoint =>
      exact familyTensor_wellFormed current.required checkpoint.required
        hValid.1.requiredWF hValid.2.requiredWF
  | mergeSelect left right =>
      exact familyChoice_wellFormed left.required right.required
        hValid.1.requiredWF hValid.2.requiredWF
  | mergeJoin left right =>
      exact familyTensor_wellFormed left.required right.required
        hValid.1.requiredWF hValid.2.requiredWF

theorem required_subset_candidate (op : HistoryOp D) (hValid : op.Valid) :
    op.required ⊆ op.candidate := by
  cases op with
  | forkChoice left right =>
      exact familyChoice_mono
        hValid.1.required_subset_may hValid.2.required_subset_may
  | forkParallel left right =>
      exact familyTensor_mono
        hValid.1.required_subset_may hValid.2.required_subset_may
  | restoreReplace checkpoint => exact hValid.required_subset_may
  | restoreLive current checkpoint =>
      exact familyTensor_mono
        hValid.1.required_subset_may hValid.2.required_subset_may
  | mergeSelect left right =>
      exact familyChoice_mono
        hValid.1.required_subset_may hValid.2.required_subset_may
  | mergeJoin left right =>
      exact familyTensor_mono
        hValid.1.required_subset_may hValid.2.required_subset_may

end HistoryOp

/-! ## Versioned structural certificate inheritance -/

/-- Classical configuration morphisms compose.  It is exposed here because
online history transformations use this fact to compose local certificates
without enumerating the eventual execution graph. -/
theorem configMorphism_comp
    (source : Finset (Finset S))
    (middle : Finset (Finset D))
    (target : Finset (Finset E))
    (rho₀₁ : D -> S) (rho₁₂ : E -> D)
    (h₀₁ : ConfigMorphism source middle rho₀₁)
    (h₁₂ : ConfigMorphism middle target rho₁₂) :
    ConfigMorphism source target (rho₀₁ ∘ rho₁₂) := by
  intro C hC
  obtain ⟨hInj₁₂, hImage₁₂⟩ := h₁₂ C hC
  obtain ⟨hInj₀₁, hImage₀₁⟩ :=
    h₀₁ (C.image rho₁₂) hImage₁₂
  refine ⟨?_, ?_⟩
  · intro e₁ he₁ e₂ he₂ hEq
    have hMiddleEq : rho₁₂ e₁ = rho₁₂ e₂ :=
      hInj₀₁
        (Finset.mem_image.mpr ⟨e₁, he₁, rfl⟩)
        (Finset.mem_image.mpr ⟨e₂, he₂, rfl⟩)
        hEq
    exact hInj₁₂ he₁ he₂ hMiddleEq
  · simpa [Finset.image_image, Function.comp_def] using hImage₀₁

/-- A checked authority envelope.  Version order is used only by lease
bookkeeping; additive authority safety depends on the family, lineage, durable
prefix, and admission proof. -/
structure AdmittedEnvelope
    (authority : Finset (Finset U)) (Cell : Type*) (Version : Type uV)
    [Fintype Cell] [DecidableEq Cell] where
  version : Version
  durable : Finset U
  future : Finset (Finset Cell)
  lineage : Cell -> U
  futureWF : SourceFamilyWellFormed future
  admitted : PrefixConfigMorphism authority durable future lineage

/-- A target future structurally refines an admitted old future when every
target configuration maps locally injectively into an old configuration and
the authority-lineage square commutes. -/
structure StructuralRefinement
    {Version : Type uV} [Preorder Version]
    {authority : Finset (Finset U)}
    (old : AdmittedEnvelope authority S Version)
    (target : Finset (Finset D)) (targetLineage : D -> U)
    (targetVersion : Version) where
  version_mono : old.version ≤ targetVersion
  targetWF : SourceFamilyWellFormed target
  parent : D -> S
  mapsFuture : ConfigMorphism old.future target parent
  lineage_commutes : ∀ d, targetLineage d = old.lineage (parent d)

namespace StructuralRefinement

theorem transports_prefixConfigMorphism
    {Version : Type uV} [Preorder Version]
    {authority : Finset (Finset U)}
    {old : AdmittedEnvelope authority S Version}
    {target : Finset (Finset D)} {targetLineage : D -> U}
    {targetVersion : Version}
    (refinement : StructuralRefinement old target targetLineage targetVersion) :
    PrefixConfigMorphism authority old.durable target targetLineage := by
  refine ⟨old.admitted.1, ?_⟩
  intro C hC
  obtain ⟨hParentInj, hParentImage⟩ := refinement.mapsFuture C hC
  obtain ⟨hOldInj, hOldDisjoint, hOldUnion⟩ :=
    old.admitted.2 (C.image refinement.parent) hParentImage
  have hTargetInj : Set.InjOn targetLineage (C : Set D) := by
    intro d₁ hd₁ d₂ hd₂ hTargetEq
    have hOldEq :
        old.lineage (refinement.parent d₁) =
          old.lineage (refinement.parent d₂) := by
      calc
        old.lineage (refinement.parent d₁) = targetLineage d₁ :=
          (refinement.lineage_commutes d₁).symm
        _ = targetLineage d₂ := hTargetEq
        _ = old.lineage (refinement.parent d₂) :=
          refinement.lineage_commutes d₂
    have hParentEq : refinement.parent d₁ = refinement.parent d₂ :=
      hOldInj
        (Finset.mem_image.mpr ⟨d₁, hd₁, rfl⟩)
        (Finset.mem_image.mpr ⟨d₂, hd₂, rfl⟩)
        hOldEq
    exact hParentInj hd₁ hd₂ hParentEq
  have hImage :
      C.image targetLineage =
        (C.image refinement.parent).image old.lineage := by
    ext u
    simp only [Finset.mem_image]
    constructor
    · rintro ⟨d, hd, hdu⟩
      refine ⟨refinement.parent d, ⟨d, hd, rfl⟩, ?_⟩
      calc
        old.lineage (refinement.parent d) = targetLineage d :=
          (refinement.lineage_commutes d).symm
        _ = u := hdu
    · rintro ⟨s, ⟨d, hd, hds⟩, hsu⟩
      subst s
      exact ⟨d, hd, (refinement.lineage_commutes d).trans hsu⟩
  exact ⟨hTargetInj, by simpa only [hImage] using hOldDisjoint,
    by simpa only [hImage] using hOldUnion⟩

/-- Produce a new versioned envelope without rechecking the authority policy.
The durable prefix is definitionally unchanged; receipt growth requires the
readmission path below. -/
def transportEnvelope
    {Version : Type uV} [Preorder Version]
    {authority : Finset (Finset U)}
    {old : AdmittedEnvelope authority S Version}
    {target : Finset (Finset D)} {targetLineage : D -> U}
    {targetVersion : Version}
    (refinement : StructuralRefinement old target targetLineage targetVersion) :
    AdmittedEnvelope authority D Version where
  version := targetVersion
  durable := old.durable
  future := target
  lineage := targetLineage
  futureWF := refinement.targetWF
  admitted := refinement.transports_prefixConfigMorphism

def refl
    {Version : Type uV} [Preorder Version]
    {authority : Finset (Finset U)}
    (envelope : AdmittedEnvelope authority D Version) :
    StructuralRefinement envelope envelope.future envelope.lineage
      envelope.version where
  version_mono := le_rfl
  targetWF := envelope.futureWF
  parent := id
  mapsFuture := by
    intro C hC
    exact ⟨Function.injective_id.injOn, by simpa using hC⟩
  lineage_commutes := by simp

/-- Sequential structural refinements compose, including version order,
configuration transport, and the lineage commuting square. -/
def trans
    {Version : Type uV} [Preorder Version]
    {authority : Finset (Finset U)}
    {old : AdmittedEnvelope authority S Version}
    {middle : Finset (Finset D)} {middleLineage : D -> U}
    {middleVersion : Version}
    (first :
      StructuralRefinement old middle middleLineage middleVersion)
    {target : Finset (Finset E)} {targetLineage : E -> U}
    {targetVersion : Version}
    (second : StructuralRefinement first.transportEnvelope
      target targetLineage targetVersion) :
    StructuralRefinement old target targetLineage targetVersion where
  version_mono := le_trans first.version_mono second.version_mono
  targetWF := second.targetWF
  parent := first.parent ∘ second.parent
  mapsFuture := configMorphism_comp old.future middle target
    first.parent second.parent first.mapsFuture second.mapsFuture
  lineage_commutes := by
    intro e
    calc
      targetLineage e = middleLineage (second.parent e) :=
        second.lineage_commutes e
      _ = old.lineage (first.parent (second.parent e)) :=
        first.lineage_commutes (second.parent e)
      _ = old.lineage ((first.parent ∘ second.parent) e) := rfl

end StructuralRefinement

/-- Structural inheritance for a typed operation is a refinement into the
candidate family generated by that operation. -/
def HistoryOp.CanInherit
    {Version : Type uV} [Preorder Version]
    {authority : Finset (Finset U)}
    (old : AdmittedEnvelope authority S Version)
    (op : HistoryOp D) (targetLineage : D -> U)
    (targetVersion : Version) : Prop :=
  Nonempty
    (StructuralRefinement old op.candidate targetLineage targetVersion)

/-! ## Refinement-certified lease survival -/

/-- The minimal structural portion of a lease certificate.  A concrete
adapter must separately bind and authenticate issuer, authority root, scope,
operation/effect digest, expiry, and signature as applicable.  Consequently,
theorems below establish binding survival, not complete runtime lease
validity. -/
structure Lease (Cell : Type*) (Version : Type uV) where
  issuedVersion : Version
  cell : Cell
  atom : U

namespace Lease

def Valid
    {Version : Type uV} [Preorder Version]
    {authority : Finset (Finset U)}
    {Cell : Type*} [Fintype Cell] [DecidableEq Cell]
    (envelope : AdmittedEnvelope authority Cell Version)
    (lease : Lease (U := U) Cell Version) : Prop :=
  lease.issuedVersion ≤ envelope.version ∧
    lease.cell ∈ CoordinationDecomposition.support envelope.future ∧
    envelope.lineage lease.cell = lease.atom

end Lease

namespace AdmittedEnvelope

/-- Every active fresh-commitment cell in an admitted envelope names an atom
outside the already durable prefix. -/
theorem active_atom_not_durable
    {Version : Type uV} {authority : Finset (Finset U)}
    {Cell : Type*} [Fintype Cell] [DecidableEq Cell]
    (envelope : AdmittedEnvelope authority Cell Version)
    {cell : Cell}
    (hActive : cell ∈ CoordinationDecomposition.support envelope.future) :
    envelope.lineage cell ∉ envelope.durable := by
  obtain ⟨C, hC, hCell⟩ := Finset.mem_biUnion.mp hActive
  have hDisjoint := (envelope.admitted.2 C hC).2.1
  intro hDurable
  exact Finset.disjoint_left.mp hDisjoint hDurable
    (Finset.mem_image.mpr ⟨cell, hCell, rfl⟩)

/-- Lineage is unique inside each feasible configuration, although mutually
exclusive target cells may share one old lineage. -/
theorem lineage_unique_in_configuration
    {Version : Type uV} {authority : Finset (Finset U)}
    {Cell : Type*} [Fintype Cell] [DecidableEq Cell]
    (envelope : AdmittedEnvelope authority Cell Version)
    {C : Finset Cell} (hC : C ∈ envelope.future) :
    Set.InjOn envelope.lineage (C : Set Cell) :=
  (envelope.admitted.2 C hC).1

end AdmittedEnvelope

/-- Evidence that an old checked binding names the parent of one active target
cell.  The binding plus this refinement witness justifies structural survival
at the target version; this layer alone does not authenticate a runtime lease. -/
structure LeaseSurvival
    {Version : Type uV} [Preorder Version]
    {authority : Finset (Finset U)}
    {old : AdmittedEnvelope authority S Version}
    {target : Finset (Finset D)} {targetLineage : D -> U}
    {targetVersion : Version}
    (refinement : StructuralRefinement old target targetLineage targetVersion)
    (lease : Lease (U := U) S Version) where
  sourceValid : lease.Valid old
  targetCell : D
  targetActive : targetCell ∈ CoordinationDecomposition.support target
  parent_eq : refinement.parent targetCell = lease.cell

namespace LeaseSurvival

def targetLease
    {Version : Type uV} [Preorder Version]
    {authority : Finset (Finset U)}
    {old : AdmittedEnvelope authority S Version}
    {target : Finset (Finset D)} {targetLineage : D -> U}
    {targetVersion : Version}
    {refinement : StructuralRefinement old target targetLineage targetVersion}
    {lease : Lease (U := U) S Version}
    (survival : LeaseSurvival refinement lease) :
    Lease (U := U) D Version where
  issuedVersion := lease.issuedVersion
  cell := survival.targetCell
  atom := lease.atom

theorem targetLease_valid
    {Version : Type uV} [Preorder Version]
    {authority : Finset (Finset U)}
    {old : AdmittedEnvelope authority S Version}
    {target : Finset (Finset D)} {targetLineage : D -> U}
    {targetVersion : Version}
    {refinement : StructuralRefinement old target targetLineage targetVersion}
    {lease : Lease (U := U) S Version}
    (survival : LeaseSurvival refinement lease) :
    survival.targetLease.Valid refinement.transportEnvelope := by
  refine ⟨le_trans survival.sourceValid.1 refinement.version_mono,
    survival.targetActive, ?_⟩
  calc
    targetLineage survival.targetCell =
        old.lineage (refinement.parent survival.targetCell) :=
      refinement.lineage_commutes survival.targetCell
    _ = old.lineage lease.cell := by rw [survival.parent_eq]
    _ = lease.atom := survival.sourceValid.2.2

theorem targetLease_atom_not_durable
    {Version : Type uV} [Preorder Version]
    {authority : Finset (Finset U)}
    {old : AdmittedEnvelope authority S Version}
    {target : Finset (Finset D)} {targetLineage : D -> U}
    {targetVersion : Version}
    {refinement : StructuralRefinement old target targetLineage targetVersion}
    {lease : Lease (U := U) S Version}
    (survival : LeaseSurvival refinement lease) :
    lease.atom ∉ old.durable := by
  have hOutside := refinement.transportEnvelope.active_atom_not_durable
    survival.targetActive
  have hBinding :
      refinement.transportEnvelope.lineage survival.targetCell =
        lease.atom := by
    simpa [targetLease, StructuralRefinement.transportEnvelope] using
      (survival.targetLease_valid).2.2
  intro hDurable
  apply hOutside
  rw [hBinding]
  exact hDurable

end LeaseSurvival

/-! ## Exact fixed-family decision boundary for typed operators -/

def HistoryOp.admittedFuture
    (authority : Finset (Finset U)) (durable : Finset U)
    (op : HistoryOp D) (lineage : D -> U) : Finset (Finset D) :=
  safeFuture authority durable op.candidate lineage

/-- The complete generated candidate can be admitted at the current durable
frontier.  This says nothing yet about whether an old certificate can be
inherited structurally. -/
def HistoryOp.FullReadmit
    (op : HistoryOp D) (authority : Finset (Finset U))
    (durable : Finset U) (lineage : D -> U) : Prop :=
  PrefixConfigMorphism authority durable op.candidate lineage

/-- Every required behavior survives exact prefix filtering, but some
optional candidate behavior does not.  Realizing the filtered family requires
a fence, gate cut, or another runtime mechanism; the theorem does not install
that mechanism. -/
def HistoryOp.NeedsMechanism
    (op : HistoryOp D) (authority : Finset (Finset U))
    (durable : Finset U) (lineage : D -> U) : Prop :=
  op.required ⊆ op.admittedFuture authority durable lineage ∧
    ¬op.FullReadmit authority durable lineage

/-- Rejection relative to a fixed authority family, durable prefix, lineage,
generated contract, and *pruning-only* repair scope.  Reissuing identities,
changing lineage, or reauthorizing the workload creates a different problem. -/
def HistoryOp.PruningReject
    (op : HistoryOp D) (authority : Finset (Finset U))
    (durable : Finset U) (lineage : D -> U) : Prop :=
  ¬∃ admitted : Finset (Finset D),
    op.required ⊆ admitted ∧
      admitted ⊆ op.candidate ∧
      PrefixConfigMorphism authority durable admitted lineage

/-- The four proof obligations exposed by the compiler boundary.  `inherit`
reuses an old structural certificate; `readmitOK` recomputes the full check;
`needsMechanism` preserves the required subfamily only after a runtime change;
and `reject` means no pruning-only repair preserves the declared requirements. -/
inductive AdmissionClass where
  | inherit
  | readmitOK
  | needsMechanism
  | reject
deriving DecidableEq, Repr

/-- A proof-free classifier skeleton.  The executable compiler mirrors this
order while emitting witnesses checked independently.  The semantic soundness
theorem below, rather than this noncomputable definition, is the trusted API. -/
noncomputable def HistoryOp.classifyAdmission
    {Version : Type uV} [Preorder Version]
    {authority : Finset (Finset U)}
    (old : AdmittedEnvelope authority S Version)
    (op : HistoryOp D) (lineage : D -> U) (targetVersion : Version) :
    AdmissionClass := by
  classical
  exact
    if op.CanInherit old lineage targetVersion then
      .inherit
    else if op.FullReadmit authority old.durable lineage then
      .readmitOK
    else if op.required ⊆ op.admittedFuture authority old.durable lineage then
      .needsMechanism
    else
      .reject

theorem op_fullReadmit_iff_candidate_eq_admittedFuture
    (authority : Finset (Finset U)) (durable : Finset U)
    (op : HistoryOp D) (lineage : D -> U)
    (hDurable : durable ∈ authority) :
    op.FullReadmit authority durable lineage ↔
      op.candidate = op.admittedFuture authority durable lineage := by
  constructor
  · intro hSafe
    apply Finset.Subset.antisymm
    · exact safeFuture_greatest authority durable op.candidate
        op.candidate lineage (fun _ h => h) hSafe
    · exact safeFuture_subset_candidate
        authority durable op.candidate lineage
  · intro hEq
    unfold HistoryOp.FullReadmit
    rw [hEq]
    exact safeFuture_prefixConfigMorphism
      authority durable op.candidate lineage hDurable

theorem op_canInherit_implies_fullReadmit
    {Version : Type uV} [Preorder Version]
    {authority : Finset (Finset U)}
    {old : AdmittedEnvelope authority S Version}
    (op : HistoryOp D) (lineage : D -> U) (targetVersion : Version)
    (hInherit : op.CanInherit old lineage targetVersion) :
    op.FullReadmit authority old.durable lineage := by
  obtain ⟨refinement⟩ := hInherit
  exact refinement.transports_prefixConfigMorphism

theorem op_fullReadmit_preserves_required
    (authority : Finset (Finset U)) (durable : Finset U)
    (op : HistoryOp D) (lineage : D -> U)
    (opValid : op.Valid) (hDurable : durable ∈ authority)
    (hFull : op.FullReadmit authority durable lineage) :
    op.required ⊆ op.admittedFuture authority durable lineage := by
  have hEq :=
    (op_fullReadmit_iff_candidate_eq_admittedFuture
      authority durable op lineage hDurable).1 hFull
  rw [← hEq]
  exact op.required_subset_candidate opValid

theorem op_required_preservable_iff_exists_admitted
    (authority : Finset (Finset U)) (durable : Finset U)
    (op : HistoryOp D) (lineage : D -> U)
    (hDurable : durable ∈ authority) :
    op.required ⊆ op.admittedFuture authority durable lineage ↔
      ∃ admitted : Finset (Finset D),
        op.required ⊆ admitted ∧
          admitted ⊆ op.candidate ∧
          PrefixConfigMorphism authority durable admitted lineage :=
  required_subset_safeFuture_iff_exists_admitted
    authority durable op.candidate op.required lineage hDurable

theorem op_required_rejected_iff_no_admitted
    (authority : Finset (Finset U)) (durable : Finset U)
    (op : HistoryOp D) (lineage : D -> U)
    (hDurable : durable ∈ authority) :
    ¬op.required ⊆ op.admittedFuture authority durable lineage ↔
      ¬∃ admitted : Finset (Finset D),
        op.required ⊆ admitted ∧
          admitted ⊆ op.candidate ∧
          PrefixConfigMorphism authority durable admitted lineage :=
  not_congr (op_required_preservable_iff_exists_admitted
    authority durable op lineage hDurable)

theorem op_required_rejected_iff_exists_configuration
    (authority : Finset (Finset U)) (durable : Finset U)
    (op : HistoryOp D) (lineage : D -> U) :
    ¬op.required ⊆ op.admittedFuture authority durable lineage ↔
      ∃ C : Finset D,
        C ∈ op.required ∧
          C ∉ op.admittedFuture authority durable lineage := by
  constructor
  · intro hSubset
    by_contra hWitness
    apply hSubset
    intro C hC
    by_contra hNotAdmitted
    exact hWitness ⟨C, hC, hNotAdmitted⟩
  · rintro ⟨C, hRequired, hNotAdmitted⟩ hSubset
    exact hNotAdmitted (hSubset hRequired)

theorem op_no_admitted_iff_exists_required_witness
    (authority : Finset (Finset U)) (durable : Finset U)
    (op : HistoryOp D) (lineage : D -> U)
    (hDurable : durable ∈ authority) :
    (¬∃ admitted : Finset (Finset D),
      op.required ⊆ admitted ∧
        admitted ⊆ op.candidate ∧
        PrefixConfigMorphism authority durable admitted lineage) ↔
      ∃ C : Finset D,
        C ∈ op.required ∧
          C ∉ op.admittedFuture authority durable lineage := by
  rw [← op_required_rejected_iff_no_admitted
    authority durable op lineage hDurable]
  exact op_required_rejected_iff_exists_configuration
    authority durable op lineage

/-- If all required behaviors survive but the full candidate does not, the
computed admitted future is a proper pruning that preserves every declared
requirement.  Installing that pruning is a mechanism change, not an immediate
authorization to execute effects. -/
theorem op_optional_pruning_exists
    (authority : Finset (Finset U)) (durable : Finset U)
    (op : HistoryOp D) (lineage : D -> U)
    (hDurable : durable ∈ authority)
    (hRequired :
      op.required ⊆ op.admittedFuture authority durable lineage)
    (hNotFull :
      ¬op.candidate ⊆ op.admittedFuture authority durable lineage) :
    ∃ admitted : Finset (Finset D),
      op.required ⊆ admitted ∧
        admitted ⊂ op.candidate ∧
        PrefixConfigMorphism authority durable admitted lineage := by
  let admitted := op.admittedFuture authority durable lineage
  have hSubset : admitted ⊆ op.candidate :=
    safeFuture_subset_candidate authority durable op.candidate lineage
  have hNe : admitted ≠ op.candidate := by
    intro hEq
    apply hNotFull
    intro C hC
    simpa [admitted, hEq] using hC
  exact ⟨admitted, hRequired,
    Finset.ssubset_iff_subset_ne.mpr ⟨hSubset, hNe⟩,
    safeFuture_prefixConfigMorphism
      authority durable op.candidate lineage hDurable⟩

/-- Coverage of the three semantic cases.  Coverage alone does not need a
well-formed contract; exclusivity below does. -/
theorem op_admission_cases_exhaustive
    (authority : Finset (Finset U)) (durable : Finset U)
    (op : HistoryOp D) (lineage : D -> U)
    (hDurable : durable ∈ authority) :
    op.FullReadmit authority durable lineage ∨
      op.NeedsMechanism authority durable lineage ∨
      op.PruningReject authority durable lineage := by
  by_cases hFull :
      op.FullReadmit authority durable lineage
  · exact Or.inl hFull
  · by_cases hRequired :
        op.required ⊆ op.admittedFuture authority durable lineage
    · exact Or.inr (Or.inl ⟨hRequired, hFull⟩)
    · exact Or.inr (Or.inr
        ((op_required_rejected_iff_no_admitted
          authority durable op lineage hDurable).1 hRequired))

/-- The three semantic classes are pairwise exclusive for a valid contract. -/
theorem op_admission_classes_pairwise
    (authority : Finset (Finset U)) (durable : Finset U)
    (op : HistoryOp D) (lineage : D -> U)
    (opValid : op.Valid) (hDurable : durable ∈ authority) :
    (op.FullReadmit authority durable lineage ->
      ¬op.NeedsMechanism authority durable lineage ∧
      ¬op.PruningReject authority durable lineage) ∧
    (op.NeedsMechanism authority durable lineage ->
      ¬op.FullReadmit authority durable lineage ∧
      ¬op.PruningReject authority durable lineage) ∧
    (op.PruningReject authority durable lineage ->
      ¬op.FullReadmit authority durable lineage ∧
      ¬op.NeedsMechanism authority durable lineage) := by
  have hRequiredCandidate := op.required_subset_candidate opValid
  have candidateWitness :
      op.FullReadmit authority durable lineage ->
        ∃ admitted : Finset (Finset D),
          op.required ⊆ admitted ∧
            admitted ⊆ op.candidate ∧
            PrefixConfigMorphism authority durable admitted lineage := by
    intro hFull
    exact ⟨op.candidate, hRequiredCandidate, fun _ h => h, hFull⟩
  have filteredWitness :
      op.required ⊆ op.admittedFuture authority durable lineage ->
        ∃ admitted : Finset (Finset D),
          op.required ⊆ admitted ∧
            admitted ⊆ op.candidate ∧
            PrefixConfigMorphism authority durable admitted lineage :=
    (op_required_preservable_iff_exists_admitted
      authority durable op lineage hDurable).1
  refine ⟨?_, ?_, ?_⟩
  · intro hFull
    refine ⟨?_, ?_⟩
    · rintro ⟨_, hNotFull⟩
      exact hNotFull hFull
    · intro hReject
      exact hReject (candidateWitness hFull)
  · rintro ⟨hRequired, hNotFull⟩
    refine ⟨hNotFull, ?_⟩
    intro hReject
    exact hReject (filteredWitness hRequired)
  · intro hReject
    refine ⟨?_, ?_⟩
    · intro hFull
      exact hReject (candidateWitness hFull)
    · rintro ⟨hRequired, _⟩
      exact hReject (filteredWitness hRequired)

/-- Genuine trichotomy for the fixed frontier and pruning-only repair scope:
the cases cover every valid operation and are pairwise exclusive.  Structural
`Inherit` is a distinguished subcase of full readmission.  Validity is
essential: without `required ⊆ candidate`, full admission and pruning-only
rejection can both hold for one malformed contract. -/
theorem op_admission_trichotomy
    (authority : Finset (Finset U)) (durable : Finset U)
    (op : HistoryOp D) (lineage : D -> U)
    (opValid : op.Valid) (hDurable : durable ∈ authority) :
    (op.FullReadmit authority durable lineage ∨
      op.NeedsMechanism authority durable lineage ∨
      op.PruningReject authority durable lineage) ∧
    (op.FullReadmit authority durable lineage ->
      ¬op.NeedsMechanism authority durable lineage ∧
      ¬op.PruningReject authority durable lineage) ∧
    (op.NeedsMechanism authority durable lineage ->
      ¬op.FullReadmit authority durable lineage ∧
      ¬op.PruningReject authority durable lineage) ∧
    (op.PruningReject authority durable lineage ->
      ¬op.FullReadmit authority durable lineage ∧
      ¬op.NeedsMechanism authority durable lineage) :=
  ⟨op_admission_cases_exhaustive authority durable op lineage hDurable,
    op_admission_classes_pairwise
      authority durable op lineage opValid hDurable⟩

/-- The four compiler outcomes have a single sound semantic interpretation.
The first two split full admission according to whether a structural proof is
available; the last two coincide with the pruning boundary above. -/
theorem classifyAdmission_sound
    {Version : Type uV} [Preorder Version]
    {authority : Finset (Finset U)}
    (old : AdmittedEnvelope authority S Version)
    (op : HistoryOp D) (lineage : D -> U) (targetVersion : Version)
    (opValid : op.Valid) :
    match op.classifyAdmission old lineage targetVersion with
    | .inherit =>
        op.CanInherit old lineage targetVersion ∧
          op.required ⊆
            op.admittedFuture authority old.durable lineage
    | .readmitOK =>
        ¬op.CanInherit old lineage targetVersion ∧
          op.FullReadmit authority old.durable lineage ∧
          op.required ⊆
            op.admittedFuture authority old.durable lineage
    | .needsMechanism =>
        op.NeedsMechanism authority old.durable lineage
    | .reject =>
        op.PruningReject authority old.durable lineage := by
  classical
  unfold HistoryOp.classifyAdmission
  by_cases hInherit : op.CanInherit old lineage targetVersion
  · rw [if_pos hInherit]
    exact ⟨hInherit,
      op_fullReadmit_preserves_required
        authority old.durable op lineage opValid old.admitted.1
        (op_canInherit_implies_fullReadmit
          op lineage targetVersion hInherit)⟩
  · rw [if_neg hInherit]
    by_cases hFull : op.FullReadmit authority old.durable lineage
    · rw [if_pos hFull]
      exact ⟨hInherit, hFull,
        op_fullReadmit_preserves_required
          authority old.durable op lineage opValid old.admitted.1 hFull⟩
    · rw [if_neg hFull]
      by_cases hRequired :
          op.required ⊆
            op.admittedFuture authority old.durable lineage
      · simp [hRequired, HistoryOp.NeedsMechanism, hFull]
      · rw [if_neg hRequired]
        exact (op_required_rejected_iff_no_admitted
          authority old.durable op lineage old.admitted.1).1 hRequired

theorem op_admittedFuture_exactFactorization_iff_mustCoordinate
    (authority : Finset (Finset U)) (durable : Finset U)
    (op : HistoryOp D) (lineage : D -> U)
    {B : Type*} [Fintype B] [DecidableEq B]
    (blockOf : D -> B)
    (authorityWF : SourceFamilyWellFormed authority)
    (opValid : op.Valid)
    (hDurable : durable ∈ authority) :
    CoordinationDecomposition.ExactFactorization
        (op.admittedFuture authority durable lineage) blockOf ↔
      ∀ d₁ d₂ : D,
        CoordinationDecomposition.MustCoordinate
            (op.admittedFuture authority durable lineage) d₁ d₂ ->
          blockOf d₁ = blockOf d₂ :=
  safeFuture_exactFactorization_iff_mustCoordinate
    authority durable op.candidate lineage blockOf
    authorityWF (op.candidate_wellFormed opValid) hDurable

/-! ## Choice versus concurrency separation -/

namespace Fixtures

def exclusiveFamily : Finset (Finset Bool) :=
  {∅, {false}, {true}}

theorem exclusiveFamily_wellFormed :
    SourceFamilyWellFormed exclusiveFamily := by
  refine ⟨⟨∅, by simp [exclusiveFamily]⟩,
    by simp [exclusiveFamily], ?_⟩
  intro C C' hC hSubset
  simp only [exclusiveFamily, Finset.mem_insert, Finset.mem_singleton] at hC ⊢
  rcases hC with rfl | rfl | rfl
  · exact Or.inl (Finset.subset_empty.mp hSubset)
  · rcases Finset.subset_singleton_iff.mp hSubset with hEmpty | hSingleton
    · exact Or.inl hEmpty
    · exact Or.inr (Or.inl hSingleton)
  · rcases Finset.subset_singleton_iff.mp hSubset with hEmpty | hSingleton
    · exact Or.inl hEmpty
    · exact Or.inr (Or.inr hSingleton)

theorem singletonFamily_wellFormed (d : Bool) :
    SourceFamilyWellFormed ({∅, {d}} : Finset (Finset Bool)) := by
  refine ⟨⟨∅, by simp⟩, by simp, ?_⟩
  intro C C' hC hSubset
  simp only [Finset.mem_insert, Finset.mem_singleton] at hC ⊢
  rcases hC with rfl | rfl
  · exact Or.inl (Finset.subset_empty.mp hSubset)
  · exact Finset.subset_singleton_iff.mp hSubset

def leftContract : FutureContract Bool where
  may := {∅, {false}}
  required := {∅, {false}}

def rightContract : FutureContract Bool where
  may := {∅, {true}}
  required := {∅, {true}}

theorem leftContract_valid : leftContract.Valid := by
  exact ⟨singletonFamily_wellFormed false,
    singletonFamily_wellFormed false, fun _ h => h⟩

theorem rightContract_valid : rightContract.Valid := by
  exact ⟨singletonFamily_wellFormed true,
    singletonFamily_wellFormed true, fun _ h => h⟩

def choiceOp : HistoryOp Bool :=
  .forkChoice leftContract rightContract

def parallelOp : HistoryOp Bool :=
  .forkParallel leftContract rightContract

theorem choiceOp_valid : choiceOp.Valid :=
  ⟨leftContract_valid, rightContract_valid⟩

theorem parallelOp_valid : parallelOp.Valid :=
  ⟨leftContract_valid, rightContract_valid⟩

theorem choice_candidate_eq : choiceOp.candidate = exclusiveFamily := by
  decide

theorem parallel_candidate_eq_univ :
    parallelOp.candidate = Finset.univ := by
  decide

def exclusiveEnvelope :
    AdmittedEnvelope exclusiveFamily Bool Unit where
  version := ()
  durable := ∅
  future := exclusiveFamily
  lineage := id
  futureWF := exclusiveFamily_wellFormed
  admitted := by
    refine ⟨by simp [exclusiveFamily], ?_⟩
    intro C hC
    refine ⟨?_, by simp, ?_⟩
    · intro d₁ _ d₂ _ hEq
      exact hEq
    · simpa using hC

def choiceRefinement :
    StructuralRefinement exclusiveEnvelope choiceOp.candidate id () where
  version_mono := le_rfl
  targetWF := choiceOp.candidate_wellFormed choiceOp_valid
  parent := id
  mapsFuture := by
    intro C hC
    refine ⟨?_, ?_⟩
    · intro d₁ _ d₂ _ hEq
      exact hEq
    · simpa [choice_candidate_eq] using hC
  lineage_commutes := by simp [exclusiveEnvelope]

/-- The exclusive operator preserves the old envelope structurally. -/
theorem choice_certificate_inherits :
    PrefixConfigMorphism exclusiveFamily ∅ choiceOp.candidate id :=
  choiceRefinement.transports_prefixConfigMorphism

/-- The same arms under a parallel operator jointly expose `{false,true}`.
Lineage commutation forces the identity parent, whose image is forbidden by
the old exclusive family; no structural inheritance certificate exists. -/
theorem parallel_has_no_structural_refinement :
    ¬Nonempty
      (StructuralRefinement exclusiveEnvelope parallelOp.candidate id ()) := by
  rintro ⟨refinement⟩
  have hParent : refinement.parent = id := by
    funext d
    simpa [exclusiveEnvelope] using (refinement.lineage_commutes d).symm
  have hBoth : ({false, true} : Finset Bool) ∈ parallelOp.candidate := by
    rw [parallel_candidate_eq_univ]
    simp
  have hImage := (refinement.mapsFuture {false, true} hBoth).2
  rw [hParent] at hImage
  have hForbidden : ({false, true} : Finset Bool) ∈ exclusiveFamily := by
    simpa using hImage
  have hNotSingleton :
      ({false, true} : Finset Bool) ≠ ({false} : Finset Bool) := by
    decide
  exact hNotSingleton (by simpa [exclusiveFamily] using hForbidden)

theorem choice_full_readmission :
    choiceOp.candidate =
      choiceOp.admittedFuture exclusiveFamily ∅ id := by
  decide

theorem parallel_required_not_admitted :
    ¬parallelOp.required ⊆
      parallelOp.admittedFuture exclusiveFamily ∅ id := by
  decide

/-- Because the joint pair is declared required, no pruning-only repair can
preserve the parallel operation's promise under the exclusive envelope. -/
theorem parallel_has_no_required_preserving_pruning :
    ¬∃ admitted : Finset (Finset Bool),
      parallelOp.required ⊆ admitted ∧
        admitted ⊆ parallelOp.candidate ∧
        PrefixConfigMorphism exclusiveFamily ∅ admitted id :=
  (op_required_rejected_iff_no_admitted
    exclusiveFamily ∅ parallelOp id
    (by simp [exclusiveFamily])).1 parallel_required_not_admitted

/-! The second fixture isolates lease/cell lineage from gate correlation. -/

namespace SharedLease

open ConfigurationCellQuotient.Fixtures

def oldEnvelope : AdmittedEnvelope unitSource Unit Nat where
  version := 0
  durable := ∅
  future := unitSource
  lineage := id
  futureWF := unitSource_wellFormed
  admitted := by
    refine ⟨by simp [unitSource], ?_⟩
    intro C _
    refine ⟨Function.injective_id.injOn, by simp, ?_⟩
    simp [unitSource]

theorem choice_candidate_eq_target :
    choiceOp.candidate = exclusiveTarget := by
  decide

theorem parallel_candidate_eq_target :
    parallelOp.candidate = parallelTarget := by
  decide

def choiceRefinement :
    StructuralRefinement oldEnvelope choiceOp.candidate
      collapseLineage 1 where
  version_mono := by simp [oldEnvelope]
  targetWF := choiceOp.candidate_wellFormed choiceOp_valid
  parent := collapseLineage
  mapsFuture := by
    simpa [choice_candidate_eq_target] using
      exclusive_shared_lineage_is_morphism
  lineage_commutes := by simp [oldEnvelope, collapseLineage]

def oldLease : Lease (U := Unit) Unit Nat where
  issuedVersion := 0
  cell := ()
  atom := ()

theorem oldLease_valid : oldLease.Valid oldEnvelope := by
  refine ⟨by simp [oldLease, oldEnvelope], ?_, by simp [oldLease, oldEnvelope]⟩
  exact Finset.mem_biUnion.mpr
    ⟨{()}, by simp [oldEnvelope, unitSource], by simp⟩

def leftSurvival : LeaseSurvival choiceRefinement oldLease where
  sourceValid := oldLease_valid
  targetCell := false
  targetActive := by decide
  parent_eq := rfl

def rightSurvival : LeaseSurvival choiceRefinement oldLease where
  sourceValid := oldLease_valid
  targetCell := true
  targetActive := by decide
  parent_eq := rfl

theorem left_lease_survives :
    leftSurvival.targetLease.Valid choiceRefinement.transportEnvelope :=
  leftSurvival.targetLease_valid

theorem right_lease_survives :
    rightSurvival.targetLease.Valid choiceRefinement.transportEnvelope :=
  rightSurvival.targetLease_valid

/-- The old lease can be referenced from either exclusive future.  The target
cells are distinct but retain the same issued atom and version. -/
theorem alternatives_share_surviving_lease :
    leftSurvival.targetLease.atom = rightSurvival.targetLease.atom ∧
      leftSurvival.targetLease.issuedVersion =
        rightSurvival.targetLease.issuedVersion ∧
      leftSurvival.targetLease.cell ≠ rightSurvival.targetLease.cell := by
  decide

theorem alternatives_cannot_coexist :
    ({false, true} : Finset Bool) ∉ choiceOp.candidate := by
  decide

theorem choice_split_controllers_not_exact :
    ¬CoordinationDecomposition.ExactFactorization
      choiceOp.candidate id := by
  unfold CoordinationDecomposition.ExactFactorization
  decide

theorem choice_shared_controller_exact :
    CoordinationDecomposition.ExactFactorization
      choiceOp.candidate (fun _ => ()) := by
  unfold CoordinationDecomposition.ExactFactorization
  decide

/-- Changing only the typed operator from exclusive choice to parallel
co-durability makes the shared lineage locally noninjective. -/
theorem parallel_has_no_shared_lease_refinement :
    ¬Nonempty
      (StructuralRefinement oldEnvelope parallelOp.candidate
        collapseLineage 1) := by
  rintro ⟨refinement⟩
  apply parallel_shared_lineage_is_not_morphism
  simpa [parallel_candidate_eq_target] using refinement.mapsFuture

theorem parallel_shared_required_not_admitted :
    ¬parallelOp.required ⊆
      parallelOp.admittedFuture unitSource ∅ collapseLineage := by
  decide

theorem parallel_shared_lease_has_no_pruning_repair :
    ¬∃ admitted : Finset (Finset Bool),
      parallelOp.required ⊆ admitted ∧
        admitted ⊆ parallelOp.candidate ∧
        PrefixConfigMorphism unitSource ∅ admitted collapseLineage :=
  (op_required_rejected_iff_no_admitted
    unitSource ∅ parallelOp collapseLineage
    (by simp [unitSource])).1 parallel_shared_required_not_admitted

end SharedLease

end Fixtures

end AuthorityContinuity.TypedHistoryAdmission
