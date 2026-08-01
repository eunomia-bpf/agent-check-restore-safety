from __future__ import annotations

from copy import deepcopy
import unittest

from adapter.replay import (
    ATTEMPT,
    TAU,
    ReplayError,
    ReplayState,
    apply_event,
    body_hash,
    event_hash,
    replay_bundle,
    seal_event,
    state_hash,
)


def emit(
    state: ReplayState | None, kind: str, operation: dict
) -> tuple[ReplayState, str, dict]:
    record = seal_event(state, kind, operation)
    successor, label = apply_event(state, record)
    return successor, label.kind, record


def start(grants: dict[str, int] | None = None) -> tuple[ReplayState, list[dict]]:
    grants = grants or {"g": 1}
    state, label, event = emit(
        None,
        "genesis",
        {
            "op": "genesis",
            "grants": grants,
            "active_branches": ["root"],
            "maximal_frontiers": [["root"]],
            "delegations": {grant: ["root"] for grant in grants},
        },
    )
    assert label == TAU
    return state, [event]


def apply(state: ReplayState, events: list[dict], kind: str, operation: dict) -> str:
    successor, label, event = emit(state, kind, operation)
    state.__dict__.update(successor.__dict__)
    events.append(event)
    return label


def reject(state: ReplayState, events: list[dict], action: dict) -> str:
    return apply(state, events, "reject", {"op": "reject", "action": action})


