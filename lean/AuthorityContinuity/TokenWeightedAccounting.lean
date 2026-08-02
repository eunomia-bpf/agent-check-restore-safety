import AuthorityContinuity.PlanTokenStrengthening

/-!
# Epoch-qualified token accounting

This module gives the *same* immutable token partition two projections:

* an identity projection, supplied by `LinearValid.token_trichotomy`; and
* a weighted projection, where token weights partition exactly as
  `B + E + W = P` in every root slot and resource coordinate.

It does not claim coherence with the older claim-indexed `FullPlanInvariant`.
The plan-epoch initializer is an explicit trusted boundary; no dynamic mint or
epoch-installation transition is modeled here.
-/

namespace AuthorityContinuity.TokenWeightedAccounting

open AuthorityContinuity LifecycleState
open AuthorityContinuity.PlanInvariant
open AuthorityContinuity.PlanTokenLinearity
open AuthorityContinuity.PlanTokenStrengthening

universe uE uN uC uI uB uG uO uS

/-- Token identity carries its issuing plan epoch. -/
structure EpochToken (Epoch : Type uE) (Serial : Type uN) where
  epoch : Epoch
  serial : Serial
  deriving DecidableEq, Fintype

/-- Epoch-qualified tokens use the lexicographic order on epoch and serial. -/
instance [LinearOrder Epoch] [LinearOrder Serial] :
    LinearOrder (EpochToken Epoch Serial) :=
  LinearOrder.lift' (fun t => toLex (t.epoch, t.serial)) (by
    intro a b h
    cases a
    cases b
    simp_all)

variable {Epoch : Type uE} {Serial : Type uN}
variable {Coord : Type uC} {Claim : Type uI} {Branch : Type uB}
variable {Grant : Type uG} {Operation : Type uO} {Slot : Type uS}
variable [Fintype Epoch] [LinearOrder Epoch]
variable [Fintype Serial] [LinearOrder Serial]
variable [Fintype Coord] [DecidableEq Coord]
variable [Fintype Claim] [LinearOrder Claim]
variable [Fintype Branch] [LinearOrder Branch]
variable [DecidableEq Grant] [Fintype Operation] [DecidableEq Operation]
variable [Fintype Slot] [LinearOrder Slot]

abbrev EToken := EpochToken Epoch Serial

/-- Immutable metadata installed at one trusted plan-epoch boundary. -/
structure PlanEpochSpec where
  epoch : Epoch
  initial : Finset (EToken (Epoch := Epoch) (Serial := Serial))
  root : EToken (Epoch := Epoch) (Serial := Serial) -> Slot
  weight : EToken (Epoch := Epoch) (Serial := Serial) -> Coord -> Nat
  same_epoch : forall t, t ∈ initial -> t.epoch = epoch

namespace PlanEpochSpec

variable (spec : PlanEpochSpec (Epoch := Epoch) (Serial := Serial)
  (Coord := Coord) (Slot := Slot))

def remainingTokens
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := EToken (Epoch := Epoch) (Serial := Serial))) :
    Finset (EToken (Epoch := Epoch) (Serial := Serial)) :=
  S.ledger.initial.filter fun t =>
    S.ledger.disposition t = .remaining

def preparedTokens
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := EToken (Epoch := Epoch) (Serial := Serial))) :
    Finset (EToken (Epoch := Epoch) (Serial := Serial)) :=
  S.ledger.initial.filter fun t =>
    S.ledger.disposition t = .prepared

def withdrawnTokens
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := EToken (Epoch := Epoch) (Serial := Serial))) :
    Finset (EToken (Epoch := Epoch) (Serial := Serial)) :=
  S.ledger.initial.filter fun t =>
    S.ledger.disposition t = .withdrawn

private def rootedWeight
    (t : EToken (Epoch := Epoch) (Serial := Serial))
    (s : Slot) (k : Coord) : Nat :=
  if spec.root t = s then spec.weight t k else 0

