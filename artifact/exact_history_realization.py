"""Bounded executable model of Exact Agent History Realization.

This module is intentionally small.  It checks finite causal-completion
families, computes the prefix-robust greatest fixed point, and exercises one
atomic history cut; it is evidence for the paper's definitions, not a proof
of the unbounded theorem.

The separate bounded cut fixture takes a trusted ``HistoryState``.  Its older
untrusted operation interface names only live history objects and registered
leaf contracts; ``derive_rewrite`` computes the completion family, source
owners, and successor frontier.  This fixture does not implement the paper's
new immutable edit-schema relation or global policy-domain epoch.  In
particular, the operation has no fields for a plan, outcome family, source set,
receipt frontier, or controller binding.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
from itertools import product
from typing import Iterable, Literal, Sequence, TypeAlias


MAX_OUTCOMES = 128
MAX_OCCURRENCES_PER_OUTCOME = 8
MAX_LINEARIZATIONS = 50_000
MAX_SAFE_EXECUTIONS = 100_000


class ModelError(ValueError):
    """A malformed state, contract, or typed history operation."""


class StaleCut(ModelError):
    """The trusted state changed after cut preparation."""


class ClosedGeneration(ModelError):
    """A protected call used a controller generation closed by installation."""


@dataclass(frozen=True, order=True)
class Occurrence:
    """One logical protected occurrence and its semantic redemption cell."""

    logical_id: str
    cell: str

    def __post_init__(self) -> None:
        if not self.logical_id or not self.cell:
            raise ModelError("occurrence identifiers and cells must be nonempty")


@dataclass(frozen=True)
class Pomset:
    """A finite partial order represented by nodes and strict order edges."""

    nodes: tuple[Occurrence, ...]
    order: frozenset[tuple[str, str]] = frozenset()

    def __post_init__(self) -> None:
        if len(self.nodes) > MAX_OCCURRENCES_PER_OUTCOME:
            raise ModelError(
                f"pomset exceeds the {MAX_OCCURRENCES_PER_OUTCOME}-occurrence cap"
            )
        ids = tuple(node.logical_id for node in self.nodes)
        if len(set(ids)) != len(ids):
            raise ModelError("logical occurrence identifiers must be unique")
        known = set(ids)
        for before, after in self.order:
            if before == after:
                raise ModelError("pomset order must be irreflexive")
            if before not in known or after not in known:
                raise ModelError("pomset order references an unknown occurrence")
        if not _is_acyclic(known, self.order):
            raise ModelError("pomset order must be acyclic")

    @property
    def by_id(self) -> dict[str, Occurrence]:
        return {node.logical_id: node for node in self.nodes}


@dataclass(frozen=True)
class Contract:
    """A nonempty finite family of complete causal outcomes."""

    outcomes: tuple[Pomset, ...]

    def __post_init__(self) -> None:
        if not self.outcomes:
            raise ModelError("a causal-completion contract must be nonempty")
        if len(self.outcomes) > MAX_OUTCOMES:
            raise ModelError(f"contract exceeds the {MAX_OUTCOMES}-outcome cap")
        if len(set(self.outcomes)) != len(self.outcomes):
            raise ModelError("contract contains duplicate outcomes")
        complete_words = tuple(
            word for outcome in self.outcomes for word in linearizations(outcome)
        )
        for left in complete_words:
            for right in complete_words:
                if len(left) < len(right) and right[: len(left)] == left:
                    raise ModelError(
                        "complete traces must be prefix-free so termination is observable"
                    )


def singleton_contract(*occurrences: Occurrence) -> Contract:
    """Construct one unordered complete outcome."""

    return Contract((Pomset(tuple(occurrences)),))


def ordered_contract(*occurrences: Occurrence) -> Contract:
    """Construct one totally ordered complete outcome."""

    edges = frozenset(
        (occurrences[index].logical_id, occurrences[index + 1].logical_id)
        for index in range(len(occurrences) - 1)
    )
    return Contract((Pomset(tuple(occurrences), edges),))


def tagged(contract: Contract, tag: str) -> Contract:
    """Freshen logical identities while retaining semantic cell identities."""

    if not tag:
        raise ModelError("contract tag must be nonempty")
    outcomes: list[Pomset] = []
    for pomset in contract.outcomes:
        rename = {
            node.logical_id: f"{tag}/{node.logical_id}" for node in pomset.nodes
        }
        nodes = tuple(
            Occurrence(rename[node.logical_id], node.cell) for node in pomset.nodes
        )
        edges = frozenset((rename[left], rename[right]) for left, right in pomset.order)
        outcomes.append(Pomset(nodes, edges))
    return _deduplicated_contract(outcomes)


def choice(left: Contract, right: Contract) -> Contract:
    """Tagged alternative once the caller has made identities disjoint."""

    return _deduplicated_contract((*left.outcomes, *right.outcomes))


def parallel(left: Contract, right: Contract) -> Contract:
    """Disjoint parallel product of two completion families."""

    outcomes = [_combine(a, b, ordered=False) for a, b in product(left.outcomes, right.outcomes)]
    return _deduplicated_contract(outcomes)


def sequence(left: Contract, right: Contract) -> Contract:
    """Ordered product: every left occurrence causally precedes every right one."""

    outcomes = [_combine(a, b, ordered=True) for a, b in product(left.outcomes, right.outcomes)]
    return _deduplicated_contract(outcomes)


def _combine(left: Pomset, right: Pomset, *, ordered: bool) -> Pomset:
    left_ids = {node.logical_id for node in left.nodes}
    right_ids = {node.logical_id for node in right.nodes}
    if left_ids & right_ids:
        raise ModelError("contract products require disjoint logical identities")
    edges = set(left.order | right.order)
    if ordered:
        edges.update((a, b) for a in left_ids for b in right_ids)
    return Pomset(tuple(sorted((*left.nodes, *right.nodes))), frozenset(edges))


def _deduplicated_contract(outcomes: Iterable[Pomset]) -> Contract:
    unique = tuple(dict.fromkeys(outcomes))
    return Contract(unique)


def _is_acyclic(nodes: set[str], edges: frozenset[tuple[str, str]]) -> bool:
    predecessors = {node: set() for node in nodes}
    successors = {node: set() for node in nodes}
    for left, right in edges:
        predecessors[right].add(left)
        successors[left].add(right)
    ready = [node for node in nodes if not predecessors[node]]
    visited = 0
    while ready:
        node = ready.pop()
        visited += 1
        for successor in successors[node]:
            predecessors[successor].remove(node)
            if not predecessors[successor]:
                ready.append(successor)
    return visited == len(nodes)


def linearizations(pomset: Pomset) -> tuple[tuple[str, ...], ...]:
    """Enumerate every topological sort, failing closed at the bounded cap."""

    ids = {node.logical_id for node in pomset.nodes}
    predecessors = {node: set() for node in ids}
    for before, after in pomset.order:
        predecessors[after].add(before)
    answers: list[tuple[str, ...]] = []

    def visit(prefix: tuple[str, ...], remaining: frozenset[str]) -> None:
        if not remaining:
            answers.append(prefix)
            if len(answers) > MAX_LINEARIZATIONS:
                raise ModelError(
                    f"linearizations exceed the {MAX_LINEARIZATIONS} cap"
                )
            return
        enabled = sorted(
            node for node in remaining if not (predecessors[node] & remaining)
        )
        for node in enabled:
            visit((*prefix, node), remaining - {node})

    visit((), frozenset(ids))
    return tuple(answers)


EMPTY_CONTRACT = Contract((Pomset(()),))


@dataclass(frozen=True, order=True)
class ResolvedEvent:
    """One non-stuttering resolution event; aliases retain logical identity."""

    kind: Literal["fresh", "alias"]
    logical_id: str
    cell: str


ResolvedTrace: TypeAlias = tuple[ResolvedEvent, ...]


def resolve(
    pomset: Pomset,
    raw_linearization: Sequence[str],
    receipt_trace: Sequence[str],
) -> ResolvedTrace:
    """Resolve one event per raw occurrence; only first cell use is fresh."""

    if tuple(sorted(raw_linearization)) != tuple(
        sorted(node.logical_id for node in pomset.nodes)
    ):
        raise ModelError("raw linearization is not a permutation of the pomset")
    if tuple(raw_linearization) not in linearizations(pomset):
        raise ModelError("raw sequence violates the pomset order")
    return _resolve_enumerated(pomset, raw_linearization, receipt_trace)


def _resolve_enumerated(
    pomset: Pomset,
    raw_linearization: Sequence[str],
    receipt_trace: Sequence[str],
) -> ResolvedTrace:
    """Resolve a linearization already produced by ``linearizations``."""

    seen = set(receipt_trace)
    by_id = pomset.by_id
    output: list[ResolvedEvent] = []
    for logical_id in raw_linearization:
        cell = by_id[logical_id].cell
        kind: Literal["fresh", "alias"] = "alias" if cell in seen else "fresh"
        output.append(ResolvedEvent(kind, logical_id, cell))
        seen.add(cell)
    return tuple(output)


def auth(trace: ResolvedTrace) -> tuple[str, ...]:
    """Project only fresh semantic-cell events to the authority monitor."""

    return tuple(event.cell for event in trace if event.kind == "fresh")


@dataclass(frozen=True)
class PrefixPolicy:
    """A finite prefix-closed policy language over fresh semantic cells."""

    allowed: frozenset[tuple[str, ...]]

    def __post_init__(self) -> None:
        if () not in self.allowed:
            raise ModelError("a prefix policy must contain the empty trace")
        for trace in self.allowed:
            for length in range(len(trace) + 1):
                if trace[:length] not in self.allowed:
                    raise ModelError("authority policy must be prefix closed")

    @classmethod
    def from_maximal(cls, *maximal_traces: Sequence[str]) -> "PrefixPolicy":
        allowed: set[tuple[str, ...]] = {()}
        for raw in maximal_traces:
            trace = tuple(raw)
            for length in range(len(trace) + 1):
                allowed.add(trace[:length])
        return cls(frozenset(allowed))

    def allows(self, trace: Sequence[str]) -> bool:
        return tuple(trace) in self.allowed


@dataclass(frozen=True)
class LiveBranch:
    branch_id: str
    contract: Contract
    owner: str

    def __post_init__(self) -> None:
        if not self.branch_id or not self.owner:
            raise ModelError("branch and owner identifiers must be nonempty")


@dataclass(frozen=True)
class FrontierGroup:
    group_id: str
    mode: Literal["choice", "parallel"]
    members: tuple[str, ...]
    selected: str | None = None

    def __post_init__(self) -> None:
        if not self.group_id or len(self.members) < 2:
            raise ModelError("a frontier group needs an id and at least two members")
        if len(set(self.members)) != len(self.members):
            raise ModelError("frontier group members must be unique")
        if self.selected is not None and (
            self.mode != "choice" or self.selected not in self.members
        ):
            raise ModelError("only a choice group may name one of its members")


@dataclass(frozen=True)
class NamedContract:
    name: str
    contract: Contract


@dataclass(frozen=True)
class HistoryEdge:
    operation: str
    affected: tuple[str, ...]
    targets: tuple[str, ...]


@dataclass(frozen=True)
class HistoryState:
    """The bounded trusted state used by the executable checker."""

    branches: tuple[LiveBranch, ...]
    groups: tuple[FrontierGroup, ...] = ()
    checkpoints: tuple[NamedContract, ...] = ()
    leaf_registry: tuple[NamedContract, ...] = ()
    provenance: tuple[HistoryEdge, ...] = ()
    receipts: tuple[str, ...] = ()
    completed: tuple[str, ...] = ()
    policy: PrefixPolicy = PrefixPolicy(frozenset({()}))
    policy_version: int = 0
    view_version: int = 0
    closed_owners: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if self.policy_version < 0 or self.view_version < 0:
            raise ModelError("trusted versions must be nonnegative")
        if len(set(self.receipts)) != len(self.receipts):
            raise ModelError("the fresh receipt trace cannot repeat a cell")
        if not self.policy.allows(self.receipts):
            raise ModelError("the durable receipt trace violates the policy")
        if any(not logical_id for logical_id in self.completed):
            raise ModelError("completed logical occurrence ids must be nonempty")
        if len(set(self.completed)) != len(self.completed):
            raise ModelError(
                "the ordered logical-occurrence frontier cannot repeat an id"
            )
        branch_ids = [branch.branch_id for branch in self.branches]
        if len(set(branch_ids)) != len(branch_ids):
            raise ModelError("live branch identifiers must be unique")
        active_owners = {branch.owner for branch in self.branches}
        if active_owners & self.closed_owners:
            raise ModelError("a closed controller generation cannot own a live branch")
        known = set(branch_ids)
        grouped: set[str] = set()
        group_ids: set[str] = set()
        for group in self.groups:
            if group.group_id in group_ids:
                raise ModelError("frontier group identifiers must be unique")
            group_ids.add(group.group_id)
            if not set(group.members) <= known:
                raise ModelError("frontier group references an unknown branch")
            if grouped & set(group.members):
                raise ModelError("the bounded model uses a flat frontier")
            grouped.update(group.members)
        _unique_named(self.checkpoints, "checkpoint")
        _unique_named(self.leaf_registry, "leaf contract")
        occurrence_ids: set[str] = set()
        for branch in self.branches:
            branch_occurrences = {
                node.logical_id
                for outcome in branch.contract.outcomes
                for node in outcome.nodes
            }
            overlap = occurrence_ids & branch_occurrences
            if overlap:
                raise ModelError(
                    "logical occurrence identities must be unique across live branches"
                )
            occurrence_ids.update(branch_occurrences)
            cell_by_occurrence: dict[str, str] = {}
            for outcome in branch.contract.outcomes:
                for node in outcome.nodes:
                    previous = cell_by_occurrence.setdefault(node.logical_id, node.cell)
                    if previous != node.cell:
                        raise ModelError(
                            "one logical occurrence cannot name different cells across outcomes"
                        )

    @property
    def branch_map(self) -> dict[str, LiveBranch]:
        return {branch.branch_id: branch for branch in self.branches}

    @property
    def group_map(self) -> dict[str, FrontierGroup]:
        return {group.group_id: group for group in self.groups}

    def leaf(self, name: str) -> Contract:
        return _lookup_named(self.leaf_registry, name, "leaf contract")

    def checkpoint(self, name: str) -> Contract:
        return _lookup_named(self.checkpoints, name, "checkpoint")


def _unique_named(values: Sequence[NamedContract], kind: str) -> None:
    names = [value.name for value in values]
    if any(not name for name in names) or len(set(names)) != len(names):
        raise ModelError(f"{kind} names must be nonempty and unique")


def _lookup_named(
    values: Sequence[NamedContract], name: str, kind: str
) -> Contract:
    matches = [value.contract for value in values if value.name == name]
    if len(matches) != 1:
        raise ModelError(f"unknown {kind}: {name!r}")
    return matches[0]


@dataclass(frozen=True)
class ForkChoice:
    branch: str
    left_leaf: str
    right_leaf: str


@dataclass(frozen=True)
class ForkParallel:
    branch: str
    left_leaf: str
    right_leaf: str


@dataclass(frozen=True)
class RestoreReplace:
    branch: str
    checkpoint: str


@dataclass(frozen=True)
class RestoreLive:
    branch: str
    checkpoint: str


@dataclass(frozen=True)
class MergeSelect:
    group: str
    winner: str
    join_leaf: str


@dataclass(frozen=True)
class MergeJoin:
    group: str
    join_leaf: str


HistoryOperation: TypeAlias = (
    ForkChoice
    | ForkParallel
    | RestoreReplace
    | RestoreLive
    | MergeSelect
    | MergeJoin
)


@dataclass(frozen=True)
class HistoryRewrite:
    operation: str
    contract: Contract
    sources: tuple[str, ...]
    targets: tuple[str, ...]
    next_state: HistoryState


def derive_rewrite(state: HistoryState, operation: HistoryOperation) -> HistoryRewrite:
    """Deterministically derive C, Src, Tgt, and H' from trusted history."""

    stamp = f"v{state.view_version + 1}:{type(operation).__name__}"
    target_owner = f"gen:{stamp}"
    branches = state.branch_map
    groups = state.group_map

    if isinstance(operation, (ForkChoice, ForkParallel)):
        source = _ungrouped_branch(state, operation.branch)
        left_id, right_id = f"{stamp}:left", f"{stamp}:right"
        left = tagged(state.leaf(operation.left_leaf), left_id)
        right = tagged(state.leaf(operation.right_leaf), right_id)
        mode: Literal["choice", "parallel"] = (
            "choice" if isinstance(operation, ForkChoice) else "parallel"
        )
        contract = choice(left, right) if mode == "choice" else parallel(left, right)
        target_branches = (
            LiveBranch(left_id, left, target_owner),
            LiveBranch(right_id, right, target_owner),
        )
        group = FrontierGroup(f"{stamp}:group", mode, (left_id, right_id))
        next_branches = _replace_branches(state.branches, {source.branch_id}, target_branches)
        next_groups = (*state.groups, group)
        affected = (source.branch_id,)
        sources = (source.owner,)
        targets = (left_id, right_id)

    elif isinstance(operation, RestoreReplace):
        source = _ungrouped_branch(state, operation.branch)
        target_id = f"{stamp}:clone"
        target = tagged(state.checkpoint(operation.checkpoint), target_id)
        target_branches = (LiveBranch(target_id, target, target_owner),)
        next_branches = _replace_branches(
            state.branches, {source.branch_id}, target_branches
        )
        next_groups = state.groups
        contract = target
        affected = (source.branch_id,)
        sources = (source.owner,)
        targets = (target_id,)

    elif isinstance(operation, RestoreLive):
        source = _ungrouped_branch(state, operation.branch)
        carry_id, clone_id = f"{stamp}:carry", f"{stamp}:clone"
        carried = _remaining_contract(source.contract, state.completed)
        cloned = tagged(state.checkpoint(operation.checkpoint), clone_id)
        contract = parallel(carried, cloned)
        target_branches = (
            LiveBranch(carry_id, carried, target_owner),
            LiveBranch(clone_id, cloned, target_owner),
        )
        group = FrontierGroup(
            f"{stamp}:group", "parallel", (carry_id, clone_id)
        )
        next_branches = _replace_branches(
            state.branches, {source.branch_id}, target_branches
        )
        next_groups = (*state.groups, group)
        affected = (source.branch_id,)
        sources = (source.owner,)
        targets = (carry_id, clone_id)

    elif isinstance(operation, MergeSelect):
        if operation.group not in groups:
            raise ModelError(f"unknown choice group: {operation.group!r}")
        group = groups[operation.group]
        if group.mode != "choice" or operation.winner not in group.members:
            raise ModelError("MergeSelect requires a member of a choice group")
        if group.selected is not None and group.selected != operation.winner:
            raise ModelError("MergeSelect contradicts the resolved choice arm")
        winner = branches[operation.winner]
        remaining = _remaining_contract(winner.contract, state.completed)
        target_id = f"{stamp}:target"
        joined = tagged(state.leaf(operation.join_leaf), f"{target_id}:join")
        contract = sequence(remaining, joined)
        target_branches = (LiveBranch(target_id, contract, target_owner),)
        retired = set(group.members)
        next_branches = _replace_branches(state.branches, retired, target_branches)
        next_groups = tuple(item for item in state.groups if item != group)
        affected = group.members
        sources = tuple(sorted({branches[item].owner for item in group.members}))
        targets = (target_id,)

    elif isinstance(operation, MergeJoin):
        if operation.group not in groups:
            raise ModelError(f"unknown parallel group: {operation.group!r}")
        group = groups[operation.group]
        if group.mode != "parallel":
            raise ModelError("MergeJoin requires a parallel group")
        parts = [
            _remaining_contract(branches[item].contract, state.completed)
            for item in group.members
        ]
        combined = parts[0]
        for part in parts[1:]:
            combined = parallel(combined, part)
        target_id = f"{stamp}:target"
        joined = tagged(state.leaf(operation.join_leaf), f"{target_id}:join")
        contract = sequence(combined, joined)
        target_branches = (LiveBranch(target_id, contract, target_owner),)
        retired = set(group.members)
        next_branches = _replace_branches(state.branches, retired, target_branches)
        next_groups = tuple(item for item in state.groups if item != group)
        affected = group.members
        sources = tuple(sorted({branches[item].owner for item in group.members}))
        targets = (target_id,)

    else:  # pragma: no cover - protects callers bypassing the type alias
        raise ModelError(f"unsupported history operation: {operation!r}")

    edge = HistoryEdge(type(operation).__name__, affected, targets)
    next_state = HistoryState(
        branches=next_branches,
        groups=next_groups,
        checkpoints=state.checkpoints,
        leaf_registry=state.leaf_registry,
        provenance=(*state.provenance, edge),
        receipts=state.receipts,
        completed=state.completed,
        policy=state.policy,
        policy_version=state.policy_version,
        view_version=state.view_version + 1,
        closed_owners=state.closed_owners,
    )
    return HistoryRewrite(type(operation).__name__, contract, sources, targets, next_state)


