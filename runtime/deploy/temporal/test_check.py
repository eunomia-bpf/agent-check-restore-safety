#!/usr/bin/env python3
"""Synthetic mutation tests for the minimal Temporal evidence checker."""

from __future__ import annotations

import importlib.util
import copy
import json
from pathlib import Path
import tempfile
import unittest


CHECK_PATH = Path(__file__).with_name("check.py")
SPEC = importlib.util.spec_from_file_location("temporal_check", CHECK_PATH)
assert SPEC is not None and SPEC.loader is not None
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


class CheckerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "evidence.json"
        digest = "a" * 64
        delivery = {"sequence": 1, "operation_id": "payment/order-1", "request_sha256": digest}
        cut = [
            "EVENT_TYPE_WORKFLOW_EXECUTION_STARTED",
            "EVENT_TYPE_WORKFLOW_TASK_SCHEDULED",
            "EVENT_TYPE_WORKFLOW_TASK_STARTED",
            "EVENT_TYPE_WORKFLOW_TASK_COMPLETED",
            "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED",
            "EVENT_TYPE_ACTIVITY_TASK_STARTED",
        ]
        common = {
            "mode": "auto_upgrade",
            "workflow_id": "food-order/order-1",
            "input_sha256": "b" * 64,
            "v1_build": {"build_id": "food-order-v1", "sha256": "c" * 64},
            "v2_build": {"build_id": "food-order-v2", "sha256": "d" * 64},
            "cut_history_event_types": cut,
            "final_history_event_types": cut + ["EVENT_TYPE_WORKFLOW_TASK_FAILED"],
            "final_status": "WORKFLOW_EXECUTION_STATUS_RUNNING",
            "observed_deployment_version": {
                "deployment_name": "food-ordering", "build_id": "food-order-v2",
            },
        }
        self.evidence = {
            "schema": 1,
            "upstream": {
                "samples_go_commit": CHECK.SAMPLES_GO_COMMIT,
                "temporal_cli_version": CHECK.TEMPORAL_CLI_VERSION,
                "temporal_server_version": CHECK.TEMPORAL_SERVER_VERSION,
                "temporal_sdk_version": CHECK.TEMPORAL_SDK_VERSION,
            },
            "mode": "auto_upgrade",
            "cases": {
                "h0": copy.deepcopy(common) | {
                    "case": "h0", "provider": {"deliveries": [copy.deepcopy(delivery)], "commits": []},
                },
                "h1": copy.deepcopy(common) | {
                    "case": "h1",
                    "provider": {
                        "deliveries": [copy.deepcopy(delivery)],
                        "commits": [copy.deepcopy(delivery)],
                    },
                },
            },
        }
        self.write()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write(self) -> None:
        self.path.write_text(json.dumps(self.evidence, sort_keys=True))

    def check(self) -> dict[str, object]:
        return CHECK.check_evidence(self.path)

    def test_accepts_observed_auto_upgrade_failure(self) -> None:
        self.assertTrue(self.check()["valid"])

    def test_accepts_auto_upgrade_without_presuming_failure(self) -> None:
        self.evidence["cases"]["h1"]["final_status"] = "WORKFLOW_EXECUTION_STATUS_COMPLETED"
        self.evidence["cases"]["h1"]["final_history_event_types"].append(
            "EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED"
        )
        self.write()
        self.assertTrue(self.check()["valid"])

    def test_rejects_mismatched_input(self) -> None:
        self.evidence["cases"]["h1"]["input_sha256"] = "e" * 64
        self.write()
        with self.assertRaisesRegex(CHECK.EvidenceError, "input_sha256 differs"):
            self.check()

    def test_rejects_mismatched_cut_history(self) -> None:
        self.evidence["cases"]["h1"]["cut_history_event_types"][-1] = "EVENT_TYPE_ACTIVITY_TASK_COMPLETED"
        self.evidence["cases"]["h1"]["final_history_event_types"][5] = "EVENT_TYPE_ACTIVITY_TASK_COMPLETED"
        self.write()
        with self.assertRaisesRegex(CHECK.EvidenceError, "cut History projection differs"):
            self.check()

    def test_rejects_h0_completion_without_commit(self) -> None:
        self.evidence["cases"]["h0"]["final_status"] = "WORKFLOW_EXECUTION_STATUS_COMPLETED"
        self.write()
        with self.assertRaisesRegex(CHECK.EvidenceError, "unsafely completed H0"):
            self.check()

    def test_rejects_second_h1_delivery(self) -> None:
        second = dict(self.evidence["cases"]["h1"]["provider"]["deliveries"][0])
        second["sequence"] = 2
        self.evidence["cases"]["h1"]["provider"]["deliveries"].append(second)
        self.write()
        with self.assertRaisesRegex(CHECK.EvidenceError, "dispatch payment exactly once"):
            self.check()

    def test_rejects_wrong_external_fact_split(self) -> None:
        self.evidence["cases"]["h0"]["provider"]["commits"] = [
            self.evidence["cases"]["h0"]["provider"]["deliveries"][0]
        ]
        self.write()
        with self.assertRaisesRegex(CHECK.EvidenceError, "h0 durable payment commit count differs"):
            self.check()

    def test_rejects_unpinned_upstream(self) -> None:
        self.evidence["upstream"]["temporal_server_version"] = "latest"
        self.write()
        with self.assertRaisesRegex(CHECK.EvidenceError, "upstream identities differ"):
            self.check()


if __name__ == "__main__":
    unittest.main()
