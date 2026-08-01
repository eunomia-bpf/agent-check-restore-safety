from __future__ import annotations

from pathlib import Path
import unittest

from adapter.oracle import assert_controller_oracle_separation, load_oracle


ROOT = Path(__file__).resolve().parents[1]


class OracleFixtureTests(unittest.TestCase):
    def test_fixture_is_complete_and_has_three_mixed_probe_families(self) -> None:
        cases = load_oracle(ROOT / "adapter" / "oracle.yaml")
        probes = [case.observation_probe for case in cases.values() if case.observation_probe]
        self.assertEqual(
            {"topology", "authority_lineage", "effect_phase"},
            {probe.name for probe in probes},
        )
        for name in {probe.name for probe in probes}:
            self.assertEqual({"accept", "reject"}, {probe.decision for probe in probes if probe.name == name})

    def test_worker_modules_do_not_import_oracle(self) -> None:
        assert_controller_oracle_separation(ROOT / "adapter")


if __name__ == "__main__":
    unittest.main()
