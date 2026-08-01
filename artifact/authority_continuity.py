"""Executable model of the paper's authority-continuity contract.

This module is deliberately small and dependency free.  It is an executable
validation model, not a proof assistant development: the accompanying explorer
checks finite instances of the paper definitions and theorems.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import combinations, product
from typing import FrozenSet, Iterable, Iterator, Optional, Sequence, Tuple


Vector = Tuple[int, ...]
Branch = str
Frontier = FrozenSet[Branch]
FrontierFamily = FrozenSet[Frontier]
ReservationBatch = Tuple[Tuple[Branch, Vector], ...]
ResidualProfile = FrozenSet[ReservationBatch]


def _same_dimension(left: Vector, right: Vector) -> None:
    if len(left) != len(right):
        raise ValueError(f"vector dimensions differ: {len(left)} != {len(right)}")


def vector_add(left: Vector, right: Vector) -> Vector:
    _same_dimension(left, right)
    return tuple(x + y for x, y in zip(left, right))


def vector_leq(left: Vector, right: Vector) -> bool:
    _same_dimension(left, right)
    return all(x <= y for x, y in zip(left, right))


def vector_sum(vectors: Iterable[Vector], dimension: int) -> Vector:
    total = (0,) * dimension
    for vector in vectors:
        total = vector_add(total, vector)
    return total


def vector_supremum(vectors: Iterable[Vector], dimension: int) -> Vector:
    result = (0,) * dimension
    for vector in vectors:
        _same_dimension(result, vector)
        result = tuple(max(x, y) for x, y in zip(result, vector))
    return result


def vector_subtract(left: Vector, right: Vector) -> Vector:
    _same_dimension(left, right)
    return tuple(x - y for x, y in zip(left, right))


def vector_infimum(vectors: Iterable[Vector]) -> Vector:
    values = tuple(vectors)
    if not values:
        raise ValueError("infimum requires at least one vector")
    dimension = len(values[0])
    if not dimension:
        raise ValueError("vectors must be nonempty")
    for value in values[1:]:
        if len(value) != dimension:
            raise ValueError("vector dimensions differ")
    return tuple(min(value[index] for value in values) for index in range(dimension))


def powerset(items: Sequence[Branch]) -> Iterator[Frontier]:
    """Yield subsets in cardinality/lexicographic order."""

    ordered = tuple(sorted(items))
    for size in range(len(ordered) + 1):
        for members in combinations(ordered, size):
            yield frozenset(members)


def downward_closure(maximal_frontiers: Iterable[Iterable[Branch]]) -> FrontierFamily:
    frontiers: set[Frontier] = set()
    for maximal in maximal_frontiers:
        frontiers.update(powerset(tuple(maximal)))
    if not frontiers:
        frontiers.add(frozenset())
    return frozenset(frontiers)


def is_downward_closed(family: FrontierFamily) -> bool:
    if not family:
        return False
    return all(subset in family for frontier in family for subset in powerset(tuple(frontier)))


@dataclass(frozen=True, order=True)
class Claim:
    """A globally unique claim and its original tentative owner, if any."""

    claim_id: str
    weight: Vector
    branch: Optional[Branch]

    def __post_init__(self) -> None:
        if not self.claim_id:
            raise ValueError("claim IDs must be nonempty")
        if not self.weight or any(component < 0 for component in self.weight):
            raise ValueError("claim weights must be nonnegative, nonempty vectors")


class NoTopologyRepair(ValueError):
    """Raised when promotion makes even the empty frontier insolvent."""


class ReservationRejected(ValueError):
    """Raised when a reservation is structurally invalid or exceeds residual authority."""


@dataclass(frozen=True)
class GuardTerm:
    """One frozen charge tied to a stable lifecycle lineage.

    ``descendants`` denotes the current leaves that witness retention of this
    lineage.  A frontier pays ``weight`` once when it contains *any* descendant.
    This OR semantics is essential after a live restore: copying the coefficient
    to both leaves would charge a retained old/restored pair twice.
    """

    lineage_id: str
    weight: Vector
    descendants: FrozenSet[Branch]

    def __post_init__(self) -> None:
        if not self.lineage_id:
            raise ValueError("lineage IDs must be nonempty")
        if not self.weight or any(component < 0 for component in self.weight):
            raise ValueError("guard weights must be nonnegative, nonempty vectors")
        if not self.descendants:
            raise ValueError("a live guard term must have at least one descendant")


@dataclass(frozen=True)
class FrozenThresholdGuard:
    """An immutable vector threshold over lineage-membership predicates."""

    guard_id: str
    residual: Vector
    terms: Tuple[GuardTerm, ...]

    def __post_init__(self) -> None:
        if not self.guard_id:
            raise ValueError("guard IDs must be nonempty")
        if not self.residual or any(component < 0 for component in self.residual):
            raise ValueError("guard residual must be a nonnegative, nonempty vector")
        if tuple(sorted(self.terms, key=lambda term: term.lineage_id)) != self.terms:
            raise ValueError("guard terms must be sorted by lineage ID")
        if len({term.lineage_id for term in self.terms}) != len(self.terms):
            raise ValueError("lineage IDs must be unique within a guard")
        for term in self.terms:
            _same_dimension(self.residual, term.weight)

    def charge(self, frontier: Frontier) -> Vector:
        return vector_sum(
            (
                term.weight
                for term in self.terms
                if not term.descendants.isdisjoint(frontier)
            ),
            len(self.residual),
        )

    def allows(self, frontier: Frontier) -> bool:
        return vector_leq(self.charge(frontier), self.residual)

    def transport_live_restore(self, old: Branch, restored: Branch) -> "FrozenThresholdGuard":
        """Transport ``z_old`` as ``z_old OR z_restored`` without double charge."""

        transported = []
        for term in self.terms:
            descendants = term.descendants
            if old in descendants:
                descendants = descendants | frozenset((restored,))
            transported.append(replace(term, descendants=descendants))
        return replace(self, terms=tuple(transported))


@dataclass(frozen=True)
class GuardedContract:
    """A structured/base downward family intersected with frozen guards.

    The executable artifact stores ``base_frontiers`` explicitly because it
    explores only small instances.  A runtime can instead keep the structured
    choice/parallel syntax and compile the conjunction to a ZDD or PB solver.
    """

    base_frontiers: FrontierFamily
    guards: Tuple[FrozenThresholdGuard, ...] = ()

    def __post_init__(self) -> None:
        if not is_downward_closed(self.base_frontiers):
            raise ValueError("contract base must be nonempty and downward closed")
        if len({guard.guard_id for guard in self.guards}) != len(self.guards):
            raise ValueError("guard IDs must be unique")

    def allows(self, frontier: Frontier) -> bool:
        return frontier in self.base_frontiers and all(
            guard.allows(frontier) for guard in self.guards
        )

    @property
    def support(self) -> FrontierFamily:
        return frozenset(
            frontier for frontier in self.base_frontiers if self.allows(frontier)
        )

    def add_guard(self, guard: FrozenThresholdGuard) -> "GuardedContract":
        if any(existing.guard_id == guard.guard_id for existing in self.guards):
            raise ValueError(f"duplicate guard ID: {guard.guard_id}")
        return replace(self, guards=self.guards + (guard,))

    def refine_leaf(
        self,
        old: Branch,
        children: Sequence[Branch],
        *,
        parallel: bool,
    ) -> "GuardedContract":
        """Replace one leaf by exclusive or parallel descendants.

        Every nonempty descendant selection projects to ``old``.  Frozen
        lineage predicates therefore substitute ``z_old`` with the OR of the
        descendant predicates, independently of whether the new siblings are
        exclusive or parallel.  This operation changes topology only; claim
        transfer is checked separately by the lifecycle structural rule.
        """

        descendants = tuple(sorted(children))
        if not descendants or len(set(descendants)) != len(descendants):
            raise ValueError("leaf refinement needs distinct nonempty children")
        if any(not child for child in descendants):
            raise ValueError("branch names must be nonempty")
        all_branches = frozenset().union(*self.base_frontiers)
        if old not in all_branches:
            raise ValueError(f"branch is not present in the contract: {old}")
        collisions = (set(descendants) - {old}) & all_branches
        if collisions:
            raise ValueError(f"refinement children already exist: {sorted(collisions)}")

        if parallel:
            local_frontiers = tuple(powerset(descendants))
        else:
            local_frontiers = (frozenset(),) + tuple(
                frozenset((child,)) for child in descendants
            )
        expanded: set[Frontier] = set()
        for frontier in self.base_frontiers:
            if old not in frontier:
                expanded.add(frontier)
                continue
            rest = frontier - frozenset((old,))
            expanded.update(rest | local for local in local_frontiers)

        transported_guards = []
        replacement = frozenset(descendants)
        for guard in self.guards:
            transported_terms = []
            for term in guard.terms:
                term_descendants = term.descendants
                if old in term_descendants:
                    term_descendants = (
                        term_descendants - frozenset((old,))
                    ) | replacement
                transported_terms.append(
                    replace(term, descendants=term_descendants)
                )
            transported_guards.append(
                replace(guard, terms=tuple(transported_terms))
            )
        return GuardedContract(
            base_frontiers=frozenset(expanded),
            guards=tuple(transported_guards),
        )

    def transport_live_restore(self, old: Branch, restored: Branch) -> "GuardedContract":
        """Refine leaf ``old`` to ``old || restored`` contextually.

        A new frontier with at least one of the two descendants projects to an
        old frontier containing ``old``.  Old guards use OR-lineage transport.
        """

        return self.refine_leaf(
            old,
            (old, restored),
            parallel=True,
        )


@dataclass(frozen=True)
class State:
    """Finite abstract state Sigma=(G,D,Q,Phi).

    ``durable`` represents D.  ``conditional`` flattens the branch-indexed Q:
    each conditional claim carries its unique owner in ``Claim.branch``.
    Terminal IDs X do not affect demand and are therefore omitted here.
    """

    grant: Vector
    durable: Tuple[Claim, ...]
    conditional: Tuple[Claim, ...]
    frontiers: FrontierFamily

    def __post_init__(self) -> None:
        if not self.grant or any(component < 0 for component in self.grant):
            raise ValueError("grant must be a nonnegative, nonempty vector")
        if not is_downward_closed(self.frontiers):
            raise ValueError("frontier family must be nonempty and downward closed")
        claims = self.durable + self.conditional
        if len({claim.claim_id for claim in claims}) != len(claims):
            raise ValueError("claim IDs must be globally unique")
        for claim in claims:
            _same_dimension(self.grant, claim.weight)
        if any(claim.branch is None for claim in self.conditional):
            raise ValueError("each conditional claim must have a branch owner")
        if tuple(sorted(self.durable)) != self.durable:
            raise ValueError("durable claims must be sorted canonically")
        if tuple(sorted(self.conditional)) != self.conditional:
            raise ValueError("conditional claims must be sorted canonically")

    @property
    def dimension(self) -> int:
        return len(self.grant)

    @property
    def durable_demand(self) -> Vector:
        return vector_sum((claim.weight for claim in self.durable), self.dimension)

    def frontier_demand(self, frontier: Frontier) -> Vector:
        """Return q(C), excluding already durable demand."""

        return vector_sum(
            (
                claim.weight
                for claim in self.conditional
                if claim.branch is not None and claim.branch in frontier
            ),
            self.dimension,
        )

    def frontier_load(self, frontier: Frontier) -> Vector:
        """Return d+q(C)."""

        if frontier not in self.frontiers:
            raise ValueError(f"not an admitted frontier: {sorted(frontier)}")
        return vector_add(self.durable_demand, self.frontier_demand(frontier))

    @property
    def need(self) -> Vector:
        """Return componentwise supremum of d+q(C) over Phi."""

        return vector_supremum(
            (self.frontier_load(frontier) for frontier in self.frontiers),
            self.dimension,
        )

    @property
    def authority_continuous(self) -> bool:
        return all(
            vector_leq(self.frontier_load(frontier), self.grant)
            for frontier in self.frontiers
        )

    def with_frontiers(self, frontiers: FrontierFamily) -> "State":
        return replace(self, frontiers=frontiers)

    def _claims_to_promote(self, claim_ids: Iterable[str]) -> Tuple[Claim, ...]:
        requested = frozenset(claim_ids)
        if not requested:
            raise ValueError("promotion set must be nonempty")
        selected = tuple(
            claim for claim in self.conditional if claim.claim_id in requested
        )
        if {claim.claim_id for claim in selected} != requested:
            missing = requested - {claim.claim_id for claim in selected}
            raise ValueError(f"claims are not tentative in this state: {sorted(missing)}")
        return selected

    def promote_plain(self, claim_ids: Iterable[str]) -> "State":
        """Move claims Q->D without changing Phi or checking the target."""

        selected = self._claims_to_promote(claim_ids)
        selected_ids = {claim.claim_id for claim in selected}
        return State(
            grant=self.grant,
            durable=tuple(sorted(self.durable + selected)),
            conditional=tuple(
                claim for claim in self.conditional if claim.claim_id not in selected_ids
            ),
            frontiers=self.frontiers,
        )

    def maximal_safe_support(self, claim_ids: Iterable[str]) -> FrontierFamily:
        """Compute Phi*_S for a nonempty set S of tentative claims."""

        promoted = self.promote_plain(claim_ids)
        return frozenset(
            frontier
            for frontier in self.frontiers
            if vector_leq(promoted.frontier_load(frontier), self.grant)
        )

    def promote_maximally(self, claim_ids: Iterable[str]) -> "State":
        """Promote claims and retain the unique largest safe subfamily."""

        claim_ids = tuple(claim_ids)
        promoted = self.promote_plain(claim_ids)
        support = frozenset(
            frontier
            for frontier in self.frontiers
            if vector_leq(promoted.frontier_load(frontier), self.grant)
        )
        if not support:
            raise NoTopologyRepair(
                "promotion overloads the empty frontier; topology restriction cannot repair it"
            )
        return promoted.with_frontiers(support)


def make_state(
    grant: Vector,
    *,
    durable: Iterable[Claim] = (),
    conditional: Iterable[Claim] = (),
    frontiers: FrontierFamily,
) -> State:
    """Construct a state while canonicalizing claim order."""

    return State(
        grant=grant,
        durable=tuple(sorted(durable)),
        conditional=tuple(sorted(conditional)),
        frontiers=frontiers,
    )


def supported_branches(state: State) -> FrozenSet[Branch]:
    """Branches occurring in at least one durability configuration."""

    return frozenset().union(*state.frontiers)


def owner_support_well_formed(
    state: State,
    support: Optional[FrontierFamily] = None,
) -> bool:
    """Whether every conditional claim owner occurs in the relevant support."""

    family = state.frontiers if support is None else support
    if not family or not family <= state.frontiers or not is_downward_closed(family):
        return False
    supported = frozenset().union(*family)
    return all(
        claim.branch is not None and claim.branch in supported
        for claim in state.conditional
    )


def claims_have_owner_support(
    state: State,
    claim_ids: Iterable[str],
    support: FrontierFamily,
) -> bool:
    """Final-owner-support predicate for a fixed promotion batch."""

    requested = frozenset(claim_ids)
    claims = {
        claim.claim_id: claim
        for claim in state.durable + state.conditional
        if claim.claim_id in requested
    }
    if set(claims) != requested or not support:
        return False
    supported = frozenset().union(*support)
    return all(
        claim.branch is not None and claim.branch in supported
        for claim in claims.values()
    )


@dataclass(frozen=True)
class SupportCleanup:
    state: State
    tombstoned_branches: FrozenSet[Branch]
    terminal_claim_ids: FrozenSet[str]


def cleanup_unsupported_owners(
    state: State,
    support: FrontierFamily,
) -> SupportCleanup:
    """Apply deterministic terminal cleanup induced by a guarded support.

    ``state.frontiers`` remains the guard's base family; ``support`` is its
    denotation.  The returned terminal IDs model X but carry no demand in this
    finite artifact.
    """

    if not support or not support <= state.frontiers or not is_downward_closed(support):
        raise ValueError("cleanup support must be a nonempty downward subfamily")
    tentative_owners = frozenset(
        claim.branch for claim in state.conditional if claim.branch is not None
    )
    live_after = frozenset().union(*support)
    tombstoned = tentative_owners - live_after
    terminal = frozenset(
        claim.claim_id
        for claim in state.conditional
        if claim.branch in tombstoned
    )
    cleaned = make_state(
        state.grant,
        durable=state.durable,
        conditional=(
            claim
            for claim in state.conditional
            if claim.branch not in tombstoned
        ),
        frontiers=state.frontiers,
    )
    return SupportCleanup(cleaned, tombstoned, terminal)


def make_reservation_batch(
    entries: Iterable[tuple[Branch, Vector]],
) -> ReservationBatch:
    """Build a canonical branch-indexed reservation batch."""

    materialized = tuple(entries)
    if len({branch for branch, _ in materialized}) != len(materialized):
        raise ValueError("a reservation batch may mention each branch at most once")
    dimension: Optional[int] = None
    for branch, weight in materialized:
        if not branch:
            raise ValueError("batch branches must be nonempty")
        if not weight or any(component < 0 for component in weight):
            raise ValueError("batch weights must be nonnegative, nonempty vectors")
        if dimension is None:
            dimension = len(weight)
        elif len(weight) != dimension:
            raise ValueError("batch vector dimensions differ")
    return tuple(sorted(materialized, key=lambda entry: entry[0]))


def _validate_batch_for_state(state: State, batch: ReservationBatch) -> None:
    canonical = make_reservation_batch(batch)
    if canonical != batch:
        raise ValueError("reservation batches must use canonical branch order")
    unsupported = {branch for branch, _ in batch} - supported_branches(state)
    if unsupported:
        raise ReservationRejected(f"unsupported branches: {sorted(unsupported)}")
    for _, weight in batch:
        _same_dimension(state.grant, weight)


def add_reservation_batches(
    left: ReservationBatch,
    right: ReservationBatch,
) -> ReservationBatch:
    """Pointwise addition of sparse branch-indexed batches."""

    left = make_reservation_batch(left)
    right = make_reservation_batch(right)
    weights: dict[Branch, Vector] = dict(left)
    for branch, weight in right:
        if branch in weights:
            weights[branch] = vector_add(weights[branch], weight)
        else:
            weights[branch] = weight
    return make_reservation_batch(weights.items())


def enumerate_reservation_batches(
    branches: Sequence[Branch],
    dimension: int,
    component_bound: int,
) -> Iterator[ReservationBatch]:
    """Enumerate the box [0,M]^(B x K) in deterministic order."""

    ordered = tuple(sorted(branches))
    if len(set(ordered)) != len(ordered):
        raise ValueError("branch order contains duplicates")
    if dimension <= 0 or component_bound < 0:
        raise ValueError("dimension must be positive and bound nonnegative")
    width = len(ordered) * dimension
    for flat in product(range(component_bound + 1), repeat=width):
        yield make_reservation_batch(
            (
                branch,
                tuple(flat[index * dimension : (index + 1) * dimension]),
            )
            for index, branch in enumerate(ordered)
        )


def configuration_slack(state: State, frontier: Frontier) -> Vector:
    """Return s_Sigma(C)=G-d-q(C)."""

    return vector_subtract(state.grant, state.frontier_load(frontier))


def branch_headroom(state: State, branch: Branch) -> Optional[Vector]:
    """Return H_Sigma(b), or None for bottom/unsupported."""

    containing = tuple(
        frontier for frontier in state.frontiers if branch in frontier
    )
    if not containing:
        return None
    return vector_infimum(
        configuration_slack(state, frontier) for frontier in containing
    )


def headroom_profile(
    state: State,
    branches: Sequence[Branch],
) -> Tuple[Tuple[Branch, Optional[Vector]], ...]:
    return tuple((branch, branch_headroom(state, branch)) for branch in sorted(branches))


def headroom_box_profile(
    state: State,
    branches: Sequence[Branch],
) -> ResidualProfile:
    """Enumerate the finite rectangular box induced by supported headrooms."""

    ordered = tuple(sorted(branches))
    headrooms = {branch: branch_headroom(state, branch) for branch in ordered}
    if any(value is None for value in headrooms.values()):
        raise ValueError("headroom box requires every listed branch to be supported")
    concrete = {
        branch: value
        for branch, value in headrooms.items()
        if value is not None
    }
    component_bound = max(
        (
            component
            for value in concrete.values()
            for component in value
        ),
        default=0,
    )
    return frozenset(
        batch
        for batch in enumerate_reservation_batches(
            ordered, state.dimension, component_bound
        )
        if all(
            vector_leq(weight, concrete[branch])
            for branch, weight in batch
        )
    )


def headroom_corner_satisfies_slack(
    state: State,
    branches: Sequence[Branch],
) -> bool:
    """Whether the all-headrooms corner satisfies every frontier inequality."""

    corner_entries = []
    for branch in sorted(branches):
        headroom = branch_headroom(state, branch)
        if headroom is None:
            raise ValueError("headroom corner requires every listed branch to be supported")
        corner_entries.append((branch, headroom))
    corner = make_reservation_batch(corner_entries)
    return all(
        vector_leq(
            batch_configuration_demand(corner, frontier, state.dimension),
            configuration_slack(state, frontier),
        )
        for frontier in state.frontiers
    )


def reserve_admitted_by_headroom(
    state: State,
    branch: Branch,
    weight: Vector,
) -> bool:
    _same_dimension(state.grant, weight)
    if any(component < 0 for component in weight):
        raise ValueError("reservation demand must be nonnegative")
    headroom = branch_headroom(state, branch)
    return headroom is not None and vector_leq(weight, headroom)


def batch_configuration_demand(
    batch: ReservationBatch,
    frontier: Frontier,
    dimension: int,
) -> Vector:
    return vector_sum(
        (weight for branch, weight in batch if branch in frontier),
        dimension,
    )


def batch_in_residual(state: State, batch: ReservationBatch) -> bool:
    """Exact, unbounded membership predicate x in R_Sigma."""

    _validate_batch_for_state(state, batch)
    return all(
        vector_leq(
            batch_configuration_demand(batch, frontier, state.dimension),
            configuration_slack(state, frontier),
        )
        for frontier in state.frontiers
    )


def reservation_target(
    state: State,
    batch: ReservationBatch,
    claim_prefix: str,
) -> State:
    """Construct the target of a structurally valid batch without admitting it."""

    _validate_batch_for_state(state, batch)
    if not claim_prefix:
        raise ValueError("claim prefix must be nonempty")
    existing_ids = {claim.claim_id for claim in state.durable + state.conditional}
    additions = []
    for index, (branch, weight) in enumerate(batch):
        if not any(weight):
            continue
        claim_id = f"{claim_prefix}:{index}:{branch}"
        if claim_id in existing_ids:
            raise ValueError(f"generated claim ID already exists: {claim_id}")
        additions.append(Claim(claim_id, weight, branch))
    return make_state(
        state.grant,
        durable=state.durable,
        conditional=state.conditional + tuple(additions),
        frontiers=state.frontiers,
    )


def batch_admitted_by_target(state: State, batch: ReservationBatch) -> bool:
    """Admission by constructing the proposed target and checking AC directly."""

    try:
        target = reservation_target(state, batch, "target-check")
    except ReservationRejected:
        return False
    return target.authority_continuous


def reserve_batch(
    state: State,
    batch: ReservationBatch,
    claim_prefix: str,
) -> State:
    """Admit a batch exactly when it belongs to the correlated residual."""

    if not batch_in_residual(state, batch):
        raise ReservationRejected("batch is outside the residual authorization profile")
    return reservation_target(state, batch, claim_prefix)


def enumerated_residual_profile(
    state: State,
    branches: Sequence[Branch],
    component_bound: int,
) -> ResidualProfile:
    """Return R_Sigma intersected with the finite box [0,M]^(B x K)."""

    ordered = tuple(sorted(branches))
    if not set(ordered) <= supported_branches(state):
        raise ValueError("enumerated profile branches must all be supported")
    return frozenset(
        batch
        for batch in enumerate_reservation_batches(
            ordered, state.dimension, component_bound
        )
        if batch_in_residual(state, batch)
    )


def bounded_residual_derivative(
    state: State,
    accepted: ReservationBatch,
    branches: Sequence[Branch],
    successor_bound: int,
) -> tuple[ResidualProfile, ResidualProfile, int]:
    """Compare the residual derivative without a truncation artifact.

    The successor side enumerates y in [0,M].  The parent profile is enumerated
    through M+max(x), which contains every x+y queried on the right-hand side.
    Returning that expanded parent bound makes the finite-domain treatment
    explicit rather than incorrectly deriving from R intersected with [0,M].
    """

    _validate_batch_for_state(state, accepted)
    if not batch_in_residual(state, accepted):
        raise ReservationRejected("derivative requires an accepted batch")
    if successor_bound < 0:
        raise ValueError("successor bound must be nonnegative")
    max_component = max(
        (component for _, weight in accepted for component in weight),
        default=0,
    )
    parent_bound = successor_bound + max_component
    parent_profile = enumerated_residual_profile(state, branches, parent_bound)
    successor = reserve_batch(state, accepted, "derivative")
    successor_profile = enumerated_residual_profile(
        successor, branches, successor_bound
    )
    candidates = tuple(
        enumerate_reservation_batches(branches, state.dimension, successor_bound)
    )
    derivative_profile = frozenset(
        candidate
        for candidate in candidates
        if add_reservation_batches(accepted, candidate) in parent_profile
    )
    return successor_profile, derivative_profile, parent_bound


def knowledge_residual_intersection(
    states: Sequence[State],
    branches: Sequence[Branch],
    component_bound: int,
) -> ResidualProfile:
    """Finite-box form of the greatest sound knowledge-based batch checker."""

    if not states:
        raise ValueError("knowledge set must be nonempty")
    profiles = [
        enumerated_residual_profile(state, branches, component_bound)
        for state in states
    ]
    return frozenset.intersection(*profiles)


def exact_repair_guard(state: State, guard_id: str) -> FrozenThresholdGuard:
    """Freeze the compact threshold whose models are exactly safe frontiers.

    Coefficients are copied from the *current* conditional bundles once.  They
    do not follow later withdrawal or reservation.  Such later operations may
    explicitly replace/relax a guard after target admission, but cannot mutate
    the meaning of an already durable lifecycle restriction.
    """

    residual = tuple(
        grant - durable
        for grant, durable in zip(state.grant, state.durable_demand)
    )
    if any(component < 0 for component in residual):
        raise NoTopologyRepair(
            "durable demand exceeds the grant; even the empty frontier is unsafe"
        )
    branches = sorted(
        {
            claim.branch
            for claim in state.conditional
            if claim.branch is not None
        }
    )
    terms = []
    for branch in branches:
        weight = vector_sum(
            (
                claim.weight
                for claim in state.conditional
                if claim.branch == branch
            ),
            state.dimension,
        )
        if any(weight):
            terms.append(
                GuardTerm(
                    lineage_id=f"{guard_id}:{branch}",
                    weight=weight,
                    descendants=frozenset((branch,)),
                )
            )
    return FrozenThresholdGuard(
        guard_id=guard_id,
        residual=residual,
        terms=tuple(sorted(terms, key=lambda term: term.lineage_id)),
    )


def install_exact_repair(
    state: State,
    contract: GuardedContract,
    guard_id: str,
) -> GuardedContract:
    """Intersect a contract with the exact authority-safe target support."""

    if state.frontiers != contract.base_frontiers:
        raise ValueError("state frontiers and contract base frontiers must agree")
    return contract.add_guard(exact_repair_guard(state, guard_id))


def guarded_authority_continuous(state: State, contract: GuardedContract) -> bool:
    if state.frontiers != contract.base_frontiers:
        raise ValueError("state frontiers and contract base frontiers must agree")
    return all(
        vector_leq(state.frontier_load(frontier), state.grant)
        for frontier in contract.support
    )


def promote_with_exact_guard(
    state: State,
    contract: GuardedContract,
    claim_ids: Iterable[str],
    guard_id: str,
) -> tuple[State, GuardedContract]:
    """Promote a batch and durably install its exact maximal safe support."""

    target = state.promote_plain(claim_ids)
    repaired = install_exact_repair(target, contract, guard_id)
    if not guarded_authority_continuous(target, repaired):
        raise AssertionError("exact repair construction failed its support invariant")
    return target, repaired


def withdraw_tentative(state: State, claim_id: str) -> State:
    """Move a tentative ID to terminal X (which carries no demand here)."""

    matches = [claim for claim in state.conditional if claim.claim_id == claim_id]
    if len(matches) != 1:
        raise ValueError(f"claim is not uniquely tentative: {claim_id}")
    return make_state(
        state.grant,
        durable=state.durable,
        conditional=(
            claim for claim in state.conditional if claim.claim_id != claim_id
        ),
        frontiers=state.frontiers,
    )


@dataclass(frozen=True)
class WitnessedPromotion:
    state: State
    tombstoned_branches: FrozenSet[Branch]
    terminal_claim_ids: FrozenSet[str]


def witnessed_promote_with_tombstones(state: State, claim_id: str) -> WitnessedPromotion:
    """Implement the conservative condition-on-owner promotion shortcut.

    This operation is intentionally distinct from exact threshold repair.  It
    tombstones alternatives outside Phi-down-owner, so serializing two escapes
    from exclusive owners can invalidate the second operation even when their
    abstract exact batch is well defined.
    """

    selected = state._claims_to_promote((claim_id,))[0]
    assert selected.branch is not None
    owner = selected.branch
    witnesses = tuple(frontier for frontier in state.frontiers if owner in frontier)
    if not witnesses:
        raise ValueError(f"claim owner is not selectable: {owner}")
    conditioned = frozenset(
        subset
        for witness in witnesses
        for subset in powerset(tuple(witness))
    )
    old_branches = frozenset().union(*state.frontiers)
    retained_branches = frozenset().union(*conditioned)
    tombstoned = old_branches - retained_branches
    terminal_claims = frozenset(
        claim.claim_id
        for claim in state.conditional
        if claim.branch in tombstoned
    )
    target = make_state(
        state.grant,
        durable=state.durable + (selected,),
        conditional=(
            claim
            for claim in state.conditional
            if claim.claim_id != claim_id and claim.branch not in tombstoned
        ),
        frontiers=conditioned,
    )
    if not target.authority_continuous:
        raise AssertionError("witnessed promotion must preserve authority continuity")
    return WitnessedPromotion(target, tombstoned, terminal_claims)


def independent_set_family(
    branches: Sequence[Branch],
    conflicts: Iterable[tuple[Branch, Branch]],
) -> FrontierFamily:
    """Return the downward family represented by a pairwise conflict graph."""

    edge_set = {frozenset(edge) for edge in conflicts}
    return frozenset(
        frontier
        for frontier in powerset(tuple(branches))
        if all(not edge <= frontier for edge in edge_set)
    )


def is_conflict_graph_representable(
    family: FrontierFamily,
    branches: Sequence[Branch],
) -> bool:
    """Brute-force whether a small family is the independent sets of any graph."""

    ordered = tuple(sorted(branches))
    possible_edges = tuple(combinations(ordered, 2))
    for mask in range(1 << len(possible_edges)):
        edges = tuple(
            edge
            for index, edge in enumerate(possible_edges)
            if mask & (1 << index)
        )
        if independent_set_family(ordered, edges) == family:
            return True
    return False


def snapshot_local_impossibility_litmus() -> dict[str, object]:
    """Apply one identical fresh Reserve to replace/live pre-states."""

    empty: Frontier = frozenset()
    replace_pre = make_state(
        (1,),
        frontiers=frozenset((empty, frozenset(("restored",)))),
    )
    live_pre = make_state(
        (1,),
        conditional=(Claim("old", (1,), "old"),),
        frontiers=downward_closure((("old", "restored"),)),
    )
    proposal = make_reservation_batch((("restored", (1,)),))
    replace_successor = reservation_target(
        replace_pre, proposal, "same-fresh-reserve"
    )
    live_successor = reservation_target(
        live_pre, proposal, "same-fresh-reserve"
    )
    return {
        "snapshot": "identical-reconstructed-bytes",
        "proposal": {
            "rule": "Reserve",
            "branch": "restored",
            "weight": [1],
            "fresh_claim_id": "same-fresh-reserve:0:restored",
        },
        "replace": {
            "pre": {
                "safe": replace_pre.authority_continuous,
                "need": list(replace_pre.need),
                "conditional_claim_ids": [],
            },
            "successor": {
                "safe": replace_successor.authority_continuous,
                "need": list(replace_successor.need),
                "decision": "accept-for-maximal-permissiveness",
            },
        },
        "live": {
            "pre": {
                "safe": live_pre.authority_continuous,
                "need": list(live_pre.need),
                "conditional_claim_ids": ["old"],
            },
            "successor": {
                "safe": live_successor.authority_continuous,
                "need": list(live_successor.need),
                "decision": "reject-for-soundness",
                "violating_frontier": ["old", "restored"],
            },
        },
    }


def plain_escape_counterexample() -> tuple[State, State, Frontier]:
    """Return the one-unit exclusive-choice counterexample."""

    family = downward_closure((("left",), ("right",)))
    source = make_state(
        (1,),
        conditional=(
            Claim("left-use", (1,), "left"),
            Claim("right-use", (1,), "right"),
        ),
        frontiers=family,
    )
    target = source.promote_plain(("left-use",))
    return source, target, frozenset(("right",))


class LifecycleRejected(ValueError):
    """Raised when a lifecycle proposal is not enabled."""


@dataclass(frozen=True, order=True)
class Ticket:
    """One crash-persistent operation ticket in J.

    ``retry_mode`` records a declared adapter premise; this finite model does
    not test a real sink's deduplication or aggregate-demand enforcement.
    """

    operation_id: str
    claim_id: str
    phase: str
    retry_mode: str

    def __post_init__(self) -> None:
        if not self.operation_id or not self.claim_id:
            raise ValueError("ticket operation and claim IDs must be nonempty")
        if self.phase not in {"prepared", "inflight", "uncertain"}:
            raise ValueError(f"invalid ticket phase: {self.phase}")
        if self.retry_mode not in {"deduplicated", "aggregate-bounded"}:
            raise ValueError(f"invalid retry mode: {self.retry_mode}")


@dataclass(frozen=True, order=True)
class Receipt:
    """One settled protected operation in R."""

    operation_id: str
    claim_id: str
    outcome: str

    def __post_init__(self) -> None:
        if not self.operation_id or not self.claim_id or not self.outcome:
            raise ValueError("receipt fields must be nonempty")


@dataclass(frozen=True)
class LifecycleState:
    """Executable finite state for epochs, tickets, receipts, and terminal IDs.

    The authority state and guarded contract model ``(G,D,Q,T)``.  The
    remaining fields make the paper's ``(N,J,R,X)`` explicit.  This artifact
    keeps epoch bindings for terminal claims so revocation history cannot be
    reconstructed away after a restore.
    """

    authority: State
    contract: GuardedContract
    epochs: Tuple[str, ...]
    claim_epochs: Tuple[Tuple[str, str], ...]
    closed_epochs: FrozenSet[str] = frozenset()
    tickets: Tuple[Ticket, ...] = ()
    receipts: Tuple[Receipt, ...] = ()
    terminal_claim_ids: FrozenSet[str] = frozenset()
    tombstoned_branches: FrozenSet[Branch] = frozenset()

    def __post_init__(self) -> None:
        if self.authority.frontiers != self.contract.base_frontiers:
            raise ValueError("authority frontiers and contract base must agree")
        if not guarded_authority_continuous(self.authority, self.contract):
            raise ValueError("lifecycle state violates guarded authority continuity")
        if not owner_support_well_formed(self.authority, self.contract.support):
            raise ValueError("every tentative owner must have guarded support")
        if not self.epochs or tuple(sorted(set(self.epochs))) != self.epochs:
            raise ValueError("epochs must be a sorted, unique, nonempty tuple")
        if not self.closed_epochs <= frozenset(self.epochs):
            raise ValueError("closed epochs must be declared")
        if tuple(sorted(self.claim_epochs)) != self.claim_epochs:
            raise ValueError("claim epoch bindings must be sorted canonically")
        epoch_map = dict(self.claim_epochs)
        if len(epoch_map) != len(self.claim_epochs):
            raise ValueError("each claim must have exactly one epoch binding")
        known_claims = {
            claim.claim_id
            for claim in self.authority.durable + self.authority.conditional
        } | set(self.terminal_claim_ids)
        if set(epoch_map) != known_claims:
            raise ValueError("epoch bindings must cover active and terminal claims")
        if not set(epoch_map.values()) <= set(self.epochs):
            raise ValueError("claim epoch binding names an undeclared epoch")
        closed_tentative = {
            claim.claim_id
            for claim in self.authority.conditional
            if epoch_map[claim.claim_id] in self.closed_epochs
        }
        if closed_tentative:
            raise ValueError(
                "tentative claims cannot remain in closed epochs: "
                f"{sorted(closed_tentative)}"
            )
        if tuple(sorted(self.tickets)) != self.tickets:
            raise ValueError("tickets must be sorted canonically")
        if tuple(sorted(self.receipts)) != self.receipts:
            raise ValueError("receipts must be sorted canonically")
        operation_ids = [
            entry.operation_id for entry in self.tickets + self.receipts
        ]
        if len(set(operation_ids)) != len(operation_ids):
            raise ValueError("operation IDs must be unique across tickets and receipts")
        operation_claims = [
            entry.claim_id for entry in self.tickets + self.receipts
        ]
        if len(set(operation_claims)) != len(operation_claims):
            raise ValueError("a durable claim may seal at most one operation")
        durable_ids = {claim.claim_id for claim in self.authority.durable}
        if not set(operation_claims) <= durable_ids:
            raise ValueError("tickets and receipts must reference durable claims")
        active_ids = {
            claim.claim_id
            for claim in self.authority.durable + self.authority.conditional
        }
        if active_ids & set(self.terminal_claim_ids):
            raise ValueError("terminal claim IDs cannot remain active")
        if any(not branch for branch in self.tombstoned_branches):
            raise ValueError("tombstoned branch names must be nonempty")
        retained_by_tombstoned = {
            claim.claim_id
            for claim in self.authority.conditional
            if claim.branch is not None and not self.branch_is_open(claim.branch)
        }
        if retained_by_tombstoned:
            raise ValueError(
                "tombstoned branches cannot retain tentative claims: "
                f"{sorted(retained_by_tombstoned)}"
            )
        reopened_in_support = (
            frozenset().union(*self.contract.support)
            & self.tombstoned_branches
        )
        if reopened_in_support:
            raise ValueError(
                "tombstoned branch epochs cannot re-enter contract support: "
                f"{sorted(reopened_in_support)}"
            )

    def branch_is_open(self, branch: Branch) -> bool:
        """Interpret the monotone tombstone set as branch-epoch status."""

        return branch not in self.tombstoned_branches

    @property
    def operation_ids(self) -> FrozenSet[str]:
        return frozenset(
            entry.operation_id for entry in self.tickets + self.receipts
        )

    def ticket(self, operation_id: str) -> Ticket:
        matches = [
            ticket for ticket in self.tickets
            if ticket.operation_id == operation_id
        ]
        if len(matches) != 1:
            raise LifecycleRejected(f"no live ticket for operation: {operation_id}")
        return matches[0]


@dataclass(frozen=True)
class LifecycleStep:
    """A transition plus logical-release and physical-attempt metadata.

    The first Dispatch releases one logical operation.  Dispatch and Retry
    both carry the stable physical attempt ID; retries do not allocate another
    claim or logical operation.
    """

    state: LifecycleState
    attempt: Optional[Tuple[str, str]] = None
    releases_logical_operation: bool = False

    @property
    def abstract_effect(self) -> Optional[Tuple[str, str]]:
        """Compatibility view: only first Dispatch releases a logical operation."""

        return self.attempt if self.releases_logical_operation else None

    @property
    def physical_attempt_id(self) -> Optional[str]:
        return self.attempt[0] if self.attempt is not None else None


def make_lifecycle_state(
    authority: State,
    *,
    contract: Optional[GuardedContract] = None,
    epochs: Sequence[str] = ("epoch-0",),
    claim_epochs: Optional[Iterable[Tuple[str, str]]] = None,
    closed_epochs: Iterable[str] = (),
    tickets: Iterable[Ticket] = (),
    receipts: Iterable[Receipt] = (),
    terminal_claim_ids: Iterable[str] = (),
    tombstoned_branches: Iterable[Branch] = (),
) -> LifecycleState:
    """Construct a canonical lifecycle state for tests and finite exploration."""

    concrete_contract = contract or GuardedContract(authority.frontiers)
    concrete_epochs = tuple(sorted(set(epochs)))
    terminal = frozenset(terminal_claim_ids)
    if claim_epochs is None:
        if len(concrete_epochs) != 1:
            raise ValueError("multiple epochs require explicit claim bindings")
        only_epoch = concrete_epochs[0]
        claim_epochs = (
            (claim_id, only_epoch)
            for claim_id in (
                {
                    claim.claim_id
                    for claim in authority.durable + authority.conditional
                }
                | set(terminal)
            )
        )
    return LifecycleState(
        authority=authority,
        contract=concrete_contract,
        epochs=concrete_epochs,
        claim_epochs=tuple(sorted(claim_epochs)),
        closed_epochs=frozenset(closed_epochs),
        tickets=tuple(sorted(tickets)),
        receipts=tuple(sorted(receipts)),
        terminal_claim_ids=terminal,
        tombstoned_branches=frozenset(tombstoned_branches),
    )


def prepare_operations(
    lifecycle: LifecycleState,
    bindings: Iterable[Tuple[str, str, str]],
    guard_id: str,
) -> LifecycleState:
    """Atomically promote claims, install exact support, and create tickets.

    Each binding is ``(claim_id, stable_operation_id, retry_mode)``.  The
    operation ID is checked against both live tickets and settled receipts
    before any protected attempt can occur.
    """

    materialized = tuple(bindings)
    if not materialized:
        raise LifecycleRejected("Prepare requires at least one claim")
    claim_ids = tuple(claim_id for claim_id, _, _ in materialized)
    operation_ids = tuple(operation_id for _, operation_id, _ in materialized)
    if len(set(claim_ids)) != len(claim_ids):
        raise LifecycleRejected("Prepare claim bindings must be injective")
    if len(set(operation_ids)) != len(operation_ids):
        raise LifecycleRejected("Prepare operation bindings must be injective")
    reused = set(operation_ids) & set(lifecycle.operation_ids)
    if reused:
        raise LifecycleRejected(f"operation IDs are not fresh: {sorted(reused)}")
    epoch_map = dict(lifecycle.claim_epochs)
    conditional_ids = {
        claim.claim_id for claim in lifecycle.authority.conditional
    }
    missing = set(claim_ids) - conditional_ids
    if missing:
        raise LifecycleRejected(f"claims are not tentative: {sorted(missing)}")
    claims_by_id = {
        claim.claim_id: claim for claim in lifecycle.authority.conditional
    }
    tombstoned = {
        claim_id
        for claim_id in claim_ids
        if claims_by_id[claim_id].branch is not None
        and not lifecycle.branch_is_open(claims_by_id[claim_id].branch)
    }
    if tombstoned:
        raise LifecycleRejected(
            f"claim owners are tombstoned: {sorted(tombstoned)}"
        )
    closed = {
        claim_id
        for claim_id in claim_ids
        if epoch_map[claim_id] in lifecycle.closed_epochs
    }
    if closed:
        raise LifecycleRejected(f"claim epochs are closed: {sorted(closed)}")
    try:
        promoted, repaired = promote_with_exact_guard(
            lifecycle.authority,
            lifecycle.contract,
            claim_ids,
            guard_id,
        )
    except (NoTopologyRepair, ValueError) as error:
        raise LifecycleRejected(str(error)) from error
    cleanup = cleanup_unsupported_owners(promoted, repaired.support)
    new_tickets = tuple(
        Ticket(operation_id, claim_id, "prepared", retry_mode)
        for claim_id, operation_id, retry_mode in materialized
    )
    return replace(
        lifecycle,
        authority=cleanup.state,
        contract=repaired,
        tickets=tuple(sorted(lifecycle.tickets + new_tickets)),
        terminal_claim_ids=(
            lifecycle.terminal_claim_ids | cleanup.terminal_claim_ids
        ),
        tombstoned_branches=(
            lifecycle.tombstoned_branches | cleanup.tombstoned_branches
        ),
    )


def dispatch_operation(
    lifecycle: LifecycleState,
    operation_id: str,
) -> LifecycleStep:
    """Persist ``prepared -> inflight`` before the first protected attempt."""

    ticket = lifecycle.ticket(operation_id)
    if ticket.phase != "prepared":
        raise LifecycleRejected(
            f"first Dispatch requires a prepared ticket: {operation_id}"
        )
    inflight = replace(ticket, phase="inflight")
    target = replace(
        lifecycle,
        tickets=tuple(sorted(
            inflight if current == ticket else current
            for current in lifecycle.tickets
        )),
    )
    return LifecycleStep(
        state=target,
        attempt=(operation_id, ticket.claim_id),
        releases_logical_operation=True,
    )


def retry_operation(
    lifecycle: LifecycleState,
    operation_id: str,
) -> LifecycleStep:
    """Retry under the same ID, changing ``uncertain`` back to ``inflight``."""

    ticket = lifecycle.ticket(operation_id)
    if ticket.phase not in {"inflight", "uncertain"}:
        raise LifecycleRejected(
            f"Retry requires an inflight or uncertain ticket: {operation_id}"
        )
    inflight = replace(ticket, phase="inflight")
    target = replace(
        lifecycle,
        tickets=tuple(sorted(
            inflight if current == ticket else current
            for current in lifecycle.tickets
        )),
    )
    return LifecycleStep(
        state=target,
        attempt=(operation_id, ticket.claim_id),
        releases_logical_operation=False,
    )


def settle_operation(
    lifecycle: LifecycleState,
    operation_id: str,
    outcome: str,
) -> LifecycleState:
    """Consume attempted work, or explicitly cancel prepared work, into R."""

    ticket = lifecycle.ticket(operation_id)
    attempted = ticket.phase in {"inflight", "uncertain"}
    canceled_prepared = ticket.phase == "prepared" and outcome == "cancelled"
    if not (attempted or canceled_prepared):
        raise LifecycleRejected(
            "Settle requires attempted work or an explicit prepared cancellation: "
            f"{operation_id}"
        )
    if not outcome:
        raise LifecycleRejected("Settle outcome must be nonempty")
    receipt = Receipt(operation_id, ticket.claim_id, outcome)
    return replace(
        lifecycle,
        tickets=tuple(
            current for current in lifecycle.tickets if current != ticket
        ),
        receipts=tuple(sorted(lifecycle.receipts + (receipt,))),
    )


def crash_recover(lifecycle: LifecycleState) -> LifecycleState:
    """Recover durable phases, conservatively marking inflight work uncertain."""

    recovered = tuple(
        replace(ticket, phase="uncertain")
        if ticket.phase == "inflight"
        else ticket
        for ticket in lifecycle.tickets
    )
    return replace(lifecycle, tickets=tuple(sorted(recovered)))


def revoke_epoch(lifecycle: LifecycleState, epoch: str) -> LifecycleState:
    """Close an epoch and terminalize its tentative claims, retaining sealed work."""

    if epoch not in lifecycle.epochs:
        raise LifecycleRejected(f"unknown epoch: {epoch}")
    if epoch in lifecycle.closed_epochs:
        raise LifecycleRejected(f"epoch is already closed: {epoch}")
    epoch_map = dict(lifecycle.claim_epochs)
    revoked_ids = frozenset(
        claim.claim_id
        for claim in lifecycle.authority.conditional
        if epoch_map[claim.claim_id] == epoch
    )
    authority = make_state(
        lifecycle.authority.grant,
        durable=lifecycle.authority.durable,
        conditional=(
            claim
            for claim in lifecycle.authority.conditional
            if claim.claim_id not in revoked_ids
        ),
        frontiers=lifecycle.authority.frontiers,
    )
    return replace(
        lifecycle,
        authority=authority,
        closed_epochs=lifecycle.closed_epochs | frozenset((epoch,)),
        terminal_claim_ids=lifecycle.terminal_claim_ids | revoked_ids,
    )


def structural_history_preserved(
    source: LifecycleState,
    target: LifecycleState,
) -> bool:
    """Check the monotone lifecycle-history side of structural simulation."""

    protected_source = {
        ticket.operation_id: ticket for ticket in source.tickets
    }
    protected_target = {
        ticket.operation_id: ticket for ticket in target.tickets
    }
    return (
        source.authority.grant == target.authority.grant
        and source.authority.durable == target.authority.durable
        and source.terminal_claim_ids <= target.terminal_claim_ids
        and source.tombstoned_branches <= target.tombstoned_branches
        and source.closed_epochs <= target.closed_epochs
        and set(source.receipts) <= set(target.receipts)
        and all(
            protected_target.get(operation_id) == ticket
            for operation_id, ticket in protected_source.items()
        )
    )


def _refine_lifecycle_leaf(
    lifecycle: LifecycleState,
    old: Branch,
    children: Sequence[Branch],
    *,
    parallel: bool,
    transfers: Iterable[Tuple[str, Branch]],
    tombstone_old: bool,
) -> LifecycleState:
    """Certificate-check a bounded leaf refinement and nonduplicating Q transfer."""

    descendants = tuple(sorted(children))
    reused_closed = set(descendants) & set(lifecycle.tombstoned_branches)
    if reused_closed:
        raise LifecycleRejected(
            "refinement descendants reuse tombstoned branch epochs: "
            f"{sorted(reused_closed)}"
        )
    transfer_entries = tuple(transfers)
    transfer_map = dict(transfer_entries)
    if len(transfer_map) != len(transfer_entries):
        raise LifecycleRejected("each tentative claim may transfer at most once")
    old_claims = {
        claim.claim_id: claim
        for claim in lifecycle.authority.conditional
        if claim.branch == old
    }
    if not set(transfer_map) <= set(old_claims):
        raise LifecycleRejected("only tentative claims owned by the refined leaf transfer")
    if not set(transfer_map.values()) <= set(descendants):
        raise LifecycleRejected("claim transfers must target refinement descendants")
    try:
        contract = lifecycle.contract.refine_leaf(
            old,
            descendants,
            parallel=parallel,
        )
    except ValueError as error:
        raise LifecycleRejected(str(error)) from error

    conditional = []
    canceled = set(old_claims) - set(transfer_map)
    for claim in lifecycle.authority.conditional:
        if claim.branch != old:
            conditional.append(claim)
        elif claim.claim_id in transfer_map:
            conditional.append(replace(claim, branch=transfer_map[claim.claim_id]))
    authority = make_state(
        lifecycle.authority.grant,
        durable=lifecycle.authority.durable,
        conditional=conditional,
        frontiers=contract.base_frontiers,
    )
    child_set = frozenset(descendants)
    for frontier in contract.base_frontiers:
        projected = frontier - child_set
        if not frontier.isdisjoint(child_set):
            projected = projected | frozenset((old,))
        if projected not in lifecycle.authority.frontiers:
            raise LifecycleRejected("refinement projection escapes the source contract")
        if not vector_leq(
            authority.frontier_load(frontier),
            lifecycle.authority.frontier_load(projected),
        ):
            raise LifecycleRejected("refinement duplicates conditional demand")
    for frontier in contract.support:
        projected = frontier - child_set
        if not frontier.isdisjoint(child_set):
            projected = projected | frozenset((old,))
        if projected not in lifecycle.contract.support:
            raise LifecycleRejected("refinement violates a frozen source guard")

    target = replace(
        lifecycle,
        authority=authority,
        contract=contract,
        terminal_claim_ids=(
            lifecycle.terminal_claim_ids | frozenset(canceled)
        ),
        tombstoned_branches=(
            lifecycle.tombstoned_branches
            | (frozenset((old,)) if tombstone_old else frozenset())
        ),
    )
    if not structural_history_preserved(lifecycle, target):
        raise AssertionError("structural refinement erased durable lifecycle history")
    return target


def restore_replace(
    lifecycle: LifecycleState,
    old: Branch,
    restored: Branch,
    transfers: Iterable[Tuple[str, Branch]] = (),
) -> LifecycleState:
    """Tombstone ``old`` and install one fresh replacement leaf."""

    if restored == old:
        raise LifecycleRejected("replacement leaf must be fresh")
    return _refine_lifecycle_leaf(
        lifecycle,
        old,
        (restored,),
        parallel=False,
        transfers=transfers,
        tombstone_old=True,
    )


def restore_live(
    lifecycle: LifecycleState,
    old: Branch,
    restored: Branch,
) -> LifecycleState:
    """Install a fresh parallel sibling while leaving the clone authority-empty."""

    transfers = tuple(
        (claim.claim_id, old)
        for claim in lifecycle.authority.conditional
        if claim.branch == old
    )
    return _refine_lifecycle_leaf(
        lifecycle,
        old,
        (old, restored),
        parallel=True,
        transfers=transfers,
        tombstone_old=False,
    )


def fork_branch(
    lifecycle: LifecycleState,
    old: Branch,
    left: Branch,
    right: Branch,
    *,
    parallel: bool,
    transfers: Iterable[Tuple[str, Branch]] = (),
) -> LifecycleState:
    """Replace one leaf by choice/parallel children with one-copy transfers."""

    if old in {left, right}:
        raise LifecycleRejected("fork children must be fresh")
    return _refine_lifecycle_leaf(
        lifecycle,
        old,
        (left, right),
        parallel=parallel,
        transfers=transfers,
        tombstone_old=True,
    )
