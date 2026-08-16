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
import subprocess
from typing import Any


MAX_FILE_BYTES = 64 << 20
MAX_CASE_BYTES = 128 << 20
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")

WORKFLOW_ID = "temporal-matched-order-1"
ORDER_ID = "order-1"
RESTAURANT_ID = "restaurant-1"
PRODUCT_ID = "pizza-1"
PRODUCT_DESCRIPTION = "Margherita Pizza"
PRODUCT_QUANTITY = 2
DELIVERY_DELAY_MILLIS = 25
DELIVERY_ID = "delivery-order-1"
DRIVER_ID = "driver-1"
PAYMENT_TOKEN = "payment-token-1"
AMOUNT_CENTS = 4200
TASK_QUEUE = "safe-change-food-orders"
DEPLOYMENT = "safe-change-food-order-worker"
V1_BUILD = "food-order-v1"
V2_BUILD = "food-order-v2"
V1_IDENTITY = "safe-change-food-order-v1-worker"
V2_IDENTITY = "safe-change-food-order-v2-worker"
SIGNAL_IDENTITY = "safe-change-harness"
BUSINESS_SIGNALS = (
    "preparation_finished", "driver_selected", "driver_at_restaurant", "delivery_finished",
)
FROZEN_FULL_SOURCE_SHA256 = "877a7a5b71b24e3dc309af5cd23bebe77c40dab6b8aec659ef929f1dc771aade"
FROZEN_RUNTIME_SOURCE_SHA256 = "e95760a49a36fa0dbf8136589545b5499a99e353baabae44c6c11e37ed581059"
FROZEN_GIT_REVISION = "65988afbfc2fad82fdcc485fbc8f67dbc3b628cc"
FROZEN_VERSIONS_SHA256 = "c0fbc207ce2a462f364d56173004eaad2b2a3d8dd2fe040b0123352505a0edd3"
FROZEN_FULL_BUILD_SHA256 = "495e37bda60465e4be169605449a6d586f705faac95cbeb57f0ea49ab97a7fa5"
NONDETERMINISM = "WORKFLOW_TASK_FAILED_CAUSE_NON_DETERMINISTIC_ERROR"
NONDETERMINISM_MESSAGE = (
    "[TMPRL1100] lookup failed for scheduledEventID to activityID: "
    "scheduleEventID: 5, activityID: 5"
)


def _workflow_name(mode: str) -> str:
    names = {
        "auto_upgrade": "FoodOrderAutoUpgrade",
        "pinned": "FoodOrderPinned",
        "manual_branch": "FoodOrderManualBranch",
    }
    _require(mode in names, "Temporal mode differs")
    return names[mode]


def _versioning_behavior(mode: str) -> str:
    _require(mode in {"auto_upgrade", "pinned", "manual_branch"}, "Temporal mode differs")
    if mode in {"auto_upgrade", "manual_branch"}:
        return "VERSIONING_BEHAVIOR_AUTO_UPGRADE"
    return "VERSIONING_BEHAVIOR_PINNED"


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
    "signal-delivery-finished.json",
    "signal-driver-at-restaurant.json",
    "signal-driver-selected.json",
    "signal-preparation-finished.json",
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

