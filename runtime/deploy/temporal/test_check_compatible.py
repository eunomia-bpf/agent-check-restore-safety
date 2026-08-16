#!/usr/bin/env python3
"""Semantic mutation tests for the raw Temporal compatible-control checker."""

from __future__ import annotations

import base64
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
DEFAULT_EVIDENCE = (
    REPO_ROOT / "docs/tmp/bootstrap/step-0016-20260815T153407Z/"
    "experiment-restate-food-ordering/raw/preflight-compatible/temporal"
)
EVIDENCE = Path(os.environ.get("TEMPORAL_COMPATIBLE_EVIDENCE", DEFAULT_EVIDENCE))
SPEC = importlib.util.spec_from_file_location("temporal_compatible_check", HERE / "check-compatible.py")
assert SPEC is not None and SPEC.loader is not None
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


def read_json(results: Path, name: str) -> object:
    return json.loads((results / name).read_bytes())


def write_json(results: Path, name: str, value: object) -> None:
    (results / name).write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def unique_event(value: dict[str, object], predicate, label: str) -> dict[str, object]:  # type: ignore[no-untyped-def]
    events = value.get("events")
    if not isinstance(events, list):
        raise AssertionError("History events are absent")
    matches = [event for event in events if isinstance(event, dict) and predicate(event)]
    if len(matches) != 1:
        raise AssertionError(f"expected exactly one {label}, found {len(matches)}")
    return matches[0]


def activity_schedule(value: dict[str, object], activity_type: str) -> dict[str, object]:
    return unique_event(
        value,
        lambda event: event.get("eventType") == "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED"
        and event.get("activityTaskScheduledEventAttributes", {}).get(
            "activityType", {}
        ).get("name") == activity_type,
        activity_type + " schedule",
    )


