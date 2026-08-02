import AuthorityContinuity.PlanInvariantTransport

/-!
# Computed plan transport for checked Merge

An explicit `MergeDescriptor` supplies an actual lifecycle target whose
authority projection is definitionally `d.transfer.targetCore A d.allowed`.
This module reuses the generic transfer core to compute the only admitted plan
target: increment the version, transport roots through `rho`, and compute the
child batch.  Admission contains executable lifecycle and owner/root checks;
it never accepts a caller-provided target plan or target validity proposition.
-/

namespace AuthorityContinuity.PlanInvariant

open AuthorityContinuity LifecycleState

universe uC uI uB uG uO uS

variable {Coord : Type uC} {Claim : Type uI} {Branch : Type uB}
variable {Grant : Type uG} {Operation : Type uO} {Slot : Type uS}
variable [Fintype Coord] [DecidableEq Coord]
variable [Fintype Claim] [LinearOrder Claim]
variable [Fintype Branch] [LinearOrder Branch]
variable [DecidableEq Grant] [Fintype Operation] [DecidableEq Operation]
variable [Fintype Slot] [LinearOrder Slot]

namespace PlanData

/-- The unique computed plan target for either Merge admission mode. -/
def afterMerge
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (d : MergeDescriptor Claim Branch) :
    PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot) :=
  p.afterCanonical d.transfer

@[simp] theorem afterMerge_version
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (d : MergeDescriptor Claim Branch) :
    (p.afterMerge d).version = p.version + 1 := rfl

@[simp] theorem afterMerge_rootSlot
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (d : MergeDescriptor Claim Branch) :
    (p.afterMerge d).rootSlot =
      PlanRootTransport.transportedRoot p.rootSlot d.transfer := rfl

@[simp] theorem afterMerge_remaining
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (d : MergeDescriptor Claim Branch) :
    (p.afterMerge d).remaining =
      Plan.childBatch d.transfer p.remaining := rfl

/-- Simulation admission visibly contains the structural transfer checker. -/
theorem simulationAdmission_structural
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (d : MergeDescriptor Claim Branch)
    (project : Finset Branch -> Finset Branch)
    (hAdmission : MergeCheck.simulationAdmission A d project = true) :
    MergeCheck.structural A d = true := by
  have hparts : (MergeCheck.structural A d = true ∧
      MergeCheck.monoZero project = true) ∧
      MergeCheck.simulation A d project = true := by
    simpa [MergeCheck.simulationAdmission, Bool.and_eq_true] using hAdmission
  exact hparts.1.1

/-- Direct admission uses the same structural transfer checker. -/
theorem directAdmission_structural
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (d : MergeDescriptor Claim Branch)
    (hAdmission : MergeCheck.directAdmission A d = true) :
    MergeCheck.structural A d = true := by
  have hparts : MergeCheck.structural A d = true ∧
      checkAC (d.target A).auth = true := by
    simpa [MergeCheck.directAdmission, Bool.and_eq_true] using hAdmission
  exact hparts.1