def B
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := EToken (Epoch := Epoch) (Serial := Serial)))
    (s : Slot) (k : Coord) : Nat :=
  ∑ t ∈ S.ledger.initial,
    if S.ledger.disposition t = .remaining then spec.rootedWeight t s k else 0

def E
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := EToken (Epoch := Epoch) (Serial := Serial)))
    (s : Slot) (k : Coord) : Nat :=
  ∑ t ∈ S.ledger.initial,
    if S.ledger.disposition t = .prepared then spec.rootedWeight t s k else 0

def W
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := EToken (Epoch := Epoch) (Serial := Serial)))
    (s : Slot) (k : Coord) : Nat :=
  ∑ t ∈ S.ledger.initial,
    if S.ledger.disposition t = .withdrawn then spec.rootedWeight t s k else 0

def P
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := EToken (Epoch := Epoch) (Serial := Serial)))
    (s : Slot) (k : Coord) : Nat :=
  ∑ t ∈ S.ledger.initial, spec.rootedWeight t s k

/-- Weighted exact accounting is a theorem of the total token disposition,
not an asserted residual row. -/
theorem weighted_partition_exact
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := EToken (Epoch := Epoch) (Serial := Serial)))
    (s : Slot) (k : Coord) :
    spec.B S s k + spec.E S s k + spec.W S s k = spec.P S s k := by
  classical
  unfold B E W P
  rw [← Finset.sum_add_distrib, ← Finset.sum_add_distrib]
  apply Finset.sum_congr rfl
  intro t ht
  cases hDisposition : S.ledger.disposition t <;>
    simp [hDisposition]

/-- Every initial token remains visible in one identity partition even when
its complete resource vector is zero. -/
theorem zero_weight_token_visible
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := EToken (Epoch := Epoch) (Serial := Serial)))
    {t : EToken (Epoch := Epoch) (Serial := Serial)}
    (ht : t ∈ S.ledger.initial) (_zero : forall k, spec.weight t k = 0) :
    t ∈ remainingTokens S ∨ t ∈ preparedTokens S ∨
      t ∈ withdrawnTokens S := by
  cases hDisposition : S.ledger.disposition t <;>
    simp [remainingTokens, preparedTokens, withdrawnTokens, ht, hDisposition]

theorem cardinality_partition
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := EToken (Epoch := Epoch) (Serial := Serial))) :
    (remainingTokens S).card + (preparedTokens S).card +
      (withdrawnTokens S).card = S.ledger.initial.card := by
  classical
  simp only [remainingTokens, preparedTokens, withdrawnTokens,
    Finset.card_eq_sum_ones, Finset.sum_filter]
  rw [← Finset.sum_add_distrib, ← Finset.sum_add_distrib]
  apply Finset.sum_congr rfl
  intro t ht
  cases hDisposition : S.ledger.disposition t <;> simp [hDisposition]

end PlanEpochSpec

/-- Identity-level projection of the same partition. -/
def IdentityProjection
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := EToken (Epoch := Epoch) (Serial := Serial))) : Prop :=
  forall t, t ∈ S.ledger.initial ->
    (S.ledger.disposition t = .remaining ∧
        (S.currentFiber t).card = 1 ∧ (S.bindingFiber t).card = 0) ∨
    (S.ledger.disposition t = .prepared ∧
        (S.currentFiber t).card = 0 ∧ (S.bindingFiber t).card = 1) ∨
    (S.ledger.disposition t = .withdrawn ∧
        (S.currentFiber t).card = 0 ∧ (S.bindingFiber t).card = 0)

def WeightedProjection
    (spec : PlanEpochSpec (Epoch := Epoch) (Serial := Serial)
      (Coord := Coord) (Slot := Slot))
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := EToken (Epoch := Epoch) (Serial := Serial))) : Prop :=
  forall s k, spec.B S s k + spec.E S s k + spec.W S s k = spec.P S s k

