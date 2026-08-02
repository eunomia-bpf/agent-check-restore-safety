"""Thin SQLite plan-aware authority controller pilot.

This module is deliberately separate from the frozen C01--C20 controller.  A
single canonical ``state_json`` contains lifecycle, tickets, and the semantic
plan, and every transition appends one hash-chained event in the same
``BEGIN IMMEDIATE`` transaction that advances the durable state head.

The public operation protocol supplies intent only.  In particular, no
operation accepts a target plan, target roots, target batch, target ``E``/``W``,
or a target-validity assertion.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from typing import Any, Callable, Iterable, Mapping, Sequence


ZERO_HASH = "0" * 64
DISPOSITIONS = frozenset({"remaining", "prepared", "withdrawn", "superseded"})
TICKET_PHASES = frozenset({"prepared", "inflight", "uncertain"})
TOKEN_DISPOSITIONS = frozenset({"remaining", "prepared", "withdrawn"})


class PlanPilotError(RuntimeError):
    """Durable-state corruption or controller misuse."""


class InjectedCrash(RuntimeError):
    """Test-only crash marker at an explicit SQLite transaction boundary."""


class _Reject(ValueError):
    pass


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _natural_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a natural number")
    return value


def _operation_natural(value: Any, name: str) -> int:
    try:
        return _natural_int(value, name)
    except ValueError as error:
        raise _Reject(str(error)) from None


def _zero_rows(slots: Sequence[str], grants: Mapping[str, int]) -> dict[str, dict[str, int]]:
    return {slot: {grant: 0 for grant in sorted(grants)} for slot in slots}


def _current_slot(state: Mapping[str, Any]) -> str | None:
    plan = state["plan"]
    remaining = set(plan["remaining"])
    for slot in plan["ordered_slots"]:
        if any(plan["root_slot"].get(claim) == slot for claim in remaining):
            return slot
    return None


def _current_group(state: Mapping[str, Any]) -> tuple[str, str, list[str]] | None:
    plan = state["plan"]
    slot = _current_slot(state)
    if slot is None:
        return None
    by_owner: dict[str, list[str]] = {}
    for claim_id in plan["remaining"]:
        claim = state["claims"].get(claim_id)
        if (
            plan["root_slot"].get(claim_id) == slot
            and claim
            and claim["status"] == "tentative"
            and isinstance(claim.get("owner"), str)
        ):
            by_owner.setdefault(claim["owner"], []).append(claim_id)
    if not by_owner:
        return None
    owner = min(by_owner)
    return slot, owner, sorted(by_owner[owner])


def _durable_load(state: Mapping[str, Any], grant: str) -> int:
    return sum(
        int(claim["demand"])
        for claim in state["claims"].values()
        if claim["grant"] == grant and claim["status"] == "durable"
    )


def _total_live_load(state: Mapping[str, Any], grant: str) -> int:
    return sum(
        int(claim["demand"])
        for claim in state["claims"].values()
        if claim["grant"] == grant and claim["status"] in {"durable", "tentative"}
    )


def _batch_rows(state: Mapping[str, Any]) -> dict[str, dict[str, int]]:
    plan = state["plan"]
    rows = _zero_rows(plan["ordered_slots"], state["grants"])
    for claim_id in plan["remaining"]:
        claim = state["claims"][claim_id]
        slot = plan["root_slot"][claim_id]
        rows[slot][claim["grant"]] += int(claim["demand"])
    return rows


def _computed_token_disposition(state: Mapping[str, Any], token: str) -> str:
    ledger = state["token_ledger"]
    if any(
        ledger["origin"].get(claim_id) == token
        for claim_id in state["plan"]["remaining"]
    ):
        return "remaining"
    bindings = list(state["tickets"].values()) + list(state["receipts"].values())
    if any(ledger["origin"].get(binding.get("claim")) == token for binding in bindings):
        return "prepared"
    return "withdrawn"


def _reclassify_tokens(state: dict[str, Any]) -> None:
    ledger = state["token_ledger"]
    ledger["disposition"] = {
        token: _computed_token_disposition(state, token)
        for token in ledger["initial"]
    }


def _validate_rows(state: Mapping[str, Any], name: str) -> None:
    plan = state["plan"]
    rows = plan[name]
    if set(rows) != set(plan["ordered_slots"]):
        raise PlanPilotError(f"plan {name} rows differ from ordered slots")
    for slot in plan["ordered_slots"]:
        if set(rows[slot]) != set(state["grants"]):
            raise PlanPilotError(f"plan {name}[{slot}] differs from grants")
        for value in rows[slot].values():
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise PlanPilotError(f"plan {name} contains a non-natural value")


def validate_state(state: Mapping[str, Any]) -> None:
    """Check the pilot's executable rich-plan and exact-ledger invariant."""

    required = {
        "global_version",
        "grants",
        "grant_epochs",
        "grant_versions",
        "branch_epochs",
        "claims",
        "tickets",
        "receipts",
        "token_ledger",
        "plan",
    }
    if set(state) != required:
        raise PlanPilotError("semantic state has an unexpected top-level schema")
    plan = state["plan"]
    expected_plan = {
        "plan_id",
        "version",
        "ordered_slots",
        "current_slot",
        "source_durable_baseline",
        "R",
        "P",
        "E",
        "W",
        "root_slot",
        "batch_root",
        "disposition",
        "remaining",
    }
    if set(plan) != expected_plan:
        raise PlanPilotError("semantic plan has an unexpected schema")
    slots = plan["ordered_slots"]
    if not isinstance(slots, list) or not slots or len(slots) != len(set(slots)):
        raise PlanPilotError("ordered_slots must be a nonempty unique list")
    if plan["remaining"] != sorted(set(plan["remaining"])):
        raise PlanPilotError("remaining must be a sorted set encoding")
    for name in ("R", "P", "E", "W"):
        _validate_rows(state, name)
    if set(plan["source_durable_baseline"]) != set(state["grants"]):
        raise PlanPilotError("durable baseline differs from grants")
    for grant, capacity in state["grants"].items():
        _positive_int(capacity, f"capacity[{grant}]")
        if state["grant_epochs"].get(grant) not in {"open", "closed"}:
            raise PlanPilotError("invalid grant epoch")
        if isinstance(state["grant_versions"].get(grant), bool) or not isinstance(
            state["grant_versions"].get(grant), int
        ):
            raise PlanPilotError("invalid grant object version")

    maps = (plan["root_slot"], plan["batch_root"], plan["disposition"])
    if not (set(maps[0]) == set(maps[1]) == set(maps[2])):
        raise PlanPilotError("lineage maps have different domains")
    for claim_id, disposition in plan["disposition"].items():
        if disposition not in DISPOSITIONS:
            raise PlanPilotError(f"invalid leaf disposition for {claim_id}")
        root = plan["root_slot"][claim_id]
        if root is not None and root not in slots:
            raise PlanPilotError(f"unknown root slot for {claim_id}")
        if not isinstance(plan["batch_root"][claim_id], str):
            raise PlanPilotError(f"invalid batch root for {claim_id}")
    encoded_remaining = sorted(
        claim for claim, disposition in plan["disposition"].items() if disposition == "remaining"
    )
    if encoded_remaining != plan["remaining"]:
        raise PlanPilotError("remaining set and dispositions disagree")
    for claim_id in plan["remaining"]:
        claim = state["claims"].get(claim_id)
        if not claim or claim["status"] != "tentative" or not claim.get("owner"):
            raise PlanPilotError("remaining leaf is not a live tentative claim")
        if state["branch_epochs"].get(str(claim["owner"])) != "open":
            raise PlanPilotError("remaining leaf owner epoch is not open")
        if plan["root_slot"][claim_id] is None:
            raise PlanPilotError("remaining leaf has no root slot")

    # ``root_slot`` is intentionally partial: a claim outside the selected
    # plan has computed root ``None``.  Root purity nevertheless ranges over
    # *all* tentative claims, so an unrelated claim cannot hide under an owner
    # that already carries scheduled work.
    tentative_owner_roots: dict[str, set[str | None]] = {}
    for claim_id, claim in state["claims"].items():
        if claim["status"] == "tentative":
            owner = str(claim["owner"])
            tentative_owner_roots.setdefault(owner, set()).add(
                plan["root_slot"].get(claim_id)
            )
    if any(len(roots) != 1 for roots in tentative_owner_roots.values()):
        raise PlanPilotError("tentative owner mixes optional plan roots")

    owner_roots: dict[str, set[tuple[str | None, str]]] = {}
    for claim_id in plan["remaining"]:
        owner = str(state["claims"][claim_id]["owner"])
        owner_roots.setdefault(owner, set()).add(
            (plan["root_slot"][claim_id], plan["batch_root"][claim_id])
        )
    if any(len(roots) != 1 for roots in owner_roots.values()):
        raise PlanPilotError("tentative owner mixes immutable roots")

    batch = _batch_rows(state)
    for slot in slots:
        for grant in state["grants"]:
            if batch[slot][grant] + plan["E"][slot][grant] + plan["W"][slot][grant] != plan["P"][slot][grant]:
                raise PlanPilotError(f"B+E+W=P failed at {slot}/{grant}")
            live = sum(
                int(state["claims"][claim_id]["demand"])
                for claim_id in plan["remaining"]
                if plan["root_slot"][claim_id] == slot
                and state["claims"][claim_id]["grant"] == grant
            )
            if live + plan["E"][slot][grant] > plan["R"][slot][grant]:
                raise PlanPilotError(f"reservation envelope failed at {slot}/{grant}")
    for grant, capacity in state["grants"].items():
        baseline = int(plan["source_durable_baseline"][grant])
        total_e = sum(int(plan["E"][slot][grant]) for slot in slots)
        if baseline + total_e != _durable_load(state, grant):
            raise PlanPilotError(f"durable exposure equation failed for {grant}")
        prior = 0
        for slot in slots:
            if baseline + prior + int(plan["R"][slot][grant]) > int(capacity):
                raise PlanPilotError(f"deadline bound failed at {slot}/{grant}")
            prior += int(plan["P"][slot][grant])
        if _total_live_load(state, grant) > int(capacity):
            raise PlanPilotError(f"live load exceeds capacity for {grant}")
    if plan["current_slot"] != _current_slot(state):
        raise PlanPilotError("stored current_slot is not the executable cursor")

    for effect, ticket in state["tickets"].items():
        if ticket.get("phase") not in TICKET_PHASES:
            raise PlanPilotError(f"invalid ticket phase for {effect}")
        claim = state["claims"].get(ticket.get("claim"))
        if not claim or claim["status"] != "durable":
            raise PlanPilotError("ticket is not stably bound to a durable claim")
        if effect in state["receipts"]:
            raise PlanPilotError("effect has both ticket and receipt")
    for receipt in state["receipts"].values():
        claim = state["claims"].get(receipt.get("claim"))
        if not claim or claim["status"] != "durable":
            raise PlanPilotError("receipt is not bound to a durable claim")

    ledger = state["token_ledger"]
    if not isinstance(ledger, Mapping) or set(ledger) != {
        "initial",
        "origin",
        "disposition",
    }:
        raise PlanPilotError("invalid token-ledger schema")
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
        or not set(origin) <= set(state["claims"])
        or not set(origin.values()) <= set(initial)
        or any(value not in TOKEN_DISPOSITIONS for value in token_disposition.values())
    ):
        raise PlanPilotError("invalid token-ledger domain")
    for claim_id in plan["remaining"]:
        if origin.get(claim_id) not in initial:
            raise PlanPilotError("remaining claim lacks an initial origin token")
    all_bindings = {**state["tickets"], **state["receipts"]}
    for binding in all_bindings.values():
        if origin.get(binding.get("claim")) not in initial:
            raise PlanPilotError("durable binding lacks an initial origin token")
    for token in initial:
        current_fiber = [
            claim_id
            for claim_id in plan["remaining"]
            if origin.get(claim_id) == token
        ]
        binding_fiber = [
            effect
            for effect, binding in all_bindings.items()
            if origin.get(binding.get("claim")) == token
        ]
        if len(current_fiber) > 1:
            raise PlanPilotError("one origin token has multiple current witnesses")
        if len(binding_fiber) > 1:
            raise PlanPilotError("one origin token has multiple durable bindings")
        if current_fiber and binding_fiber:
            raise PlanPilotError("origin token is both remaining and prepared")
        if token_disposition[token] != _computed_token_disposition(state, token):
            raise PlanPilotError("token disposition is not computed exactly")


