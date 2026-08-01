import AuthorityContinuity.Transfer
import Mathlib.Data.Fintype.Powerset

/-!
# Checked explicit merge targets

Canonical Fork and Restore derive their target structure from a fixed builder.
Merge is intentionally different: an adapter proposes an explicit finite
contract and branch-epoch map.  This module checks those structural atoms
one by one, then keeps simulation admission separate from direct target-AC
admission.  Neither mode accepts a logical target-WF certificate.
-/

namespace AuthorityContinuity

universe uC uI uB uG uO

/-- Explicit finite data proposed by a Merge adapter.  Capacity, immutable
claim metadata, grant epochs, tickets, and receipts are not fields because
the builder preserves them definitionally. -/
structure MergeDescriptor (Claim : Type uI) (Branch : Type uB) where
  allowed : Finset (Finset Branch)
  branchEpoch : Branch → EpochStatus
  transfer : Transfer Claim Branch

namespace MergeDescriptor

variable {Coord : Type uC} {Claim : Type uI} {Branch : Type uB}
variable {Grant : Type uG} {Operation : Type uO}
variable [Fintype Coord] [DecidableEq Coord]
variable [Fintype Claim] [DecidableEq Claim]
variable [Fintype Branch] [DecidableEq Branch]
variable [DecidableEq Grant] [DecidableEq Operation]

/-- The unique lifecycle target denoted by an explicit Merge descriptor. -/
def target
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (d : MergeDescriptor Claim Branch) :
    LifecycleState Coord Claim Branch Grant Operation where
  auth := d.transfer.targetCore A d.allowed
  grantOf := A.grantOf
  branchEpoch := d.branchEpoch
  grantEpoch := A.grantEpoch
  tickets := A.tickets
  receipts := A.receipts

end MergeDescriptor

namespace MergeCheck

variable {Coord : Type uC} {Claim : Type uI} {Branch : Type uB}
variable {Grant : Type uG} {Operation : Type uO}
variable [Fintype Coord] [DecidableEq Coord]
variable [Fintype Claim] [DecidableEq Claim]
variable [Fintype Branch] [DecidableEq Branch]
variable [DecidableEq Grant] [DecidableEq Operation]

def empty
    (d : MergeDescriptor Claim Branch) : Bool :=
  decide (∅ ∈ d.allowed)

def downward
    (d : MergeDescriptor Claim Branch) : Bool :=
  finiteAll d.allowed fun C =>
    finiteAll Finset.univ fun C' => decide (C' ⊆ C → C' ∈ d.allowed)

def support
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (d : MergeDescriptor Claim Branch) : Bool :=
  finiteAll Finset.univ fun c =>
    match d.transfer.targetStatus A c with
    | .tentative b => decide (∃ C ∈ d.allowed, b ∈ C)
    | _ => true

def configurationOpen
    (d : MergeDescriptor Claim Branch) : Bool :=
  finiteAll d.allowed fun C =>
    finiteAll C fun b => decide (d.branchEpoch b = .open)

def ownerOpen
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (d : MergeDescriptor Claim Branch) : Bool :=
  finiteAll Finset.univ fun c =>
    match d.transfer.targetStatus A c with
    | .tentative b => decide (d.branchEpoch b = .open)
    | _ => true

def grantOpen
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (d : MergeDescriptor Claim Branch) : Bool :=
  finiteAll Finset.univ fun c =>
    match d.transfer.targetStatus A c with
    | .tentative _ => decide (A.grantEpoch (A.grantOf c) = .open)
    | _ => true

def activeExact
    (d : MergeDescriptor Claim Branch) : Bool :=
  finiteAll Finset.univ fun b =>
    decide (d.branchEpoch b = .open ↔ ∃ C ∈ d.allowed, b ∈ C)

/-- Executable epoch-advance relation. -/
def epochAdvances (source target : EpochStatus) : Bool :=
  match source, target with
  | .unissued, _ => true
  | .open, .open | .open, .closed | .closed, .closed => true
  | _, _ => false

def epochMonotone
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (d : MergeDescriptor Claim Branch) : Bool :=
  finiteAll Finset.univ fun b =>
    epochAdvances (A.branchEpoch b) (d.branchEpoch b)

