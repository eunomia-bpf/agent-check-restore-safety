#!/usr/bin/env python3
"""Independently check raw matched H0/H1 Temporal evidence."""

from __future__ import annotations

import argparse
import base64
import copy
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any


MAX_FILE_BYTES = 64 << 20
MAX_CASE_BYTES = 128 << 20
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")

WORKFLOW_ID = "temporal-matched-order-1"
ORDER_ID = "order-1"
PAYMENT_TOKEN = "payment-token-1"
AMOUNT_CENTS = 4200
TASK_QUEUE = "safe-change-food-orders"
DEPLOYMENT = "safe-change-food-order-worker"
V1_BUILD = "food-order-v1"
V2_BUILD = "food-order-v2"
V1_IDENTITY = "safe-change-food-order-v1-worker"
V2_IDENTITY = "safe-change-food-order-v2-worker"
SIGNAL_IDENTITY = "safe-change-harness"
NONDETERMINISM = "WORKFLOW_TASK_FAILED_CAUSE_NON_DETERMINISTIC_ERROR"
NONDETERMINISM_MESSAGE = (
    "[TMPRL1100] lookup failed for scheduledEventID to activityID: "
    "scheduleEventID: 5, activityID: 5"
)

EXPECTED_CUT_TYPES = [
    "EVENT_TYPE_WORKFLOW_EXECUTION_STARTED",
    "EVENT_TYPE_WORKFLOW_TASK_SCHEDULED",
    "EVENT_TYPE_WORKFLOW_TASK_STARTED",
    "EVENT_TYPE_WORKFLOW_TASK_COMPLETED",
    "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED",
]
EXPECTED_PRE_V2_TYPES = EXPECTED_CUT_TYPES + [
    "EVENT_TYPE_ACTIVITY_TASK_STARTED",
    "EVENT_TYPE_ACTIVITY_TASK_TIMED_OUT",
    "EVENT_TYPE_WORKFLOW_TASK_SCHEDULED",
]

REQUIRED_FILES = {
    "SHA256SUMS",
    "build.env",
    "completion-cut.history",
    "completion-final-stats.json",
    "completion-final.history",
    "compose-config.yaml",
    "compose-ps.txt",
    "compose.log",
    "containers-final.json",
    "cut-describe.json",
    "cut-show-after.json",
    "cut-show-before.json",
    "deployment-before-current.json",
    "deployment-v1-current.json",
    "deployment-v2-current.json",
    "exit-status.txt",
    "final-describe.json",
    "final-history.json",
    "observed.json",
    "payment-before-v2-stats.json",
    "payment-cut-stats.json",
    "payment-cut.history",
    "payment-final-stats.json",
    "payment-final.history",
    "pre-v2-history.json",
    "set-current-v1.json",
    "set-current-v2.json",
    "signal-complete.json",
    "start.json",
    "v1-activity-pollers.json",
    "v1-running-inspect.json",
    "v1-stopped-inspect.json",
    "v1-workflow-pollers.json",
    "v2-activity-pollers.json",
    "v2-running-inspect.json",
    "v2-workflow-pollers.json",
    "version-v1.json",
    "version-v2-before-current.json",
    "version-v2-current.json",
    "versions.env",
}

BUILD_KEYS = {
    "GIT_REVISION",
    "SOURCE_SHA256",
    "WORKER_V1_IMAGE",
    "WORKER_V1_ID",
    "WORKER_V1_BINARY_SHA256",
    "WORKER_V2_IMAGE",
    "WORKER_V2_ID",
    "WORKER_V2_BINARY_SHA256",
    "STARTER_IMAGE",
    "STARTER_ID",
    "STARTER_BINARY_SHA256",
    "RUNTIME_SOURCE_SHA256",
    "EFFECTS_IMAGE",
    "EFFECTS_ID",
    "EFFECTS_BINARY_SHA256",
}


class EvidenceError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceError(message)


def _object(value: Any, label: str) -> dict[str, Any]:
    _require(isinstance(value, dict), f"{label} must be an object")
    return value


def _array(value: Any, label: str) -> list[Any]:
    _require(isinstance(value, list), f"{label} must be an array")
    return value


def _results_dir(root: Path) -> Path:
    _require(not root.is_symlink(), "case root must not be a symlink")
    candidate = root / "results"
    results = candidate if candidate.is_dir() else root
    _require(results.is_dir() and not results.is_symlink(), "results directory is absent or unsafe")
    return results


def _read(path: Path) -> bytes:
    _require(path.exists(), f"missing evidence file: {path.name}")
    _require(path.is_file() and not path.is_symlink(), f"unsafe evidence file: {path.name}")
    size = path.stat().st_size
    _require(size <= MAX_FILE_BYTES, f"evidence file exceeds size limit: {path.name}")
    return path.read_bytes()


def _json(path: Path) -> dict[str, Any]:
    data = _read(path)
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvidenceError(f"{path.name} is not JSON") from error
    return _object(value, path.name)