/-- One token partition, with both identity and vector projections. -/
structure UnifiedProjection
    (spec : PlanEpochSpec (Epoch := Epoch) (Serial := Serial)
      (Coord := Coord) (Slot := Slot))
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := EToken (Epoch := Epoch) (Serial := Serial))) : Prop where
  installed : S.ledger.initial = spec.initial
  identity : IdentityProjection S
  weighted : WeightedProjection spec S
  cardinality : (PlanEpochSpec.remainingTokens S).card +
    (PlanEpochSpec.preparedTokens S).card +
      (PlanEpochSpec.withdrawnTokens S).card =
      S.ledger.initial.card

/-- Trusted installation boundary for one static plan epoch.  It deliberately
does not define an executable dynamic mint or epoch rollover. -/
structure TrustedPlanEpochStart
    (spec : PlanEpochSpec (Epoch := Epoch) (Serial := Serial)
      (Coord := Coord) (Slot := Slot))
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := EToken (Epoch := Epoch) (Serial := Serial))) : Prop where
  tokenSafe : TokenSafe S
  installed : S.ledger.initial = spec.initial

theorem linearValid_identityProjection
    {S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := EToken (Epoch := Epoch) (Serial := Serial))}
    (h : S.LinearValid) : IdentityProjection S := by
  intro t ht
  exact h.token_trichotomy ht

theorem tokenSafe_unifiedProjection
    (spec : PlanEpochSpec (Epoch := Epoch) (Serial := Serial)
      (Coord := Coord) (Slot := Slot))
    {S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := EToken (Epoch := Epoch) (Serial := Serial))}
    (hSafe : TokenSafe S) (hInstalled : S.ledger.initial = spec.initial) :
    UnifiedProjection spec S := by
  refine ⟨hInstalled, ?_, spec.weighted_partition_exact S,
    PlanEpochSpec.cardinality_partition S⟩
  exact linearValid_identityProjection hSafe.tokenLinear

/-- Installed token identities are qualified by the single trusted plan
epoch.  The epoch is part of the token itself, rather than mutable ledger
state. -/
theorem unifiedProjection_initial_same_epoch
    {spec : PlanEpochSpec (Epoch := Epoch) (Serial := Serial)
      (Coord := Coord) (Slot := Slot)}
    {S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := EToken (Epoch := Epoch) (Serial := Serial))}
    (h : UnifiedProjection spec S) {t : EToken (Epoch := Epoch)
      (Serial := Serial)} (ht : t ∈ S.ledger.initial) :
    t.epoch = spec.epoch := by
  apply spec.same_epoch t
  rw [← h.installed]
  exact ht