/-- Source validity plus the two executable Merge checks reconstructs the
complete target plan invariant in simulation mode. -/
theorem afterSimulationMerge_preserves_valid
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    {d : MergeDescriptor Claim Branch}
    {project : Finset Branch -> Finset Branch}
    (hv : p.Valid A)
    (hAdmission : MergeCheck.simulationAdmission A d project = true)
    (hOwner : PlanRootTransport.checkTargetOwnerRootPure A d.transfer
      d.allowed p.rootSlot = true) :
    (p.afterMerge d).Valid (d.target A) := by
  have hStructure := simulationAdmission_structural A d project hAdmission
  have hCore := (MergeCheck.checkMergeStructure_sound A d hStructure).transfer
  simpa [afterMerge] using
    afterTransferCore_preserves_valid
      (A := A) (A' := d.target A) (p := p)
      (tr := d.transfer) (allowed := d.allowed) rfl hv hCore hOwner

/-- The direct-AC admission mode reuses exactly the same structural/core plan
argument; only its lifecycle AC proof differs from simulation mode. -/
theorem afterDirectMerge_preserves_valid
    {A : LifecycleState Coord Claim Branch Grant Operation}
    {p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot)}
    {d : MergeDescriptor Claim Branch}
    (hv : p.Valid A)
    (hAdmission : MergeCheck.directAdmission A d = true)
    (hOwner : PlanRootTransport.checkTargetOwnerRootPure A d.transfer
      d.allowed p.rootSlot = true) :
    (p.afterMerge d).Valid (d.target A) := by
  have hStructure := directAdmission_structural A d hAdmission
  have hCore := (MergeCheck.checkMergeStructure_sound A d hStructure).transfer
  simpa [afterMerge] using
    afterTransferCore_preserves_valid
      (A := A) (A' := d.target A) (p := p)
      (tr := d.transfer) (allowed := d.allowed) rfl hv hCore hOwner

/-- One executable controller check for simulation Merge.  Its atoms remain
visible: durable plan CAS, the repository's real simulation admission, and
owner/root purity on the computed target/root map. -/
def checkSimulationMergePlan
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (d : MergeDescriptor Claim Branch)
    (project : Finset Branch -> Finset Branch) (offered : Nat) : Bool :=
  p.checkVersion offered &&
    (MergeCheck.simulationAdmission A d project &&
      PlanRootTransport.checkTargetOwnerRootPure A d.transfer
        d.allowed p.rootSlot)

theorem checkSimulationMergePlan_parts
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (d : MergeDescriptor Claim Branch)
    (project : Finset Branch -> Finset Branch) (offered : Nat)
    (hCheck : checkSimulationMergePlan A p d project offered = true) :
    p.checkVersion offered = true ∧
      MergeCheck.simulationAdmission A d project = true ∧
      PlanRootTransport.checkTargetOwnerRootPure A d.transfer
        d.allowed p.rootSlot = true := by
  simpa [checkSimulationMergePlan, Bool.and_eq_true] using hCheck

/-- Direct Merge has a separate executable controller check so use of target
`checkAC` remains explicit rather than being conflated with simulation. -/
def checkDirectMergePlan
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (d : MergeDescriptor Claim Branch) (offered : Nat) : Bool :=
  p.checkVersion offered &&
    (MergeCheck.directAdmission A d &&
      PlanRootTransport.checkTargetOwnerRootPure A d.transfer
        d.allowed p.rootSlot)

theorem checkDirectMergePlan_parts
    (A : LifecycleState Coord Claim Branch Grant Operation)
    (p : PlanData (Coord := Coord) (Claim := Claim) (Slot := Slot))
    (d : MergeDescriptor Claim Branch) (offered : Nat)
    (hCheck : checkDirectMergePlan A p d offered = true) :
    p.checkVersion offered = true ∧
      MergeCheck.directAdmission A d = true ∧
      PlanRootTransport.checkTargetOwnerRootPure A d.transfer
        d.allowed p.rootSlot = true := by
  simpa [checkDirectMergePlan, Bool.and_eq_true] using hCheck

def advanceSimulationMerge
    (S : InvariantState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot))
    (d : MergeDescriptor Claim Branch) :
    InvariantState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot) where
  lifecycle := d.target S.lifecycle
  plan := S.plan.afterMerge d

/-- Paper-facing simulation Merge.  All plan/lifecycle evidence is either a
source invariant or an executable Boolean check. -/
inductive SimulationMergePlanned :
    InvariantState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot) ->
    Nat -> MergeDescriptor Claim Branch ->
    (Finset Branch -> Finset Branch) ->
    InvariantState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot) -> Prop where
  | mk {S offered d project}
      (hWF : S.lifecycle.LWF)
      (hAC : AC S.lifecycle.auth)
      (hActive : ActiveExact S.lifecycle)
      (hValid : S.plan.Valid S.lifecycle)
      (hVersion : S.plan.checkVersion offered = true)
      (hAdmission : MergeCheck.simulationAdmission
        S.lifecycle d project = true)
      (hOwner : PlanRootTransport.checkTargetOwnerRootPure
        S.lifecycle d.transfer d.allowed S.plan.rootSlot = true) :
      SimulationMergePlanned S offered d project
        (advanceSimulationMerge S d)