def initial_state(
    *,
    grants: Mapping[str, int],
    ordered_slots: Sequence[str],
    claims: Iterable[Mapping[str, Any]],
    plan_id: str = "plan-pilot",
) -> dict[str, Any]:
    """Build and validate a trusted plan genesis from compact source facts."""

    grant_map = {str(grant): _positive_int(value, f"capacity[{grant}]") for grant, value in grants.items()}
    slots = [str(slot) for slot in ordered_slots]
    if not grant_map or not slots or len(slots) != len(set(slots)):
        raise ValueError("genesis requires grants and unique ordered slots")
    lifecycle_claims: dict[str, dict[str, Any]] = {}
    roots: dict[str, str | None] = {}
    batch_roots: dict[str, str] = {}
    dispositions: dict[str, str] = {}
    origins: dict[str, str] = {}
    branches: set[str] = set()
    for raw in claims:
        allowed = {"claim", "grant", "demand", "owner", "slot", "batch_root"}
        if not set(raw) <= allowed or not {"claim", "grant", "demand", "owner", "slot"} <= set(raw):
            raise ValueError("malformed genesis claim")
        claim_id, grant = str(raw["claim"]), str(raw["grant"])
        owner, slot = str(raw["owner"]), str(raw["slot"])
        demand = _natural_int(raw["demand"], f"demand[{claim_id}]")
        if claim_id in lifecycle_claims or grant not in grant_map or slot not in slots:
            raise ValueError("duplicate claim or unknown grant/slot")
        lifecycle_claims[claim_id] = {
            "grant": grant,
            "demand": demand,
            "status": "tentative",
            "owner": owner,
            "revision": 0,
        }
        roots[claim_id] = slot
        batch_roots[claim_id] = str(raw.get("batch_root", claim_id))
        dispositions[claim_id] = "remaining"
        origins[claim_id] = f"token:{claim_id}"
        branches.add(owner)
    rows = _zero_rows(slots, grant_map)
    for claim_id, claim in lifecycle_claims.items():
        rows[roots[claim_id]][claim["grant"]] += int(claim["demand"])
    state: dict[str, Any] = {
        "global_version": 0,
        "grants": dict(sorted(grant_map.items())),
        "grant_epochs": {grant: "open" for grant in sorted(grant_map)},
        "grant_versions": {grant: 0 for grant in sorted(grant_map)},
        "branch_epochs": {branch: "open" for branch in sorted(branches)},
        "claims": dict(sorted(lifecycle_claims.items())),
        "tickets": {},
        "receipts": {},
        "token_ledger": {
            "initial": sorted(origins.values()),
            "origin": dict(sorted(origins.items())),
            "disposition": {
                token: "remaining" for token in sorted(origins.values())
            },
        },
        "plan": {
            "plan_id": str(plan_id),
            "version": 0,
            "ordered_slots": slots,
            "current_slot": None,
            "source_durable_baseline": {grant: 0 for grant in sorted(grant_map)},
            "R": deepcopy(rows),
            "P": deepcopy(rows),
            "E": _zero_rows(slots, grant_map),
            "W": _zero_rows(slots, grant_map),
            "root_slot": dict(sorted(roots.items())),
            "batch_root": dict(sorted(batch_roots.items())),
            "disposition": dict(sorted(dispositions.items())),
            "remaining": sorted(lifecycle_claims),
        },
    }
    state["plan"]["current_slot"] = _current_slot(state)
    validate_state(state)
    return state