LEGACY_BUILD_KEYS = {
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
COMPATIBLE_BUILD_KEYS = {
    "WORKER_V1_VARIANT_SHA256",
    "WORKER_COMPATIBLE_V2_IMAGE",
    "WORKER_COMPATIBLE_V2_ID",
    "WORKER_COMPATIBLE_V2_BINARY_SHA256",
    "WORKER_COMPATIBLE_V2_VARIANT_SHA256",
}
BUILD_KEYS = LEGACY_BUILD_KEYS | COMPATIBLE_BUILD_KEYS

FROZEN_BUILD_PROFILES = {
    FROZEN_FULL_BUILD_SHA256: {
        "name": "step-0016-full-food-order",
        "keys": BUILD_KEYS,
        "git_revision": FROZEN_GIT_REVISION,
        "source_sha256": FROZEN_FULL_SOURCE_SHA256,
        "runtime_source_sha256": FROZEN_RUNTIME_SOURCE_SHA256,
    },
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


def _frozen_build_profile(build_data: bytes, build: dict[str, str]) -> dict[str, Any]:
    digest = sha256(build_data).hexdigest()
    profile = FROZEN_BUILD_PROFILES.get(digest)
    _require(profile is not None, "unsupported frozen Temporal build profile")
    assert profile is not None
    _require(set(build) == profile["keys"], "build.env fields differ")
    _require(
        build.get("GIT_REVISION") == profile["git_revision"] and
        build.get("SOURCE_SHA256") == profile["source_sha256"] and
        build.get("RUNTIME_SOURCE_SHA256") == profile["runtime_source_sha256"],
        "frozen Temporal build identity differs",
    )
    return profile


def _require_commit_object(repo_root: Path, revision: str) -> None:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "cat-file", "-e", f"{revision}^{{commit}}"],
        check=False, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    _require(result.returncode == 0, "recorded build revision commit object is absent")


def _check_build(results: Path) -> tuple[bytes, bytes, dict[str, str]]:
    versions_data = _read(results / "versions.env")
    _require(sha256(versions_data).hexdigest() == FROZEN_VERSIONS_SHA256, "unsupported frozen versions profile")
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
    profile = _frozen_build_profile(build_data, build)
    _require(HEX40.fullmatch(build["GIT_REVISION"]) is not None, "build revision is invalid")
    for key in build:
        if key.endswith("_SHA256"):
            _require(HEX64.fullmatch(build[key]) is not None, f"{key} is not SHA-256")
        if key.endswith("_ID"):
            _require(IMAGE_ID.fullmatch(build[key]) is not None, f"{key} is not an image ID")
    image_ids = {build["WORKER_V1_ID"], build["WORKER_V2_ID"]}
    image_names = [build["WORKER_V1_IMAGE"], build["WORKER_V2_IMAGE"]]
    if COMPATIBLE_BUILD_KEYS <= set(build):
        image_ids.add(build["WORKER_COMPATIBLE_V2_ID"])
        image_names.append(build["WORKER_COMPATIBLE_V2_IMAGE"])
    _require(len(image_ids) == len(image_names), "worker images are not distinct")
    _require(all("latest" not in image for image in image_names), "latest image is forbidden")
    repo_root = Path(__file__).resolve().parents[3]
    _require_commit_object(repo_root, profile["git_revision"])
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


def _completion_operation_id() -> str:
    value = b"operation-id-v1\0temporal-order-workflow\0complete:" + ORDER_ID.encode()
    return "op-" + sha256(value).hexdigest()


def _order_bytes() -> bytes:
    return (
        b'{"order_id":"order-1","restaurant_id":"restaurant-1","products":['
        b'{"product_id":"pizza-1","description":"Margherita Pizza","quantity":2}],'
        b'"amount_cents":4200,"delivery_delay_millis":25,"payment_token":"payment-token-1"}'
    )


def _json_payload_object(value: Any, label: str) -> dict[str, Any]:
    try:
        decoded = json.loads(_payload_bytes(value, label))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvidenceError(f"{label} is not JSON") from error
    return _object(decoded, label)


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


def _check_cut_history(
    results: Path, run_id: str, mode: str = "auto_upgrade",
) -> tuple[dict[str, Any], str]:
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
    _require(started["workflowType"] == {"name": _workflow_name(mode)}, "Workflow type differs")
    _require(started["taskQueue"] == {"name": TASK_QUEUE, "kind": "TASK_QUEUE_KIND_NORMAL"}, "Workflow task queue differs")
    _require(_payload_bytes(started["input"], "Workflow input") == _order_bytes(), "Workflow input bytes differ")
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
        completed.get("versioningBehavior") == _versioning_behavior(mode) and
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


def _check_cut_describe(
    results: Path, run_id: str, mode: str = "auto_upgrade",
) -> dict[str, Any]:
    value = _json(results / "cut-describe.json")
    info = _object(value.get("workflowExecutionInfo"), "cut Workflow info")
    _require(info.get("execution") == {"workflowId": WORKFLOW_ID, "runId": run_id}, "cut Workflow execution differs")
    _require(info.get("type") == {"name": _workflow_name(mode)}, "cut Workflow type differs")
    _require(info.get("status") == "WORKFLOW_EXECUTION_STATUS_RUNNING", "cut Workflow is not running")
    _require(info.get("taskQueue") == TASK_QUEUE and info.get("workerDeploymentName") == DEPLOYMENT, "cut queue/deployment differs")
    _require(info.get("mostRecentWorkerVersionStamp") == {"buildId": V1_BUILD, "useVersioning": True}, "cut worker version differs")
    versioning = _object(info.get("versioningInfo"), "cut versioning info")
    _require(
        versioning.get("behavior") == _versioning_behavior(mode) and
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


def _expected_provider_record(operation_id: str, path: str, reference_prefix: str) -> dict[str, str]:
    body = b'{"order_id":"order-1","amount_cents":4200}'
    return {
        "operation_id": operation_id,
        "request_hash": sha256(b"POST\0" + path.encode() + b"\0" + body).hexdigest(),
        "result_hash": sha256(b"charged\0" + operation_id.encode() + b"\0" + b"1").hexdigest(),
        "remote_reference": f"{reference_prefix}/{operation_id}/commit-1",
        "path": path,
    }


def _one_provider_record(data: bytes, label: str) -> dict[str, Any]:
    _require(data.endswith(b"\n") and data.count(b"\n") == 1, f"{label} must contain exactly one record")
    try:
        record = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvidenceError(f"{label} is not JSON") from error
    return _object(record, label)


def _check_provider(
    results: Path, case_name: str, operation_id: str, mode: str = "auto_upgrade",
) -> dict[str, dict[str, Any] | None]:
    _require(case_name in {"h0", "h1"}, "provider case differs")
    _require(mode in {"auto_upgrade", "pinned", "manual_branch"}, "Temporal mode differs")
    commits = 0 if case_name == "h0" else 1
    for name in ("payment-cut-stats.json", "payment-before-v2-stats.json", "payment-final-stats.json"):
        _check_stats(results, name, 1, commits, {"/v1/charge": 1})

    completion_expected = mode == "manual_branch" and case_name == "h1"
    _check_stats(
        results, "completion-final-stats.json",
        1 if completion_expected else 0,
        1 if completion_expected else 0,
        {"/v1/complete": 1} if completion_expected else {},
    )
    _require(_read(results / "completion-cut.history") == b"", "completion state is nonempty at cut")
    completion_data = _read(results / "completion-final.history")
    completion_record: dict[str, Any] | None = None
    if completion_expected:
        completion_record = _one_provider_record(completion_data, "H1 completion record")
        _require(
            completion_record == _expected_provider_record(
                _completion_operation_id(), "/v1/complete", "temporal-completion",
            ),
            "H1 completion record differs from the scheduled Activity",
        )
    else:
        _require(completion_data == b"", "completion effect occurred")

    cut = _read(results / "payment-cut.history")
    final = _read(results / "payment-final.history")
    _require(cut == final, "payment state changed after the cut")
    if case_name == "h0":
        _require(final == b"", "H0 contains a durable payment")
        return {"payment": None, "completion": completion_record}
    record = _one_provider_record(final, "H1 payment record")
    _require(
        record == _expected_provider_record(operation_id, "/v1/charge", "temporal-payment"),
        "H1 payment record differs from the scheduled Activity",
    )
    return {"payment": record, "completion": completion_record}


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
    for name in (
        "signal-preparation-finished.json", "signal-driver-selected.json",
        "signal-driver-at-restaurant.json", "signal-delivery-finished.json",
    ):
        _require(_read(results / name) == b"", f"{name} CLI output differs")
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


def _encoded_payload(data: bytes) -> dict[str, Any]:
    return {
        "payloads": [{
            "metadata": {"encoding": "anNvbi9wbGFpbg=="},
            "data": base64.b64encode(data).decode("ascii"),
        }],
    }


def _effect_request_bytes(operation_id: str) -> bytes:
    return (
        b'{"order_id":"order-1","amount_cents":4200,"operation_id":"' +
        operation_id.encode() + b'"}'
    )


def _manual_query_observation(
    case_name: str, operation_id: str, payment_fact: dict[str, Any] | None,
) -> dict[str, Any]:
    expected_payment = _expected_provider_record(operation_id, "/v1/charge", "temporal-payment")
    if case_name == "h0":
        _require(payment_fact is None, "H0 query is paired with a durable payment fact")
        return {
            "schema": 1,
            "operation_id": operation_id,
            "request_hash": expected_payment["request_hash"],
            "outcome": "inconclusive",
            "fact_hash": "",
            "remote_reference": f"temporal-payment/{operation_id}/count=0",
        }
    _require(case_name == "h1", "manual query case differs")
    _require(payment_fact == expected_payment, "H1 query is not paired with the payment provider fact")
    return {
        "schema": 1,
        "operation_id": operation_id,
        "request_hash": payment_fact["request_hash"],
        "outcome": "succeeded",
        "fact_hash": payment_fact["result_hash"],
        "remote_reference": payment_fact["remote_reference"],
    }


def _check_manual_query_result(
    value: Any, case_name: str, operation_id: str, payment_fact: dict[str, Any] | None,
) -> dict[str, Any]:
    try:
        observation = json.loads(_payload_bytes(value, "QueryPayment result"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvidenceError("QueryPayment result is not JSON") from error
    observation = _object(observation, "QueryPayment result")
    expected = _manual_query_observation(case_name, operation_id, payment_fact)
    _require(observation == expected, "QueryPayment result does not match the payment provider fact")
    return expected


def _manual_order_result() -> dict[str, Any]:
    return {
        "schema": 1,
        "order_id": ORDER_ID,
        "restaurant_id": RESTAURANT_ID,
        "product_count": PRODUCT_QUANTITY,
        "worker_build": V2_BUILD,
        "phase": "DELIVERED",
        "delivery_id": DELIVERY_ID,
        "driver_id": DRIVER_ID,
        "stages": [
            "RESTAURANT_SELECTED", "CREATED", "PAYMENT_PENDING", "PAYMENT_QUERY_PENDING",
            "PAYMENT_COMMITTED", "SCHEDULED", "IN_PREPARATION", "SCHEDULING_DELIVERY",
            "WAITING_FOR_DRIVER", "IN_DELIVERY", "DELIVERED",
        ],
    }


def _check_business_signals(events: list[Any]) -> list[dict[str, Any]]:
    signals = [
        _object(event, "business signal event")
        for event in events
        if isinstance(event, dict) and event.get("eventType") == "EVENT_TYPE_WORKFLOW_EXECUTION_SIGNALED"
    ]
    _require(len(signals) == len(BUSINESS_SIGNALS), "business signal count differs")
    attributes = [
        _object(event.get("workflowExecutionSignaledEventAttributes"), "business signal")
        for event in signals
    ]
    _require(
        [item.get("signalName") for item in attributes] == list(BUSINESS_SIGNALS),
        "business signal order differs",
    )
    for item in attributes:
        _require(set(item) == {"signalName", "input", "identity"}, "business signal fields differ")
        _require(item["identity"] == SIGNAL_IDENTITY, "business signal identity differs")
        if item["signalName"] == "driver_selected":
            _require(
                _payload_bytes(item["input"], "driver_selected input") ==
                b'{"delivery_id":"delivery-order-1","driver_id":"driver-1"}',
                "driver assignment signal differs",
            )
        else:
            _require(item["input"] == {}, f"{item['signalName']} input differs")
    return signals


def _expected_activity_input(activity_name: str, operation_id: str) -> bytes:
    inputs = {
        "QueryPayment": _effect_request_bytes(operation_id),
        "PrepareFood": (
            b'{"order_id":"order-1","restaurant_id":"restaurant-1","products":['
            b'{"product_id":"pizza-1","description":"Margherita Pizza","quantity":2}]}'
        ),
        "ScheduleDelivery": (
            b'{"order_id":"order-1","delivery_id":"delivery-order-1",'
            b'"restaurant_id":"restaurant-1","region":"San Jose (CA)"}'
        ),
        "CompleteOrder": _effect_request_bytes(_completion_operation_id()),
    }
    _require(activity_name in inputs, f"unexpected post-cut Activity {activity_name}")
    return inputs[activity_name]


def _check_post_cut_activity_schedule(event: dict[str, Any], operation_id: str) -> str:
    attributes = _object(event.get("activityTaskScheduledEventAttributes"), "post-cut Activity schedule")
    _require(
        set(attributes) == {
            "activityId", "activityType", "taskQueue", "header", "input", "scheduleToCloseTimeout",
            "scheduleToStartTimeout", "startToCloseTimeout", "heartbeatTimeout",
            "workflowTaskCompletedEventId", "retryPolicy", "useWorkflowBuildId",
        },
        "post-cut Activity schedule fields differ",
    )
    activity_type = _object(attributes.get("activityType"), "post-cut Activity type").get("name")
    _require(isinstance(activity_type, str), "post-cut Activity type is absent")
    timeout = "30s" if activity_type in {"PrepareFood", "ScheduleDelivery"} else "60s"
    _require(
        attributes["activityId"] == event.get("eventId") and
        attributes["taskQueue"] == {"name": TASK_QUEUE, "kind": "TASK_QUEUE_KIND_NORMAL"} and
        attributes["header"] == {} and
        _payload_bytes(attributes["input"], f"{activity_type} input") ==
        _expected_activity_input(activity_type, operation_id) and
        attributes["scheduleToCloseTimeout"] == "0s" and
        attributes["scheduleToStartTimeout"] == "0s" and
        attributes["startToCloseTimeout"] == timeout and
        attributes["heartbeatTimeout"] == "0s" and
        isinstance(attributes["workflowTaskCompletedEventId"], str) and
        attributes["retryPolicy"] == {
            "initialInterval": "1s", "backoffCoefficient": 2,
            "maximumInterval": "100s", "maximumAttempts": 1,
        } and attributes["useWorkflowBuildId"] is True,
        f"{activity_type} schedule semantics differ",
    )
    return activity_type


def _check_manual_terminal_event(event: Any, case_name: str) -> None:
    event = _object(event, "manual terminal event")
    if case_name == "h0":
        _require(event.get("eventType") == "EVENT_TYPE_WORKFLOW_EXECUTION_FAILED", "H0 terminal event differs")
        _require(
            event.get("workflowExecutionFailedEventAttributes") == {
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
            "H0 terminal failure is not the exact nonretryable reconciliation failure",
        )
        return
    _require(case_name == "h1", "manual terminal case differs")
    _require(event.get("eventType") == "EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED", "H1 terminal event differs")
    attributes = _object(event.get("workflowExecutionCompletedEventAttributes"), "H1 completion")
    _require(set(attributes) == {"result", "workflowTaskCompletedEventId"}, "H1 completion fields differ")
    expected_bytes = json.dumps(_manual_order_result(), separators=(",", ":")).encode()
    _require(
        _payload_bytes(attributes["result"], "H1 Workflow result") == expected_bytes and
        attributes["workflowTaskCompletedEventId"] == "23",
        "H1 terminal result differs",
    )


def _manual_wft_completion(scheduled_id: str, started_id: str) -> dict[str, Any]:
    return {
        "scheduledEventId": scheduled_id,
        "startedEventId": started_id,
        "identity": V2_IDENTITY,
        "workerVersion": {"buildId": V2_BUILD, "useVersioning": True},
        "sdkMetadata": {},
        "meteringMetadata": {},
        "versioningBehavior": "VERSIONING_BEHAVIOR_AUTO_UPGRADE",
        "workerDeploymentName": DEPLOYMENT,
        "deploymentVersion": {"buildId": V2_BUILD, "deploymentName": DEPLOYMENT},
    }


def _manual_activity_schedule(
    activity_id: str, activity_name: str, operation_id: str, completed_wft_id: str,
) -> dict[str, Any]:
    return {
        "activityId": activity_id,
        "activityType": {"name": activity_name},
        "taskQueue": {"name": TASK_QUEUE, "kind": "TASK_QUEUE_KIND_NORMAL"},
        "header": {},
        "input": _encoded_payload(_effect_request_bytes(operation_id)),
        "scheduleToCloseTimeout": "0s",
        "scheduleToStartTimeout": "0s",
        "startToCloseTimeout": "60s",
        "heartbeatTimeout": "0s",
        "workflowTaskCompletedEventId": completed_wft_id,
        "retryPolicy": {
            "initialInterval": "1s", "backoffCoefficient": 2,
            "maximumInterval": "100s", "maximumAttempts": 1,
        },
        "useWorkflowBuildId": True,
    }


def _manual_event(event_id: int, event_type: str, attribute_name: str, attributes: dict[str, Any]) -> dict[str, Any]:
    return {"eventId": str(event_id), "eventType": event_type, attribute_name: attributes}


def _manual_sticky_schedule() -> dict[str, Any]:
    return {
        "taskQueue": {
            "name": "<sticky-queue>", "kind": "TASK_QUEUE_KIND_STICKY", "normalName": TASK_QUEUE,
        },
        "startToCloseTimeout": "10s",
        "attempt": 1,
    }


def _expected_manual_tail(
    case_name: str, operation_id: str, query_observation: dict[str, Any],
    completion_fact: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    query_bytes = json.dumps(query_observation, separators=(",", ":")).encode()
    tail = [
        _manual_event(9, "EVENT_TYPE_WORKFLOW_EXECUTION_SIGNALED", "workflowExecutionSignaledEventAttributes", {
            "signalName": "complete", "input": {}, "identity": SIGNAL_IDENTITY,
        }),
        _manual_event(10, "EVENT_TYPE_WORKFLOW_TASK_STARTED", "workflowTaskStartedEventAttributes", {
            "scheduledEventId": "8", "identity": V2_IDENTITY,
        }),
        _manual_event(11, "EVENT_TYPE_WORKFLOW_TASK_COMPLETED", "workflowTaskCompletedEventAttributes",
                      _manual_wft_completion("8", "10")),
        _manual_event(12, "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED", "activityTaskScheduledEventAttributes",
                      _manual_activity_schedule("12", "QueryPayment", operation_id, "11")),
        _manual_event(13, "EVENT_TYPE_ACTIVITY_TASK_STARTED", "activityTaskStartedEventAttributes", {
            "scheduledEventId": "12", "identity": V2_IDENTITY, "attempt": 1,
            "workerVersion": {"buildId": V2_BUILD, "useVersioning": True},
        }),
        _manual_event(14, "EVENT_TYPE_ACTIVITY_TASK_COMPLETED", "activityTaskCompletedEventAttributes", {
            "result": _encoded_payload(query_bytes),
            "scheduledEventId": "12", "startedEventId": "13", "identity": V2_IDENTITY,
        }),
        _manual_event(15, "EVENT_TYPE_WORKFLOW_TASK_SCHEDULED", "workflowTaskScheduledEventAttributes",
                      _manual_sticky_schedule()),
        _manual_event(16, "EVENT_TYPE_WORKFLOW_TASK_STARTED", "workflowTaskStartedEventAttributes", {
            "scheduledEventId": "15", "identity": V2_IDENTITY,
        }),
        _manual_event(17, "EVENT_TYPE_WORKFLOW_TASK_COMPLETED", "workflowTaskCompletedEventAttributes",
                      _manual_wft_completion("15", "16")),
    ]
    if case_name == "h0":
        tail.append(_manual_event(
            18, "EVENT_TYPE_WORKFLOW_EXECUTION_FAILED", "workflowExecutionFailedEventAttributes", {
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
        ))
        return tail

    _require(case_name == "h1", "manual final case differs")
    expected_completion = _expected_provider_record(
        _completion_operation_id(), "/v1/complete", "temporal-completion",
    )
    _require(completion_fact == expected_completion, "completion receipt is not paired with the provider fact")
    receipt = {
        "schema": 1,
        "operation_id": expected_completion["operation_id"],
        "outcome": "succeeded",
        "result_hash": expected_completion["result_hash"],
        "remote_reference": expected_completion["remote_reference"],
    }
    tail.extend([
        _manual_event(18, "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED", "activityTaskScheduledEventAttributes",
                      _manual_activity_schedule("18", "CompleteOrder", _completion_operation_id(), "17")),
        _manual_event(19, "EVENT_TYPE_ACTIVITY_TASK_STARTED", "activityTaskStartedEventAttributes", {
            "scheduledEventId": "18", "identity": V2_IDENTITY, "attempt": 1,
            "workerVersion": {"buildId": V2_BUILD, "useVersioning": True},
        }),
        _manual_event(20, "EVENT_TYPE_ACTIVITY_TASK_COMPLETED", "activityTaskCompletedEventAttributes", {
            "result": _encoded_payload(json.dumps(receipt, separators=(",", ":")).encode()),
            "scheduledEventId": "18", "startedEventId": "19", "identity": V2_IDENTITY,
        }),
        _manual_event(21, "EVENT_TYPE_WORKFLOW_TASK_SCHEDULED", "workflowTaskScheduledEventAttributes",
                      _manual_sticky_schedule()),
        _manual_event(22, "EVENT_TYPE_WORKFLOW_TASK_STARTED", "workflowTaskStartedEventAttributes", {
            "scheduledEventId": "21", "identity": V2_IDENTITY,
        }),
        _manual_event(23, "EVENT_TYPE_WORKFLOW_TASK_COMPLETED", "workflowTaskCompletedEventAttributes",
                      _manual_wft_completion("21", "22")),
        _manual_event(24, "EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED", "workflowExecutionCompletedEventAttributes", {
            "result": _encoded_payload(json.dumps(_manual_order_result(), separators=(",", ":")).encode()),
            "workflowTaskCompletedEventId": "23",
        }),
    ])
    return tail


def _check_final_manual(
    results: Path, run_id: str, case_name: str, operation_id: str,
    provider_facts: dict[str, dict[str, Any] | None],
) -> int:
    history = _json(results / "final-history.json")
    _require(set(history) == {"events"}, "manual final History fields differ")
    events = _array(history["events"], "manual final History events")
    _require(history["events"][:8] == _json(results / "pre-v2-history.json")["events"], "final History does not extend pre-v2 History")
    for index, event in enumerate(events, 1):
        event = _object(event, "manual final History event")
        _require(event.get("eventId") == str(index), "manual final History event IDs differ")
        _require(isinstance(event.get("eventTime"), str) and event["eventTime"], "manual final event time is absent")
        _require(isinstance(event.get("taskId"), str) and event["taskId"].isdigit(), "manual final task ID differs")

    _check_business_signals(events)
    _require(
        not any(
            event.get("eventType") == "EVENT_TYPE_WORKFLOW_TASK_FAILED"
            for event in events if isinstance(event, dict)
        ),
        "manual execution produced a Workflow task failure",
    )

    schedules = [
        _object(event, "Activity schedule event") for event in events
        if isinstance(event, dict) and event.get("eventType") == "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED"
    ]
    schedule_types = [
        event.get("activityTaskScheduledEventAttributes", {}).get("activityType", {}).get("name")
        for event in schedules
    ]
    expected_types = ["ChargePayment", "QueryPayment"]
    if case_name == "h1":
        expected_types.extend(["PrepareFood", "ScheduleDelivery", "CompleteOrder"])
    _require(schedule_types == expected_types, "manual Activity sequence differs")
    for event in schedules[1:]:
        _check_post_cut_activity_schedule(event, operation_id)

    starts_by_schedule: dict[str, dict[str, Any]] = {}
    completions_by_schedule: dict[str, dict[str, Any]] = {}
    for event in events[8:]:
        if not isinstance(event, dict):
            continue
        if event.get("eventType") == "EVENT_TYPE_ACTIVITY_TASK_STARTED":
            attributes = _object(event.get("activityTaskStartedEventAttributes"), "post-cut Activity start")
            scheduled_id = attributes.get("scheduledEventId")
            _require(isinstance(scheduled_id, str) and scheduled_id not in starts_by_schedule, "post-cut Activity start identity differs")
            _require(
                attributes.get("identity") == V2_IDENTITY and attributes.get("attempt") == 1 and
                attributes.get("workerVersion") == {"buildId": V2_BUILD, "useVersioning": True} and
                isinstance(attributes.get("requestId"), str) and attributes["requestId"],
                "post-cut Activity ran on the wrong worker",
            )
            starts_by_schedule[scheduled_id] = attributes
        elif event.get("eventType") == "EVENT_TYPE_ACTIVITY_TASK_COMPLETED":
            attributes = _object(event.get("activityTaskCompletedEventAttributes"), "post-cut Activity completion")
            scheduled_id = attributes.get("scheduledEventId")
            _require(isinstance(scheduled_id, str) and scheduled_id not in completions_by_schedule, "post-cut Activity completion identity differs")
            _require(attributes.get("identity") == V2_IDENTITY, "post-cut Activity completion worker differs")
            completions_by_schedule[scheduled_id] = attributes

    post_schedules = {event["eventId"]: event for event in schedules[1:]}
    _require(set(starts_by_schedule) == set(post_schedules), "post-cut Activity start set differs")
    _require(set(completions_by_schedule) == set(post_schedules), "post-cut Activity completion set differs")
    query_event = schedules[1]
    query_completion = completions_by_schedule[query_event["eventId"]]
    _check_manual_query_result(
        query_completion.get("result"), case_name, operation_id, provider_facts.get("payment"),
    )

    if case_name == "h1":
        activity_results = {
            event.get("activityTaskScheduledEventAttributes", {}).get("activityType", {}).get("name"):
            completions_by_schedule[event["eventId"]]
            for event in schedules[2:]
        }
        _require(
            _json_payload_object(activity_results["PrepareFood"].get("result"), "PrepareFood result") == {
                "schema": 1, "order_id": ORDER_ID, "restaurant_id": RESTAURANT_ID,
                "product_count": PRODUCT_QUANTITY, "outcome": "accepted",
            },
            "PrepareFood result differs",
        )
        _require(
            _json_payload_object(activity_results["ScheduleDelivery"].get("result"), "ScheduleDelivery result") == {
                "schema": 1, "order_id": ORDER_ID, "delivery_id": DELIVERY_ID,
                "restaurant_id": RESTAURANT_ID, "region": "San Jose (CA)", "outcome": "scheduled",
            },
            "ScheduleDelivery result differs",
        )
        completion_fact = provider_facts.get("completion")
        _require(isinstance(completion_fact, dict), "H1 completion provider fact is absent")
        _require(
            _json_payload_object(activity_results["CompleteOrder"].get("result"), "CompleteOrder result") == {
                "schema": 1, "operation_id": _completion_operation_id(), "outcome": "succeeded",
                "result_hash": completion_fact["result_hash"],
                "remote_reference": completion_fact["remote_reference"],
            },
            "CompleteOrder result differs from the provider fact",
        )
        timer_starts = [
            _object(event, "preparation timer start") for event in events
            if isinstance(event, dict) and event.get("eventType") == "EVENT_TYPE_TIMER_STARTED"
        ]
        timer_fires = [
            _object(event, "preparation timer fire") for event in events
            if isinstance(event, dict) and event.get("eventType") == "EVENT_TYPE_TIMER_FIRED"
        ]
        _require(len(timer_starts) == 1 and len(timer_fires) == 1, "preparation timer event set differs")
        timer_start = _object(timer_starts[0].get("timerStartedEventAttributes"), "preparation timer start")
        timer_fire = _object(timer_fires[0].get("timerFiredEventAttributes"), "preparation timer fire")
        _require(
            timer_start.get("timerId") == timer_starts[0].get("eventId") and
            timer_start.get("startToFireTimeout") == "0.025s" and
            timer_fire.get("timerId") == timer_start.get("timerId") and
            timer_fire.get("startedEventId") == timer_starts[0].get("eventId"),
            "preparation timer semantics differ",
        )
    else:
        _require(
            not any(
                event.get("eventType") in {"EVENT_TYPE_TIMER_STARTED", "EVENT_TYPE_TIMER_FIRED"}
                for event in events if isinstance(event, dict)
            ),
            "H0 progressed into preparation",
        )

    terminal = _object(events[-1], "manual terminal event")
    if case_name == "h0":
        _require(terminal.get("eventType") == "EVENT_TYPE_WORKFLOW_EXECUTION_FAILED", "H0 terminal event differs")
        terminal_attributes = _object(
            terminal.get("workflowExecutionFailedEventAttributes"), "H0 terminal failure",
        )
        completed_id = terminal_attributes.get("workflowTaskCompletedEventId")
        _require(isinstance(completed_id, str) and completed_id.isdigit(), "H0 terminal Workflow task differs")
        _require(
            {key: value for key, value in terminal_attributes.items() if key != "workflowTaskCompletedEventId"} == {
                "failure": {
                    "message": "manual payment reconciliation was inconclusive", "source": "GoSDK",
                    "applicationFailureInfo": {
                        "type": "ManualPaymentReconciliationFailed", "nonRetryable": True,
                    },
                },
                "retryState": "RETRY_STATE_RETRY_POLICY_NOT_SET",
            },
            "H0 terminal failure is not the exact nonretryable reconciliation failure",
        )
    else:
        _require(terminal.get("eventType") == "EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED", "H1 terminal event differs")
        terminal_attributes = _object(
            terminal.get("workflowExecutionCompletedEventAttributes"), "H1 terminal completion",
        )
        _require(set(terminal_attributes) == {"result", "workflowTaskCompletedEventId"}, "H1 terminal fields differ")
        _require(
            _json_payload_object(terminal_attributes["result"], "H1 Workflow result") == _manual_order_result(),
            "H1 terminal result differs",
        )

    final = _json(results / "final-describe.json")
    expected_keys = {"closeEvent", "executionConfig", "workflowExecutionInfo", "workflowExtendedInfo"}
    if case_name == "h1":
        expected_keys.add("result")
    _require(set(final) == expected_keys, "manual final describe fields differ")
    info = _object(final.get("workflowExecutionInfo"), "manual final Workflow info")
    expected_status = (
        "WORKFLOW_EXECUTION_STATUS_FAILED" if case_name == "h0" else
        "WORKFLOW_EXECUTION_STATUS_COMPLETED"
    )
    _require(info.get("execution") == {"workflowId": WORKFLOW_ID, "runId": run_id}, "manual final execution differs")
    _require(info.get("firstRunId") == run_id, "manual final first run differs")
    _require(info.get("rootExecution") == {"workflowId": WORKFLOW_ID, "runId": run_id}, "manual final root execution differs")
    _require(info.get("status") == expected_status, "manual final Workflow status differs")
    _require(info.get("historyLength") == str(len(events)), "manual final History length metadata differs")
    _require(info.get("type") == {"name": "FoodOrderManualBranch"}, "manual final Workflow type differs")
    _require(
        info.get("taskQueue") == TASK_QUEUE and info.get("workerDeploymentName") == DEPLOYMENT and
        info.get("mostRecentWorkerVersionStamp") == {"buildId": V2_BUILD, "useVersioning": True},
        "manual final Workflow queue/version differs",
    )
    _require(
        info.get("versioningInfo") == {
            "behavior": "VERSIONING_BEHAVIOR_AUTO_UPGRADE",
            "deploymentVersion": {"buildId": V2_BUILD, "deploymentName": DEPLOYMENT},
            "revisionNumber": "2",
            "version": f"{DEPLOYMENT}.{V2_BUILD}",
        },
        "manual final execution is not bound to v2",
    )

    close = _object(final.get("closeEvent"), "manual close event")
    close_attribute = (
        "workflowExecutionFailedEventAttributes" if case_name == "h0" else
        "workflowExecutionCompletedEventAttributes"
    )
    _require(
        set(close) == {"eventId", "eventTime", "eventType", "taskId", close_attribute},
        "manual close event fields differ",
    )
    _require(close.get("eventId") == str(len(events)), "manual close event ID differs")
    _require(close.get("eventType") == events[-1].get("eventType"), "manual close event type differs")
    _require(close.get("eventTime") == events[-1].get("eventTime"), "manual close event time differs")
    _require(close.get("taskId") == events[-1].get("taskId"), "manual close task ID differs")
    if case_name == "h0":
        _require("result" not in final, "H0 unexpectedly contains a Workflow result")
        _require(
            close.get("workflowExecutionFailedEventAttributes") ==
            events[-1].get("workflowExecutionFailedEventAttributes"),
            "H0 close failure differs from History",
        )
    else:
        result = _manual_order_result()
        _require(final.get("result") == result, "H1 final result differs")
        _require(
            close.get("workflowExecutionCompletedEventAttributes") == {
                "result": [result],
                "workflowTaskCompletedEventId": terminal_attributes["workflowTaskCompletedEventId"],
            },
            "H1 close result differs from History",
        )
    return 0


def _check_final(
    results: Path, run_id: str, pre_v2: dict[str, Any], mode: str = "auto_upgrade",
    case_name: str | None = None, operation_id: str | None = None,
    provider_facts: dict[str, dict[str, Any] | None] | None = None,
) -> int:
    _require(mode in {"auto_upgrade", "pinned", "manual_branch"}, "Temporal mode differs")
    if mode == "manual_branch":
        _require(case_name in {"h0", "h1"}, "manual final case differs")
        _require(isinstance(operation_id, str), "manual Operation identity is absent")
        _require(provider_facts is not None, "manual provider facts are absent")
        return _check_final_manual(results, run_id, case_name, operation_id, provider_facts)
    history = _json(results / "final-history.json")
    events = _array(history.get("events"), "final History")
    _require(history["events"][:8] == _json(results / "pre-v2-history.json")["events"], "final History does not extend pre-v2 History")
    _check_business_signals(events)
    failures = [
        event for event in events
        if isinstance(event, dict) and event.get("eventType") == "EVENT_TYPE_WORKFLOW_TASK_FAILED"
    ]
    later_starts = [
        event.get("workflowTaskStartedEventAttributes", {}).get("identity")
        for event in events[8:]
        if isinstance(event, dict) and event.get("eventType") == "EVENT_TYPE_WORKFLOW_TASK_STARTED"
    ]
    if mode == "auto_upgrade":
        _require(len(failures) >= 1, "v2 did not produce a Workflow task failure")
        for event in failures:
            attributes = _object(event.get("workflowTaskFailedEventAttributes"), "Workflow task failure")
            failure = _object(attributes.get("failure"), "Workflow task failure detail")
            _require(
                attributes.get("cause") == NONDETERMINISM and attributes.get("identity") == V2_IDENTITY and
                failure.get("message") == NONDETERMINISM_MESSAGE and failure.get("source") == "GoSDK",
                "v2 failure is not the expected replay nondeterminism",
            )
        _require(
            later_starts and all(identity == V2_IDENTITY for identity in later_starts),
            "a post-cut Workflow task ran on the wrong worker",
        )
    else:
        _require(not failures, "Pinned execution produced a Workflow task failure")
        _require(not later_starts, "Pinned execution ran after its v1 worker stopped")
        tail = [
            event for event in events[8:]
            if isinstance(event, dict) and
            event.get("eventType") != "EVENT_TYPE_WORKFLOW_EXECUTION_SIGNALED"
        ]
        expected_tail = sorted([
            "EVENT_TYPE_WORKFLOW_TASK_SCHEDULED",
            "EVENT_TYPE_WORKFLOW_TASK_TIMED_OUT",
        ])
        _require(
            len(tail) == 2 and
            sorted(event.get("eventType") for event in tail) == expected_tail,
            "Pinned final History tail differs",
        )
        timed_out = next(
            event for event in tail if event.get("eventType") == "EVENT_TYPE_WORKFLOW_TASK_TIMED_OUT"
        )
        _require(
            timed_out.get("workflowTaskTimedOutEventAttributes") == {
                "scheduledEventId": "8", "timeoutType": "TIMEOUT_TYPE_SCHEDULE_TO_START",
            },
            "Pinned Workflow task timeout differs",
        )
        scheduled = next(
            event for event in tail if event.get("eventType") == "EVENT_TYPE_WORKFLOW_TASK_SCHEDULED"
        )
        _require(
            scheduled.get("workflowTaskScheduledEventAttributes") == {
                "taskQueue": {"name": TASK_QUEUE, "kind": "TASK_QUEUE_KIND_NORMAL"},
                "startToCloseTimeout": "10s", "attempt": 1,
            },
            "Pinned Workflow task reschedule differs",
        )
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
    _require(info.get("type") == {"name": _workflow_name(mode)}, "final Workflow type differs")
    _require(
        info.get("taskQueue") == TASK_QUEUE and info.get("workerDeploymentName") == DEPLOYMENT and
        info.get("mostRecentWorkerVersionStamp") == {"buildId": V1_BUILD, "useVersioning": True},
        "final Workflow queue/version differs",
    )
    versioning = _object(info.get("versioningInfo"), "final versioning info")
    if mode == "auto_upgrade":
        _require(
            versioning.get("behavior") == "VERSIONING_BEHAVIOR_AUTO_UPGRADE" and
            versioning.get("deploymentVersion") == {"buildId": V1_BUILD, "deploymentName": DEPLOYMENT} and
            versioning.get("versionTransition", {}).get("deploymentVersion") == {"buildId": V2_BUILD, "deploymentName": DEPLOYMENT},
            "final v2 version transition differs",
        )
    else:
        _require(
            versioning.get("behavior") == "VERSIONING_BEHAVIOR_PINNED" and
            versioning.get("version") == f"{DEPLOYMENT}.{V1_BUILD}" and
            versioning.get("deploymentVersion") == {"buildId": V1_BUILD, "deploymentName": DEPLOYMENT} and
            versioning.get("revisionNumber") == "1" and "versionTransition" not in versioning,
            "Pinned execution did not remain bound to v1",
        )
        pending = _object(final.get("pendingWorkflowTask"), "final pending Workflow task")
        _require(
            pending.get("state") == "PENDING_WORKFLOW_TASK_STATE_SCHEDULED" and
            pending.get("attempt") == 1 and isinstance(pending.get("scheduledTime"), str) and
            isinstance(pending.get("originalScheduledTime"), str),
            "Pinned execution is not stranded waiting for v1",
        )
    return len(failures)


def _check_case(root: Path, case_name: str) -> dict[str, Any]:
    results = _results_dir(root)
    _verify_checksums(results)
    _require(_read(results / "exit-status.txt") == b"0\n", f"{case_name} runner did not exit successfully")
    versions_data, build_data, build = _check_build(results)
    versions = _parse_env(versions_data, "versions.env")

    observed = _json(results / "observed.json")
    mode = observed.get("mode")
    _require(mode in {"auto_upgrade", "pinned", "manual_branch"}, f"{case_name} Temporal mode differs")

    start = _json(results / "start.json")
    expected_behavior = {
        "auto_upgrade": "autoupgrade", "pinned": "pinned", "manual_branch": "manual",
    }[mode]
    _require(
        set(start) == {"schema", "behavior", "workflow_id", "run_id"} and
        start.get("schema") == 1 and start.get("behavior") == expected_behavior and
        start.get("workflow_id") == WORKFLOW_ID and isinstance(start.get("run_id"), str) and start["run_id"],
        f"{case_name} start record differs",
    )
    run_id = start["run_id"]
    cut_history, operation_id = _check_cut_history(results, run_id, mode)
    cut_describe = _check_cut_describe(results, run_id, mode)
    provider_facts = _check_provider(results, case_name, operation_id, mode)
    _check_deployments(results)
    _check_containers(results, build, versions)
    pre_v2 = _check_pre_v2(results, run_id, cut_history)
    failure_count = _check_final(
        results, run_id, pre_v2, mode, case_name, operation_id, provider_facts,
    )

    expected_commits = 0 if case_name == "h0" else 1
    completion_commits = 1 if mode == "manual_branch" and case_name == "h1" else 0
    final_status = "WORKFLOW_EXECUTION_STATUS_RUNNING"
    if mode == "manual_branch":
        final_status = (
            "WORKFLOW_EXECUTION_STATUS_FAILED" if case_name == "h0" else
            "WORKFLOW_EXECUTION_STATUS_COMPLETED"
        )
    _require(
        observed == {
            "schema": 1,
            "case": case_name,
            "mode": mode,
            "workflow_id": WORKFLOW_ID,
            "run_id": run_id,
            "final_status": final_status,
            "workflow_task_failures": failure_count,
            "payment": {"deliveries": 1, "commits": expected_commits, "paths": {"/v1/charge": 1}},
            "completion": {
                "deliveries": completion_commits,
                "commits": completion_commits,
                "paths": {"/v1/complete": 1} if completion_commits else {},
            },
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
        "final_status": final_status,
        "mode": mode,
    }


def check_pair(h0_root: Path, h1_root: Path) -> dict[str, Any]:
    h0 = _check_case(h0_root, "h0")
    h1 = _check_case(h1_root, "h1")
    _require(h0["versions_data"] == h1["versions_data"], "H0/H1 versions differ")
    _require(h0["build_data"] == h1["build_data"], "H0/H1 builds differ")
    _require(h0["mode"] == h1["mode"], "H0/H1 Temporal modes differ")
    _require(h0["operation_id"] == h1["operation_id"], "H0/H1 Operation identity differs")
    _require(h0["cut_history"] == h1["cut_history"], "H0/H1 cut History semantics differ")
    _require(h0["cut_describe"] == h1["cut_describe"], "H0/H1 pending Activity semantics differ")
    _require(h0["pre_v2"] == h1["pre_v2"], "H0/H1 pre-v2 History semantics differ")
    _require(h0["run_id"] != h1["run_id"], "H0/H1 unexpectedly reused a Temporal run")
    return {
        "valid": True,
        "mode": h0["mode"],
        "workflow_id": WORKFLOW_ID,
        "operation_id": h0["operation_id"],
        "cut_history_equal": True,
        "pending_activity_equal": True,
        "h0_payment_commits": 0,
        "h1_payment_commits": 1,
        "h0_final_status": h0["final_status"],
        "h1_final_status": h1["final_status"],
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