def _verify_checksums(results: Path) -> None:
    items = list(results.iterdir())
    _require(all(item.is_file() and not item.is_symlink() for item in items), "results contains a non-regular entry")
    _require(sum(item.stat().st_size for item in items) <= MAX_CASE_BYTES, "case evidence exceeds size limit")
    actual_names = {item.name for item in items if item.name != "SHA256SUMS"}
    _require(REQUIRED_FILES <= {item.name for item in items}, "case evidence is incomplete")
    manifest = _read(results / "SHA256SUMS").decode("ascii").splitlines()
    declared: dict[str, str] = {}
    for line in manifest:
        parts = line.split("  ", 1)
        _require(len(parts) == 2 and HEX64.fullmatch(parts[0]) is not None, "invalid SHA256SUMS line")
        name = parts[1]
        _require(name.startswith("./") and "/" not in name[2:] and name[2:] != "SHA256SUMS", "unsafe SHA256SUMS path")
        name = name[2:]
        _require(name not in declared, "duplicate SHA256SUMS entry")
        declared[name] = parts[0]
    _require(set(declared) == actual_names, "SHA256SUMS does not cover the exact evidence set")
    for name, digest in declared.items():
        _require(sha256(_read(results / name)).hexdigest() == digest, f"checksum mismatch: {name}")


def _parse_env(data: bytes, label: str) -> dict[str, str]:
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError as error:
        raise EvidenceError(f"{label} is not ASCII") from error
    parsed: dict[str, str] = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        _require("=" in line, f"invalid {label} line")
        key, value = line.split("=", 1)
        _require(key not in parsed and re.fullmatch(r"[A-Z0-9_]+", key) is not None, f"invalid {label} key")
        parsed[key] = value
    return parsed


def _source_digest(files: list[Path], base: Path) -> str:
    stream = bytearray()
    for path in sorted(files):
        _require(path.is_file() and not path.is_symlink(), "source tree contains an unsafe entry")
        stream.extend(path.relative_to(base).as_posix().encode())
        stream.append(0)
        stream.extend(sha256(path.read_bytes()).hexdigest().encode())
        stream.extend(b"\n")
    return sha256(stream).hexdigest()


def _check_build(results: Path) -> tuple[bytes, bytes, dict[str, str]]:
    versions_data = _read(results / "versions.env")
    local_versions = Path(__file__).with_name("versions.env").read_bytes()
    _require(versions_data == local_versions, "versions.env differs from the checked harness")
    versions = _parse_env(versions_data, "versions.env")
    _require(versions.get("TEMPORAL_CLI_VERSION") == "1.8.2", "Temporal CLI version differs")
    _require(versions.get("TEMPORAL_SERVER_VERSION") == "1.31.2", "Temporal Server version differs")
    _require(versions.get("TEMPORAL_GO_SDK_VERSION") == "v1.47.0", "Temporal SDK version differs")
    _require(
        versions.get("TEMPORAL_IMAGE") ==
        "docker.io/temporalio/temporal:1.8.2@sha256:cf86707827fac99e4d1c4a47dc11b105382d796199c7bd41fb3213fb0471628e",
        "Temporal Server image differs",
    )

    build_data = _read(results / "build.env")
    build = _parse_env(build_data, "build.env")
    _require(set(build) == BUILD_KEYS, "build.env fields differ")
    _require(HEX40.fullmatch(build["GIT_REVISION"]) is not None, "build revision is invalid")
    for key in BUILD_KEYS:
        if key.endswith("_SHA256"):
            _require(HEX64.fullmatch(build[key]) is not None, f"{key} is not SHA-256")
        if key.endswith("_ID"):
            _require(IMAGE_ID.fullmatch(build[key]) is not None, f"{key} is not an image ID")
    _require(build["WORKER_V1_ID"] != build["WORKER_V2_ID"], "worker images are not distinct")
    _require("latest" not in build["WORKER_V1_IMAGE"] and "latest" not in build["WORKER_V2_IMAGE"], "latest image is forbidden")

    temporal_dir = Path(__file__).resolve().parent
    runtime_dir = temporal_dir.parents[1]
    app_files = [path for path in (temporal_dir / "app").rglob("*") if path.is_file()]
    _require(_source_digest(app_files, runtime_dir.parent) == build["SOURCE_SHA256"], "Temporal source hash differs")
    runtime_inputs = [runtime_dir / "go.mod", runtime_dir / "go.sum"]
    for directory in (runtime_dir / "cmd/payment", runtime_dir / "internal/kernel", runtime_dir / "internal/payment"):
        runtime_inputs.extend(path for path in directory.rglob("*") if path.is_file())
    _require(_source_digest(runtime_inputs, runtime_dir.parent) == build["RUNTIME_SOURCE_SHA256"], "effects source hash differs")
    return versions_data, build_data, build