def target_delivery_workflow_task(
    value: dict[str, object],
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    delivery = activity_schedule(value, "ScheduleDelivery")
    completed_id = delivery["activityTaskScheduledEventAttributes"]["workflowTaskCompletedEventId"]  # type: ignore[index]
    completed = unique_event(
        value,
        lambda event: event.get("eventId") == completed_id
        and event.get("eventType") == "EVENT_TYPE_WORKFLOW_TASK_COMPLETED"
        and event.get("workflowTaskCompletedEventAttributes", {}).get("identity")
        == CHECK.TARGET_IDENTITY,
        "target Workflow task completion that scheduled delivery",
    )
    completed_attributes = completed["workflowTaskCompletedEventAttributes"]  # type: ignore[index]
    started_id = completed_attributes["startedEventId"]  # type: ignore[index]
    scheduled_id = completed_attributes["scheduledEventId"]  # type: ignore[index]
    started = unique_event(
        value,
        lambda event: event.get("eventId") == started_id
        and event.get("eventType") == "EVENT_TYPE_WORKFLOW_TASK_STARTED"
        and event.get("workflowTaskStartedEventAttributes", {}).get("identity")
        == CHECK.TARGET_IDENTITY,
        "target Workflow task start that scheduled delivery",
    )
    scheduled = unique_event(
        value,
        lambda event: event.get("eventId") == scheduled_id
        and event.get("eventType") == "EVENT_TYPE_WORKFLOW_TASK_SCHEDULED",
        "Workflow task schedule that scheduled delivery",
    )
    return scheduled, started, completed


def rehash(results: Path) -> None:
    lines = []
    for path in sorted(results.iterdir()):
        if path.name == "SHA256SUMS":
            continue
        lines.append(f"{sha256(path.read_bytes()).hexdigest()}  ./{path.name}\n")
    (results / "SHA256SUMS").write_text("".join(lines))


class CompatibleCheckerMutationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not (EVIDENCE / "results/SHA256SUMS").is_file():
            raise unittest.SkipTest("frozen compatible preflight evidence is absent")

    def fixture(self, temporary: str) -> tuple[Path, Path]:
        root = Path(temporary) / "evidence"
        results = root / "results"
        shutil.copytree(EVIDENCE / "results", results)
        return root, results

    def assert_rejected(self, mutate) -> None:  # type: ignore[no-untyped-def]
        with tempfile.TemporaryDirectory() as temporary:
            root, results = self.fixture(temporary)
            mutate(results)
            rehash(results)
            with self.assertRaises(CHECK.EvidenceError):
                CHECK.check_evidence(root)

    def test_accepts_frozen_raw_evidence(self) -> None:
        checked = CHECK.check_evidence(EVIDENCE)
        self.assertTrue(checked["valid"])
        self.assertEqual(checked["closure_version"], "compatible-v2")

    def test_commit_validation_uses_recorded_object_not_head(self) -> None:
        completed = subprocess.CompletedProcess(args=[], returncode=0)
        with mock.patch.object(CHECK.subprocess, "run", return_value=completed) as run:
            self.assertTrue(CHECK.check_evidence(EVIDENCE)["valid"])
        run.assert_called_once_with(
            [
                "git", "-C", str(REPO_ROOT), "cat-file", "-e",
                f"{CHECK.FROZEN_GIT_REVISION}^{{commit}}",
            ],
            check=False, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )

    def test_rejects_missing_recorded_commit_object(self) -> None:
        completed = subprocess.CompletedProcess(args=[], returncode=1)
        with mock.patch.object(CHECK.subprocess, "run", return_value=completed):
            with self.assertRaisesRegex(CHECK.EvidenceError, "commit object is absent"):
                CHECK.check_evidence(EVIDENCE)

    def test_rejects_unsupported_frozen_build_profile(self) -> None:
        def mutate(results: Path) -> None:
            path = results / "build.env"
            path.write_bytes(path.read_bytes() + b"# same claims, different archived bytes\n")
        self.assert_rejected(mutate)

    def test_rejects_unsupported_frozen_versions_profile(self) -> None:
        def mutate(results: Path) -> None:
            path = results / "versions.env"
            path.write_bytes(path.read_bytes() + b"# same claims, different archived bytes\n")
        self.assert_rejected(mutate)

    def test_rejects_archived_non_delta_source_mutation(self) -> None:
        def mutate(results: Path) -> None:
            path = results / "source-activities.go"
            path.write_bytes(path.read_bytes() + b"\n// fabricated archived source\n")
        self.assert_rejected(mutate)

    def test_observed_summary_is_not_an_oracle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, results = self.fixture(temporary)
            write_json(results, "observed.json", {
                "schema": 999, "final_status": "fabricated", "payment": {"deliveries": 99},
            })
            rehash(results)
            self.assertTrue(CHECK.check_evidence(root)["valid"])

    def test_invocation_summary_is_not_an_oracle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, results = self.fixture(temporary)
            write_json(results, "invocation.json", {"fabricated": True})
            rehash(results)
            self.assertTrue(CHECK.check_evidence(root)["valid"])

    def test_rejects_payment_redispatch(self) -> None:
        def mutate(results: Path) -> None:
            value = read_json(results, "payment-final-stats.json")
            value["deliveries"] = 2
            value["paths"]["/v1/charge"] = 2
            write_json(results, "payment-final-stats.json", value)
        self.assert_rejected(mutate)

    def test_rejects_second_payment_record(self) -> None:
        def mutate(results: Path) -> None:
            path = results / "payment-final.history"
            path.write_bytes(path.read_bytes() * 2)
        self.assert_rejected(mutate)

    def test_rejects_completion_marker_mutation(self) -> None:
        def mutate(results: Path) -> None:
            value = read_json(results, "final-history.json")
            completion = activity_schedule(value, "CompleteOrder")
            payload = completion["activityTaskScheduledEventAttributes"]["input"]["payloads"][0]
            decoded = base64.b64decode(payload["data"])
            payload["data"] = base64.b64encode(decoded.replace(b"compatible-v2", b"fabricated-v2")).decode()
            write_json(results, "final-history.json", value)
        self.assert_rejected(mutate)

    def test_rejects_completion_provider_hash_mutation(self) -> None:
        def mutate(results: Path) -> None:
            path = results / "completion-final.history"
            value = json.loads(path.read_bytes())
            value["request_hash"] = "0" * 64
            path.write_text(json.dumps(value, separators=(",", ":")) + "\n")
        self.assert_rejected(mutate)

    def test_rejects_target_workflow_task_build_mutation(self) -> None:
        def mutate(results: Path) -> None:
            value = read_json(results, "final-history.json")
            _, _, completed = target_delivery_workflow_task(value)
            attrs = completed["workflowTaskCompletedEventAttributes"]
            attrs["workerVersion"]["buildId"] = "food-order-v2"
            attrs["deploymentVersion"]["buildId"] = "food-order-v2"
            write_json(results, "final-history.json", value)
        self.assert_rejected(mutate)

    def test_rejects_target_workflow_task_start_identity(self) -> None:
        def mutate(results: Path) -> None:
            value = read_json(results, "final-history.json")
            _, started, _ = target_delivery_workflow_task(value)
            started["workflowTaskStartedEventAttributes"]["identity"] = CHECK.V1_IDENTITY
            write_json(results, "final-history.json", value)
        self.assert_rejected(mutate)

    def test_rejects_sticky_queue_mutation(self) -> None:
        def mutate(results: Path) -> None:
            value = read_json(results, "final-history.json")
            scheduled, _, _ = target_delivery_workflow_task(value)
            scheduled["workflowTaskScheduledEventAttributes"]["taskQueue"]["normalName"] = "other"
            write_json(results, "final-history.json", value)
        self.assert_rejected(mutate)

    def test_rejects_workflow_task_failure(self) -> None:
        def mutate(results: Path) -> None:
            value = read_json(results, "final-history.json")
            terminal = unique_event(
                value,
                lambda event: event.get("eventType")
                == "EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED",
                "Workflow completion",
            )
            completed_id = terminal["workflowExecutionCompletedEventAttributes"]["workflowTaskCompletedEventId"]
            completed = unique_event(
                value,
                lambda event: event.get("eventId") == completed_id
                and event.get("eventType") == "EVENT_TYPE_WORKFLOW_TASK_COMPLETED"
                and event.get("workflowTaskCompletedEventAttributes", {}).get("identity")
                == CHECK.TARGET_IDENTITY,
                "target terminal Workflow task completion",
            )
            completed["eventType"] = "EVENT_TYPE_WORKFLOW_TASK_FAILED"
            write_json(results, "final-history.json", value)
        self.assert_rejected(mutate)

    def test_rejects_cut_prefix_mutation(self) -> None:
        def mutate(results: Path) -> None:
            value = read_json(results, "cut-history-before.json")
            timer = unique_event(
                value,
                lambda event: event.get("eventType") == "EVENT_TYPE_TIMER_STARTED"
                and event.get("timerStartedEventAttributes", {}).get("startToFireTimeout")
                == "0.025s",
                "preparation timer start",
            )
            completed_id = timer["timerStartedEventAttributes"]["workflowTaskCompletedEventId"]
            completed = unique_event(
                value,
                lambda event: event.get("eventId") == completed_id
                and event.get("eventType") == "EVENT_TYPE_WORKFLOW_TASK_COMPLETED"
                and event.get("workflowTaskCompletedEventAttributes", {}).get("identity")
                == CHECK.V1_IDENTITY,
                "v1 Workflow task completion that started preparation timer",
            )
            completed["workflowTaskCompletedEventAttributes"]["identity"] = CHECK.TARGET_IDENTITY
            write_json(results, "cut-history-before.json", value)
            write_json(results, "cut-history-after.json", value)
        self.assert_rejected(mutate)

    def test_rejects_v1_not_removed(self) -> None:
        def mutate(results: Path) -> None:
            (results / "v1-removed-inspect-status.txt").write_text("0\n")
        self.assert_rejected(mutate)

    def test_rejects_v1_in_pre_target_snapshot(self) -> None:
        def mutate(results: Path) -> None:
            before = read_json(results, "containers-before-target.json")
            cut = read_json(results, "containers-cut.json")
            before.append(next(item for item in cut if item["Config"]["Labels"]["com.docker.compose.service"] == "worker-v1"))
            write_json(results, "containers-before-target.json", before)
        self.assert_rejected(mutate)

    def test_rejects_main_v2_as_final_worker(self) -> None:
        def mutate(results: Path) -> None:
            value = read_json(results, "containers-final.json")
            worker = next(item for item in value if item["Config"]["Labels"]["com.docker.compose.service"] == "worker-compatible-v2")
            worker["Config"]["Labels"]["io.safe-change.worker.build-id"] = "food-order-v2"
            write_json(results, "containers-final.json", value)
        self.assert_rejected(mutate)

    def test_rejects_target_entrypoint_override(self) -> None:
        def mutate(results: Path) -> None:
            value = read_json(results, "containers-final.json")
            worker = next(item for item in value if item["Config"]["Labels"]["com.docker.compose.service"] == "worker-compatible-v2")
            worker["Config"]["Entrypoint"] = ["/bin/true"]
            write_json(results, "containers-final.json", value)
        self.assert_rejected(mutate)

    def test_rejects_target_root_user(self) -> None:
        def mutate(results: Path) -> None:
            value = read_json(results, "containers-final.json")
            worker = next(item for item in value if item["Config"]["Labels"]["com.docker.compose.service"] == "worker-compatible-v2")
            worker["Config"]["User"] = "0:0"
            write_json(results, "containers-final.json", value)
        self.assert_rejected(mutate)

    def test_rejects_ambiguous_target_endpoint(self) -> None:
        def mutate(results: Path) -> None:
            value = read_json(results, "containers-final.json")
            worker = next(item for item in value if item["Config"]["Labels"]["com.docker.compose.service"] == "worker-compatible-v2")
            worker["Config"]["Env"].append("TEMPORAL_ADDRESS=attacker:7233")
            write_json(results, "containers-final.json", value)
        self.assert_rejected(mutate)

    def test_rejects_provider_entrypoint_override(self) -> None:
        def mutate(results: Path) -> None:
            value = read_json(results, "containers-final.json")
            payment = next(item for item in value if item["Config"]["Labels"]["com.docker.compose.service"] == "payment")
            payment["Config"]["Entrypoint"] = ["/bin/true"]
            write_json(results, "containers-final.json", value)
        self.assert_rejected(mutate)

    def test_rejects_target_image_substitution(self) -> None:
        def mutate(results: Path) -> None:
            value = read_json(results, "compatible-running-inspect.json")
            value[0]["Image"] = "sha256:" + "0" * 64
            write_json(results, "compatible-running-inspect.json", value)
        self.assert_rejected(mutate)

    def test_rejects_target_image_sdk_label_mutation(self) -> None:
        def mutate(results: Path) -> None:
            value = read_json(results, "compatible-image-inspect.json")
            value[0]["Config"]["Labels"]["io.safe-change.temporal.go-sdk.version"] = "v0.0.0"
            write_json(results, "compatible-image-inspect.json", value)
        self.assert_rejected(mutate)

    def test_rejects_extracted_binary_hash_mutation(self) -> None:
        def mutate(results: Path) -> None:
            path = results / "build.env"
            text = path.read_text()
            old = next(line for line in text.splitlines() if line.startswith("WORKER_COMPATIBLE_V2_BINARY_SHA256="))
            path.write_text(text.replace(old, "WORKER_COMPATIBLE_V2_BINARY_SHA256=" + "0" * 64))
        self.assert_rejected(mutate)

    def test_rejects_co_mutated_binary_hash_claims(self) -> None:
        def mutate(results: Path) -> None:
            for name in ("build.env", "binary-verification.env"):
                path = results / name
                text = path.read_text()
                old = next(line for line in text.splitlines() if line.startswith("WORKER_COMPATIBLE_V2_BINARY_SHA256="))
                path.write_text(text.replace(old, "WORKER_COMPATIBLE_V2_BINARY_SHA256=" + "0" * 64))
        self.assert_rejected(mutate)

    def test_rejects_source_delta_expansion(self) -> None:
        def mutate(results: Path) -> None:
            path = results / "source-variant-compatible-v2.go"
            path.write_bytes(path.read_bytes() + b"\n// unrelated target-only change\n")
        self.assert_rejected(mutate)

    def test_rejects_route_rollback(self) -> None:
        def mutate(results: Path) -> None:
            value = read_json(results, "deployment-compatible-current.json")
            value["routingConfig"]["currentVersionBuildID"] = CHECK.V1_BUILD
            write_json(results, "deployment-compatible-current.json", value)
        self.assert_rejected(mutate)

    def test_rejects_late_v1_current_transition(self) -> None:
        def mutate(results: Path) -> None:
            value = read_json(results, "deployment-v1-current.json")
            value["routingConfig"]["currentVersionChangedTime"] = "2099-01-01T00:00:00Z"
            write_json(results, "deployment-v1-current.json", value)
        self.assert_rejected(mutate)

    def test_rejects_missing_final_deployment_versions(self) -> None:
        def mutate(results: Path) -> None:
            value = read_json(results, "deployment-final.json")
            value["versionSummaries"] = []
            write_json(results, "deployment-final.json", value)
        self.assert_rejected(mutate)

    def test_rejects_fabricated_final_describe_result(self) -> None:
        def mutate(results: Path) -> None:
            value = read_json(results, "final-describe.json")
            value["result"]["phase"] = "FABRICATED"
            value["closeEvent"]["workflowExecutionCompletedEventAttributes"]["result"][0]["phase"] = "FABRICATED"
            write_json(results, "final-describe.json", value)
        self.assert_rejected(mutate)

    def test_rejects_temporal_command_mutation(self) -> None:
        def mutate(results: Path) -> None:
            value = read_json(results, "containers-final.json")
            temporal = next(item for item in value if item["Config"]["Labels"]["com.docker.compose.service"] == "temporal")
            temporal["Config"]["Cmd"] = []
            write_json(results, "containers-final.json", value)
        self.assert_rejected(mutate)

    def test_rejects_signal_before_target_current(self) -> None:
        def mutate(results: Path) -> None:
            value = read_json(results, "final-history.json")
            signal = unique_event(
                value,
                lambda event: event.get("eventType")
                == "EVENT_TYPE_WORKFLOW_EXECUTION_SIGNALED"
                and event.get("workflowExecutionSignaledEventAttributes", {}).get("signalName")
                == "preparation_finished",
                "preparation_finished signal",
            )
            signal["eventTime"] = "2020-01-01T00:00:00Z"
            write_json(results, "final-history.json", value)
        self.assert_rejected(mutate)

    def test_rejects_legacy_completion_body(self) -> None:
        def mutate(results: Path) -> None:
            path = results / "completion-final.history"
            value = json.loads(path.read_bytes())
            body = b'{"order_id":"order-1","amount_cents":4200}'
            value["request_hash"] = sha256(b"POST\0/v1/complete\0" + body).hexdigest()
            path.write_text(json.dumps(value, separators=(",", ":")) + "\n")
        self.assert_rejected(mutate)

    def test_rejects_final_query_from_v1(self) -> None:
        def mutate(results: Path) -> None:
            value = read_json(results, "final-query.json")
            value["queryResult"][0]["worker_build"] = CHECK.V1_BUILD
            write_json(results, "final-query.json", value)
        self.assert_rejected(mutate)

    def test_rejects_nonzero_runner_exit(self) -> None:
        def mutate(results: Path) -> None:
            (results / "exit-status.txt").write_text("1\n")
        self.assert_rejected(mutate)


if __name__ == "__main__":
    unittest.main()