def _ungrouped_branch(state: HistoryState, branch_id: str) -> LiveBranch:
    branch = state.branch_map.get(branch_id)
    if branch is None:
        raise ModelError(f"unknown live branch: {branch_id!r}")
    if any(branch_id in group.members for group in state.groups):
        raise ModelError(
            "the bounded flat-frontier model rewrites grouped branches only by Merge"
        )
    return branch


def _replace_branches(
    branches: Sequence[LiveBranch],
    retired: set[str],
    targets: Sequence[LiveBranch],
) -> tuple[LiveBranch, ...]:
    return tuple(branch for branch in branches if branch.branch_id not in retired) + tuple(
        targets
    )


def _remaining_contract(contract: Contract, completed: Sequence[str]) -> Contract:
    universe = {
        node.logical_id for outcome in contract.outcomes for node in outcome.nodes
    }
    relevant = set(completed) & universe
    outcomes: list[Pomset] = []
    for pomset in contract.outcomes:
        ids = {node.logical_id for node in pomset.nodes}
        if not relevant <= ids:
            continue
        if any(after in relevant and before not in relevant for before, after in pomset.order):
            continue
        nodes = tuple(node for node in pomset.nodes if node.logical_id not in relevant)
        edges = frozenset(
            (before, after)
            for before, after in pomset.order
            if before not in relevant and after not in relevant
        )
        outcomes.append(Pomset(nodes, edges))
    if not outcomes:
        raise ModelError("completed logical occurrences contradict every outcome")
    return _deduplicated_contract(outcomes)


