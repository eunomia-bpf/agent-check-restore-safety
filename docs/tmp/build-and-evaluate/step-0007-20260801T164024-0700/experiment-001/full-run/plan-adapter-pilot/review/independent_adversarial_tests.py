from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from adapter.plan_pilot import (
    PlanPilotController,
    PlanPilotError,
    canonical_json,
    digest as controller_digest,
)
from adapter.plan_pilot_runner import controlled_decisions
from adapter.plan_replay import (
    ReplayError,
    digest as replay_digest,
    exact_transport_safe,
    replay_events,
    semantic_transport_safe,
)


def forged_event(
    previous_event: dict,
    *,
    kind: str,
    operation: dict,
    accepted: bool,
    successor: dict,
) -> dict:
    body = {
        "operation": operation,
        "accepted": accepted,
        "reason": "admitted" if accepted else "forged rejection",
        "successor_state": successor,
    }
    envelope = {
        "seq": int(previous_event["seq"]) + 1,
        "previous_hash": previous_event["event_hash"],
        "state_hash": replay_digest(successor),
        "kind": kind,
        "body_hash": replay_digest(body),
    }
    return {**envelope, "event_hash": replay_digest(envelope), "body": body}


class IndependentAdversarialReview(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def controller(self, name: str, claims: list[dict], capacity: int = 2) -> PlanPilotController:
        return PlanPilotController(
            self.root / f"{name}.sqlite3",
            grants={"g": capacity},
            ordered_slots=["s"],
            claims=claims,
            plan_id=name,
        )

    @staticmethod
    def one_claim() -> list[dict]:
        return [
            {
                "claim": "c",
                "grant": "g",
                "demand": 1,
                "owner": "o",
                "slot": "s",
            }
        ]

    def test_two_writers_prepare_has_exactly_one_cas_winner(self) -> None:
        path = self.root / "concurrent.sqlite3"
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
        with PlanPilotController(path) as controller:
            snapshot = controller.snapshot()
            self.assertEqual(1, snapshot["state"]["plan"]["version"])
            self.assertEqual(1, len(snapshot["state"]["tickets"]))
            replay_events(
                controller.events(),
                expected_head_hash=snapshot["head_hash"],
                expected_state_hash=snapshot["state_hash"],
            )

    def test_zero_demand_split_fails_on_real_transition_path(self) -> None:
        with self.controller(
            "zero",
            [
                {
                    "claim": "z",
                    "grant": "g",
                    "demand": 0,
                    "owner": "o",
                    "slot": "s",
                }
            ],
            capacity=1,
        ) as controller:
            before = controller.snapshot()
            decision = controller.apply(
                {
                    "op": "refine",
                    "plan_version": 0,
                    "source_claim": "z",
                    "children": [
                        {"claim": "zl", "owner": "o", "demand": 0},
                        {"claim": "zr", "owner": "o", "demand": 0},
                    ],
                }
            )
            after = controller.snapshot()
            self.assertFalse(decision.accepted)
            self.assertEqual("computed target duplicates one origin token", decision.reason)
            self.assertEqual(before["state"], after["state"])
            self.assertEqual(before["state_hash"], decision.state_hash)

    def test_replay_accepts_forged_crash_that_closes_grant(self) -> None:
        with self.controller("replay-crash", self.one_claim()) as controller:
            genesis = controller.events()[0]
        successor = deepcopy(genesis["body"]["successor_state"])
        successor["global_version"] += 1
        successor["grant_epochs"]["g"] = "closed"
        forged = forged_event(
            genesis,
            kind="crash",
            operation={"op": "crash"},
            accepted=True,
            successor=successor,
        )
        result = replay_events(
            [genesis, forged],
            expected_head_hash=forged["event_hash"],
            expected_state_hash=forged["state_hash"],
        )
        self.assertEqual("closed", result.state["grant_epochs"]["g"])

    def test_replay_does_not_recompute_rejected_decision(self) -> None:
        with self.controller("replay-reject", self.one_claim()) as controller:
            genesis = controller.events()[0]
        state = deepcopy(genesis["body"]["successor_state"])
        valid_prepare = {
            "op": "prepare",
            "plan_version": 0,
            "assignments": {"e": "c"},
        }
        forged = forged_event(
            genesis,
            kind="reject",
            operation=valid_prepare,
            accepted=False,
            successor=state,
        )
        result = replay_events([genesis, forged])
        self.assertEqual(state, result.state)

    def test_exact_baseline_omits_merge_target_freshness(self) -> None:
        claims = [
            {
                "claim": "a",
                "grant": "g",
                "demand": 1,
                "owner": "oa",
                "slot": "s",
                "batch_root": "r",
            },
            {
                "claim": "b",
                "grant": "g",
                "demand": 1,
                "owner": "ob",
                "slot": "s",
                "batch_root": "r",
            },
        ]
        with self.controller("target-fresh", claims) as controller:
            state = controller.snapshot()["state"]
            operation = {
                "op": "merge",
                "plan_version": 0,
                "source_owners": ["oa", "ob"],
                "target_owner": "oa",
            }
            self.assertTrue(semantic_transport_safe(state, operation))
            self.assertTrue(exact_transport_safe(state, operation))
            decision = controller.apply(operation)
            self.assertFalse(decision.accepted)
            self.assertEqual("invalid merge owners", decision.reason)

    def test_refine_batch_alias_rolls_back_but_is_not_reject_event(self) -> None:
        claims = [
            {
                "claim": "source",
                "grant": "g",
                "demand": 1,
                "owner": "oa",
                "slot": "s",
                "batch_root": "ra",
            },
            {
                "claim": "peer",
                "grant": "g",
                "demand": 1,
                "owner": "ob",
                "slot": "s",
                "batch_root": "rb",
            },
        ]
        with self.controller("batch-alias", claims) as controller:
            before = controller.snapshot()
            with self.assertRaisesRegex(PlanPilotError, "mixes immutable roots"):
                controller.apply(
                    {
                        "op": "refine",
                        "plan_version": 0,
                        "source_claim": "source",
                        "children": [
                            {"claim": "child", "owner": "ob", "demand": 1}
                        ],
                    }
                )
            after = controller.snapshot()
            self.assertEqual(before, after)
            self.assertEqual(1, len(controller.events()))

    def test_reopen_accepts_valid_but_unaudited_token_rewrite(self) -> None:
        path = self.root / "rewrite.sqlite3"
        controller = PlanPilotController(
            path,
            grants={"g": 1},
            ordered_slots=["s"],
            claims=self.one_claim(),
        )
        controller.close()
        with sqlite3.connect(path) as database:
            raw = database.execute(
                "SELECT state_json FROM controller_meta WHERE singleton=1"
            ).fetchone()[0]
            state = json.loads(raw)
            state["token_ledger"] = {
                "initial": ["forged-token"],
                "origin": {"c": "forged-token"},
                "disposition": {"forged-token": "remaining"},
            }
            database.execute(
                "UPDATE controller_meta SET state_json=? WHERE singleton=1",
                (canonical_json(state),),
            )
        with PlanPilotController(path) as reopened:
            snapshot = reopened.snapshot()
            self.assertEqual("forged-token", snapshot["state"]["token_ledger"]["origin"]["c"])
            with self.assertRaisesRegex(ReplayError, "durable state hash mismatch"):
                replay_events(
                    reopened.events(),
                    expected_head_hash=snapshot["head_hash"],
                    expected_state_hash=controller_digest(snapshot["state"]),
                )

    def test_public_exact_control_is_identical_to_semantic_decision(self) -> None:
        decisions = controlled_decisions()
        self.assertTrue(decisions)
        self.assertTrue(
            all(
                record["semantic_transport"] == record["exact_re_solve"]
                for record in decisions
            )
        )


if __name__ == "__main__":
    unittest.main()
