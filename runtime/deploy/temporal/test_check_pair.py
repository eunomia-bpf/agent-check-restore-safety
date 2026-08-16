#!/usr/bin/env python3
"""Mutation tests for the raw Temporal pair checker."""

from __future__ import annotations

import base64
import copy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock


CHECK_PATH = Path(__file__).with_name("check-pair.py")
SPEC = importlib.util.spec_from_file_location("temporal_pair_check", CHECK_PATH)
assert SPEC is not None and SPEC.loader is not None
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


def payload(data: bytes) -> dict[str, object]:
    return {
        "payloads": [{
            "metadata": {"encoding": "anNvbi9wbGFpbg=="},
            "data": base64.b64encode(data).decode(),
        }],
    }


def cut_history(run_id: str = "run-1") -> dict[str, object]:
    operation_id = CHECK._operation_id()
    order = CHECK._order_bytes()
    payment = b'{"order_id":"order-1","amount_cents":4200,"operation_id":"' + operation_id.encode() + b'"}'
    return {"events": [
        {
            "eventId": "1", "eventTime": "2026-01-01T00:00:00Z",
            "eventType": "EVENT_TYPE_WORKFLOW_EXECUTION_STARTED", "taskId": "1",
            "workflowExecutionStartedEventAttributes": {
                "workflowType": {"name": "FoodOrderAutoUpgrade"},
                "taskQueue": {"name": CHECK.TASK_QUEUE, "kind": "TASK_QUEUE_KIND_NORMAL"},
                "input": payload(order), "workflowExecutionTimeout": "0s", "workflowRunTimeout": "0s",
                "workflowTaskTimeout": "10s", "originalExecutionRunId": run_id,
                "identity": "safe-change-temporal-starter", "firstExecutionRunId": run_id,
                "attempt": 1, "firstWorkflowTaskBackoff": "0s", "header": {},
                "workflowId": CHECK.WORKFLOW_ID,
            },
        },
        {
            "eventId": "2", "eventTime": "2026-01-01T00:00:01Z",
            "eventType": "EVENT_TYPE_WORKFLOW_TASK_SCHEDULED", "taskId": "2",
            "workflowTaskScheduledEventAttributes": {
                "taskQueue": {"name": CHECK.TASK_QUEUE, "kind": "TASK_QUEUE_KIND_NORMAL"},
                "startToCloseTimeout": "10s", "attempt": 1,
            },
        },
        {
            "eventId": "3", "eventTime": "2026-01-01T00:00:02Z",
            "eventType": "EVENT_TYPE_WORKFLOW_TASK_STARTED", "taskId": "3",
            "workflowTaskStartedEventAttributes": {
                "scheduledEventId": "2", "identity": CHECK.V1_IDENTITY,
                "requestId": "request-1", "historySizeBytes": "397",
            },
        },
        {
            "eventId": "4", "eventTime": "2026-01-01T00:00:03Z",
            "eventType": "EVENT_TYPE_WORKFLOW_TASK_COMPLETED", "taskId": "4",
            "workflowTaskCompletedEventAttributes": {
                "scheduledEventId": "2", "startedEventId": "3", "identity": CHECK.V1_IDENTITY,
                "workerVersion": {"buildId": CHECK.V1_BUILD, "useVersioning": True},
                "sdkMetadata": {"langUsedFlags": [3], "sdkName": "temporal-go", "sdkVersion": "1.47.0"},
                "meteringMetadata": {}, "versioningBehavior": "VERSIONING_BEHAVIOR_AUTO_UPGRADE",
                "workerDeploymentName": CHECK.DEPLOYMENT,
                "deploymentVersion": {"buildId": CHECK.V1_BUILD, "deploymentName": CHECK.DEPLOYMENT},
            },
        },
        {
            "eventId": "5", "eventTime": "2026-01-01T00:00:04Z",
            "eventType": "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED", "taskId": "5",
            "activityTaskScheduledEventAttributes": {
                "activityId": "5", "activityType": {"name": "ChargePayment"},
                "taskQueue": {"name": CHECK.TASK_QUEUE, "kind": "TASK_QUEUE_KIND_NORMAL"},
                "header": {}, "input": payload(payment), "scheduleToCloseTimeout": "0s",
                "scheduleToStartTimeout": "0s", "startToCloseTimeout": "30s", "heartbeatTimeout": "0s",
                "workflowTaskCompletedEventId": "4",
                "retryPolicy": {
                    "initialInterval": "1s", "backoffCoefficient": 2,
                    "maximumInterval": "100s", "maximumAttempts": 1,
                },
                "useWorkflowBuildId": True,
            },
        },
    ]}