@dataclass(frozen=True)
class OutcomeExecutions:
    """Policy-safe executions of one explicitly indexed causal outcome."""

    outcome_index: int
    outcome: Pomset
    safe: tuple[ResolvedTrace, ...]


@dataclass(frozen=True)
class IndexedCompletion:
    """A completion together with the outcome identity erased at runtime."""

    outcome_index: int
    trace: ResolvedTrace


@dataclass(frozen=True)
class PruningCause:
    """Why one candidate leaves the descending greatest-fixed-point chain."""

    rank: int
    removed: IndexedCompletion
    prefix: ResolvedTrace
    compatible_outcome_index: int


@dataclass(frozen=True)
class SurvivorWitness:
    """One stabilized coverage witness for a prefix/outcome obligation."""

    source: IndexedCompletion
    prefix: ResolvedTrace
    compatible_outcome_index: int
    completion: IndexedCompletion


@dataclass(frozen=True)
class ImpossibilityWitness:
    """A missing coverage obligation, including the all-unsafe base case."""

    rank: int
    prefix: ResolvedTrace
    compatible_outcome_index: int
    removed: IndexedCompletion | None


@dataclass(frozen=True)
class AdmissionResult:
    admitted: bool
    outcomes: tuple[OutcomeExecutions, ...]
    candidate_completions: frozenset[IndexedCompletion]
    surviving_indexed_completions: frozenset[IndexedCompletion]
    safe_completions: frozenset[ResolvedTrace]
    language_w: frozenset[ResolvedTrace]
    descending_chain: tuple[frozenset[IndexedCompletion], ...]
    pruning_causes: tuple[PruningCause, ...]
    survivor_witnesses: tuple[SurvivorWitness, ...]
    impossibility_witness: ImpossibilityWitness | None


