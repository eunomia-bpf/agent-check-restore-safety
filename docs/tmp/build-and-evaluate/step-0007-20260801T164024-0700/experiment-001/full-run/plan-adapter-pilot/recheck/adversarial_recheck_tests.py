"""Independent post-repair adversarial checks for the plan-aware pilot.

The review is intentionally black/grey box.  It does not modify the adapter
implementation.  It forges hash-consistent event envelopes, rewrites temporary
SQLite stores, differentially compares the controller with the separately
implemented reference transition, and traverses the real Codex App Server
callback seam.
"""

from __future__ import annotations

import ast
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import threading
import unittest


REPOSITORY = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (parent / "adapter" / "plan_pilot.py").is_file()
)
sys.path.insert(0, str(REPOSITORY))

from adapter.plan_pilot import (  # noqa: E402
    InjectedCrash,
    PlanPilotController,
    PlanPilotError,
    canonical_json,
    service_protected_callback,
)
from adapter.plan_pilot_runner import controlled_decisions  # noqa: E402
from adapter.plan_replay import (  # noqa: E402
    ReplayError,
    aggregate_json,
    digest,
    reference_transition,
    replay_events,
    semantic_transport_safe,
    transition_oracle_safe,
)


RECORD = (
    REPOSITORY
    / "docs/tmp/build-and-evaluate/step-0007-20260801T164024-0700/"
    "experiment-001/full-run/plan-adapter-pilot"
)


def forge_event(
    previous: dict,
    *,
    operation: dict,
    accepted: bool,
    successor: dict,
    kind: str | None = None,
    reason: str = "independent forged diagnostic",
) -> dict:
    """Build a fully rehashed successor event after ``previous``."""

    body = {
        "operation": deepcopy(operation),
        "accepted": accepted,
        "reason": reason,
        "successor_state": deepcopy(successor),
    }
    envelope = {
        "seq": int(previous["seq"]) + 1,
        "previous_hash": previous["event_hash"],
        "state_hash": digest(successor),
        "kind": kind if kind is not None else (str(operation.get("op", "")) if accepted else "reject"),
        "body_hash": digest(body),
    }
    return {**envelope, "event_hash": digest(envelope), "body": body}