def cut_describe(run_id: str = "run-1") -> dict[str, object]:
    return {
        "workflowExecutionInfo": {
            "execution": {"workflowId": CHECK.WORKFLOW_ID, "runId": run_id},
            "type": {"name": "FoodOrderAutoUpgrade"},
            "status": "WORKFLOW_EXECUTION_STATUS_RUNNING", "taskQueue": CHECK.TASK_QUEUE,
            "workerDeploymentName": CHECK.DEPLOYMENT,
            "mostRecentWorkerVersionStamp": {"buildId": CHECK.V1_BUILD, "useVersioning": True},
            "versioningInfo": {
                "behavior": "VERSIONING_BEHAVIOR_AUTO_UPGRADE",
                "version": f"{CHECK.DEPLOYMENT}.{CHECK.V1_BUILD}",
                "deploymentVersion": {"buildId": CHECK.V1_BUILD, "deploymentName": CHECK.DEPLOYMENT},
                "revisionNumber": "1",
            },
        },
        "pendingActivities": [{
            "activityId": "5", "activityType": {"name": "ChargePayment"},
            "state": "PENDING_ACTIVITY_STATE_STARTED", "lastStartedTime": "time-1",
            "attempt": 1, "maximumAttempts": 1, "scheduledTime": "time-0",
            "lastWorkerIdentity": CHECK.V1_IDENTITY,
            "lastWorkerDeploymentVersion": f"{CHECK.DEPLOYMENT}.{CHECK.V1_BUILD}",
            "lastDeploymentVersion": {"buildId": CHECK.V1_BUILD, "deploymentName": CHECK.DEPLOYMENT},
            "activityOptions": {
                "taskQueue": {"name": CHECK.TASK_QUEUE, "normalName": CHECK.TASK_QUEUE},
                "scheduleToCloseTimeout": "0s", "scheduleToStartTimeout": "0s",
                "startToCloseTimeout": "30s", "heartbeatTimeout": "0s",
                "retryPolicy": {
                    "initialInterval": "1s", "backoffCoefficient": 2,
                    "maximumInterval": "100s", "maximumAttempts": 1,
                },
            },
        }],
    }


