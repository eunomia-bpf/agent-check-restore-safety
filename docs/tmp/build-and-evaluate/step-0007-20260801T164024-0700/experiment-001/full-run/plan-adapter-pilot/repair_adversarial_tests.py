"""Adversarial checks added after the independent pilot review.

This file intentionally lives with the retained experiment record rather than
the controller.  It forges self-consistent hashes and manipulates SQLite
directly so that the checks do not merely exercise the public happy path.
"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

_REPOSITORY = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (parent / "adapter" / "plan_pilot.py").is_file()
)
sys.path.insert(0, str(_REPOSITORY))

from adapter.plan_pilot import (
    PlanPilotController,
    PlanPilotError,
    canonical_json,
)
from adapter.plan_replay import (
    ReplayError,
    digest,
    reference_transition,
    replay_events,
    semantic_transport_safe,
    transition_oracle_safe,
)


def forge(
    previous: dict,
    *,
    kind: str,
    operation: dict,
    accepted: bool,
    successor: dict,
) -> dict:
    body = {
        "operation": operation,
        "accepted": accepted,
        "reason": "adversarial fixture",
        "successor_state": successor,
    }
    envelope = {
        "seq": int(previous["seq"]) + 1,
        "previous_hash": previous["event_hash"],
        "state_hash": digest(successor),
        "kind": kind,
        "body_hash": digest(body),
    }
    return {**envelope, "event_hash": digest(envelope), "body": body}


class RepairAdversarialTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def claims(*, mixed_batch: bool = False) -> list[dict]:
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

    def controller(self, name: str, *, mixed_batch: bool = False) -> PlanPilotController:
        return PlanPilotController(
            self.root / f"{name}.sqlite3",
            grants={"g": 2},
            ordered_slots=["s"],
            claims=self.claims(mixed_batch=mixed_batch),
            plan_id=name,
        )

    def test_hash_consistent_forged_successor_is_rejected(self) -> None:
        with self.controller("forged-successor") as controller:
            genesis = controller.events()[0]
        source = deepcopy(genesis["body"]["successor_state"])
        forged_state = deepcopy(source)
        forged_state["global_version"] += 1
        forged_state["grant_epochs"]["g"] = "closed"
        event = forge(
            genesis,
            kind="crash",
            operation={"op": "crash"},
            accepted=True,
            successor=forged_state,
        )
        with self.assertRaisesRegex(ReplayError, "full-state recomputation"):
            replay_events([genesis, event])

    def test_arbitrary_stutter_reject_is_rejected(self) -> None:
        with self.controller("forged-reject") as controller:
            genesis = controller.events()[0]
        source = deepcopy(genesis["body"]["successor_state"])
        operation = {
            "op": "merge",
            "plan_version": 0,
            "source_owners": ["oa", "ob"],
            "target_owner": "joined",
        }
        self.assertTrue(reference_transition(source, operation).accepted)
        event = forge(
            genesis,
            kind="reject",
            operation=operation,
            accepted=False,
            successor=source,
        )
        with self.assertRaisesRegex(ReplayError, "rejection is admitted"):
            replay_events([genesis, event])

    def test_target_freshness_source_epoch_and_field_injection_are_in_oracle(self) -> None:
        with self.controller("oracle-fields") as controller:
            state = controller.snapshot()["state"]
        valid = {
            "op": "merge",
            "plan_version": 0,
            "source_owners": ["oa", "ob"],
            "target_owner": "joined",
        }
        self.assertTrue(semantic_transport_safe(state, valid))
        self.assertTrue(transition_oracle_safe(state, valid))
        for invalid in (
            {**valid, "target_owner": "oa"},
            {**valid, "source_owners": ["oa", "unknown"]},
            {**valid, "target_valid": True},
            {key: value for key, value in valid.items() if key != "target_owner"},
        ):
            self.assertFalse(semantic_transport_safe(state, invalid))
            self.assertFalse(transition_oracle_safe(state, invalid))

    def test_candidate_invariant_failure_is_logged_as_reject(self) -> None:
        with self.controller("candidate", mixed_batch=True) as controller:
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
            self.assertEqual(before["state_hash"], decision.state_hash)
            self.assertEqual("reject", controller.events()[-1]["kind"])
            replay_events(
                controller.events(),
                expected_head_hash=controller.snapshot()["head_hash"],
                expected_state_hash=before["state_hash"],
            )

    def test_reopen_replays_store_and_external_anchor_is_effective(self) -> None:
        path = self.root / "anchor.sqlite3"
        with self.controller("anchor-source") as source:
            # Move the generated DB to the explicit path without shell/file
            # mutation tricks by using SQLite's own backup API.
            with sqlite3.connect(path) as target:
                source._db.backup(target)  # experiment-only white-box probe
        with PlanPilotController(path) as controller:
            old_anchor = controller.snapshot()["head_hash"]
            controller.apply({"op": "restrict", "plan_version": 0, "keep_owners": ["oa"]})
            new_anchor = controller.snapshot()["head_hash"]
        with PlanPilotController(path, expected_head_hash=new_anchor):
            pass
        with self.assertRaisesRegex(PlanPilotError, "durable head hash mismatch"):
            PlanPilotController(path, expected_head_hash=old_anchor)

        with sqlite3.connect(path) as database:
            raw = database.execute(
                "SELECT state_json FROM controller_meta WHERE singleton=1"
            ).fetchone()[0]
            state = json.loads(raw)
            state["global_version"] += 7
            database.execute(
                "UPDATE controller_meta SET state_json=? WHERE singleton=1",
                (canonical_json(state),),
            )
        with self.assertRaises(PlanPilotError):
            PlanPilotController(path)


if __name__ == "__main__":
    unittest.main()