class RuntimeRepairRecheck(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def one_claim(*, demand: int = 1) -> list[dict]:
        return [
            {
                "claim": "c",
                "grant": "g",
                "demand": demand,
                "owner": "o",
                "slot": "s",
                "batch_root": "r",
            }
        ]

    @staticmethod
    def same_root_claims(*, mixed_batch: bool = False) -> list[dict]:
        return [
            {
                "claim": "a",
                "grant": "g",
                "demand": 1,
                "owner": "oa",
                "slot": "s",
                "batch_root": "ra" if mixed_batch else "r",
            },
            {
                "claim": "b",
                "grant": "g",
                "demand": 1,
                "owner": "ob",
                "slot": "s",
                "batch_root": "rb" if mixed_batch else "r",
            },
        ]

    def controller(
        self,
        name: str,
        *,
        claims: list[dict] | None = None,
        capacity: int = 2,
    ) -> PlanPilotController:
        return PlanPilotController(
            self.root / f"{name}.sqlite3",
            grants={"g": capacity},
            ordered_slots=["s"],
            claims=self.one_claim() if claims is None else claims,
            plan_id=name,
        )

    def assert_controller_matches_reference(
        self, controller: PlanPilotController, operation: dict
    ) -> None:
        source = controller.snapshot()["state"]
        reference = reference_transition(source, operation)
        decision = controller.apply(operation)
        self.assertEqual(reference.accepted, decision.accepted, operation)
        self.assertEqual(reference.successor, controller.snapshot()["state"], operation)
        replayed = replay_events(
            controller.events(),
            expected_head_hash=controller.snapshot()["head_hash"],
            expected_state_hash=controller.snapshot()["state_hash"],
        )
        self.assertEqual(reference.successor, replayed.state)

    def test_repair_hash_manifest_matches_reviewed_bytes(self) -> None:
        manifest = RECORD / "repair-sha256.txt"
        for line in manifest.read_text(encoding="utf-8").splitlines():
            expected, relative = line.split(maxsplit=1)
            payload = (REPOSITORY / relative).read_bytes()
            self.assertEqual(expected, sha256(payload).hexdigest(), relative)

    def test_all_ten_controller_operations_match_independent_successors(self) -> None:
        with self.controller("prepare", capacity=1) as controller:
            self.assert_controller_matches_reference(
                controller,
                {"op": "prepare", "plan_version": 0, "assignments": {"e": "c"}},
            )

        with self.controller("disjoint", capacity=2) as controller:
            self.assert_controller_matches_reference(
                controller,
                {
                    "op": "disjoint_mutation",
                    "claim": "outside",
                    "grant": "g",
                    "demand": 1,
                    "owner": "outside-owner",
                },
            )

        with self.controller("refine", capacity=1) as controller:
            self.assert_controller_matches_reference(
                controller,
                {
                    "op": "refine",
                    "plan_version": 0,
                    "source_claim": "c",
                    "children": [{"claim": "child", "owner": "o", "demand": 1}],
                },
            )

        with self.controller(
            "merge", claims=self.same_root_claims(), capacity=2
        ) as controller:
            self.assert_controller_matches_reference(
                controller,
                {
                    "op": "merge",
                    "plan_version": 0,
                    "source_owners": ["oa", "ob"],
                    "target_owner": "joined",
                },
            )

        with self.controller("revoke", capacity=1) as controller:
            self.assert_controller_matches_reference(
                controller, {"op": "revoke", "plan_version": 0, "grant": "g"}
            )

        with self.controller("restrict", capacity=1) as controller:
            self.assert_controller_matches_reference(
                controller,
                {"op": "restrict", "plan_version": 0, "keep_owners": []},
            )

        for ticket_op in ("dispatch", "retry", "crash", "settle"):
            with self.controller(f"ticket-{ticket_op}", capacity=1) as controller:
                self.assertTrue(
                    controller.apply(
                        {
                            "op": "prepare",
                            "plan_version": 0,
                            "assignments": {"e": "c"},
                        }
                    ).accepted
                )
                if ticket_op in {"retry", "crash", "settle"}:
                    self.assertTrue(
                        controller.apply({"op": "dispatch", "effect": "e"}).accepted
                    )
                operation = {
                    "dispatch": {"op": "dispatch", "effect": "e"},
                    "retry": {"op": "retry", "effect": "e"},
                    "crash": {"op": "crash", "effects": ["e"]},
                    "settle": {
                        "op": "settle",
                        "effect": "e",
                        "outcome": "succeeded",
                    },
                }[ticket_op]
                self.assert_controller_matches_reference(controller, operation)

    def test_replay_rejects_forged_prepare_refine_revoke_and_crash_successors(self) -> None:
        fixtures: list[tuple[str, list[dict], int, list[dict], dict]] = [
            (
                "prepare",
                self.one_claim(),
                1,
                [],
                {"op": "prepare", "plan_version": 0, "assignments": {"e": "c"}},
            ),
            (
                "refine",
                self.one_claim(),
                1,
                [],
                {
                    "op": "refine",
                    "plan_version": 0,
                    "source_claim": "c",
                    "children": [{"claim": "child", "owner": "o", "demand": 1}],
                },
            ),
            (
                "revoke",
                self.one_claim(),
                1,
                [],
                {"op": "revoke", "plan_version": 0, "grant": "g"},
            ),
            (
                "crash",
                self.one_claim(),
                1,
                [
                    {"op": "prepare", "plan_version": 0, "assignments": {"e": "c"}},
                    {"op": "dispatch", "effect": "e"},
                ],
                {"op": "crash", "effects": ["e"]},
            ),
        ]
        for name, claims, capacity, setup, operation in fixtures:
            with self.subTest(operation=name):
                with self.controller(
                    f"forged-{name}", claims=claims, capacity=capacity
                ) as controller:
                    for prior in setup:
                        self.assertTrue(controller.apply(prior).accepted)
                    events = controller.events()
                    source = controller.snapshot()["state"]
                expected = reference_transition(source, operation)
                self.assertTrue(expected.accepted)
                forged_successor = deepcopy(expected.successor)
                # global_version is intentionally unconstrained by the state
                # invariant, so this remains invariant-valid and attacks exact
                # successor equality rather than merely target validation.
                forged_successor["global_version"] += 17
                forged = forge_event(
                    events[-1],
                    operation=operation,
                    accepted=True,
                    successor=forged_successor,
                )
                with self.assertRaisesRegex(ReplayError, "full-state recomputation"):
                    replay_events([*events, forged])

    def test_replay_rejects_valid_operation_faked_as_rejection(self) -> None:
        with self.controller("fake-reject", capacity=1) as controller:
            events = controller.events()
            source = controller.snapshot()["state"]
        operation = {
            "op": "prepare",
            "plan_version": 0,
            "assignments": {"e": "c"},
        }
        self.assertTrue(reference_transition(source, operation).accepted)
        forged = forge_event(
            events[-1],
            operation=operation,
            accepted=False,
            successor=source,
            kind="reject",
        )
        with self.assertRaisesRegex(ReplayError, "rejection is admitted"):
            replay_events([*events, forged])

    def test_reason_spoof_is_hash_covered_but_not_semantically_checked(self) -> None:
        with self.controller("reason-boundary", capacity=1) as controller:
            events = controller.events()
            source = controller.snapshot()["state"]
        rejected = {
            "op": "prepare",
            "plan_version": 99,
            "assignments": {"e": "c"},
        }
        self.assertFalse(reference_transition(source, rejected).accepted)
        forged = forge_event(
            events[-1],
            operation=rejected,
            accepted=False,
            successor=source,
            kind="reject",
            reason="spoofed category that the oracle does not recompute",
        )
        result = replay_events([*events, forged])
        self.assertEqual(source, result.state)

        tampered_without_rehash = deepcopy(forged)
        tampered_without_rehash["body"]["reason"] = "changed after commitment"
        with self.assertRaisesRegex(ReplayError, "body hash"):
            replay_events([*events, tampered_without_rehash])

    def test_reopen_rejects_incoherent_state_but_coherent_store_rewrite_needs_anchor(self) -> None:
        victim_path = self.root / "victim.sqlite3"
        replacement_path = self.root / "replacement.sqlite3"
        with PlanPilotController(
            victim_path,
            grants={"g": 1},
            ordered_slots=["s"],
            claims=self.one_claim(),
            plan_id="victim",
        ) as victim:
            old_anchor = victim.snapshot()["head_hash"]

        with PlanPilotController(
            replacement_path,
            grants={"g": 1},
            ordered_slots=["s"],
            claims=[
                {
                    "claim": "replacement",
                    "grant": "g",
                    "demand": 1,
                    "owner": "replacement-owner",
                    "slot": "s",
                }
            ],
            plan_id="replacement",
        ) as replacement:
            replacement_anchor = replacement.snapshot()["head_hash"]
        self.assertNotEqual(old_anchor, replacement_anchor)

        # A hostile process with complete SQLite write authority can substitute
        # a fully coherent database, including its in-database head.  This is
        # deliberately inside the stated trusted-store TCB.
        with sqlite3.connect(replacement_path) as source, sqlite3.connect(
            victim_path
        ) as target:
            source.backup(target)

        with PlanPilotController(victim_path) as unanchored:
            self.assertEqual(replacement_anchor, unanchored.snapshot()["head_hash"])
            self.assertIn("replacement", unanchored.snapshot()["state"]["claims"])
        with self.assertRaisesRegex(PlanPilotError, "durable head hash mismatch"):
            PlanPilotController(victim_path, expected_head_hash=old_anchor)

        # A torn materialized state rewrite is detected even without an
        # external anchor because it disagrees with the replayed event chain.
        with sqlite3.connect(victim_path) as database:
            row = database.execute(
                "SELECT state_json FROM controller_meta WHERE singleton=1"
            ).fetchone()
            state = json.loads(row[0])
            state["global_version"] += 7
            database.execute(
                "UPDATE controller_meta SET state_json=? WHERE singleton=1",
                (canonical_json(state),),
            )
        with self.assertRaisesRegex(PlanPilotError, "durable history verification"):
            PlanPilotController(victim_path)

    def test_transition_oracle_is_separate_and_covers_admission_dependencies(self) -> None:
        replay_source = (REPOSITORY / "adapter/plan_replay.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(replay_source)
        imports: set[str] = set()
        functions: dict[str, ast.FunctionDef] = {}
        for node in tree.body:
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add((node.module or "").split(".")[0])
            elif isinstance(node, ast.FunctionDef):
                functions[node.name] = node
        self.assertNotIn("adapter", imports)

        semantic_calls = {
            call.func.id
            for call in ast.walk(functions["semantic_transport_safe"])
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
        }
        self.assertFalse(
            semantic_calls
            & {"reference_transition", "transition_oracle_safe", "exact_transport_safe"}
        )
        oracle_calls = {
            call.func.id
            for call in ast.walk(functions["transition_oracle_safe"])
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
        }
        self.assertIn("reference_transition", oracle_calls)

        with self.controller(
            "oracle", claims=self.same_root_claims(), capacity=2
        ) as controller:
            state = controller.snapshot()["state"]
        valid = {
            "op": "merge",
            "plan_version": 0,
            "source_owners": ["oa", "ob"],
            "target_owner": "joined",
        }
        self.assertTrue(semantic_transport_safe(state, valid))
        self.assertTrue(transition_oracle_safe(state, valid))
        negatives = [
            {**valid, "target_owner": "oa"},
            {**valid, "plan_version": 1},
            {**valid, "source_owners": ["oa", "closed-or-unknown"]},
            {**valid, "target_valid": True},
            {key: value for key, value in valid.items() if key != "target_owner"},
        ]
        for operation in negatives:
            self.assertFalse(transition_oracle_safe(state, operation), operation)
        records = controlled_decisions()
        self.assertEqual(7, len(records))
        self.assertTrue(
            all(
                record["semantic_transport"] == record["transition_oracle"]
                for record in records
            )
        )

    def test_candidate_invalidity_is_reject_but_source_corruption_is_hard_error(self) -> None:
        with self.controller(
            "candidate",
            claims=self.same_root_claims(mixed_batch=True),
            capacity=2,
        ) as controller:
            before = controller.snapshot()
            operation = {
                "op": "refine",
                "plan_version": 0,
                "source_claim": "a",
                "children": [{"claim": "child", "owner": "ob", "demand": 1}],
            }
            decision = controller.apply(operation)
            self.assertFalse(decision.accepted)
            self.assertIn("computed successor invalid", decision.reason)
            self.assertEqual(before["state"], controller.snapshot()["state"])
            self.assertEqual("reject", controller.events()[-1]["kind"])
            replay_events(controller.events())

            before_event_count = len(controller.events())
            with sqlite3.connect(controller.path) as database:
                raw = database.execute(
                    "SELECT state_json FROM controller_meta WHERE singleton=1"
                ).fetchone()[0]
                corrupted = json.loads(raw)
                corrupted["plan"]["current_slot"] = None
                database.execute(
                    "UPDATE controller_meta SET state_json=? WHERE singleton=1",
                    (canonical_json(corrupted),),
                )
            with self.assertRaisesRegex(PlanPilotError, "current_slot"):
                controller.apply({"op": "crash"})
            self.assertEqual(before_event_count, len(controller.events()))

    def test_two_writer_prepare_and_injected_crash_have_only_serial_heads(self) -> None:
        path = self.root / "writers.sqlite3"
        PlanPilotController(
            path,
            grants={"g": 1},
            ordered_slots=["s"],
            claims=self.one_claim(),
        ).close()
        barrier = threading.Barrier(2)

        def attempt(effect: str) -> tuple[bool, str]:
            with PlanPilotController(path) as controller:
                barrier.wait(timeout=10)
                decision = controller.apply(
                    {
                        "op": "prepare",
                        "plan_version": 0,
                        "assignments": {effect: "c"},
                    }
                )
                return decision.accepted, decision.reason

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, ("e1", "e2")))
        self.assertEqual(1, sum(accepted for accepted, _ in results))
        self.assertEqual(1, sum(reason == "stale plan version" for _, reason in results))
        with PlanPilotController(path) as reopened:
            self.assertEqual(1, len(reopened.snapshot()["state"]["tickets"]))
            replay_events(reopened.events())

        crash_path = self.root / "crash.sqlite3"
        controller = PlanPilotController(
            crash_path,
            grants={"g": 1},
            ordered_slots=["s"],
            claims=self.one_claim(),
        )
        operation = {
            "op": "prepare",
            "plan_version": 0,
            "assignments": {"e": "c"},
        }
        with self.assertRaisesRegex(InjectedCrash, "before SQLite commit"):
            controller.apply(operation, crash_at="before_commit")
        self.assertEqual(0, controller.snapshot()["state"]["plan"]["version"])
        self.assertEqual(1, controller.snapshot()["sequence"])
        with self.assertRaisesRegex(InjectedCrash, "after SQLite commit"):
            controller.apply(operation, crash_at="after_commit")
        controller.close()
        with PlanPilotController(crash_path) as reopened:
            self.assertEqual(1, reopened.snapshot()["state"]["plan"]["version"])
            self.assertEqual(2, reopened.snapshot()["sequence"])
            replay_events(reopened.events())

    def test_zero_demand_actual_transition_retry_and_settlement(self) -> None:
        with self.controller(
            "zero-demand", claims=self.one_claim(demand=0), capacity=1
        ) as controller:
            duplicated = controller.apply(
                {
                    "op": "refine",
                    "plan_version": 0,
                    "source_claim": "c",
                    "children": [
                        {"claim": "left", "owner": "o", "demand": 0},
                        {"claim": "right", "owner": "o", "demand": 0},
                    ],
                }
            )
            self.assertFalse(duplicated.accepted)
            self.assertIn("duplicates one origin token", duplicated.reason)
            identity = controller.apply(
                {
                    "op": "refine",
                    "plan_version": 0,
                    "source_claim": "c",
                    "children": [{"claim": "replacement", "owner": "o", "demand": 0}],
                }
            )
            self.assertTrue(identity.accepted)
            self.assertTrue(
                controller.apply(
                    {
                        "op": "prepare",
                        "plan_version": 1,
                        "assignments": {"e": "replacement"},
                    }
                ).accepted
            )
            self.assertTrue(controller.apply({"op": "dispatch", "effect": "e"}).accepted)
            self.assertTrue(
                controller.apply({"op": "crash", "effects": ["e"]}).accepted
            )
            self.assertEqual(
                "uncertain", controller.snapshot()["state"]["tickets"]["e"]["phase"]
            )
            self.assertTrue(controller.apply({"op": "retry", "effect": "e"}).accepted)
            self.assertTrue(
                controller.apply(
                    {"op": "settle", "effect": "e", "outcome": "succeeded"}
                ).accepted
            )
            self.assertNotIn("e", controller.snapshot()["state"]["tickets"])
            self.assertEqual(
                "succeeded",
                controller.snapshot()["state"]["receipts"]["e"]["outcome"],
            )
            replay_events(controller.events())

    def test_real_codex_callback_dispatches_before_response_and_settles_after(self) -> None:
        self.assertIsNotNone(shutil.which("codex"), "real codex binary is required")
        from adapter.test_app_server import run_preflight

        raw_path = self.root / "codex-callback.jsonl"
        with self.controller("real-callback", capacity=1) as controller:
            self.assertTrue(
                controller.apply(
                    {
                        "op": "prepare",
                        "plan_version": 0,
                        "assignments": {"preflight-effect-1": "c"},
                    }
                ).accepted
            )
            observed: list[str] = []

            def handler(pending: object) -> None:
                effect = str(getattr(pending, "arguments")["effect_id"])
                self.assertEqual(
                    "prepared", controller.snapshot()["state"]["tickets"][effect]["phase"]
                )

                def callback(binding: dict[str, str]) -> dict:
                    self.assertEqual({"effect": effect, "claim": "c"}, binding)
                    self.assertEqual(
                        "inflight",
                        controller.snapshot()["state"]["tickets"][effect]["phase"],
                    )
                    observed.append("dispatch-before-response")
                    getattr(pending, "respond_text")(f"receipt:{effect}")
                    observed.append("response-before-settle")
                    return {"outcome": "succeeded"}

                result = service_protected_callback(
                    controller, effect=effect, callback=callback
                )
                self.assertEqual("completed", result["status"])
                self.assertNotIn(effect, controller.snapshot()["state"]["tickets"])
                self.assertIn(effect, controller.snapshot()["state"]["receipts"])
                observed.append("settled")

            preflight = run_preflight(
                workspace=self.root,
                raw_jsonl_path=raw_path,
                tool_handler=handler,
            )
            self.assertTrue(preflight.ok)
            self.assertEqual(
                ["dispatch-before-response", "response-before-settle", "settled"],
                observed,
            )
            replay_events(controller.events())
        raw = raw_path.read_text(encoding="utf-8")
        self.assertIn('"method":"item/tool/call"', raw.replace(" ", ""))

    def test_count_only_aggregate_is_deterministic_and_arithmetically_complete(self) -> None:
        first_records = controlled_decisions()
        second_records = controlled_decisions()
        first = aggregate_json(first_records)
        second = aggregate_json(second_records)
        retained = (RECORD / "aggregate.json").read_text(encoding="utf-8").strip()
        self.assertEqual(first, second)
        self.assertEqual(retained, first)
        parsed = json.loads(first)
        self.assertEqual(
            {"schema", "cases", "baselines", "oracle_safe_semantic_reuse_cases"},
            set(parsed),
        )
        self.assertEqual(
            {"global_version", "per_object", "semantic_transport"},
            set(parsed["baselines"]),
        )
        confusion_keys = {
            "safe_reuse",
            "safe_replan",
            "unsafe_reuse",
            "false_invalidation",
        }
        for counts in parsed["baselines"].values():
            self.assertEqual(confusion_keys, set(counts))
            self.assertEqual(parsed["cases"], sum(counts.values()))
            self.assertTrue(all(type(value) is int and value >= 0 for value in counts.values()))
        for forbidden in (
            "outside-owner",
            "same-root-join",
            "cross-root-join",
            "source_owners",
            "successor_state",
            "plan_version",
            str(REPOSITORY),
        ):
            self.assertNotIn(forbidden, first)


if __name__ == "__main__":
    unittest.main()