def _payload_bytes(value: Any, label: str) -> bytes:
    container = _object(value, label)
    _require(set(container) == {"payloads"}, f"{label} fields differ")
    payloads = _array(container["payloads"], label + " payloads")
    _require(len(payloads) == 1, f"{label} must contain one payload")
    payload = _object(payloads[0], label + " payload")
    _require(set(payload) == {"metadata", "data"}, f"{label} payload fields differ")
    _require(payload["metadata"] == {"encoding": "anNvbi9wbGFpbg=="}, f"{label} encoding differs")
    _require(isinstance(payload["data"], str), f"{label} data is absent")
    try:
        return base64.b64decode(payload["data"], validate=True)
    except ValueError as error:
        raise EvidenceError(f"{label} data is not base64") from error


def _operation_id() -> str:
    value = b"operation-id-v1\0temporal-order-workflow\0" + PAYMENT_TOKEN.encode()
    return "op-" + sha256(value).hexdigest()


def _normalize_history(history: dict[str, Any], run_id: str) -> dict[str, Any]:
    normalized = copy.deepcopy(history)
    for event in normalized["events"]:
        event.pop("eventTime", None)
        event.pop("taskId", None)
        for attributes in event.values():
            if not isinstance(attributes, dict):
                continue
            for key in ("originalExecutionRunId", "firstExecutionRunId"):
                if attributes.get(key) == run_id:
                    attributes[key] = "<run-id>"
            attributes.pop("requestId", None)
            attributes.pop("historySizeBytes", None)
            queue = attributes.get("taskQueue")
            if isinstance(queue, dict) and queue.get("kind") == "TASK_QUEUE_KIND_STICKY":
                _require(queue.get("normalName") == TASK_QUEUE, "sticky task queue has the wrong normal name")
                queue["name"] = "<sticky-queue>"
    return normalized


def _check_cut_history(results: Path, run_id: str) -> tuple[dict[str, Any], str]:
    before_data = _read(results / "cut-show-before.json")
    _require(before_data == _read(results / "cut-show-after.json"), "cut History double-read is unstable")
    history = _json(results / "cut-show-before.json")
    _require(set(history) == {"events"}, "cut History fields differ")
    events = _array(history["events"], "cut History events")
    _require([event.get("eventType") for event in events if isinstance(event, dict)] == EXPECTED_CUT_TYPES, "cut History event sequence differs")
    _require([event.get("eventId") for event in events] == [str(i) for i in range(1, 6)], "cut History event IDs differ")
    for event in events:
        _require(isinstance(event.get("eventTime"), str) and event["eventTime"], "cut event time is absent")
        _require(isinstance(event.get("taskId"), str) and event["taskId"].isdigit(), "cut task ID differs")

    started = _object(events[0].get("workflowExecutionStartedEventAttributes"), "Workflow start")
    _require(
        set(started) == {
            "workflowType", "taskQueue", "input", "workflowExecutionTimeout", "workflowRunTimeout",
            "workflowTaskTimeout", "originalExecutionRunId", "identity", "firstExecutionRunId", "attempt",
            "firstWorkflowTaskBackoff", "header", "workflowId",
        },
        "Workflow start fields differ",
    )
    _require(started["workflowType"] == {"name": "FoodOrderAutoUpgrade"}, "Workflow type differs")
    _require(started["taskQueue"] == {"name": TASK_QUEUE, "kind": "TASK_QUEUE_KIND_NORMAL"}, "Workflow task queue differs")
    expected_order = b'{"order_id":"order-1","amount_cents":4200,"payment_token":"payment-token-1"}'
    _require(_payload_bytes(started["input"], "Workflow input") == expected_order, "Workflow input bytes differ")
    _require(
        started["workflowExecutionTimeout"] == "0s" and started["workflowRunTimeout"] == "0s" and
        started["workflowTaskTimeout"] == "10s" and started["firstWorkflowTaskBackoff"] == "0s",
        "Workflow timeouts differ",
    )
    _require(
        started["originalExecutionRunId"] == run_id and started["firstExecutionRunId"] == run_id and
        started["identity"] == "safe-change-temporal-starter" and started["attempt"] == 1 and
        started["header"] == {} and started["workflowId"] == WORKFLOW_ID,
        "Workflow start identity differs",
    )

    scheduled = _object(events[1].get("workflowTaskScheduledEventAttributes"), "Workflow task scheduled")
    _require(
        scheduled == {
            "taskQueue": {"name": TASK_QUEUE, "kind": "TASK_QUEUE_KIND_NORMAL"},
            "startToCloseTimeout": "10s", "attempt": 1,
        },
        "first Workflow task schedule differs",
    )
    task_started = _object(events[2].get("workflowTaskStartedEventAttributes"), "Workflow task started")
    _require(set(task_started) == {"scheduledEventId", "identity", "requestId", "historySizeBytes"}, "Workflow task start fields differ")
    _require(
        task_started["scheduledEventId"] == "2" and task_started["identity"] == V1_IDENTITY and
        isinstance(task_started["requestId"], str) and task_started["requestId"] and
        isinstance(task_started["historySizeBytes"], str) and task_started["historySizeBytes"].isdigit(),
        "Workflow task start differs",
    )
    completed = _object(events[3].get("workflowTaskCompletedEventAttributes"), "Workflow task completed")
    _require(
        completed.get("scheduledEventId") == "2" and completed.get("startedEventId") == "3" and
        completed.get("identity") == V1_IDENTITY and
        completed.get("workerVersion") == {"buildId": V1_BUILD, "useVersioning": True} and
        completed.get("sdkMetadata") == {"langUsedFlags": [3], "sdkName": "temporal-go", "sdkVersion": "1.47.0"} and
        completed.get("meteringMetadata") == {} and
        completed.get("versioningBehavior") == "VERSIONING_BEHAVIOR_AUTO_UPGRADE" and
        completed.get("workerDeploymentName") == DEPLOYMENT and
        completed.get("deploymentVersion") == {"buildId": V1_BUILD, "deploymentName": DEPLOYMENT},
        "Workflow task completion/version differs",
    )

    activity = _object(events[4].get("activityTaskScheduledEventAttributes"), "Payment schedule")
    _require(
        set(activity) == {
            "activityId", "activityType", "taskQueue", "header", "input", "scheduleToCloseTimeout",
            "scheduleToStartTimeout", "startToCloseTimeout", "heartbeatTimeout",
            "workflowTaskCompletedEventId", "retryPolicy", "useWorkflowBuildId",
        },
        "Payment schedule fields differ",
    )
    operation_id = _operation_id()
    expected_payment = (
        b'{"order_id":"order-1","amount_cents":4200,"operation_id":"' + operation_id.encode() + b'"}'
    )
    _require(_payload_bytes(activity["input"], "Payment input") == expected_payment, "Payment input bytes differ")
    _require(
        activity["activityId"] == "5" and activity["activityType"] == {"name": "ChargePayment"} and
        activity["taskQueue"] == {"name": TASK_QUEUE, "kind": "TASK_QUEUE_KIND_NORMAL"} and
        activity["header"] == {} and activity["scheduleToCloseTimeout"] == "0s" and
        activity["scheduleToStartTimeout"] == "0s" and activity["startToCloseTimeout"] == "30s" and
        activity["heartbeatTimeout"] == "0s" and activity["workflowTaskCompletedEventId"] == "4" and
        activity["retryPolicy"] == {
            "initialInterval": "1s", "backoffCoefficient": 2,
            "maximumInterval": "100s", "maximumAttempts": 1,
        } and activity["useWorkflowBuildId"] is True,
        "Payment schedule semantics differ",
    )
    return _normalize_history(history, run_id), operation_id


