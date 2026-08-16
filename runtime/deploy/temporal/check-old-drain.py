#!/usr/bin/env python3
"""Independently validate Temporal Pinned old-version-drain evidence."""

from __future__ import annotations

import argparse
import base64
import copy
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[2]
WORKFLOW_ID = "temporal-old-drain-order-1"
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
V1_IDENTITY = "safe-change-food-order-v1-worker"
SIGNAL_IDENTITY = "safe-change-old-drain-harness"
BUSINESS_SIGNALS = (
    "preparation_finished", "driver_selected", "driver_at_restaurant", "delivery_finished",
)
SOURCE_SHA256 = "877a7a5b71b24e3dc309af5cd23bebe77c40dab6b8aec659ef929f1dc771aade"
RUNTIME_SOURCE_SHA256 = "e95760a49a36fa0dbf8136589545b5499a99e353baabae44c6c11e37ed581059"
BUILD_ENV_SHA256 = "495e37bda60465e4be169605449a6d586f705faac95cbeb57f0ea49ab97a7fa5"
V1_SOURCE_SHA256 = "46b82cdab94d538051928e3322cefee2eca3a5cdaf502f1ccad03d6c8b03621b"
ACTIVITIES_SOURCE_SHA256 = "96a7eaa2518658f5790fcd577141a5bf6210c9201455729271afb9d3e3e3095a"
WORKFLOWS_SOURCE_SHA256 = "8e498105a55f4c272cf0a4b3d4d0461bb81711a21d13fc0558c4faa710bca88b"
TYPES_SOURCE_SHA256 = "b8b5de1b534687d67dd8f232f893b41e43261cf1d6271e997c069e915cc91b23"
STARTER_SOURCE_SHA256 = "bcf831df018af843519483a7d2b3e88c286ef201e99463da1e578bf169417473"
V1_IMAGE_ID = "sha256:8a236550df67fe5cd334fd05bd092ff6457daf80ba7fd0077f1a98a6bdcd919f"
V1_BINARY_SHA256 = "98a12265e86a04c3cf384ab36c05f55973f1751914c66d51c89da5b1cd1deac3"
STARTER_IMAGE_ID = "sha256:a754ee9e7301a3c22d36ac93175efae634f9224f5e2a9032b22632f6793b2feb"
EFFECTS_IMAGE_ID = "sha256:7c81b969bae3fd7372a91620854974834b27d58d9ec9f3887e90d9a553746b7f"
TOXIPROXY_VERSION = "2.12.0"
TOXIPROXY_MANIFEST = "a3e244375123dad8849091bcc59775e188624d3f602db01901f9af855682fef8"
TOXIPROXY_IMAGE = f"ghcr.io/shopify/toxiproxy:{TOXIPROXY_VERSION}@sha256:{TOXIPROXY_MANIFEST}"
TOXIPROXY_PROXY = "temporal-payment-cut"
TOXIPROXY_PORT = 8666
TOXIPROXY_LATENCY_MS = 120000
TEMPORAL_IMAGE = (
    "docker.io/temporalio/temporal:1.8.2@"
    "sha256:cf86707827fac99e4d1c4a47dc11b105382d796199c7bd41fb3213fb0471628e"
)
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
MAX_FILE_BYTES = 64 << 20
MAX_RESULTS_BYTES = 256 << 20

EXPECTED_CUT_TYPES = [
    "EVENT_TYPE_WORKFLOW_EXECUTION_STARTED",
    "EVENT_TYPE_WORKFLOW_TASK_SCHEDULED",
    "EVENT_TYPE_WORKFLOW_TASK_STARTED",
    "EVENT_TYPE_WORKFLOW_TASK_COMPLETED",
    "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED",
]

BUILD_KEYS = {
    "GIT_REVISION", "SOURCE_SHA256",
    "WORKER_V1_IMAGE", "WORKER_V1_ID", "WORKER_V1_BINARY_SHA256",
    "WORKER_V1_VARIANT_SHA256",
    "WORKER_V2_IMAGE", "WORKER_V2_ID", "WORKER_V2_BINARY_SHA256",
    "WORKER_COMPATIBLE_V2_IMAGE", "WORKER_COMPATIBLE_V2_ID",
    "WORKER_COMPATIBLE_V2_BINARY_SHA256", "WORKER_COMPATIBLE_V2_VARIANT_SHA256",
    "STARTER_IMAGE", "STARTER_ID", "STARTER_BINARY_SHA256",
    "RUNTIME_SOURCE_SHA256", "EFFECTS_IMAGE", "EFFECTS_ID", "EFFECTS_BINARY_SHA256",
}

REQUIRED_FILES = {
    "SHA256SUMS", "exit-status.txt", "build.env", "versions.env", "old-drain.env",
    "runner.sh", "base-compose.yaml", "compose-old-drain.yaml", "compose-config.yaml",
    "source-variant-v1.go", "source-activities.go", "source-workflows.go",
    "source-types.go", "source-starter.go", "run-metadata.json",
    "v1-image-inspect.json", "starter-image-inspect.json", "effects-image-inspect.json",
    "toxiproxy-image-inspect.json", "toxiproxy-version.json",
    "proxy-create-request.json", "proxy-create-response.json",
    "toxic-create-request.json", "toxic-create-response.json", "proxy-at-cut.json",
    "proxy-after-release.json", "toxic-delete-status.txt", "toxic-delete-body.txt",
    "toxic-delete-headers.txt", "toxic-created-at.txt", "toxic-created-epoch-ns.txt",
    "cut-recorded-at.txt", "cut-epoch-ns.txt", "release-requested-at.txt",
    "release-requested-epoch-ns.txt", "release-confirmed-at.txt",
    "release-confirmed-epoch-ns.txt", "final-recorded-at.txt", "final-epoch-ns.txt",
    "deployment-before-current.json", "version-v1.json", "set-current-v1.json",
    "deployment-v1-current.json", "deployment-final.json", "version-v1-final.json",
    "v1-workflow-pollers.json", "v1-activity-pollers.json",
    "v1-final-workflow-pollers.json", "v1-final-activity-pollers.json",
    "start.json", "cut-history-before.json", "cut-history-after.json", "cut-describe.json",
    "cut-describe-poll.json",
    "payment-cut-stats.json", "completion-cut-stats.json", "payment-cut.history",
    "completion-cut.history", "v1-cut-inspect.json", "containers-cut.json",
    "v2-containers-at-cut.txt", "settled-history.json", "settled-describe.json",
    "settled-query.json", "payment-settled-stats.json", "completion-settled-stats.json",
    "payment-settled.history", "completion-settled.history", "signal-delivery-finished.json",
    "signal-driver-at-restaurant.json", "signal-driver-selected.json",
    "signal-preparation-finished.json",
    "final-history.json", "final-describe.json", "final-query.json",
    "payment-final-stats.json", "completion-final-stats.json", "payment-final.history",
    "completion-final.history", "v1-final-inspect.json", "containers-final.json",
    "v2-containers-final.txt", "v1.log", "observed.json", "compose-ps.txt", "compose.log",
    "docker-events-since-at.txt", "docker-events-since-epoch-ns.txt",
    "docker-events-until-epoch.txt", "docker-events.jsonl",
}