@dataclass(frozen=True)
class PlanDecision:
    operation: str
    accepted: bool
    reason: str
    event_seq: int
    state_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "decision": "accept" if self.accepted else "reject",
            "reason": self.reason,
            "event_seq": self.event_seq,
            "state_hash": self.state_hash,
        }


class PlanPilotController:
    """SQLite controller whose transaction is the Prepare linearization point."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        grants: Mapping[str, int] | None = None,
        ordered_slots: Sequence[str] | None = None,
        claims: Iterable[Mapping[str, Any]] | None = None,
        plan_id: str = "plan-pilot",
        expected_head_hash: str | None = None,
    ) -> None:
        self.path = Path(db_path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, timeout=30.0, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS controller_meta(
              singleton INTEGER PRIMARY KEY CHECK(singleton=1),
              state_json TEXT NOT NULL,
              sequence INTEGER NOT NULL,
              head_hash TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events(
              seq INTEGER PRIMARY KEY,
              previous_hash TEXT NOT NULL,
              event_hash TEXT NOT NULL UNIQUE,
              state_hash TEXT NOT NULL,
              kind TEXT NOT NULL,
              body_hash TEXT NOT NULL,
              body_json TEXT NOT NULL
            );
            CREATE TRIGGER IF NOT EXISTS plan_events_no_update BEFORE UPDATE ON events
            BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
            CREATE TRIGGER IF NOT EXISTS plan_events_no_delete BEFORE DELETE ON events
            BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
            """
        )
        row = self._db.execute("SELECT * FROM controller_meta WHERE singleton=1").fetchone()
        if row is None:
            if grants is None or ordered_slots is None or claims is None:
                raise ValueError("new plan pilot requires grants, ordered_slots, and claims")
            state = initial_state(
                grants=grants, ordered_slots=ordered_slots, claims=claims, plan_id=plan_id
            )
            self._db.execute("BEGIN IMMEDIATE")
            try:
                self._db.execute(
                    "INSERT INTO controller_meta VALUES(1,?,?,?)",
                    (canonical_json(state), 0, ZERO_HASH),
                )
                self._append_locked(
                    "genesis",
                    {"operation": {"op": "genesis"}, "accepted": True, "reason": "trusted bootstrap"},
                    state,
                )
                self._db.commit()
            except BaseException:
                self._db.rollback()
                raise
        # The SQLite database is the pilot's trusted durable store.  On every
        # open, independently replay its complete event history and require the
        # materialized head to agree exactly.  ``expected_head_hash`` can pin
        # that history to an anchor held outside this database.  Without such
        # an external anchor this detects torn/accidental rewrites, but does not
        # defend against an attacker who can coherently rewrite the whole DB.
        try:
            if row is not None:
                validate_state(json.loads(row["state_json"]))
            self._verify_durable_history(expected_head_hash=expected_head_hash)
        except BaseException:
            self._db.close()
            raise

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> "PlanPilotController":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _load(self) -> tuple[dict[str, Any], int, str]:
        row = self._db.execute("SELECT * FROM controller_meta WHERE singleton=1").fetchone()
        if row is None:
            raise PlanPilotError("missing controller metadata")
        return json.loads(row["state_json"]), int(row["sequence"]), str(row["head_hash"])

    def snapshot(self) -> dict[str, Any]:
        state, sequence, head_hash = self._load()
        return {
            "state": state,
            "sequence": sequence,
            "head_hash": head_hash,
            "state_hash": digest(state),
        }

    def events(self) -> list[dict[str, Any]]:
        rows = self._db.execute("SELECT * FROM events ORDER BY seq").fetchall()
        return [
            {
                "seq": int(row["seq"]),
                "previous_hash": str(row["previous_hash"]),
                "event_hash": str(row["event_hash"]),
                "state_hash": str(row["state_hash"]),
                "kind": str(row["kind"]),
                "body_hash": str(row["body_hash"]),
                "body": json.loads(row["body_json"]),
            }
            for row in rows
        ]

    def _verify_durable_history(self, *, expected_head_hash: str | None) -> None:
        from adapter.plan_replay import ReplayError, replay_events

        state, sequence, head_hash = self._load()
        anchor = head_hash if expected_head_hash is None else expected_head_hash
        try:
            result = replay_events(
                self.events(),
                expected_head_hash=anchor,
                expected_state_hash=digest(state),
            )
        except ReplayError as error:
            raise PlanPilotError(f"durable history verification failed: {error}") from error
        if result.sequence != sequence or result.head_hash != head_hash or result.state != state:
            raise PlanPilotError("materialized durable head differs from replayed history")

    def _append_locked(
        self, kind: str, body: Mapping[str, Any], state: Mapping[str, Any]
    ) -> dict[str, Any]:
        row = self._db.execute(
            "SELECT sequence,head_hash FROM controller_meta WHERE singleton=1"
        ).fetchone()
        if row is None:
            raise PlanPilotError("missing controller metadata")
        seq, previous = int(row["sequence"]) + 1, str(row["head_hash"])
        successor = deepcopy(dict(state))
        canonical_body = {**dict(body), "successor_state": successor}
        body_hash = digest(canonical_body)
        state_hash = digest(successor)
        envelope = {
            "seq": seq,
            "previous_hash": previous,
            "state_hash": state_hash,
            "kind": kind,
            "body_hash": body_hash,
        }
        event_hash = digest(envelope)
        self._db.execute(
            "INSERT INTO events VALUES(?,?,?,?,?,?,?)",
            (seq, previous, event_hash, state_hash, kind, body_hash, canonical_json(canonical_body)),
        )
        self._db.execute(
            "UPDATE controller_meta SET state_json=?,sequence=?,head_hash=? WHERE singleton=1",
            (canonical_json(successor), seq, event_hash),
        )
        return {**envelope, "event_hash": event_hash}

    @staticmethod
    def _require_fields(
        operation: Mapping[str, Any], required: set[str], optional: set[str] | None = None
    ) -> None:
        optional = optional or set()
        # No opaque caller payload is admitted: otherwise target plan material
        # could be smuggled under a metadata field even though transitions do
        # not read it.
        expected = required | optional | {"op"}
        if not required <= set(operation) or not set(operation) <= expected:
            raise _Reject("operation has missing or caller-supplied target fields")

    @staticmethod
    def _check_version(state: Mapping[str, Any], operation: Mapping[str, Any]) -> None:
        offered = operation.get("plan_version")
        if isinstance(offered, bool) or not isinstance(offered, int):
            raise _Reject("plan_version must be an integer")
        if offered != state["plan"]["version"]:
            raise _Reject("stale plan version")

    @staticmethod
    def _withdraw_claim(state: dict[str, Any], claim_id: str) -> None:
        plan = state["plan"]
        if plan["disposition"].get(claim_id) != "remaining":
            return
        claim = state["claims"][claim_id]
        slot = plan["root_slot"][claim_id]
        plan["disposition"][claim_id] = "withdrawn"
        plan["remaining"].remove(claim_id)
        plan["W"][slot][claim["grant"]] += int(claim["demand"])

    def _prepare(self, state: dict[str, Any], op: Mapping[str, Any]) -> None:
        self._require_fields(op, {"plan_version", "assignments"})
        self._check_version(state, op)
        head = _current_group(state)
        if head is None:
            raise _Reject("no current nonempty owner group")
        slot, owner, group = head
        assignments = op["assignments"]
        if not isinstance(assignments, Mapping) or not assignments:
            raise _Reject("assignments must be a nonempty object")
        normalized = {str(effect): str(claim) for effect, claim in assignments.items()}
        if len(normalized) != len(assignments) or len(set(normalized.values())) != len(normalized):
            raise _Reject("assignment is not injective")
        if set(normalized.values()) != set(group):
            raise _Reject("assignment does not cover the computed head group")
        if any(effect in state["tickets"] or effect in state["receipts"] for effect in normalized):
            raise _Reject("assignment effect is not fresh")
        loads: dict[str, int] = {grant: 0 for grant in state["grants"]}
        for claim_id in group:
            claim = state["claims"].get(claim_id)
            if (
                not claim
                or claim["status"] != "tentative"
                or claim.get("owner") != owner
                or state["grant_epochs"].get(claim["grant"]) != "open"
            ):
                raise _Reject("computed head is not currently tentative and open")
            loads[claim["grant"]] += int(claim["demand"])
        for grant, load in loads.items():
            if load == 0:
                continue
            if _durable_load(state, grant) + load > int(state["grants"][grant]):
                raise _Reject("capacity check failed")
            if load + int(state["plan"]["E"][slot][grant]) > int(
                state["plan"]["P"][slot][grant]
            ):
                raise _Reject("planned batch bound failed")

        inverse = {claim: effect for effect, claim in normalized.items()}
        for claim_id in group:
            claim = state["claims"][claim_id]
            claim["status"], claim["owner"] = "durable", None
            claim["revision"] += 1
            state["tickets"][inverse[claim_id]] = {
                "claim": claim_id,
                "phase": "prepared",
            }
            state["plan"]["disposition"][claim_id] = "prepared"
            state["plan"]["remaining"].remove(claim_id)
            state["plan"]["E"][slot][claim["grant"]] += int(claim["demand"])
        state["plan"]["version"] += 1
        state["global_version"] += 1
        state["plan"]["current_slot"] = _current_slot(state)
        _reclassify_tokens(state)

    def _disjoint_mutation(self, state: dict[str, Any], op: Mapping[str, Any]) -> None:
        self._require_fields(op, {"claim", "grant", "demand", "owner"})
        claim_id, grant, owner = str(op["claim"]), str(op["grant"]), str(op["owner"])
        demand = _operation_natural(op["demand"], "demand")
        if (
            claim_id in state["claims"]
            or grant not in state["grants"]
            or state["grant_epochs"].get(grant) != "open"
            or owner in state["branch_epochs"]
        ):
            raise _Reject("invalid disjoint mutation")
        if _total_live_load(state, grant) + demand > int(state["grants"][grant]):
            raise _Reject("disjoint mutation exceeds capacity")
        state["claims"][claim_id] = {
            "grant": grant,
            "demand": demand,
            "status": "tentative",
            "owner": owner,
            "revision": 0,
        }
        # The outside owner and its root=None classification are computed by
        # the controller.  The selected semantic plan itself remains a byte-
        # for-byte stutter.
        state["branch_epochs"][owner] = "open"
        state["branch_epochs"] = dict(sorted(state["branch_epochs"].items()))
        state["claims"] = dict(sorted(state["claims"].items()))
        state["global_version"] += 1

    def _refine(self, state: dict[str, Any], op: Mapping[str, Any]) -> None:
        self._require_fields(op, {"plan_version", "source_claim", "children"})
        self._check_version(state, op)
        source_id = str(op["source_claim"])
        source = state["claims"].get(source_id)
        children = op["children"]
        if (
            not source
            or source["status"] != "tentative"
            or source_id not in state["plan"]["remaining"]
            or not isinstance(children, list)
            or len(children) < 1
        ):
            raise _Reject("invalid refinement source")
        normalized: list[tuple[str, str, int]] = []
        for child in children:
            if not isinstance(child, Mapping) or set(child) != {"claim", "owner", "demand"}:
                raise _Reject("refinement child has target plan fields")
            child_id, owner = str(child["claim"]), str(child["owner"])
            demand = _operation_natural(child["demand"], f"child demand {child_id}")
            if child_id in state["claims"] or state["branch_epochs"].get(owner) != "open":
                raise _Reject("invalid refinement child")
            normalized.append((child_id, owner, demand))
        if len({child[0] for child in normalized}) != len(normalized):
            raise _Reject("duplicate refinement child")
        child_load = sum(child[2] for child in normalized)
        if child_load > int(source["demand"]):
            raise _Reject("refinement violates demand conservation")

        source_token = state["token_ledger"]["origin"].get(source_id)
        if source_token not in state["token_ledger"]["initial"]:
            raise _Reject("refinement source lacks an initial origin token")
        if len(normalized) > 1:
            raise _Reject("computed target duplicates one origin token")

        plan = state["plan"]
        slot, batch_root = plan["root_slot"][source_id], plan["batch_root"][source_id]
        for _, owner, _ in normalized:
            existing_roots = {
                plan["root_slot"].get(claim_id)
                for claim_id, claim in state["claims"].items()
                if claim["status"] == "tentative" and claim.get("owner") == owner
            }
            if existing_roots and existing_roots != {slot}:
                raise _Reject("refinement child owner has a different plan root")
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
        plan["W"][slot][source["grant"]] += int(source["demand"]) - child_load
        plan["remaining"] = sorted(plan["remaining"])
        state["claims"] = dict(sorted(state["claims"].items()))
        for key in ("root_slot", "batch_root", "disposition"):
            plan[key] = dict(sorted(plan[key].items()))
        plan["version"] += 1
        state["global_version"] += 1
        plan["current_slot"] = _current_slot(state)
        state["token_ledger"]["origin"] = dict(
            sorted(state["token_ledger"]["origin"].items())
        )
        _reclassify_tokens(state)

    def _merge(self, state: dict[str, Any], op: Mapping[str, Any]) -> None:
        self._require_fields(op, {"plan_version", "source_owners", "target_owner"})
        self._check_version(state, op)
        raw_sources = op["source_owners"]
        target = str(op["target_owner"])
        if not isinstance(raw_sources, list):
            raise _Reject("source_owners must be a list")
        sources = {str(owner) for owner in raw_sources}
        if (
            len(sources) < 2
            or any(state["branch_epochs"].get(owner) != "open" for owner in sources)
            or target in state["branch_epochs"]
        ):
            raise _Reject("invalid merge owners")
        affected = sorted(
            claim_id
            for claim_id, claim in state["claims"].items()
            if claim["status"] == "tentative" and claim.get("owner") in sources
        )
        planned = [claim for claim in affected if claim in state["plan"]["remaining"]]
        if not planned or not all(
            any(state["claims"][claim]["owner"] == owner for claim in affected)
            for owner in sources
        ):
            raise _Reject("merge has no complete computed planned fiber")
        lineage = {
            (
                state["plan"]["root_slot"].get(claim),
                state["plan"]["batch_root"].get(claim),
            )
            for claim in affected
        }
        if len(lineage) != 1 or next(iter(lineage))[0] is None:
            raise _Reject("mixed-root or cross-slot merge")
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
        _reclassify_tokens(state)

    def _revoke(self, state: dict[str, Any], op: Mapping[str, Any]) -> None:
        self._require_fields(op, {"plan_version", "grant"})
        self._check_version(state, op)
        grant = str(op["grant"])
        if state["grant_epochs"].get(grant) != "open":
            raise _Reject("grant is not open")
        state["grant_epochs"][grant] = "closed"
        state["grant_versions"][grant] += 1
        for claim_id, claim in state["claims"].items():
            if claim["grant"] == grant and claim["status"] == "tentative":
                self._withdraw_claim(state, claim_id)
                claim["status"], claim["owner"] = "terminal", None
                claim["revision"] += 1
        state["plan"]["remaining"] = sorted(state["plan"]["remaining"])
        state["plan"]["version"] += 1
        state["global_version"] += 1
        state["plan"]["current_slot"] = _current_slot(state)
        _reclassify_tokens(state)

    def _restrict(self, state: dict[str, Any], op: Mapping[str, Any]) -> None:
        self._require_fields(op, {"plan_version", "keep_owners"})
        self._check_version(state, op)
        raw_keep = op["keep_owners"]
        if not isinstance(raw_keep, list):
            raise _Reject("keep_owners must be a list")
        keep = {str(owner) for owner in raw_keep}
        for owner, epoch in list(state["branch_epochs"].items()):
            if epoch == "open" and owner not in keep:
                state["branch_epochs"][owner] = "closed"
        for claim_id, claim in state["claims"].items():
            if claim["status"] == "tentative" and claim.get("owner") not in keep:
                self._withdraw_claim(state, claim_id)
                claim["status"], claim["owner"] = "terminal", None
                claim["revision"] += 1
        state["plan"]["remaining"] = sorted(state["plan"]["remaining"])
        state["plan"]["version"] += 1
        state["global_version"] += 1
        state["plan"]["current_slot"] = _current_slot(state)
        _reclassify_tokens(state)

    def _dispatch(self, state: dict[str, Any], op: Mapping[str, Any], retry: bool) -> None:
        self._require_fields(op, {"effect"})
        effect = str(op["effect"])
        if effect in state["receipts"]:
            raise _Reject("effect already settled")
        ticket = state["tickets"].get(effect)
        if not ticket:
            raise _Reject("missing durable ticket")
        if retry and ticket["phase"] not in {"inflight", "uncertain"}:
            raise _Reject("retry requires inflight or uncertain ticket")
        if not retry and ticket["phase"] != "prepared":
            raise _Reject("dispatch requires prepared ticket")
        # Deliberately no plan-version, current-slot, owner, or grant-epoch read.
        ticket["phase"] = "inflight"
        state["global_version"] += 1

    def _crash(self, state: dict[str, Any], op: Mapping[str, Any]) -> None:
        self._require_fields(op, set(), {"effects"})
        changed = sorted(
            effect for effect, ticket in state["tickets"].items() if ticket["phase"] == "inflight"
        )
        declared = op.get("effects")
        if declared is not None:
            if not isinstance(declared, list) or sorted(map(str, declared)) != changed:
                raise _Reject("crash effects disagree with inflight tickets")
        for effect in changed:
            state["tickets"][effect]["phase"] = "uncertain"
        state["global_version"] += 1

    def _settle(self, state: dict[str, Any], op: Mapping[str, Any]) -> None:
        self._require_fields(op, {"effect", "outcome"})
        effect, outcome = str(op["effect"]), str(op["outcome"])
        ticket = state["tickets"].get(effect)
        if not ticket or ticket["phase"] not in {"inflight", "uncertain"}:
            raise _Reject("settlement requires a dispatched durable ticket")
        if outcome not in {"succeeded", "failed", "cancelled"}:
            raise _Reject("invalid outcome")
        del state["tickets"][effect]
        state["receipts"][effect] = {"claim": ticket["claim"], "outcome": outcome}
        state["global_version"] += 1

    def _transition(self, state: dict[str, Any], op: Mapping[str, Any]) -> None:
        kind = str(op.get("op", ""))
        if kind == "prepare":
            self._prepare(state, op)
        elif kind == "disjoint_mutation":
            self._disjoint_mutation(state, op)
        elif kind == "refine":
            self._refine(state, op)
        elif kind == "merge":
            self._merge(state, op)
        elif kind == "revoke":
            self._revoke(state, op)
        elif kind == "restrict":
            self._restrict(state, op)
        elif kind == "dispatch":
            self._dispatch(state, op, False)
        elif kind == "retry":
            self._dispatch(state, op, True)
        elif kind == "crash":
            self._crash(state, op)
        elif kind == "settle":
            self._settle(state, op)
        else:
            raise _Reject(f"unsupported operation {kind}")

    def apply(
        self, operation: Mapping[str, Any], *, crash_at: str | None = None
    ) -> PlanDecision:
        if crash_at not in {None, "before_commit", "after_commit"}:
            raise ValueError("unknown crash boundary")
        op = deepcopy(dict(operation))
        kind = str(op.get("op", ""))
        self._db.execute("BEGIN IMMEDIATE")
        try:
            state, _, _ = self._load()
            # A malformed loaded source is store corruption and remains a hard
            # error.  Only a controller-computed malformed successor becomes
            # an auditable reject below.
            validate_state(state)
            candidate = deepcopy(state)
            try:
                self._transition(candidate, op)
                validate_state(candidate)
                accepted, reason = True, "admitted"
                successor = candidate
            except _Reject as rejection:
                accepted, reason = False, str(rejection)
                successor = state
            except PlanPilotError as invalid_candidate:
                accepted = False
                reason = f"computed successor invalid: {invalid_candidate}"
                successor = state
            event = self._append_locked(
                kind if accepted else "reject",
                {"operation": op, "accepted": accepted, "reason": reason},
                successor,
            )
            if crash_at == "before_commit":
                raise InjectedCrash("injected before SQLite commit")
            self._db.commit()
        except BaseException:
            self._db.rollback()
            raise
        if crash_at == "after_commit":
            raise InjectedCrash("injected after SQLite commit")
        return PlanDecision(kind, accepted, reason, int(event["seq"]), str(event["state_hash"]))