def _check_cut_describe(results: Path, run_id: str) -> dict[str, Any]:
    value = _json(results / "cut-describe.json")
    info = _object(value.get("workflowExecutionInfo"), "cut Workflow info")
    _require(info.get("execution") == {"workflowId": WORKFLOW_ID, "runId": run_id}, "cut Workflow execution differs")
    _require(info.get("type") == {"name": "FoodOrderAutoUpgrade"}, "cut Workflow type differs")
    _require(info.get("status") == "WORKFLOW_EXECUTION_STATUS_RUNNING", "cut Workflow is not running")
    _require(info.get("taskQueue") == TASK_QUEUE and info.get("workerDeploymentName") == DEPLOYMENT, "cut queue/deployment differs")
    _require(info.get("mostRecentWorkerVersionStamp") == {"buildId": V1_BUILD, "useVersioning": True}, "cut worker version differs")
    versioning = _object(info.get("versioningInfo"), "cut versioning info")
    _require(
        versioning.get("behavior") == "VERSIONING_BEHAVIOR_AUTO_UPGRADE" and
        versioning.get("version") == f"{DEPLOYMENT}.{V1_BUILD}" and
        versioning.get("deploymentVersion") == {"buildId": V1_BUILD, "deploymentName": DEPLOYMENT} and
        versioning.get("revisionNumber") == "1",
        "cut versioning info differs",
    )
    pending = _array(value.get("pendingActivities"), "pending Activities")
    _require(len(pending) == 1, "cut must have one pending Activity")
    item = _object(pending[0], "pending Payment")
    _require(
        item.get("activityId") == "5" and item.get("activityType") == {"name": "ChargePayment"} and
        item.get("state") == "PENDING_ACTIVITY_STATE_STARTED" and item.get("attempt") == 1 and
        item.get("maximumAttempts") == 1 and item.get("lastWorkerIdentity") == V1_IDENTITY and
        item.get("lastWorkerDeploymentVersion") == f"{DEPLOYMENT}.{V1_BUILD}" and
        item.get("lastDeploymentVersion") == {"buildId": V1_BUILD, "deploymentName": DEPLOYMENT},
        "pending Payment state/version differs",
    )
    _require(isinstance(item.get("lastStartedTime"), str) and isinstance(item.get("scheduledTime"), str), "pending Payment times are absent")
    options = _object(item.get("activityOptions"), "pending Payment options")
    _require(
        options.get("taskQueue") == {"name": TASK_QUEUE, "normalName": TASK_QUEUE} and
        options.get("scheduleToCloseTimeout") == "0s" and options.get("scheduleToStartTimeout") == "0s" and
        options.get("startToCloseTimeout") == "30s" and options.get("heartbeatTimeout") == "0s" and
        options.get("retryPolicy") == {
            "initialInterval": "1s", "backoffCoefficient": 2,
            "maximumInterval": "100s", "maximumAttempts": 1,
        },
        "pending Payment options differ",
    )
    return {
        "type": info["type"], "status": info["status"], "taskQueue": info["taskQueue"],
        "workerDeploymentName": info["workerDeploymentName"],
        "mostRecentWorkerVersionStamp": info["mostRecentWorkerVersionStamp"],
        "versioningInfo": versioning,
        "pending": {key: item[key] for key in (
            "activityId", "activityType", "state", "attempt", "maximumAttempts",
            "lastWorkerIdentity", "lastWorkerDeploymentVersion", "lastDeploymentVersion", "activityOptions",
        )},
    }