def _trace_key(trace: ResolvedTrace) -> tuple[tuple[str, str, str], ...]:
    return tuple((event.kind, event.logical_id, event.cell) for event in trace)


def _completion_key(
    completion: IndexedCompletion,
) -> tuple[int, tuple[tuple[str, str, str], ...]]:
    return completion.outcome_index, _trace_key(completion.trace)


def _raw(trace: ResolvedTrace) -> tuple[str, ...]:
    return tuple(event.logical_id for event in trace)


def _prefix_witness_index(
    completions: frozenset[IndexedCompletion],
) -> tuple[
    tuple[IndexedCompletion, ...],
    dict[tuple[int, ResolvedTrace], IndexedCompletion],
]:
    """Index the first canonical completion for each outcome/prefix pair."""

    ordered = tuple(sorted(completions, key=_completion_key))
    witnesses: dict[tuple[int, ResolvedTrace], IndexedCompletion] = {}
    for completion in ordered:
        for length in range(len(completion.trace) + 1):
            witnesses.setdefault(
                (completion.outcome_index, completion.trace[:length]),
                completion,
            )
    return ordered, witnesses


def check_admission(state: HistoryState, contract: Contract) -> AdmissionResult:
    """Compute the prefix-robust greatest fixed point and its certificates.

    ``B_0`` contains every indexed policy-safe completion.  A candidate remains
    in ``Phi(B)`` only when every prefix of that candidate has an extension in
    ``B`` for every causal outcome still compatible with the prefix.  Iterating
    ``Phi`` downward reaches the finite greatest fixed point.  Keeping outcome
    indices here is important: two structurally distinct outcomes may have the
    same resolved runtime trace.
    """

    outcome_results: list[OutcomeExecutions] = []
    candidates: set[IndexedCompletion] = set()
    raw_prefixes_by_outcome: list[frozenset[tuple[str, ...]]] = []
    for outcome_index, pomset in enumerate(contract.outcomes):
        safe: list[ResolvedTrace] = []
        raw_prefixes: set[tuple[str, ...]] = {()}
        raw_linearizations = linearizations(pomset)
        for raw_linearization in raw_linearizations:
            for length in range(len(raw_linearization) + 1):
                raw_prefixes.add(raw_linearization[:length])
            resolved = _resolve_enumerated(
                pomset,
                raw_linearization,
                state.receipts,
            )
            if state.policy.allows((*state.receipts, *auth(resolved))):
                safe.append(resolved)
                candidates.add(IndexedCompletion(outcome_index, resolved))
                if len(candidates) > MAX_SAFE_EXECUTIONS:
                    raise ModelError(
                        f"indexed safe executions exceed the "
                        f"{MAX_SAFE_EXECUTIONS} cap"
                    )
        outcome_results.append(
            OutcomeExecutions(outcome_index, pomset, tuple(safe))
        )
        raw_prefixes_by_outcome.append(frozenset(raw_prefixes))

    outcomes_by_raw_prefix: dict[tuple[str, ...], list[int]] = {}
    for outcome_index, raw_prefixes in enumerate(raw_prefixes_by_outcome):
        for raw_prefix in raw_prefixes:
            outcomes_by_raw_prefix.setdefault(raw_prefix, []).append(outcome_index)

    def compatible_outcomes(prefix: ResolvedTrace) -> tuple[int, ...]:
        return tuple(outcomes_by_raw_prefix.get(_raw(prefix), ()))

    current = frozenset(candidates)
    descending_chain: list[frozenset[IndexedCompletion]] = [current]
    pruning_causes: list[PruningCause] = []
    rank = 1
    while current:
        removed: set[IndexedCompletion] = set()
        ordered_current, prefix_witnesses = _prefix_witness_index(current)
        for candidate in ordered_current:
            cause: PruningCause | None = None
            for length in range(len(candidate.trace) + 1):
                prefix = candidate.trace[:length]
                for outcome_index in compatible_outcomes(prefix):
                    if (outcome_index, prefix) not in prefix_witnesses:
                        cause = PruningCause(
                            rank,
                            candidate,
                            prefix,
                            outcome_index,
                        )
                        break
                if cause is not None:
                    break
            if cause is not None:
                removed.add(candidate)
                pruning_causes.append(cause)
        if not removed:
            break
        current = current - removed
        descending_chain.append(current)
        rank += 1

    survivor_witnesses: list[SurvivorWitness] = []
    ordered_current, prefix_witnesses = _prefix_witness_index(current)
    for candidate in ordered_current:
        for length in range(len(candidate.trace) + 1):
            prefix = candidate.trace[:length]
            for outcome_index in compatible_outcomes(prefix):
                completion = prefix_witnesses.get((outcome_index, prefix))
                if completion is None:  # pragma: no cover - internal invariant
                    raise AssertionError("stabilized set lacks a coverage witness")
                survivor_witnesses.append(
                    SurvivorWitness(
                        candidate,
                        prefix,
                        outcome_index,
                        completion,
                    )
                )

    language: set[ResolvedTrace] = set()
    projected_survivors: set[ResolvedTrace] = set()
    for completion in current:
        projected_survivors.add(completion.trace)
        for length in range(len(completion.trace) + 1):
            language.add(completion.trace[:length])

    impossibility: ImpossibilityWitness | None = None
    if not current:
        if pruning_causes:
            last = pruning_causes[-1]
            impossibility = ImpossibilityWitness(
                last.rank,
                last.prefix,
                last.compatible_outcome_index,
                last.removed,
            )
        else:
            missing_outcome = next(
                (
                    result.outcome_index
                    for result in outcome_results
                    if not result.safe
                ),
                0,
            )
            impossibility = ImpossibilityWitness(0, (), missing_outcome, None)

    return AdmissionResult(
        admitted=bool(current),
        outcomes=tuple(outcome_results),
        candidate_completions=frozenset(candidates),
        surviving_indexed_completions=current,
        safe_completions=frozenset(projected_survivors),
        language_w=frozenset(language),
        descending_chain=tuple(descending_chain),
        pruning_causes=tuple(pruning_causes),
        survivor_witnesses=tuple(survivor_witnesses),
        impossibility_witness=impossibility,
    )


