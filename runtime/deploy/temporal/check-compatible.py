#!/usr/bin/env python3
"""Fail-closed checker for raw Temporal AutoUpgrade compatible-control evidence.

`observed.json` and `invocation.json` are checksum-covered convenience files.
They are deliberately never parsed or used as evidence.
"""

from __future__ import annotations

import argparse
import base64
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
from typing import Any


MAX_FILE_BYTES = 64 << 20
MAX_EVIDENCE_BYTES = 192 << 20
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")

WORKFLOW_ID = "temporal-compatible-order-1"
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
TARGET_BUILD = "food-order-compatible-v2"
V1_IDENTITY = "safe-change-food-order-v1-worker"
TARGET_IDENTITY = "safe-change-food-order-compatible-v2-worker"
SIGNAL_IDENTITY = "safe-change-compatible-harness"
BUSINESS_SIGNALS = (
    "preparation_finished", "driver_selected", "driver_at_restaurant", "delivery_finished",
)
WORKFLOW_TYPE = "FoodOrderAutoUpgrade"
FROZEN_V1_IMAGE_ID = "sha256:8a236550df67fe5cd334fd05bd092ff6457daf80ba7fd0077f1a98a6bdcd919f"
FROZEN_TARGET_IMAGE_ID = "sha256:dd422ae6d892c7aa31bad97c6f8b97e872011ef5c2a759aeb2a8cd83d9df8853"
FROZEN_V1_BINARY_SHA256 = "98a12265e86a04c3cf384ab36c05f55973f1751914c66d51c89da5b1cd1deac3"
FROZEN_TARGET_BINARY_SHA256 = "4c1a9b03807ed1a5cc624050eede3eb597f60c8e316e3b427dbc7e31fac8767d"
FROZEN_VERSIONS_SHA256 = "c0fbc207ce2a462f364d56173004eaad2b2a3d8dd2fe040b0123352505a0edd3"
FROZEN_COMPATIBLE_BUILD_SHA256 = "495e37bda60465e4be169605449a6d586f705faac95cbeb57f0ea49ab97a7fa5"
FROZEN_GIT_REVISION = "65988afbfc2fad82fdcc485fbc8f67dbc3b628cc"
FROZEN_SOURCE_SHA256 = "877a7a5b71b24e3dc309af5cd23bebe77c40dab6b8aec659ef929f1dc771aade"
FROZEN_RUNTIME_SOURCE_SHA256 = "e95760a49a36fa0dbf8136589545b5499a99e353baabae44c6c11e37ed581059"

TEMPORAL_IMAGE = (
    "docker.io/temporalio/temporal:1.8.2@"
    "sha256:cf86707827fac99e4d1c4a47dc11b105382d796199c7bd41fb3213fb0471628e"
)
GO_IMAGE = (
    "docker.io/library/golang:1.25.13-alpine@"
    "sha256:844b27705f54e73773e0f9bc3c780633b9d7f4b4831bf35cdad02a81a4c80bd0"
)
RUNTIME_IMAGE = (
    "docker.io/library/alpine:3.22.2@"
    "sha256:4b7ce07002c69e8f3d704a9c5d6fd3053be500b7f1c69fc0d80990c2ad8dd412"
)

EXPECTED_CUT_TYPES = [
    "EVENT_TYPE_WORKFLOW_EXECUTION_STARTED",
    "EVENT_TYPE_WORKFLOW_TASK_SCHEDULED",
    "EVENT_TYPE_WORKFLOW_TASK_STARTED",
    "EVENT_TYPE_WORKFLOW_TASK_COMPLETED",
    "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED",
    "EVENT_TYPE_ACTIVITY_TASK_STARTED",
    "EVENT_TYPE_ACTIVITY_TASK_COMPLETED",
    "EVENT_TYPE_WORKFLOW_TASK_SCHEDULED",
    "EVENT_TYPE_WORKFLOW_TASK_STARTED",
    "EVENT_TYPE_WORKFLOW_TASK_COMPLETED",
]
EXPECTED_FINAL_TYPES = EXPECTED_CUT_TYPES + [
    "EVENT_TYPE_WORKFLOW_EXECUTION_SIGNALED",
    "EVENT_TYPE_WORKFLOW_TASK_SCHEDULED",
    "EVENT_TYPE_WORKFLOW_TASK_STARTED",
    "EVENT_TYPE_WORKFLOW_TASK_COMPLETED",
    "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED",
    "EVENT_TYPE_ACTIVITY_TASK_STARTED",
    "EVENT_TYPE_ACTIVITY_TASK_COMPLETED",
    "EVENT_TYPE_WORKFLOW_TASK_SCHEDULED",
    "EVENT_TYPE_WORKFLOW_TASK_STARTED",
    "EVENT_TYPE_WORKFLOW_TASK_COMPLETED",
    "EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED",
]

REQUIRED_FILES = {
    "SHA256SUMS", "binary-verification.env", "build.env", "build.log", "compatible-activity-pollers.json",
    "compatible-image-inspect.json", "compatible-running-inspect.json",
    "compatible-workflow-pollers.json", "compatible.log", "completion-cut-stats.json",
    "completion-cut.history", "completion-final-stats.json", "completion-final.history",
    "compose-config.yaml", "compose-ps.txt", "compose.log", "containers-before-target.json",
    "containers-cut.json", "containers-final.json", "cut-describe.json",
    "cut-history-after.json", "cut-history-before.json", "cut-query.json",
    "deployment-before-current.json", "deployment-compatible-current.json",
    "deployment-final.json", "deployment-v1-current.json", "effects-image-inspect.json",
    "exit-status.txt", "final-describe.json", "final-history.json", "final-query.json",
    "invocation.json", "observed.json", "payment-cut-stats.json", "payment-cut.history",
    "payment-final-stats.json", "payment-final.history", "remove-v1.txt", "runner.sh",
    "set-current-compatible.json", "set-current-v1.json", "signal-delivery-finished.json",
    "signal-driver-at-restaurant.json", "signal-driver-selected.json",
    "signal-preparation-finished.json",
    "source-activities.go", "source-types.go", "source-variant-compatible-v2.go",
    "source-variant-v1.go", "source-workflows.go", "source-starter.go",
    "start.json", "starter-image-inspect.json",
    "v1-activity-pollers.json", "v1-after-remove.txt", "v1-image-inspect.json",
    "v1-removed-inspect-status.txt", "v1-removed-inspect.json",
    "v1-removed-inspect.stderr", "v1-running-inspect.json", "v1-workflow-pollers.json",
    "v1.log", "version-compatible-before-current.json", "version-compatible-current.json",
    "version-v1.json", "versions.env",
}

BUILD_KEYS = {
    "GIT_REVISION", "SOURCE_SHA256",
    "WORKER_V1_IMAGE", "WORKER_V1_ID", "WORKER_V1_BINARY_SHA256",
    "WORKER_V1_VARIANT_SHA256", "WORKER_V2_IMAGE", "WORKER_V2_ID",
    "WORKER_V2_BINARY_SHA256", "WORKER_COMPATIBLE_V2_IMAGE",
    "WORKER_COMPATIBLE_V2_ID", "WORKER_COMPATIBLE_V2_BINARY_SHA256",
    "WORKER_COMPATIBLE_V2_VARIANT_SHA256", "STARTER_IMAGE", "STARTER_ID",
    "STARTER_BINARY_SHA256", "RUNTIME_SOURCE_SHA256", "EFFECTS_IMAGE",
    "EFFECTS_ID", "EFFECTS_BINARY_SHA256",
}

FROZEN_BUILD_PROFILES = {
    FROZEN_COMPATIBLE_BUILD_SHA256: {
        "name": "step-0016-full-food-order-compatible",
        "git_revision": FROZEN_GIT_REVISION,
        "source_sha256": FROZEN_SOURCE_SHA256,
        "runtime_source_sha256": FROZEN_RUNTIME_SOURCE_SHA256,
    },
}