def _check_stats(results: Path, name: str, deliveries: int, commits: int, paths: dict[str, int]) -> None:
    value = _json(results / name)
    _require(set(value) == {"deliveries", "commits", "paths"}, f"{name} fields differ")
    _require(value == {"deliveries": deliveries, "commits": commits, "paths": paths}, f"{name} counts differ")


def _check_provider(results: Path, case_name: str, operation_id: str) -> None:
    commits = 0 if case_name == "h0" else 1
    for name in ("payment-cut-stats.json", "payment-before-v2-stats.json", "payment-final-stats.json"):
        _check_stats(results, name, 1, commits, {"/v1/charge": 1})
    _check_stats(results, "completion-final-stats.json", 0, 0, {})
    _require(_read(results / "completion-cut.history") == b"", "completion state is nonempty at cut")
    _require(_read(results / "completion-final.history") == b"", "completion effect occurred")

    cut = _read(results / "payment-cut.history")
    final = _read(results / "payment-final.history")
    _require(cut == final, "payment state changed after the cut")
    if case_name == "h0":
        _require(final == b"", "H0 contains a durable payment")
        return
    _require(final.endswith(b"\n") and final.count(b"\n") == 1, "H1 must contain exactly one payment record")
    try:
        record = json.loads(final)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvidenceError("H1 payment record is not JSON") from error
    record = _object(record, "H1 payment record")
    body = b'{"order_id":"order-1","amount_cents":4200}'
    request_hash = sha256(b"POST\0/v1/charge\0" + body).hexdigest()
    result_hash = sha256(b"charged\0" + operation_id.encode() + b"\0" + b"1").hexdigest()
    _require(
        record == {
            "operation_id": operation_id,
            "request_hash": request_hash,
            "result_hash": result_hash,
            "remote_reference": f"temporal-payment/{operation_id}/commit-1",
            "path": "/v1/charge",
        },
        "H1 payment record differs from the scheduled Activity",
    )


def _check_poller(results: Path, name: str, build_id: str, identity: str) -> None:
    value = _json(results / name)
    pollers = _array(value.get("pollers"), name + " pollers")
    matches = [
        item for item in pollers
        if isinstance(item, dict)
        and item.get("identity") == identity
        and item.get("worker_version_capabilities") == {
            "build_id": build_id, "use_versioning": True, "deployment_series_name": DEPLOYMENT,
        }
        and item.get("deployment_options") == {
            "deployment_name": DEPLOYMENT, "build_id": build_id, "worker_versioning_mode": 2,
        }
    ]
    _require(len(matches) == 1, f"{name} does not prove the expected poller")
    _require(isinstance(matches[0].get("last_access_time"), dict), f"{name} poller freshness is absent")