@dataclass(frozen=True)
class CutSeal:
    operation: HistoryOperation
    view_version: int
    policy_version: int
    receipts: tuple[str, ...]
    completed: tuple[str, ...]
    completed_digest: str
    frontier: tuple[object, ...]
    sources: tuple[str, ...]
    contract: Contract


@dataclass(frozen=True)
class CompiledCut:
    rewrite: HistoryRewrite
    admission: AdmissionResult
    seal: CutSeal | None


def compile_cut(state: HistoryState, operation: HistoryOperation) -> CompiledCut:
    """Derive, admit, and seal one cut; rejected cuts receive no seal."""

    rewrite = derive_rewrite(state, operation)
    admission = check_admission(state, rewrite.contract)
    seal = None
    if admission.admitted:
        seal = CutSeal(
            operation=operation,
            view_version=state.view_version,
            policy_version=state.policy_version,
            receipts=state.receipts,
            completed=state.completed,
            completed_digest=logical_frontier_digest(state.completed),
            frontier=_frontier_signature(state),
            sources=rewrite.sources,
            contract=rewrite.contract,
        )
    return CompiledCut(rewrite, admission, seal)


def install_cut(current: HistoryState, compiled: CompiledCut) -> HistoryState:
    """Atomically rederive the cut, fence all sources, and activate the target."""

    seal = compiled.seal
    if seal is None:
        raise ModelError("a rejected history rewrite is not installable")
    observed = (
        current.view_version,
        current.policy_version,
        current.receipts,
        current.completed,
        logical_frontier_digest(current.completed),
        _frontier_signature(current),
    )
    expected = (
        seal.view_version,
        seal.policy_version,
        seal.receipts,
        seal.completed,
        seal.completed_digest,
        seal.frontier,
    )
    if observed != expected:
        raise StaleCut("receipt, logical, policy, view, or frontier state changed")
    rewrite = derive_rewrite(current, seal.operation)
    if rewrite.sources != seal.sources or rewrite.contract != seal.contract:
        raise StaleCut("trusted rederivation no longer matches the cut seal")
    if not check_admission(current, rewrite.contract).admitted:
        raise StaleCut("trusted rederivation is no longer policy admissible")
    return replace(
        rewrite.next_state,
        closed_owners=current.closed_owners | frozenset(rewrite.sources),
    )


