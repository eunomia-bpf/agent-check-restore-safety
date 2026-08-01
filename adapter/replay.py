"""Independent replay decoder for trusted authority-continuity events.

The decoder deliberately imports neither the controller nor the evaluation
oracle.  A genesis record contains the initial semantic state; every later
record contains only a checked operation delta.  Replaying a record computes
the successor state, checks the P3 authority invariant, and then verifies both
the semantic-state hash and the append-only event hash chain.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from itertools import combinations
import json
from typing import Any, Iterable, Mapping, Sequence


ZERO_HASH = "0" * 64
TAU = "tau"
ATTEMPT = "attempt"
_PHASES = frozenset({"prepared", "inflight", "uncertain"})
_CLAIM_STATUSES = frozenset({"tentative", "durable", "terminal"})
_RECEIPT_OUTCOMES = frozenset({"succeeded", "failed", "cancelled"})
_KINDS = frozenset(
    {
        "genesis",
        "checkpoint",
        "fork",
        "restore",
        "delegate",
        "select",
        "reserve",
        "prepare",
        "revoke",
        "dispatch",
        "retry",
        "crash",
        "settle",
        "merge",
        "reject",
    }
)
_FORBIDDEN_DELTA_KEYS = frozenset(
    {"state", "post_state", "postState", "successor_state", "controller_state"}
)


class ReplayError(ValueError):
    """A record is malformed, unauthorised, or inconsistent with its hashes."""


@dataclass(frozen=True)
class Claim:
    grant: str
    demand: int
    status: str
    owner: str | None = None


@dataclass(frozen=True)
class Ticket:
    claim: str
    phase: str


@dataclass(frozen=True)
class Receipt:
    claim: str
    outcome: str


@dataclass(frozen=True)
class Checkpoint:
    branch: str


@dataclass(frozen=True)
class ForkGroup:
    kind: str
    children: tuple[str, ...]


@dataclass(frozen=True)
class ReplayLabel:
    kind: str
    effect: str | None = None
    claim: str | None = None


@dataclass
class ReplayState:
    """Finite semantic state reconstructed solely from trusted deltas.

    ``frontier`` is the full downward-closed family of durability
    configurations, not merely its maximal elements.  ``active_branches`` is
    checked to be exactly the support of that family.
    """

    grants: dict[str, int] = field(default_factory=dict)
    grant_epochs: dict[str, str] = field(default_factory=dict)
    branch_epochs: dict[str, str] = field(default_factory=dict)
    active_branches: set[str] = field(default_factory=set)
    frontier: set[frozenset[str]] = field(default_factory=lambda: {frozenset()})
    claims: dict[str, Claim] = field(default_factory=dict)
    tickets: dict[str, Ticket] = field(default_factory=dict)
    receipts: dict[str, Receipt] = field(default_factory=dict)
    checkpoints: dict[str, Checkpoint] = field(default_factory=dict)
    delegations: dict[str, set[str]] = field(default_factory=dict)
    forks: dict[str, ForkGroup] = field(default_factory=dict)
    sequence: int = 0
    head_hash: str = ZERO_HASH

    def semantic_dict(self) -> dict[str, Any]:
        """Canonical controller-independent projection used by ``state_hash``."""

        return {
            "grants": dict(sorted(self.grants.items())),
            "grant_epochs": dict(sorted(self.grant_epochs.items())),
            "branch_epochs": dict(sorted(self.branch_epochs.items())),
            "active_branches": sorted(self.active_branches),
            "frontier": sorted((sorted(config) for config in self.frontier)),
            "claims": {
                claim: asdict(value) for claim, value in sorted(self.claims.items())
            },
            "tickets": {
                effect: asdict(value) for effect, value in sorted(self.tickets.items())
            },
            "receipts": {
                effect: asdict(value) for effect, value in sorted(self.receipts.items())
            },
            "checkpoints": {
                checkpoint: asdict(value)
                for checkpoint, value in sorted(self.checkpoints.items())
            },
            "delegations": {
                grant: sorted(branches)
                for grant, branches in sorted(self.delegations.items())
            },
            "forks": {
                parent: {"kind": value.kind, "children": list(value.children)}
                for parent, value in sorted(self.forks.items())
            },
        }


@dataclass(frozen=True)
class ReplayResult:
    state: ReplayState
    labels: tuple[ReplayLabel, ...]


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def state_hash(state: ReplayState) -> str:
    return _digest(state.semantic_dict())


def body_hash(body: Mapping[str, Any]) -> str:
    return _digest(dict(body))


def event_hash(event: Mapping[str, Any]) -> str:
    """Hash the controller's fixed event envelope.

    The body is committed through its separately retained hash so a checker
    can diagnose body corruption independently from chain corruption.
    """

    return _digest(
        {
            "seq": event["seq"],
            "previous_hash": event["previous_hash"],
            "state_hash": event["state_hash"],
            "kind": event["kind"],
            "body_hash": event["body_hash"],
        }
    )


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReplayError(f"{name} must be a nonempty string")
    return value


def _integer(value: Any, name: str, *, positive: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ReplayError(f"{name} must be an integer")
    if value < (1 if positive else 0):
        raise ReplayError(f"{name} is out of range")
    return value


def _get(operation: Mapping[str, Any], *names: str, required: bool = True) -> Any:
    present = [name for name in names if name in operation]
    if len(present) > 1:
        values = {canonical_json(operation[name]) for name in present}
        if len(values) != 1:
            raise ReplayError(f"conflicting aliases for {names[0]}")
    if present:
        return operation[present[0]]
    if required:
        raise ReplayError(f"missing operation field {names[0]}")
    return None


def _powerset(values: Iterable[str]) -> set[frozenset[str]]:
    ordered = sorted(set(values))
    return {
        frozenset(group)
        for size in range(len(ordered) + 1)
        for group in combinations(ordered, size)
    }


def _downward_closure(maxima: Iterable[Iterable[str]]) -> set[frozenset[str]]:
    result: set[frozenset[str]] = {frozenset()}
    for maximum in maxima:
        result.update(_powerset(maximum))
    return result


def _maximal_frontier(frontier: set[frozenset[str]]) -> list[list[str]]:
    maxima = [config for config in frontier if not any(config < other for other in frontier)]
    return sorted((sorted(config) for config in maxima))


def _actual_is_zero(operation: Mapping[str, Any], body: Mapping[str, Any]) -> bool:
    actual = operation.get("actual", body.get("actual", 0))
    if isinstance(actual, Mapping):
        return all(value == 0 for value in actual.values())
    return actual == 0


def _check_downward(frontier: set[frozenset[str]]) -> None:
    if frozenset() not in frontier:
        raise ReplayError("frontier must contain the empty configuration")
    for config in frontier:
        if not _powerset(config) <= frontier:
            raise ReplayError("frontier is not downward closed")


def _authority_violations(state: ReplayState) -> list[str]:
    failures: list[str] = []
    for grant, capacity in state.grants.items():
        durable = sum(
            claim.demand
            for claim in state.claims.values()
            if claim.grant == grant and claim.status == "durable"
        )
        for config in state.frontier:
            conditional = sum(
                claim.demand
                for claim in state.claims.values()
                if claim.grant == grant
                and claim.status == "tentative"
                and claim.owner in config
            )
            if durable + conditional > capacity:
                failures.append(
                    f"grant {grant} exceeds {capacity} in {sorted(config)}: "
                    f"{durable}+{conditional}"
                )
    return failures


def _validate_state(state: ReplayState) -> None:
    _check_downward(state.frontier)
    support = set().union(*state.frontier) if state.frontier else set()
    if support != state.active_branches:
        raise ReplayError("active branches differ from frontier support")
    for branch, epoch in state.branch_epochs.items():
        if epoch not in {"open", "closed"}:
            raise ReplayError(f"invalid branch epoch for {branch}")
        if (branch in state.active_branches) != (epoch == "open"):
            raise ReplayError(f"branch epoch/support mismatch for {branch}")
    if not state.active_branches <= set(state.branch_epochs):
        raise ReplayError("an active branch has no epoch")
    for grant, capacity in state.grants.items():
        _integer(capacity, f"capacity of {grant}", positive=True)
        if state.grant_epochs.get(grant) not in {"open", "closed"}:
            raise ReplayError(f"grant {grant} has no valid epoch")
        if grant not in state.delegations:
            raise ReplayError(f"grant {grant} has no delegation entry")
    for claim_id, claim in state.claims.items():
        if claim.status not in _CLAIM_STATUSES:
            raise ReplayError(f"invalid status for {claim_id}")
        if claim.grant not in state.grants:
            raise ReplayError(f"claim {claim_id} refers to an unknown grant")
        _integer(claim.demand, f"demand of {claim_id}", positive=True)
        if claim.status == "tentative":
            if claim.owner not in state.active_branches:
                raise ReplayError(f"tentative claim {claim_id} has no active owner")
            if state.grant_epochs[claim.grant] != "open":
                raise ReplayError(f"tentative claim {claim_id} uses a closed grant")
            if claim.owner not in state.delegations[claim.grant]:
                raise ReplayError(f"claim {claim_id} lacks delegated authority")
        elif claim.owner is not None:
            raise ReplayError(f"non-tentative claim {claim_id} retains an owner")
    bindings: dict[str, str] = {}
    for effect, ticket in state.tickets.items():
        if ticket.phase not in _PHASES:
            raise ReplayError(f"invalid ticket phase for {effect}")
        claim = state.claims.get(ticket.claim)
        if claim is None or claim.status != "durable":
            raise ReplayError(f"ticket {effect} is not bound to a durable claim")
        if effect in state.receipts:
            raise ReplayError(f"effect {effect} has both a ticket and receipt")
        if ticket.claim in bindings and bindings[ticket.claim] != effect:
            raise ReplayError(f"claim {ticket.claim} has multiple effect bindings")
        bindings[ticket.claim] = effect
    for effect, receipt in state.receipts.items():
        if receipt.outcome not in _RECEIPT_OUTCOMES:
            raise ReplayError(f"invalid receipt outcome for {effect}")
        claim = state.claims.get(receipt.claim)
        if claim is None or claim.status != "durable":
            raise ReplayError(f"receipt {effect} is not bound to a durable claim")
        if receipt.claim in bindings and bindings[receipt.claim] != effect:
            raise ReplayError(f"claim {receipt.claim} has multiple effect bindings")
        bindings[receipt.claim] = effect
    violations = _authority_violations(state)
    if violations:
        raise ReplayError("authority continuity failed: " + violations[0])


def _close_branches(state: ReplayState, branches: set[str]) -> None:
    for branch in branches:
        if state.branch_epochs.get(branch) == "open":
            state.branch_epochs[branch] = "closed"
    state.active_branches.difference_update(branches)
    state.frontier = {config - branches for config in state.frontier}
    for claim_id, claim in list(state.claims.items()):
        if claim.status == "tentative" and claim.owner in branches:
            state.claims[claim_id] = Claim(claim.grant, claim.demand, "terminal", None)
    for grant in state.delegations:
        state.delegations[grant].difference_update(branches)


def _fresh_branch(state: ReplayState, branch: str) -> None:
    if branch in state.branch_epochs:
        raise ReplayError(f"branch epoch {branch} is not fresh")


def _replace_frontier(
    frontier: set[frozenset[str]], source: str, replacements: Sequence[set[str]]
) -> set[frozenset[str]]:
    maxima: list[set[str]] = []
    for config in frontier:
        if source in config:
            base = set(config) - {source}
            maxima.extend(base | replacement for replacement in replacements)
        else:
            maxima.append(set(config))
    return _downward_closure(maxima)


def _operation_from_body(kind: str, body: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(body, Mapping):
        raise ReplayError("event body must be an object")
    allowed_body = {"operation", "abstract_label", "correlation", "actual"}
    unknown = set(body) - allowed_body
    if unknown:
        raise ReplayError(f"unknown body fields: {sorted(unknown)}")
    raw = body.get("operation")
    if not isinstance(raw, Mapping):
        raise ReplayError("event body needs an operation object")
    operation = dict(raw)
    operation_kind = operation.get("op", operation.get("kind", kind))
    if operation_kind != kind:
        raise ReplayError(f"envelope kind {kind} disagrees with operation {operation_kind}")
    if kind != "genesis" and _FORBIDDEN_DELTA_KEYS.intersection(operation):
        raise ReplayError("a non-genesis event contains a full post-state field")
    return operation


def _parse_genesis(operation: Mapping[str, Any]) -> ReplayState:
    nested = operation.get("state")
    if nested is not None:
        if not isinstance(nested, Mapping):
            raise ReplayError("genesis state must be an object")
        source: Mapping[str, Any] = nested
    else:
        source = operation
    raw_grants = source.get("grants")
    if not isinstance(raw_grants, Mapping) or not raw_grants:
        raise ReplayError("genesis needs a nonempty grants map")
    grants = {
        _string(grant, "grant id"): _integer(capacity, f"capacity of {grant}", positive=True)
        for grant, capacity in raw_grants.items()
    }
    active_raw = source.get("active_branches", [source.get("root", "root")])
    if not isinstance(active_raw, Sequence) or isinstance(active_raw, (str, bytes)):
        raise ReplayError("active_branches must be a list")
    active = {_string(branch, "branch") for branch in active_raw}
    maxima_raw = source.get("maximal_frontiers", source.get("frontiers", [sorted(active)]))
    if not isinstance(maxima_raw, Sequence) or isinstance(maxima_raw, (str, bytes)):
        raise ReplayError("maximal_frontiers must be a list")
    maxima: list[list[str]] = []
    for config in maxima_raw:
        if not isinstance(config, Sequence) or isinstance(config, (str, bytes)):
            raise ReplayError("each frontier configuration must be a list")
        maxima.append([_string(branch, "frontier branch") for branch in config])
    frontier = _downward_closure(maxima)
    explicit_frontier = source.get("frontier")
    if explicit_frontier is not None:
        parsed = {frozenset(map(str, config)) for config in explicit_frontier}
        _check_downward(parsed)
        frontier = parsed
    support = set().union(*frontier) if frontier else set()
    if support != active:
        raise ReplayError("genesis active branches differ from frontier support")
    raw_delegations = source.get("delegations")
    if raw_delegations is None:
        delegations = {grant: set(active) for grant in grants}
    elif isinstance(raw_delegations, Mapping):
        delegations = {
            str(grant): {_string(branch, "delegated branch") for branch in branches}
            for grant, branches in raw_delegations.items()
        }
    else:
        raise ReplayError("delegations must be an object")
    if set(delegations) != set(grants):
        raise ReplayError("genesis delegations must cover exactly the grants")
    raw_grant_epochs = source.get("grant_epochs", {})
    if not isinstance(raw_grant_epochs, Mapping):
        raise ReplayError("grant_epochs must be an object")
    grant_epochs = {
        grant: str(raw_grant_epochs.get(grant, "open")) for grant in grants
    }
    raw_branch_epochs = source.get("branch_epochs", {})
    if not isinstance(raw_branch_epochs, Mapping):
        raise ReplayError("branch_epochs must be an object")
    branch_epochs = {str(branch): str(epoch) for branch, epoch in raw_branch_epochs.items()}
    for branch in active:
        branch_epochs.setdefault(branch, "open")

    raw_claims = source.get("claims", {})
    if not isinstance(raw_claims, Mapping):
        raise ReplayError("claims must be an object")
    claims: dict[str, Claim] = {}
    for claim_id, raw_claim in raw_claims.items():
        if not isinstance(raw_claim, Mapping):
            raise ReplayError("each genesis claim must be an object")
        claims[str(claim_id)] = Claim(
            grant=_string(raw_claim.get("grant"), "claim grant"),
            demand=_integer(raw_claim.get("demand"), "claim demand", positive=True),
            status=_string(raw_claim.get("status"), "claim status"),
            owner=(str(raw_claim["owner"]) if raw_claim.get("owner") is not None else None),
        )

    raw_tickets = source.get("tickets", {})
    if not isinstance(raw_tickets, Mapping):
        raise ReplayError("tickets must be an object")
    tickets: dict[str, Ticket] = {}
    for effect, raw_ticket in raw_tickets.items():
        if not isinstance(raw_ticket, Mapping):
            raise ReplayError("each genesis ticket must be an object")
        tickets[str(effect)] = Ticket(
            _string(raw_ticket.get("claim"), "ticket claim"),
            _string(raw_ticket.get("phase"), "ticket phase"),
        )

    raw_receipts = source.get("receipts", {})
    if not isinstance(raw_receipts, Mapping):
        raise ReplayError("receipts must be an object")
    receipts: dict[str, Receipt] = {}
    for effect, raw_receipt in raw_receipts.items():
        if not isinstance(raw_receipt, Mapping):
            raise ReplayError("each genesis receipt must be an object")
        receipts[str(effect)] = Receipt(
            _string(raw_receipt.get("claim"), "receipt claim"),
            _string(raw_receipt.get("outcome"), "receipt outcome"),
        )

    raw_checkpoints = source.get("checkpoints", {})
    if not isinstance(raw_checkpoints, Mapping):
        raise ReplayError("checkpoints must be an object")
    checkpoints: dict[str, Checkpoint] = {}
    for checkpoint, raw_checkpoint in raw_checkpoints.items():
        if isinstance(raw_checkpoint, Mapping):
            branch = raw_checkpoint.get("branch")
        else:
            branch = raw_checkpoint
        checkpoints[str(checkpoint)] = Checkpoint(_string(branch, "checkpoint branch"))

    raw_forks = source.get("forks", {})
    if not isinstance(raw_forks, Mapping):
        raise ReplayError("forks must be an object")
    forks: dict[str, ForkGroup] = {}
    for parent, raw_fork in raw_forks.items():
        if not isinstance(raw_fork, Mapping):
            raise ReplayError("each genesis fork must be an object")
        raw_children = raw_fork.get("children")
        if not isinstance(raw_children, Sequence) or isinstance(raw_children, (str, bytes)):
            raise ReplayError("genesis fork children must be a list")
        forks[str(parent)] = ForkGroup(
            _string(raw_fork.get("kind"), "fork kind"),
            tuple(_string(child, "fork child") for child in raw_children),
        )
    state = ReplayState(
        grants=grants,
        grant_epochs=grant_epochs,
        branch_epochs=branch_epochs,
        active_branches=active,
        frontier=frontier,
        claims=claims,
        tickets=tickets,
        receipts=receipts,
        checkpoints=checkpoints,
        delegations=delegations,
        forks=forks,
    )
    _validate_state(state)
    return state


def _apply_nonreject(state: ReplayState, kind: str, operation: Mapping[str, Any]) -> ReplayLabel:
    if kind == "checkpoint":
        checkpoint = _string(_get(operation, "checkpoint", "checkpoint_id"), "checkpoint")
        branch = _string(_get(operation, "branch", "branch_id"), "branch")
        if checkpoint in state.checkpoints:
            raise ReplayError(f"checkpoint {checkpoint} already exists")
        if branch not in state.active_branches:
            raise ReplayError("checkpoint branch is not active")
        state.checkpoints[checkpoint] = Checkpoint(branch)

    elif kind == "fork":
        source = _string(_get(operation, "source"), "fork source")
        fork_kind = _string(_get(operation, "kind", "fork_kind"), "fork kind")
        if fork_kind not in {"choice", "parallel"}:
            raise ReplayError("fork kind must be choice or parallel")
        raw_children = _get(operation, "children")
        if not isinstance(raw_children, Sequence) or isinstance(raw_children, (str, bytes)):
            raise ReplayError("fork children must be a list")
        children = tuple(_string(child, "fork child") for child in raw_children)
        if len(children) < 2 or len(set(children)) != len(children):
            raise ReplayError("fork needs at least two distinct children")
        if source not in state.active_branches:
            raise ReplayError("fork source is not active")
        for child in children:
            _fresh_branch(state, child)
        source_claims = [
            claim for claim in state.claims.values()
            if claim.status == "tentative" and claim.owner == source
        ]
        if source_claims:
            raise ReplayError("fork of tentative authority requires an explicit transfer")
        replacements = [{child} for child in children] if fork_kind == "choice" else [set(children)]
        state.frontier = _replace_frontier(state.frontier, source, replacements)
        state.branch_epochs[source] = "closed"
        state.active_branches.remove(source)
        for child in children:
            state.branch_epochs[child] = "open"
            state.active_branches.add(child)
        for branches in state.delegations.values():
            if source in branches:
                branches.remove(source)
                branches.update(children)
        state.forks[source] = ForkGroup(fork_kind, children)

    elif kind == "restore":
        checkpoint_id = _string(_get(operation, "checkpoint", "checkpoint_id"), "checkpoint")
        source = _string(_get(operation, "source"), "restore source")
        target = _string(_get(operation, "target"), "restore target")
        mode = _string(_get(operation, "mode"), "restore mode")
        checkpoint = state.checkpoints.get(checkpoint_id)
        if checkpoint is None or checkpoint.branch != source:
            raise ReplayError("restore checkpoint does not name the source branch")
        if source not in state.active_branches:
            raise ReplayError("restore source is not active")
        _fresh_branch(state, target)
        if mode not in {"replace", "live"}:
            raise ReplayError("restore mode must be replace or live")
        inherited = {grant for grant, branches in state.delegations.items() if source in branches}
        if mode == "replace":
            state.frontier = _replace_frontier(state.frontier, source, [{target}])
            _close_branches(state, {source})
        else:
            state.frontier = _replace_frontier(state.frontier, source, [{source, target}])
        state.branch_epochs[target] = "open"
        state.active_branches.add(target)
        for grant in inherited:
            state.delegations[grant].add(target)

    elif kind == "delegate":
        grant = _string(_get(operation, "grant", "grant_id"), "grant")
        branch = _string(_get(operation, "branch", "branch_id"), "branch")
        if state.grant_epochs.get(grant) != "open":
            raise ReplayError("cannot delegate a closed or unknown grant")
        if branch not in state.active_branches:
            raise ReplayError("delegation target is not active")
        for claim in state.claims.values():
            if claim.grant == grant and claim.status == "tentative" and claim.owner != branch:
                raise ReplayError("delegation would strand a tentative claim")
        state.delegations[grant] = {branch}

    elif kind == "select":
        selected = _string(_get(operation, "branch", "branch_id"), "selected branch")
        if selected not in state.active_branches:
            raise ReplayError("selected branch is not active")
        group = next(
            (group for group in state.forks.values() if selected in group.children and group.kind == "choice"),
            None,
        )
        if group is None:
            raise ReplayError("selected branch is not in an open choice fork")
        retired = set(group.children) - {selected}
        _close_branches(state, retired)

    elif kind == "reserve":
        claim_id = _string(_get(operation, "claim", "claim_id"), "claim")
        branch = _string(_get(operation, "branch", "branch_id"), "branch")
        grant = _string(_get(operation, "grant", "grant_id"), "grant")
        demand = _integer(_get(operation, "demand"), "claim demand", positive=True)
        if claim_id in state.claims:
            raise ReplayError("claim identifier is not fresh")
        if branch not in state.active_branches or state.branch_epochs.get(branch) != "open":
            raise ReplayError("claim owner is not an open active branch")
        if state.grant_epochs.get(grant) != "open":
            raise ReplayError("claim grant is not open")
        if branch not in state.delegations.get(grant, set()):
            raise ReplayError("claim owner lacks a delegation")
        state.claims[claim_id] = Claim(grant, demand, "tentative", branch)

    elif kind == "prepare":
        effect = _string(_get(operation, "effect", "effect_id"), "effect")
        claim_id = _string(_get(operation, "claim", "claim_id"), "claim")
        if effect in state.tickets or effect in state.receipts:
            raise ReplayError("effect identifier is already bound")
        claim = state.claims.get(claim_id)
        if claim is None or claim.status != "tentative":
            raise ReplayError("prepare requires a tentative claim")
        if any(ticket.claim == claim_id for ticket in state.tickets.values()) or any(
            receipt.claim == claim_id for receipt in state.receipts.values()
        ):
            raise ReplayError("claim already has a stable effect binding")
        state.claims[claim_id] = Claim(claim.grant, claim.demand, "durable", None)
        state.tickets[effect] = Ticket(claim_id, "prepared")
        solvent = {
            config for config in state.frontier
            if not _authority_violations_for_config(state, config)
        }
        if frozenset() not in solvent:
            raise ReplayError("prepare makes durable load exceed capacity")
        state.frontier = solvent
        supported = set().union(*solvent) if solvent else set()
        retired = state.active_branches - supported
        _close_branches(state, retired)

    elif kind == "revoke":
        grant = _string(_get(operation, "grant", "grant_id"), "grant")
        if grant not in state.grants or state.grant_epochs.get(grant) == "closed":
            raise ReplayError("grant is unknown or already closed")
        state.grant_epochs[grant] = "closed"
        state.delegations[grant].clear()
        for claim_id, claim in list(state.claims.items()):
            if claim.grant == grant and claim.status == "tentative":
                state.claims[claim_id] = Claim(grant, claim.demand, "terminal", None)

    elif kind in {"dispatch", "retry"}:
        effect = _string(_get(operation, "effect", "effect_id"), "effect")
        if effect in state.receipts:
            raise ReplayError("a settled effect cannot be redispatched")
        ticket = state.tickets.get(effect)
        if ticket is None:
            raise ReplayError("attempt has no prepared ticket")
        supplied_claim = _get(operation, "claim", "claim_id", required=False)
        if supplied_claim is not None and supplied_claim != ticket.claim:
            raise ReplayError("attempt changes the stable effect binding")
        if kind == "dispatch" and ticket.phase != "prepared":
            raise ReplayError("dispatch requires a prepared ticket")
        if kind == "retry" and ticket.phase not in {"inflight", "uncertain"}:
            raise ReplayError("retry requires an inflight or uncertain ticket")
        state.tickets[effect] = Ticket(ticket.claim, "inflight")
        return ReplayLabel(ATTEMPT, effect, ticket.claim)

    elif kind == "crash":
        changed = {effect for effect, ticket in state.tickets.items() if ticket.phase == "inflight"}
        declared = operation.get("effects")
        if declared is not None and set(map(str, declared)) != changed:
            raise ReplayError("crash delta does not name exactly the inflight tickets")
        for effect in changed:
            ticket = state.tickets[effect]
            state.tickets[effect] = Ticket(ticket.claim, "uncertain")

    elif kind == "settle":
        effect = _string(_get(operation, "effect", "effect_id"), "effect")
        outcome = _string(_get(operation, "outcome"), "receipt outcome")
        if outcome not in _RECEIPT_OUTCOMES:
            raise ReplayError("invalid receipt outcome")
        if effect in state.receipts:
            raise ReplayError("effect is already settled")
        ticket = state.tickets.get(effect)
        if ticket is None:
            raise ReplayError("settlement has no stable ticket")
        supplied_claim = _get(operation, "claim", "claim_id", required=False)
        if supplied_claim is not None and supplied_claim != ticket.claim:
            raise ReplayError("settlement changes the stable effect binding")
        if ticket.phase == "prepared" and outcome != "cancelled":
            raise ReplayError("a prepared ticket may only be cancelled")
        if ticket.phase not in _PHASES:
            raise ReplayError("invalid settlement phase")
        del state.tickets[effect]
        state.receipts[effect] = Receipt(ticket.claim, outcome)

    elif kind == "merge":
        raw_sources = _get(operation, "sources")
        if not isinstance(raw_sources, Sequence) or isinstance(raw_sources, (str, bytes)):
            raise ReplayError("merge sources must be a list")
        sources = {_string(source, "merge source") for source in raw_sources}
        target = _string(_get(operation, "target"), "merge target")
        raw_keep = operation.get("retain_claims", operation.get("claims", []))
        if not isinstance(raw_keep, Sequence) or isinstance(raw_keep, (str, bytes)):
            raise ReplayError("retain_claims must be a list")
        keep = {_string(claim, "retained claim") for claim in raw_keep}
        mode = _string(_get(operation, "mode"), "merge mode")
        if mode not in {"certified", "direct"}:
            raise ReplayError("invalid merge mode")
        if len(sources) < 2 or not sources <= state.active_branches:
            raise ReplayError("merge needs at least two active sources")
        _fresh_branch(state, target)
        tentative_on_sources = {
            claim_id for claim_id, claim in state.claims.items()
            if claim.status == "tentative" and claim.owner in sources
        }
        if not keep <= tentative_on_sources:
            raise ReplayError("merge retains a claim outside its source branches")
        if mode == "certified":
            certificate = operation.get("certificate")
            if not isinstance(certificate, Mapping) or set(certificate) != {
                "projection",
                "claim_map",
            }:
                raise ReplayError("certified merge needs a canonical certificate")
            projection = certificate.get("projection")
            claim_map = certificate.get("claim_map")
            if not isinstance(projection, Mapping) or set(projection) != {
                "target_configuration",
                "source_configuration",
            }:
                raise ReplayError("malformed merge projection")
            raw_target_config = projection.get("target_configuration")
            raw_source_config = projection.get("source_configuration")
            if (
                not isinstance(raw_target_config, list)
                or not isinstance(raw_source_config, list)
            ):
                raise ReplayError("merge projection configurations must be lists")
            target_config = [_string(value, "projected target") for value in raw_target_config]
            source_config = {
                _string(value, "projected source") for value in raw_source_config
            }
            if (
                target_config != [target]
                or not source_config
                or not source_config <= sources
                or frozenset(source_config) not in state.frontier
            ):
                raise ReplayError("merge projection is not an admitted source image")
            if not isinstance(claim_map, list) or any(
                not isinstance(entry, Mapping) for entry in claim_map
            ):
                raise ReplayError("merge claim map must be a list")
            bindings: dict[str, str] = {}
            for entry in claim_map:
                if set(entry) != {"source_claim", "target_claim"}:
                    raise ReplayError("malformed merge claim-map entry")
                source_claim = _string(entry["source_claim"], "source claim")
                target_claim = _string(entry["target_claim"], "target claim")
                if source_claim in bindings:
                    raise ReplayError("merge claim map repeats a source")
                bindings[source_claim] = target_claim
            if set(bindings) != keep or set(bindings.values()) != keep:
                raise ReplayError("merge claim map differs from retained claims")
            if any(
                bindings[claim] != claim
                or state.claims[claim].owner not in source_config
                for claim in keep
            ):
                raise ReplayError("merge certificate does not source each retained claim")
        maxima = []
        for config in state.frontier:
            base = set(config) - sources
            maxima.append(base | ({target} if config & sources else set()))
        state.frontier = _downward_closure(maxima)
        inherited = {
            grant for grant, branches in state.delegations.items() if branches & sources
        }
        _close_branches(state, sources)
        state.branch_epochs[target] = "open"
        state.active_branches.add(target)
        for grant in inherited:
            state.delegations[grant].add(target)
        for claim_id in tentative_on_sources:
            claim = state.claims[claim_id]
            if claim_id in keep:
                state.claims[claim_id] = Claim(claim.grant, claim.demand, "tentative", target)
            else:
                state.claims[claim_id] = Claim(claim.grant, claim.demand, "terminal", None)

    else:
        raise ReplayError(f"unsupported semantic event kind {kind}")

    return ReplayLabel(TAU)


def _authority_violations_for_config(state: ReplayState, config: frozenset[str]) -> list[str]:
    failures: list[str] = []
    for grant, capacity in state.grants.items():
        load = sum(
            claim.demand
            for claim in state.claims.values()
            if claim.grant == grant
            and (
                claim.status == "durable"
                or (claim.status == "tentative" and claim.owner in config)
            )
        )
        if load > capacity:
            failures.append(grant)
    return failures


def _apply_semantic(
    state: ReplayState | None, kind: str, body: Mapping[str, Any]
) -> tuple[ReplayState, ReplayLabel]:
    if kind not in _KINDS:
        raise ReplayError(f"unknown event kind: {kind}")
    operation = _operation_from_body(kind, body)
    if kind == "genesis":
        if state is not None:
            raise ReplayError("genesis may occur only as the first event")
        successor = _parse_genesis(operation)
        label = ReplayLabel(TAU)
    else:
        if state is None:
            raise ReplayError("the first event must be genesis")
        successor = deepcopy(state)
        if kind == "reject":
            rejected = operation.get("action", operation.get("rejected"))
            if not isinstance(rejected, Mapping):
                raise ReplayError("reject needs an embedded action delta")
            rejected_kind = rejected.get("op", rejected.get("kind"))
            if rejected_kind not in _KINDS - {"genesis", "reject"}:
                raise ReplayError("reject embeds an invalid action kind")
            candidate_body = {"operation": dict(rejected), "abstract_label": ATTEMPT if rejected_kind in {"dispatch", "retry"} else TAU}
            try:
                _apply_semantic(state, str(rejected_kind), candidate_body)
            except ReplayError:
                pass
            else:
                raise ReplayError("reject event rejects an admissible action")
            label = ReplayLabel(TAU)
        else:
            label = _apply_nonreject(successor, kind, operation)
        _validate_state(successor)
    declared_label = body.get("abstract_label")
    expected_label = label.kind
    if kind == "reject":
        if declared_label is not None:
            raise ReplayError("reject stutters omit abstract_label")
    elif declared_label != expected_label:
        raise ReplayError(
            f"declared abstract label {declared_label!r} != {expected_label!r}"
        )
    if label.kind == TAU and not _actual_is_zero(operation, body):
        raise ReplayError("a tau/stutter event carries a nonzero protected outcome")
    return successor, label


def apply_event(
    state: ReplayState | None, event: Mapping[str, Any]
) -> tuple[ReplayState, ReplayLabel]:
    """Apply one checked delta and verify its chain and successor-state hashes."""

    required = {
        "seq",
        "previous_hash",
        "event_hash",
        "state_hash",
        "kind",
        "body",
        "body_hash",
    }
    if not isinstance(event, Mapping) or set(event) != required:
        missing = required - set(event) if isinstance(event, Mapping) else required
        extra = set(event) - required if isinstance(event, Mapping) else set()
        raise ReplayError(f"invalid event envelope; missing={sorted(missing)}, extra={sorted(extra)}")
    seq = _integer(event["seq"], "event sequence", positive=True)
    previous = _string(event["previous_hash"], "previous_hash")
    kind = _string(event["kind"], "event kind")
    body = event["body"]
    if not isinstance(body, Mapping):
        raise ReplayError("event body must be an object")
    expected_previous = ZERO_HASH if state is None else state.head_hash
    expected_seq = 1 if state is None else state.sequence + 1
    if seq != expected_seq:
        raise ReplayError(f"event sequence {seq} does not follow {expected_seq - 1}")
    if previous != expected_previous:
        raise ReplayError("event hash chain has the wrong predecessor")
    if body_hash(body) != event["body_hash"]:
        raise ReplayError("event body hash mismatch")
    if event_hash(event) != event["event_hash"]:
        raise ReplayError("event hash mismatch")
    successor, label = _apply_semantic(state, kind, body)
    if state_hash(successor) != event["state_hash"]:
        raise ReplayError("successor state hash mismatch")
    successor.sequence = seq
    successor.head_hash = str(event["event_hash"])
    return successor, label


def seal_event(
    state: ReplayState | None,
    kind: str,
    operation: Mapping[str, Any],
    *,
    correlation: Mapping[str, Any] | None = None,
    actual: int | Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """Construct the canonical envelope used by fixtures and controller mirrors.

    This helper does not weaken replay: ``apply_event`` recomputes every value.
    Production controller code need not import this module and may mirror the
    short, documented hash formula independently.
    """

    body: dict[str, Any] = {"operation": dict(operation)}
    if kind != "reject":
        body["abstract_label"] = ATTEMPT if kind in {"dispatch", "retry"} else TAU
    if correlation is not None:
        body["correlation"] = dict(correlation)
    if actual is not None:
        body["actual"] = actual
    successor, _ = _apply_semantic(state, kind, body)
    envelope: dict[str, Any] = {
        "seq": 1 if state is None else state.sequence + 1,
        "previous_hash": ZERO_HASH if state is None else state.head_hash,
        "state_hash": state_hash(successor),
        "kind": kind,
        "body": body,
        "body_hash": body_hash(body),
    }
    envelope["event_hash"] = event_hash(envelope)
    return envelope


def replay_bundle(bundle: Mapping[str, Any] | Sequence[Mapping[str, Any]]) -> ReplayResult:
    """Replay a complete bundle and optionally verify its retained final anchor."""

    if isinstance(bundle, Mapping):
        raw_events = bundle.get("events")
        if not isinstance(raw_events, Sequence) or isinstance(raw_events, (str, bytes)):
            raise ReplayError("bundle events must be a list")
        expected_head = bundle.get("head_hash")
        expected_state = bundle.get("state_hash")
    else:
        raw_events = bundle
        expected_head = None
        expected_state = None
    state: ReplayState | None = None
    labels: list[ReplayLabel] = []
    for event in raw_events:
        state, label = apply_event(state, event)
        labels.append(label)
    if state is None:
        raise ReplayError("cannot replay an empty bundle")
    if expected_head is not None and expected_head != state.head_hash:
        raise ReplayError("bundle head hash mismatch")
    if expected_state is not None and expected_state != state_hash(state):
        raise ReplayError("bundle final state hash mismatch")
    return ReplayResult(state=state, labels=tuple(labels))


__all__ = [
    "ATTEMPT",
    "TAU",
    "ZERO_HASH",
    "Checkpoint",
    "Claim",
    "Receipt",
    "ReplayError",
    "ReplayLabel",
    "ReplayResult",
    "ReplayState",
    "Ticket",
    "apply_event",
    "body_hash",
    "canonical_json",
    "event_hash",
    "replay_bundle",
    "seal_event",
    "state_hash",
]
