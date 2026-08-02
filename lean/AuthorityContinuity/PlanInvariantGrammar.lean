import AuthorityContinuity.PlanInvariantMerge
import AuthorityContinuity.PlanInvariantDrop
import AuthorityContinuity.Trace

/-!
# Unified positive controller grammar

This module combines the independently checked positive controller operations
without weakening any operation-specific admission rule.  Every edge projects
to the repository's sole `Step` relation.  Plan-mutating edges advance the
durable version exactly once; checkpoint and ticket/recovery edges stutter the
plan and therefore preserve its version.
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

/-! ## Version-checked canonical wrapper -/

def advanceCanonicalTransport
    (S : InvariantState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot))
    (tr : Transfer Claim Branch) (op : CanonicalOp Branch) :
    InvariantState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot) where
  lifecycle := canonicalTarget S.lifecycle tr op
  plan := S.plan.afterCanonical tr

/-- Paper-facing canonical topology transport with source invariants, durable
version CAS, actual canonical checker, and computed target owner/root check. -/
inductive CanonicalTransportPlanned :
    InvariantState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot) ->
    Nat -> Transfer Claim Branch -> CanonicalOp Branch ->
    InvariantState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot) -> Prop where
  | mk {S offered tr op}
      (hWF : S.lifecycle.LWF)
      (hAC : AC S.lifecycle.auth)
      (hActive : ActiveExact S.lifecycle)
      (hValid : S.plan.Valid S.lifecycle)
      (hVersion : S.plan.checkVersion offered = true)
      (hCanonical : checkCanonical S.lifecycle tr op = true)
      (hOwner : PlanRootTransport.checkTargetOwnerRootPure
        S.lifecycle tr (canonicalAllowed S.lifecycle op)
          S.plan.rootSlot = true) :
      CanonicalTransportPlanned S offered tr op
        (advanceCanonicalTransport S tr op)

theorem canonicalTransportPlanned_of_check
    {S : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)}
    {offered : Nat} {tr : Transfer Claim Branch} {op : CanonicalOp Branch}
    (hWF : S.lifecycle.LWF) (hAC : AC S.lifecycle.auth)
    (hActive : ActiveExact S.lifecycle) (hValid : S.plan.Valid S.lifecycle)
    (hCheck : checkCanonicalPlan S.lifecycle S.plan tr op offered = true) :
    CanonicalTransportPlanned S offered tr op
      (advanceCanonicalTransport S tr op) := by
  have hp := checkCanonicalPlan_parts
    S.lifecycle S.plan tr op offered hCheck
  exact .mk hWF hAC hActive hValid hp.1 hp.2.1 hp.2.2