class ReplayWitnessTests(unittest.TestCase):
    def test_c13_replace_and_c14_live_restore_have_different_p3_labels(self) -> None:
        def prefix(mode: str) -> tuple[ReplayState, list[dict]]:
            state, events = start()
            apply(state, events, "checkpoint", {"op": "checkpoint", "checkpoint": "cp0", "branch": "root"})
            apply(
                state,
                events,
                "reserve",
                {"op": "reserve", "claim": "c_old", "branch": "root", "grant": "g", "demand": 1},
            )
            apply(
                state,
                events,
                "restore",
                {
                    "op": "restore",
                    "checkpoint": "cp0",
                    "source": "root",
                    "target": "restored",
                    "mode": mode,
                },
            )
            return state, events

        replace, replace_events = prefix("replace")
        self.assertEqual(
            TAU,
            apply(
                replace,
                replace_events,
                "reserve",
                {
                    "op": "reserve",
                    "claim": "c_new",
                    "branch": "restored",
                    "grant": "g",
                    "demand": 1,
                },
            ),
        )
        self.assertEqual("terminal", replace.claims["c_old"].status)

        live, live_events = prefix("live")
        before = state_hash(live)
        self.assertEqual(
            TAU,
            reject(
                live,
                live_events,
                {
                    "op": "reserve",
                    "claim": "c_new",
                    "branch": "restored",
                    "grant": "g",
                    "demand": 1,
                },
            ),
        )
        self.assertEqual(before, state_hash(live))
        self.assertNotIn("c_new", live.claims)
        self.assertEqual(frozenset({"root", "restored"}), max(live.frontier, key=len))

    def test_c16_shared_parallel_grant_rejects_but_c18_delegated_grants_accept(self) -> None:
        shared, shared_events = start()
        apply(
            shared,
            shared_events,
            "fork",
            {"op": "fork", "source": "root", "kind": "parallel", "children": ["left", "right"]},
        )
        apply(
            shared,
            shared_events,
            "reserve",
            {"op": "reserve", "claim": "c1", "branch": "left", "grant": "g", "demand": 1},
        )
        reject(
            shared,
            shared_events,
            {"op": "reserve", "claim": "c2", "branch": "right", "grant": "g", "demand": 1},
        )
        self.assertNotIn("c2", shared.claims)

        split, split_events = start({"g1": 1, "g2": 1})
        apply(
            split,
            split_events,
            "fork",
            {"op": "fork", "source": "root", "kind": "parallel", "children": ["left", "right"]},
        )
        apply(split, split_events, "delegate", {"op": "delegate", "grant": "g1", "branch": "left"})
        apply(split, split_events, "delegate", {"op": "delegate", "grant": "g2", "branch": "right"})
        apply(
            split,
            split_events,
            "reserve",
            {"op": "reserve", "claim": "c1", "branch": "left", "grant": "g1", "demand": 1},
        )
        apply(
            split,
            split_events,
            "reserve",
            {"op": "reserve", "claim": "c2", "branch": "right", "grant": "g2", "demand": 1},
        )
        self.assertEqual({"c1", "c2"}, set(split.claims))

    def test_c02_prepared_attempt_and_c04_settled_redispatch_stutter(self) -> None:
        prepared, prepared_events = start()
        apply(
            prepared,
            prepared_events,
            "reserve",
            {"op": "reserve", "claim": "c1", "branch": "root", "grant": "g", "demand": 1},
        )
        apply(prepared, prepared_events, "prepare", {"op": "prepare", "effect": "e1", "claim": "c1"})
        apply(prepared, prepared_events, "crash", {"op": "crash", "effects": []})
        self.assertEqual(
            ATTEMPT,
            apply(prepared, prepared_events, "dispatch", {"op": "dispatch", "effect": "e1", "claim": "c1"}),
        )

        settled, settled_events = start()
        apply(
            settled,
            settled_events,
            "reserve",
            {"op": "reserve", "claim": "c1", "branch": "root", "grant": "g", "demand": 1},
        )
        apply(settled, settled_events, "prepare", {"op": "prepare", "effect": "e1", "claim": "c1"})
        apply(settled, settled_events, "dispatch", {"op": "dispatch", "effect": "e1"})
        apply(settled, settled_events, "settle", {"op": "settle", "effect": "e1", "outcome": "succeeded"})
        before = state_hash(settled)
        self.assertEqual(
            TAU,
            reject(settled, settled_events, {"op": "retry", "effect": "e1", "claim": "c1"}),
        )
        self.assertEqual(before, state_hash(settled))
        self.assertIn("e1", settled.receipts)
        self.assertNotIn("e1", settled.tickets)

    def test_crash_changes_only_inflight_to_uncertain_and_retry_keeps_binding(self) -> None:
        state, events = start()
        apply(
            state,
            events,
            "reserve",
            {"op": "reserve", "claim": "c1", "branch": "root", "grant": "g", "demand": 1},
        )
        apply(state, events, "prepare", {"op": "prepare", "effect": "e1", "claim": "c1"})
        apply(state, events, "dispatch", {"op": "dispatch", "effect": "e1"})
        apply(state, events, "crash", {"op": "crash", "effects": ["e1"]})
        self.assertEqual("uncertain", state.tickets["e1"].phase)
        self.assertEqual(ATTEMPT, apply(state, events, "retry", {"op": "retry", "effect": "e1"}))
        self.assertEqual("c1", state.tickets["e1"].claim)

    def test_c19_certified_merge_passes_and_c20_unsafe_direct_merge_rejects(self) -> None:
        def choice_prefix() -> tuple[ReplayState, list[dict]]:
            state, events = start()
            apply(
                state,
                events,
                "fork",
                {"op": "fork", "source": "root", "kind": "choice", "children": ["left", "right"]},
            )
            apply(
                state,
                events,
                "reserve",
                {"op": "reserve", "claim": "c1", "branch": "left", "grant": "g", "demand": 1},
            )
            apply(
                state,
                events,
                "reserve",
                {"op": "reserve", "claim": "c2", "branch": "right", "grant": "g", "demand": 1},
            )
            return state, events

        safe, safe_events = choice_prefix()
        apply(
            safe,
            safe_events,
            "merge",
            {
                "op": "merge",
                "mode": "certified",
                "sources": ["left", "right"],
                "target": "merged",
                "retain_claims": ["c1"],
                "certificate": {
                    "projection": {
                        "target_configuration": ["merged"],
                        "source_configuration": ["left"],
                    },
                    "claim_map": [
                        {"source_claim": "c1", "target_claim": "c1"}
                    ],
                },
            },
        )
        self.assertEqual("tentative", safe.claims["c1"].status)
        self.assertEqual("terminal", safe.claims["c2"].status)

        uncertified, uncertified_events = choice_prefix()
        reject(
            uncertified,
            uncertified_events,
            {
                "op": "merge",
                "mode": "certified",
                "sources": ["left", "right"],
                "target": "merged",
                "retain_claims": ["c1"],
            },
        )
        self.assertNotIn("merged", uncertified.branch_epochs)

        unsafe, unsafe_events = choice_prefix()
        reject(
            unsafe,
            unsafe_events,
            {
                "op": "merge",
                "mode": "direct",
                "sources": ["left", "right"],
                "target": "merged",
                "retain_claims": ["c1", "c2"],
            },
        )
        self.assertNotIn("merged", unsafe.branch_epochs)