class PairCheckerTests(unittest.TestCase):
    def write_json(self, directory: Path, name: str, value: object) -> None:
        (directory / name).write_text(json.dumps(value, sort_keys=True))

    def test_supported_frozen_build_profiles_are_exact(self) -> None:
        self.assertEqual(
            CHECK.FROZEN_BUILD_PROFILES,
            {
                CHECK.FROZEN_FULL_BUILD_SHA256: {
                    "name": "step-0016-full-food-order",
                    "keys": CHECK.BUILD_KEYS,
                    "git_revision": CHECK.FROZEN_GIT_REVISION,
                    "source_sha256": CHECK.FROZEN_FULL_SOURCE_SHA256,
                    "runtime_source_sha256": CHECK.FROZEN_RUNTIME_SOURCE_SHA256,
                },
            },
        )

    def test_rejects_unsupported_frozen_build_profile(self) -> None:
        with self.assertRaisesRegex(CHECK.EvidenceError, "unsupported frozen Temporal build profile"):
            CHECK._frozen_build_profile(b"unsupported\n", {})

    def test_commit_validation_uses_recorded_object_not_head(self) -> None:
        completed = subprocess.CompletedProcess(args=[], returncode=0)
        with mock.patch.object(CHECK.subprocess, "run", return_value=completed) as run:
            CHECK._require_commit_object(Path("/repo"), CHECK.FROZEN_GIT_REVISION)
        run.assert_called_once_with(
            [
                "git", "-C", "/repo", "cat-file", "-e",
                f"{CHECK.FROZEN_GIT_REVISION}^{{commit}}",
            ],
            check=False, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )

    def test_rejects_missing_recorded_commit_object(self) -> None:
        completed = subprocess.CompletedProcess(args=[], returncode=1)
        with mock.patch.object(CHECK.subprocess, "run", return_value=completed):
            with self.assertRaisesRegex(CHECK.EvidenceError, "commit object is absent"):
                CHECK._require_commit_object(Path("/repo"), CHECK.FROZEN_GIT_REVISION)

    def test_cut_history_accepts_exact_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            value = cut_history()
            self.write_json(root, "cut-show-before.json", value)
            self.write_json(root, "cut-show-after.json", value)
            projection, operation_id = CHECK._check_cut_history(root, "run-1")
            self.assertEqual(operation_id, CHECK._operation_id())
            self.assertEqual(len(projection["events"]), 5)

    def test_rejects_tampered_payment_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            value = cut_history()
            value["events"][4]["activityTaskScheduledEventAttributes"]["input"] = payload(b'{"amount_cents":1}')
            self.write_json(root, "cut-show-before.json", value)
            self.write_json(root, "cut-show-after.json", value)
            with self.assertRaisesRegex(CHECK.EvidenceError, "Payment input bytes differ"):
                CHECK._check_cut_history(root, "run-1")

    def test_rejects_unstable_cut_double_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_json(root, "cut-show-before.json", cut_history())
            changed = cut_history()
            changed["events"][4]["eventTime"] = "later"
            self.write_json(root, "cut-show-after.json", changed)
            with self.assertRaisesRegex(CHECK.EvidenceError, "double-read is unstable"):
                CHECK._check_cut_history(root, "run-1")

    def test_allowed_ids_normalize_but_semantics_do_not(self) -> None:
        first = cut_history("run-a")
        second = cut_history("run-b")
        for event in second["events"]:
            event["eventTime"] = "different"
            event["taskId"] = str(int(event["eventId"]) + 100)
        second["events"][2]["workflowTaskStartedEventAttributes"]["requestId"] = "different"
        second["events"][2]["workflowTaskStartedEventAttributes"]["historySizeBytes"] = "999"
        self.assertEqual(CHECK._normalize_history(first, "run-a"), CHECK._normalize_history(second, "run-b"))
        second["events"][4]["activityTaskScheduledEventAttributes"]["activityType"]["name"] = "Other"
        self.assertNotEqual(CHECK._normalize_history(first, "run-a"), CHECK._normalize_history(second, "run-b"))

    def test_rejects_pending_state_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            value = cut_describe()
            value["pendingActivities"][0]["state"] = "PENDING_ACTIVITY_STATE_SCHEDULED"
            self.write_json(root, "cut-describe.json", value)
            with self.assertRaisesRegex(CHECK.EvidenceError, "pending Payment state/version differs"):
                CHECK._check_cut_describe(root, "run-1")

    def make_provider(self, root: Path, case_name: str, mode: str = "auto_upgrade") -> None:
        commits = 0 if case_name == "h0" else 1
        stats = {"deliveries": 1, "commits": commits, "paths": {"/v1/charge": 1}}
        for name in ("payment-cut-stats.json", "payment-before-v2-stats.json", "payment-final-stats.json"):
            self.write_json(root, name, stats)
        completion_expected = mode == "manual_branch" and case_name == "h1"
        self.write_json(root, "completion-final-stats.json", {
            "deliveries": 1 if completion_expected else 0,
            "commits": 1 if completion_expected else 0,
            "paths": {"/v1/complete": 1} if completion_expected else {},
        })
        (root / "completion-cut.history").write_bytes(b"")
        completion = b""
        if completion_expected:
            record = CHECK._expected_provider_record(
                CHECK._completion_operation_id(), "/v1/complete", "temporal-completion",
            )
            completion = json.dumps(record, separators=(",", ":")).encode() + b"\n"
        (root / "completion-final.history").write_bytes(completion)
        payment = b""
        if case_name == "h1":
            operation_id = CHECK._operation_id()
            body = b'{"order_id":"order-1","amount_cents":4200}'
            record = {
                "operation_id": operation_id,
                "request_hash": sha256(b"POST\0/v1/charge\0" + body).hexdigest(),
                "result_hash": sha256(b"charged\0" + operation_id.encode() + b"\0" + b"1").hexdigest(),
                "remote_reference": f"temporal-payment/{operation_id}/commit-1",
                "path": "/v1/charge",
            }
            payment = json.dumps(record, separators=(",", ":")).encode() + b"\n"
        (root / "payment-cut.history").write_bytes(payment)
        (root / "payment-final.history").write_bytes(payment)

    def test_provider_accepts_exact_external_fact_split(self) -> None:
        for case_name in ("h0", "h1"):
            with self.subTest(case=case_name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self.make_provider(root, case_name)
                CHECK._check_provider(root, case_name, CHECK._operation_id())

    def test_provider_accepts_manual_completion_split(self) -> None:
        for case_name in ("h0", "h1"):
            with self.subTest(case=case_name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self.make_provider(root, case_name, "manual_branch")
                facts = CHECK._check_provider(
                    root, case_name, CHECK._operation_id(), "manual_branch",
                )
                self.assertEqual(facts["completion"] is not None, case_name == "h1")

    def test_rejects_tampered_provider_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_provider(root, "h1")
            record = json.loads((root / "payment-final.history").read_bytes())
            record["result_hash"] = "0" * 64
            changed = json.dumps(record, separators=(",", ":")).encode() + b"\n"
            (root / "payment-cut.history").write_bytes(changed)
            (root / "payment-final.history").write_bytes(changed)
            with self.assertRaisesRegex(CHECK.EvidenceError, "payment record differs"):
                CHECK._check_provider(root, "h1", CHECK._operation_id())

    def worker_inspect(self, image: str = "sha256:" + "1" * 64) -> list[dict[str, object]]:
        return [{
            "Image": image,
            "Config": {
                "Image": image,
                "Labels": {
                    "com.docker.compose.service": "worker-v2",
                    "io.safe-change.source.sha256": "2" * 64,
                    "io.safe-change.build.target": "worker_v2",
                    "io.safe-change.worker.build-id": CHECK.V2_BUILD,
                    "org.opencontainers.image.revision": "4" * 40,
                },
            },
            "State": {"Running": True},
        }]

    def test_rejects_tampered_worker_image(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "v2-running-inspect.json"
            self.write_json(path.parent, path.name, self.worker_inspect("sha256:" + "3" * 64))
            with self.assertRaisesRegex(CHECK.EvidenceError, "image/state binding differs"):
                CHECK._check_worker_inspect(
                    path, "sha256:" + "1" * 64, "worker-v2", True,
                    "2" * 64, "4" * 40, CHECK.V2_BUILD,
                )

    def make_final(
        self, root: Path, cause: str = CHECK.NONDETERMINISM, mode: str = "auto_upgrade",
    ) -> None:
        pre_events = [{"eventId": str(index), "eventType": event_type} for index, event_type in enumerate(CHECK.EXPECTED_PRE_V2_TYPES, 1)]
        pre_events[4]["activityTaskScheduledEventAttributes"] = {"activityType": {"name": "ChargePayment"}}
        self.write_json(root, "pre-v2-history.json", {"events": pre_events})
        final_events = copy.deepcopy(pre_events)
        for event_id, signal_name in enumerate(CHECK.BUSINESS_SIGNALS, 9):
            signal_input = (
                payload(b'{"delivery_id":"delivery-order-1","driver_id":"driver-1"}')
                if signal_name == "driver_selected" else {}
            )
            final_events.append({
                "eventId": str(event_id), "eventType": "EVENT_TYPE_WORKFLOW_EXECUTION_SIGNALED",
                "workflowExecutionSignaledEventAttributes": {
                    "signalName": signal_name, "input": signal_input, "identity": CHECK.SIGNAL_IDENTITY,
                },
            })
        if mode == "auto_upgrade":
            final_events.extend([{
                "eventId": "13", "eventType": "EVENT_TYPE_WORKFLOW_TASK_STARTED",
                "workflowTaskStartedEventAttributes": {"identity": CHECK.V2_IDENTITY},
            },
            {
                "eventId": "14", "eventType": "EVENT_TYPE_WORKFLOW_TASK_FAILED",
                "workflowTaskFailedEventAttributes": {
                    "cause": cause, "identity": CHECK.V2_IDENTITY,
                    "failure": {"message": CHECK.NONDETERMINISM_MESSAGE, "source": "GoSDK"},
                },
            }])
        else:
            final_events.extend([{
                "eventId": "13", "eventType": "EVENT_TYPE_WORKFLOW_TASK_TIMED_OUT",
                "workflowTaskTimedOutEventAttributes": {
                    "scheduledEventId": "8", "timeoutType": "TIMEOUT_TYPE_SCHEDULE_TO_START",
                },
            }, {
                "eventId": "14", "eventType": "EVENT_TYPE_WORKFLOW_TASK_SCHEDULED",
                "workflowTaskScheduledEventAttributes": {
                    "taskQueue": {"name": CHECK.TASK_QUEUE, "kind": "TASK_QUEUE_KIND_NORMAL"},
                    "startToCloseTimeout": "10s", "attempt": 1,
                },
            }])
        self.write_json(root, "final-history.json", {"events": final_events})
        versioning_info = {
            "behavior": "VERSIONING_BEHAVIOR_AUTO_UPGRADE",
            "deploymentVersion": {"buildId": CHECK.V1_BUILD, "deploymentName": CHECK.DEPLOYMENT},
            "versionTransition": {
                "deploymentVersion": {"buildId": CHECK.V2_BUILD, "deploymentName": CHECK.DEPLOYMENT},
            },
        }
        final_describe = {
            "workflowExecutionInfo": {
                "execution": {"workflowId": CHECK.WORKFLOW_ID, "runId": "run-1"},
                "status": "WORKFLOW_EXECUTION_STATUS_RUNNING",
                "type": {"name": CHECK._workflow_name(mode)},
                "taskQueue": CHECK.TASK_QUEUE,
                "workerDeploymentName": CHECK.DEPLOYMENT,
                "mostRecentWorkerVersionStamp": {"buildId": CHECK.V1_BUILD, "useVersioning": True},
                "versioningInfo": versioning_info,
            },
        }
        if mode == "pinned":
            versioning_info.clear()
            versioning_info.update({
                "behavior": "VERSIONING_BEHAVIOR_PINNED",
                "version": f"{CHECK.DEPLOYMENT}.{CHECK.V1_BUILD}",
                "deploymentVersion": {"buildId": CHECK.V1_BUILD, "deploymentName": CHECK.DEPLOYMENT},
                "revisionNumber": "1",
            })
            final_describe["pendingWorkflowTask"] = {
                "state": "PENDING_WORKFLOW_TASK_STATE_SCHEDULED",
                "scheduledTime": "time-2", "originalScheduledTime": "time-2", "attempt": 1,
            }
        self.write_json(root, "final-describe.json", final_describe)

    def test_final_accepts_observed_nondeterminism(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_final(root)
            self.assertEqual(CHECK._check_final(root, "run-1", {}), 1)

    def test_rejects_tampered_failure_cause(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_final(root, "WORKFLOW_TASK_FAILED_CAUSE_WORKFLOW_WORKER_UNHANDLED_FAILURE")
            with self.assertRaisesRegex(CHECK.EvidenceError, "expected replay nondeterminism"):
                CHECK._check_final(root, "run-1", {})

    def test_final_accepts_observed_pinned_stranding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_final(root, mode="pinned")
            self.assertEqual(CHECK._check_final(root, "run-1", {}, "pinned"), 0)

    def test_rejects_pinned_execution_on_v2(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_final(root, mode="pinned")
            value = json.loads((root / "final-history.json").read_bytes())
            value["events"].append({
                "eventId": "15", "eventType": "EVENT_TYPE_WORKFLOW_TASK_STARTED",
                "workflowTaskStartedEventAttributes": {"identity": CHECK.V2_IDENTITY},
            })
            self.write_json(root, "final-history.json", value)
            with self.assertRaisesRegex(CHECK.EvidenceError, "ran after its v1 worker stopped"):
                CHECK._check_final(root, "run-1", {}, "pinned")

    def test_rejects_forged_pinned_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_final(root, mode="pinned")
            value = json.loads((root / "final-history.json").read_bytes())
            value["events"][12]["workflowTaskTimedOutEventAttributes"]["scheduledEventId"] = "99"
            self.write_json(root, "final-history.json", value)
            with self.assertRaisesRegex(CHECK.EvidenceError, "timeout differs"):
                CHECK._check_final(root, "run-1", {}, "pinned")

    def test_rejects_manual_query_outcome_mutation(self) -> None:
        expected = CHECK._manual_query_observation("h0", CHECK._operation_id(), None)
        CHECK._check_manual_query_result(
            payload(json.dumps(expected, separators=(",", ":")).encode()),
            "h0", CHECK._operation_id(), None,
        )
        expected["outcome"] = "succeeded"
        with self.assertRaisesRegex(CHECK.EvidenceError, "does not match the payment provider fact"):
            CHECK._check_manual_query_result(
                payload(json.dumps(expected, separators=(",", ":")).encode()),
                "h0", CHECK._operation_id(), None,
            )

    def test_rejects_manual_query_hash_mutation(self) -> None:
        payment_fact = CHECK._expected_provider_record(
            CHECK._operation_id(), "/v1/charge", "temporal-payment",
        )
        expected = CHECK._manual_query_observation("h1", CHECK._operation_id(), payment_fact)
        CHECK._check_manual_query_result(
            payload(json.dumps(expected, separators=(",", ":")).encode()),
            "h1", CHECK._operation_id(), payment_fact,
        )
        expected["request_hash"] = "0" * 64
        with self.assertRaisesRegex(CHECK.EvidenceError, "does not match the payment provider fact"):
            CHECK._check_manual_query_result(
                payload(json.dumps(expected, separators=(",", ":")).encode()),
                "h1", CHECK._operation_id(), payment_fact,
            )

    def manual_h0_terminal(self) -> dict[str, object]:
        return {
            "eventType": "EVENT_TYPE_WORKFLOW_EXECUTION_FAILED",
            "workflowExecutionFailedEventAttributes": {
                "failure": {
                    "message": "manual payment reconciliation was inconclusive",
                    "source": "GoSDK",
                    "applicationFailureInfo": {
                        "type": "ManualPaymentReconciliationFailed", "nonRetryable": True,
                    },
                },
                "retryState": "RETRY_STATE_RETRY_POLICY_NOT_SET",
                "workflowTaskCompletedEventId": "17",
            },
        }

    def manual_h1_terminal(self) -> dict[str, object]:
        result = json.dumps(CHECK._manual_order_result(), separators=(",", ":")).encode()
        return {
            "eventType": "EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED",
            "workflowExecutionCompletedEventAttributes": {
                "result": payload(result), "workflowTaskCompletedEventId": "23",
            },
        }

    def test_rejects_manual_h0_terminal_behavior_mutation(self) -> None:
        event = self.manual_h0_terminal()
        CHECK._check_manual_terminal_event(event, "h0")
        event["workflowExecutionFailedEventAttributes"]["failure"]["applicationFailureInfo"]["nonRetryable"] = False
        with self.assertRaisesRegex(CHECK.EvidenceError, "exact nonretryable reconciliation failure"):
            CHECK._check_manual_terminal_event(event, "h0")

    def test_rejects_manual_h1_terminal_behavior_mutation(self) -> None:
        event = self.manual_h1_terminal()
        CHECK._check_manual_terminal_event(event, "h1")
        changed = CHECK._manual_order_result()
        changed["phase"] = "PAYMENT_COMMITTED"
        event["workflowExecutionCompletedEventAttributes"]["result"] = payload(
            json.dumps(changed, separators=(",", ":")).encode(),
        )
        with self.assertRaisesRegex(CHECK.EvidenceError, "terminal result differs"):
            CHECK._check_manual_terminal_event(event, "h1")

    def test_rejects_checksum_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in CHECK.REQUIRED_FILES - {"SHA256SUMS"}:
                (root / name).write_bytes(b"")
            lines = []
            for path in sorted(root.iterdir()):
                lines.append(f"{sha256(path.read_bytes()).hexdigest()}  ./{path.name}\n")
            (root / "SHA256SUMS").write_text("".join(lines))
            CHECK._verify_checksums(root)
            (root / "observed.json").write_bytes(b"tampered")
            with self.assertRaisesRegex(CHECK.EvidenceError, "checksum mismatch: observed.json"):
                CHECK._verify_checksums(root)


if __name__ == "__main__":
    unittest.main()
