from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from adapter.controller import DurableController
from adapter.oracle import load_oracle
from adapter.replay import ATTEMPT, TAU, replay_bundle
from adapter.spec import LitmusCase, load_litmus


ROOT = Path(__file__).resolve().parents[1]


def grants_for(case: LitmusCase) -> dict[str, int]:
    return {
        str(operation["grant"]): int(operation["capacity"])
        for operation in case.operations
        if operation["op"] == "grant"
    }


def execute_p3_case(case: LitmusCase, database: Path) -> tuple[dict[str, str], dict, list[dict]]:
    """Execute the declarative stream plus its controller-side crash edges.

    The helper deliberately receives no oracle.  A remote success is represented
    only by the subsequent settlement; sink behavior belongs to worker tests.
    """

    decisions: dict[str, str] = {}
    with DurableController(database, "P3", grants_for(case)) as controller:
        for operation in case.operations:
            if operation["op"] == "grant":
                continue

            if operation["op"] == "dispatch" and case.crash_mode == "before_dispatch":
                crash = controller.apply({"op": "crash", "effects": []})
                if not crash.accepted:
                    raise AssertionError("the before-dispatch crash edge must stutter")

            decision = controller.apply(operation)
            if decision.request is not None:
                decisions[decision.request] = "accept" if decision.accepted else "reject"

            if operation["op"] != "dispatch" or not decision.accepted:
                continue

            effect = str(operation["effect"])
            if case.crash_mode == "after_remote_success":
                recovered = controller.recover_after_crash(effect)
                if not recovered.accepted:
                    raise AssertionError("an inflight ticket must admit its crash edge")

            settled = controller.apply(
                {"op": "settle", "effect": effect, "outcome": "succeeded"}
            )
            if not settled.accepted:
                raise AssertionError("a dispatched ticket must admit settlement")

            if case.crash_mode == "after_controller_commit":
                cached_retry = controller.apply({"op": "retry", "effect": effect})
                if cached_retry.accepted:
                    raise AssertionError("a settled effect must not be attempted again")

        return decisions, controller.snapshot(), controller.events()


class FixedP3ControllerTests(unittest.TestCase):
    def test_all_twenty_frozen_cases_match_oracle_and_independently_replay(self) -> None:
        cases = load_litmus(ROOT / "adapter" / "litmus.yaml")
        oracle = load_oracle(ROOT / "adapter" / "oracle.yaml")

        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for case in cases:
                with self.subTest(case=case.case_id):
                    decisions, snapshot, events = execute_p3_case(
                        case, directory / f"{case.case_id}.sqlite3"
                    )
                    expected = oracle[case.case_id].decisions
                    self.assertEqual(expected, {key: decisions.get(key) for key in expected})

                    result = replay_bundle(
                        {
                            "events": events,
                            "head_hash": snapshot["head_hash"],
                            "state_hash": snapshot["state_hash"],
                        }
                    )
                    self.assertEqual(snapshot["state"], result.state.semantic_dict())
                    self.assertEqual(snapshot["sequence"], result.state.sequence)

                    attempts = [label for label in result.labels if label.kind == ATTEMPT]
                    self.assertEqual(1 if case.dispatch_site is not None else 0, len(attempts))
                    self.assertEqual(TAU, result.labels[0].kind)

    def test_oracle_rejections_are_hash_preserving_stutters(self) -> None:
        cases = load_litmus(ROOT / "adapter" / "litmus.yaml")
        unsafe_requests = {
            request
            for case in load_oracle(ROOT / "adapter" / "oracle.yaml").values()
            for request in case.unsafe_if_accepted
        }

        with TemporaryDirectory() as temporary:
            for case in cases:
                _, _, events = execute_p3_case(
                    case, Path(temporary) / f"stutter-{case.case_id}.sqlite3"
                )
                for index, event in enumerate(events):
                    if event["kind"] != "reject":
                        continue
                    action = event["body"]["operation"]["action"]
                    if action.get("request") not in unsafe_requests:
                        continue
                    self.assertGreater(index, 0)
                    self.assertEqual(events[index - 1]["state_hash"], event["state_hash"])


