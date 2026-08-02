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
    InjectedCrash,
    PlanPilotError,
    PlanPilotController,
    canonical_json,
    initial_state,
    service_protected_callback,
    validate_state,
)
from adapter.plan_replay import (
    ReplayError,
    aggregate_json,
    decision_baselines,
    digest as replay_digest,
    exact_serial_orders,
    reference_transition,
    replay_events,
    transition_oracle_safe,
    validate_semantic_state,
)
from adapter.sink import AuthenticatedSink, verify_evidence


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
        "reason": "forged",
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


class PlanPilotTests(unittest.TestCase):
    secret = b"plan-pilot-test-secret"

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def controller(
        self,
        name: str,
        *,
        grants: dict[str, int],
        slots: list[str],
        claims: list[dict],
    ) -> PlanPilotController:
        return PlanPilotController(
            self.root / f"{name}.sqlite3",
            grants=grants,
            ordered_slots=slots,
            claims=claims,
            plan_id=name,
        )

    @staticmethod
    def two_slot_claims() -> list[dict]:
        return [
            {"claim": "c1", "grant": "g", "demand": 1, "owner": "o1", "slot": "s1"},
            {"claim": "c2", "grant": "g", "demand": 1, "owner": "o2", "slot": "s2"},
        ]

    def assert_replays(self, controller: PlanPilotController) -> None:
        snapshot = controller.snapshot()
        result = replay_events(
            controller.events(),
            expected_head_hash=snapshot["head_hash"],
            expected_state_hash=snapshot["state_hash"],
        )
        self.assertEqual(snapshot["state"], result.state)
        self.assertEqual(snapshot["sequence"], result.sequence)

    def test_stale_copied_plan_head_and_caller_target_are_rejected_stutters(self) -> None:
        with self.controller(
            "stale", grants={"g": 2}, slots=["s1", "s2"], claims=self.two_slot_claims()
        ) as controller:
            copied_version = controller.snapshot()["state"]["plan"]["version"]
            first = controller.apply(
                {"op": "prepare", "plan_version": copied_version, "assignments": {"e1": "c1"}}
            )
            self.assertTrue(first.accepted)
            before = controller.snapshot()
            stale = controller.apply(
                {"op": "prepare", "plan_version": copied_version, "assignments": {"e2": "c2"}}
            )
            target_injection = controller.apply(
                {
                    "op": "prepare",
                    "plan_version": 1,
                    "assignments": {"e2": "c2"},
                    "W": {"s2": {"g": 0}},
                }
            )
            nested_target_injection = controller.apply(
                {
                    "op": "prepare",
                    "plan_version": 1,
                    "assignments": {"e2": "c2"},
                    "request": {"target_valid": True},
                }
            )
            token_origin_injection = controller.apply(
                {
                    "op": "prepare",
                    "plan_version": 1,
                    "assignments": {"e2": "c2"},
                    "origin": {"c2": "caller-token"},
                }
            )
            after = controller.snapshot()
            self.assertFalse(stale.accepted)
            self.assertEqual("stale plan version", stale.reason)
            self.assertFalse(target_injection.accepted)
            self.assertIn("caller-supplied target", target_injection.reason)
            self.assertFalse(nested_target_injection.accepted)
            self.assertIn("caller-supplied target", nested_target_injection.reason)
            self.assertFalse(token_origin_injection.accepted)
            self.assertIn("caller-supplied target", token_origin_injection.reason)
            self.assertEqual(before["state_hash"], stale.state_hash)
            self.assertEqual(before["state"], after["state"])
            self.assertNotIn("e2", after["state"]["tickets"])
            reject_events = [event for event in controller.events() if event["kind"] == "reject"]
            self.assertEqual(4, len(reject_events))
            self.assertTrue(all(event["state_hash"] == before["state_hash"] for event in reject_events))
            self.assert_replays(controller)

    def test_disjoint_mutation_reuses_semantic_plan_but_global_version_replans(self) -> None:
        with self.controller(
            "disjoint", grants={"g": 3}, slots=["s1", "s2"], claims=self.two_slot_claims()
        ) as controller:
            before = controller.snapshot()["state"]
            aliased_owner = {
                "op": "disjoint_mutation",
                "claim": "aliased",
                "grant": "g",
                "demand": 1,
                "owner": "o1",
            }
            aliased_decisions = decision_baselines(before, aliased_owner)
            self.assertTrue(aliased_decisions["per_object"])
            self.assertFalse(aliased_decisions["semantic_transport"])
            self.assertFalse(aliased_decisions["transition_oracle"])
            self.assertFalse(controller.apply(aliased_owner).accepted)
            self.assertEqual(before, controller.snapshot()["state"])
            forged = json.loads(json.dumps(before))
            forged["claims"]["aliased"] = {
                "grant": "g",
                "demand": 1,
                "status": "tentative",
                "owner": "o1",
                "revision": 0,
            }
            with self.assertRaisesRegex(PlanPilotError, "mixes optional plan roots"):
                validate_state(forged)
            with self.assertRaisesRegex(ReplayError, "mixes optional plan roots"):
                validate_semantic_state(forged)

            operation = {
                "op": "disjoint_mutation",
                "claim": "outside",
                "grant": "g",
                "demand": 1,
                "owner": "outside-owner",
            }
            decisions = decision_baselines(before, operation)
            self.assertEqual(
                {
                    "global_version": False,
                    "per_object": True,
                    "semantic_transport": True,
                    "transition_oracle": True,
                },
                decisions,
            )
            result = controller.apply(operation)
            after = controller.snapshot()["state"]
            self.assertTrue(result.accepted)
            self.assertEqual(before["plan"], after["plan"])
            self.assertEqual(before["global_version"] + 1, after["global_version"])
            self.assertNotIn("outside", after["plan"]["disposition"])
            self.assertEqual("open", after["branch_epochs"]["outside-owner"])
            self.assert_replays(controller)

    def test_same_slot_token_preserving_refinement_and_coarsening_are_computed(self) -> None:
        claims = [
            {
                "claim": "source",
                "grant": "g",
                "demand": 2,
                "owner": "o1",
                "slot": "s1",
                "batch_root": "root-batch",
            },
            {
                "claim": "peer",
                "grant": "g",
                "demand": 1,
                "owner": "o2",
                "slot": "s1",
                "batch_root": "root-batch",
            },
        ]
        with self.controller("refine", grants={"g": 3}, slots=["s1"], claims=claims) as controller:
            duplicated_origin = {
                "op": "refine",
                "plan_version": 0,
                "source_claim": "source",
                "children": [
                    {"claim": "left", "owner": "o1", "demand": 1},
                    {"claim": "right", "owner": "o2", "demand": 1},
                ],
            }
            duplicate_baseline = decision_baselines(
                controller.snapshot()["state"], duplicated_origin
            )
            self.assertFalse(duplicate_baseline["semantic_transport"])
            self.assertFalse(duplicate_baseline["transition_oracle"])
            duplicated = controller.apply(duplicated_origin)
            self.assertFalse(duplicated.accepted)
            self.assertEqual(
                "computed target duplicates one origin token", duplicated.reason
            )

            refinement = {
                "op": "refine",
                "plan_version": 0,
                "source_claim": "source",
                "children": [
                    {"claim": "replacement", "owner": "o1", "demand": 2},
                ],
            }
            baseline = decision_baselines(controller.snapshot()["state"], refinement)
            self.assertTrue(baseline["semantic_transport"])
            self.assertTrue(baseline["transition_oracle"])
            self.assertFalse(baseline["global_version"])
            self.assertFalse(baseline["per_object"])
            self.assertTrue(controller.apply(refinement).accepted)
            refined = controller.snapshot()["state"]
            child = "replacement"
            self.assertEqual("s1", refined["plan"]["root_slot"][child])
            self.assertEqual("root-batch", refined["plan"]["batch_root"][child])
            self.assertEqual("remaining", refined["plan"]["disposition"][child])
            self.assertEqual(
                refined["token_ledger"]["origin"]["source"],
                refined["token_ledger"]["origin"][child],
            )
            self.assertEqual("superseded", refined["plan"]["disposition"]["source"])
            self.assertEqual(0, refined["plan"]["W"]["s1"]["g"])

            coarsening = {
                "op": "merge",
                "plan_version": 1,
                "source_owners": ["o1", "o2"],
                "target_owner": "joined",
            }
            baseline = decision_baselines(refined, coarsening)
            self.assertTrue(all(baseline[name] for name in ("per_object", "semantic_transport", "transition_oracle")))
            self.assertTrue(controller.apply(coarsening).accepted)
            merged = controller.snapshot()["state"]
            self.assertEqual(
                {"joined"},
                {merged["claims"][claim]["owner"] for claim in merged["plan"]["remaining"]},
            )
            self.assertEqual(2, merged["plan"]["version"])
            self.assertTrue(exact_serial_orders(merged))
            self.assert_replays(controller)

    def test_zero_demand_one_token_fork_rejects_but_identity_remains_schedulable(self) -> None:
        with self.controller(
            "zero-token",
            grants={"g": 1},
            slots=["s1"],
            claims=[
                {
                    "claim": "zero",
                    "grant": "g",
                    "demand": 0,
                    "owner": "o1",
                    "slot": "s1",
                }
            ],
        ) as controller:
            source = controller.snapshot()["state"]
            token = source["token_ledger"]["origin"]["zero"]
            forged = json.loads(json.dumps(source))
            forged["claims"]["z-copy"] = {
                "grant": "g",
                "demand": 0,
                "status": "tentative",
                "owner": "o1",
                "revision": 0,
            }
            forged["plan"]["root_slot"]["z-copy"] = "s1"
            forged["plan"]["batch_root"]["z-copy"] = "zero"
            forged["plan"]["disposition"]["z-copy"] = "remaining"
            forged["plan"]["remaining"] = ["z-copy", "zero"]
            forged["token_ledger"]["origin"]["z-copy"] = token
            with self.assertRaisesRegex(PlanPilotError, "multiple current witnesses"):
                validate_state(forged)
            with self.assertRaisesRegex(ReplayError, "multiple current witnesses"):
                validate_semantic_state(forged)

            split = {
                "op": "refine",
                "plan_version": 0,
                "source_claim": "zero",
                "children": [
                    {"claim": "z-left", "owner": "o1", "demand": 0},
                    {"claim": "z-right", "owner": "o1", "demand": 0},
                ],
            }
            decisions = decision_baselines(source, split)
            self.assertFalse(decisions["semantic_transport"])
            self.assertFalse(decisions["transition_oracle"])
            rejected = controller.apply(split)
            self.assertFalse(rejected.accepted)
            self.assertEqual("computed target duplicates one origin token", rejected.reason)
            self.assertEqual(source, controller.snapshot()["state"])

            replacement = {
                "op": "refine",
                "plan_version": 0,
                "source_claim": "zero",
                "children": [{"claim": "z-next", "owner": "o1", "demand": 0}],
            }
            self.assertTrue(controller.apply(replacement).accepted)
            transported = controller.snapshot()["state"]
            self.assertEqual(token, transported["token_ledger"]["origin"]["z-next"])
            self.assertEqual("remaining", transported["token_ledger"]["disposition"][token])
            prepared = controller.apply(
                {"op": "prepare", "plan_version": 1, "assignments": {"e0": "z-next"}}
            )
            self.assertTrue(prepared.accepted)
            final = controller.snapshot()["state"]
            self.assertEqual("prepared", final["token_ledger"]["disposition"][token])
            self.assertEqual("prepared", final["tickets"]["e0"]["phase"])
            self.assert_replays(controller)

    def test_cross_slot_and_same_slot_mixed_root_merge_are_rejected(self) -> None:
        with self.controller(
            "cross", grants={"g": 2}, slots=["s1", "s2"], claims=self.two_slot_claims()
        ) as controller:
            operation = {
                "op": "merge",
                "plan_version": 0,
                "source_owners": ["o1", "o2"],
                "target_owner": "joined",
            }
            decisions = decision_baselines(controller.snapshot()["state"], operation)
            self.assertEqual(False, decisions["global_version"])
            self.assertEqual(True, decisions["per_object"])
            self.assertEqual(False, decisions["semantic_transport"])
            self.assertEqual(False, decisions["transition_oracle"])
            rejected = controller.apply(operation)
            self.assertFalse(rejected.accepted)
            self.assertEqual("mixed-root or cross-slot merge", rejected.reason)
            self.assertNotIn("joined", controller.snapshot()["state"]["branch_epochs"])
            self.assert_replays(controller)

        mixed_claims = [
            {"claim": "a", "grant": "g", "demand": 1, "owner": "oa", "slot": "s", "batch_root": "ra"},
            {"claim": "b", "grant": "g", "demand": 1, "owner": "ob", "slot": "s", "batch_root": "rb"},
        ]
        with self.controller("mixed", grants={"g": 2}, slots=["s"], claims=mixed_claims) as controller:
            rejected = controller.apply(
                {
                    "op": "merge",
                    "plan_version": 0,
                    "source_owners": ["oa", "ob"],
                    "target_owner": "joined",
                }
            )
            self.assertFalse(rejected.accepted)
            self.assertEqual("mixed-root or cross-slot merge", rejected.reason)

    def test_two_prepare_advances_one_group_at_a_time_and_empties_tail(self) -> None:
        with self.controller(
            "two-prepare", grants={"g": 2}, slots=["s1", "s2"], claims=self.two_slot_claims()
        ) as controller:
            first = controller.apply(
                {"op": "prepare", "plan_version": 0, "assignments": {"e1": "c1"}}
            )
            middle = controller.snapshot()["state"]
            second = controller.apply(
                {"op": "prepare", "plan_version": 1, "assignments": {"e2": "c2"}}
            )
            final = controller.snapshot()["state"]
            self.assertTrue(first.accepted and second.accepted)
            self.assertEqual("s2", middle["plan"]["current_slot"])
            self.assertEqual(["c2"], middle["plan"]["remaining"])
            self.assertEqual(1, middle["plan"]["E"]["s1"]["g"])
            self.assertEqual(2, final["plan"]["version"])
            self.assertIsNone(final["plan"]["current_slot"])
            self.assertEqual([], final["plan"]["remaining"])
            self.assertEqual(1, final["plan"]["E"]["s2"]["g"])
            self.assertEqual({"e1", "e2"}, set(final["tickets"]))
            self.assertEqual(
                {"prepared"}, set(final["token_ledger"]["disposition"].values())
            )
            self.assert_replays(controller)

    def test_post_prepare_revoke_withdraws_tail_but_dispatch_uses_ticket(self) -> None:
        sink_path = self.root / "post-revoke-sink.sqlite3"
        with (
            self.controller(
                "post-revoke", grants={"g": 2}, slots=["s1", "s2"], claims=self.two_slot_claims()
            ) as controller,
            AuthenticatedSink(sink_path, self.secret) as sink,
        ):
            self.assertTrue(
                controller.apply(
                    {"op": "prepare", "plan_version": 0, "assignments": {"e1": "c1"}}
                ).accepted
            )
            revoke = controller.apply({"op": "revoke", "plan_version": 1, "grant": "g"})
            revoked = controller.snapshot()["state"]
            self.assertTrue(revoke.accepted)
            self.assertEqual("closed", revoked["grant_epochs"]["g"])
            self.assertEqual("withdrawn", revoked["plan"]["disposition"]["c2"])
            self.assertEqual(1, revoked["plan"]["W"]["s2"]["g"])
            self.assertEqual([], revoked["plan"]["remaining"])
            self.assertEqual("prepared", revoked["tickets"]["e1"]["phase"])
            self.assertEqual(
                "prepared",
                revoked["token_ledger"]["disposition"][
                    revoked["token_ledger"]["origin"]["c1"]
                ],
            )
            self.assertEqual(
                "withdrawn",
                revoked["token_ledger"]["disposition"][
                    revoked["token_ledger"]["origin"]["c2"]
                ],
            )

            def callback(binding: dict[str, str]) -> dict:
                self.assertEqual({"effect": "e1", "claim": "c1"}, binding)
                stable_key = binding["effect"]
                request_hash = "request-hash-e1"
                outcome = "succeeded"
                evidence = sink.attempt(
                    effect_id="e1",
                    stable_key=stable_key,
                    request_hash=request_hash,
                    outcome=outcome,
                    authorization=sink.authorize_attempt(
                        "e1", stable_key, request_hash, outcome
                    ),
                )
                return {"outcome": outcome, "evidence": evidence}

            result = service_protected_callback(controller, effect="e1", callback=callback)
            self.assertEqual("completed", result["status"])
            self.assertEqual("succeeded", result["outcome"])
            evidence = result["callback_result"]["evidence"]
            self.assertEqual("e1", verify_evidence(self.secret, evidence)["effect_id"])
            final = controller.snapshot()["state"]
            self.assertNotIn("e1", final["tickets"])
            self.assertEqual({"claim": "c1", "outcome": "succeeded"}, final["receipts"]["e1"])
            self.assertEqual(1, len(sink.snapshot()["outcomes"]))
            self.assert_replays(controller)

    def test_restriction_computes_withdrawal_and_token_disposition(self) -> None:
        claims = [
            {"claim": "c1", "grant": "g", "demand": 1, "owner": "o1", "slot": "s1"},
            {"claim": "c2", "grant": "g", "demand": 1, "owner": "o2", "slot": "s1"},
        ]
        with self.controller(
            "restriction", grants={"g": 2}, slots=["s1"], claims=claims
        ) as controller:
            before = controller.snapshot()["state"]
            removed_token = before["token_ledger"]["origin"]["c2"]
            restricted = controller.apply(
                {"op": "restrict", "plan_version": 0, "keep_owners": ["o1"]}
            )
            self.assertTrue(restricted.accepted)
            after = controller.snapshot()["state"]
            self.assertEqual(["c1"], after["plan"]["remaining"])
            self.assertEqual("withdrawn", after["plan"]["disposition"]["c2"])
            self.assertEqual(1, after["plan"]["W"]["s1"]["g"])
            self.assertEqual("terminal", after["claims"]["c2"]["status"])
            self.assertEqual(
                "withdrawn", after["token_ledger"]["disposition"][removed_token]
            )
            self.assertTrue(
                controller.apply(
                    {"op": "prepare", "plan_version": 1, "assignments": {"e1": "c1"}}
                ).accepted
            )
            self.assert_replays(controller)

    def test_retry_after_crash_uses_only_the_durable_ticket(self) -> None:
        with self.controller(
            "ticket-retry",
            grants={"g": 1},
            slots=["s1"],
            claims=[
                {
                    "claim": "c1",
                    "grant": "g",
                    "demand": 1,
                    "owner": "o1",
                    "slot": "s1",
                }
            ],
        ) as controller:
            self.assertTrue(
                controller.apply(
                    {"op": "prepare", "plan_version": 0, "assignments": {"e1": "c1"}}
                ).accepted
            )
            prepared = controller.snapshot()["state"]
            frozen_plan = prepared["plan"]
            frozen_ledger = prepared["token_ledger"]
            self.assertTrue(controller.apply({"op": "dispatch", "effect": "e1"}).accepted)
            self.assertTrue(controller.apply({"op": "crash"}).accepted)
            uncertain = controller.snapshot()["state"]
            self.assertEqual("uncertain", uncertain["tickets"]["e1"]["phase"])
            self.assertEqual(frozen_plan, uncertain["plan"])
            self.assertEqual(frozen_ledger, uncertain["token_ledger"])
            self.assertTrue(controller.apply({"op": "retry", "effect": "e1"}).accepted)
            retried = controller.snapshot()["state"]
            self.assertEqual("inflight", retried["tickets"]["e1"]["phase"])
            self.assertEqual(frozen_plan, retried["plan"])
            self.assertEqual(frozen_ledger, retried["token_ledger"])
            self.assertTrue(
                controller.apply(
                    {"op": "settle", "effect": "e1", "outcome": "succeeded"}
                ).accepted
            )
            settled = controller.snapshot()["state"]
            self.assertEqual(frozen_plan, settled["plan"])
            self.assertEqual(frozen_ledger, settled["token_ledger"])
            self.assertEqual({"claim": "c1", "outcome": "succeeded"}, settled["receipts"]["e1"])
            self.assert_replays(controller)

    def test_prepare_crash_boundaries_are_old_or_new_not_torn(self) -> None:
        path = self.root / "crash.sqlite3"
        controller = PlanPilotController(
            path,
            grants={"g": 1},
            ordered_slots=["s1"],
            claims=[{"claim": "c1", "grant": "g", "demand": 1, "owner": "o1", "slot": "s1"}],
        )
        with self.assertRaisesRegex(InjectedCrash, "before SQLite commit"):
            controller.apply(
                {"op": "prepare", "plan_version": 0, "assignments": {"e1": "c1"}},
                crash_at="before_commit",
            )
        old = controller.snapshot()
        self.assertEqual(0, old["state"]["plan"]["version"])
        self.assertEqual({}, old["state"]["tickets"])
        self.assertEqual(1, old["sequence"])
        with self.assertRaisesRegex(InjectedCrash, "after SQLite commit"):
            controller.apply(
                {"op": "prepare", "plan_version": 0, "assignments": {"e1": "c1"}},
                crash_at="after_commit",
            )
        controller.close()

        with PlanPilotController(path) as reopened:
            new = reopened.snapshot()
            self.assertEqual(1, new["state"]["plan"]["version"])
            self.assertEqual("durable", new["state"]["claims"]["c1"]["status"])
            self.assertEqual("prepared", new["state"]["tickets"]["e1"]["phase"])
            self.assertEqual([], new["state"]["plan"]["remaining"])
            self.assertEqual(2, new["sequence"])
            self.assert_replays(reopened)

    def test_replay_recomputes_full_successors_and_rejected_admission(self) -> None:
        with self.controller(
            "replay-adversarial",
            grants={"g": 1},
            slots=["s1"],
            claims=[
                {
                    "claim": "c1",
                    "grant": "g",
                    "demand": 1,
                    "owner": "o1",
                    "slot": "s1",
                }
            ],
        ) as controller:
            genesis = controller.events()[0]
        source = deepcopy(genesis["body"]["successor_state"])

        forged_crash_state = deepcopy(source)
        forged_crash_state["global_version"] += 1
        forged_crash_state["grant_epochs"]["g"] = "closed"
        forged_crash = forged_event(
            genesis,
            kind="crash",
            operation={"op": "crash"},
            accepted=True,
            successor=forged_crash_state,
        )
        with self.assertRaisesRegex(ReplayError, "full-state recomputation"):
            replay_events([genesis, forged_crash])

        valid_prepare = {
            "op": "prepare",
            "plan_version": 0,
            "assignments": {"e1": "c1"},
        }
        forged_reject = forged_event(
            genesis,
            kind="reject",
            operation=valid_prepare,
            accepted=False,
            successor=source,
        )
        with self.assertRaisesRegex(ReplayError, "rejection is admitted"):
            replay_events([genesis, forged_reject])

        expected = reference_transition(source, valid_prepare)
        self.assertTrue(expected.accepted)
        forged_prepare_state = deepcopy(expected.successor)
        forged_prepare_state["grant_versions"]["g"] += 1
        forged_prepare = forged_event(
            genesis,
            kind="prepare",
            operation=valid_prepare,
            accepted=True,
            successor=forged_prepare_state,
        )
        with self.assertRaisesRegex(ReplayError, "full-state recomputation"):
            replay_events([genesis, forged_prepare])

    def test_computed_invalid_candidate_is_an_auditable_reject(self) -> None:
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
        with self.controller(
            "candidate-reject", grants={"g": 2}, slots=["s"], claims=claims
        ) as controller:
            before = controller.snapshot()
            operation = {
                "op": "refine",
                "plan_version": 0,
                "source_claim": "source",
                "children": [{"claim": "child", "owner": "ob", "demand": 1}],
            }
            self.assertFalse(transition_oracle_safe(before["state"], operation))
            decision = controller.apply(operation)
            after = controller.snapshot()
            self.assertFalse(decision.accepted)
            self.assertIn("computed successor invalid", decision.reason)
            self.assertEqual(before["state"], after["state"])
            self.assertEqual(before["state_hash"], decision.state_hash)
            self.assertEqual("reject", controller.events()[-1]["kind"])
            self.assert_replays(controller)

    def test_loaded_source_corruption_is_a_hard_error_not_a_reject(self) -> None:
        path = self.root / "source-corruption.sqlite3"
        controller = PlanPilotController(
            path,
            grants={"g": 1},
            ordered_slots=["s"],
            claims=[
                {
                    "claim": "c",
                    "grant": "g",
                    "demand": 1,
                    "owner": "o",
                    "slot": "s",
                }
            ],
        )
        before_events = len(controller.events())
        with sqlite3.connect(path) as database:
            raw = database.execute(
                "SELECT state_json FROM controller_meta WHERE singleton=1"
            ).fetchone()[0]
            state = json.loads(raw)
            state["plan"]["current_slot"] = None
            database.execute(
                "UPDATE controller_meta SET state_json=? WHERE singleton=1",
                (canonical_json(state),),
            )
        with self.assertRaisesRegex(PlanPilotError, "current_slot"):
            controller.apply({"op": "crash"})
        self.assertEqual(before_events, len(controller.events()))
        controller.close()

    def test_reopen_verifies_history_and_supports_external_head_anchor(self) -> None:
        path = self.root / "anchored.sqlite3"
        with PlanPilotController(
            path,
            grants={"g": 1},
            ordered_slots=["s"],
            claims=[
                {
                    "claim": "c",
                    "grant": "g",
                    "demand": 1,
                    "owner": "o",
                    "slot": "s",
                }
            ],
        ) as controller:
            genesis_anchor = controller.snapshot()["head_hash"]
            self.assertTrue(
                controller.apply(
                    {
                        "op": "prepare",
                        "plan_version": 0,
                        "assignments": {"e": "c"},
                    }
                ).accepted
            )
            current_anchor = controller.snapshot()["head_hash"]

        with PlanPilotController(path, expected_head_hash=current_anchor) as reopened:
            self.assertEqual(current_anchor, reopened.snapshot()["head_hash"])
        with self.assertRaisesRegex(PlanPilotError, "durable head hash mismatch"):
            PlanPilotController(path, expected_head_hash=genesis_anchor)

        with sqlite3.connect(path) as database:
            raw = database.execute(
                "SELECT state_json FROM controller_meta WHERE singleton=1"
            ).fetchone()[0]
            state = json.loads(raw)
            state["token_ledger"] = {
                "initial": ["forged"],
                "origin": {"c": "forged"},
                "disposition": {"forged": "prepared"},
            }
            database.execute(
                "UPDATE controller_meta SET state_json=? WHERE singleton=1",
                (canonical_json(state),),
            )
        with self.assertRaisesRegex(PlanPilotError, "durable history verification"):
            PlanPilotController(path)

    def test_transition_oracle_covers_epochs_target_freshness_and_schemas(self) -> None:
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
        with self.controller("oracle-fields", grants={"g": 2}, slots=["s"], claims=claims) as controller:
            state = controller.snapshot()["state"]
            valid = {
                "op": "merge",
                "plan_version": 0,
                "source_owners": ["oa", "ob"],
                "target_owner": "joined",
            }
            self.assertTrue(transition_oracle_safe(state, valid))
            for field in ("plan_version", "source_owners", "target_owner"):
                missing = dict(valid)
                del missing[field]
                self.assertFalse(transition_oracle_safe(state, missing), field)
            injected = {**valid, "target_valid": True}
            self.assertFalse(transition_oracle_safe(state, injected))
            self.assertFalse(
                transition_oracle_safe(state, {**valid, "target_owner": "oa"})
            )
            self.assertFalse(
                transition_oracle_safe(
                    state,
                    {**valid, "source_owners": ["oa", "closed-or-unknown"]},
                )
            )
            stale = {**valid, "plan_version": 1}
            self.assertFalse(transition_oracle_safe(state, stale))

    def test_transition_oracle_has_complete_operation_field_coverage(self) -> None:
        one = initial_state(
            grants={"g": 2},
            ordered_slots=["s"],
            claims=[
                {
                    "claim": "c",
                    "grant": "g",
                    "demand": 1,
                    "owner": "o",
                    "slot": "s",
                    "batch_root": "r",
                }
            ],
        )
        same_root = initial_state(
            grants={"g": 3},
            ordered_slots=["s"],
            claims=[
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
            ],
        )
        prepare = {
            "op": "prepare",
            "plan_version": 0,
            "assignments": {"e": "c"},
        }
        prepared = reference_transition(one, prepare).successor
        dispatch = {"op": "dispatch", "effect": "e"}
        inflight = reference_transition(prepared, dispatch).successor
        crash = {"op": "crash", "effects": ["e"]}
        uncertain = reference_transition(inflight, crash).successor
        cases = [
            (one, prepare),
            (
                one,
                {
                    "op": "disjoint_mutation",
                    "claim": "outside",
                    "grant": "g",
                    "demand": 1,
                    "owner": "outside-owner",
                },
            ),
            (
                one,
                {
                    "op": "refine",
                    "plan_version": 0,
                    "source_claim": "c",
                    "children": [{"claim": "child", "owner": "o", "demand": 1}],
                },
            ),
            (
                same_root,
                {
                    "op": "merge",
                    "plan_version": 0,
                    "source_owners": ["oa", "ob"],
                    "target_owner": "joined",
                },
            ),
            (one, {"op": "revoke", "plan_version": 0, "grant": "g"}),
            (one, {"op": "restrict", "plan_version": 0, "keep_owners": ["o"]}),
            (prepared, dispatch),
            (inflight, crash),
            (uncertain, {"op": "retry", "effect": "e"}),
            (inflight, {"op": "settle", "effect": "e", "outcome": "succeeded"}),
        ]
        for source, operation in cases:
            with self.subTest(operation=operation["op"]):
                self.assertTrue(reference_transition(source, operation).accepted)
                for field in set(operation) - {"op"}:
                    if operation["op"] == "crash" and field == "effects":
                        continue
                    missing = deepcopy(operation)
                    del missing[field]
                    self.assertFalse(reference_transition(source, missing).accepted)
                injected = {**operation, "target_valid": True}
                self.assertFalse(reference_transition(source, injected).accepted)

    def test_two_prepare_writers_have_one_cas_winner(self) -> None:
        path = self.root / "two-writers.sqlite3"
        PlanPilotController(
            path,
            grants={"g": 1},
            ordered_slots=["s"],
            claims=[
                {
                    "claim": "c",
                    "grant": "g",
                    "demand": 1,
                    "owner": "o",
                    "slot": "s",
                }
            ],
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
            self.assertEqual(1, len(controller.snapshot()["state"]["tickets"]))
            self.assert_replays(controller)

    def test_real_codex_client_owned_callback_is_ticket_gated(self) -> None:
        from adapter.test_app_server import run_preflight

        raw_path = self.root / "real-codex-app-server.jsonl"
        with self.controller(
            "real-codex-gate",
            grants={"g": 1},
            slots=["s"],
            claims=[
                {
                    "claim": "c",
                    "grant": "g",
                    "demand": 1,
                    "owner": "o",
                    "slot": "s",
                }
            ],
        ) as controller:
            self.assertTrue(
                controller.apply(
                    {
                        "op": "prepare",
                        "plan_version": 0,
                        "assignments": {"preflight-effect-1": "c"},
                    }
                ).accepted
            )
            gated_results: list[dict] = []

            def handler(pending: object) -> None:
                arguments = getattr(pending, "arguments")
                effect = str(arguments["effect_id"])

                def callback(binding: dict[str, str]) -> dict:
                    self.assertEqual({"effect": effect, "claim": "c"}, binding)
                    getattr(pending, "respond_text")(f"receipt:{effect}")
                    return {"outcome": "succeeded"}

                gated_results.append(
                    service_protected_callback(
                        controller, effect=effect, callback=callback
                    )
                )

            preflight = run_preflight(
                workspace=self.root,
                raw_jsonl_path=raw_path,
                tool_handler=handler,
            )
            self.assertTrue(preflight.ok)
            self.assertEqual("completed", gated_results[0]["status"])
            self.assertEqual(
                {"claim": "c", "outcome": "succeeded"},
                controller.snapshot()["state"]["receipts"]["preflight-effect-1"],
            )
            self.assert_replays(controller)

    def test_decision_aggregate_is_deterministic_and_contains_no_trajectories(self) -> None:
        records: list[dict[str, bool]] = []
        with self.controller(
            "aggregate-disjoint", grants={"g": 3}, slots=["s1", "s2"], claims=self.two_slot_claims()
        ) as controller:
            records.append(
                decision_baselines(
                    controller.snapshot()["state"],
                    {
                        "op": "disjoint_mutation",
                        "claim": "x",
                        "grant": "g",
                        "demand": 1,
                        "owner": "outside-owner",
                    },
                )
            )
        with self.controller(
            "aggregate-cross", grants={"g": 2}, slots=["s1", "s2"], claims=self.two_slot_claims()
        ) as controller:
            records.append(
                decision_baselines(
                    controller.snapshot()["state"],
                    {"op": "merge", "plan_version": 0, "source_owners": ["o1", "o2"], "target_owner": "m"},
                )
            )
        first, second = aggregate_json(records), aggregate_json(records)
        self.assertEqual(first, second)
        aggregate = json.loads(first)
        self.assertEqual("plan-adapter-pilot.aggregate.v2", aggregate["schema"])
        self.assertEqual(2, aggregate["cases"])
        self.assertEqual(1, aggregate["baselines"]["per_object"]["unsafe_reuse"])
        self.assertEqual(1, aggregate["baselines"]["global_version"]["false_invalidation"])
        self.assertEqual(0, aggregate["baselines"]["semantic_transport"]["unsafe_reuse"])
        self.assertNotIn("claims", first)
        self.assertNotIn("successor_state", first)


if __name__ == "__main__":
    unittest.main()
