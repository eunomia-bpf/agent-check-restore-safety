import Mathlib

/-!
# Configuration cells and additive transport

This module isolates a classical configuration-morphism bridge.  It is a
supporting mathematical fact, not the novelty claim of the agent-history
work: universal preservation of every finite additive capacity invariant is
equivalent to mapping each feasible target configuration injectively into a
feasible source configuration.

The target sum ranges over semantic redemption cells.  Multiple API handles
that share one linearization cell must therefore be quotiented before they
become elements of `D`; counting those handles as separate `D` values would
model independent redemption state rather than aliases.
-/

namespace AuthorityContinuity.ConfigurationCellQuotient

open scoped BigOperators

-- The finite interfaces are intentional even where an individual lemma
-- generalizes beyond them.
set_option linter.unusedSectionVars false

universe uU uD uH

variable {U : Type uU} {D : Type uD}
variable [Fintype U] [DecidableEq U] [Fintype D] [DecidableEq D]

/-! ## Configuration families and additive safety -/

/-- The source configurations form a nonempty downward-closed finite family.
`empty_mem` is recorded explicitly because it is used at the zero-cardinality
boundary of the necessity proof. -/
structure SourceFamilyWellFormed (source : Finset (Finset U)) : Prop where
  nonempty : source.Nonempty
  empty_mem : (∅ : Finset U) ∈ source
  downwardClosed :
    ∀ {C C' : Finset U}, C ∈ source -> C' ⊆ C -> C' ∈ source

/-- Every feasible source configuration respects additive capacity `k`. -/
def SourceSafe (source : Finset (Finset U)) (w : U -> Nat) (k : Nat) : Prop :=
  ∀ C ∈ source, (∑ u ∈ C, w u) <= k

/-- Every feasible target configuration respects the same capacity after
pulling weights back along `ell`.  The sum is over target cells themselves;
it deliberately does not deduplicate `C.image ell` before summing. -/
def TargetSafe (target : Finset (Finset D)) (ell : D -> U)
    (w : U -> Nat) (k : Nat) : Prop :=
  ∀ C ∈ target, (∑ d ∈ C, w (ell d)) <= k

/-- All natural-number additive capacity invariants valid at the source are
transported to the target. -/
def UniversalAdditiveTransport (source : Finset (Finset U))
    (target : Finset (Finset D)) (ell : D -> U) : Prop :=
  ∀ (w : U -> Nat) (k : Nat),
    SourceSafe source w k -> TargetSafe target ell w k

/-- A target configuration is mapped without a within-configuration collision
to a configuration admitted by the source family. -/
def ConfigMorphism (source : Finset (Finset U))
    (target : Finset (Finset D)) (ell : D -> U) : Prop :=
  ∀ C ∈ target,
    Set.InjOn ell (C : Set D) ∧ C.image ell ∈ source

/-! ## Explicit binary witnesses for necessity -/

/-- A binary weight concentrated at one source unit. -/
def pointWeight (u0 : U) (u : U) : Nat :=
  if u0 = u then 1 else 0

/-- A binary weight selecting a finite set of source units. -/
def indicatorWeight (I : Finset U) (u : U) : Nat :=
  if u ∈ I then 1 else 0

theorem sourceSafe_pointWeight (source : Finset (Finset U)) (u0 : U) :
    SourceSafe source (pointWeight u0) 1 := by
  intro C _
  by_cases h : u0 ∈ C <;> simp [pointWeight, h]

theorem sum_indicatorWeight_eq_card_inter (C I : Finset U) :
    (∑ u ∈ C, indicatorWeight I u) = (C ∩ I).card := by
  simp [indicatorWeight]

/-- If two distinct target cells in one feasible configuration have the same
lineage, the point weight at that lineage is source-safe at capacity one but
not target-safe. -/
theorem collision_capacity_one_witness
    (source : Finset (Finset U)) (target : Finset (Finset D))
    (ell : D -> U) {C : Finset D} (hC : C ∈ target)
    {d0 d1 : D} (hd0 : d0 ∈ C) (hd1 : d1 ∈ C)
    (hne : d0 ≠ d1) (hlineage : ell d0 = ell d1) :
    ∃ w : U -> Nat,
      SourceSafe source w 1 ∧ ¬TargetSafe target ell w 1 := by
  refine ⟨pointWeight (ell d0), sourceSafe_pointWeight source (ell d0), ?_⟩
  intro hTarget
  have hPair : ({d0, d1} : Finset D) ⊆ C := by
    intro d hd
    simp only [Finset.mem_insert, Finset.mem_singleton] at hd
    rcases hd with rfl | rfl
    · exact hd0
    · exact hd1
  have hLower :
      (∑ d ∈ ({d0, d1} : Finset D), pointWeight (ell d0) (ell d)) <=
        ∑ d ∈ C, pointWeight (ell d0) (ell d) :=
    Finset.sum_le_sum_of_subset hPair
  have hPairSum :
      (∑ d ∈ ({d0, d1} : Finset D), pointWeight (ell d0) (ell d)) = 2 := by
    rw [Finset.sum_insert (by simpa using hne), Finset.sum_singleton]
    simp [pointWeight, hlineage]
  have hCapacity := hTarget C hC
  omega

/-- If an injective target image is not a source configuration, its indicator
weight is source-safe at capacity `|image|-1` but not target-safe.  Downward
closure is exactly what turns containment of the image in a source
configuration into membership of the image itself. -/
theorem forbidden_image_indicator_witness
    (source : Finset (Finset U)) (target : Finset (Finset D))
    (ell : D -> U) (wf : SourceFamilyWellFormed source)
    {C : Finset D} (hC : C ∈ target)
    (hinj : Set.InjOn ell (C : Set D))
    (hForbidden : C.image ell ∉ source) :
    ∃ w : U -> Nat,
      SourceSafe source w ((C.image ell).card - 1) ∧
        ¬TargetSafe target ell w ((C.image ell).card - 1) := by
  let I : Finset U := C.image ell
  have hINonempty : I.Nonempty := by
    by_contra hEmpty
    have hIEmpty : I = ∅ := Finset.not_nonempty_iff_eq_empty.mp hEmpty
    exact hForbidden (by simpa [I, hIEmpty] using wf.empty_mem)
  refine ⟨indicatorWeight I, ?_, ?_⟩
  · intro S hS
    change (∑ u ∈ S, indicatorWeight I u) <= I.card - 1
    rw [sum_indicatorWeight_eq_card_inter]
    have hNotSubset : ¬I ⊆ S := by
      intro hSubset
      exact hForbidden (by
        change I ∈ source
        exact wf.downwardClosed hS hSubset)
    have hStrict : S ∩ I ⊂ I := by
      refine Finset.ssubset_iff_subset_ne.mpr ⟨Finset.inter_subset_right, ?_⟩
      intro hEq
      apply hNotSubset
      intro u hu
      have : u ∈ S ∩ I := by simpa [hEq] using hu
      exact Finset.mem_inter.mp this |>.1
    have hCard : (S ∩ I).card < I.card := Finset.card_lt_card hStrict
    exact Nat.le_pred_of_lt hCard
  · intro hTarget
    have hCapacity := hTarget C hC
    change (∑ d ∈ C, indicatorWeight I (ell d)) <= I.card - 1 at hCapacity
    have hTargetSum :
        (∑ d ∈ C, indicatorWeight I (ell d)) = C.card := by
      calc
        (∑ d ∈ C, indicatorWeight I (ell d)) = ∑ _d ∈ C, 1 := by
          apply Finset.sum_congr rfl
          intro d hd
          have hell : ell d ∈ I := by
            exact Finset.mem_image.mpr ⟨d, hd, rfl⟩
          simp [indicatorWeight, hell]
        _ = C.card := by simp
    have hImageCard : I.card = C.card := by
      exact Finset.card_image_of_injOn hinj
    have hPositive : 0 < I.card := Finset.card_pos.mpr hINonempty
    rw [hTargetSum] at hCapacity
    rw [hImageCard] at hCapacity
    rw [hImageCard] at hPositive
    omega

/-! ## Exact configuration-morphism bridge -/

theorem configMorphism_implies_universalAdditiveTransport
    (source : Finset (Finset U)) (target : Finset (Finset D))
    (ell : D -> U) (hMorphism : ConfigMorphism source target ell) :
    UniversalAdditiveTransport source target ell := by
  intro w k hSource C hC
  obtain ⟨hinj, hImage⟩ := hMorphism C hC
  have hBound := hSource (C.image ell) hImage
  rw [Finset.sum_image hinj] at hBound
  exact hBound

theorem universalAdditiveTransport_implies_configMorphism
    (source : Finset (Finset U)) (target : Finset (Finset D))
    (ell : D -> U) (wf : SourceFamilyWellFormed source)
    (hTransport : UniversalAdditiveTransport source target ell) :
    ConfigMorphism source target ell := by
  intro C hC
  have hinj : Set.InjOn ell (C : Set D) := by
    intro d0 hd0 d1 hd1 hlineage
    by_contra hne
    obtain ⟨w, hSource, hTargetFailure⟩ :=
      collision_capacity_one_witness source target ell hC hd0 hd1 hne hlineage
    exact hTargetFailure (hTransport w 1 hSource)
  refine ⟨hinj, ?_⟩
  by_contra hForbidden
  obtain ⟨w, hSource, hTargetFailure⟩ :=
    forbidden_image_indicator_witness source target ell wf hC hinj hForbidden
  exact hTargetFailure (hTransport w ((C.image ell).card - 1) hSource)

/-- Universal additive transport is exactly the local configuration-morphism
condition. -/
theorem universalAdditiveTransport_iff_configMorphism
    (source : Finset (Finset U)) (target : Finset (Finset D))
    (ell : D -> U) (wf : SourceFamilyWellFormed source) :
    UniversalAdditiveTransport source target ell ↔
      ConfigMorphism source target ell := by
  constructor
  · exact universalAdditiveTransport_implies_configMorphism source target ell wf
  · exact configMorphism_implies_universalAdditiveTransport source target ell

/-! ## Executable fixtures -/

namespace Fixtures

/-- Quotienting handles by their shared semantic cell.  This helper is where
alias multiplicity disappears; `ConfigMorphism` subsequently reasons about
the resulting cells, not the handles. -/
def semanticCells {Handle : Type uH} {Cell : Type*} [DecidableEq Cell]
    (handles : Finset Handle) (cellOf : Handle -> Cell) : Finset Cell :=
  handles.image cellOf

/-- Two handles for one shared cell produce one semantic cell. -/
theorem two_handles_one_cell :
    (semanticCells ({false, true} : Finset Bool) (fun _ => ())).card = 1 := by
  decide

def unitSource : Finset (Finset Unit) :=
  Finset.univ

def collapseLineage (_ : Bool) : Unit := ()

/-- Either target cell may be used, but no feasible configuration contains
both. -/
def exclusiveTarget : Finset (Finset Bool) :=
  {∅, {false}, {true}}

/-- Both independent target cells may occur in one configuration. -/
def parallelTarget : Finset (Finset Bool) :=
  insert {false, true} exclusiveTarget

theorem unitSource_wellFormed : SourceFamilyWellFormed unitSource := by
  refine ⟨⟨∅, by simp [unitSource]⟩, by simp [unitSource], ?_⟩
  intro C C' _ _
  simp [unitSource]

/-- Two exclusive target alternatives may share one source lineage because
injectivity is required per feasible configuration, not globally. -/
theorem exclusive_shared_lineage_is_morphism :
    ConfigMorphism unitSource exclusiveTarget collapseLineage := by
  intro C hC
  simp [exclusiveTarget] at hC
  rcases hC with rfl | rfl | rfl
  all_goals simp [unitSource, collapseLineage]

theorem exclusive_shared_lineage_transports :
    UniversalAdditiveTransport unitSource exclusiveTarget collapseLineage :=
  (universalAdditiveTransport_iff_configMorphism
    unitSource exclusiveTarget collapseLineage unitSource_wellFormed).2
      exclusive_shared_lineage_is_morphism

theorem parallel_shared_lineage_is_not_morphism :
    ¬ConfigMorphism unitSource parallelTarget collapseLineage := by
  intro hMorphism
  obtain ⟨hinj, _⟩ := hMorphism {false, true} (by
    simp [parallelTarget])
  have hFalseEqTrue : false = true := hinj (by simp) (by simp) rfl
  contradiction

/-- Capacity one is the concrete binary counterexample for the parallel
collision. -/
theorem parallel_capacity_one_counterexample :
    SourceSafe unitSource (fun _ => 1) 1 ∧
      ¬TargetSafe parallelTarget collapseLineage (fun _ => 1) 1 := by
  constructor
  · intro C _
    simpa using Finset.card_le_one_of_subsingleton C
  · intro hTarget
    have hCapacity := hTarget {false, true} (by simp [parallelTarget])
    norm_num at hCapacity

theorem parallel_shared_lineage_does_not_transport :
    ¬UniversalAdditiveTransport unitSource parallelTarget collapseLineage := by
  intro hTransport
  exact parallel_shared_lineage_is_not_morphism
    ((universalAdditiveTransport_iff_configMorphism
      unitSource parallelTarget collapseLineage unitSource_wellFormed).1 hTransport)

def boolConfigurations : Finset (Finset Bool) :=
  Finset.univ

theorem boolConfigurations_wellFormed :
    SourceFamilyWellFormed boolConfigurations := by
  refine ⟨⟨∅, by simp [boolConfigurations]⟩, by simp [boolConfigurations], ?_⟩
  intro C C' _ _
  simp [boolConfigurations]

/-- Distinct target cells mapped to distinct source units preserve even the
parallel configuration. -/
theorem distinct_cells_distinct_units_is_morphism :
    ConfigMorphism boolConfigurations boolConfigurations id := by
  intro C _
  exact ⟨Function.injective_id.injOn, by simp [boolConfigurations]⟩

theorem distinct_cells_distinct_units_transport :
    UniversalAdditiveTransport boolConfigurations boolConfigurations id :=
  (universalAdditiveTransport_iff_configMorphism
    boolConfigurations boolConfigurations id boolConfigurations_wellFormed).2
      distinct_cells_distinct_units_is_morphism

end Fixtures

end AuthorityContinuity.ConfigurationCellQuotient