/-- Within one plan epoch, the same immutable spec remains installed and both
projections are reconstructed at every trace endpoint. -/
theorem trace_preserves_unifiedProjection
    (spec : PlanEpochSpec (Epoch := Epoch) (Serial := Serial)
      (Coord := Coord) (Slot := Slot))
    {S S' : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := EToken (Epoch := Epoch) (Serial := Serial))}
    (hTrace : TokenPositiveTrace S S') (hStart : TrustedPlanEpochStart spec S) :
    TokenSafe S' ∧ UnifiedProjection spec S' := by
  have hSafe' := token_positive_trace_preserves_source_decomposed
    hTrace hStart.tokenSafe
  have hInitial := within_plan_epoch_initial_tokens_fixed hTrace
  refine ⟨hSafe', tokenSafe_unifiedProjection spec hSafe' ?_⟩
  exact hInitial.symm.trans hStart.installed

theorem trace_initial_token_same_epoch
    (spec : PlanEpochSpec (Epoch := Epoch) (Serial := Serial)
      (Coord := Coord) (Slot := Slot))
    {S S' : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := EToken (Epoch := Epoch) (Serial := Serial))}
    (hTrace : TokenPositiveTrace S S') (hStart : TrustedPlanEpochStart spec S)
    {t : EToken (Epoch := Epoch) (Serial := Serial)}
    (ht : t ∈ S'.ledger.initial) : t.epoch = spec.epoch := by
  have hUnified := (trace_preserves_unifiedProjection spec hTrace hStart).2
  exact unifiedProjection_initial_same_epoch hUnified ht

/-- Optional bridge to the concrete controller: a current witness carries the
immutable token's root and resource vector. -/
structure CurrentWitnessCoherent
    (spec : PlanEpochSpec (Epoch := Epoch) (Serial := Serial)
      (Coord := Coord) (Slot := Slot))
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := EToken (Epoch := Epoch) (Serial := Serial))) : Prop where
  demand_eq : forall t c, c ∈ S.currentFiber t ->
    forall k, S.controller.lifecycle.auth.demand c k = spec.weight t k
  root_eq : forall t c, c ∈ S.currentFiber t ->
    S.controller.plan.rootSlot c = some (spec.root t)

/-- Optional controller bridge for both remaining claims and durable bound
claims.  This is an explicit assumption, not a claimed consequence of the
older claim-indexed `FullPlanInvariant`. -/
structure WitnessCoherent
    (spec : PlanEpochSpec (Epoch := Epoch) (Serial := Serial)
      (Coord := Coord) (Slot := Slot))
    (S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := EToken (Epoch := Epoch) (Serial := Serial))) : Prop
    extends CurrentWitnessCoherent spec S where
  bound_demand_eq : forall t e c,
    S.controller.lifecycle.opClaim e = some c ->
    S.ledger.origin c = some t ->
    forall k, S.controller.lifecycle.auth.demand c k = spec.weight t k
  bound_root_eq : forall t e c,
    S.controller.lifecycle.opClaim e = some c ->
    S.ledger.origin c = some t ->
    S.controller.plan.rootSlot c = some (spec.root t)

theorem current_witness_matches_spec
    {spec : PlanEpochSpec (Epoch := Epoch) (Serial := Serial)
      (Coord := Coord) (Slot := Slot)}
    {S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := EToken (Epoch := Epoch) (Serial := Serial))}
    (h : CurrentWitnessCoherent spec S) {t : EToken (Epoch := Epoch)
      (Serial := Serial)} {c : Claim} (hc : c ∈ S.currentFiber t) :
    (forall k, S.controller.lifecycle.auth.demand c k = spec.weight t k) ∧
      S.controller.plan.rootSlot c = some (spec.root t) :=
  ⟨h.demand_eq t c hc, h.root_eq t c hc⟩

theorem binding_witness_matches_spec
    {spec : PlanEpochSpec (Epoch := Epoch) (Serial := Serial)
      (Coord := Coord) (Slot := Slot)}
    {S : TokenState (Coord := Coord) (Claim := Claim) (Branch := Branch)
      (Grant := Grant) (Operation := Operation) (Slot := Slot)
      (Token := EToken (Epoch := Epoch) (Serial := Serial))}
    (h : WitnessCoherent spec S) {t : EToken (Epoch := Epoch)
      (Serial := Serial)} {e : Operation} (he : e ∈ S.bindingFiber t) :
    ∃ c, S.controller.lifecycle.opClaim e = some c ∧
      S.ledger.origin c = some t ∧
      (forall k, S.controller.lifecycle.auth.demand c k = spec.weight t k) ∧
      S.controller.plan.rootSlot c = some (spec.root t) := by
  simp only [TokenState.bindingFiber, TokenLedger.bindingFiber,
    Finset.mem_filter, Finset.mem_univ, true_and] at he
  obtain ⟨c, hop, horigin⟩ := Option.bind_eq_some_iff.mp he
  exact ⟨c, hop, horigin, h.bound_demand_eq t e c hop horigin,
    h.bound_root_eq t e c hop horigin⟩

#print axioms PlanEpochSpec.weighted_partition_exact
#print axioms PlanEpochSpec.cardinality_partition
#print axioms PlanEpochSpec.zero_weight_token_visible
#print axioms tokenSafe_unifiedProjection
#print axioms unifiedProjection_initial_same_epoch
#print axioms trace_preserves_unifiedProjection
#print axioms trace_initial_token_same_epoch
#print axioms current_witness_matches_spec
#print axioms binding_witness_matches_spec

end AuthorityContinuity.TokenWeightedAccounting
