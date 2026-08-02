"""Independent replay, pure transition oracle, and decision baselines.

This module intentionally does not import :mod:`adapter.plan_pilot`.  It reads
the controller's append-only envelopes as untrusted data, checks the hash
chain, recomputes every complete successor, and provides the comparison
decisions used by the pilot.  Aggregate output contains counts only, never
state trajectories.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from itertools import permutations
import json
from typing import Any, Iterable, Mapping, Sequence


ZERO_HASH = "0" * 64
STRUCTURAL_OPS = frozenset(
    {"disjoint_mutation", "refine", "merge", "revoke", "restrict"}
)


class ReplayError(RuntimeError):
    pass


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _current_slot(state: Mapping[str, Any]) -> str | None:
    plan = state["plan"]
    for slot in plan["ordered_slots"]:
        if any(plan["root_slot"].get(claim) == slot for claim in plan["remaining"]):
            return slot
    return None


def _head(state: Mapping[str, Any]) -> tuple[str, str, tuple[str, ...]] | None:
    slot = _current_slot(state)
    if slot is None:
        return None
    plan = state["plan"]
    owners: dict[str, list[str]] = {}
    for claim_id in plan["remaining"]:
        claim = state["claims"].get(claim_id)
        if plan["root_slot"].get(claim_id) == slot and claim and claim["status"] == "tentative":
            owners.setdefault(str(claim.get("owner")), []).append(claim_id)
    if not owners:
        return None
    owner = min(owners)
    return slot, owner, tuple(sorted(owners[owner]))


def _batch(state: Mapping[str, Any]) -> dict[str, dict[str, int]]:
    plan = state["plan"]
    result = {
        slot: {grant: 0 for grant in sorted(state["grants"])}
        for slot in plan["ordered_slots"]
    }
    for claim_id in plan["remaining"]:
        claim = state["claims"][claim_id]
        result[plan["root_slot"][claim_id]][claim["grant"]] += int(claim["demand"])
    return result


def _durable(state: Mapping[str, Any], grant: str) -> int:
    return sum(
        int(claim["demand"])
        for claim in state["claims"].values()
        if claim["grant"] == grant and claim["status"] == "durable"
    )


def _computed_token_disposition(state: Mapping[str, Any], token: str) -> str:
    ledger = state["token_ledger"]
    if any(
        ledger["origin"].get(claim_id) == token
        for claim_id in state["plan"]["remaining"]
    ):
        return "remaining"
    bindings = list(state.get("tickets", {}).values()) + list(
        state.get("receipts", {}).values()
    )
    if any(ledger["origin"].get(binding.get("claim")) == token for binding in bindings):
        return "prepared"
    return "withdrawn"


def validate_semantic_state(state: Mapping[str, Any]) -> None:
    """Independent small-state checker for the paper-bearing invariants."""

    plan = state.get("plan")
    if not isinstance(plan, Mapping):
        raise ReplayError("missing semantic plan")
    slots = plan.get("ordered_slots")
    grants = state.get("grants")
    if not isinstance(slots, list) or not slots or len(slots) != len(set(slots)):
        raise ReplayError("invalid slots")
    if not isinstance(grants, Mapping) or not grants:
        raise ReplayError("invalid grants")
    remaining = plan.get("remaining")
    disposition = plan.get("disposition")
    if not isinstance(remaining, list) or remaining != sorted(set(remaining)):
        raise ReplayError("remaining is not canonical")
    if not isinstance(disposition, Mapping):
        raise ReplayError("missing disposition ledger")
    if remaining != sorted(k for k, value in disposition.items() if value == "remaining"):
        raise ReplayError("remaining/disposition mismatch")
    if not (
        set(plan.get("root_slot", {}))
        == set(plan.get("batch_root", {}))
        == set(disposition)
    ):
        raise ReplayError("lineage map domains differ")

    tentative_owner_roots: dict[str, set[Any]] = {}
    for claim_id, claim in state.get("claims", {}).items():
        if claim.get("status") == "tentative":
            tentative_owner_roots.setdefault(str(claim.get("owner")), set()).add(
                plan["root_slot"].get(claim_id)
            )
    if any(len(roots) != 1 for roots in tentative_owner_roots.values()):
        raise ReplayError("tentative owner mixes optional plan roots")

    owner_roots: dict[str, set[tuple[Any, Any]]] = {}
    for claim_id in remaining:
        claim = state.get("claims", {}).get(claim_id)
        if not claim or claim.get("status") != "tentative" or not claim.get("owner"):
            raise ReplayError("remaining claim is not tentative")
        if state.get("branch_epochs", {}).get(str(claim["owner"])) != "open":
            raise ReplayError("remaining claim owner epoch is not open")
        root = plan["root_slot"].get(claim_id)
        if root not in slots:
            raise ReplayError("remaining claim has no declared root")
        owner_roots.setdefault(str(claim["owner"]), set()).add(
            (root, plan["batch_root"].get(claim_id))
        )
    if any(len(lineage) != 1 for lineage in owner_roots.values()):
        raise ReplayError("owner mixes root lineage")

    batch = _batch(state)
    for name in ("R", "P", "E", "W"):
        rows = plan.get(name)
        if not isinstance(rows, Mapping) or set(rows) != set(slots):
            raise ReplayError(f"invalid {name} rows")
        if any(set(rows[slot]) != set(grants) for slot in slots):
            raise ReplayError(f"invalid {name} grant domain")
    for slot in slots:
        for grant in grants:
            b = batch[slot][grant]
            e, w, p = (int(plan[name][slot][grant]) for name in ("E", "W", "P"))
            if b + e + w != p:
                raise ReplayError("exact B+E+W=P failed")
            if b + e > int(plan["R"][slot][grant]):
                raise ReplayError("reservation envelope failed")
    for grant, capacity in grants.items():
        baseline = int(plan["source_durable_baseline"][grant])
        exposure = sum(int(plan["E"][slot][grant]) for slot in slots)
        if baseline + exposure != _durable(state, grant):
            raise ReplayError("durable exposure equation failed")
        prior = 0
        for slot in slots:
            if baseline + prior + int(plan["R"][slot][grant]) > int(capacity):
                raise ReplayError("deadline bound failed")
            prior += int(plan["P"][slot][grant])
        live = sum(
            int(claim["demand"])
            for claim in state.get("claims", {}).values()
            if claim.get("grant") == grant
            and claim.get("status") in {"durable", "tentative"}
        )
        if live > int(capacity):
            raise ReplayError("live load exceeds capacity")
    if plan.get("current_slot") != _current_slot(state):
        raise ReplayError("cursor mismatch")
    for effect, ticket in state.get("tickets", {}).items():
        claim = state.get("claims", {}).get(ticket.get("claim"))
        if ticket.get("phase") not in {"prepared", "inflight", "uncertain"}:
            raise ReplayError(f"bad ticket phase {effect}")
        if not claim or claim.get("status") != "durable":
            raise ReplayError("ticket lacks durable binding")
        if effect in state.get("receipts", {}):
            raise ReplayError("ticket/receipt overlap")
    for receipt in state.get("receipts", {}).values():
        claim = state.get("claims", {}).get(receipt.get("claim"))
        if not claim or claim.get("status") != "durable":
            raise ReplayError("receipt lacks durable binding")

    ledger = state.get("token_ledger")
    if not isinstance(ledger, Mapping) or set(ledger) != {
        "initial",
        "origin",
        "disposition",
    }:
        raise ReplayError("invalid token-ledger schema")
    initial = ledger["initial"]
    origin = ledger["origin"]
    token_disposition = ledger["disposition"]
    if (
        not isinstance(initial, list)
        or initial != sorted(set(initial))
        or not all(isinstance(token, str) for token in initial)
        or not isinstance(origin, Mapping)
        or not isinstance(token_disposition, Mapping)
        or set(token_disposition) != set(initial)
        or not set(origin) <= set(state.get("claims", {}))
        or not set(origin.values()) <= set(initial)
        or any(value not in {"remaining", "prepared", "withdrawn"} for value in token_disposition.values())
    ):
        raise ReplayError("invalid token-ledger domain")
    for claim_id in remaining:
        if origin.get(claim_id) not in initial:
            raise ReplayError("remaining claim lacks an initial origin token")
    bindings = {**state.get("tickets", {}), **state.get("receipts", {})}
    for binding in bindings.values():
        if origin.get(binding.get("claim")) not in initial:
            raise ReplayError("durable binding lacks an initial origin token")
    for token in initial:
        current_fiber = [claim for claim in remaining if origin.get(claim) == token]
        binding_fiber = [
            effect
            for effect, binding in bindings.items()
            if origin.get(binding.get("claim")) == token
        ]
        if len(current_fiber) > 1:
            raise ReplayError("one origin token has multiple current witnesses")
        if len(binding_fiber) > 1:
            raise ReplayError("one origin token has multiple durable bindings")
        if current_fiber and binding_fiber:
            raise ReplayError("origin token is both remaining and prepared")
        if token_disposition[token] != _computed_token_disposition(state, token):
            raise ReplayError("token disposition is not computed exactly")


def exact_serial_orders(state: Mapping[str, Any]) -> tuple[tuple[str, ...], ...]:
    """Enumerate all small finite group orders consistent with slot order.

    Invalid lineage or exact accounting yields no order.  This is an exact
    bounded checker/control for the pilot, not a scalable planner.
    """

    try:
        validate_semantic_state(state)
    except ReplayError:
        return tuple()
    plan = state["plan"]
    slot_index = {slot: index for index, slot in enumerate(plan["ordered_slots"])}
    groups: dict[tuple[str, str], list[str]] = {}
    for claim_id in plan["remaining"]:
        claim = state["claims"][claim_id]
        groups.setdefault((plan["root_slot"][claim_id], str(claim["owner"])), []).append(claim_id)
    ordered_groups = sorted(groups)
    if not ordered_groups:
        return (tuple(),)
    start = {grant: _durable(state, grant) for grant in state["grants"]}
    accepted: list[tuple[str, ...]] = []
    for order in permutations(ordered_groups):
        indices = [slot_index[group[0]] for group in order]
        if indices != sorted(indices):
            continue
        loads = dict(start)
        feasible = True
        labels: list[str] = []
        for slot, owner in order:
            labels.append(f"{slot}:{owner}")
            for claim_id in groups[(slot, owner)]:
                claim = state["claims"][claim_id]
                loads[claim["grant"]] += int(claim["demand"])
            if any(loads[grant] > int(state["grants"][grant]) for grant in loads):
                feasible = False
                break
        if feasible:
            accepted.append(tuple(labels))
    return tuple(sorted(accepted))


def _cas_matches(state: Mapping[str, Any], operation: Mapping[str, Any]) -> bool:
    offered = operation.get("plan_version")
    return isinstance(offered, int) and not isinstance(offered, bool) and offered == state["plan"]["version"]


class _Admission(ValueError):
    pass


@dataclass(frozen=True)
class ReferenceDecision:
    """Result of the independently written pure transition relation."""

    accepted: bool
    reason: str
    successor: dict[str, Any]


def _clone(value: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(canonical_json(value))


def _fields(
    operation: Mapping[str, Any], required: set[str], optional: set[str] | None = None
) -> None:
    expected = {"op"} | required | (optional or set())
    if not required <= set(operation) or not set(operation) <= expected:
        raise _Admission("operation schema rejected")


def _nat(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _Admission("non-natural demand")
    return value


def _live_load(state: Mapping[str, Any], grant: str) -> int:
    return sum(
        int(claim["demand"])
        for claim in state["claims"].values()
        if claim["grant"] == grant and claim["status"] in {"durable", "tentative"}
    )


def _classify_tokens(state: dict[str, Any]) -> None:
    state["token_ledger"]["disposition"] = {
        token: _computed_token_disposition(state, token)
        for token in state["token_ledger"]["initial"]
    }


def _withdraw(state: dict[str, Any], claim_id: str) -> None:
    plan = state["plan"]
    if plan["disposition"].get(claim_id) != "remaining":
        return
    claim = state["claims"][claim_id]
    slot = plan["root_slot"][claim_id]
    plan["disposition"][claim_id] = "withdrawn"
    plan["remaining"].remove(claim_id)
    plan["W"][slot][claim["grant"]] += int(claim["demand"])


def _reference_prepare(state: dict[str, Any], operation: Mapping[str, Any]) -> None:
    _fields(operation, {"plan_version", "assignments"})
    if not _cas_matches(state, operation):
        raise _Admission("plan CAS failed")
    head = _head(state)
    assignments = operation.get("assignments")
    if head is None or not isinstance(assignments, Mapping) or not assignments:
        raise _Admission("missing computed head assignment")
    slot, owner, group = head
    normalized = {str(effect): str(claim) for effect, claim in assignments.items()}
    if (
        len(normalized) != len(assignments)
        or len(set(normalized.values())) != len(normalized)
        or set(normalized.values()) != set(group)
        or any(effect in state["tickets"] or effect in state["receipts"] for effect in normalized)
    ):
        raise _Admission("assignment coverage/freshness failed")
    load = {grant: 0 for grant in state["grants"]}
    for claim_id in group:
        claim = state["claims"].get(claim_id)
        if (
            not claim
            or claim.get("status") != "tentative"
            or claim.get("owner") != owner
            or state["grant_epochs"].get(claim.get("grant")) != "open"
        ):
            raise _Admission("head epoch failed")
        load[claim["grant"]] += int(claim["demand"])
    for grant, amount in load.items():
        if amount and (
            _durable(state, grant) + amount > int(state["grants"][grant])
            or amount + int(state["plan"]["E"][slot][grant])
            > int(state["plan"]["P"][slot][grant])
        ):
            raise _Admission("head capacity failed")
    effect_for = {claim: effect for effect, claim in normalized.items()}
    for claim_id in group:
        claim = state["claims"][claim_id]
        claim["status"], claim["owner"] = "durable", None
        claim["revision"] += 1
        state["tickets"][effect_for[claim_id]] = {
            "claim": claim_id,
            "phase": "prepared",
        }
        state["plan"]["disposition"][claim_id] = "prepared"
        state["plan"]["remaining"].remove(claim_id)
        state["plan"]["E"][slot][claim["grant"]] += int(claim["demand"])
    state["plan"]["version"] += 1
    state["global_version"] += 1
    state["plan"]["current_slot"] = _current_slot(state)
    _classify_tokens(state)


def _reference_disjoint(state: dict[str, Any], operation: Mapping[str, Any]) -> None:
    _fields(operation, {"claim", "grant", "demand", "owner"})
    claim_id = str(operation["claim"])
    grant = str(operation["grant"])
    owner = str(operation["owner"])
    demand = _nat(operation["demand"])
    if (
        claim_id in state["claims"]
        or grant not in state["grants"]
        or state["grant_epochs"].get(grant) != "open"
        or owner in state["branch_epochs"]
        or _live_load(state, grant) + demand > int(state["grants"][grant])
    ):
        raise _Admission("invalid outside mutation")
    state["claims"][claim_id] = {
        "grant": grant,
        "demand": demand,
        "status": "tentative",
        "owner": owner,
        "revision": 0,
    }
    state["branch_epochs"][owner] = "open"
    state["claims"] = dict(sorted(state["claims"].items()))
    state["branch_epochs"] = dict(sorted(state["branch_epochs"].items()))
    state["global_version"] += 1


def _reference_refine(state: dict[str, Any], operation: Mapping[str, Any]) -> None:
    _fields(operation, {"plan_version", "source_claim", "children"})
    if not _cas_matches(state, operation):
        raise _Admission("plan CAS failed")
    source_id = str(operation["source_claim"])
    source = state["claims"].get(source_id)
    children = operation["children"]
    if (
        not source
        or source.get("status") != "tentative"
        or source_id not in state["plan"]["remaining"]
        or not isinstance(children, list)
        or not children
    ):
        raise _Admission("bad refinement source")
    normalized: list[tuple[str, str, int]] = []
    for child in children:
        if not isinstance(child, Mapping) or set(child) != {"claim", "owner", "demand"}:
            raise _Admission("bad refinement child schema")
        child_id, owner = str(child["claim"]), str(child["owner"])
        demand = _nat(child["demand"])
        if child_id in state["claims"] or state["branch_epochs"].get(owner) != "open":
            raise _Admission("bad refinement child identity/epoch")
        normalized.append((child_id, owner, demand))
    if len({item[0] for item in normalized}) != len(normalized):
        raise _Admission("duplicate child")
    if sum(item[2] for item in normalized) > int(source["demand"]):
        raise _Admission("demand conservation failed")
    source_token = state["token_ledger"]["origin"].get(source_id)
    if source_token not in state["token_ledger"]["initial"] or len(normalized) != 1:
        raise _Admission("linear origin transport failed")
    plan = state["plan"]
    slot, batch_root = plan["root_slot"][source_id], plan["batch_root"][source_id]
    for _, owner, _ in normalized:
        roots = {
            plan["root_slot"].get(claim_id)
            for claim_id, claim in state["claims"].items()
            if claim["status"] == "tentative" and claim.get("owner") == owner
        }
        if roots and roots != {slot}:
            raise _Admission("child owner root mismatch")
    source["status"], source["owner"] = "terminal", None
    source["revision"] += 1
    plan["remaining"].remove(source_id)
    plan["disposition"][source_id] = "superseded"
    for child_id, owner, demand in normalized:
        state["claims"][child_id] = {
            "grant": source["grant"],
            "demand": demand,
            "status": "tentative",
            "owner": owner,
            "revision": 0,
        }
        plan["root_slot"][child_id] = slot
        plan["batch_root"][child_id] = batch_root
        plan["disposition"][child_id] = "remaining"
        plan["remaining"].append(child_id)
        state["token_ledger"]["origin"][child_id] = source_token
    plan["W"][slot][source["grant"]] += int(source["demand"]) - sum(
        item[2] for item in normalized
    )
    plan["remaining"] = sorted(plan["remaining"])
    state["claims"] = dict(sorted(state["claims"].items()))
    for name in ("root_slot", "batch_root", "disposition"):
        plan[name] = dict(sorted(plan[name].items()))
    state["token_ledger"]["origin"] = dict(
        sorted(state["token_ledger"]["origin"].items())
    )
    plan["version"] += 1
    state["global_version"] += 1
    plan["current_slot"] = _current_slot(state)
    _classify_tokens(state)


def _reference_merge(state: dict[str, Any], operation: Mapping[str, Any]) -> None:
    _fields(operation, {"plan_version", "source_owners", "target_owner"})
    if not _cas_matches(state, operation):
        raise _Admission("plan CAS failed")
    raw_sources = operation["source_owners"]
    if not isinstance(raw_sources, list):
        raise _Admission("bad source owner list")
    sources = {str(owner) for owner in raw_sources}
    target = str(operation["target_owner"])
    if (
        len(sources) < 2
        or any(state["branch_epochs"].get(owner) != "open" for owner in sources)
        or target in state["branch_epochs"]
    ):
        raise _Admission("source epoch or target freshness failed")
    affected = sorted(
        claim_id
        for claim_id, claim in state["claims"].items()
        if claim.get("status") == "tentative" and claim.get("owner") in sources
    )
    planned = [claim for claim in affected if claim in state["plan"]["remaining"]]
    present = {state["claims"][claim].get("owner") for claim in affected}
    if not planned or not sources <= present:
        raise _Admission("incomplete merge fiber")
    lineage = {
        (
            state["plan"]["root_slot"].get(claim),
            state["plan"]["batch_root"].get(claim),
        )
        for claim in affected
    }
    if len(lineage) != 1 or next(iter(lineage))[0] is None:
        raise _Admission("mixed merge fiber")
    for claim_id in affected:
        state["claims"][claim_id]["owner"] = target
        state["claims"][claim_id]["revision"] += 1
    for owner in sources:
        state["branch_epochs"][owner] = "closed"
    state["branch_epochs"][target] = "open"
    state["branch_epochs"] = dict(sorted(state["branch_epochs"].items()))
    state["plan"]["version"] += 1
    state["global_version"] += 1
    state["plan"]["current_slot"] = _current_slot(state)
    _classify_tokens(state)


def _reference_revoke(state: dict[str, Any], operation: Mapping[str, Any]) -> None:
    _fields(operation, {"plan_version", "grant"})
    if not _cas_matches(state, operation):
        raise _Admission("plan CAS failed")
    grant = str(operation["grant"])
    if state["grant_epochs"].get(grant) != "open":
        raise _Admission("grant epoch closed")
    state["grant_epochs"][grant] = "closed"
    state["grant_versions"][grant] += 1
    for claim_id, claim in state["claims"].items():
        if claim["grant"] == grant and claim["status"] == "tentative":
            _withdraw(state, claim_id)
            claim["status"], claim["owner"] = "terminal", None
            claim["revision"] += 1
    state["plan"]["remaining"] = sorted(state["plan"]["remaining"])
    state["plan"]["version"] += 1
    state["global_version"] += 1
    state["plan"]["current_slot"] = _current_slot(state)
    _classify_tokens(state)


def _reference_restrict(state: dict[str, Any], operation: Mapping[str, Any]) -> None:
    _fields(operation, {"plan_version", "keep_owners"})
    if not _cas_matches(state, operation):
        raise _Admission("plan CAS failed")
    raw_keep = operation["keep_owners"]
    if not isinstance(raw_keep, list):
        raise _Admission("bad keep owner list")
    keep = {str(owner) for owner in raw_keep}
    for owner, epoch in list(state["branch_epochs"].items()):
        if epoch == "open" and owner not in keep:
            state["branch_epochs"][owner] = "closed"
    for claim_id, claim in state["claims"].items():
        if claim["status"] == "tentative" and claim.get("owner") not in keep:
            _withdraw(state, claim_id)
            claim["status"], claim["owner"] = "terminal", None
            claim["revision"] += 1
    state["plan"]["remaining"] = sorted(state["plan"]["remaining"])
    state["plan"]["version"] += 1
    state["global_version"] += 1
    state["plan"]["current_slot"] = _current_slot(state)
    _classify_tokens(state)


def _reference_ticket_step(state: dict[str, Any], operation: Mapping[str, Any]) -> None:
    kind = str(operation.get("op", ""))
    if kind in {"dispatch", "retry"}:
        _fields(operation, {"effect"})
        effect = str(operation["effect"])
        if effect in state["receipts"] or effect not in state["tickets"]:
            raise _Admission("ticket unavailable")
        phase = state["tickets"][effect]["phase"]
        if (kind == "dispatch" and phase != "prepared") or (
            kind == "retry" and phase not in {"inflight", "uncertain"}
        ):
            raise _Admission("ticket phase rejected")
        state["tickets"][effect]["phase"] = "inflight"
    elif kind == "crash":
        _fields(operation, set(), {"effects"})
        changed = sorted(
            effect
            for effect, ticket in state["tickets"].items()
            if ticket["phase"] == "inflight"
        )
        if "effects" in operation:
            declared = operation["effects"]
            if not isinstance(declared, list) or sorted(map(str, declared)) != changed:
                raise _Admission("crash declaration mismatch")
        for effect in changed:
            state["tickets"][effect]["phase"] = "uncertain"
    elif kind == "settle":
        _fields(operation, {"effect", "outcome"})
        effect, outcome = str(operation["effect"]), str(operation["outcome"])
        ticket = state["tickets"].get(effect)
        if not ticket or ticket["phase"] not in {"inflight", "uncertain"}:
            raise _Admission("ticket not dispatched")
        if outcome not in {"succeeded", "failed", "cancelled"}:
            raise _Admission("bad settlement outcome")
        del state["tickets"][effect]
        state["receipts"][effect] = {"claim": ticket["claim"], "outcome": outcome}
    else:
        raise _Admission("unsupported ticket operation")
    state["global_version"] += 1


def reference_transition(
    previous: Mapping[str, Any], operation: Mapping[str, Any]
) -> ReferenceDecision:
    """Purely recompute admission and the complete successor.

    Source validity is checked before admission: an invalid source is a replay
    error, not an operation rejection.  Candidate invariant failure is an
    independently recomputed rejection and therefore must be logged as a
    state stutter by the controller.
    """

    validate_semantic_state(previous)
    source = _clone(previous)
    candidate = _clone(previous)
    try:
        kind = str(operation.get("op", ""))
        if kind == "prepare":
            _reference_prepare(candidate, operation)
        elif kind == "disjoint_mutation":
            _reference_disjoint(candidate, operation)
        elif kind == "refine":
            _reference_refine(candidate, operation)
        elif kind == "merge":
            _reference_merge(candidate, operation)
        elif kind == "revoke":
            _reference_revoke(candidate, operation)
        elif kind == "restrict":
            _reference_restrict(candidate, operation)
        else:
            _reference_ticket_step(candidate, operation)
        validate_semantic_state(candidate)
    except (_Admission, ReplayError) as rejection:
        return ReferenceDecision(False, str(rejection), source)
    return ReferenceDecision(True, "admitted", candidate)


def semantic_transport_safe(state: Mapping[str, Any], operation: Mapping[str, Any]) -> bool:
    """Compact structural admission predicate, separate from the oracle."""

    kind = str(operation.get("op", ""))
    if kind == "disjoint_mutation":
        if set(operation) != {"op", "claim", "grant", "demand", "owner"}:
            return False
        claim = str(operation.get("claim", ""))
        grant = str(operation.get("grant", ""))
        owner = str(operation.get("owner", ""))
        demand = operation.get("demand")
        live = sum(
            int(item["demand"])
            for item in state["claims"].values()
            if item["grant"] == grant and item["status"] in {"durable", "tentative"}
        )
        return (
            claim not in state["claims"]
            and grant in state["grants"]
            and state["grant_epochs"].get(grant) == "open"
            and owner not in state["branch_epochs"]
            and isinstance(demand, int)
            and not isinstance(demand, bool)
            and demand >= 0
            and live + demand <= int(state["grants"][grant])
        )
    schemas = {
        "refine": {"op", "plan_version", "source_claim", "children"},
        "merge": {"op", "plan_version", "source_owners", "target_owner"},
        "revoke": {"op", "plan_version", "grant"},
        "restrict": {"op", "plan_version", "keep_owners"},
    }
    if (
        kind not in schemas
        or set(operation) != schemas[kind]
        or not _cas_matches(state, operation)
    ):
        return False
    if kind == "refine":
        source_id = str(operation.get("source_claim", ""))
        source = state["claims"].get(source_id)
        children = operation.get("children")
        if (
            not source
            or source.get("status") != "tentative"
            or source_id not in state["plan"]["remaining"]
            or not isinstance(children, list)
        ):
            return False
        try:
            ids = [str(child["claim"]) for child in children]
            demands = [child["demand"] for child in children]
            owners = [str(child["owner"]) for child in children]
        except (KeyError, TypeError):
            return False
        if any(not isinstance(child, Mapping) or set(child) != {"claim", "owner", "demand"} for child in children):
            return False
        source_lineage = (
            state["plan"]["root_slot"].get(source_id),
            state["plan"]["batch_root"].get(source_id),
        )
        return (
            len(children) == 1
            and len(ids) == len(set(ids))
            and all(claim not in state["claims"] for claim in ids)
            and all(state["branch_epochs"].get(owner) == "open" for owner in owners)
            and all(
                {
                    (
                        state["plan"]["root_slot"].get(claim_id),
                        state["plan"]["batch_root"].get(claim_id),
                    )
                    for claim_id, claim in state["claims"].items()
                    if claim["status"] == "tentative" and claim.get("owner") == owner
                }
                in (set(), {source_lineage})
                for owner in owners
            )
            and all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in demands)
            and sum(demands) <= int(source["demand"])
            and state["token_ledger"]["origin"].get(source_id)
            in state["token_ledger"]["initial"]
        )
    if kind == "merge":
        raw_sources = operation.get("source_owners")
        if not isinstance(raw_sources, list):
            return False
        sources = {str(owner) for owner in raw_sources}
        target = str(operation.get("target_owner", ""))
        affected = [
            claim_id
            for claim_id, claim in state["claims"].items()
            if claim.get("status") == "tentative" and claim.get("owner") in sources
        ]
        lineage = {
            (
                state["plan"]["root_slot"].get(claim),
                state["plan"]["batch_root"].get(claim),
            )
            for claim in affected
        }
        planned = [claim for claim in affected if claim in state["plan"]["remaining"]]
        owners_present = {state["claims"][claim].get("owner") for claim in affected}
        return (
            len(sources) >= 2
            and all(state["branch_epochs"].get(owner) == "open" for owner in sources)
            and target not in state["branch_epochs"]
            and bool(planned)
            and sources <= owners_present
            and len(lineage) == 1
            and next(iter(lineage))[0] is not None
        )
    if kind == "revoke":
        return state["grant_epochs"].get(str(operation.get("grant", ""))) == "open"
    raw_keep = operation.get("keep_owners")
    return isinstance(raw_keep, list)


def exact_transport_safe(state: Mapping[str, Any], operation: Mapping[str, Any]) -> bool:
    """Compatibility alias for the independent transition oracle."""

    return transition_oracle_safe(state, operation)


def transition_oracle_safe(state: Mapping[str, Any], operation: Mapping[str, Any]) -> bool:
    """Decide safety by complete pure successor construction and validation."""

    try:
        return reference_transition(state, operation).accepted
    except ReplayError:
        return False


def per_object_safe(state: Mapping[str, Any], operation: Mapping[str, Any]) -> bool:
    """Local cache baseline that intentionally omits owner/root topology."""

    kind = str(operation.get("op", ""))
    if kind == "disjoint_mutation":
        return str(operation.get("claim", "")) not in state["plan"]["disposition"]
    if kind == "merge" and _cas_matches(state, operation):
        sources = set(map(str, operation.get("source_owners", [])))
        # Claim IDs, demand, grant, and tentative phase remain unchanged; owner
        # topology is outside this baseline's dependency key.
        return len(sources) >= 2 and any(
            state["claims"][claim].get("owner") in sources
            for claim in state["plan"]["remaining"]
        )
    if kind == "revoke" and _cas_matches(state, operation):
        grant = str(operation.get("grant", ""))
        return not any(state["claims"][claim]["grant"] == grant for claim in state["plan"]["remaining"])
    if kind == "restrict" and _cas_matches(state, operation):
        keep = set(map(str, operation.get("keep_owners", [])))
        return all(state["claims"][claim].get("owner") in keep for claim in state["plan"]["remaining"])
    return False


def decision_baselines(state: Mapping[str, Any], operation: Mapping[str, Any]) -> dict[str, bool]:
    if str(operation.get("op", "")) not in STRUCTURAL_OPS:
        raise ValueError("baseline comparison requires a structural mutation")
    oracle = transition_oracle_safe(state, operation)
    return {
        "global_version": False,
        "per_object": per_object_safe(state, operation),
        "semantic_transport": semantic_transport_safe(state, operation),
        "transition_oracle": oracle,
    }


def aggregate_decisions(records: Iterable[Mapping[str, bool]]) -> dict[str, Any]:
    """Return deterministic count-only comparison output."""

    materialized = [dict(record) for record in records]
    baselines = ("global_version", "per_object", "semantic_transport")
    result: dict[str, Any] = {
        "schema": "plan-adapter-pilot.aggregate.v2",
        "cases": len(materialized),
        "baselines": {},
    }
    for baseline in baselines:
        confusion = {"safe_reuse": 0, "safe_replan": 0, "unsafe_reuse": 0, "false_invalidation": 0}
        for record in materialized:
            predicted, oracle = bool(record[baseline]), bool(record["transition_oracle"])
            if predicted and oracle:
                confusion["safe_reuse"] += 1
            elif not predicted and not oracle:
                confusion["safe_replan"] += 1
            elif predicted and not oracle:
                confusion["unsafe_reuse"] += 1
            else:
                confusion["false_invalidation"] += 1
        result["baselines"][baseline] = confusion
    result["oracle_safe_semantic_reuse_cases"] = sum(
        1
        for record in materialized
        if record["semantic_transport"] and record["transition_oracle"] and not record["global_version"]
    )
    return result


def aggregate_json(records: Iterable[Mapping[str, bool]]) -> str:
    return canonical_json(aggregate_decisions(records))


@dataclass(frozen=True)
class ReplayResult:
    state: dict[str, Any]
    sequence: int
    head_hash: str


def _check_transition(
    previous: Mapping[str, Any],
    successor: Mapping[str, Any],
    body: Mapping[str, Any],
    event_kind: str,
) -> None:
    if set(body) != {"operation", "accepted", "reason", "successor_state"}:
        raise ReplayError("event body schema differs from the operation protocol")
    operation = body.get("operation")
    if (
        not isinstance(operation, Mapping)
        or not isinstance(body.get("accepted"), bool)
        or not isinstance(body.get("reason"), str)
    ):
        raise ReplayError("event lacks operation")
    expected = reference_transition(previous, operation)
    accepted = bool(body["accepted"])
    if accepted != expected.accepted:
        if accepted:
            raise ReplayError("logged acceptance is rejected by independent admission")
        raise ReplayError("logged rejection is admitted by independent admission")
    kind = str(operation.get("op", ""))
    expected_kind = kind if expected.accepted else "reject"
    if event_kind != expected_kind:
        raise ReplayError("event kind disagrees with independent admission")
    if successor != expected.successor:
        raise ReplayError("logged successor differs from pure full-state recomputation")


def replay_events(
    events: Sequence[Mapping[str, Any]], *, expected_head_hash: str | None = None,
    expected_state_hash: str | None = None,
) -> ReplayResult:
    previous_hash = ZERO_HASH
    previous_state: dict[str, Any] | None = None
    for expected_seq, event in enumerate(events, start=1):
        if int(event.get("seq", -1)) != expected_seq or event.get("previous_hash") != previous_hash:
            raise ReplayError("event sequence or predecessor hash mismatch")
        body = event.get("body")
        if not isinstance(body, Mapping) or digest(body) != event.get("body_hash"):
            raise ReplayError("event body hash mismatch")
        successor = body.get("successor_state")
        if not isinstance(successor, Mapping) or digest(successor) != event.get("state_hash"):
            raise ReplayError("event state hash mismatch")
        envelope = {
            "seq": expected_seq,
            "previous_hash": previous_hash,
            "state_hash": event["state_hash"],
            "kind": event["kind"],
            "body_hash": event["body_hash"],
        }
        if digest(envelope) != event.get("event_hash"):
            raise ReplayError("event envelope hash mismatch")
        successor_dict = json.loads(canonical_json(successor))
        if expected_seq == 1:
            if event["kind"] != "genesis" or body.get("operation") != {"op": "genesis"}:
                raise ReplayError("first event is not genesis")
            validate_semantic_state(successor_dict)
        else:
            assert previous_state is not None
            _check_transition(previous_state, successor_dict, body, str(event["kind"]))
        previous_state = successor_dict
        previous_hash = str(event["event_hash"])
    if previous_state is None:
        raise ReplayError("empty event chain")
    if expected_head_hash is not None and previous_hash != expected_head_hash:
        raise ReplayError("durable head hash mismatch")
    if expected_state_hash is not None and digest(previous_state) != expected_state_hash:
        raise ReplayError("durable state hash mismatch")
    return ReplayResult(previous_state, len(events), previous_hash)


__all__ = [
    "ReferenceDecision",
    "ReplayError",
    "ReplayResult",
    "aggregate_decisions",
    "aggregate_json",
    "decision_baselines",
    "exact_serial_orders",
    "exact_transport_safe",
    "per_object_safe",
    "reference_transition",
    "replay_events",
    "semantic_transport_safe",
    "transition_oracle_safe",
    "validate_semantic_state",
]