FROZEN_ARCHIVED_FILE_SHA256 = {
    "binary-verification.env": "fd90ae3edbf8fb689c71cdead773597b2880bace2e59669553cca6abc93295c7",
    "runner.sh": "bcf378f4f9b22f6ee8ac9b5da70367b2455a1c8203d5fb9c4d77c5489de556ed",
    "source-activities.go": "96a7eaa2518658f5790fcd577141a5bf6210c9201455729271afb9d3e3e3095a",
    "source-types.go": "b8b5de1b534687d67dd8f232f893b41e43261cf1d6271e997c069e915cc91b23",
    "source-variant-compatible-v2.go": "1c8d84c2db049407ad6587f8b48388ac92a5db783c241d328feadf913c9a4b38",
    "source-variant-v1.go": "46b82cdab94d538051928e3322cefee2eca3a5cdaf502f1ccad03d6c8b03621b",
    "source-workflows.go": "8e498105a55f4c272cf0a4b3d4d0461bb81711a21d13fc0558c4faa710bca88b",
    "source-starter.go": "bcf831df018af843519483a7d2b3e88c286ef201e99463da1e578bf169417473",
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
    _require(not root.is_symlink(), "evidence root must not be a symlink")
    candidate = root / "results"
    results = candidate if candidate.is_dir() else root
    _require(results.is_dir() and not results.is_symlink(), "results directory is absent or unsafe")
    return results


def _read(path: Path) -> bytes:
    _require(path.exists(), f"missing evidence file: {path.name}")
    _require(path.is_file() and not path.is_symlink(), f"unsafe evidence file: {path.name}")
    _require(path.stat().st_size <= MAX_FILE_BYTES, f"evidence file is too large: {path.name}")
    return path.read_bytes()


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(_read(path))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvidenceError(f"{path.name} is not JSON") from error
    return _object(value, path.name)


def _json_array(path: Path) -> list[Any]:
    try:
        value = json.loads(_read(path))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvidenceError(f"{path.name} is not JSON") from error
    return _array(value, path.name)


def _verify_checksums(results: Path) -> None:
    entries = list(results.iterdir())
    _require(all(item.is_file() and not item.is_symlink() for item in entries), "results contains an unsafe entry")
    _require(sum(item.stat().st_size for item in entries) <= MAX_EVIDENCE_BYTES, "evidence exceeds size limit")
    names = {item.name for item in entries}
    _require(names == REQUIRED_FILES, "evidence file set differs")
    declared: dict[str, str] = {}
    try:
        lines = _read(results / "SHA256SUMS").decode("ascii").splitlines()
    except UnicodeDecodeError as error:
        raise EvidenceError("SHA256SUMS is not ASCII") from error
    for line in lines:
        parts = line.split("  ", 1)
        _require(len(parts) == 2 and HEX64.fullmatch(parts[0]) is not None, "invalid SHA256SUMS line")
        name = parts[1]
        _require(name.startswith("./") and "/" not in name[2:] and name[2:] != "SHA256SUMS", "unsafe checksum path")
        name = name[2:]
        _require(name not in declared, "duplicate checksum entry")
        declared[name] = parts[0]
    _require(set(declared) == names - {"SHA256SUMS"}, "SHA256SUMS coverage differs")
    for name, expected in declared.items():
        _require(sha256(_read(results / name)).hexdigest() == expected, f"checksum mismatch: {name}")


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
        _require(re.fullmatch(r"[A-Z0-9_]+", key) is not None and key not in parsed, f"invalid {label} key")
        parsed[key] = value
    return parsed


def _frozen_build_profile(build_data: bytes, build: dict[str, str]) -> dict[str, str]:
    digest = sha256(build_data).hexdigest()
    profile = FROZEN_BUILD_PROFILES.get(digest)
    _require(profile is not None, "unsupported frozen compatible build profile")
    assert profile is not None
    _require(set(build) == BUILD_KEYS, "build.env fields differ")
    _require(
        build.get("GIT_REVISION") == profile["git_revision"] and
        build.get("SOURCE_SHA256") == profile["source_sha256"] and
        build.get("RUNTIME_SOURCE_SHA256") == profile["runtime_source_sha256"],
        "frozen compatible build identity differs",
    )
    return profile


def _require_commit_object(repo_root: Path, revision: str) -> None:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "cat-file", "-e", f"{revision}^{{commit}}"],
        check=False, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    _require(result.returncode == 0, "recorded build revision commit object is absent")


def _check_build(results: Path) -> dict[str, str]:
    temporal_dir = Path(__file__).resolve().parent
    repo_root = temporal_dir.parents[2]
    versions_data = _read(results / "versions.env")
    _require(sha256(versions_data).hexdigest() == FROZEN_VERSIONS_SHA256, "unsupported frozen versions profile")
    versions = _parse_env(versions_data, "versions.env")
    _require(versions.get("TEMPORAL_CLI_VERSION") == "1.8.2", "Temporal CLI version differs")
    _require(versions.get("TEMPORAL_SERVER_VERSION") == "1.31.2", "Temporal Server version differs")
    _require(versions.get("TEMPORAL_GO_SDK_VERSION") == "v1.47.0", "Temporal SDK version differs")
    _require(versions.get("TEMPORAL_IMAGE") == TEMPORAL_IMAGE, "Temporal image differs")
    _require(versions.get("TEMPORAL_GO_IMAGE") == GO_IMAGE, "Go image differs")
    _require(versions.get("TEMPORAL_RUNTIME_IMAGE") == RUNTIME_IMAGE, "runtime image differs")

    build_data = _read(results / "build.env")
    build = _parse_env(build_data, "build.env")
    profile = _frozen_build_profile(build_data, build)
    _require(HEX40.fullmatch(build["GIT_REVISION"]) is not None, "Git revision is invalid")
    for key, value in build.items():
        if key.endswith("_SHA256"):
            _require(HEX64.fullmatch(value) is not None, f"{key} is not SHA-256")
        if key.endswith("_ID"):
            _require(IMAGE_ID.fullmatch(value) is not None, f"{key} is not an image ID")
    _require(
        len({build["WORKER_V1_ID"], build["WORKER_V2_ID"], build["WORKER_COMPATIBLE_V2_ID"]}) == 3,
        "worker image IDs are not distinct",
    )
    _require(
        build["WORKER_V1_ID"] == FROZEN_V1_IMAGE_ID and
        build["WORKER_COMPATIBLE_V2_ID"] == FROZEN_TARGET_IMAGE_ID and
        build["WORKER_V1_BINARY_SHA256"] == FROZEN_V1_BINARY_SHA256 and
        build["WORKER_COMPATIBLE_V2_BINARY_SHA256"] == FROZEN_TARGET_BINARY_SHA256,
        "frozen compatible worker provenance differs",
    )
    binary_verification = _parse_env(_read(results / "binary-verification.env"), "binary-verification.env")
    _require(set(binary_verification) == {
        "WORKER_V1_BINARY_SHA256", "WORKER_COMPATIBLE_V2_BINARY_SHA256",
    }, "binary verification fields differ")
    _require(
        binary_verification["WORKER_V1_BINARY_SHA256"] == build["WORKER_V1_BINARY_SHA256"] and
        binary_verification["WORKER_COMPATIBLE_V2_BINARY_SHA256"] == build["WORKER_COMPATIBLE_V2_BINARY_SHA256"],
        "extracted worker binary hash differs",
    )
    for key in ("WORKER_V1_IMAGE", "WORKER_V2_IMAGE", "WORKER_COMPATIBLE_V2_IMAGE", "STARTER_IMAGE", "EFFECTS_IMAGE"):
        _require("latest" not in build[key], f"mutable latest tag in {key}")
    _require_commit_object(repo_root, profile["git_revision"])

    for evidence_name, expected_digest in FROZEN_ARCHIVED_FILE_SHA256.items():
        _require(
            sha256(_read(results / evidence_name)).hexdigest() == expected_digest,
            f"{evidence_name} differs from its frozen archived profile",
        )
    v1 = _read(results / "source-variant-v1.go")
    target = _read(results / "source-variant-compatible-v2.go")
    _require(sha256(v1).hexdigest() == build["WORKER_V1_VARIANT_SHA256"], "v1 variant hash differs")
    _require(sha256(target).hexdigest() == build["WORKER_COMPATIBLE_V2_VARIANT_SHA256"], "target variant hash differs")
    expected = v1
    replacements = (
        (b"//go:build worker_v1", b"//go:build worker_compatible_v2"),
        (b'const buildID = "food-order-v1"', b'const buildID = "food-order-compatible-v2"'),
        (
            b'finishFoodOrder(ctx, order, status, "")',
            b'finishFoodOrder(ctx, order, status, "compatible-v2")',
        ),
    )
    for old, new in replacements:
        _require(expected.count(old) == 1, "v1 compatibility anchor count differs")
        expected = expected.replace(old, new, 1)
    _require(target == expected, "compatible target is not the exact future-closure delta")
    _require(
        b'ClosureVersion string `json:"closure_version,omitempty"`' in _read(results / "source-types.go") and
        b'ClosureVersion string `json:"closure_version,omitempty"`' in _read(results / "source-activities.go"),
        "closure marker serialization source differs",
    )
    return build