class ControllerReplayContractTests(unittest.TestCase):
    def test_prepare_retires_newly_insolvent_choice_branch(self) -> None:
        with TemporaryDirectory() as temporary:
            database = Path(temporary) / "controller.sqlite3"
            with DurableController(database, "P3", {"g": 1}) as controller:
                operations = (
                    {"op": "fork", "source": "root", "kind": "choice", "children": ["left", "right"]},
                    {"op": "reserve", "claim": "c1", "branch": "left", "grant": "g", "demand": 1},
                    {"op": "reserve", "claim": "c2", "branch": "right", "grant": "g", "demand": 1},
                    {"op": "prepare", "effect": "e1", "claim": "c1"},
                )
                self.assertTrue(all(controller.apply(operation).accepted for operation in operations))
                snapshot, events = controller.snapshot(), controller.events()

            result = replay_bundle(
                {
                    "events": events,
                    "head_hash": snapshot["head_hash"],
                    "state_hash": snapshot["state_hash"],
                }
            )
            self.assertEqual(snapshot["state"], result.state.semantic_dict())
            self.assertEqual(["left"], snapshot["state"]["active_branches"])
            self.assertEqual("closed", snapshot["state"]["branch_epochs"]["right"])
            self.assertEqual("terminal", snapshot["state"]["claims"]["c2"]["status"])
            self.assertNotIn("right", snapshot["state"]["delegations"]["g"])

    def test_rejected_malformed_deltas_remain_replayable_stutters(self) -> None:
        with TemporaryDirectory() as temporary:
            database = Path(temporary) / "controller.sqlite3"
            with DurableController(database, "P3", {"g": 1}) as controller:
                rejected = [
                    controller.apply(
                        {"op": "reserve", "claim": "bad", "branch": "root", "grant": "g", "demand": 0}
                    ),
                    controller.apply(
                        {"op": "fork", "source": "root", "kind": "parallel", "children": ["left", "left"]}
                    ),
                ]
                self.assertTrue(
                    controller.apply(
                        {"op": "fork", "source": "root", "kind": "parallel", "children": ["left", "right"]}
                    ).accepted
                )
                self.assertTrue(
                    controller.apply(
                        {"op": "reserve", "claim": "c1", "branch": "left", "grant": "g", "demand": 1}
                    ).accepted
                )
                rejected.append(
                    controller.apply({"op": "delegate", "grant": "g", "branch": "right"})
                )
                self.assertTrue(
                    controller.apply({"op": "prepare", "effect": "e1", "claim": "c1"}).accepted
                )
                self.assertTrue(controller.apply({"op": "dispatch", "effect": "e1"}).accepted)
                rejected.append(
                    controller.apply({"op": "crash", "effects": ["not-inflight"]})
                )
                self.assertTrue(controller.apply({"op": "crash", "effects": ["e1"]}).accepted)
                rejected.append(
                    controller.apply({"op": "settle", "effect": "e1", "outcome": "invented"})
                )
                self.assertTrue(
                    controller.apply({"op": "settle", "effect": "e1", "outcome": "succeeded"}).accepted
                )
                snapshot, events = controller.snapshot(), controller.events()

            self.assertTrue(all(not decision.accepted for decision in rejected))
            result = replay_bundle(
                {
                    "events": events,
                    "head_hash": snapshot["head_hash"],
                    "state_hash": snapshot["state_hash"],
                }
            )
            self.assertEqual(snapshot["state"], result.state.semantic_dict())
            for index, event in enumerate(events):
                if event["kind"] == "reject":
                    self.assertEqual(events[index - 1]["state_hash"], event["state_hash"])

    def test_reopen_preserves_chain_and_allows_crash_recovery(self) -> None:
        with TemporaryDirectory() as temporary:
            database = Path(temporary) / "controller.sqlite3"
            with DurableController(database, "P3", {"g": 1}) as controller:
                for operation in (
                    {"op": "reserve", "claim": "c1", "branch": "root", "grant": "g", "demand": 1},
                    {"op": "prepare", "effect": "e1", "claim": "c1"},
                    {"op": "dispatch", "effect": "e1"},
                ):
                    self.assertTrue(controller.apply(operation).accepted)
                old_head = controller.snapshot()["head_hash"]

            with DurableController(database, "P3") as controller:
                self.assertEqual(old_head, controller.events()[-1]["event_hash"])
                self.assertTrue(controller.recover_after_crash("e1").accepted)
                self.assertTrue(
                    controller.apply({"op": "settle", "effect": "e1", "outcome": "succeeded"}).accepted
                )
                snapshot, events = controller.snapshot(), controller.events()

            result = replay_bundle(
                {
                    "events": events,
                    "head_hash": snapshot["head_hash"],
                    "state_hash": snapshot["state_hash"],
                }
            )
            self.assertEqual("succeeded", result.state.receipts["e1"].outcome)


if __name__ == "__main__":
    unittest.main()