def _check_deployments(results: Path) -> None:
    _check_poller(results, "v1-workflow-pollers.json", V1_BUILD, V1_IDENTITY)
    _check_poller(results, "v1-activity-pollers.json", V1_BUILD, V1_IDENTITY)
    _check_poller(results, "v2-workflow-pollers.json", V2_BUILD, V2_IDENTITY)
    _check_poller(results, "v2-activity-pollers.json", V2_BUILD, V2_IDENTITY)
    _require(_read(results / "set-current-v1.json") == b"", "set-current v1 output differs")
    _require(_read(results / "set-current-v2.json") == b"", "set-current v2 output differs")
    _require(_read(results / "signal-complete.json") == b"", "signal CLI output differs")
    v1 = _json(results / "deployment-v1-current.json")
    v2 = _json(results / "deployment-v2-current.json")
    _require(
        v1.get("name") == DEPLOYMENT and
        v1.get("routingConfig", {}).get("currentVersionDeploymentName") == DEPLOYMENT and
        v1.get("routingConfig", {}).get("currentVersionBuildID") == V1_BUILD,
        "v1 was not current before the cut",
    )
    _require(
        v2.get("name") == DEPLOYMENT and
        v2.get("routingConfig", {}).get("currentVersionDeploymentName") == DEPLOYMENT and
        v2.get("routingConfig", {}).get("currentVersionBuildID") == V2_BUILD,
        "v2 was not current after the cut",
    )
    for name, build in (
        ("version-v1.json", V1_BUILD),
        ("version-v2-before-current.json", V2_BUILD),
        ("version-v2-current.json", V2_BUILD),
    ):
        version = _json(results / name)
        _require(version.get("deploymentName") == DEPLOYMENT and version.get("BuildID") == build, f"{name} identity differs")
        queues = _array(version.get("taskQueuesInfos"), name + " task queues")
        _require(
            {tuple(sorted(item.items())) for item in queues if isinstance(item, dict)} == {
                (("name", TASK_QUEUE), ("type", "activity")),
                (("name", TASK_QUEUE), ("type", "workflow")),
            },
            f"{name} task queues differ",
        )


def _service_container(containers: list[Any], service: str) -> dict[str, Any]:
    matches = [
        item for item in containers
        if isinstance(item, dict)
        and isinstance(item.get("Config"), dict)
        and item["Config"].get("Labels", {}).get("com.docker.compose.service") == service
    ]
    _require(len(matches) == 1, f"container evidence for {service} differs")
    return matches[0]


def _check_worker_inspect(
    path: Path, image: str, service: str, running: bool,
    source_hash: str, revision: str, build_id: str,
) -> None:
    values = json.loads(_read(path))
    values = _array(values, path.name)
    _require(len(values) == 1, f"{path.name} container count differs")
    item = _object(values[0], path.name + " container")
    labels = _object(item.get("Config", {}).get("Labels"), path.name + " labels")
    _require(
        item.get("Image") == image and item.get("Config", {}).get("Image") == image and
        item.get("State", {}).get("Running") is running and
        labels.get("com.docker.compose.service") == service and
        labels.get("io.safe-change.source.sha256") == source_hash and
        labels.get("io.safe-change.build.target") == service.replace("-", "_") and
        labels.get("io.safe-change.worker.build-id") == build_id and
        labels.get("org.opencontainers.image.revision") == revision,
        f"{path.name} image/state binding differs",
    )


def _check_containers(results: Path, build: dict[str, str], versions: dict[str, str]) -> None:
    _check_worker_inspect(
        results / "v1-running-inspect.json", build["WORKER_V1_ID"], "worker-v1", True,
        build["SOURCE_SHA256"], build["GIT_REVISION"], V1_BUILD,
    )
    _check_worker_inspect(
        results / "v1-stopped-inspect.json", build["WORKER_V1_ID"], "worker-v1", False,
        build["SOURCE_SHA256"], build["GIT_REVISION"], V1_BUILD,
    )
    _check_worker_inspect(
        results / "v2-running-inspect.json", build["WORKER_V2_ID"], "worker-v2", True,
        build["SOURCE_SHA256"], build["GIT_REVISION"], V2_BUILD,
    )
    values = json.loads(_read(results / "containers-final.json"))
    containers = _array(values, "final containers")
    _require(len(containers) == 5, "final container set differs")
    temporal = _service_container(containers, "temporal")
    payment = _service_container(containers, "payment")
    completion = _service_container(containers, "completion")
    v1 = _service_container(containers, "worker-v1")
    v2 = _service_container(containers, "worker-v2")
    temporal_id = "sha256:" + versions["TEMPORAL_IMAGE"].rsplit("@sha256:", 1)[1]
    _require(
        temporal.get("Image") == temporal_id and temporal.get("Config", {}).get("Image") == versions["TEMPORAL_IMAGE"] and
        temporal.get("State", {}).get("Running") is True,
        "Temporal Server container differs",
    )
    for service, item in (("payment", payment), ("completion", completion)):
        labels = item.get("Config", {}).get("Labels", {})
        _require(
            item.get("Image") == build["EFFECTS_ID"] and item.get("Config", {}).get("Image") == build["EFFECTS_ID"] and
            item.get("State", {}).get("Running") is True and labels.get("io.safe-change.build.target") == "effects" and
            labels.get("io.safe-change.source.sha256") == build["RUNTIME_SOURCE_SHA256"] and
            labels.get("org.opencontainers.image.revision") == build["GIT_REVISION"],
            f"{service} container differs",
        )
    _require(v1.get("Image") == build["WORKER_V1_ID"] and v1.get("State", {}).get("Running") is False, "final v1 state differs")
    _require(v2.get("Image") == build["WORKER_V2_ID"] and v2.get("State", {}).get("Running") is True, "final v2 state differs")