def _payload_bytes(value: Any, label: str) -> bytes:
    container = _object(value, label)
    _require(set(container) == {"payloads"}, f"{label} fields differ")
    payloads = _array(container["payloads"], label + " payloads")
    _require(len(payloads) == 1, f"{label} payload count differs")
    payload = _object(payloads[0], label + " payload")
    _require(set(payload) == {"metadata", "data"}, f"{label} payload fields differ")
    _require(payload["metadata"] == {"encoding": "anNvbi9wbGFpbg=="}, f"{label} encoding differs")
    try:
        return base64.b64decode(payload["data"], validate=True)
    except (TypeError, ValueError) as error:
        raise EvidenceError(f"{label} is not base64") from error


def _operation_id(identity: str) -> str:
    raw = b"operation-id-v1\0temporal-order-workflow\0" + identity.encode()
    return "op-" + sha256(raw).hexdigest()


def _payment_operation_id() -> str:
    return _operation_id(PAYMENT_TOKEN)


def _completion_operation_id() -> str:
    return _operation_id("complete:" + ORDER_ID)


def _order_bytes() -> bytes:
    return (
        b'{"order_id":"order-1","restaurant_id":"restaurant-1","products":['
        b'{"product_id":"pizza-1","description":"Margherita Pizza","quantity":2}],'
        b'"amount_cents":4200,"delivery_delay_millis":25,"payment_token":"payment-token-1"}'
    )


def _json_payload(value: Any, label: str) -> dict[str, Any]:
    try:
        decoded = json.loads(_payload_bytes(value, label))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvidenceError(f"{label} is not JSON") from error
    return _object(decoded, label)


def _final_result() -> dict[str, Any]:
    return {
        "schema": 1, "order_id": ORDER_ID, "restaurant_id": RESTAURANT_ID,
        "product_count": PRODUCT_QUANTITY, "worker_build": TARGET_BUILD, "phase": "DELIVERED",
        "delivery_id": DELIVERY_ID, "driver_id": DRIVER_ID,
        "stages": [
            "RESTAURANT_SELECTED", "CREATED", "PAYMENT_PENDING", "PAYMENT_COMMITTED",
            "SCHEDULED", "IN_PREPARATION", "SCHEDULING_DELIVERY", "WAITING_FOR_DRIVER",
            "IN_DELIVERY", "DELIVERED",
        ],
    }


def _expected_receipt(operation_id: str, result_hash: str, remote_reference: str) -> dict[str, Any]:
    return {
        "schema": 1, "operation_id": operation_id, "outcome": "succeeded",
        "result_hash": result_hash, "remote_reference": remote_reference,
    }


def _event_attrs(event: dict[str, Any], key: str, label: str) -> dict[str, Any]:
    return _object(event.get(key), label)


def _check_wft_completed(event: dict[str, Any], scheduled: str, started: str, identity: str, build: str) -> None:
    attrs = _event_attrs(event, "workflowTaskCompletedEventAttributes", "Workflow task completion")
    _require(attrs.get("scheduledEventId") == scheduled and attrs.get("startedEventId") == started, "Workflow task links differ")
    _require(attrs.get("identity") == identity, "Workflow task identity differs")
    _require(attrs.get("workerVersion") == {"buildId": build, "useVersioning": True}, "Workflow task build differs")
    _require(attrs.get("versioningBehavior") == "VERSIONING_BEHAVIOR_AUTO_UPGRADE", "Workflow versioning behavior differs")
    _require(attrs.get("workerDeploymentName") == DEPLOYMENT, "Workflow deployment differs")
    _require(attrs.get("deploymentVersion") == {"buildId": build, "deploymentName": DEPLOYMENT}, "Workflow deployment version differs")


def _check_wft_started(event: dict[str, Any], scheduled: str, identity: str) -> None:
    attrs = _event_attrs(event, "workflowTaskStartedEventAttributes", "Workflow task start")
    _require(set(attrs) == {"scheduledEventId", "identity", "requestId", "historySizeBytes"}, "Workflow task start fields differ")
    _require(attrs.get("scheduledEventId") == scheduled and attrs.get("identity") == identity, "Workflow task start identity differs")
    _require(isinstance(attrs.get("requestId"), str) and attrs["requestId"], "Workflow task request ID is absent")
    _require(isinstance(attrs.get("historySizeBytes"), str) and attrs["historySizeBytes"].isdigit(), "Workflow task History size differs")


def _check_wft_scheduled(event: dict[str, Any], sticky: bool) -> dict[str, Any]:
    attrs = _event_attrs(event, "workflowTaskScheduledEventAttributes", "Workflow task schedule")
    _require(attrs.get("startToCloseTimeout") == "10s" and attrs.get("attempt") == 1, "Workflow task schedule options differ")
    queue = _object(attrs.get("taskQueue"), "Workflow task queue")
    if sticky:
        _require(
            queue.get("kind") == "TASK_QUEUE_KIND_STICKY" and queue.get("normalName") == TASK_QUEUE and
            isinstance(queue.get("name"), str) and queue["name"],
            "sticky Workflow task queue differs",
        )
    else:
        _require(queue == {"name": TASK_QUEUE, "kind": "TASK_QUEUE_KIND_NORMAL"}, "normal Workflow task queue differs")
    return queue


def _check_activity_schedule(event: dict[str, Any], activity_id: str, name: str, completed: str, body: bytes, timeout: str) -> None:
    attrs = _event_attrs(event, "activityTaskScheduledEventAttributes", name + " schedule")
    _require(attrs.get("activityId") == activity_id and attrs.get("activityType") == {"name": name}, f"{name} identity differs")
    _require(attrs.get("taskQueue") == {"name": TASK_QUEUE, "kind": "TASK_QUEUE_KIND_NORMAL"}, f"{name} queue differs")
    _require(_payload_bytes(attrs.get("input"), name + " input") == body, f"{name} input bytes differ")
    _require(
        attrs.get("header") == {} and attrs.get("scheduleToCloseTimeout") == "0s" and
        attrs.get("scheduleToStartTimeout") == "0s" and attrs.get("startToCloseTimeout") == timeout and
        attrs.get("heartbeatTimeout") == "0s" and attrs.get("workflowTaskCompletedEventId") == completed and
        attrs.get("retryPolicy") == {
            "initialInterval": "1s", "backoffCoefficient": 2,
            "maximumInterval": "100s", "maximumAttempts": 1,
        } and attrs.get("useWorkflowBuildId") is True,
        f"{name} scheduling semantics differ",
    )


def _check_activity_started(event: dict[str, Any], scheduled: str, identity: str, build: str) -> None:
    attrs = _event_attrs(event, "activityTaskStartedEventAttributes", "Activity start")
    _require(attrs.get("scheduledEventId") == scheduled and attrs.get("attempt") == 1, "Activity start link/attempt differs")
    _require(attrs.get("identity") == identity, "Activity start identity differs")
    _require(attrs.get("workerVersion") == {"buildId": build, "useVersioning": True}, "Activity start build differs")


