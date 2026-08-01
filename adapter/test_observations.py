from __future__ import annotations

import unittest

from adapter.observations import ProbeRecord, mixed_label_fibers, observation_key


def record(case: str, trusted_mode: str, decision: str) -> ProbeRecord:
    return ProbeRecord(
        case_id=case,
        workspace={"checkpoint": "same-bytes"},
        provider_events=(
            {
                "kind": "tool_pending",
                "threadId": f"thread-{case}",
                "turnId": f"turn-{case}",
                "callId": f"call-{case}",
                "tool": "protected_commit",
            },
        ),
        trusted_events=({"kind": "effect_phase", "effect_id": f"effect-{case}", "phase": trusted_mode},),
        action={"kind": "attempt", "effect_id": f"effect-{case}", "same_operation": True},
        oracle_decision=decision,
    )


class ObservationTests(unittest.TestCase):
    def test_alpha_renaming_removes_incidental_ids(self) -> None:
        left = record("C02", "prepared", "accept")
        right = record("C04", "settled", "reject")
        self.assertEqual(observation_key(left, "O1"), observation_key(right, "O1"))
        self.assertNotEqual(observation_key(left, "O2"), observation_key(right, "O2"))

    def test_effect_pair_is_mixed_only_below_o2(self) -> None:
        records = [record("C02", "prepared", "accept"), record("C04", "settled", "reject")]
        self.assertEqual(1, len(mixed_label_fibers(records, "O0")))
        self.assertEqual(1, len(mixed_label_fibers(records, "O1")))
        self.assertEqual([], mixed_label_fibers(records, "O2"))


if __name__ == "__main__":
    unittest.main()