class EvidenceError(ValueError):
    """Raw old-drain evidence is absent, malformed, or contradictory."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceError(message)


def object_value(value: Any, label: str) -> dict[str, Any]:
    require(isinstance(value, dict), f"{label} must be an object")
    return value


def array_value(value: Any, label: str) -> list[Any]:
    require(isinstance(value, list), f"{label} must be an array")
    return value


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        require(key not in value, f"duplicate JSON key: {key}")
        value[key] = item
    return value


def decode_json(data: bytes, label: str) -> Any:
    try:
        return json.loads(data, object_pairs_hook=reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvidenceError(f"{label} is not JSON") from error


def evidence_root(path: Path) -> Path:
    require(path.exists() and path.is_dir() and not path.is_symlink(), "evidence root is absent or unsafe")
    results = path / "results"
    root = results if results.is_dir() else path
    require(root.is_dir() and not root.is_symlink(), "results directory is absent or unsafe")
    return root


def read(root: Path, name: str) -> bytes:
    path = root / name
    require(path.exists() and path.is_file() and not path.is_symlink(), f"missing or unsafe evidence file: {name}")
    require(path.stat().st_size <= MAX_FILE_BYTES, f"evidence file exceeds size limit: {name}")
    return path.read_bytes()


def json_value(root: Path, name: str) -> dict[str, Any]:
    return object_value(decode_json(read(root, name), name), name)


def json_array(root: Path, name: str) -> list[Any]:
    return array_value(decode_json(read(root, name), name), name)


def parse_env(data: bytes, label: str) -> dict[str, str]:
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError as error:
        raise EvidenceError(f"{label} is not ASCII") from error
    values: dict[str, str] = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        require("=" in line, f"invalid {label} line")
        key, value = line.split("=", 1)
        require(re.fullmatch(r"[A-Z0-9_]+", key) is not None and key not in values, f"invalid {label} key")
        values[key] = value
    return values


def verify_checksums(root: Path) -> None:
    items = list(root.iterdir())
    require(all(item.is_file() and not item.is_symlink() for item in items), "results contains a non-regular entry")
    require(sum(item.stat().st_size for item in items) <= MAX_RESULTS_BYTES, "results exceed size limit")
    names = {item.name for item in items}
    require(names == REQUIRED_FILES, "old-drain evidence file set differs")
    lines = read(root, "SHA256SUMS").decode("ascii").splitlines()
    declared: dict[str, str] = {}
    for line in lines:
        parts = line.split("  ", 1)
        require(len(parts) == 2 and HEX64.fullmatch(parts[0]) is not None, "invalid SHA256SUMS line")
        name = parts[1]
        require(name.startswith("./") and "/" not in name[2:] and name[2:] != "SHA256SUMS", "unsafe SHA256SUMS path")
        name = name[2:]
        require(name not in declared, "duplicate SHA256SUMS entry")
        declared[name] = parts[0]
    require(set(declared) == names - {"SHA256SUMS"}, "SHA256SUMS does not cover the exact evidence set")
    for name, digest in declared.items():
        require(sha256(read(root, name)).hexdigest() == digest, f"checksum mismatch: {name}")


def source_digest(files: list[Path], base: Path) -> str:
    stream = bytearray()
    for path in sorted(files):
        require(path.is_file() and not path.is_symlink(), "source tree contains an unsafe entry")
        stream.extend(path.relative_to(base).as_posix().encode())
        stream.append(0)
        stream.extend(sha256(path.read_bytes()).hexdigest().encode())
        stream.extend(b"\n")
    return sha256(stream).hexdigest()


def operation_id(identity: str) -> str:
    raw = b"operation-id-v1\0temporal-order-workflow\0" + identity.encode()
    return "op-" + sha256(raw).hexdigest()


def order_bytes() -> bytes:
    return (
        b'{"order_id":"order-1","restaurant_id":"restaurant-1","products":['
        b'{"product_id":"pizza-1","description":"Margherita Pizza","quantity":2}],'
        b'"amount_cents":4200,"delivery_delay_millis":25,"payment_token":"payment-token-1"}'
    )


def json_payload(value: Any, label: str) -> dict[str, Any]:
    return object_value(decode_json(payload_bytes(value, label), label), label)


def final_result() -> dict[str, Any]:
    return {
        "schema": 1, "order_id": ORDER_ID, "restaurant_id": RESTAURANT_ID,
        "product_count": PRODUCT_QUANTITY, "worker_build": V1_BUILD, "phase": "DELIVERED",
        "delivery_id": DELIVERY_ID, "driver_id": DRIVER_ID,
        "stages": [
            "RESTAURANT_SELECTED", "CREATED", "PAYMENT_PENDING", "PAYMENT_COMMITTED",
            "SCHEDULED", "IN_PREPARATION", "SCHEDULING_DELIVERY", "WAITING_FOR_DRIVER",
            "IN_DELIVERY", "DELIVERED",
        ],
    }


def expected_record(identity: str, path: str, prefix: str) -> dict[str, str]:
    op_id = operation_id(identity)
    body = b'{"order_id":"order-1","amount_cents":4200}'
    request_hash = sha256(b"POST\0" + path.encode() + b"\0" + body).hexdigest()
    result_hash = sha256(b"charged\0" + op_id.encode() + b"\0" + b"1").hexdigest()
    return {
        "operation_id": op_id,
        "request_hash": request_hash,
        "result_hash": result_hash,
        "remote_reference": f"{prefix}/{op_id}/commit-1",
        "path": path,
    }


def one_record(data: bytes, expected: dict[str, str], label: str) -> dict[str, Any]:
    require(data.endswith(b"\n") and data.count(b"\n") == 1, f"{label} must contain exactly one record")
    value = decode_json(data, label)
    record = object_value(value, label)
    require(record == expected, f"{label} differs from the scheduled effect")
    return record


def payload_bytes(value: Any, label: str) -> bytes:
    container = object_value(value, label)
    payloads = array_value(container.get("payloads"), label + " payloads")
    require(len(payloads) == 1, f"{label} must contain one payload")
    payload = object_value(payloads[0], label + " payload")
    require(payload.get("metadata") == {"encoding": "anNvbi9wbGFpbg=="}, f"{label} encoding differs")
    encoded = payload.get("data")
    require(isinstance(encoded, str), f"{label} data is absent")
    try:
        return base64.b64decode(encoded, validate=True)
    except ValueError as error:
        raise EvidenceError(f"{label} data is not base64") from error


def normalize_history(history: dict[str, Any], run_id: str) -> dict[str, Any]:
    normalized = copy.deepcopy(history)
    for event in array_value(normalized.get("events"), "History events"):
        item = object_value(event, "History event")
        item.pop("eventTime", None)
        item.pop("taskId", None)
        for attributes in item.values():
            if not isinstance(attributes, dict):
                continue
            for key in ("originalExecutionRunId", "firstExecutionRunId"):
                if attributes.get(key) == run_id:
                    attributes[key] = "<run-id>"
            attributes.pop("requestId", None)
            attributes.pop("historySizeBytes", None)
            queue = attributes.get("taskQueue")
            if isinstance(queue, dict) and queue.get("kind") == "TASK_QUEUE_KIND_STICKY":
                require(queue.get("normalName") == TASK_QUEUE, "sticky queue normal name differs")
                queue["name"] = "<sticky-queue>"
    return normalized


def parse_time(value: str, label: str) -> datetime:
    require(isinstance(value, str) and value, f"{label} is absent")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise EvidenceError(f"{label} is not ISO-8601") from error


def parse_epoch_ns(root: Path, name: str) -> int:
    value = read(root, name).decode("ascii").strip()
    require(re.fullmatch(r"[0-9]{16,20}", value) is not None, f"{name} differs")
    return int(value)


def event_attributes(event: dict[str, Any], key: str, label: str) -> dict[str, Any]:
    return object_value(event.get(key), label)


def check_wft_scheduled(event: dict[str, Any], sticky: bool) -> dict[str, Any]:
    attributes = event_attributes(event, "workflowTaskScheduledEventAttributes", "Workflow task schedule")
    require(attributes.get("startToCloseTimeout") == "10s" and attributes.get("attempt") == 1,
            "Workflow task scheduling options differ")
    queue = object_value(attributes.get("taskQueue"), "Workflow task queue")
    if sticky:
        require(
            queue.get("kind") == "TASK_QUEUE_KIND_STICKY" and
            queue.get("normalName") == TASK_QUEUE and
            isinstance(queue.get("name"), str) and bool(queue["name"]),
            "sticky Workflow task queue differs",
        )
    else:
        require(queue == {"name": TASK_QUEUE, "kind": "TASK_QUEUE_KIND_NORMAL"},
                "normal Workflow task queue differs")
    return queue


def check_wft_started(event: dict[str, Any], scheduled: str) -> None:
    attributes = event_attributes(event, "workflowTaskStartedEventAttributes", "Workflow task start")
    require(attributes.get("scheduledEventId") == scheduled and attributes.get("identity") == V1_IDENTITY,
            "Workflow task start identity/link differs")
    require(isinstance(attributes.get("requestId"), str) and bool(attributes["requestId"]),
            "Workflow task request ID is absent")


def check_wft_completed(event: dict[str, Any], scheduled: str, started: str) -> None:
    attributes = event_attributes(event, "workflowTaskCompletedEventAttributes", "Workflow task completion")
    require(
        attributes.get("scheduledEventId") == scheduled and attributes.get("startedEventId") == started and
        attributes.get("identity") == V1_IDENTITY and
        attributes.get("workerVersion") == {"buildId": V1_BUILD, "useVersioning": True} and
        attributes.get("versioningBehavior") == "VERSIONING_BEHAVIOR_PINNED" and
        attributes.get("workerDeploymentName") == DEPLOYMENT and
        attributes.get("deploymentVersion") == {"buildId": V1_BUILD, "deploymentName": DEPLOYMENT},
        "Workflow task completion version/link differs",
    )


def check_activity_schedule(
    event: dict[str, Any], activity_id: str, activity_type: str,
    workflow_task_completed: str, body: bytes, timeout: str,
) -> None:
    attributes = event_attributes(event, "activityTaskScheduledEventAttributes", activity_type + " schedule")
    require(
        attributes.get("activityId") == activity_id and
        attributes.get("activityType") == {"name": activity_type} and
        attributes.get("taskQueue") == {"name": TASK_QUEUE, "kind": "TASK_QUEUE_KIND_NORMAL"} and
        payload_bytes(attributes.get("input"), activity_type + " input") == body and
        attributes.get("header") == {} and
        attributes.get("scheduleToCloseTimeout") == "0s" and
        attributes.get("scheduleToStartTimeout") == "0s" and
        attributes.get("startToCloseTimeout") == timeout and
        attributes.get("heartbeatTimeout") == "0s" and
        attributes.get("workflowTaskCompletedEventId") == workflow_task_completed and
        attributes.get("retryPolicy") == {
            "initialInterval": "1s", "backoffCoefficient": 2,
            "maximumInterval": "100s", "maximumAttempts": 1,
        } and attributes.get("useWorkflowBuildId") is True,
        f"{activity_type} scheduling semantics differ",
    )


def check_activity_started(event: dict[str, Any], scheduled: str) -> None:
    attributes = event_attributes(event, "activityTaskStartedEventAttributes", "Activity start")
    require(
        attributes.get("scheduledEventId") == scheduled and attributes.get("attempt") == 1 and
        attributes.get("identity") == V1_IDENTITY and
        attributes.get("workerVersion") == {"buildId": V1_BUILD, "useVersioning": True},
        "Activity start link/version differs",
    )


def expected_receipt(record: dict[str, str]) -> dict[str, Any]:
    return {
        "schema": 1, "operation_id": record["operation_id"], "outcome": "succeeded",
        "result_hash": record["result_hash"], "remote_reference": record["remote_reference"],
    }


def check_activity_completed(
    event: dict[str, Any], scheduled: str, started: str, record: dict[str, str],
) -> None:
    attributes = event_attributes(event, "activityTaskCompletedEventAttributes", "Activity completion")
    require(
        attributes.get("scheduledEventId") == scheduled and attributes.get("startedEventId") == started and
        attributes.get("identity") == V1_IDENTITY,
        "Activity completion identity/link differs",
    )
    receipt = object_value(decode_json(payload_bytes(attributes.get("result"), "Activity result"), "Activity result"),
                           "Activity receipt")
    require(receipt == expected_receipt(record), "Activity receipt/provider fact mismatch")


def check_inputs(root: Path) -> dict[str, str]:
    local_bindings = {
        "versions.env": SCRIPT_DIR / "versions.env",
        "old-drain.env": SCRIPT_DIR / "old-drain.env",
        "runner.sh": SCRIPT_DIR / "run-old-drain-case.sh",
        "base-compose.yaml": SCRIPT_DIR / "compose.yaml",
        "compose-old-drain.yaml": SCRIPT_DIR / "compose-old-drain.yaml",
        "source-variant-v1.go": SCRIPT_DIR / "app/internal/workerapp/variant_v1.go",
        "source-activities.go": SCRIPT_DIR / "app/internal/workerapp/activities.go",
        "source-workflows.go": SCRIPT_DIR / "app/internal/workerapp/workflows.go",
        "source-types.go": SCRIPT_DIR / "app/internal/harness/types.go",
        "source-starter.go": SCRIPT_DIR / "app/cmd/starter/main.go",
    }
    for name, path in local_bindings.items():
        require(read(root, name) == path.read_bytes(), f"{name} differs from the checked harness")
    require(sha256(read(root, "build.env")).hexdigest() == BUILD_ENV_SHA256, "frozen build.env bytes differ")
    require(sha256(read(root, "source-variant-v1.go")).hexdigest() == V1_SOURCE_SHA256, "v1 source snapshot differs")
    require(sha256(read(root, "source-activities.go")).hexdigest() == ACTIVITIES_SOURCE_SHA256, "Activity source snapshot differs")
    require(sha256(read(root, "source-workflows.go")).hexdigest() == WORKFLOWS_SOURCE_SHA256, "Workflow source snapshot differs")
    require(sha256(read(root, "source-types.go")).hexdigest() == TYPES_SOURCE_SHA256, "harness type source snapshot differs")
    require(sha256(read(root, "source-starter.go")).hexdigest() == STARTER_SOURCE_SHA256, "starter source snapshot differs")

    versions = parse_env(read(root, "versions.env"), "versions.env")
    require(versions.get("TEMPORAL_CLI_VERSION") == "1.8.2", "Temporal CLI version differs")
    require(versions.get("TEMPORAL_SERVER_VERSION") == "1.31.2", "Temporal Server version differs")
    require(versions.get("TEMPORAL_GO_SDK_VERSION") == "v1.47.0", "Temporal SDK version differs")
    require(versions.get("TEMPORAL_IMAGE") == TEMPORAL_IMAGE, "Temporal image differs")
    old = parse_env(read(root, "old-drain.env"), "old-drain.env")
    require(old == {
        "TOXIPROXY_VERSION": TOXIPROXY_VERSION,
        "TOXIPROXY_IMAGE": TOXIPROXY_IMAGE,
        "TOXIPROXY_AMD64_MANIFEST_SHA256": TOXIPROXY_MANIFEST,
        "TOXIPROXY_PROXY_NAME": TOXIPROXY_PROXY,
        "TOXIPROXY_LISTEN_PORT": str(TOXIPROXY_PORT),
        "TOXIPROXY_LATENCY_MS": str(TOXIPROXY_LATENCY_MS),
    }, "old-drain tool pin differs")

    build = parse_env(read(root, "build.env"), "build.env")
    require(set(build) == BUILD_KEYS, "build.env fields differ")
    require(HEX40.fullmatch(build["GIT_REVISION"]) is not None, "build revision is invalid")
    for key, value in build.items():
        if key.endswith("_SHA256"):
            require(HEX64.fullmatch(value) is not None, f"{key} is not SHA-256")
        if key.endswith("_ID"):
            require(IMAGE_ID.fullmatch(value) is not None, f"{key} is not an image ID")
    require(build["SOURCE_SHA256"] == SOURCE_SHA256, "frozen Temporal source hash differs")
    require(build["RUNTIME_SOURCE_SHA256"] == RUNTIME_SOURCE_SHA256, "frozen effect source hash differs")
    require(build["WORKER_V1_ID"] == V1_IMAGE_ID, "frozen v1 image differs")
    require(build["WORKER_V1_BINARY_SHA256"] == V1_BINARY_SHA256, "frozen v1 binary differs")
    require(build["STARTER_ID"] == STARTER_IMAGE_ID, "frozen starter image differs")
    require(build["EFFECTS_ID"] == EFFECTS_IMAGE_ID, "frozen effects image differs")
    revision = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "cat-file", "-e", build["GIT_REVISION"] + "^{commit}"],
        capture_output=True,
    )
    require(revision.returncode == 0, "recorded build commit is absent")

    app_files = [path for path in (SCRIPT_DIR / "app").rglob("*") if path.is_file()]
    require(source_digest(app_files, REPO_ROOT) == SOURCE_SHA256, "live Temporal source hash differs")
    runtime_dir = REPO_ROOT / "runtime"
    runtime_inputs = [runtime_dir / "go.mod", runtime_dir / "go.sum"]
    for directory in (runtime_dir / "cmd/payment", runtime_dir / "internal/kernel", runtime_dir / "internal/payment"):
        runtime_inputs.extend(path for path in directory.rglob("*") if path.is_file())
    require(source_digest(runtime_inputs, REPO_ROOT) == RUNTIME_SOURCE_SHA256, "live effects source hash differs")

    inspections = {
        "v1-image-inspect.json": V1_IMAGE_ID,
        "starter-image-inspect.json": STARTER_IMAGE_ID,
        "effects-image-inspect.json": EFFECTS_IMAGE_ID,
    }
    for name, expected_id in inspections.items():
        values = json_array(root, name)
        require(len(values) == 1 and object_value(values[0], name).get("Id") == expected_id, f"{name} image ID differs")
    toxiproxy = json_array(root, "toxiproxy-image-inspect.json")
    require(len(toxiproxy) == 1, "Toxiproxy image inspect count differs")
    proxy_image = object_value(toxiproxy[0], "Toxiproxy image")
    require(IMAGE_ID.fullmatch(str(proxy_image.get("Id"))) is not None, "Toxiproxy image ID differs")
    require(proxy_image.get("Architecture") == "amd64" and proxy_image.get("Os") == "linux", "Toxiproxy platform differs")
    repo_digests = array_value(proxy_image.get("RepoDigests"), "Toxiproxy RepoDigests")
    require(any(str(item).endswith("@sha256:" + TOXIPROXY_MANIFEST) for item in repo_digests), "Toxiproxy manifest digest differs")
    return build


def check_metadata(root: Path, expected_case: str | None) -> tuple[str, str]:
    metadata = json_value(root, "run-metadata.json")
    case = metadata.get("case")
    require(case in {"h0", "h1"}, "old-drain case differs")
    if expected_case is not None:
        require(case == expected_case, "old-drain case does not match CLI expectation")
    stream = "upstream" if case == "h0" else "downstream"
    require(
        metadata.get("schema") == 1 and metadata.get("cell") == "old-drain" and
        metadata.get("system") == "temporal-pinned" and metadata.get("workflow_id") == WORKFLOW_ID and
        metadata.get("order_id") == ORDER_ID and metadata.get("payment_token") == PAYMENT_TOKEN and
        metadata.get("restaurant_id") == RESTAURANT_ID and
        metadata.get("products") == [{
            "product_id": PRODUCT_ID, "description": PRODUCT_DESCRIPTION,
            "quantity": PRODUCT_QUANTITY,
        }] and metadata.get("delivery_delay_millis") == DELIVERY_DELAY_MILLIS and
        metadata.get("amount_cents") == AMOUNT_CENTS,
        "old-drain workload metadata differs",
    )
    require(metadata.get("fault") == {
        "tool": "toxiproxy", "toxic": "latency", "stream": stream,
        "latency_ms": TOXIPROXY_LATENCY_MS, "jitter_ms": 0,
    }, "old-drain fault metadata differs")
    invocation = object_value(metadata.get("effective_invocation"), "effective invocation")
    require(
        invocation.get("OLD_DRAIN_CASE") == case and invocation.get("SKIP_BUILD") == 1 and
        invocation.get("script") == "runtime/deploy/temporal/run-old-drain-case.sh",
        "effective invocation differs",
    )
    start = json_value(root, "start.json")
    require(set(start) == {"schema", "behavior", "workflow_id", "run_id"}, "starter output fields differ")
    require(start.get("schema") == 1 and start.get("behavior") == "pinned" and start.get("workflow_id") == WORKFLOW_ID, "starter output differs")
    run_id = start.get("run_id")
    require(
        isinstance(run_id, str) and
        re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", run_id) is not None,
        "run ID differs",
    )
    return str(case), run_id


def check_cut(root: Path, run_id: str) -> tuple[dict[str, Any], dict[str, Any], str]:
    before_data = read(root, "cut-history-before.json")
    require(before_data == read(root, "cut-history-after.json"), "cut History double-read is unstable")
    history = json_value(root, "cut-history-before.json")
    require(set(history) == {"events"}, "cut History envelope differs")
    events = array_value(history.get("events"), "cut History events")
    require([object_value(event, "cut event").get("eventType") for event in events] == EXPECTED_CUT_TYPES, "cut History event sequence differs")
    require([event.get("eventId") for event in events] == [str(index) for index in range(1, 6)], "cut event IDs differ")
    require(all(isinstance(event.get("eventTime"), str) and event["eventTime"] for event in events),
            "cut event time is absent")
    started = object_value(events[0].get("workflowExecutionStartedEventAttributes"), "Workflow start")
    require(started.get("workflowType") == {"name": "FoodOrderPinned"}, "Workflow type differs")
    require(
        started.get("workflowId") == WORKFLOW_ID and
        started.get("identity") == "safe-change-temporal-starter" and
        started.get("taskQueue") == {"name": TASK_QUEUE, "kind": "TASK_QUEUE_KIND_NORMAL"} and
        started.get("attempt") == 1 and started.get("workflowTaskTimeout") == "10s",
        "Workflow identity/options differ",
    )
    require(started.get("originalExecutionRunId") == run_id and started.get("firstExecutionRunId") == run_id, "Workflow run binding differs")
    require(payload_bytes(started.get("input"), "Workflow input") == order_bytes(), "Workflow input differs")
    check_wft_scheduled(events[1], False)
    check_wft_started(events[2], "2")
    check_wft_completed(events[3], "2", "3")
    payment_id = operation_id(PAYMENT_TOKEN)
    expected_payment = (
        b'{"order_id":"order-1","amount_cents":4200,"operation_id":"' +
        payment_id.encode() + b'"}'
    )
    check_activity_schedule(events[4], "5", "ChargePayment", "4", expected_payment, "30s")

    describe = json_value(root, "cut-describe.json")
    info = object_value(describe.get("workflowExecutionInfo"), "cut Workflow info")
    require(info.get("execution") == {"workflowId": WORKFLOW_ID, "runId": run_id}, "cut execution differs")
    require(
        info.get("status") == "WORKFLOW_EXECUTION_STATUS_RUNNING" and
        info.get("type") == {"name": "FoodOrderPinned"} and info.get("taskQueue") == TASK_QUEUE and
        info.get("historyLength") == "5" and
        info.get("mostRecentWorkerVersionStamp") == {"buildId": V1_BUILD, "useVersioning": True} and
        info.get("workerDeploymentName") == DEPLOYMENT,
        "cut Workflow identity/state differs",
    )
    versioning = object_value(info.get("versioningInfo"), "cut versioning info")
    require(
        versioning.get("behavior") == "VERSIONING_BEHAVIOR_PINNED" and
        versioning.get("version") == f"{DEPLOYMENT}.{V1_BUILD}" and
        versioning.get("deploymentVersion") == {"buildId": V1_BUILD, "deploymentName": DEPLOYMENT} and
        versioning.get("revisionNumber") == "1" and
        "versionTransition" not in versioning,
        "cut execution is not pinned to v1",
    )
    pending = array_value(describe.get("pendingActivities"), "pending Activities")
    require(len(pending) == 1, "cut must contain one pending Activity")
    activity = object_value(pending[0], "pending Payment")
    require(
        activity.get("activityId") == "5" and activity.get("activityType") == {"name": "ChargePayment"} and
        activity.get("state") == "PENDING_ACTIVITY_STATE_STARTED" and activity.get("attempt") == 1 and
        activity.get("maximumAttempts") == 1 and activity.get("lastWorkerIdentity") == V1_IDENTITY and
        activity.get("lastWorkerDeploymentVersion") == f"{DEPLOYMENT}.{V1_BUILD}" and
        activity.get("lastDeploymentVersion") == {"buildId": V1_BUILD, "deploymentName": DEPLOYMENT},
        "pending Payment state/version differs",
    )
    options = object_value(activity.get("activityOptions"), "pending Payment options")
    require(
        options.get("taskQueue") == {"name": TASK_QUEUE, "normalName": TASK_QUEUE} and
        options.get("scheduleToCloseTimeout") == "0s" and
        options.get("scheduleToStartTimeout") == "0s" and
        options.get("startToCloseTimeout") == "30s" and options.get("heartbeatTimeout") == "0s" and
        options.get("retryPolicy") == {
            "initialInterval": "1s", "backoffCoefficient": 2,
            "maximumInterval": "100s", "maximumAttempts": 1,
        },
        "pending Payment options differ",
    )
    last_started = parse_time(str(activity.get("lastStartedTime")), "pending Payment start")
    scheduled_time = parse_time(str(activity.get("scheduledTime")), "pending Payment schedule")
    toxic_time = parse_time(read(root, "toxic-created-at.txt").decode("ascii").strip(), "toxic creation time")
    cut_time = parse_time(read(root, "cut-recorded-at.txt").decode("ascii").strip(), "cut recording time")
    require(toxic_time < scheduled_time <= last_started <= cut_time, "pending Payment/cut timestamps differ")
    projection = {
        "execution": {"workflowId": WORKFLOW_ID}, "status": info.get("status"),
        "type": info.get("type"), "taskQueue": info.get("taskQueue"),
        "workerDeploymentName": info.get("workerDeploymentName"), "versioningInfo": versioning,
        "pending": {key: activity.get(key) for key in (
            "activityId", "activityType", "state", "attempt", "maximumAttempts",
            "lastWorkerIdentity", "lastWorkerDeploymentVersion", "lastDeploymentVersion", "activityOptions",
        )},
    }
    return normalize_history(history, run_id), projection, payment_id


def check_stats(root: Path, name: str, expected: dict[str, Any]) -> None:
    value = json_value(root, name)
    require(set(value) == {"deliveries", "commits", "paths"} and value == expected, f"{name} differs")


def check_provider(root: Path, case: str) -> tuple[dict[str, Any], dict[str, Any]]:
    cut_payment = (
        {"deliveries": 0, "commits": 0, "paths": {}} if case == "h0" else
        {"deliveries": 1, "commits": 1, "paths": {"/v1/charge": 1}}
    )
    final_payment = {"deliveries": 1, "commits": 1, "paths": {"/v1/charge": 1}}
    no_completion = {"deliveries": 0, "commits": 0, "paths": {}}
    final_completion = {"deliveries": 1, "commits": 1, "paths": {"/v1/complete": 1}}
    check_stats(root, "payment-cut-stats.json", cut_payment)
    check_stats(root, "completion-cut-stats.json", no_completion)
    check_stats(root, "payment-settled-stats.json", final_payment)
    check_stats(root, "completion-settled-stats.json", no_completion)
    check_stats(root, "payment-final-stats.json", final_payment)
    check_stats(root, "completion-final-stats.json", final_completion)

    payment = expected_record(PAYMENT_TOKEN, "/v1/charge", "temporal-payment")
    completion = expected_record("complete:" + ORDER_ID, "/v1/complete", "temporal-completion")
    cut_payment_data = read(root, "payment-cut.history")
    if case == "h0":
        require(cut_payment_data == b"", "H0 contains a payment at the cut")
    else:
        one_record(cut_payment_data, payment, "H1 cut payment")
    require(read(root, "completion-cut.history") == b"", "completion occurred at the cut")
    one_record(read(root, "payment-settled.history"), payment, "settled payment")
    require(read(root, "completion-settled.history") == b"", "completion occurred before the signal")
    one_record(read(root, "payment-final.history"), payment, "final payment")
    one_record(read(root, "completion-final.history"), completion, "final completion")
    if case == "h1":
        require(cut_payment_data == read(root, "payment-settled.history"), "H1 payment changed after the cut")
    require(read(root, "payment-settled.history") == read(root, "payment-final.history"), "payment changed after settlement")
    return payment, completion


def check_toxic_document(value: dict[str, Any], case: str, label: str) -> None:
    stream = "upstream" if case == "h0" else "downstream"
    require(set(value) == {"name", "listen", "upstream", "enabled", "Logger", "toxics"}, f"{label} fields differ")
    require(value.get("name") == TOXIPROXY_PROXY, f"{label} proxy name differs")
    require(value.get("listen") == f"[::]:{TOXIPROXY_PORT}" or value.get("listen") == f"0.0.0.0:{TOXIPROXY_PORT}",
            f"{label} listen address differs")
    require(value.get("upstream") == "payment:8081" and value.get("enabled") is True and value.get("Logger") == {},
            f"{label} route differs")
    toxics = array_value(value.get("toxics"), label + " toxics")
    require(len(toxics) == 1, f"{label} must contain one toxic")
    toxic = object_value(toxics[0], label + " toxic")
    require(
        toxic.get("name") == "history-cut" and toxic.get("type") == "latency" and
        toxic.get("stream") == stream and toxic.get("toxicity") == 1 and
        toxic.get("attributes") == {"latency": TOXIPROXY_LATENCY_MS, "jitter": 0},
        f"{label} toxic differs",
    )


def check_toxiproxy(root: Path, case: str) -> None:
    version = json_value(root, "toxiproxy-version.json")
    require(version == {"version": TOXIPROXY_VERSION}, "Toxiproxy server version differs")
    create = json_value(root, "proxy-create-request.json")
    require(create == {
        "name": TOXIPROXY_PROXY, "listen": f"0.0.0.0:{TOXIPROXY_PORT}",
        "upstream": "payment:8081", "enabled": True,
    }, "proxy creation request differs")
    response = json_value(root, "proxy-create-response.json")
    require(response == {
        "name": TOXIPROXY_PROXY, "listen": f"[::]:{TOXIPROXY_PORT}",
        "upstream": "payment:8081", "enabled": True, "Logger": {}, "toxics": [],
    } or response == {
        "name": TOXIPROXY_PROXY, "listen": f"0.0.0.0:{TOXIPROXY_PORT}",
        "upstream": "payment:8081", "enabled": True, "Logger": {}, "toxics": [],
    }, "proxy creation response differs")
    toxic_request = json_value(root, "toxic-create-request.json")
    expected_stream = "upstream" if case == "h0" else "downstream"
    require(toxic_request == {
        "name": "history-cut", "type": "latency", "stream": expected_stream, "toxicity": 1,
        "attributes": {"latency": TOXIPROXY_LATENCY_MS, "jitter": 0},
    }, "toxic creation request differs")
    toxic_response = json_value(root, "toxic-create-response.json")
    require(
        toxic_response.get("name") == "history-cut" and toxic_response.get("type") == "latency" and
        toxic_response.get("stream") == expected_stream and toxic_response.get("toxicity") == 1 and
        toxic_response.get("attributes") == {"latency": TOXIPROXY_LATENCY_MS, "jitter": 0},
        "toxic creation response differs",
    )
    check_toxic_document(json_value(root, "proxy-at-cut.json"), case, "cut proxy")
    after = json_value(root, "proxy-after-release.json")
    require(
        set(after) == {"name", "listen", "upstream", "enabled", "Logger", "toxics"} and
        after.get("name") == TOXIPROXY_PROXY and
        after.get("listen") in {f"[::]:{TOXIPROXY_PORT}", f"0.0.0.0:{TOXIPROXY_PORT}"} and
        after.get("upstream") == "payment:8081" and after.get("enabled") is True and
        after.get("Logger") == {} and after.get("toxics") == [],
        "proxy toxic was not removed",
    )
    require(read(root, "toxic-delete-status.txt") == b"204\n", "toxic deletion HTTP status differs")
    require(read(root, "toxic-delete-body.txt") == b"", "toxic deletion returned a body")
    headers = read(root, "toxic-delete-headers.txt").decode("ascii", errors="strict")
    require(
        bool(headers.splitlines()) and
        re.fullmatch(r"HTTP/[0-9.]+ 204(?: [^\r\n]+)?", headers.splitlines()[0]) is not None,
        "toxic deletion response headers differ",
    )

    toxic_ns = parse_epoch_ns(root, "toxic-created-epoch-ns.txt")
    cut_ns = parse_epoch_ns(root, "cut-epoch-ns.txt")
    requested_ns = parse_epoch_ns(root, "release-requested-epoch-ns.txt")
    confirmed_ns = parse_epoch_ns(root, "release-confirmed-epoch-ns.txt")
    final_ns = parse_epoch_ns(root, "final-epoch-ns.txt")
    require(toxic_ns < cut_ns <= requested_ns <= confirmed_ns < final_ns, "fault/cut/release/final chronology differs")
    require(requested_ns < toxic_ns + TOXIPROXY_LATENCY_MS * 1_000_000,
            "latency could have expired before explicit deletion")
    for name in ("toxic-created-at.txt", "cut-recorded-at.txt", "release-requested-at.txt", "release-confirmed-at.txt", "final-recorded-at.txt"):
        parse_time(read(root, name).decode("ascii").strip(), name)


def check_settlement_and_final(root: Path, run_id: str) -> tuple[datetime, dict[str, Any], dict[str, Any]]:
    cut = json_value(root, "cut-history-before.json")
    settled = json_value(root, "settled-history.json")
    final = json_value(root, "final-history.json")
    require(set(cut) == set(settled) == set(final) == {"events"}, "History envelope fields differ")
    cut_events = array_value(cut.get("events"), "cut events")
    settled_events = [object_value(event, "settled event") for event in array_value(settled.get("events"), "settled events")]
    final_events = [object_value(event, "final event") for event in array_value(final.get("events"), "final events")]
    require(
        [event.get("eventId") for event in final_events] ==
        [str(index) for index in range(1, len(final_events) + 1)],
        "final event IDs differ",
    )
    require(all(isinstance(event.get("eventTime"), str) and event["eventTime"] for event in final_events),
            "final event time is absent")
    require(settled_events[:len(cut_events)] == cut_events, "settled History does not extend the cut")
    require(final_events[:len(settled_events)] == settled_events, "final History does not extend settlement")
    allowed_types = {
        "EVENT_TYPE_WORKFLOW_EXECUTION_STARTED", "EVENT_TYPE_WORKFLOW_TASK_SCHEDULED",
        "EVENT_TYPE_WORKFLOW_TASK_STARTED", "EVENT_TYPE_WORKFLOW_TASK_COMPLETED",
        "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED", "EVENT_TYPE_ACTIVITY_TASK_STARTED",
        "EVENT_TYPE_ACTIVITY_TASK_COMPLETED", "EVENT_TYPE_TIMER_STARTED", "EVENT_TYPE_TIMER_FIRED",
        "EVENT_TYPE_WORKFLOW_EXECUTION_SIGNALED", "EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED",
    }
    require(all(event.get("eventType") in allowed_types for event in final_events), "unexpected final History event")

    wft_schedules = {
        event["eventId"]: event for event in final_events
        if event.get("eventType") == "EVENT_TYPE_WORKFLOW_TASK_SCHEDULED"
    }
    wft_starts = [event for event in final_events if event.get("eventType") == "EVENT_TYPE_WORKFLOW_TASK_STARTED"]
    wft_completions = [event for event in final_events if event.get("eventType") == "EVENT_TYPE_WORKFLOW_TASK_COMPLETED"]
    require(len(wft_schedules) == len(wft_starts) == len(wft_completions), "Workflow task event counts differ")
    sticky_queues = []
    for index, event in enumerate(wft_schedules.values()):
        queue = check_wft_scheduled(event, index != 0)
        if index:
            sticky_queues.append(queue)
    require(sticky_queues and all(queue == sticky_queues[0] for queue in sticky_queues),
            "retained v1 sticky queue changed")
    start_by_schedule: dict[str, dict[str, Any]] = {}
    for event in wft_starts:
        attributes = event_attributes(event, "workflowTaskStartedEventAttributes", "Workflow task start")
        scheduled_id = attributes.get("scheduledEventId")
        require(isinstance(scheduled_id, str) and scheduled_id in wft_schedules,
                "Workflow task start schedule differs")
        check_wft_started(event, scheduled_id)
        start_by_schedule[scheduled_id] = event
    for event in wft_completions:
        attributes = event_attributes(event, "workflowTaskCompletedEventAttributes", "Workflow task completion")
        scheduled_id = attributes.get("scheduledEventId")
        require(isinstance(scheduled_id, str) and scheduled_id in start_by_schedule,
                "Workflow task completion schedule differs")
        check_wft_completed(event, scheduled_id, start_by_schedule[scheduled_id]["eventId"])

    activity_schedules = [
        event for event in final_events if event.get("eventType") == "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED"
    ]
    activity_types = [
        event.get("activityTaskScheduledEventAttributes", {}).get("activityType", {}).get("name")
        for event in activity_schedules
    ]
    require(activity_types == ["ChargePayment", "PrepareFood", "ScheduleDelivery", "CompleteOrder"],
            "food-ordering Activity sequence differs")

    payment_record = expected_record(PAYMENT_TOKEN, "/v1/charge", "temporal-payment")
    completion_record = expected_record("complete:" + ORDER_ID, "/v1/complete", "temporal-completion")
    payment_id = operation_id(PAYMENT_TOKEN)
    completion_id = operation_id("complete:" + ORDER_ID)
    activity_inputs = {
        "ChargePayment": (
            b'{"order_id":"order-1","amount_cents":4200,"operation_id":"' +
            payment_id.encode() + b'"}', "30s",
        ),
        "PrepareFood": (
            b'{"order_id":"order-1","restaurant_id":"restaurant-1","products":['
            b'{"product_id":"pizza-1","description":"Margherita Pizza","quantity":2}]}', "30s",
        ),
        "ScheduleDelivery": (
            b'{"order_id":"order-1","delivery_id":"delivery-order-1",'
            b'"restaurant_id":"restaurant-1","region":"San Jose (CA)"}', "30s",
        ),
        "CompleteOrder": (
            b'{"order_id":"order-1","amount_cents":4200,"operation_id":"' +
            completion_id.encode() + b'"}', "60s",
        ),
    }
    completed_wft_ids = {event["eventId"] for event in wft_completions}
    for event, activity_type in zip(activity_schedules, activity_types, strict=True):
        attributes = event_attributes(event, "activityTaskScheduledEventAttributes", activity_type + " schedule")
        wft_completed = attributes.get("workflowTaskCompletedEventId")
        require(isinstance(wft_completed, str) and wft_completed in completed_wft_ids,
                "Activity Workflow task link differs")
        body, timeout = activity_inputs[activity_type]
        check_activity_schedule(event, event["eventId"], activity_type, wft_completed, body, timeout)

    activity_starts: dict[str, dict[str, Any]] = {}
    activity_completions: dict[str, dict[str, Any]] = {}
    for event in final_events:
        if event.get("eventType") == "EVENT_TYPE_ACTIVITY_TASK_STARTED":
            attributes = event_attributes(event, "activityTaskStartedEventAttributes", "Activity start")
            scheduled_id = attributes.get("scheduledEventId")
            require(isinstance(scheduled_id, str) and scheduled_id not in activity_starts,
                    "Activity start set differs")
            activity_starts[scheduled_id] = event
        elif event.get("eventType") == "EVENT_TYPE_ACTIVITY_TASK_COMPLETED":
            attributes = event_attributes(event, "activityTaskCompletedEventAttributes", "Activity completion")
            scheduled_id = attributes.get("scheduledEventId")
            require(isinstance(scheduled_id, str) and scheduled_id not in activity_completions,
                    "Activity completion set differs")
            activity_completions[scheduled_id] = event
    schedule_ids = {event["eventId"] for event in activity_schedules}
    require(set(activity_starts) == schedule_ids == set(activity_completions), "Activity execution set differs")
    for event in activity_schedules:
        scheduled_id = event["eventId"]
        check_activity_started(activity_starts[scheduled_id], scheduled_id)
        completion_attributes = event_attributes(
            activity_completions[scheduled_id], "activityTaskCompletedEventAttributes", "Activity completion",
        )
        require(
            completion_attributes.get("startedEventId") == activity_starts[scheduled_id]["eventId"] and
            completion_attributes.get("identity") == V1_IDENTITY,
            "Activity completion link/version differs",
        )
    check_activity_completed(
        activity_completions[activity_schedules[0]["eventId"]],
        activity_schedules[0]["eventId"], activity_starts[activity_schedules[0]["eventId"]]["eventId"],
        payment_record,
    )
    check_activity_completed(
        activity_completions[activity_schedules[3]["eventId"]],
        activity_schedules[3]["eventId"], activity_starts[activity_schedules[3]["eventId"]]["eventId"],
        completion_record,
    )
    require(
        json_payload(
            activity_completions[activity_schedules[1]["eventId"]].get("activityTaskCompletedEventAttributes", {}).get("result"),
            "PrepareFood result",
        ) == {
            "schema": 1, "order_id": ORDER_ID, "restaurant_id": RESTAURANT_ID,
            "product_count": PRODUCT_QUANTITY, "outcome": "accepted",
        },
        "PrepareFood receipt differs",
    )
    require(
        json_payload(
            activity_completions[activity_schedules[2]["eventId"]].get("activityTaskCompletedEventAttributes", {}).get("result"),
            "ScheduleDelivery result",
        ) == {
            "schema": 1, "order_id": ORDER_ID, "delivery_id": DELIVERY_ID,
            "restaurant_id": RESTAURANT_ID, "region": "San Jose (CA)", "outcome": "scheduled",
        },
        "ScheduleDelivery receipt differs",
    )

    payment_completion = activity_completions[activity_schedules[0]["eventId"]]
    completion_time = parse_time(str(payment_completion.get("eventTime")), "payment completion time")
    release_requested = parse_time(read(root, "release-requested-at.txt").decode("ascii").strip(), "release request time")
    require(release_requested <= completion_time, "payment completed before toxic deletion was requested")
    completion_epoch_ns = int(completion_time.timestamp() * 1_000_000_000)
    require(
        completion_epoch_ns < parse_epoch_ns(root, "toxic-created-epoch-ns.txt") + TOXIPROXY_LATENCY_MS * 1_000_000,
        "payment could have completed by natural latency expiry",
    )

    settled_query = json_value(root, "settled-query.json")
    require(settled_query == {"queryResult": [{
        "schema": 1, "order_id": ORDER_ID, "restaurant_id": RESTAURANT_ID,
        "product_count": PRODUCT_QUANTITY, "worker_build": V1_BUILD, "phase": "IN_PREPARATION",
        "delivery_id": "", "driver_id": "",
        "stages": [
            "RESTAURANT_SELECTED", "CREATED", "PAYMENT_PENDING", "PAYMENT_COMMITTED",
            "SCHEDULED", "IN_PREPARATION",
        ],
    }]}, "settled Workflow query differs")
    settled_describe = json_value(root, "settled-describe.json")
    settled_info = object_value(settled_describe.get("workflowExecutionInfo"), "settled info")
    require(
        settled_info.get("execution") == {"workflowId": WORKFLOW_ID, "runId": run_id} and
        settled_info.get("status") == "WORKFLOW_EXECUTION_STATUS_RUNNING" and
        settled_info.get("historyLength") == str(len(settled_events)) and settled_info.get("type") == {"name": "FoodOrderPinned"} and
        settled_info.get("taskQueue") == TASK_QUEUE and settled_info.get("workerDeploymentName") == DEPLOYMENT and
        settled_info.get("mostRecentWorkerVersionStamp") == {"buildId": V1_BUILD, "useVersioning": True},
        "settled Workflow state differs",
    )
    require(
        settled_info.get("versioningInfo") == {
            "behavior": "VERSIONING_BEHAVIOR_PINNED", "version": f"{DEPLOYMENT}.{V1_BUILD}",
            "deploymentVersion": {"buildId": V1_BUILD, "deploymentName": DEPLOYMENT}, "revisionNumber": "1",
        },
        "settled Workflow lost v1 pinning",
    )
    require(settled_describe.get("pendingActivities") is None and settled_describe.get("result") is None and
            settled_describe.get("closeEvent") is None, "settled Workflow has unexpected pending/terminal data")

    timers_started = [event for event in final_events if event.get("eventType") == "EVENT_TYPE_TIMER_STARTED"]
    timers_fired = [event for event in final_events if event.get("eventType") == "EVENT_TYPE_TIMER_FIRED"]
    require(len(timers_started) == len(timers_fired) == 1, "preparation timer event set differs")
    timer_start = event_attributes(timers_started[0], "timerStartedEventAttributes", "preparation timer start")
    timer_fire = event_attributes(timers_fired[0], "timerFiredEventAttributes", "preparation timer fire")
    require(
        timer_start.get("startToFireTimeout") == "0.025s" and
        timer_fire.get("timerId") == timer_start.get("timerId") and
        timer_fire.get("startedEventId") == timers_started[0]["eventId"],
        "preparation timer semantics differ",
    )

    expected_settled_counts = {
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
    settled_counts = {
        event_type: sum(event.get("eventType") == event_type for event in settled_events)
        for event_type in expected_settled_counts
    }
    require(settled_counts == expected_settled_counts and len(settled_events) == 21,
            "settled History event set differs")
    require(settled_events[-1].get("eventType") == "EVENT_TYPE_WORKFLOW_TASK_COMPLETED",
            "settled phase is not durable")

    signals = [event for event in final_events if event.get("eventType") == "EVENT_TYPE_WORKFLOW_EXECUTION_SIGNALED"]
    require(len(signals) == len(BUSINESS_SIGNALS), "business signal count differs")
    signal_attributes = [
        event_attributes(event, "workflowExecutionSignaledEventAttributes", "business signal")
        for event in signals
    ]
    require([item.get("signalName") for item in signal_attributes] == list(BUSINESS_SIGNALS),
            "business signal order differs")
    for item in signal_attributes:
        require(set(item) == {"signalName", "input", "identity"}, "business signal fields differ")
        require(item["identity"] == SIGNAL_IDENTITY, "business signal identity differs")
        if item["signalName"] == "driver_selected":
            require(
                payload_bytes(item["input"], "driver_selected input") ==
                b'{"delivery_id":"delivery-order-1","driver_id":"driver-1"}',
                "driver assignment signal differs",
            )
        else:
            require(item["input"] == {}, f"{item['signalName']} input differs")

    require(final_events[-1].get("eventType") == "EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED",
            "Workflow did not complete")
    terminal_attributes = event_attributes(
        final_events[-1], "workflowExecutionCompletedEventAttributes", "Workflow completion",
    )
    require(terminal_attributes.get("workflowTaskCompletedEventId") in completed_wft_ids,
            "Workflow completion link differs")
    result = json_payload(terminal_attributes.get("result"), "Workflow result")
    require(result == final_result(), "Workflow result differs")
    final_query = json_value(root, "final-query.json")
    require(final_query == {"queryResult": [result]}, "final query/result mismatch")
    final_describe = json_value(root, "final-describe.json")
    final_info = object_value(final_describe.get("workflowExecutionInfo"), "final info")
    require(
        final_info.get("execution") == {"workflowId": WORKFLOW_ID, "runId": run_id} and
        final_info.get("status") == "WORKFLOW_EXECUTION_STATUS_COMPLETED" and
        final_info.get("historyLength") == str(len(final_events)) and final_info.get("type") == {"name": "FoodOrderPinned"} and
        final_info.get("taskQueue") == TASK_QUEUE and final_info.get("workerDeploymentName") == DEPLOYMENT and
        final_info.get("mostRecentWorkerVersionStamp") == {"buildId": V1_BUILD, "useVersioning": True},
        "final Workflow identity/state differs",
    )
    versioning = object_value(final_info.get("versioningInfo"), "final versioning info")
    require(
        versioning.get("behavior") == "VERSIONING_BEHAVIOR_PINNED" and
        versioning.get("version") == f"{DEPLOYMENT}.{V1_BUILD}" and
        versioning.get("deploymentVersion") == {"buildId": V1_BUILD, "deploymentName": DEPLOYMENT} and
        versioning.get("revisionNumber") == "1" and
        "versionTransition" not in versioning,
        "final execution did not remain pinned to v1",
    )
    require(final_describe.get("pendingActivities") is None and final_describe.get("pendingWorkflowTask") is None,
            "final Workflow still has pending work")
    require(final_describe.get("result") == result, "final describe result differs")
    close_event = object_value(final_describe.get("closeEvent"), "final close event")
    require(
        close_event.get("eventId") == str(len(final_events)) and
        close_event.get("eventType") == "EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED" and
        close_event.get("workflowExecutionCompletedEventAttributes") == {
            "result": [result],
            "workflowTaskCompletedEventId": terminal_attributes["workflowTaskCompletedEventId"],
        },
        "final close event differs",
    )
    points = array_value(object_value(final_info.get("autoResetPoints"), "reset points").get("points"), "reset points")
    require([point.get("buildId") for point in points if isinstance(point, dict)] == [V1_BUILD],
            "final execution used a non-v1 build")
    for name in (
        "signal-preparation-finished.json", "signal-driver-selected.json",
        "signal-driver-at-restaurant.json", "signal-delivery-finished.json",
    ):
        require(read(root, name) == b"", f"{name} command output differs")
    return completion_time, normalize_history(settled, run_id), normalize_history(final, run_id)


def service_map(values: list[Any], label: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for raw in values:
        item = object_value(raw, label + " container")
        labels = object_value(item.get("Config", {}).get("Labels"), label + " labels")
        service = labels.get("com.docker.compose.service")
        require(isinstance(service, str) and service not in result, f"{label} service inventory differs")
        result[service] = item
    return result


def environment_map(item: dict[str, Any], label: str) -> dict[str, str]:
    values = array_value(object_value(item.get("Config"), label + " config").get("Env"), label + " environment")
    result: dict[str, str] = {}
    for raw in values:
        require(isinstance(raw, str) and "=" in raw, f"{label} environment entry differs")
        key, value = raw.split("=", 1)
        require(key not in result, f"{label} contains a duplicate environment variable")
        result[key] = value
    return result


def check_no_v2_events(root: Path, project: str) -> None:
    lines = read(root, "docker-events.jsonl").splitlines()
    require(lines, "Docker event evidence is empty")
    events = [object_value(decode_json(line, "Docker event"), "Docker event") for line in lines]
    since_ns = parse_epoch_ns(root, "docker-events-since-epoch-ns.txt")
    until_text = read(root, "docker-events-until-epoch.txt").decode("ascii").strip()
    require(re.fullmatch(r"[0-9]{10,12}", until_text) is not None, "Docker event end differs")
    until_ns = int(until_text) * 1_000_000_000
    parse_time(read(root, "docker-events-since-at.txt").decode("ascii").strip(), "Docker event start")
    by_service: dict[str, list[dict[str, Any]]] = {}
    forbidden = {"worker-v2", "worker-compatible-v2"}
    for event in events:
        actor = object_value(event.get("Actor"), "Docker event actor")
        attributes = object_value(actor.get("Attributes"), "Docker event attributes")
        require(attributes.get("com.docker.compose.project") == project, "Docker event project differs")
        serialized = json.dumps(event, sort_keys=True).lower()
        require("food-order-v2" not in serialized and "food-order-compatible-v2" not in serialized,
                "a v2 build appeared in Docker events")
        event_ns_raw = event.get("timeNano")
        require(isinstance(event_ns_raw, int) or (isinstance(event_ns_raw, str) and event_ns_raw.isdigit()),
                "Docker event timestamp differs")
        event_ns = int(event_ns_raw)
        require(since_ns <= event_ns <= until_ns,
                "Docker event lies outside the captured lifecycle")
        if event.get("Type") != "container":
            continue
        service = attributes.get("com.docker.compose.service")
        require(isinstance(service, str) and service, "Docker event service is absent")
        require(service not in forbidden and "v2" not in service.lower(), "a v2 service appeared in Docker events")
        by_service.setdefault(service, []).append(event)
    expected = {"temporal", "payment", "completion", "payment-proxy", "worker-v1", "starter"}
    require(expected <= set(by_service), "Docker event lifecycle is incomplete")
    for service in expected:
        actions = [event.get("Action") for event in by_service[service]]
        require(actions.count("create") == 1 and actions.count("start") == 1,
                f"{service} create/start lifecycle differs")
    for service in expected - {"starter"}:
        actions = {event.get("Action") for event in by_service[service]}
        require(not actions.intersection({"die", "destroy", "kill", "stop", "restart"}),
                f"{service} stopped during the measured lifecycle")


def check_poller(root: Path, name: str) -> None:
    value = json_value(root, name)
    pollers = array_value(value.get("pollers"), name + " pollers")
    relevant = [item for item in pollers if isinstance(item, dict) and item.get("worker_version_capabilities", {}).get("use_versioning") is True]
    require(len(relevant) == 1, f"{name} versioned poller count differs")
    item = relevant[0]
    require(
        item.get("identity") == V1_IDENTITY and
        item.get("worker_version_capabilities", {}).get("build_id") == V1_BUILD and
        item.get("deployment_options", {}).get("deployment_name") == DEPLOYMENT and
        item.get("deployment_options", {}).get("build_id") == V1_BUILD,
        f"{name} contains a non-v1 poller",
    )


def check_containers_and_deployment(root: Path, build: dict[str, str]) -> tuple[str, int]:
    for name in ("v1-workflow-pollers.json", "v1-activity-pollers.json", "v1-final-workflow-pollers.json", "v1-final-activity-pollers.json"):
        check_poller(root, name)
    cut_inspect = json_array(root, "v1-cut-inspect.json")
    final_inspect = json_array(root, "v1-final-inspect.json")
    require(len(cut_inspect) == len(final_inspect) == 1, "v1 inspect count differs")
    cut_v1 = object_value(cut_inspect[0], "cut v1")
    final_v1 = object_value(final_inspect[0], "final v1")
    v1_id = cut_v1.get("Id")
    require(isinstance(v1_id, str) and re.fullmatch(r"[0-9a-f]{64}", v1_id) is not None, "v1 container ID differs")
    for item, label in ((cut_v1, "cut v1"), (final_v1, "final v1")):
        labels = object_value(item.get("Config", {}).get("Labels"), label + " labels")
        state = object_value(item.get("State"), label + " state")
        require(
            item.get("Id") == v1_id and item.get("Image") == V1_IMAGE_ID and
            state.get("Running") is True and state.get("Paused") is False and
            state.get("Restarting") is False and state.get("Dead") is False and
            state.get("RestartCount", item.get("RestartCount")) in {None, 0} and
            labels.get("com.docker.compose.service") == "worker-v1" and
            labels.get("io.safe-change.source.sha256") == SOURCE_SHA256 and
            labels.get("io.safe-change.worker.build-id") == V1_BUILD,
            f"{label} provenance/state differs",
        )
    require(
        cut_v1.get("Created") == final_v1.get("Created") and
        cut_v1.get("State", {}).get("StartedAt") == final_v1.get("State", {}).get("StartedAt") and
        cut_v1.get("RestartCount") == final_v1.get("RestartCount") == 0,
        "v1 was restarted or replaced",
    )
    require(read(root, "v2-containers-at-cut.txt") == b"" and read(root, "v2-containers-final.txt") == b"", "v2 container existed")

    cut_services = service_map(json_array(root, "containers-cut.json"), "cut")
    final_services = service_map(json_array(root, "containers-final.json"), "final")
    expected_services = {"temporal", "payment", "completion", "payment-proxy", "worker-v1"}
    require(set(cut_services) == set(final_services) == expected_services, "container service inventory differs")
    projects = {
        item.get("Config", {}).get("Labels", {}).get("com.docker.compose.project")
        for group in (cut_services, final_services) for item in group.values()
    }
    require(len(projects) == 1 and None not in projects, "Compose project identity differs")
    project = str(next(iter(projects)))
    for service in expected_services:
        cut_item = cut_services[service]
        final_item = final_services[service]
        require(
            cut_item.get("Id") == final_item.get("Id") and
            cut_item.get("Image") == final_item.get("Image") and
            cut_item.get("Created") == final_item.get("Created") and
            cut_item.get("State", {}).get("StartedAt") == final_item.get("State", {}).get("StartedAt") and
            cut_item.get("RestartCount") == final_item.get("RestartCount") == 0 and
            cut_item.get("State", {}).get("Running") is True and
            final_item.get("State", {}).get("Running") is True,
            f"{service} was stopped, restarted, or replaced",
        )
    require(cut_services["worker-v1"].get("Id") == final_services["worker-v1"].get("Id") == v1_id, "v1 was replaced")
    require(final_services["payment"].get("Image") == EFFECTS_IMAGE_ID, "payment image differs")
    require(final_services["completion"].get("Image") == EFFECTS_IMAGE_ID, "completion image differs")

    payment = final_services["payment"]
    require(payment.get("Config", {}).get("Cmd") == [
        "-listen=0.0.0.0:8081", "-state=/state/payment.history",
        "-hold-before-commit=false", "-hold-after-commit=false", "-non-idempotent=true",
        "-reference-prefix=temporal-payment",
    ], "payment provider command/fault mode differs")
    completion = final_services["completion"]
    require(completion.get("Config", {}).get("Cmd") == [
        "-listen=0.0.0.0:8081", "-state=/state/completion.history",
        "-non-idempotent=true", "-reference-prefix=temporal-completion",
    ], "completion provider command differs")
    worker = final_services["worker-v1"]
    worker_env = environment_map(worker, "worker-v1")
    require(
        worker.get("Config", {}).get("Image") == V1_IMAGE_ID and
        worker_env.get("TEMPORAL_ADDRESS") == "temporal:7233" and
        worker_env.get("PAYMENT_URL") == f"http://payment-proxy:{TOXIPROXY_PORT}" and
        worker_env.get("COMPLETION_URL") == "http://completion:8081" and
        sum(1 for key in worker_env if key == "PAYMENT_URL") == 1,
        "worker-v1 effect routing differs",
    )
    proxy = final_services["payment-proxy"]
    proxy_image_id = object_value(json_array(root, "toxiproxy-image-inspect.json")[0], "proxy image").get("Id")
    require(
        proxy.get("Image") == proxy_image_id and proxy.get("Config", {}).get("Image") == TOXIPROXY_IMAGE and
        proxy.get("Config", {}).get("Cmd") == ["-host=0.0.0.0"],
        "Toxiproxy container image/command differs",
    )
    host = object_value(proxy.get("HostConfig"), "Toxiproxy host config")
    require(host.get("ReadonlyRootfs") is True and host.get("CapDrop") == ["ALL"], "Toxiproxy container hardening differs")
    require(host.get("PortBindings") in ({}, None), "Toxiproxy control API was published on the host")
    networks = object_value(proxy.get("NetworkSettings", {}).get("Networks"), "Toxiproxy networks")
    require(len(networks) == 1, "Toxiproxy must use only the isolated effects network")
    proxy_network = object_value(next(iter(networks.values())), "Toxiproxy effects network")
    proxy_ip = proxy_network.get("IPAddress")
    require(isinstance(proxy_ip, str) and re.fullmatch(r"(?:[0-9]{1,3}\.){3}[0-9]{1,3}", proxy_ip) is not None,
            "Toxiproxy project-network address differs")
    metadata_endpoint = json_value(root, "run-metadata.json").get("proxy_endpoint")
    require(metadata_endpoint == f"{proxy_ip}:8474", "Toxiproxy control endpoint is not bound to its isolated network")
    check_no_v2_events(root, project)

    deployment_v1 = json_value(root, "deployment-v1-current.json")
    deployment_final = json_value(root, "deployment-final.json")
    for value, label in ((deployment_v1, "initial deployment"), (deployment_final, "final deployment")):
        require(
            value.get("name") == DEPLOYMENT and
            value.get("routingConfig", {}).get("currentVersionDeploymentName") == DEPLOYMENT and
            value.get("routingConfig", {}).get("currentVersionBuildID") == V1_BUILD,
            f"{label} current version differs",
        )
        summaries = array_value(value.get("versionSummaries"), label + " versions")
        require(len(summaries) == 1 and summaries[0].get("BuildID") == V1_BUILD, f"{label} contains a target version")
    for name in ("version-v1.json", "version-v1-final.json"):
        version = json_value(root, name)
        require(version.get("deploymentName") == DEPLOYMENT and version.get("BuildID") == V1_BUILD, f"{name} differs")
    require(read(root, "set-current-v1.json") == b"", "set-current v1 output differs")
    for name in ("deployment-before-current.json", "deployment-v1-current.json", "deployment-final.json",
                 "version-v1.json", "version-v1-final.json"):
        lowered = read(root, name).lower()
        require(b"food-order-v2" not in lowered and b"food-order-compatible-v2" not in lowered,
                f"{name} contains a target build")
    log = read(root, "v1.log").decode("utf-8", errors="strict")
    require(log.count("ActivityType ChargePayment") == 1, "v1 did not run exactly one payment Activity")
    require(log.count("ActivityType PrepareFood") == 1, "v1 did not run exactly one preparation Activity")
    require(log.count("ActivityType ScheduleDelivery") == 1, "v1 did not run exactly one delivery Activity")
    require(log.count("ActivityType CompleteOrder") == 1, "v1 did not run exactly one completion Activity")

    cut_ns = parse_epoch_ns(root, "cut-epoch-ns.txt")
    final_ns = parse_epoch_ns(root, "final-epoch-ns.txt")
    retained_ns = final_ns - cut_ns
    require(retained_ns > 0, "v1 retention duration differs")
    return str(v1_id), retained_ns


def check_observed(root: Path, case: str, run_id: str, v1_id: str, retained_ns: int) -> None:
    cut_payment = (
        {"deliveries": 0, "commits": 0, "paths": {}} if case == "h0" else
        {"deliveries": 1, "commits": 1, "paths": {"/v1/charge": 1}}
    )
    observed = json_value(root, "observed.json")
    require(observed == {
        "schema": 1, "cell": "old-drain", "system": "temporal-pinned", "case": case,
        "workflow_id": WORKFLOW_ID, "run_id": run_id, "decision": "retain-v1",
        "toxic_stream": "upstream" if case == "h0" else "downstream",
        "toxic_deleted": True, "source_build": V1_BUILD, "target_started": False,
        "old_code_required": True, "availability_preserved": True,
        "v1_container_id": v1_id, "v1_running_at_cut": True,
        "v1_running_at_completion": True, "retained_worker_ns": retained_ns,
        "payment_at_cut": cut_payment,
        "payment_final": {"deliveries": 1, "commits": 1, "paths": {"/v1/charge": 1}},
        "completion_final": {"deliveries": 1, "commits": 1, "paths": {"/v1/complete": 1}},
        "final_status": "WORKFLOW_EXECUTION_STATUS_COMPLETED",
        "duplicate_external_effect": False,
    }, "observed summary does not match raw evidence")


def check_evidence(path: Path, expected_case: str | None = None) -> dict[str, Any]:
    root = evidence_root(path)
    verify_checksums(root)
    require(read(root, "exit-status.txt") == b"0\n", "old-drain runner did not exit successfully")
    build = check_inputs(root)
    case, run_id = check_metadata(root, expected_case)
    cut_history, cut_projection, payment_id = check_cut(root, run_id)
    payment, completion = check_provider(root, case)
    require(payment["operation_id"] == payment_id, "History/provider payment identity differs")
    check_toxiproxy(root, case)
    payment_completion_time, settled_history, final_history = check_settlement_and_final(root, run_id)
    v1_id, retained_ns = check_containers_and_deployment(root, build)
    artifact_hashes = {
        name: sha256(read(root, name)).hexdigest()
        for name in sorted(item.name for item in root.iterdir() if item.name not in {"SHA256SUMS", "observed.json"})
    }
    digest = sha256(json.dumps(artifact_hashes, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    stable_names = (
        "build.env", "versions.env", "old-drain.env", "runner.sh", "base-compose.yaml",
        "compose-old-drain.yaml", "source-variant-v1.go", "source-activities.go",
        "source-workflows.go", "source-types.go", "source-starter.go",
    )
    static_inputs = {name: sha256(read(root, name)).hexdigest() for name in stable_names}
    static_digest = sha256(json.dumps(static_inputs, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        "schema": 1, "valid": True, "cell": "old-drain", "system": "temporal-pinned",
        "case": case, "workflow_id": WORKFLOW_ID, "run_id": run_id,
        "payment_operation_id": payment["operation_id"],
        "completion_operation_id": completion["operation_id"],
        "cut_payment_commits": 0 if case == "h0" else 1,
        "final_payment_commits": 1, "final_completion_commits": 1,
        "toxic_stream": "upstream" if case == "h0" else "downstream",
        "toxic_deleted": True, "payment_completed_at": payment_completion_time.isoformat(),
        "source_build": V1_BUILD, "target_started": False, "old_code_required": True,
        "availability_preserved": True, "v1_container_id": v1_id,
        "v1_running_at_cut": True, "v1_running_at_completion": True,
        "retained_worker_ns": retained_ns, "final_status": "WORKFLOW_EXECUTION_STATUS_COMPLETED",
        "duplicate_external_effect": False, "cut_history": cut_history,
        "cut_projection": cut_projection, "settled_history": settled_history, "final_history": final_history,
        "build_data_sha256": sha256(read(root, "build.env")).hexdigest(),
        "static_inputs_sha256": static_digest,
        "evidence_digest": digest,
    }


def check_pair(first_path: Path, second_path: Path) -> dict[str, Any]:
    first = check_evidence(first_path)
    second = check_evidence(second_path)
    by_case = {first["case"]: first, second["case"]: second}
    require(set(by_case) == {"h0", "h1"}, "pair must contain one H0 and one H1")
    h0 = by_case["h0"]
    h1 = by_case["h1"]
    require(h0["run_id"] != h1["run_id"], "H0/H1 reused a Temporal run")
    require(h0["build_data_sha256"] == h1["build_data_sha256"], "H0/H1 builds differ")
    require(h0["static_inputs_sha256"] == h1["static_inputs_sha256"], "H0/H1 harness/source inputs differ")
    require(h0["workflow_id"] == h1["workflow_id"] == WORKFLOW_ID, "H0/H1 workflow identities differ")
    require(h0["payment_operation_id"] == h1["payment_operation_id"], "H0/H1 payment identities differ")
    require(h0["completion_operation_id"] == h1["completion_operation_id"], "H0/H1 completion identities differ")
    require(h0["cut_history"] == h1["cut_history"], "H0/H1 cut History semantics differ")
    require(h0["cut_projection"] == h1["cut_projection"], "H0/H1 pending state semantics differ")
    require(h0["settled_history"] == h1["settled_history"], "H0/H1 settlement semantics differ")
    require(h0["final_history"] == h1["final_history"], "H0/H1 final semantics differ")
    require(h0["cut_payment_commits"] == 0 and h1["cut_payment_commits"] == 1, "H0/H1 external fact split differs")
    require(h0["toxic_stream"] == "upstream" and h1["toxic_stream"] == "downstream", "H0/H1 fault directions differ")
    pair_material = json.dumps(
        {"h0": h0["evidence_digest"], "h1": h1["evidence_digest"]},
        sort_keys=True, separators=(",", ":"),
    ).encode()
    for value in (h0, h1):
        value.pop("cut_history")
        value.pop("cut_projection")
        value.pop("settled_history")
        value.pop("final_history")
    return {
        "schema": 1, "valid": True, "cell": "old-drain", "system": "temporal-pinned",
        "workflow_id": WORKFLOW_ID, "same_temporal_cut": True,
        "different_external_commit_fact": True, "decision_h0": "retain-v1",
        "decision_h1": "retain-v1", "old_code_required": True,
        "availability_preserved": True, "target_started": False,
        "matched_payment_identity": h0["payment_operation_id"],
        "matched_completion_identity": h0["completion_operation_id"],
        "h0": h0, "h1": h1, "pair_digest": sha256(pair_material).hexdigest(),
    }


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--evidence", required=True, type=Path, help="old-drain case or results directory")
    value.add_argument("--case", choices=("h0", "h1"), help="expected case")
    value.add_argument("--peer", type=Path, help="paired H0/H1 evidence")
    return value


def main() -> int:
    args = parser().parse_args()
    try:
        result = check_pair(args.evidence, args.peer) if args.peer else check_evidence(args.evidence, args.case)
    except (EvidenceError, OSError, subprocess.SubprocessError) as error:
        print(f"check-old-drain: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
