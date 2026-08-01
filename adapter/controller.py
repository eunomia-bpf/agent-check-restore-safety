"""Durable authority controller used by the fixed Codex runtime litmus suite.

The implementation is intentionally independent of :mod:`adapter.replay` and
the evaluation oracle.  It stores a full operational state for recovery, but
emits only append-only checked deltas.  The independent replay decoder rebuilds
the P3 state from those deltas and verifies the event/state hash chain.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
from itertools import combinations
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Mapping


ZERO_HASH = "0" * 64
POLICIES = frozenset({"P0", "P1", "P2", "P3"})


class ControllerError(RuntimeError):
    pass


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _powerset(values: Iterable[str]) -> set[frozenset[str]]:
    ordered = sorted(set(values))
    return {
        frozenset(group)
        for size in range(len(ordered) + 1)
        for group in combinations(ordered, size)
    }


def _downward(maxima: Iterable[Iterable[str]]) -> set[frozenset[str]]:
    result = {frozenset()}
    for maximum in maxima:
        result.update(_powerset(maximum))
    return result


def _frontier_from_json(value: Iterable[Iterable[str]]) -> set[frozenset[str]]:
    return {frozenset(map(str, config)) for config in value}


def _frontier_json(value: Iterable[frozenset[str]]) -> list[list[str]]:
    # This is part of the durable state-hash contract.  Keep the ordering
    # byte-for-byte identical to ReplayState.semantic_dict(), which uses the
    # ordinary lexicographic ordering of the canonical branch lists.
    return sorted(sorted(config) for config in value)


def _maxima(frontier: set[frozenset[str]]) -> list[set[str]]:
    return [set(config) for config in frontier if not any(config < other for other in frontier)]


def _replace_frontier(
    frontier: set[frozenset[str]], source: str, replacements: list[set[str]]
) -> set[frozenset[str]]:
    maxima: list[set[str]] = []
    for config in frontier:
        if source in config:
            base = set(config) - {source}
            maxima.extend(base | replacement for replacement in replacements)
        else:
            maxima.append(set(config))
    return _downward(maxima)


def _semantic_state(grants: Mapping[str, int]) -> dict[str, Any]:
    grant_map = {str(grant): int(capacity) for grant, capacity in grants.items()}
    return {
        "grants": dict(sorted(grant_map.items())),
        "grant_epochs": {grant: "open" for grant in sorted(grant_map)},
        "branch_epochs": {"root": "open"},
        "active_branches": ["root"],
        "frontier": [[], ["root"]],
        "claims": {},
        "tickets": {},
        "receipts": {},
        "checkpoints": {},
        "delegations": {grant: ["root"] for grant in sorted(grant_map)},
        "forks": {},
    }


def semantic_state_hash(state: Mapping[str, Any]) -> str:
    return digest(state)


@dataclass(frozen=True)
class Decision:
    request: str | None
    operation: str
    accepted: bool
    reason: str
    abstract_label: str | None
    event_seq: int
    state_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "request": self.request,
            "operation": self.operation,
            "decision": "accept" if self.accepted else "reject",
            "reason": self.reason,
            "abstract_label": self.abstract_label,
            "event_seq": self.event_seq,
            "state_hash": self.state_hash,
        }


class DurableController:
    """SQLite-backed controller with one crash-atomic event per transition."""

    def __init__(
        self,
        db_path: str | Path,
        policy: str,
        grants: Mapping[str, int] | None = None,
    ) -> None:
        if policy not in POLICIES:
            raise ValueError(f"unknown policy: {policy}")
        self.path = Path(db_path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.policy = policy
        self._db = sqlite3.connect(self.path, timeout=30.0, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS controller_meta(
              singleton INTEGER PRIMARY KEY CHECK(singleton=1),
              policy TEXT NOT NULL,
              state_json TEXT NOT NULL,
              policy_json TEXT NOT NULL,
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
            CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
            BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
            CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
            BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
            """
        )
        row = self._db.execute("SELECT * FROM controller_meta WHERE singleton=1").fetchone()
        if row is None:
            if not grants:
                raise ValueError("new controller requires a nonempty grants map")
            if any(int(value) <= 0 for value in grants.values()):
                raise ValueError("grant capacities must be positive")
            state = _semantic_state(grants)
            policy_state = {
                "budgets": {grant: {"root": int(capacity)} for grant, capacity in grants.items()},
                "escrow": {grant: 0 for grant in grants},
            }
            self._db.execute("BEGIN IMMEDIATE")
            try:
                self._db.execute(
                    "INSERT INTO controller_meta VALUES(1,?,?,?,?,?)",
                    (policy, canonical_json(state), canonical_json(policy_state), 0, ZERO_HASH),
                )
                operation = {
                    "op": "genesis",
                    "grants": dict(sorted((str(k), int(v)) for k, v in grants.items())),
                    "root": "root",
                    "active_branches": ["root"],
                    "maximal_frontiers": [["root"]],
                    "delegations": {str(grant): ["root"] for grant in sorted(grants)},
                }
                self._append_locked("genesis", {"operation": operation, "abstract_label": "tau", "actual": 0}, state, policy_state)
                self._db.commit()
            except BaseException:
                self._db.rollback()
                raise
        elif row["policy"] != policy:
            raise ControllerError("controller policy differs from durable database")

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> "DurableController":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _load(self) -> tuple[dict[str, Any], dict[str, Any], int, str]:
        row = self._db.execute("SELECT * FROM controller_meta WHERE singleton=1").fetchone()
        if row is None:
            raise ControllerError("missing controller metadata")
        return (
            json.loads(row["state_json"]),
            json.loads(row["policy_json"]),
            int(row["sequence"]),
            str(row["head_hash"]),
        )

    def snapshot(self) -> dict[str, Any]:
        state, policy_state, sequence, head = self._load()
        return {
            "policy": self.policy,
            "state": state,
            "policy_state": policy_state,
            "sequence": sequence,
            "head_hash": head,
            "state_hash": semantic_state_hash(state),
        }

    def events(self) -> list[dict[str, Any]]:
        rows = self._db.execute("SELECT * FROM events ORDER BY seq").fetchall()
        return [
            {
                "seq": int(row["seq"]),
                "previous_hash": row["previous_hash"],
                "event_hash": row["event_hash"],
                "state_hash": row["state_hash"],
                "kind": row["kind"],
                "body_hash": row["body_hash"],
                "body": json.loads(row["body_json"]),
            }
            for row in rows
        ]

    def _append_locked(
        self,
        kind: str,
        body: Mapping[str, Any],
        state: Mapping[str, Any],
        policy_state: Mapping[str, Any],
    ) -> dict[str, Any]:
        row = self._db.execute("SELECT sequence,head_hash FROM controller_meta WHERE singleton=1").fetchone()
        if row is None:
            raise ControllerError("missing controller metadata")
        seq = int(row["sequence"]) + 1
        previous = str(row["head_hash"])
        canonical_body = dict(body)
        body_digest = digest(canonical_body)
        successor_hash = semantic_state_hash(state)
        envelope_core = {
            "seq": seq,
            "previous_hash": previous,
            "state_hash": successor_hash,
            "kind": kind,
            "body_hash": body_digest,
        }
        event_digest = digest(envelope_core)
        self._db.execute(
            "INSERT INTO events VALUES(?,?,?,?,?,?,?)",
            (seq, previous, event_digest, successor_hash, kind, body_digest, canonical_json(canonical_body)),
        )
        self._db.execute(
            "UPDATE controller_meta SET state_json=?,policy_json=?,sequence=?,head_hash=? WHERE singleton=1",
            (canonical_json(state), canonical_json(policy_state), seq, event_digest),
        )
        return {**envelope_core, "event_hash": event_digest, "body": canonical_body}

    @staticmethod
    def _frontier(state: Mapping[str, Any]) -> set[frozenset[str]]:
        return _frontier_from_json(state["frontier"])

    @staticmethod
    def _set_frontier(state: dict[str, Any], frontier: set[frozenset[str]]) -> None:
        state["frontier"] = _frontier_json(frontier)
        state["active_branches"] = sorted(set().union(*frontier) if frontier else set())

    @staticmethod
    def _violations(state: Mapping[str, Any]) -> list[str]:
        failures: list[str] = []
        for grant, capacity in state["grants"].items():
            for config in _frontier_from_json(state["frontier"]):
                load = 0
                for claim in state["claims"].values():
                    if claim["grant"] != grant:
                        continue
                    if claim["status"] == "durable" or (
                        claim["status"] == "tentative" and claim.get("owner") in config
                    ):
                        load += int(claim["demand"])
                if load > int(capacity):
                    failures.append(f"grant {grant} load {load}>{capacity} on {sorted(config)}")
        return failures

    @staticmethod
    def _close(state: dict[str, Any], branches: set[str]) -> None:
        if not branches:
            return
        for branch in branches:
            state["branch_epochs"][branch] = "closed"
        frontier = {config - branches for config in _frontier_from_json(state["frontier"])}
        DurableController._set_frontier(state, _downward(frontier))
        for claim in state["claims"].values():
            if claim["status"] == "tentative" and claim.get("owner") in branches:
                claim["status"] = "terminal"
                claim["owner"] = None
        for grant in state["delegations"]:
            state["delegations"][grant] = sorted(set(state["delegations"][grant]) - branches)

    def _admit_budget(self, op: Mapping[str, Any], policy_state: dict[str, Any]) -> tuple[bool, str]:
        branch, grant, demand = str(op["branch"]), str(op["grant"]), int(op["demand"])
        if self.policy == "P0":
            return True, "workspace-local admission"
        if self.policy == "P3":
            return True, "correlated controller"
        available = int(policy_state["budgets"].get(grant, {}).get(branch, 0))
        if available < demand:
            return False, f"local budget {available}<{demand}"
        policy_state["budgets"][grant][branch] = available - demand
        return True, "local budget"

    def _apply_candidate(
        self, state: dict[str, Any], policy_state: dict[str, Any], op: Mapping[str, Any]
    ) -> tuple[bool, str, str]:
        kind = str(op["op"])
        active = set(state["active_branches"])
        label = "attempt" if kind in {"dispatch", "retry"} else "tau"

        if kind == "checkpoint":
            checkpoint, branch = str(op["checkpoint"]), str(op["branch"])
            if checkpoint in state["checkpoints"] or branch not in active:
                return False, "invalid checkpoint", label
            state["checkpoints"][checkpoint] = {"branch": branch}

        elif kind == "fork":
            source, fork_kind = str(op["source"]), str(op["kind"])
            raw_children = op["children"]
            if not isinstance(raw_children, (list, tuple)):
                return False, "fork children must be a list", label
            children = [str(child) for child in raw_children]
            if source not in active or fork_kind not in {"choice", "parallel"}:
                return False, "invalid fork", label
            if len(children) < 2 or len(set(children)) != len(children):
                return False, "fork needs distinct children", label
            if any(child in state["branch_epochs"] for child in children):
                return False, "reused branch id", label
            if any(c["status"] == "tentative" and c.get("owner") == source for c in state["claims"].values()):
                return False, "fork requires explicit claim transfer", label
            replacements = [{child} for child in children] if fork_kind == "choice" else [set(children)]
            self._set_frontier(state, _replace_frontier(self._frontier(state), source, replacements))
            state["branch_epochs"][source] = "closed"
            for child in children:
                state["branch_epochs"][child] = "open"
            state["forks"][source] = {"kind": fork_kind, "children": children}
            for grant, branches in state["delegations"].items():
                members = set(branches)
                if source in members:
                    members.remove(source)
                    members.update(children)
                state["delegations"][grant] = sorted(members)
            for grant, budgets in policy_state["budgets"].items():
                source_budget = int(budgets.pop(source, 0))
                if self.policy == "P1":
                    quotient, remainder = divmod(source_budget, len(children))
                    for index, child in enumerate(sorted(children)):
                        budgets[child] = quotient + (1 if index < remainder else 0)
                elif self.policy == "P2":
                    policy_state["escrow"][grant] += source_budget
                    for child in children:
                        budgets[child] = 0
                else:
                    for child in children:
                        budgets[child] = source_budget

        elif kind == "restore":
            source, target, mode = str(op["source"]), str(op["target"]), str(op["mode"])
            checkpoint = state["checkpoints"].get(str(op["checkpoint"]))
            if not checkpoint or checkpoint["branch"] != source or source not in active:
                return False, "invalid restore source", label
            if target in state["branch_epochs"] or mode not in {"replace", "live"}:
                return False, "invalid restore target", label
            inherited = [g for g, branches in state["delegations"].items() if source in branches]
            if mode == "replace":
                self._set_frontier(state, _replace_frontier(self._frontier(state), source, [{target}]))
                self._close(state, {source})
            else:
                self._set_frontier(state, _replace_frontier(self._frontier(state), source, [{source, target}]))
            state["branch_epochs"][target] = "open"
            state["active_branches"] = sorted(set(state["active_branches"]) | {target})
            for grant in inherited:
                state["delegations"][grant] = sorted(set(state["delegations"][grant]) | {target})
            for grant, budgets in policy_state["budgets"].items():
                source_budget = int(budgets.get(source, 0))
                if mode == "replace":
                    budgets.pop(source, None)
                    budgets[target] = source_budget
                elif self.policy == "P1":
                    left, right = divmod(source_budget, 2)
                    budgets[source] = left + right
                    budgets[target] = left
                elif self.policy == "P2":
                    policy_state["escrow"][grant] += source_budget
                    budgets[source] = budgets[target] = 0
                else:
                    budgets[target] = source_budget

        elif kind == "delegate":
            grant, branch = str(op["grant"]), str(op["branch"])
            if state["grant_epochs"].get(grant) != "open" or branch not in active:
                return False, "invalid delegation", label
            if any(
                claim["grant"] == grant
                and claim["status"] == "tentative"
                and claim.get("owner") != branch
                for claim in state["claims"].values()
            ):
                return False, "delegation would strand a tentative claim", label
            state["delegations"][grant] = [branch]
            capacity = int(state["grants"][grant])
            policy_state["budgets"][grant] = {branch: capacity}
            policy_state["escrow"][grant] = 0

        elif kind == "select":
            branch = str(op["branch"])
            group = next((g for g in state["forks"].values() if g["kind"] == "choice" and branch in g["children"]), None)
            if group is None or branch not in active:
                return False, "invalid selection", label
            retired = set(group["children"]) - {branch}
            self._close(state, retired)
            if self.policy == "P2":
                for grant, amount in policy_state["escrow"].items():
                    policy_state["budgets"][grant][branch] = int(amount)
                    policy_state["escrow"][grant] = 0

        elif kind == "reserve":
            claim, branch, grant = str(op["claim"]), str(op["branch"]), str(op["grant"])
            raw_demand = op["demand"]
            if isinstance(raw_demand, bool) or not isinstance(raw_demand, int) or raw_demand <= 0:
                return False, "reserve demand must be positive", label
            demand = raw_demand
            structural = (
                claim not in state["claims"]
                and branch in active
                and state["branch_epochs"].get(branch) == "open"
                and state["grant_epochs"].get(grant) == "open"
            )
            if self.policy == "P3":
                structural = structural and branch in state["delegations"].get(grant, [])
            if not structural:
                return False, "reserve structural premise", label
            budget_state = deepcopy(policy_state)
            admitted, reason = self._admit_budget(op, budget_state)
            if not admitted:
                return False, reason, label
            state["claims"][claim] = {"grant": grant, "demand": demand, "status": "tentative", "owner": branch}
            if self.policy == "P3" and self._violations(state):
                return False, "correlated authority deficit", label
            policy_state.clear(); policy_state.update(budget_state)

        elif kind == "prepare":
            effect, claim = str(op["effect"]), str(op["claim"])
            value = state["claims"].get(claim)
            if not value or value["status"] != "tentative" or effect in state["tickets"] or effect in state["receipts"]:
                return False, "prepare structural premise", label
            if state["grant_epochs"].get(value["grant"]) != "open" and self.policy == "P0":
                return False, "local revoke bit", label
            value["status"], value["owner"] = "durable", None
            state["tickets"][effect] = {"claim": claim, "phase": "prepared"}
            if self.policy == "P3":
                solvent = {config for config in self._frontier(state) if not self._violations({**state, "frontier": _frontier_json({config})})}
                if frozenset() not in solvent:
                    return False, "durable load exceeds grant", label
                retired = set(state["active_branches"]) - (
                    set().union(*solvent) if solvent else set()
                )
                self._set_frontier(state, solvent)
                self._close(state, retired)

        elif kind == "revoke":
            grant = str(op["grant"])
            if state["grant_epochs"].get(grant) != "open":
                return False, "grant already closed", label
            state["grant_epochs"][grant] = "closed"
            state["delegations"][grant] = []
            for value in state["claims"].values():
                if value["grant"] == grant and value["status"] == "tentative":
                    value["status"], value["owner"] = "terminal", None

        elif kind in {"dispatch", "retry"}:
            effect = str(op["effect"])
            if effect in state["receipts"]:
                return False, "effect already settled", label
            ticket = state["tickets"].get(effect)
            if not ticket:
                return False, "missing stable ticket", label
            if kind == "dispatch" and ticket["phase"] != "prepared":
                return False, "dispatch requires prepared", label
            if kind == "retry" and ticket["phase"] not in {"inflight", "uncertain"}:
                return False, "retry requires uncertain/inflight", label
            ticket["phase"] = "inflight"
            op = dict(op); op.setdefault("claim", ticket["claim"])

        elif kind == "crash":
            changed = []
            for effect, ticket in state["tickets"].items():
                if ticket["phase"] == "inflight":
                    ticket["phase"] = "uncertain"; changed.append(effect)
            declared = op.get("effects")
            if declared is not None and set(map(str, declared)) != set(changed):
                return False, "crash delta disagrees with inflight tickets", label

        elif kind == "settle":
            effect, outcome = str(op["effect"]), str(op["outcome"])
            ticket = state["tickets"].get(effect)
            if not ticket or effect in state["receipts"]:
                return False, "missing or settled ticket", label
            if outcome not in {"succeeded", "failed", "cancelled"}:
                return False, "invalid receipt outcome", label
            if ticket["phase"] == "prepared" and outcome != "cancelled":
                return False, "prepared ticket may only cancel", label
            del state["tickets"][effect]
            state["receipts"][effect] = {"claim": ticket["claim"], "outcome": outcome}
            op = dict(op); op.setdefault("claim", ticket["claim"])

        elif kind == "merge":
            raw_sources = op["sources"]
            raw_keep = op.get("retain_claims", [])
            if not isinstance(raw_sources, (list, tuple)) or not isinstance(raw_keep, (list, tuple)):
                return False, "merge sources and retained claims must be lists", label
            sources, target = set(map(str, raw_sources)), str(op["target"])
            keep = set(map(str, raw_keep))
            mode = str(op.get("mode", ""))
            if (
                len(sources) < 2
                or not sources <= active
                or target in state["branch_epochs"]
                or mode not in {"certified", "direct"}
            ):
                return False, "invalid merge structure", label
            tentative = {cid for cid, value in state["claims"].items() if value["status"] == "tentative" and value.get("owner") in sources}
            if not keep <= tentative:
                return False, "merge retains foreign claim", label
            if self.policy == "P3" and mode == "certified":
                certificate = op.get("certificate")
                if not isinstance(certificate, Mapping) or set(certificate) != {"projection", "claim_map"}:
                    return False, "certified merge requires a canonical certificate", label
                projection = certificate.get("projection")
                claim_map = certificate.get("claim_map")
                if not isinstance(projection, Mapping) or set(projection) != {
                    "target_configuration",
                    "source_configuration",
                }:
                    return False, "malformed merge projection", label
                raw_target_configuration = projection.get("target_configuration")
                raw_source_configuration = projection.get("source_configuration")
                if not isinstance(raw_target_configuration, list) or not isinstance(raw_source_configuration, list):
                    return False, "merge projection configurations must be lists", label
                target_configuration = list(map(str, raw_target_configuration))
                source_configuration = set(map(str, raw_source_configuration))
                if target_configuration != [target] or not source_configuration or not source_configuration <= sources:
                    return False, "merge projection does not map the target to a source configuration", label
                if frozenset(source_configuration) not in self._frontier(state):
                    return False, "merge projection source is not admitted", label
                if not isinstance(claim_map, list) or any(not isinstance(entry, Mapping) for entry in claim_map):
                    return False, "merge claim map must be a list of entries", label
                bindings: dict[str, str] = {}
                for entry in claim_map:
                    if set(entry) != {"source_claim", "target_claim"}:
                        return False, "malformed merge claim-map entry", label
                    source_claim, target_claim = str(entry["source_claim"]), str(entry["target_claim"])
                    if source_claim in bindings:
                        return False, "merge claim map is not injective", label
                    bindings[source_claim] = target_claim
                if set(bindings) != keep or set(bindings.values()) != keep:
                    return False, "merge claim map differs from retained claims", label
                if any(
                    bindings[claim] != claim
                    or state["claims"][claim].get("owner") not in source_configuration
                    for claim in keep
                ):
                    return False, "merge certificate does not source each retained claim", label
            frontier = self._frontier(state)
            new_frontier = _downward((set(config) - sources) | ({target} if set(config) & sources else set()) for config in frontier)
            self._set_frontier(state, new_frontier)
            inherited = [g for g, branches in state["delegations"].items() if set(branches) & sources]
            self._close(state, sources)
            state["branch_epochs"][target] = "open"
            state["active_branches"] = sorted(set(state["active_branches"]) | {target})
            for grant in inherited:
                state["delegations"][grant] = sorted(set(state["delegations"][grant]) | {target})
            for cid in tentative:
                value = state["claims"][cid]
                if cid in keep:
                    value["status"], value["owner"] = "tentative", target
                else:
                    value["status"], value["owner"] = "terminal", None
            if self.policy == "P3" and self._violations(state):
                return False, "merge authority deficit", label

        else:
            return False, f"unsupported operation {kind}", label

        if self.policy == "P3" and self._violations(state):
            return False, "authority continuity violation", label
        return True, "admitted", label

    def apply(self, operation: Mapping[str, Any]) -> Decision:
        op = dict(operation)
        kind = str(op.get("op", ""))
        if kind == "grant" or not kind:
            raise ControllerError("grants are batch genesis inputs, not runtime operations")
        request = str(op["request"]) if "request" in op else None
        self._db.execute("BEGIN IMMEDIATE")
        try:
            state, policy_state, _, _ = self._load()
            candidate_state, candidate_policy = deepcopy(state), deepcopy(policy_state)
            accepted, reason, label = self._apply_candidate(candidate_state, candidate_policy, op)
            if accepted:
                body: dict[str, Any] = {"operation": op, "abstract_label": label, "actual": 1 if label == "attempt" else 0}
                event = self._append_locked(kind, body, candidate_state, candidate_policy)
            else:
                reject_op = {"op": "reject", "action": op}
                event = self._append_locked("reject", {"operation": reject_op, "actual": 0}, state, policy_state)
            self._db.commit()
        except BaseException:
            self._db.rollback()
            raise
        return Decision(request, kind, accepted, reason, label if accepted else None, int(event["seq"]), str(event["state_hash"]))

    def recover_after_crash(self, effect: str) -> Decision:
        """Durably model process recovery, then leave reconciliation to worker."""
        return self.apply({"op": "crash", "request": f"crash_{effect}", "effects": [effect]})


__all__ = ["ControllerError", "Decision", "DurableController", "POLICIES"]