theorem CanonicalTransportPlanned.version_sound
    {S S' : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)}
    {offered : Nat} {tr : Transfer Claim Branch} {op : CanonicalOp Branch}
    (h : CanonicalTransportPlanned S offered tr op S') :
    offered = S.plan.version := by
  cases h with
  | mk _ _ _ _ hVersion _ _ => exact checkVersion_sound _ _ hVersion

theorem CanonicalTransportPlanned.version_succ
    {S S' : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)}
    {offered : Nat} {tr : Transfer Claim Branch} {op : CanonicalOp Branch}
    (h : CanonicalTransportPlanned S offered tr op S') :
    S'.plan.version = S.plan.version + 1 := by
  cases h
  rfl

theorem CanonicalTransportPlanned.actual_step
    {S S' : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)}
    {offered : Nat} {tr : Transfer Claim Branch} {op : CanonicalOp Branch}
    (h : CanonicalTransportPlanned S offered tr op S') :
    Step S.lifecycle .tau S'.lifecycle := by
  cases h with
  | mk _ _ _ _ _ hCanonical _ => exact Step.canonical tr op hCanonical

theorem CanonicalTransportPlanned.preserves_valid
    {S S' : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)}
    {offered : Nat} {tr : Transfer Claim Branch} {op : CanonicalOp Branch}
    (h : CanonicalTransportPlanned S offered tr op S') :
    S'.plan.Valid S'.lifecycle := by
  cases h with
  | mk _ _ _ hValid _ hCanonical hOwner =>
      exact afterCanonical_preserves_valid hValid hCanonical hOwner

theorem CanonicalTransportPlanned.preserves_all
    {S S' : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)}
    {offered : Nat} {tr : Transfer Claim Branch} {op : CanonicalOp Branch}
    (h : CanonicalTransportPlanned S offered tr op S') :
    S'.lifecycle.LWF ∧ AC S'.lifecycle.auth ∧
      ActiveExact S'.lifecycle ∧ S'.plan.Valid S'.lifecycle ∧
      Step S.lifecycle .tau S'.lifecycle := by
  cases h with
  | mk hWF hAC hActive hValid _ hCanonical hOwner =>
      have hLifecycle := canonical_preserves_wf_ac
        S.lifecycle tr op hWF hAC hActive hCanonical
      exact ⟨hLifecycle.1, hLifecycle.2.1, hLifecycle.2.2,
        afterCanonical_preserves_valid hValid hCanonical hOwner,
        Step.canonical tr op hCanonical⟩

/-! ## One positive edge grammar -/

/-- The four invariants carried across the unified controller history. -/
structure Safe
    (S : InvariantState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)) : Prop where
  lwf : S.lifecycle.LWF
  ac : AC S.lifecycle.auth
  activeExact : ActiveExact S.lifecycle
  planValid : S.plan.Valid S.lifecycle

/-- A small positive grammar.  Each mutating constructor wraps its own checked
relation; ticket/recovery changes only lifecycle metadata while the plan
stutters. -/
inductive PositiveStep :
    InvariantState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot) ->
    Label Operation Claim ->
    InvariantState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot) -> Prop where
  | checkpoint (S) : PositiveStep S .tau S
  | prepare {S S' offered assignment}
      (h : PreparePlanned S offered assignment S') :
      PositiveStep S .tau S'
  | canonical {S S' offered tr op}
      (h : CanonicalTransportPlanned S offered tr op S') :
      PositiveStep S .tau S'
  | restriction {S S' offered owners keep}
      (h : RestrictionPlanned S offered owners keep S') :
      PositiveStep S .tau S'
  | revoke {S S' offered g}
      (h : RevokePlanned S offered g S') :
      PositiveStep S .tau S'
  | simulationMerge {S S' offered d project}
      (h : SimulationMergePlanned S offered d project S') :
      PositiveStep S .tau S'
  | directMerge {S S' offered d}
      (h : DirectMergePlanned S offered d S') :
      PositiveStep S .tau S'
  | ticket (S) {A' : LifecycleState Coord Claim Branch Grant Operation}
      {eta : Label Operation Claim} (h : TicketStep S.lifecycle eta A') :
      PositiveStep S eta { lifecycle := A', plan := S.plan }

theorem PositiveStep.actual_step
    {S S' : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)}
    {eta : Label Operation Claim} (h : PositiveStep S eta S') :
    Step S.lifecycle eta S'.lifecycle := by
  cases h with
  | checkpoint => exact Step.core (CoreStep.checkpoint _)
  | prepare h => exact h.actual_step
  | canonical h => exact h.actual_step
  | restriction h => exact h.actual_step
  | revoke h => exact h.actual_step
  | simulationMerge h => exact h.actual_step
  | directMerge h => exact h.actual_step
  | ticket h => exact Step.core (CoreStep.ticket h)

theorem PositiveStep.preserves_valid
    {S S' : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)}
    {eta : Label Operation Claim} (h : PositiveStep S eta S')
    (hValid : S.plan.Valid S.lifecycle) : S'.plan.Valid S'.lifecycle := by
  cases h with
  | checkpoint => exact hValid
  | prepare h => exact h.preserves_valid
  | canonical h => exact h.preserves_valid
  | restriction h => exact h.preserves_valid hValid
  | revoke h => exact h.preserves_valid hValid
  | simulationMerge h => exact h.preserves_valid
  | directMerge h => exact h.preserves_valid
  | ticket h => exact hValid.transport_auth (ticketStep_auth_eq h)

/-- Every unified positive edge preserves lifecycle safety and the complete
plan invariant. -/
theorem PositiveStep.preserves_safe
    {S S' : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)}
    {eta : Label Operation Claim} (h : PositiveStep S eta S')
    (hSafe : Safe S) : Safe S' := by
  have hLifecycle := step_preserves_wf_ac h.actual_step
    hSafe.lwf hSafe.ac hSafe.activeExact
  exact ⟨hLifecycle.1, hLifecycle.2.1, hLifecycle.2.2,
    h.preserves_valid hSafe.planValid⟩

/-- A positive edge never decreases the durable plan version.  Mutating
constructors add one; checkpoint and ticket/recovery stutter. -/
theorem PositiveStep.version_mono
    {S S' : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)}
    {eta : Label Operation Claim} (h : PositiveStep S eta S') :
    S.plan.version <= S'.plan.version := by
  cases h with
  | checkpoint => exact le_rfl
  | prepare h => rw [h.version_succ]; omega
  | canonical h => rw [h.version_succ]; omega
  | restriction h => rw [h.version_succ]; omega
  | revoke h => rw [h.version_succ]; omega
  | simulationMerge h => rw [h.version_succ]; omega
  | directMerge h => rw [h.version_succ]; omega
  | ticket => exact le_rfl

def PositiveEdge
    (S S' : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)) : Prop :=
  ∃ eta, PositiveStep S eta S'

abbrev PositiveTrace
    (S S' : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)) : Prop :=
  Relation.ReflTransGen PositiveEdge S S'

/-- Arbitrary finite histories in the positive grammar preserve all coupled
lifecycle and plan invariants. -/
theorem positive_trace_preserves
    {S S' : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)}
    (hTrace : PositiveTrace S S') (hSafe : Safe S) : Safe S' := by
  induction hTrace with
  | refl => exact hSafe
  | tail _ hEdge ih =>
      obtain ⟨eta, hStep⟩ := hEdge
      exact hStep.preserves_safe ih

/-- Erasing controller data and operation constructors yields an actual trace
of the sole lifecycle `Step` relation. -/
theorem positive_trace_projects
    {S S' : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)}
    (hTrace : PositiveTrace S S') :
    AbstractTrace S.lifecycle S'.lifecycle := by
  induction hTrace with
  | refl => exact .refl
  | tail _ hEdge ih =>
      obtain ⟨eta, hStep⟩ := hEdge
      exact ih.tail ⟨eta, hStep.actual_step⟩

/-- Durable plan versions are monotone along arbitrary finite positive
histories, including ticket/recovery and checkpoint stutters. -/
theorem positive_trace_version_mono
    {S S' : InvariantState (Coord := Coord) (Claim := Claim)
      (Branch := Branch) (Grant := Grant) (Operation := Operation)
      (Slot := Slot)}
    (hTrace : PositiveTrace S S') :
    S.plan.version <= S'.plan.version := by
  induction hTrace with
  | refl => exact le_rfl
  | tail _ hEdge ih =>
      obtain ⟨eta, hStep⟩ := hEdge
      exact ih.trans hStep.version_mono

#print axioms CanonicalTransportPlanned.preserves_all
#print axioms PositiveStep.preserves_safe
#print axioms PositiveStep.version_mono
#print axioms positive_trace_preserves
#print axioms positive_trace_projects
#print axioms positive_trace_version_mono

end PlanData

end AuthorityContinuity.PlanInvariant