def _check_pre_v2(results: Path, run_id: str, cut: dict[str, Any]) -> dict[str, Any]:
    history = _json(results / "pre-v2-history.json")
    events = _array(history.get("events"), "pre-v2 History")
    _require([event.get("eventType") for event in events if isinstance(event, dict)] == EXPECTED_PRE_V2_TYPES, "pre-v2 History differs")
    _require(history["events"][:5] == _json(results / "cut-show-before.json")["events"], "pre-v2 History does not extend the cut")
    started = _object(events[5].get("activityTaskStartedEventAttributes"), "Payment start")
    _require(
        started.get("scheduledEventId") == "5" and started.get("identity") == V1_IDENTITY and
        started.get("attempt") == 1 and isinstance(started.get("requestId"), str),
        "Payment start differs",
    )
    timed_out = _object(events[6].get("activityTaskTimedOutEventAttributes"), "Payment timeout")
    _require(
        timed_out.get("scheduledEventId") == "5" and timed_out.get("startedEventId") == "6" and
        timed_out.get("retryState") == "RETRY_STATE_MAXIMUM_ATTEMPTS_REACHED" and
        timed_out.get("failure", {}).get("timeoutFailureInfo", {}).get("timeoutType") == "TIMEOUT_TYPE_START_TO_CLOSE",
        "Payment timeout differs",
    )
    next_task = _object(events[7].get("workflowTaskScheduledEventAttributes"), "post-timeout Workflow task")
    _require(
        next_task.get("taskQueue", {}).get("kind") == "TASK_QUEUE_KIND_STICKY" and
        next_task.get("taskQueue", {}).get("normalName") == TASK_QUEUE and
        next_task.get("startToCloseTimeout") == "10s" and next_task.get("attempt") == 1,
        "post-timeout Workflow task differs",
    )
    normalized = _normalize_history(history, run_id)
    _require(normalized["events"][:5] == cut["events"], "normalized pre-v2 History does not extend the cut")
    return normalized


def _check_final(results: Path, run_id: str, pre_v2: dict[str, Any]) -> int:
    history = _json(results / "final-history.json")
    events = _array(history.get("events"), "final History")
    _require(history["events"][:8] == _json(results / "pre-v2-history.json")["events"], "final History does not extend pre-v2 History")
    signals = [
        event for event in events
        if isinstance(event, dict) and event.get("eventType") == "EVENT_TYPE_WORKFLOW_EXECUTION_SIGNALED"
    ]
    _require(len(signals) == 1, "final History must contain one completion signal")
    signal = _object(signals[0].get("workflowExecutionSignaledEventAttributes"), "completion signal")
    _require(
        signal == {"signalName": "complete", "input": {}, "identity": SIGNAL_IDENTITY},
        "completion signal differs",
    )
    failures = [
        event for event in events
        if isinstance(event, dict) and event.get("eventType") == "EVENT_TYPE_WORKFLOW_TASK_FAILED"
    ]
    _require(len(failures) >= 1, "v2 did not produce a Workflow task failure")
    for event in failures:
        attributes = _object(event.get("workflowTaskFailedEventAttributes"), "Workflow task failure")
        failure = _object(attributes.get("failure"), "Workflow task failure detail")
        _require(
            attributes.get("cause") == NONDETERMINISM and attributes.get("identity") == V2_IDENTITY and
            failure.get("message") == NONDETERMINISM_MESSAGE and failure.get("source") == "GoSDK",
            "v2 failure is not the expected replay nondeterminism",
        )
    later_starts = [
        event.get("workflowTaskStartedEventAttributes", {}).get("identity")
        for event in events[8:]
        if isinstance(event, dict) and event.get("eventType") == "EVENT_TYPE_WORKFLOW_TASK_STARTED"
    ]
    _require(later_starts and all(identity == V2_IDENTITY for identity in later_starts), "a post-cut Workflow task ran on the wrong worker")
    terminal = {
        "EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED", "EVENT_TYPE_WORKFLOW_EXECUTION_FAILED",
        "EVENT_TYPE_WORKFLOW_EXECUTION_CANCELED", "EVENT_TYPE_WORKFLOW_EXECUTION_TERMINATED",
        "EVENT_TYPE_WORKFLOW_EXECUTION_TIMED_OUT",
    }
    _require(not any(event.get("eventType") in terminal for event in events if isinstance(event, dict)), "Workflow unexpectedly terminated")
    scheduled_activities = [
        event for event in events
        if isinstance(event, dict) and event.get("eventType") == "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED"
    ]
    _require(
        len(scheduled_activities) == 1 and
        scheduled_activities[0].get("activityTaskScheduledEventAttributes", {}).get("activityType") == {"name": "ChargePayment"},
        "final Activity schedule set differs",
    )
    _require(
        not any(
            event.get("eventType") == "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED" and
            event.get("activityTaskScheduledEventAttributes", {}).get("activityType", {}).get("name") == "CompleteOrder"
            for event in events if isinstance(event, dict)
        ),
        "completion Activity was scheduled",
    )
    final = _json(results / "final-describe.json")
    info = _object(final.get("workflowExecutionInfo"), "final Workflow info")
    _require(info.get("execution") == {"workflowId": WORKFLOW_ID, "runId": run_id}, "final execution differs")
    _require(info.get("status") == "WORKFLOW_EXECUTION_STATUS_RUNNING", "final Workflow is not running")
    versioning = _object(info.get("versioningInfo"), "final versioning info")
    _require(
        versioning.get("behavior") == "VERSIONING_BEHAVIOR_AUTO_UPGRADE" and
        versioning.get("deploymentVersion") == {"buildId": V1_BUILD, "deploymentName": DEPLOYMENT} and
        versioning.get("versionTransition", {}).get("deploymentVersion") == {"buildId": V2_BUILD, "deploymentName": DEPLOYMENT},
        "final v2 version transition differs",
    )
    return len(failures)


