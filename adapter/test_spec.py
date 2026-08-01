from __future__ import annotations

from pathlib import Path
import unittest

from adapter.spec import FORBIDDEN_WORKER_KEYS, load_litmus


ROOT = Path(__file__).resolve().parents[1]


class LitmusSpecTests(unittest.TestCase):
    def test_fixed_matrix_and_worker_oracle_separation(self) -> None:
        cases = load_litmus(ROOT / "adapter" / "litmus.yaml")
        self.assertEqual(20, len(cases))
        self.assertEqual(20, len({case.opaque_worker_id for case in cases}))
        for case in cases:
            payload = case.worker_payload("P3")
            self.assertFalse(FORBIDDEN_WORKER_KEYS.intersection(payload))
            self.assertNotIn(case.case_id, repr(payload))

    def test_three_observation_pair_inputs_are_structurally_matched(self) -> None:
        by_id = {case.case_id: case for case in load_litmus(ROOT / "adapter" / "litmus.yaml")}
        self.assertEqual(
            [op["request"] for op in by_id["C13"].operations if op.get("request")],
            [op["request"] for op in by_id["C14"].operations if op.get("request")],
        )
        self.assertEqual(
            [op["request"] for op in by_id["C16"].operations if op.get("request")][-1],
            [op["request"] for op in by_id["C18"].operations if op.get("request")][-1],
        )
        self.assertEqual("before_dispatch", by_id["C02"].crash_mode)
        self.assertEqual("after_controller_commit", by_id["C04"].crash_mode)


if __name__ == "__main__":
    unittest.main()