theorem simulationMergePlanned_of_check
    {S : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)}
    {offered : Nat} {d : MergeDescriptor Claim Branch}
    {project : Finset Branch -> Finset Branch}
    (hWF : S.lifecycle.LWF) (hAC : AC S.lifecycle.auth)
    (hActive : ActiveExact S.lifecycle) (hValid : S.plan.Valid S.lifecycle)
    (hCheck : checkSimulationMergePlan S.lifecycle S.plan d project
      offered = true) :
    SimulationMergePlanned S offered d project
      (advanceSimulationMerge S d) := by
  have hp := checkSimulationMergePlan_parts
    S.lifecycle S.plan d project offered hCheck
  exact .mk hWF hAC hActive hValid hp.1 hp.2.1 hp.2.2

theorem SimulationMergePlanned.version_sound
    {S S' : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)}
    {offered : Nat} {d : MergeDescriptor Claim Branch}
    {project : Finset Branch -> Finset Branch}
    (h : SimulationMergePlanned S offered d project S') :
    offered = S.plan.version := by
  cases h with
  | mk _ _ _ _ hVersion _ _ => exact checkVersion_sound _ _ hVersion

theorem SimulationMergePlanned.version_succ
    {S S' : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)}
    {offered : Nat} {d : MergeDescriptor Claim Branch}
    {project : Finset Branch -> Finset Branch}
    (h : SimulationMergePlanned S offered d project S') :
    S'.plan.version = S.plan.version + 1 := by
  cases h
  rfl

theorem SimulationMergePlanned.actual_step
    {S S' : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)}
    {offered : Nat} {d : MergeDescriptor Claim Branch}
    {project : Finset Branch -> Finset Branch}
    (h : SimulationMergePlanned S offered d project S') :
    Step S.lifecycle .tau S'.lifecycle := by
  cases h with
  | mk _ _ _ _ _ hAdmission _ =>
      exact Step.simulationMerge d project hAdmission

theorem SimulationMergePlanned.preserves_valid
    {S S' : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)}
    {offered : Nat} {d : MergeDescriptor Claim Branch}
    {project : Finset Branch -> Finset Branch}
    (h : SimulationMergePlanned S offered d project S') :
    S'.plan.Valid S'.lifecycle := by
  cases h with
  | mk _ _ _ hValid _ hAdmission hOwner =>
      exact afterSimulationMerge_preserves_valid hValid hAdmission hOwner

theorem SimulationMergePlanned.preserves_all
    {S S' : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)}
    {offered : Nat} {d : MergeDescriptor Claim Branch}
    {project : Finset Branch -> Finset Branch}
    (h : SimulationMergePlanned S offered d project S') :
    S'.lifecycle.LWF ∧ AC S'.lifecycle.auth ∧
      ActiveExact S'.lifecycle ∧ S'.plan.Valid S'.lifecycle ∧
      Step S.lifecycle .tau S'.lifecycle := by
  cases h with
  | mk hWF hAC _ hValid _ hAdmission hOwner =>
      have hLifecycle := simulation_merge_preserves_wf_ac
        S.lifecycle d project hWF hAC hAdmission
      exact ⟨hLifecycle.1, hLifecycle.2.1, hLifecycle.2.2,
        afterSimulationMerge_preserves_valid hValid hAdmission hOwner,
        Step.simulationMerge d project hAdmission⟩

def advanceDirectMerge
    (S : InvariantState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot))
    (d : MergeDescriptor Claim Branch) :
    InvariantState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot) where
  lifecycle := d.target S.lifecycle
  plan := S.plan.afterMerge d

/-- Honest direct-AC wrapper.  It stays a distinct constructor because its
admission invokes the executable target AC checker rather than a simulation. -/
inductive DirectMergePlanned :
    InvariantState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot) ->
    Nat -> MergeDescriptor Claim Branch ->
    InvariantState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot) -> Prop where
  | mk {S offered d}
      (hWF : S.lifecycle.LWF)
      (hValid : S.plan.Valid S.lifecycle)
      (hVersion : S.plan.checkVersion offered = true)
      (hAdmission : MergeCheck.directAdmission S.lifecycle d = true)
      (hOwner : PlanRootTransport.checkTargetOwnerRootPure
        S.lifecycle d.transfer d.allowed S.plan.rootSlot = true) :
      DirectMergePlanned S offered d (advanceDirectMerge S d)

theorem directMergePlanned_of_check
    {S : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)}
    {offered : Nat} {d : MergeDescriptor Claim Branch}
    (hWF : S.lifecycle.LWF) (hValid : S.plan.Valid S.lifecycle)
    (hCheck : checkDirectMergePlan S.lifecycle S.plan d offered = true) :
    DirectMergePlanned S offered d (advanceDirectMerge S d) := by
  have hp := checkDirectMergePlan_parts
    S.lifecycle S.plan d offered hCheck
  exact .mk hWF hValid hp.1 hp.2.1 hp.2.2

theorem DirectMergePlanned.version_sound
    {S S' : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)}
    {offered : Nat} {d : MergeDescriptor Claim Branch}
    (h : DirectMergePlanned S offered d S') :
    offered = S.plan.version := by
  cases h with
  | mk _ _ hVersion _ _ => exact checkVersion_sound _ _ hVersion

theorem DirectMergePlanned.version_succ
    {S S' : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)}
    {offered : Nat} {d : MergeDescriptor Claim Branch}
    (h : DirectMergePlanned S offered d S') :
    S'.plan.version = S.plan.version + 1 := by
  cases h
  rfl

theorem DirectMergePlanned.actual_step
    {S S' : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)}
    {offered : Nat} {d : MergeDescriptor Claim Branch}
    (h : DirectMergePlanned S offered d S') :
    Step S.lifecycle .tau S'.lifecycle := by
  cases h with
  | mk _ _ _ hAdmission _ => exact Step.directMerge d hAdmission

theorem DirectMergePlanned.preserves_valid
    {S S' : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)}
    {offered : Nat} {d : MergeDescriptor Claim Branch}
    (h : DirectMergePlanned S offered d S') :
    S'.plan.Valid S'.lifecycle := by
  cases h with
  | mk _ hValid _ hAdmission hOwner =>
      exact afterDirectMerge_preserves_valid hValid hAdmission hOwner

theorem DirectMergePlanned.preserves_all
    {S S' : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)}
    {offered : Nat} {d : MergeDescriptor Claim Branch}
    (h : DirectMergePlanned S offered d S') :
    S'.lifecycle.LWF ∧ AC S'.lifecycle.auth ∧
      ActiveExact S'.lifecycle ∧ S'.plan.Valid S'.lifecycle ∧
      Step S.lifecycle .tau S'.lifecycle := by
  cases h with
  | mk hWF hValid _ hAdmission hOwner =>
      have hLifecycle := direct_merge_preserves_wf_ac
        S.lifecycle d hWF hAdmission
      exact ⟨hLifecycle.1, hLifecycle.2.1, hLifecycle.2.2,
        afterDirectMerge_preserves_valid hValid hAdmission hOwner,
        Step.directMerge d hAdmission⟩

#print axioms afterSimulationMerge_preserves_valid
#print axioms SimulationMergePlanned.preserves_all
#print axioms afterDirectMerge_preserves_valid
#print axioms DirectMergePlanned.preserves_all

end PlanData

end AuthorityContinuity.PlanInvariant