def _history(results: Path, run_id: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    cut_data = _read(results / "cut-history-before.json")
    _require(cut_data == _read(results / "cut-history-after.json"), "cut History double-read is unstable")
    cut = _json(results / "cut-history-before.json")
    final = _json(results / "final-history.json")
    _require(set(cut) == {"events"} and set(final) == {"events"}, "History envelope fields differ")
    cut_events = [_object(event, "cut event") for event in _array(cut["events"], "cut events")]
    final_events = [_object(event, "final event") for event in _array(final["events"], "final events")]
    _require(final_events[:len(cut_events)] == cut_events, "final History does not exactly extend the frozen cut")
    _require(
        [event.get("eventId") for event in final_events] ==
        [str(i) for i in range(1, len(final_events) + 1)],
        "event IDs differ",
    )
    _require(all(isinstance(event.get("eventTime"), str) and event["eventTime"] for event in final_events), "event time is absent")
    _require(not any(event["eventType"] == "EVENT_TYPE_WORKFLOW_TASK_FAILED" for event in final_events), "Workflow task failure occurred")
    allowed_types = {
        "EVENT_TYPE_WORKFLOW_EXECUTION_STARTED", "EVENT_TYPE_WORKFLOW_TASK_SCHEDULED",
        "EVENT_TYPE_WORKFLOW_TASK_STARTED", "EVENT_TYPE_WORKFLOW_TASK_COMPLETED",
        "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED", "EVENT_TYPE_ACTIVITY_TASK_STARTED",
        "EVENT_TYPE_ACTIVITY_TASK_COMPLETED", "EVENT_TYPE_TIMER_STARTED", "EVENT_TYPE_TIMER_FIRED",
        "EVENT_TYPE_WORKFLOW_EXECUTION_SIGNALED", "EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED",
    }
    _require(all(event.get("eventType") in allowed_types for event in final_events), "unexpected History event type")

    started = _event_attrs(final_events[0], "workflowExecutionStartedEventAttributes", "Workflow start")
    _require(started.get("workflowType") == {"name": WORKFLOW_TYPE}, "Workflow type differs")
    _require(started.get("taskQueue") == {"name": TASK_QUEUE, "kind": "TASK_QUEUE_KIND_NORMAL"}, "Workflow queue differs")
    _require(_payload_bytes(started.get("input"), "Workflow input") == _order_bytes(), "Workflow input bytes differ")
    _require(
        started.get("workflowId") == WORKFLOW_ID and started.get("identity") == "safe-change-temporal-starter" and
        started.get("originalExecutionRunId") == run_id and started.get("firstExecutionRunId") == run_id and
        started.get("attempt") == 1 and started.get("workflowTaskTimeout") == "10s",
        "Workflow start identity differs",
    )

    wft_schedules = {
        event["eventId"]: event for event in final_events
        if event.get("eventType") == "EVENT_TYPE_WORKFLOW_TASK_SCHEDULED"
    }
    wft_starts = {
        event["eventId"]: event for event in final_events
        if event.get("eventType") == "EVENT_TYPE_WORKFLOW_TASK_STARTED"
    }
    wft_completions = [
        event for event in final_events if event.get("eventType") == "EVENT_TYPE_WORKFLOW_TASK_COMPLETED"
    ]
    _require(len(wft_schedules) == len(wft_starts) == len(wft_completions), "Workflow task event counts differ")
    for index, event in enumerate(wft_schedules.values()):
        _check_wft_scheduled(event, index != 0)
    start_by_schedule: dict[str, dict[str, Any]] = {}
    for event in wft_starts.values():
        attrs = _event_attrs(event, "workflowTaskStartedEventAttributes", "Workflow task start")
        scheduled_id = attrs.get("scheduledEventId")
        _require(isinstance(scheduled_id, str) and scheduled_id in wft_schedules, "Workflow task schedule link differs")
        identity = V1_IDENTITY if int(event["eventId"]) <= len(cut_events) else TARGET_IDENTITY
        _check_wft_started(event, scheduled_id, identity)
        start_by_schedule[scheduled_id] = event
    for event in wft_completions:
        attrs = _event_attrs(event, "workflowTaskCompletedEventAttributes", "Workflow task completion")
        scheduled_id = attrs.get("scheduledEventId")
        _require(isinstance(scheduled_id, str) and scheduled_id in start_by_schedule, "Workflow task completion schedule differs")
        started_event = start_by_schedule[scheduled_id]
        identity = V1_IDENTITY if int(event["eventId"]) <= len(cut_events) else TARGET_IDENTITY
        build = V1_BUILD if identity == V1_IDENTITY else TARGET_BUILD
        _check_wft_completed(event, scheduled_id, started_event["eventId"], identity, build)

    activity_schedules = [
        event for event in final_events if event.get("eventType") == "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED"
    ]
    activity_types = [
        event.get("activityTaskScheduledEventAttributes", {}).get("activityType", {}).get("name")
        for event in activity_schedules
    ]
    _require(
        activity_types == ["ChargePayment", "PrepareFood", "ScheduleDelivery", "CompleteOrder"],
        "food-ordering Activity sequence differs",
    )
    payment_id = _payment_operation_id()
    payment_input = (
        b'{"order_id":"order-1","amount_cents":4200,"operation_id":"' + payment_id.encode() + b'"}'
    )
    activity_inputs = {
        "ChargePayment": (payment_input, "30s"),
        "PrepareFood": (
            b'{"order_id":"order-1","restaurant_id":"restaurant-1","products":['
            b'{"product_id":"pizza-1","description":"Margherita Pizza","quantity":2}]}', "30s",
        ),
        "ScheduleDelivery": (
            b'{"order_id":"order-1","delivery_id":"delivery-order-1",'
            b'"restaurant_id":"restaurant-1","region":"San Jose (CA)"}', "30s",
        ),
    }
    completion_id = _completion_operation_id()
    completion_input = (
        b'{"order_id":"order-1","amount_cents":4200,"operation_id":"' + completion_id.encode() +
        b'","closure_version":"compatible-v2"}'
    )
    activity_inputs["CompleteOrder"] = (completion_input, "60s")
    completed_wft_ids = {event["eventId"] for event in wft_completions}
    for event, activity_name in zip(activity_schedules, activity_types, strict=True):
        attrs = _event_attrs(event, "activityTaskScheduledEventAttributes", activity_name + " schedule")
        completed_wft = attrs.get("workflowTaskCompletedEventId")
        _require(isinstance(completed_wft, str) and completed_wft in completed_wft_ids, "Activity Workflow task link differs")
        body, timeout = activity_inputs[activity_name]
        _check_activity_schedule(event, event["eventId"], activity_name, completed_wft, body, timeout)

    activity_starts: dict[str, dict[str, Any]] = {}
    activity_completions: dict[str, dict[str, Any]] = {}
    for event in final_events:
        if event.get("eventType") == "EVENT_TYPE_ACTIVITY_TASK_STARTED":
            attrs = _event_attrs(event, "activityTaskStartedEventAttributes", "Activity start")
            scheduled_id = attrs.get("scheduledEventId")
            _require(isinstance(scheduled_id, str) and scheduled_id not in activity_starts, "Activity start set differs")
            activity_starts[scheduled_id] = event
        elif event.get("eventType") == "EVENT_TYPE_ACTIVITY_TASK_COMPLETED":
            attrs = _event_attrs(event, "activityTaskCompletedEventAttributes", "Activity completion")
            scheduled_id = attrs.get("scheduledEventId")
            _require(isinstance(scheduled_id, str) and scheduled_id not in activity_completions, "Activity completion set differs")
            activity_completions[scheduled_id] = event
    schedule_ids = {event["eventId"] for event in activity_schedules}
    _require(set(activity_starts) == schedule_ids == set(activity_completions), "Activity execution set differs")
    for event, activity_name in zip(activity_schedules, activity_types, strict=True):
        identity = V1_IDENTITY if activity_name in {"ChargePayment", "PrepareFood"} else TARGET_IDENTITY
        build = V1_BUILD if identity == V1_IDENTITY else TARGET_BUILD
        start_event = activity_starts[event["eventId"]]
        _check_activity_started(start_event, event["eventId"], identity, build)
        receipt_attrs = _event_attrs(
            activity_completions[event["eventId"]], "activityTaskCompletedEventAttributes",
            activity_name + " completion",
        )
        _require(
            receipt_attrs.get("startedEventId") == start_event["eventId"] and
            receipt_attrs.get("identity") == identity,
            f"{activity_name} completion links differ",
        )

    prepare_event = activity_schedules[1]
    delivery_event = activity_schedules[2]
    _require(
        _json_payload(
            activity_completions[prepare_event["eventId"]].get("activityTaskCompletedEventAttributes", {}).get("result"),
            "PrepareFood result",
        ) == {
            "schema": 1, "order_id": ORDER_ID, "restaurant_id": RESTAURANT_ID,
            "product_count": PRODUCT_QUANTITY, "outcome": "accepted",
        },
        "PrepareFood receipt differs",
    )
    _require(
        _json_payload(
            activity_completions[delivery_event["eventId"]].get("activityTaskCompletedEventAttributes", {}).get("result"),
            "ScheduleDelivery result",
        ) == {
            "schema": 1, "order_id": ORDER_ID, "delivery_id": DELIVERY_ID,
            "restaurant_id": RESTAURANT_ID, "region": "San Jose (CA)", "outcome": "scheduled",
        },
        "ScheduleDelivery receipt differs",
    )

    timers_started = [event for event in final_events if event.get("eventType") == "EVENT_TYPE_TIMER_STARTED"]
    timers_fired = [event for event in final_events if event.get("eventType") == "EVENT_TYPE_TIMER_FIRED"]
    _require(len(timers_started) == len(timers_fired) == 1, "preparation timer event set differs")
    timer_start = _event_attrs(timers_started[0], "timerStartedEventAttributes", "preparation timer start")
    timer_fire = _event_attrs(timers_fired[0], "timerFiredEventAttributes", "preparation timer fire")
    _require(
        timer_start.get("startToFireTimeout") == "0.025s" and
        timer_fire.get("timerId") == timer_start.get("timerId") and
        timer_fire.get("startedEventId") == timers_started[0]["eventId"],
        "preparation timer semantics differ",
    )
    _require(timers_fired[0] in cut_events and prepare_event in cut_events, "cut precedes preparation completion")

    signals = [event for event in final_events if event.get("eventType") == "EVENT_TYPE_WORKFLOW_EXECUTION_SIGNALED"]
    _require(len(signals) == len(BUSINESS_SIGNALS), "business signal count differs")
    signal_attrs = [
        _event_attrs(event, "workflowExecutionSignaledEventAttributes", "business signal")
        for event in signals
    ]
    _require([attrs.get("signalName") for attrs in signal_attrs] == list(BUSINESS_SIGNALS), "business signal order differs")
    for attrs in signal_attrs:
        _require(set(attrs) == {"signalName", "input", "identity"}, "business signal fields differ")
        _require(attrs["identity"] == SIGNAL_IDENTITY, "business signal identity differs")
        if attrs["signalName"] == "driver_selected":
            _require(
                _payload_bytes(attrs["input"], "driver_selected input") ==
                b'{"delivery_id":"delivery-order-1","driver_id":"driver-1"}',
                "driver assignment signal differs",
            )
        else:
            _require(attrs["input"] == {}, f"{attrs['signalName']} input differs")

    _require(final_events[-1].get("eventType") == "EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED", "Workflow did not complete")
    completed = _event_attrs(final_events[-1], "workflowExecutionCompletedEventAttributes", "Workflow completion")
    expected_result = json.dumps(_final_result(), separators=(",", ":")).encode()
    _require(_payload_bytes(completed.get("result"), "Workflow result") == expected_result, "Workflow result differs")
    _require(completed.get("workflowTaskCompletedEventId") in completed_wft_ids, "Workflow completion link differs")

    expected_cut_counts = {
        "EVENT_TYPE_WORKFLOW_EXECUTION_STARTED": 1,
        "EVENT_TYPE_WORKFLOW_TASK_SCHEDULED": 4,
        "EVENT_TYPE_WORKFLOW_TASK_STARTED": 4,
        "EVENT_TYPE_WORKFLOW_TASK_COMPLETED": 4,
        "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED": 2,
        "EVENT_TYPE_ACTIVITY_TASK_STARTED": 2,
        "EVENT_TYPE_ACTIVITY_TASK_COMPLETED": 2,
        "EVENT_TYPE_TIMER_STARTED": 1,
        "EVENT_TYPE_TIMER_FIRED": 1,
    }
    cut_counts = {
        event_type: sum(event.get("eventType") == event_type for event in cut_events)
        for event_type in expected_cut_counts
    }
    _require(cut_counts == expected_cut_counts and len(cut_events) == 21, "cut event set differs")
    _require(cut_events[-1].get("eventType") == "EVENT_TYPE_WORKFLOW_TASK_COMPLETED", "cut phase is not durable")
    return (
        cut, final,
        activity_completions[activity_schedules[0]["eventId"]],
        activity_completions[activity_schedules[3]["eventId"]],
    )


def _check_query(results: Path, name: str, expected: dict[str, Any]) -> None:
    value = _json(results / name)
    _require(value == {"queryResult": [expected]}, f"{name} differs")


def _check_describes(results: Path, run_id: str) -> None:
    cut_length = len(_array(_json(results / "cut-history-before.json")["events"], "cut History"))
    final_history = _array(_json(results / "final-history.json")["events"], "final History")
    final_length = len(final_history)
    cut = _json(results / "cut-describe.json")
    cut_info = _object(cut.get("workflowExecutionInfo"), "cut Workflow info")
    _require(cut_info.get("execution") == {"workflowId": WORKFLOW_ID, "runId": run_id}, "cut execution differs")
    _require(cut_info.get("type") == {"name": WORKFLOW_TYPE}, "cut type differs")
    _require(cut_info.get("status") == "WORKFLOW_EXECUTION_STATUS_RUNNING", "cut status differs")
    _require(cut_info.get("historyLength") == str(cut_length) and cut_info.get("taskQueue") == TASK_QUEUE, "cut History/queue differs")
    _require(cut_info.get("mostRecentWorkerVersionStamp") == {"buildId": V1_BUILD, "useVersioning": True}, "cut worker differs")
    _require(cut_info.get("workerDeploymentName") == DEPLOYMENT, "cut deployment differs")
    _require(cut_info.get("versioningInfo") == {
        "behavior": "VERSIONING_BEHAVIOR_AUTO_UPGRADE",
        "version": f"{DEPLOYMENT}.{V1_BUILD}",
        "deploymentVersion": {"buildId": V1_BUILD, "deploymentName": DEPLOYMENT},
        "revisionNumber": "1",
    }, "cut versioning info differs")
    _require(cut.get("pendingActivities") is None and cut.get("pendingWorkflowTask") is None, "cut has pending work")
    _require(cut.get("result") is None and cut.get("closeEvent") is None, "cut is already closed")
    _require(cut.get("executionConfig") == {
        "taskQueue": {"name": TASK_QUEUE, "kind": "TASK_QUEUE_KIND_NORMAL"},
        "workflowExecutionTimeout": "0s", "workflowRunTimeout": "0s",
        "defaultWorkflowTaskTimeout": "10s",
    }, "cut execution config differs")

    final = _json(results / "final-describe.json")
    info = _object(final.get("workflowExecutionInfo"), "final Workflow info")
    _require(info.get("execution") == {"workflowId": WORKFLOW_ID, "runId": run_id}, "final execution differs")
    _require(info.get("status") == "WORKFLOW_EXECUTION_STATUS_COMPLETED" and info.get("historyLength") == str(final_length), "final status/History differs")
    _require(
        info.get("type") == {"name": WORKFLOW_TYPE} and info.get("taskQueue") == TASK_QUEUE and
        info.get("workerDeploymentName") == DEPLOYMENT,
        "final type/queue/deployment differs",
    )
    _require(info.get("mostRecentWorkerVersionStamp") == {"buildId": TARGET_BUILD, "useVersioning": True}, "final worker differs")
    _require(info.get("versioningInfo") == {
        "behavior": "VERSIONING_BEHAVIOR_AUTO_UPGRADE",
        "version": f"{DEPLOYMENT}.{TARGET_BUILD}",
        "deploymentVersion": {"buildId": TARGET_BUILD, "deploymentName": DEPLOYMENT},
        "revisionNumber": "2",
    }, "final versioning info differs")
    _require(final.get("pendingActivities") is None and final.get("pendingWorkflowTask") is None, "final has pending work")
    expected_result = _final_result()
    _require(final.get("result") == expected_result, "final describe result differs")
    close_event = _object(final.get("closeEvent"), "final close event")
    _require(
        close_event.get("eventId") == str(final_length) and
        close_event.get("eventType") == "EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED" and
        close_event.get("eventTime") == info.get("closeTime") and
        isinstance(close_event.get("taskId"), str) and close_event["taskId"].isdigit(),
        "final close event identity differs",
    )
    terminal_attrs = _event_attrs(
        _object(final_history[-1], "terminal History event"),
        "workflowExecutionCompletedEventAttributes", "terminal Workflow completion",
    )
    _require(close_event.get("workflowExecutionCompletedEventAttributes") == {
        "result": [expected_result],
        "workflowTaskCompletedEventId": terminal_attrs.get("workflowTaskCompletedEventId"),
    }, "final close event result differs")
    _require(final.get("executionConfig") == {
        "defaultWorkflowTaskTimeout": "10s",
        "taskQueue": {"kind": "TASK_QUEUE_KIND_NORMAL", "name": TASK_QUEUE},
        "workflowExecutionTimeout": "0s", "workflowRunTimeout": "0s",
    }, "final execution config differs")
    points = _array(_object(info.get("autoResetPoints"), "reset points").get("points"), "reset points")
    _require([point.get("buildId") for point in points if isinstance(point, dict)] == [V1_BUILD, TARGET_BUILD], "used worker builds differ")
    _check_query(results, "cut-query.json", {
        "schema": 1, "order_id": ORDER_ID, "restaurant_id": RESTAURANT_ID,
        "product_count": PRODUCT_QUANTITY, "worker_build": V1_BUILD, "phase": "IN_PREPARATION",
        "delivery_id": "", "driver_id": "",
        "stages": [
            "RESTAURANT_SELECTED", "CREATED", "PAYMENT_PENDING", "PAYMENT_COMMITTED",
            "SCHEDULED", "IN_PREPARATION",
        ],
    })
    _check_query(results, "final-query.json", expected_result)


def _check_stats(results: Path, name: str, expected: dict[str, Any]) -> None:
    _require(_json(results / name) == expected, f"{name} differs")


def _provider_record(data: bytes, label: str) -> dict[str, Any]:
    _require(data.endswith(b"\n") and data.count(b"\n") == 1, f"{label} record count differs")
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvidenceError(f"{label} is not JSON") from error
    return _object(value, label)


def _expected_provider(operation_id: str, path: str, body: bytes, prefix: str) -> dict[str, str]:
    return {
        "operation_id": operation_id,
        "request_hash": sha256(b"POST\0" + path.encode() + b"\0" + body).hexdigest(),
        "result_hash": sha256(b"charged\0" + operation_id.encode() + b"\0" + b"1").hexdigest(),
        "remote_reference": f"{prefix}/{operation_id}/commit-1",
        "path": path,
    }


def _activity_receipt(event: dict[str, Any], identity: str) -> dict[str, Any]:
    attrs = _event_attrs(event, "activityTaskCompletedEventAttributes", "Activity completion")
    _require(
        isinstance(attrs.get("scheduledEventId"), str) and attrs["scheduledEventId"].isdigit() and
        isinstance(attrs.get("startedEventId"), str) and attrs["startedEventId"].isdigit(),
        "Activity completion links differ",
    )
    _require(attrs.get("identity") == identity, "Activity completion identity differs")
    try:
        return _object(json.loads(_payload_bytes(attrs.get("result"), "Activity result")), "Activity receipt")
    except json.JSONDecodeError as error:
        raise EvidenceError("Activity receipt is not JSON") from error


def _check_providers(results: Path, payment_event: dict[str, Any], completion_event: dict[str, Any]) -> None:
    payment_stats = {"deliveries": 1, "commits": 1, "paths": {"/v1/charge": 1}}
    completion_zero = {"deliveries": 0, "commits": 0, "paths": {}}
    completion_one = {"deliveries": 1, "commits": 1, "paths": {"/v1/complete": 1}}
    _check_stats(results, "payment-cut-stats.json", payment_stats)
    _check_stats(results, "payment-final-stats.json", payment_stats)
    _check_stats(results, "completion-cut-stats.json", completion_zero)
    _check_stats(results, "completion-final-stats.json", completion_one)
    payment_data = _read(results / "payment-cut.history")
    _require(payment_data == _read(results / "payment-final.history"), "payment provider changed after cut")
    _require(_read(results / "completion-cut.history") == b"", "completion occurred before upgrade")
    payment_body = b'{"order_id":"order-1","amount_cents":4200}'
    completion_body = b'{"order_id":"order-1","amount_cents":4200,"closure_version":"compatible-v2"}'
    payment = _expected_provider(_payment_operation_id(), "/v1/charge", payment_body, "temporal-payment")
    completion = _expected_provider(_completion_operation_id(), "/v1/complete", completion_body, "temporal-completion")
    _require(_provider_record(payment_data, "payment History") == payment, "payment provider record differs")
    _require(_provider_record(_read(results / "completion-final.history"), "completion History") == completion, "completion provider record differs")
    _require(
        _activity_receipt(payment_event, V1_IDENTITY) ==
        _expected_receipt(payment["operation_id"], payment["result_hash"], payment["remote_reference"]),
        "payment Activity receipt differs from provider",
    )
    _require(
        _activity_receipt(completion_event, TARGET_IDENTITY) ==
        _expected_receipt(completion["operation_id"], completion["result_hash"], completion["remote_reference"]),
        "completion Activity receipt differs from provider",
    )


def _check_poller(results: Path, name: str, build: str, identity: str) -> None:
    value = _json(results / name)
    pollers = _array(value.get("pollers"), name + " pollers")
    matches = [item for item in pollers if isinstance(item, dict) and
        item.get("identity") == identity and
        item.get("worker_version_capabilities") == {
            "build_id": build, "use_versioning": True, "deployment_series_name": DEPLOYMENT,
        } and item.get("deployment_options") == {
            "deployment_name": DEPLOYMENT, "build_id": build, "worker_versioning_mode": 2,
        }]
    _require(len(matches) == 1 and isinstance(matches[0].get("last_access_time"), dict), f"{name} does not prove expected poller")


def _routing(value: dict[str, Any], build: str) -> None:
    _require(value.get("name") == DEPLOYMENT, "deployment name differs")
    routing = _object(value.get("routingConfig"), "routing config")
    _require(routing.get("currentVersionDeploymentName") == (DEPLOYMENT if build else ""), "current deployment differs")
    _require(routing.get("currentVersionBuildID") == build, "current build differs")
    _require(routing.get("rampingVersionDeploymentName") == "" and routing.get("rampingVersionBuildID") == "" and routing.get("rampingVersionPercentage") == 0, "ramping route is present")


def _check_version(value: dict[str, Any], build: str) -> None:
    _require(value.get("deploymentName") == DEPLOYMENT and value.get("BuildID") == build, "deployment version identity differs")
    queues = _array(value.get("taskQueuesInfos"), "deployment version queues")
    _require({(item.get("name"), item.get("type")) for item in queues if isinstance(item, dict)} == {
        (TASK_QUEUE, "activity"), (TASK_QUEUE, "workflow"),
    }, "deployment version queues differ")


def _time(value: Any, label: str) -> datetime:
    _require(isinstance(value, str) and value.endswith("Z"), f"{label} is not an ISO timestamp")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise EvidenceError(f"{label} is not an ISO timestamp") from error


def _check_deployments(results: Path) -> tuple[datetime, datetime]:
    _check_poller(results, "v1-workflow-pollers.json", V1_BUILD, V1_IDENTITY)
    _check_poller(results, "v1-activity-pollers.json", V1_BUILD, V1_IDENTITY)
    _check_poller(results, "compatible-workflow-pollers.json", TARGET_BUILD, TARGET_IDENTITY)
    _check_poller(results, "compatible-activity-pollers.json", TARGET_BUILD, TARGET_IDENTITY)
    _require(_read(results / "set-current-v1.json") == b"", "set-current v1 stdout differs")
    _require(_read(results / "set-current-compatible.json") == b"", "set-current target stdout differs")
    for name in (
        "signal-preparation-finished.json", "signal-driver-selected.json",
        "signal-driver-at-restaurant.json", "signal-delivery-finished.json",
    ):
        _require(_read(results / name) == b"", f"{name} stdout differs")
    before = _json(results / "deployment-before-current.json")
    v1 = _json(results / "deployment-v1-current.json")
    target = _json(results / "deployment-compatible-current.json")
    final = _json(results / "deployment-final.json")
    _routing(before, "")
    _routing(v1, V1_BUILD)
    _routing(target, TARGET_BUILD)
    _routing(final, TARGET_BUILD)
    _require(
        before["routingConfig"]["currentVersionChangedTime"] == "0001-01-01T00:00:00Z" and
        before["routingConfig"]["rampingVersionChangedTime"] == "0001-01-01T00:00:00Z" and
        before["routingConfig"]["rampingVersionPercentageChangedTime"] == "0001-01-01T00:00:00Z",
        "initial routing timestamps differ",
    )
    before_summaries = _array(before.get("versionSummaries"), "initial versions")
    _require([(item.get("BuildID"), item.get("drainageStatus")) for item in before_summaries] == [(V1_BUILD, "unspecified")], "initial deployment versions differ")
    v1_summaries = _array(v1.get("versionSummaries"), "v1-current versions")
    _require([(item.get("BuildID"), item.get("drainageStatus")) for item in v1_summaries] == [(V1_BUILD, "unspecified")], "v1-current deployment versions differ")
    target_summaries = _array(target.get("versionSummaries"), "target versions")
    _require(
        len(target_summaries) == 2 and
        target_summaries[0].get("deploymentName") == DEPLOYMENT and
        target_summaries[0].get("BuildID") == TARGET_BUILD and
        target_summaries[0].get("drainageStatus") == "unspecified" and
        target_summaries[1].get("deploymentName") == DEPLOYMENT and
        target_summaries[1].get("BuildID") == V1_BUILD and
        target_summaries[1].get("drainageStatus") in {"draining", "drained"},
        "target deployment versions differ",
    )
    _require(final.get("routingConfig") == target.get("routingConfig"), "final routing changed")
    final_summaries = _array(final.get("versionSummaries"), "final versions")
    _require(
        len(final_summaries) == 2 and
        final_summaries[0].get("deploymentName") == DEPLOYMENT and
        final_summaries[0].get("BuildID") == TARGET_BUILD and
        final_summaries[0].get("drainageStatus") == "unspecified" and
        final_summaries[1].get("deploymentName") == DEPLOYMENT and
        final_summaries[1].get("BuildID") == V1_BUILD and
        final_summaries[1].get("drainageStatus") in {"draining", "drained"},
        "final deployment versions differ",
    )
    v1_version = _json(results / "version-v1.json")
    _check_version(v1_version, V1_BUILD)
    _require(
        v1_version.get("currentSinceTime") == "1970-01-01T00:00:00Z" and
        v1_version.get("routingChangedTime") == "1970-01-01T00:00:00Z",
        "v1 was current before the official transition",
    )
    before_version = _json(results / "version-compatible-before-current.json")
    _check_version(before_version, TARGET_BUILD)
    _require(
        before_version.get("currentSinceTime") == "1970-01-01T00:00:00Z" and
        before_version.get("routingChangedTime") == "1970-01-01T00:00:00Z",
        "target was already current",
    )
    current_version = _json(results / "version-compatible-current.json")
    _check_version(current_version, TARGET_BUILD)
    _require(current_version.get("currentSinceTime") == target["routingConfig"]["currentVersionChangedTime"], "target current time differs")
    return (
        _time(v1["routingConfig"]["currentVersionChangedTime"], "v1 routing time"),
        _time(target["routingConfig"]["currentVersionChangedTime"], "target routing time"),
    )


def _image_labels(item: dict[str, Any], label: str) -> dict[str, Any]:
    return _object(_object(item.get("Config"), label + " config").get("Labels"), label + " labels")


def _check_image(path: Path, image_id: str, image_name: str, labels_expected: dict[str, str], entrypoint: list[str]) -> None:
    values = _json_array(path)
    _require(len(values) == 1, f"{path.name} image count differs")
    item = _object(values[0], path.name + " image")
    _require(item.get("Id") == image_id, f"{path.name} image ID differs")
    _require(image_name in _array(item.get("RepoTags"), path.name + " tags"), f"{path.name} tag differs")
    config = _object(item.get("Config"), path.name + " config")
    _require(config.get("Entrypoint") == entrypoint, f"{path.name} entrypoint differs")
    labels = _image_labels(item, path.name)
    for key, value in labels_expected.items():
        _require(labels.get(key) == value, f"{path.name} label {key} differs")


def _containers(path: Path) -> dict[str, dict[str, Any]]:
    values = [_object(item, path.name + " container") for item in _json_array(path)]
    mapped: dict[str, dict[str, Any]] = {}
    for item in values:
        labels = _image_labels(item, path.name)
        service = labels.get("com.docker.compose.service")
        _require(isinstance(service, str) and service not in mapped, f"{path.name} service labels differ")
        mapped[service] = item
    return mapped


def _container_security(item: dict[str, Any], label: str) -> None:
    _require(_object(item.get("State"), label + " state").get("Running") is True, f"{label} is not running")
    host = _object(item.get("HostConfig"), label + " host config")
    _require(host.get("ReadonlyRootfs") is True, f"{label} root filesystem is writable")
    _require(host.get("CapDrop") == ["ALL"], f"{label} capabilities differ")
    _require("no-new-privileges:true" in (host.get("SecurityOpt") or []), f"{label} security options differ")


def _check_worker_container(item: dict[str, Any], image: str, service: str, build: str, build_target: str, source: str, revision: str) -> None:
    _container_security(item, service)
    config = _object(item.get("Config"), service + " config")
    labels = _image_labels(item, service)
    _require(item.get("Image") == image and config.get("Image") == image, f"{service} image differs")
    _require(
        config.get("Entrypoint") == ["/usr/local/bin/worker"] and config.get("Cmd") is None and
        config.get("User") == "65532:65532",
        f"{service} executable/user differs",
    )
    _require(labels.get("com.docker.compose.service") == service, f"{service} label differs")
    _require(labels.get("io.safe-change.build.target") == build_target, f"{service} build target differs")
    _require(labels.get("io.safe-change.worker.build-id") == build, f"{service} build ID differs")
    _require(labels.get("io.safe-change.source.sha256") == source, f"{service} source hash differs")
    _require(labels.get("org.opencontainers.image.revision") == revision, f"{service} revision differs")
    env = _array(config.get("Env"), service + " environment")
    _require(len(env) == len(set(env)) and set(env) == {
        "TEMPORAL_ADDRESS=temporal:7233", "PAYMENT_URL=http://payment:8081",
        "COMPLETION_URL=http://completion:8081", "HOME=/tmp",
        "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    }, f"{service} environment differs")


def _check_provider_container(item: dict[str, Any], service: str, effects_id: str) -> None:
    _container_security(item, service)
    config = _object(item.get("Config"), service + " config")
    _require(item.get("Image") == effects_id and config.get("Image") == effects_id, f"{service} image differs")
    _require(config.get("Entrypoint") == ["/usr/local/bin/payment"], f"{service} entrypoint differs")
    _require(config.get("User") not in {"", "0", "root", "0:0"}, f"{service} runs as root")
    _require(config.get("Env") == ["PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"], f"{service} environment differs")
    expected = ["-listen=0.0.0.0:8081", f"-state=/state/{service}.history"]
    if service == "payment":
        expected += ["-hold-before-commit=false", "-hold-after-commit=false"]
    expected += ["-non-idempotent=true", f"-reference-prefix=temporal-{service}"]
    _require(config.get("Cmd") == expected, f"{service} command differs")


def _check_temporal_container(item: dict[str, Any]) -> None:
    _container_security(item, "temporal")
    _require(item.get("Image") == TEMPORAL_IMAGE.rsplit("@", 1)[1], "Temporal image ID differs")
    config = _object(item.get("Config"), "Temporal config")
    _require(
        config.get("Image") == TEMPORAL_IMAGE and config.get("Entrypoint") == ["temporal"] and
        config.get("Cmd") == [
            "server", "start-dev", "--headless", "--ip=0.0.0.0", "--port=7233",
            "--db-filename=/state/temporal.db",
            "--dynamic-config-value=frontend.WorkflowPauseEnabled=true", "--log-level=warn",
        ],
        "Temporal container command differs",
    )


def _check_containers(results: Path, build: dict[str, str], cut_time: datetime, routing_time: datetime) -> None:
    _check_image(results / "v1-image-inspect.json", build["WORKER_V1_ID"], build["WORKER_V1_IMAGE"], {
        "io.safe-change.source.sha256": build["SOURCE_SHA256"],
        "io.safe-change.build.target": "worker_v1", "io.safe-change.worker.build-id": V1_BUILD,
        "org.opencontainers.image.revision": build["GIT_REVISION"],
        "org.opencontainers.image.base.name": RUNTIME_IMAGE,
        "io.safe-change.builder.base": GO_IMAGE,
        "io.safe-change.temporal.go-sdk.version": "v1.47.0",
    }, ["/usr/local/bin/worker"])
    _check_image(results / "compatible-image-inspect.json", build["WORKER_COMPATIBLE_V2_ID"], build["WORKER_COMPATIBLE_V2_IMAGE"], {
        "io.safe-change.source.sha256": build["SOURCE_SHA256"],
        "io.safe-change.build.target": "worker_compatible_v2", "io.safe-change.worker.build-id": TARGET_BUILD,
        "org.opencontainers.image.revision": build["GIT_REVISION"],
        "org.opencontainers.image.base.name": RUNTIME_IMAGE,
        "io.safe-change.builder.base": GO_IMAGE,
        "io.safe-change.temporal.go-sdk.version": "v1.47.0",
    }, ["/usr/local/bin/worker"])
    _check_image(results / "starter-image-inspect.json", build["STARTER_ID"], build["STARTER_IMAGE"], {
        "io.safe-change.source.sha256": build["SOURCE_SHA256"],
        "io.safe-change.build.target": "starter", "org.opencontainers.image.revision": build["GIT_REVISION"],
    }, ["/usr/local/bin/starter"])
    _check_image(results / "effects-image-inspect.json", build["EFFECTS_ID"], build["EFFECTS_IMAGE"], {
        "io.safe-change.source.sha256": build["RUNTIME_SOURCE_SHA256"],
        "io.safe-change.runtime.source.sha256": build["RUNTIME_SOURCE_SHA256"],
        "io.safe-change.build.target": "effects", "org.opencontainers.image.revision": build["GIT_REVISION"],
    }, ["/usr/local/bin/payment"])

    cut = _containers(results / "containers-cut.json")
    before_target = _containers(results / "containers-before-target.json")
    final = _containers(results / "containers-final.json")
    _require(set(cut) == {"temporal", "payment", "completion", "worker-v1"}, "cut container services differ")
    _require(set(before_target) == {"temporal", "payment", "completion"}, "pre-target container services differ")
    _require(set(final) == {"temporal", "payment", "completion", "worker-compatible-v2"}, "final container services differ")
    projects = {
        _image_labels(item, "container").get("com.docker.compose.project")
        for group in (cut, before_target, final) for item in group.values()
    }
    _require(len(projects) == 1 and None not in projects, "Compose project identity differs")
    for service in ("temporal", "payment", "completion"):
        ids = {group[service].get("Id") for group in (cut, before_target, final)}
        _require(len(ids) == 1, f"{service} container changed across boundary")
    for group in (cut, before_target, final):
        _check_temporal_container(group["temporal"])
    for group in (cut, before_target, final):
        _check_provider_container(group["payment"], "payment", build["EFFECTS_ID"])
        _check_provider_container(group["completion"], "completion", build["EFFECTS_ID"])
    _check_worker_container(cut["worker-v1"], build["WORKER_V1_ID"], "worker-v1", V1_BUILD, "worker_v1", build["SOURCE_SHA256"], build["GIT_REVISION"])
    _check_worker_container(final["worker-compatible-v2"], build["WORKER_COMPATIBLE_V2_ID"], "worker-compatible-v2", TARGET_BUILD, "worker_compatible_v2", build["SOURCE_SHA256"], build["GIT_REVISION"])

    v1_inspect = _json_array(results / "v1-running-inspect.json")
    target_inspect = _json_array(results / "compatible-running-inspect.json")
    _require(len(v1_inspect) == len(target_inspect) == 1, "worker inspect count differs")
    v1_standalone = _object(v1_inspect[0], "v1 standalone inspect")
    target_standalone = _object(target_inspect[0], "target standalone inspect")
    _check_worker_container(v1_standalone, build["WORKER_V1_ID"], "worker-v1", V1_BUILD, "worker_v1", build["SOURCE_SHA256"], build["GIT_REVISION"])
    _check_worker_container(target_standalone, build["WORKER_COMPATIBLE_V2_ID"], "worker-compatible-v2", TARGET_BUILD, "worker_compatible_v2", build["SOURCE_SHA256"], build["GIT_REVISION"])
    _require(v1_standalone.get("Id") == cut["worker-v1"].get("Id"), "v1 inspect/container mismatch")
    _require(target_standalone.get("Id") == final["worker-compatible-v2"].get("Id"), "target inspect/container mismatch")
    target_started = _time(_object(final["worker-compatible-v2"].get("State"), "target state").get("StartedAt"), "target start")
    _require(cut_time < target_started < routing_time, "cut/start/current ordering differs")

    old_id = str(cut["worker-v1"].get("Id"))
    _require(re.fullmatch(r"[0-9a-f]{64}", old_id) is not None, "v1 container ID differs")
    _require(_read(results / "v1-removed-inspect-status.txt") == b"1\n", "v1 removal inspect status differs")
    _require(_read(results / "v1-removed-inspect.json") == b"[]\n", "v1 removal inspect stdout differs")
    stderr = _read(results / "v1-removed-inspect.stderr").decode("utf-8", errors="strict")
    _require(re.fullmatch(r"error: no such object: " + old_id + r"\n", stderr) is not None, "v1 removal error differs")
    _require(_read(results / "v1-after-remove.txt") == b"", "Compose still resolves v1 after removal")
    _require(b"worker-v1-1" in _read(results / "remove-v1.txt"), "v1 remove command output differs")


def _check_logs(results: Path, run_id: str) -> None:
    v1 = _read(results / "v1.log").decode("utf-8")
    target = _read(results / "compatible.log").decode("utf-8")
    _require(
        v1.count("ActivityType ChargePayment") == 1 and
        v1.count("ActivityType PrepareFood") == 1 and
        "ActivityType ScheduleDelivery" not in v1 and "ActivityType CompleteOrder" not in v1,
        "v1 Activity log differs",
    )
    _require(
        target.count("ActivityType ScheduleDelivery") == 1 and
        target.count("ActivityType CompleteOrder") == 1 and
        "ActivityType ChargePayment" not in target and "ActivityType PrepareFood" not in target,
        "target Activity log differs",
    )
    _require(run_id in v1 and run_id in target, "worker logs do not bind the same run")
    _require(f"build_id={V1_BUILD}" in v1 and f"build_id={TARGET_BUILD}" in target, "worker log build IDs differ")


def check_evidence(root: Path) -> dict[str, Any]:
    results = _results_dir(root)
    _verify_checksums(results)
    _require(_read(results / "exit-status.txt") == b"0\n", "runner did not exit successfully")
    build = _check_build(results)
    start = _json(results / "start.json")
    _require(set(start) == {"schema", "behavior", "workflow_id", "run_id"}, "starter output fields differ")
    _require(start.get("schema") == 1 and start.get("behavior") == "autoupgrade" and start.get("workflow_id") == WORKFLOW_ID, "starter output differs")
    run_id = start.get("run_id")
    _require(isinstance(run_id, str) and re.fullmatch(r"[0-9a-f-]{36}", run_id) is not None, "run ID differs")
    cut, _final, payment_event, completion_event = _history(results, run_id)
    _check_describes(results, run_id)
    _check_providers(results, payment_event, completion_event)
    v1_routing_time, routing_time = _check_deployments(results)
    cut_events = _array(cut["events"], "cut events")
    start_time = _time(_object(cut_events[0], "Workflow start event").get("eventTime"), "Workflow start time")
    cut_time = _time(_object(cut_events[-1], "last cut event").get("eventTime"), "cut event time")
    signal_events = [
        _object(event, "signal event")
        for event in _array(_json(results / "final-history.json")["events"], "final events")
        if isinstance(event, dict) and event.get("eventType") == "EVENT_TYPE_WORKFLOW_EXECUTION_SIGNALED"
    ]
    _require(signal_events, "business signals are absent")
    signal_time = _time(signal_events[0].get("eventTime"), "signal time")
    _require(v1_routing_time < start_time < cut_time < routing_time < signal_time, "deployment/workflow chronology differs")
    _check_containers(results, build, cut_time, routing_time)
    _check_logs(results, run_id)
    return {
        "valid": True,
        "workflow_id": WORKFLOW_ID,
        "run_id": run_id,
        "source_build": V1_BUILD,
        "target_build": TARGET_BUILD,
        "closure_version": "compatible-v2",
        "payment_deliveries": 1,
        "payment_commits": 1,
        "completion_deliveries": 1,
        "completion_commits": 1,
        "final_status": "WORKFLOW_EXECUTION_STATUS_COMPLETED",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()
    try:
        result = check_evidence(args.evidence)
    except (EvidenceError, OSError, subprocess.SubprocessError) as error:
        print(json.dumps({"valid": False, "error": str(error)}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
