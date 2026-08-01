"""Executable model of the paper's authority-continuity contract.

This module is deliberately small and dependency free.  It is an executable
validation model, not a proof assistant development: the accompanying explorer
checks finite instances of the paper definitions and theorems.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import combinations
from typing import FrozenSet, Iterable, Iterator, Optional, Sequence, Tuple


Vector = Tuple[int, ...]
Branch = str
Frontier = FrozenSet[Branch]
FrontierFamily = FrozenSet[Frontier]


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


def snapshot_local_impossibility_litmus() -> dict[str, object]:
    """Return the two indistinguishable Reserve worlds from the paper."""

    empty: Frontier = frozenset()
    replace_state = make_state(
        (1,),
        conditional=(Claim("new", (1,), "restored"),),
        frontiers=frozenset((empty, frozenset(("restored",)))),
    )
    live_state = make_state(
        (1,),
        conditional=(
            Claim("old", (1,), "old"),
            Claim("new", (1,), "restored"),
        ),
        frontiers=downward_closure((("old", "restored"),)),
    )
    observation = {
        "snapshot": "identical-reconstructed-bytes",
        "grant": [1],
        "proposal": {"rule": "Reserve", "branch": "restored", "weight": [1]},
    }
    return {
        "observation": observation,
        "replace": {
            "safe": replace_state.authority_continuous,
            "need": list(replace_state.need),
            "required_decision": "accept-for-maximal-permissiveness",
        },
        "live": {
            "safe": live_state.authority_continuous,
            "need": list(live_state.need),
            "violating_frontier": ["old", "restored"],
            "required_decision": "reject-for-soundness",
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