def service_protected_callback(
    controller: PlanPilotController,
    *,
    effect: str,
    callback: Callable[[Mapping[str, str]], Mapping[str, Any]],
) -> dict[str, Any]:
    """Gate a client-owned tool callback or sink with a durable ticket.

    The callback receives only the stable durable ticket binding.  The pilot
    test invokes this function while a real Codex App Server
    ``item/tool/call`` is pending, so dispatch admission precedes the client
    response.  This narrow integration does not make Codex emit plan metadata
    or couple native fork activation to Prepare; no plan object crosses the
    callback boundary.
    """

    dispatch = controller.apply({"op": "dispatch", "effect": effect})
    if not dispatch.accepted:
        return {"status": "rejected", "dispatch": dispatch.as_dict()}
    ticket = controller.snapshot()["state"]["tickets"][effect]
    result = dict(callback({"effect": effect, "claim": str(ticket["claim"])}))
    outcome = str(result.get("outcome", ""))
    settlement = controller.apply({"op": "settle", "effect": effect, "outcome": outcome})
    if not settlement.accepted:
        raise PlanPilotError(f"callback completed but settlement failed: {settlement.reason}")
    return {
        "status": "completed",
        "binding": {"effect": effect, "claim": str(ticket["claim"])},
        "outcome": outcome,
        "dispatch": dispatch.as_dict(),
        "settlement": settlement.as_dict(),
        "callback_result": result,
    }


__all__ = [
    "InjectedCrash",
    "PlanDecision",
    "PlanPilotController",
    "PlanPilotError",
    "canonical_json",
    "digest",
    "initial_state",
    "service_protected_callback",
    "validate_state",
]
