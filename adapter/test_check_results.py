from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import unittest

from adapter.check_results import check_document


ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "adapter" / "litmus.yaml"
ORACLE = ROOT / "adapter" / "oracle.yaml"
RESULT = ROOT / "adapter" / "results" / "litmus.json"
RAW = ROOT / "adapter" / "results" / "raw" / "app-server.jsonl"


@unittest.skipUnless(RESULT.exists() and RAW.exists(), "checked runtime artifact is absent")
class CheckedArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.document = json.loads(RESULT.read_text(encoding="utf-8"))

    def check(self, document: dict) -> dict:
        return check_document(
            document,
            suite_path=SUITE,
            oracle_path=ORACLE,
            adapter_root=ROOT / "adapter",
            raw_jsonl_path=RAW,
        )

    def test_retained_artifact_passes_every_gate(self) -> None:
        report = self.check(self.document)
        self.assertTrue(report["ok"], report["failures"])
        self.assertEqual(89, report["metrics"]["p3_decisions_matching"])
        self.assertEqual(20, report["metrics"]["p3_replay_count"])
        self.assertEqual(44, report["metrics"]["raw_protocol"]["item_tool_call_count"])

    def test_oracle_decision_and_event_tampering_fail_closed(self) -> None:
        altered = deepcopy(self.document)
        p3_c01 = next(
            run
            for run in altered["runs"]
            if run["policy"] == "P3" and run["case_id"] == "C01"
        )
        next(
            decision
            for decision in p3_c01["decisions"]
            if decision.get("request") == "reserve_e1"
        )["decision"] = "reject"
        p3_c01["controller"]["events"][0]["state_hash"] = "f" * 64
        report = self.check(altered)
        self.assertFalse(report["ok"])
        self.assertTrue(any("expected accept" in item for item in report["failures"]))
        self.assertTrue(any("replay failed" in item for item in report["failures"]))

    def test_fabricated_or_missing_provider_summary_disagrees_with_raw_jsonl(self) -> None:
        altered = deepcopy(self.document)
        run = next(value for value in altered["runs"] if value["provider"]["tool_calls"])
        run["provider"]["tool_calls"].clear()
        report = self.check(altered)
        self.assertFalse(report["ok"])
        self.assertTrue(any("raw item/tool/call multiset" in item for item in report["failures"]))


if __name__ == "__main__":
    unittest.main()
