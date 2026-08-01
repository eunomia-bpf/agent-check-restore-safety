from __future__ import annotations

import signal
from pathlib import Path
import tempfile
import unittest

from adapter.controller import DurableController
from adapter.sink import verify_evidence
from adapter.worker import (
    apply_in_worker,
    dispatch_with_recovery,
    stable_key_for,
)


class WorkerCrashRecoveryTests(unittest.TestCase):
    secret = b"worker-test-secret"

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def _paths(self, name: str) -> tuple[Path, Path]:
        directory = self.root / name
        directory.mkdir()
        return directory / "controller.sqlite3", directory / "sink.sqlite3"

    def _prepare(self, name: str, policy: str = "P3") -> tuple[Path, Path]:
        controller_path, sink_path = self._paths(name)
        with DurableController(controller_path, policy, {"g": 1}) as controller:
            reserve = controller.apply(
                {
                    "op": "reserve",
                    "request": "reserve_e1",
                    "claim": "c1",
                    "branch": "root",
                    "grant": "g",
                    "demand": 1,
                }
            )
            prepare = controller.apply(
                {
                    "op": "prepare",
                    "request": "prepare_e1",
                    "effect": "e1",
                    "claim": "c1",
                }
            )
        self.assertTrue(reserve.accepted)
        self.assertTrue(prepare.accepted)
        return controller_path, sink_path

    def _dispatch(self, name: str, fault_mode: str, policy: str = "P3") -> dict:
        controller_path, sink_path = self._prepare(name, policy)
        return dispatch_with_recovery(
            controller_path=controller_path,
            policy=policy,
            grants={"g": 1},
            sink_path=sink_path,
            secret=self.secret,
            operation={
                "op": "dispatch",
                "request": "dispatch_e1",
                "effect": "e1",
                "site": "e1.initial",
            },
            crash_mode=fault_mode,
            provider_call_id="provider-call-1",
            timeout=5.0,
            restart_timeout=5.0,
            request_hash="request-hash-1",
        )

    def assert_single_receipt(self, result: dict, stable_key: str = "e1") -> None:
        self.assertEqual("completed", result["status"])
        self.assertEqual(1, result["attempt_count"])
        self.assertEqual(1, result["outcome_count"])
        self.assertEqual(stable_key, result["stable_key"])
        self.assertEqual(
            {"claim": "c1", "outcome": "succeeded"},
            result["controller_receipt"],
        )
        self.assertEqual(1, len(result["sink_snapshot"]["attempts"]))
        self.assertFalse(result["sink_snapshot"]["attempts"][0]["reused"])
        evidence = result["reply"]["sink_evidence"]
        body = verify_evidence(self.secret, evidence)
        self.assertEqual("receipt", body["kind"])
        self.assertEqual("e1", body["effect_id"])
        self.assertEqual(stable_key, body["stable_key"])
        self.assertEqual("succeeded", body["outcome"])
        self.assertEqual("dispatch_e1", result["dispatch_decision"]["request"])
        self.assertEqual("dispatch", result["dispatch_decision"]["operation"])
        self.assertEqual("accept", result["dispatch_decision"]["decision"])
        self.assertEqual("attempt", result["dispatch_decision"]["abstract_label"])

    def test_no_fault_dispatches_and_settles_in_one_worker(self) -> None:
        result = self._dispatch("none", "none")
        self.assert_single_receipt(result)
        self.assertEqual("none", result["recovery_action"])
        self.assertEqual(0, result["initial_worker"]["exitcode"])
        self.assertIsNone(result["recovery_worker"])

    def test_before_dispatch_crash_restarts_then_dispatches_once(self) -> None:
        result = self._dispatch("before", "before_dispatch")
        self.assert_single_receipt(result)
        self.assertEqual("dispatch_once", result["recovery_action"])
        self.assertEqual("accept", result["attempt_probe"]["decision"])
        self.assertEqual(-int(signal.SIGKILL), result["initial_worker"]["exitcode"])
        self.assertEqual(0, result["recovery_worker"]["exitcode"])
        self.assertNotEqual(
            result["initial_worker"]["pid"], result["recovery_worker"]["pid"]
        )
        with DurableController(
            self.root / "before" / "controller.sqlite3", "P3"
        ) as controller:
            kinds = [event["kind"] for event in controller.events()]
        self.assertEqual(1, kinds.count("dispatch"))
        self.assertEqual(1, kinds.count("settle"))
        self.assertNotIn("crash", kinds)
        self.assertEqual(
            "prepared",
            result["crash_boundary"]["controller"]["state"]["tickets"]["e1"]["phase"],
        )
        self.assertEqual([], result["crash_boundary"]["sink"]["outcomes"])

    def test_after_remote_success_queries_without_duplicate_attempt(self) -> None:
        result = self._dispatch("remote", "after_remote_success")
        self.assert_single_receipt(result)
        self.assertEqual("query_and_settle", result["recovery_action"])
        self.assertEqual(-int(signal.SIGKILL), result["initial_worker"]["exitcode"])
        self.assertEqual(0, result["recovery_worker"]["exitcode"])
        with DurableController(
            self.root / "remote" / "controller.sqlite3", "P3"
        ) as controller:
            kinds = [event["kind"] for event in controller.events()]
        self.assertEqual(1, kinds.count("dispatch"))
        self.assertEqual(1, kinds.count("crash"))
        self.assertEqual(1, kinds.count("settle"))
        self.assertNotIn("retry", kinds)
        self.assertEqual(
            "inflight",
            result["crash_boundary"]["controller"]["state"]["tickets"]["e1"]["phase"],
        )
        self.assertEqual(1, len(result["crash_boundary"]["sink"]["outcomes"]))

    def test_after_controller_commit_returns_cached_receipt(self) -> None:
        result = self._dispatch("commit", "after_controller_commit")
        self.assert_single_receipt(result)
        self.assertEqual("return_cached_receipt", result["recovery_action"])
        self.assertEqual("reject", result["attempt_probe"]["decision"])
        self.assertEqual("attempt_e1", result["attempt_probe"]["request"])
        self.assertEqual(-int(signal.SIGKILL), result["initial_worker"]["exitcode"])
        payload = result["recovery_worker"]["payload"]
        self.assertIsNone(payload["dispatch"])
        self.assertIsNone(payload["settlement"])
        with DurableController(
            self.root / "commit" / "controller.sqlite3", "P3"
        ) as controller:
            kinds = [event["kind"] for event in controller.events()]
        self.assertEqual(1, kinds.count("dispatch"))
        self.assertEqual(1, kinds.count("settle"))
        self.assertEqual(1, kinds.count("reject"))
        self.assertNotIn("crash", kinds)
        self.assertEqual(
            {"claim": "c1", "outcome": "succeeded"},
            result["crash_boundary"]["controller"]["state"]["receipts"]["e1"],
        )
        self.assertEqual(1, len(result["crash_boundary"]["sink"]["outcomes"]))

    def test_p0_uses_retained_provider_call_id_and_never_synthesizes_one(self) -> None:
        self.assertEqual(
            "provider-call-1",
            stable_key_for(
                "P0", effect_id="e1", provider_call_id="provider-call-1"
            ),
        )
        with self.assertRaisesRegex(ValueError, "retained provider_call_id"):
            stable_key_for("P0", effect_id="e1", provider_call_id=None)

        result = self._dispatch("p0", "after_remote_success", policy="P0")
        self.assert_single_receipt(result, stable_key="provider-call-1")
        self.assertEqual("e1", result["effect_id"])
        self.assertEqual("provider-call-1", result["provider_call_id"])

    def test_apply_in_worker_initializes_and_reopens_controller(self) -> None:
        controller_path, _ = self._paths("ordinary")
        reserve = apply_in_worker(
            controller_path=controller_path,
            policy="P3",
            grants={"g": 1},
            operation={
                "op": "reserve",
                "request": "reserve_e1",
                "claim": "c1",
                "branch": "root",
                "grant": "g",
                "demand": 1,
            },
        )
        prepare = apply_in_worker(
            controller_path=controller_path,
            policy="P3",
            grants={"g": 1},
            operation={
                "op": "prepare",
                "request": "prepare_e1",
                "effect": "e1",
                "claim": "c1",
            },
        )
        self.assertEqual("accept", reserve["decision"]["decision"])
        self.assertEqual("accept", prepare["decision"]["decision"])
        self.assertNotEqual(reserve["worker"]["pid"], prepare["worker"]["pid"])
        self.assertEqual(
            "prepared",
            prepare["controller_snapshot"]["state"]["tickets"]["e1"]["phase"],
        )


if __name__ == "__main__":
    unittest.main()