class ReplayIntegrityTests(unittest.TestCase):
    def test_genesis_can_bootstrap_the_complete_semantic_state(self) -> None:
        operation = {
            "op": "genesis",
            "state": {
                "grants": {"g": 1},
                "grant_epochs": {"g": "open"},
                "active_branches": ["root"],
                "frontier": [[], ["root"]],
                "branch_epochs": {"root": "open"},
                "delegations": {"g": ["root"]},
                "claims": {
                    "c1": {"grant": "g", "demand": 1, "status": "durable", "owner": None}
                },
                "tickets": {"e1": {"claim": "c1", "phase": "prepared"}},
                "receipts": {},
                "checkpoints": {"cp0": {"branch": "root"}},
                "forks": {},
            },
        }
        event = seal_event(None, "genesis", operation)
        state, label = apply_event(None, event)
        self.assertEqual(TAU, label.kind)
        self.assertEqual("prepared", state.tickets["e1"].phase)
        self.assertEqual("root", state.checkpoints["cp0"].branch)

    def test_replay_bundle_checks_final_anchor(self) -> None:
        state, events = start()
        apply(state, events, "checkpoint", {"op": "checkpoint", "checkpoint": "cp0", "branch": "root"})
        result = replay_bundle(
            {"events": events, "head_hash": state.head_hash, "state_hash": state_hash(state)}
        )
        self.assertEqual(state_hash(state), state_hash(result.state))
        self.assertEqual((TAU, TAU), tuple(label.kind for label in result.labels))

    def test_body_hash_tampering_is_detected(self) -> None:
        state, _ = start()
        event = seal_event(state, "checkpoint", {"op": "checkpoint", "checkpoint": "cp0", "branch": "root"})
        event["body"]["operation"]["checkpoint"] = "attacker"
        with self.assertRaisesRegex(ReplayError, "body hash mismatch"):
            apply_event(state, event)

    def test_chain_and_state_hash_tampering_are_detected(self) -> None:
        state, _ = start()
        event = seal_event(state, "checkpoint", {"op": "checkpoint", "checkpoint": "cp0", "branch": "root"})

        wrong_chain = deepcopy(event)
        wrong_chain["previous_hash"] = "f" * 64
        wrong_chain["event_hash"] = event_hash(wrong_chain)
        with self.assertRaisesRegex(ReplayError, "wrong predecessor"):
            apply_event(state, wrong_chain)

        wrong_state = deepcopy(event)
        wrong_state["state_hash"] = "e" * 64
        wrong_state["event_hash"] = event_hash(wrong_state)
        with self.assertRaisesRegex(ReplayError, "state hash mismatch"):
            apply_event(state, wrong_state)

    def test_non_genesis_full_post_state_and_nonzero_stutter_are_rejected(self) -> None:
        state, _ = start()
        malformed = {
            "op": "checkpoint",
            "checkpoint": "cp0",
            "branch": "root",
            "post_state": state.semantic_dict(),
        }
        with self.assertRaisesRegex(ReplayError, "full post-state"):
            seal_event(state, "checkpoint", malformed)

        with self.assertRaisesRegex(ReplayError, "nonzero protected outcome"):
            seal_event(
                state,
                "checkpoint",
                {"op": "checkpoint", "checkpoint": "cp0", "branch": "root", "actual": 1},
            )

    def test_attempt_requires_prepare_and_effect_binding_is_one_shot(self) -> None:
        state, events = start()
        with self.assertRaisesRegex(ReplayError, "no prepared ticket"):
            seal_event(state, "dispatch", {"op": "dispatch", "effect": "e1"})
        apply(
            state,
            events,
            "reserve",
            {"op": "reserve", "claim": "c1", "branch": "root", "grant": "g", "demand": 1},
        )
        apply(state, events, "prepare", {"op": "prepare", "effect": "e1", "claim": "c1"})
        with self.assertRaisesRegex(ReplayError, "already bound"):
            seal_event(state, "prepare", {"op": "prepare", "effect": "e1", "claim": "c1"})


if __name__ == "__main__":
    unittest.main()