/-- Atomized structural checker for an explicit Merge target. -/
def structural
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (d : MergeDescriptor Claim Branch) : Bool :=
  empty d && downward d && support A d && configurationOpen d &&
    ownerOpen A d && grantOpen A d && activeExact d &&
    epochMonotone A d && d.transfer.checkTransferCore A

end MergeCheck

/-- Logical output of the explicit atomized Merge structure checker. -/
structure MergeStructureValid
    {Coord : Type uC} {Claim : Type uI} {Branch : Type uB}
    {Grant : Type uG} {Operation : Type uO}
    [Fintype Coord] [DecidableEq Coord]
    [Fintype Claim] [DecidableEq Claim]
    [Fintype Branch] [DecidableEq Branch]
    [DecidableEq Grant]
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (d : MergeDescriptor Claim Branch) : Prop where
  empty_mem : ∅ ∈ d.allowed
  downward : ∀ ⦃C C' : Finset Branch⦄,
    C ∈ d.allowed → C' ⊆ C → C' ∈ d.allowed
  supported : ∀ c b, d.transfer.targetStatus A c = .tentative b →
    ∃ C ∈ d.allowed, b ∈ C
  configuration_open : ∀ C ∈ d.allowed, ∀ b ∈ C,
    d.branchEpoch b = .open
  owner_open : ∀ c b, d.transfer.targetStatus A c = .tentative b →
    d.branchEpoch b = .open
  grant_open : ∀ c b, d.transfer.targetStatus A c = .tentative b →
    A.grantEpoch (A.grantOf c) = .open
  active_exact : ∀ b, d.branchEpoch b = .open ↔
    ∃ C ∈ d.allowed, b ∈ C
  branch_epoch_mono : ∀ b,
    (A.branchEpoch b).Advances (d.branchEpoch b)
  transfer : d.transfer.CoreValid A

namespace MergeCheck

variable {Coord : Type uC} {Claim : Type uI} {Branch : Type uB}
variable {Grant : Type uG} {Operation : Type uO}
variable [Fintype Coord] [DecidableEq Coord]
variable [Fintype Claim] [DecidableEq Claim]
variable [Fintype Branch] [DecidableEq Branch]
variable [DecidableEq Grant] [DecidableEq Operation]