def _check_case(root: Path, case_name: str) -> dict[str, Any]:
    results = _results_dir(root)
    _verify_checksums(results)
    _require(_read(results / "exit-status.txt") == b"0\n", f"{case_name} runner did not exit successfully")
    versions_data, build_data, build = _check_build(results)
    versions = _parse_env(versions_data, "versions.env")

    start = _json(results / "start.json")
    _require(
        set(start) == {"schema", "behavior", "workflow_id", "run_id"} and
        start.get("schema") == 1 and start.get("behavior") == "autoupgrade" and
        start.get("workflow_id") == WORKFLOW_ID and isinstance(start.get("run_id"), str) and start["run_id"],
        f"{case_name} start record differs",
    )
    run_id = start["run_id"]
    cut_history, operation_id = _check_cut_history(results, run_id)
    cut_describe = _check_cut_describe(results, run_id)
    _check_provider(results, case_name, operation_id)
    _check_deployments(results)
    _check_containers(results, build, versions)
    pre_v2 = _check_pre_v2(results, run_id, cut_history)
    failure_count = _check_final(results, run_id, pre_v2)

    observed = _json(results / "observed.json")
    expected_commits = 0 if case_name == "h0" else 1
    _require(
        observed == {
            "schema": 1,
            "case": case_name,
            "mode": "auto_upgrade",
            "workflow_id": WORKFLOW_ID,
            "run_id": run_id,
            "final_status": "WORKFLOW_EXECUTION_STATUS_RUNNING",
            "workflow_task_failures": failure_count,
            "payment": {"deliveries": 1, "commits": expected_commits, "paths": {"/v1/charge": 1}},
            "completion": {"deliveries": 0, "commits": 0, "paths": {}},
        },
        f"{case_name} observed summary does not match raw evidence",
    )
    return {
        "results": results,
        "versions_data": versions_data,
        "build_data": build_data,
        "build": build,
        "run_id": run_id,
        "operation_id": operation_id,
        "cut_history": cut_history,
        "cut_describe": cut_describe,
        "pre_v2": pre_v2,
        "failure_count": failure_count,
    }


def check_pair(h0_root: Path, h1_root: Path) -> dict[str, Any]:
    h0 = _check_case(h0_root, "h0")
    h1 = _check_case(h1_root, "h1")
    _require(h0["versions_data"] == h1["versions_data"], "H0/H1 versions differ")
    _require(h0["build_data"] == h1["build_data"], "H0/H1 builds differ")
    _require(h0["operation_id"] == h1["operation_id"], "H0/H1 Operation identity differs")
    _require(h0["cut_history"] == h1["cut_history"], "H0/H1 cut History semantics differ")
    _require(h0["cut_describe"] == h1["cut_describe"], "H0/H1 pending Activity semantics differ")
    _require(h0["pre_v2"] == h1["pre_v2"], "H0/H1 pre-v2 History semantics differ")
    _require(h0["run_id"] != h1["run_id"], "H0/H1 unexpectedly reused a Temporal run")
    return {
        "valid": True,
        "mode": "auto_upgrade",
        "workflow_id": WORKFLOW_ID,
        "operation_id": h0["operation_id"],
        "cut_history_equal": True,
        "pending_activity_equal": True,
        "h0_payment_commits": 0,
        "h1_payment_commits": 1,
        "h0_final_status": "WORKFLOW_EXECUTION_STATUS_RUNNING",
        "h1_final_status": "WORKFLOW_EXECUTION_STATUS_RUNNING",
        "h0_nondeterministic_tasks": h0["failure_count"],
        "h1_nondeterministic_tasks": h1["failure_count"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("h0", type=Path)
    parser.add_argument("h1", type=Path)
    args = parser.parse_args()
    try:
        verdict = check_pair(args.h0, args.h1)
    except (EvidenceError, OSError, json.JSONDecodeError) as error:
        print(json.dumps({"valid": False, "error": str(error)}, sort_keys=True))
        return 1
    print(json.dumps(verdict, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
