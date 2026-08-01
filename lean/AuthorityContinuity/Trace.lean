import AuthorityContinuity.Step
import Mathlib.Algebra.Order.BigOperators.Group.Finset

/-!
# Trace-level effect accounting

This module proves the trace and concrete-effect results from the frozen RQ3
matrix.  Stable operation identifiers index aggregate outcomes: physical
retries are not separate entries in `ops`.
-/

namespace AuthorityContinuity

open LifecycleState

universe uC uI uB uG uO uX

section AbstractTrace

variable {Coord : Type uC} {Claim : Type uI} {Branch : Type uB}
variable {Grant : Type uG} {Operation : Type uO}
variable [Fintype Coord] [Fintype Claim] [Fintype Branch]
variable [DecidableEq Coord] [DecidableEq Claim] [DecidableEq Branch]
variable [DecidableEq Grant] [DecidableEq Operation]

/-- Erase the label while retaining one admitted abstract lifecycle step. -/
def AbstractStep
    (A A' : LifecycleState Coord Claim Branch Grant Operation) : Prop :=
  ∃ η : Label Operation Claim, Step A η A'

/-- The reflexive-transitive closure of admitted abstract lifecycle steps. -/
abbrev AbstractTrace
    (A A' : LifecycleState Coord Claim Branch Grant Operation) : Prop :=
  Relation.ReflTransGen AbstractStep A A'

/-- Every finite admitted abstract trace preserves lifecycle well-formedness,
authority continuity, and exact correspondence between open epochs and the
computed contract support. -/
theorem trace_preserves_wf_ac
    {A A' : LifecycleState Coord Claim Branch Grant Operation}
    (hTrace : AbstractTrace A A')
    (hWF : LifecycleState.LWF A) (hAC : AC A.auth)
    (hActive : LifecycleState.ActiveExact A) :
    LifecycleState.LWF A' ∧ AC A'.auth ∧
      LifecycleState.ActiveExact A' := by
  induction hTrace with
  | refl => exact ⟨hWF, hAC, hActive⟩
  | tail _ hStep ih =>
      obtain ⟨η, hStep⟩ := hStep
      exact step_preserves_wf_ac hStep ih.1 ih.2.1 ih.2.2

/-- Terminal claim IDs cannot be revived by any finite admitted abstract
trace.  This says only what the modeled `Step` constructors enforce. -/
theorem trace_terminal_mono
    {A A' : LifecycleState Coord Claim Branch Grant Operation}
    (hTrace : AbstractTrace A A') : A.TerminalMonotone A' := by
  induction hTrace with
  | refl =>
      intro c hc
      exact hc
  | tail _ hStep ih =>
      obtain ⟨η, hStep⟩ := hStep
      intro c hc
      exact step_terminal_mono hStep c (ih c hc)

/-- Branch and grant epoch closure is likewise monotone along any finite
admitted abstract trace. -/
theorem trace_epoch_mono
    {A A' : LifecycleState Coord Claim Branch Grant Operation}
    (hTrace : AbstractTrace A A') : A.EpochMonotone A' := by
  induction hTrace with
  | refl =>
      exact ⟨fun b => EpochStatus.Advances.refl (A.branchEpoch b),
        fun g => EpochStatus.Advances.refl (A.grantEpoch g)⟩
  | tail _ hStep ih =>
      obtain ⟨η, hStep⟩ := hStep
      have hOne := step_epoch_mono hStep
      exact ⟨
        fun b => EpochStatus.Advances.trans (ih.1 b) (hOne.1 b),
        fun g => EpochStatus.Advances.trans (ih.2 g) (hOne.2 g)⟩

/-- Stable bindings persist through the full admitted abstract closure. -/
theorem trace_preserves_existing_binding
    {A A' : LifecycleState Coord Claim Branch Grant Operation}
    (hTrace : AbstractTrace A A') :
    ∀ e c, A.opClaim e = some c → A'.opClaim e = some c := by
  intro e c hBound
  induction hTrace with
  | refl => exact hBound
  | tail _ hStep ih =>
      obtain ⟨eta, hStep⟩ := hStep
      exact step_preserves_existing_binding hStep e c ih

/-- One concrete transition event, including the resource outcome observed at
that edge.  Outcomes are aggregated by stable operation ID below. -/
structure ConcreteEvent
    (Operation : Type uO) (Claim : Type uI) (Coord : Type uC) where
  label : Label Operation Claim
  actual : Coord → Nat

namespace ConcreteEvent

/-- An abstraction stutter carries no protected outcome.  A nonzero outcome
must therefore occur on an exact abstract attempt edge. -/
def WellMediated
    (event : ConcreteEvent Operation Claim Coord) : Prop :=
  match event.label with
  | .tau => ∀ k, event.actual k = 0
  | .attempt _ _ => True

/-- Contribution of one concrete event to stable operation `e`. -/
def actualFor [DecidableEq Operation]
    (event : ConcreteEvent Operation Claim Coord) (e : Operation)
    (k : Coord) : Nat :=
  match event.label with
  | .tau => 0
  | .attempt e' _ => if e' = e then event.actual k else 0

end ConcreteEvent

/-- Aggregate resource outcome of every physical attempt sharing stable ID
`e` in this concrete prefix. -/
def aggregateActual [DecidableEq Operation]
    (events : List (ConcreteEvent Operation Claim Coord))
    (e : Operation) (k : Coord) : Nat :=
  (events.map fun event => event.actualFor e k).sum

/-- A labeled, per-edge forward simulation of one concrete execution.  Each
concrete edge is either a zero-outcome abstraction stutter or maps with its
exact label and outcome to one admitted abstract step. -/
inductive SimulatedTrace
    {Concrete : Type uX}
    (concreteStep : Concrete → ConcreteEvent Operation Claim Coord → Concrete → Prop)
    (abstract : Concrete → LifecycleState Coord Claim Branch Grant Operation) :
    Concrete → List (ConcreteEvent Operation Claim Coord) → Concrete → Prop where
  | refl (x) : SimulatedTrace concreteStep abstract x [] x
  | stutter {x y z events event} :
      SimulatedTrace concreteStep abstract x events y →
      concreteStep y event z → event.WellMediated →
      event.label = .tau → abstract y = abstract z →
      SimulatedTrace concreteStep abstract x (events ++ [event]) z
  | step {x y z events event} :
      SimulatedTrace concreteStep abstract x events y →
      concreteStep y event z → event.WellMediated →
      Step (abstract y) event.label (abstract z) →
      SimulatedTrace concreteStep abstract x (events ++ [event]) z

/-- The simulated execution projects to the admitted abstract closure. -/
theorem SimulatedTrace.abstract_trace
    {Concrete : Type uX}
    {concreteStep : Concrete → ConcreteEvent Operation Claim Coord → Concrete → Prop}
    {abstract : Concrete → LifecycleState Coord Claim Branch Grant Operation}
    {x x' : Concrete} {events : List (ConcreteEvent Operation Claim Coord)}
    (hSimulation : SimulatedTrace concreteStep abstract x events x') :
    AbstractTrace (abstract x) (abstract x') := by
  induction hSimulation with
  | refl => exact Relation.ReflTransGen.refl
  | stutter _ _ _ _ hEq ih => simpa [hEq] using ih
  | step _ _ _ hStep ih =>
      exact Relation.ReflTransGen.tail ih ⟨_, hStep⟩

/-- The same witness also contains the underlying concrete execution. -/
theorem SimulatedTrace.concrete_trace
    {Concrete : Type uX}
    {concreteStep : Concrete → ConcreteEvent Operation Claim Coord → Concrete → Prop}
    {abstract : Concrete → LifecycleState Coord Claim Branch Grant Operation}
    {x x' : Concrete} {events : List (ConcreteEvent Operation Claim Coord)}
    (hSimulation : SimulatedTrace concreteStep abstract x events x') :
    Relation.ReflTransGen (fun y z => ∃ event, concreteStep y event z) x x' := by
  induction hSimulation with
  | refl => exact Relation.ReflTransGen.refl
  | stutter _ hStep _ _ _ ih =>
      exact Relation.ReflTransGen.tail ih ⟨_, hStep⟩
  | step _ hStep _ _ ih => exact Relation.ReflTransGen.tail ih ⟨_, hStep⟩

/-- Every concrete attempt event in a simulated prefix retains its stable
binding at the end of that prefix.  The event's own abstract step establishes
durable-before-attempt; subsequent steps preserve the binding. -/
theorem SimulatedTrace.attempt_binding_final
    {Concrete : Type uX}
    {concreteStep : Concrete → ConcreteEvent Operation Claim Coord → Concrete → Prop}
    {abstract : Concrete → LifecycleState Coord Claim Branch Grant Operation}
    {x x' : Concrete} {events : List (ConcreteEvent Operation Claim Coord)}
    (hSimulation : SimulatedTrace concreteStep abstract x events x')
    (hInitialWF : LifecycleState.LWF (abstract x))
    (hInitialAC : AC (abstract x).auth)
    (hInitialActive : LifecycleState.ActiveExact (abstract x))
    {event : ConcreteEvent Operation Claim Coord} (hEvent : event ∈ events)
    {e : Operation} {c : Claim} (hLabel : event.label = .attempt e c) :
    (abstract x').opClaim e = some c := by
  induction hSimulation generalizing event with
  | refl => simp at hEvent
  | stutter hPrefix hConcrete hWell hTau hEq ih =>
      rw [List.mem_append] at hEvent
      rcases hEvent with hOld | hLast
      · simpa [hEq] using ih hOld hLabel
      · simp only [List.mem_singleton] at hLast
        subst event
        simp [hTau] at hLabel
  | step hPrefix hConcrete hWell hStep ih =>
      rw [List.mem_append] at hEvent
      rcases hEvent with hOld | hLast
      · exact step_preserves_existing_binding hStep e c (ih hOld hLabel)
      · simp only [List.mem_singleton] at hLast
        subst event
        have hAttemptStep := hStep
        rw [hLabel] at hAttemptStep
        have hPrefixInvariant := trace_preserves_wf_ac
          hPrefix.abstract_trace hInitialWF hInitialAC hInitialActive
        exact (step_attempt_safe hAttemptStep hPrefixInvariant.1).2.2

end AbstractTrace

/--
Distinct mediated operations bound injectively to durable claims cannot have
more aggregate effect than those durable claims carry.  The result is
componentwise in the resource type.
-/
theorem effect_coverage
    {Operation Claim Resource : Type*}
    [DecidableEq Operation] [DecidableEq Claim]
    (ops : Finset Operation)
    (durable : Finset Claim)
    (claimOf : Operation → Claim)
    (actual : Operation → Resource → Nat)
    (claimDemand : Claim → Resource → Nat)
    (hStable : Set.InjOn claimOf (ops : Set Operation))
    (hPrepared : ∀ e ∈ ops, claimOf e ∈ durable)
    (hBound : ∀ e ∈ ops, ∀ k, actual e k ≤ claimDemand (claimOf e) k) :
    ∀ k, (∑ e ∈ ops, actual e k) ≤ ∑ c ∈ durable, claimDemand c k := by
  intro k
  calc
    (∑ e ∈ ops, actual e k) ≤ ∑ e ∈ ops, claimDemand (claimOf e) k :=
      Finset.sum_le_sum fun e he => hBound e he k
    _ = ∑ c ∈ ops.image claimOf, claimDemand c k := by
      symm
      exact Finset.sum_image hStable
    _ ≤ ∑ c ∈ durable, claimDemand c k := by
      apply Finset.sum_le_sum_of_subset
      intro c hc
      obtain ⟨e, he, rfl⟩ := Finset.mem_image.mp hc
      exact hPrepared e he

section ConcreteTrace

variable {Coord : Type uC} {Claim : Type uI} {Branch : Type uB}
variable {Grant : Type uG} {Operation : Type uO}
variable [Fintype Coord] [Fintype Claim] [Fintype Branch] [Fintype Operation]
variable [DecidableEq Coord] [DecidableEq Claim] [DecidableEq Branch]
variable [DecidableEq Grant] [DecidableEq Operation]

/--
Conditional concrete authority safety.  The theorem does not manufacture a
runtime refinement: complete mediation, durable pre-dispatch binding,
per-step simulation, and the sink's aggregate outcome bound remain the same
explicit hypotheses.  `ActiveExact` is only the abstract lifecycle invariant
needed by the computed topology preservation theorem.
-/
theorem concrete_trace_authority_safety
    {Concrete : Type uX}
    (concreteStep : Concrete → ConcreteEvent Operation Claim Coord → Concrete → Prop)
    (abstract : Concrete → LifecycleState Coord Claim Branch Grant Operation)
    {x₀ x : Concrete} {events : List (ConcreteEvent Operation Claim Coord)}
    (hStepSimulation : SimulatedTrace concreteStep abstract x₀ events x)
    (hInitialWF : LifecycleState.LWF (abstract x₀))
    (hInitialAC : AC (abstract x₀).auth)
    (hInitialActive : LifecycleState.ActiveExact (abstract x₀))
    (protectedOps : Finset Operation)
    (claimOf : Operation → Claim)
    (hCompleteMediation : ∀ e,
      (∃ k, aggregateActual events e k ≠ 0) → e ∈ protectedOps)
    (hAttemptWitness : ∀ e ∈ protectedOps,
      ∃ event ∈ events, event.label = Label.attempt e (claimOf e))
    (hAggregateBound : ∀ e ∈ protectedOps, ∀ k,
      aggregateActual events e k ≤ (abstract x).auth.demand (claimOf e) k)
    (C : Finset Branch) (hPermitted : C ∈ (abstract x).auth.allowed) :
    ∀ k, (∑ e : Operation, aggregateActual events e k) +
      (abstract x).auth.conditionalLoad C k ≤ (abstract x).auth.capacity k := by
  intro k
  have hAbstractTrace : AbstractTrace (abstract x₀) (abstract x) :=
    hStepSimulation.abstract_trace
  have hCurrent : LifecycleState.LWF (abstract x) ∧
      AC (abstract x).auth ∧ LifecycleState.ActiveExact (abstract x) :=
    trace_preserves_wf_ac hAbstractTrace hInitialWF hInitialAC hInitialActive
  have hFinalBinding : ∀ e ∈ protectedOps,
      (abstract x).opClaim e = some (claimOf e) := by
    intro e he
    obtain ⟨event, hEvent, hLabel⟩ := hAttemptWitness e he
    exact hStepSimulation.attempt_binding_final hInitialWF hInitialAC
      hInitialActive hEvent hLabel
  have hStableBinding : Set.InjOn claimOf (protectedOps : Set Operation) := by
    intro e he e' he' hClaim
    apply hCurrent.1.binding_injective e e' (claimOf e)
    · exact hFinalBinding e he
    · simpa [hClaim] using hFinalBinding e' he'
  have hPrepared : ∀ e ∈ protectedOps,
      claimOf e ∈ (abstract x).auth.durableClaims := by
    intro e he
    simp only [State.durableClaims, Finset.mem_filter, Finset.mem_univ, true_and]
    exact hCurrent.1.bound_durable e (claimOf e) (hFinalBinding e he)
  have hCovered : (∑ e ∈ protectedOps, aggregateActual events e k) ≤
      (abstract x).auth.durableLoad k := by
    simpa [State.durableLoad] using
      effect_coverage protectedOps (abstract x).auth.durableClaims claimOf
        (aggregateActual events) (abstract x).auth.demand hStableBinding
        hPrepared hAggregateBound k
  have hAllEffects : (∑ e : Operation, aggregateActual events e k) =
      ∑ e ∈ protectedOps, aggregateActual events e k := by
    symm
    apply Finset.sum_subset (Finset.subset_univ protectedOps)
    intro e _ he
    by_contra hNonzero
    exact he (hCompleteMediation e ⟨k, hNonzero⟩)
  rw [hAllEffects]
  exact (Nat.add_le_add_right hCovered _).trans
    (hCurrent.2.1 C hPermitted k)

end ConcreteTrace

end AuthorityContinuity