/-- Soundness of the atomized structure checker.  This theorem assembles
finite checked atoms; it does not decide `WF`, `LWF`, or `AC` wholesale. -/
theorem checkMergeStructure_sound
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (d : MergeDescriptor Claim Branch)
    (h : structural A d = true) : MergeStructureValid A d := by
  simp only [structural, Bool.and_eq_true] at h
  rcases h with ⟨⟨⟨⟨⟨⟨⟨⟨hempty, hdown⟩, hsupp⟩, hconf⟩,
    howner⟩, hgrant⟩, hactive⟩, hepoch⟩, htransfer⟩
  refine ⟨of_decide_eq_true hempty, ?_, ?_, ?_, ?_, ?_, ?_, ?_,
    Transfer.checkTransferCore_sound A d.transfer htransfer⟩
  · intro C C' hC hsub
    have hCcheck := (finiteAll_eq_true d.allowed _).mp hdown C hC
    have hC' := (finiteAll_eq_true Finset.univ _).mp hCcheck C'
      (Finset.mem_univ C')
    exact (of_decide_eq_true hC') hsub
  · intro c b hs
    have hc := (finiteAll_eq_true Finset.univ _).mp hsupp c
      (Finset.mem_univ c)
    simp [hs] at hc
    exact hc
  · intro C hC b hb
    have hCcheck := (finiteAll_eq_true d.allowed _).mp hconf C hC
    have hbcheck := (finiteAll_eq_true C _).mp hCcheck b hb
    exact of_decide_eq_true hbcheck
  · intro c b hs
    have hc := (finiteAll_eq_true Finset.univ _).mp howner c
      (Finset.mem_univ c)
    simp [hs] at hc
    exact hc
  · intro c b hs
    have hc := (finiteAll_eq_true Finset.univ _).mp hgrant c
      (Finset.mem_univ c)
    simp [hs] at hc
    exact hc
  · intro b
    have hb := (finiteAll_eq_true Finset.univ _).mp hactive b
      (Finset.mem_univ b)
    exact of_decide_eq_true hb
  · intro b
    have hb := (finiteAll_eq_true Finset.univ _).mp hepoch b
      (Finset.mem_univ b)
    cases hs : A.branchEpoch b <;> cases ht : d.branchEpoch b <;>
      simp [epochAdvances, EpochStatus.Advances, hs, ht] at hb ⊢

end MergeCheck

namespace MergeCheck

variable {Coord : Type uC} {Claim : Type uI} {Branch : Type uB}
variable {Grant : Type uG} {Operation : Type uO}
variable [Fintype Coord] [DecidableEq Coord]
variable [Fintype Claim] [DecidableEq Claim]
variable [Fintype Branch] [DecidableEq Branch]
variable [DecidableEq Grant] [DecidableEq Operation]

/-- Finite check of zero preservation and monotonicity for an explicit Merge
projection. -/
def monoZero (project : Finset Branch → Finset Branch) : Bool :=
  decide (project ∅ = ∅) &&
  finiteAll Finset.univ fun C =>
    finiteAll Finset.univ fun D => decide (C ⊆ D → project C ⊆ project D)

/-- Finite check of the paper's per-configuration simulation formula. -/
def simulation
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (d : MergeDescriptor Claim Branch)
    (project : Finset Branch → Finset Branch) : Bool :=
  let target := d.target A
  finiteAll d.allowed fun C =>
    decide (project C ∈ A.auth.allowed) &&
    finiteAll Finset.univ fun k => decide
      (target.auth.durableLoad k + target.auth.conditionalLoad C k ≤
       A.auth.durableLoad k + A.auth.conditionalLoad (project C) k)

/-- Simulation-mode Merge never invokes the target AC checker. -/
def simulationAdmission
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (d : MergeDescriptor Claim Branch)
    (project : Finset Branch → Finset Branch) : Bool :=
  structural A d && monoZero project && simulation A d project

/-- Direct-admission Merge has no projection premise and visibly invokes the
existing sound target AC checker. -/
def directAdmission
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (d : MergeDescriptor Claim Branch) : Bool :=
  structural A d && checkAC (d.target A).auth

theorem checkMergeMonoZero_sound
    (project : Finset Branch → Finset Branch)
    (h : monoZero project = true) :
    project ∅ = ∅ ∧
      ∀ ⦃C D : Finset Branch⦄, C ⊆ D → project C ⊆ project D := by
  rw [monoZero, Bool.and_eq_true] at h
  refine ⟨of_decide_eq_true h.1, ?_⟩
  intro C D hCD
  have hC := (finiteAll_eq_true Finset.univ _).mp h.2 C
    (Finset.mem_univ C)
  have hD := (finiteAll_eq_true Finset.univ _).mp hC D
    (Finset.mem_univ D)
  exact (of_decide_eq_true hD) hCD

theorem checkMergeSimulation_sound
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (d : MergeDescriptor Claim Branch)
    (project : Finset Branch → Finset Branch)
    (h : simulation A d project = true) :
    ∀ C ∈ d.allowed,
      project C ∈ A.auth.allowed ∧
      ∀ k,
        (d.target A).auth.durableLoad k +
            (d.target A).auth.conditionalLoad C k ≤
          A.auth.durableLoad k +
            A.auth.conditionalLoad (project C) k := by
  intro C hC
  have hrow := (finiteAll_eq_true d.allowed _).mp h C hC
  rw [Bool.and_eq_true] at hrow
  refine ⟨of_decide_eq_true hrow.1, ?_⟩
  intro k
  have hk := (finiteAll_eq_true Finset.univ _).mp hrow.2 k
    (Finset.mem_univ k)
  exact of_decide_eq_true hk

end MergeCheck

namespace MergeDescriptor

variable {Coord : Type uC} {Claim : Type uI} {Branch : Type uB}
variable {Grant : Type uG} {Operation : Type uO}
variable [Fintype Coord] [DecidableEq Coord]
variable [Fintype Claim] [DecidableEq Claim]
variable [Fintype Branch] [DecidableEq Branch]
variable [DecidableEq Grant] [DecidableEq Operation]

@[simp] theorem target_opClaim
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (d : MergeDescriptor Claim Branch) (e : Operation) :
    (d.target A).opClaim e = A.opClaim e := rfl

/-- The atomized structure result plus preserved durable history assembles the
target lifecycle invariant and exact active-branch invariant. -/
theorem target_lwf_active
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (d : MergeDescriptor Claim Branch)
    (hWF : A.LWF) (hvalid : MergeStructureValid A d) :
    (d.target A).LWF ∧ (d.target A).ActiveExact := by
  constructor
  · refine ⟨⟨hvalid.empty_mem, hvalid.downward, ?_⟩,
      hvalid.configuration_open, hvalid.owner_open, hvalid.grant_open,
      ?_, ?_, ?_⟩
    · intro c b hs
      exact hvalid.supported c b hs
    · exact hWF.ticket_receipt_disjoint
    · intro e c he
      have hsource : A.opClaim e = some c := by
        simpa using he
      have hdurable := hWF.bound_durable e c hsource
      change d.transfer.targetStatus A c = .durable
      exact (Transfer.targetStatus_durable_iff A d.transfer
        hvalid.transfer c).2 hdurable
    · intro e e' c he he'
      apply hWF.binding_injective e e' c
      · simpa using he
      · simpa using he'
  · intro b
    exact hvalid.active_exact b

theorem target_epoch_mono
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (d : MergeDescriptor Claim Branch)
    (hvalid : MergeStructureValid A d) : A.EpochMonotone (d.target A) := by
  exact ⟨hvalid.branch_epoch_mono,
    fun g => EpochStatus.Advances.refl (A.grantEpoch g)⟩

theorem target_terminal_mono
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (d : MergeDescriptor Claim Branch)
    (hvalid : MergeStructureValid A d) : A.TerminalMonotone (d.target A) := by
  intro c hc
  exact Transfer.targetStatus_terminal_of_terminal
    A d.transfer hvalid.transfer c hc

end MergeDescriptor

/-- Simulation-mode Merge derives target AC from source AC and checked
configuration simulation; it never invokes `checkAC target`. -/
theorem simulation_merge_preserves_wf_ac
    {Coord : Type uC} {Claim : Type uI} {Branch : Type uB}
    {Grant : Type uG} {Operation : Type uO}
    [Fintype Coord] [DecidableEq Coord]
    [Fintype Claim] [DecidableEq Claim]
    [Fintype Branch] [DecidableEq Branch]
    [DecidableEq Grant] [DecidableEq Operation]
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (d : MergeDescriptor Claim Branch)
    (project : Finset Branch → Finset Branch)
    (hWF : A.LWF) (hAC : AC A.auth)
    (hcheck : MergeCheck.simulationAdmission A d project = true) :
    (d.target A).LWF ∧ AC (d.target A).auth ∧
      (d.target A).ActiveExact := by
  have hparts : (MergeCheck.structural A d = true ∧
      MergeCheck.monoZero project = true) ∧
      MergeCheck.simulation A d project = true := by
    simpa [MergeCheck.simulationAdmission, Bool.and_eq_true] using hcheck
  have hstructure := MergeCheck.checkMergeStructure_sound A d hparts.1.1
  have hlifecycle := d.target_lwf_active A hWF hstructure
  have hsimulation := MergeCheck.checkMergeSimulation_sound
    A d project hparts.2
  refine ⟨hlifecycle.1, ?_, hlifecycle.2⟩
  exact simulation_preserves_ac A.auth (d.target A).auth project rfl hAC
    hsimulation

/-- Direct-admission Merge is a visibly separate mode: it uses the same
structure checker and the existing sound target AC checker, with no
projection or simulation premise. -/
theorem direct_merge_preserves_wf_ac
    {Coord : Type uC} {Claim : Type uI} {Branch : Type uB}
    {Grant : Type uG} {Operation : Type uO}
    [Fintype Coord] [DecidableEq Coord]
    [Fintype Claim] [DecidableEq Claim]
    [Fintype Branch] [DecidableEq Branch]
    [DecidableEq Grant] [DecidableEq Operation]
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (d : MergeDescriptor Claim Branch)
    (hWF : A.LWF)
    (hcheck : MergeCheck.directAdmission A d = true) :
    (d.target A).LWF ∧ AC (d.target A).auth ∧
      (d.target A).ActiveExact := by
  have hparts : MergeCheck.structural A d = true ∧
      checkAC (d.target A).auth = true := by
    simpa [MergeCheck.directAdmission, Bool.and_eq_true] using hcheck
  have hstructure := MergeCheck.checkMergeStructure_sound A d hparts.1
  have hlifecycle := d.target_lwf_active A hWF hstructure
  exact ⟨hlifecycle.1, checkAC_sound (d.target A).auth hparts.2,
    hlifecycle.2⟩

end AuthorityContinuity