def _frontier_signature(state: HistoryState) -> tuple[object, ...]:
    return (
        tuple(sorted(state.branches, key=lambda branch: branch.branch_id)),
        tuple(sorted(state.groups, key=lambda group: group.group_id)),
        state.checkpoints,
        state.leaf_registry,
    )


def logical_frontier_digest(completed: Sequence[str]) -> str:
    """Order-sensitive length-delimited digest of the append-only chi trace."""

    digest = hashlib.sha256()
    for logical_id in completed:
        encoded = logical_id.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return "sha256:" + digest.hexdigest()


@dataclass(frozen=True)
class GateInvocation:
    """The exact logical gate binding captured by a protected call."""

    owner: str
    logical_id: str
    cell: str


def commit_gate(
    state: HistoryState, invocation: GateInvocation
) -> tuple[HistoryState, ResolvedEvent | None]:
    """Commit one enabled exact gate binding; a same-ID retry is a stutter."""

    if invocation.owner in state.closed_owners:
        raise ClosedGeneration(f"controller generation is closed: {invocation.owner}")
    matches: list[tuple[LiveBranch, Occurrence]] = []
    for branch in state.branches:
        if branch.owner != invocation.owner:
            continue
        for outcome in branch.contract.outcomes:
            for node in outcome.nodes:
                if (
                    node.logical_id == invocation.logical_id
                    and node.cell == invocation.cell
                ):
                    matches.append((branch, node))
    unique_matches = {
        (branch.branch_id, node.logical_id, node.cell): (branch, node)
        for branch, node in matches
    }
    if not unique_matches:
        raise ModelError("gate binding is not owned by an active generation")
    branch, _ = next(iter(unique_matches.values()))
    if invocation.logical_id in state.completed:
        return state, None

    remaining = _remaining_contract(branch.contract, state.completed)
    enabled = any(
        invocation.logical_id in {node.logical_id for node in outcome.nodes}
        and not any(after == invocation.logical_id for _, after in outcome.order)
        for outcome in remaining.outcomes
    )
    if not enabled:
        raise ModelError("logical occurrence is not causally enabled")

    is_alias = invocation.cell in state.receipts
    event = ResolvedEvent(
        "alias" if is_alias else "fresh",
        invocation.logical_id,
        invocation.cell,
    )
    receipts = state.receipts
    if not is_alias:
        receipts = (*receipts, invocation.cell)
        if not state.policy.allows(receipts):
            raise ModelError("fresh commitment would violate the authority policy")

    groups = list(state.groups)
    for index, group in enumerate(groups):
        if branch.branch_id not in group.members or group.mode != "choice":
            continue
        if group.selected is not None and group.selected != branch.branch_id:
            raise ModelError("the other choice arm has already been selected")
        groups[index] = replace(group, selected=branch.branch_id)

    next_state = replace(
        state,
        groups=tuple(groups),
        receipts=receipts,
        completed=(*state.completed, invocation.logical_id),
    )
    return next_state, event
