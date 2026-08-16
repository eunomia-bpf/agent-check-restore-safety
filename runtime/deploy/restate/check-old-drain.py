#!/usr/bin/env python3
"""Validate native Restate's conservative old-code-retention control.

The runner's ``observed.json`` is deliberately ignored.  This checker derives
the verdict from official Restate queries, immutable build inputs, container
inspection, the append-only provider record, and the exact runner hash.  With
``--peer`` it additionally proves that H0 and H1 expose the same Restate state
while differing only in the provider's durable commit fact.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import re
import sys
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
COMPAT_PATH = SCRIPT_DIR / "check-compatible.py"
SPEC = importlib.util.spec_from_file_location("restate_compatible_check", COMPAT_PATH)
assert SPEC is not None and SPEC.loader is not None
COMPAT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COMPAT)

RUNNER_PATH = SCRIPT_DIR / "run-old-drain-case.sh"
VERSIONS_PATH = SCRIPT_DIR / "versions.env"
IMAGES_PATH = SCRIPT_DIR / "images.env"
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
CONTAINER_ID = re.compile(r"[0-9a-f]{64}\Z")
UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z"
)


class EvidenceError(ValueError):
    """The old-drain evidence is absent, malformed, or contradictory."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceError(message)


def root_for(path: Path) -> Path:
    try:
        return COMPAT.evidence_root(path)
    except COMPAT.EvidenceError as error:
        raise EvidenceError(str(error)) from error


def read(root: Path, name: str, *, maximum: int = 64 << 20) -> bytes:
    try:
        return COMPAT.read(root, name, maximum=maximum)
    except COMPAT.EvidenceError as error:
        raise EvidenceError(str(error)) from error


def json_value(root: Path, name: str) -> Any:
    try:
        return COMPAT.json_value(root, name)
    except COMPAT.EvidenceError as error:
        raise EvidenceError(str(error)) from error


def object_value(value: Any, label: str) -> dict[str, Any]:
    require(isinstance(value, dict), f"{label} must be an object")
    return value


def list_value(value: Any, label: str) -> list[Any]:
    require(isinstance(value, list), f"{label} must be an array")
    return value


def exact_fields(value: dict[str, Any], fields: set[str], label: str) -> None:
    require(set(value) == fields, f"{label} fields changed")


def one_row(value: Any, label: str) -> dict[str, Any]:
    document = object_value(value, label)
    exact_fields(document, {"rows"}, label)
    rows = list_value(document["rows"], label + " rows")
    require(len(rows) == 1 and isinstance(rows[0], dict), f"{label} must contain one row")
    return rows[0]


def timestamp(value: Any, label: str) -> datetime:
    try:
        return COMPAT.timestamp(value, label)
    except COMPAT.EvidenceError as error:
        raise EvidenceError(str(error)) from error


def local_bytes(path: Path, label: str) -> bytes:
    try:
        info = path.lstat()
    except FileNotFoundError as error:
        raise EvidenceError(f"current {label} is absent") from error
    require(path.is_file() and not path.is_symlink(), f"current {label} is not a regular file")
    data = path.read_bytes()
    require(len(data) == info.st_size, f"current {label} changed while read")
    return data


def parse_env(data: bytes, label: str) -> dict[str, str]:
    try:
        return COMPAT.parse_frozen_env(data, label)
    except COMPAT.EvidenceError as error:
        raise EvidenceError(str(error)) from error


def validate_inputs(root: Path) -> tuple[dict[str, str], dict[str, str], dict[str, str], str]:
    versions_bytes = read(root, "versions.env")
    images_bytes = read(root, "images.env")
    require(versions_bytes == local_bytes(VERSIONS_PATH, "versions.env"), "versions.env differs from the current frozen harness")
    require(images_bytes == local_bytes(IMAGES_PATH, "images.env"), "images.env differs from the current frozen harness")
    versions = parse_env(versions_bytes, "versions.env")
    images = parse_env(images_bytes, "images.env")
    require(
        versions == {
            "RESTATE_EXAMPLES_TAG": "v1.7.7",
            "RESTATE_EXAMPLES_COMMIT": COMPAT.UPSTREAM_COMMIT,
            "RESTATE_SERVER_IMAGE": COMPAT.RESTATE_IMAGE,
            "RESTATE_CLI_IMAGE": COMPAT.RESTATE_CLI_IMAGE,
            "NODE_IMAGE": "docker.io/library/node:22-alpine@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32",
        },
        "versions.env does not pin the approved official Restate inputs",
    )
    require(
        images == {
            "KAFKA_IMAGE": "docker.io/confluentinc/cp-kafka:7.5.0@sha256:fbbb6fa11b258a88b83f54d4f0bddfcffbf2279f99d66a843486e3da7bdfbf41",
            "JAEGER_IMAGE": "docker.io/jaegertracing/all-in-one:1.47@sha256:ac85f812596ffb596ddcdbfe7c287eb44f781706e4232741bf9f81ff23aa1da9",
            "WEBUI_NODE_IMAGE": "docker.io/library/node:22-alpine@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32",
            "GO_BUILD_IMAGE": "docker.io/library/golang:1.25.13-alpine@sha256:844b27705f54e73773e0f9bc3c780633b9d7f4b4831bf35cdad02a81a4c80bd0",
            "ALPINE_IMAGE": "docker.io/library/alpine:3.22.2@sha256:4b7ce07002c69e8f3d704a9c5d6fd3053be500b7f1c69fc0d80990c2ad8dd412",
            "RESTATE_EXAMPLES_ARCHIVE_SHA256": COMPAT.FROZEN_BUILD_HASHES["UPSTREAM_ARCHIVE_SHA256"],
        },
        "images.env differs from the frozen external-image inputs",
    )
    try:
        build = COMPAT.parse_build_env(read(root, "build.env"))
    except COMPAT.EvidenceError as error:
        raise EvidenceError(str(error)) from error
    require(
        build["UPSTREAM_ARCHIVE_SHA256"] == images["RESTATE_EXAMPLES_ARCHIVE_SHA256"],
        "build and image inputs disagree on the upstream archive",
    )
    runner_hash = sha256(local_bytes(RUNNER_PATH, "old-drain runner")).hexdigest()
    checksum = read(root, "runner.sha256").decode("utf-8", errors="strict")
    match = re.fullmatch(r"([0-9a-f]{64})  (.+/run-old-drain-case\.sh)\n", checksum)
    require(match is not None and match.group(1) == runner_hash, "runner.sha256 does not bind the current old-drain runner")
    return versions, images, build, runner_hash


def validate_metadata(
    root: Path,
    expected_case: str | None,
    versions: dict[str, str],
    build: dict[str, str],
    runner_hash: str,
) -> tuple[str, str, int, int]:
    value = object_value(json_value(root, "run-metadata.json"), "run metadata")
    exact_fields(value, {
        "schema", "recorded_at", "cell", "system", "case", "state_dir", "order_id",
        "observation_seconds", "terminal_seconds", "source_image", "restate_cli_image", "restate_server_image",
        "runner_sha256", "build_env", "skip_build", "effective_invocation",
    }, "run metadata")
    case = value.get("case")
    require(case in {"h0", "h1"}, "run metadata case is invalid")
    require(expected_case is None or case == expected_case, "evidence case differs from requested case")
    order_id = value.get("order_id")
    observation = value.get("observation_seconds")
    terminal = value.get("terminal_seconds")
    require(
        value.get("schema") == 1 and value.get("cell") == "old-drain"
        and value.get("system") == "native-restate"
        and isinstance(value.get("state_dir"), str) and value["state_dir"]
        and isinstance(order_id, str) and COMPAT.ORDER_ID.fullmatch(order_id) is not None
        and type(observation) is int and 5 <= observation <= 120
        and type(terminal) is int and 20 <= terminal <= 300
        and value.get("source_image") == build["NATIVE_ORDER_V1_IMAGE"]
        and value.get("restate_cli_image") == versions["RESTATE_CLI_IMAGE"]
        and value.get("restate_server_image") == versions["RESTATE_SERVER_IMAGE"]
        and value.get("runner_sha256") == runner_hash
        and isinstance(value.get("build_env"), str) and value["build_env"]
        and type(value.get("skip_build")) is bool,
        "run metadata does not describe the frozen old-drain invocation",
    )
    timestamp(value.get("recorded_at"), "run metadata recording time")
    effective = object_value(value.get("effective_invocation"), "effective invocation")
    exact_fields(effective, {
        "OLD_DRAIN_CASE", "OLD_DRAIN_STATE_DIR", "ORDER_ID", "OLD_DRAIN_OBSERVATION_SECONDS",
        "OLD_DRAIN_TERMINAL_SECONDS", "SKIP_BUILD", "HARNESS_BUILD_ENV", "script",
    }, "effective invocation")
    require(
        effective == {
            "OLD_DRAIN_CASE": case,
            "OLD_DRAIN_STATE_DIR": value["state_dir"],
            "ORDER_ID": order_id,
            "OLD_DRAIN_OBSERVATION_SECONDS": observation,
            "OLD_DRAIN_TERMINAL_SECONDS": terminal,
            "SKIP_BUILD": 1 if value["skip_build"] else 0,
            "HARNESS_BUILD_ENV": value["build_env"],
            "script": "runtime/deploy/restate/run-old-drain-case.sh",
        },
        "effective invocation differs from the recorded old-drain parameters",
    )
    return str(case), str(order_id), int(observation), int(terminal)


def validate_order(root: Path, order_id: str) -> bytes:
    data = read(root, "order.json")
    order = object_value(json_value(root, "order.json"), "order")
    require(order == {
        "id": order_id,
        "restaurantId": "restaurant-01",
        "products": [{"productId": "pizza-01", "description": "Pizza", "quantity": 1}],
        "totalCost": 42,
        "deliveryDelay": 0,
    }, "order workload differs from the frozen old-drain workload")
    checksum = read(root, "order.sha256").decode("utf-8", errors="strict")
    match = re.fullmatch(r"([0-9a-f]{64})  (.+/order\.json)\n", checksum)
    require(match is not None and match.group(1) == sha256(data).hexdigest(), "order.sha256 does not bind order.json")
    return data


def deployment_services(value: Any, label: str) -> set[str]:
    rows = list_value(value, label)
    names: set[str] = set()
    for item in rows:
        row = object_value(item, label + " item")
        name = row.get("name")
        require(isinstance(name, str) and name and name not in names, f"{label} contains an invalid service")
        names.add(name)
    return names


def validate_deployment(root: Path) -> tuple[str, datetime]:
    initial = object_value(json_value(root, "deployment-v1.json"), "deployment response")
    deployment_id = initial.get("id")
    require(
        isinstance(deployment_id, str) and COMPAT.DEPLOYMENT_ID.fullmatch(deployment_id) is not None
        and initial.get("min_protocol_version") == 5
        and initial.get("max_protocol_version") == 7
        and initial.get("sdk_version") == "restate-sdk-typescript/1.16.6",
        "source deployment response is malformed",
    )
    expected_services = {
        "driver-delivery-matcher", "order-workflow", "order-status", "driver-mobile-app",
        "delivery-manager", "driver-digital-twin",
    }
    services = list_value(initial.get("services"), "source deployment services")
    require(deployment_services(services, "source deployment services") == expected_services, "source deployment service set differs")
    for service in services:
        require(service.get("deployment_id") == deployment_id and service.get("revision") == 1, "source service is not bound to revision 1")
    workflow = next(item for item in services if item.get("name") == "order-workflow")
    require(workflow.get("ty") == "Workflow", "order-workflow is not registered as a Workflow")
    handlers = list_value(workflow.get("handlers"), "order-workflow handlers")
    run_handlers = [item for item in handlers if isinstance(item, dict) and item.get("name") == "run"]
    require(len(run_handlers) == 1 and run_handlers[0].get("ty") == "Workflow", "source deployment omitted the workflow run handler")

    require(read(root, "deployments-at-cut.json") == read(root, "final-deployments.json"), "deployment set changed during old-code retention")
    listing = object_value(json_value(root, "final-deployments.json"), "final deployments")
    exact_fields(listing, {"deployments"}, "final deployments")
    rows = list_value(listing["deployments"], "final deployments")
    require(len(rows) == 1 and isinstance(rows[0], dict), "old-drain did not retain exactly one deployment")
    source = rows[0]
    exact_fields(source, {
        "id", "uri", "protocol_type", "http_version", "metadata", "created_at",
        "min_protocol_version", "max_protocol_version", "sdk_version", "services",
    }, "source deployment listing")
    require(
        source.get("id") == deployment_id
        and source.get("uri") == "http://order-v1:9080/"
        and source.get("protocol_type") == "BidiStream"
        and source.get("http_version") == "HTTP/2.0"
        and source.get("metadata") == {
            "method": "old-drain", "upstream_commit": COMPAT.UPSTREAM_COMMIT, "variant": "native-v1",
        }
        and source.get("min_protocol_version") == 5
        and source.get("max_protocol_version") == 7
        and source.get("sdk_version") == "restate-sdk-typescript/1.16.6"
        and deployment_services(source.get("services"), "listed source services") == expected_services,
        "source deployment listing differs from the frozen native-v1 deployment",
    )
    return str(deployment_id), timestamp(source.get("created_at"), "source deployment creation time")


def validate_status(
    root: Path, order_id: str, deployment_id: str, deployment_created: datetime
) -> tuple[str, datetime, datetime, datetime, str, int]:
    submit = object_value(json_value(root, "source-submit.json"), "source submit")
    exact_fields(submit, {"invocationId", "status"}, "source submit")
    invocation_id = submit.get("invocationId")
    require(
        submit.get("status") == "Accepted" and isinstance(invocation_id, str)
        and COMPAT.INVOCATION_ID.fullmatch(invocation_id) is not None,
        "source workflow was not accepted",
    )
    before = one_row(json_value(root, "status-before-pause.json"), "status before pause")
    exact_fields(before, {
        "id", "target", "status", "pinned_deployment_id", "pinned_service_protocol_version",
        "last_attempt_deployment_id", "retry_count", "journal_size", "created_at", "modified_at",
    }, "status before pause row")
    expected_target = f"order-workflow/{order_id}/run"
    require(
        before.get("id") == invocation_id and before.get("target") == expected_target
        and before.get("status") == "running"
        and before.get("pinned_deployment_id") == deployment_id
        and before.get("last_attempt_deployment_id") == deployment_id
        and before.get("pinned_service_protocol_version") == 6
        and before.get("retry_count") == 1 and before.get("journal_size") == 3,
        "workflow did not reach the running unknown-payment cut",
    )
    created = timestamp(before.get("created_at"), "invocation creation time")
    before_modified = timestamp(before.get("modified_at"), "pre-pause modification time")
    require(deployment_created <= created <= before_modified, "deployment/invocation chronology is inconsistent")

    cut_bytes = read(root, "cut-status.json")
    require(
        read(root, "paused-poll.json") == cut_bytes
        and read(root, "paused-status-after-window.json") == cut_bytes,
        "paused invocation changed before fault release",
    )
    cut = one_row(json_value(root, "cut-status.json"), "paused cut status")
    exact_fields(cut, {
        "id", "target", "status", "pinned_deployment_id", "pinned_service_protocol_version",
        "journal_size", "created_at", "modified_at",
    }, "paused cut status row")
    require(
        cut.get("id") == invocation_id and cut.get("target") == expected_target
        and cut.get("status") == "paused" and cut.get("pinned_deployment_id") == deployment_id
        and cut.get("pinned_service_protocol_version") == 6 and cut.get("journal_size") == 3
        and cut.get("created_at") == before.get("created_at"),
        "old-drain did not retain the same invocation paused on v1",
    )
    cut_modified = timestamp(cut.get("modified_at"), "pause modification time")
    require(cut_modified > before_modified, "pause did not advance invocation state")

    final_bytes = read(root, "final-status.json")
    require(final_bytes == read(root, "final-invocations.json"), "final query did not isolate the source invocation")
    final = one_row(json_value(root, "final-status.json"), "final source status")
    required_fields = {
        "id", "target", "status", "pinned_deployment_id", "pinned_service_protocol_version",
        "journal_size", "created_at", "modified_at",
    }
    optional_fields = {"last_attempt_deployment_id", "retry_count", "next_retry_at"}
    require(
        required_fields <= set(final) <= required_fields | optional_fields,
        "final source status fields changed",
    )
    final_status = final.get("status")
    journal_size = final.get("journal_size")
    require(
        final.get("id") == invocation_id and final.get("target") == expected_target
        and final.get("created_at") == before.get("created_at")
        and final_status in {"running", "completed"}
        and final.get("pinned_deployment_id") == deployment_id
        and final.get("pinned_service_protocol_version") == 6
        and type(journal_size) is int and journal_size >= 3,
        "official resume did not continue the same source invocation on v1",
    )
    final_modified = timestamp(final.get("modified_at"), "final invocation modification time")
    require(final_modified > cut_modified, "resume did not advance the source invocation")
    return str(invocation_id), created, cut_modified, final_modified, str(final_status), int(journal_size)


def validate_journal_and_state(
    root: Path, order_id: str, order_bytes: bytes, final_status: str, final_journal_size: int
) -> tuple[str, str]:
    journal_bytes = read(root, "cut-journal.json")
    require(
        journal_bytes == read(root, "paused-journal-after-window.json"),
        "journal changed while the invocation was paused",
    )
    try:
        rows = COMPAT.validate_journal_document(json_value(root, "cut-journal.json"), "old-drain journal")
    except COMPAT.EvidenceError as error:
        raise EvidenceError(str(error)) from error
    require(
        COMPAT.row_shape(rows) == [
            (0, "Command: Input", ""),
            (1, "Command: SetState", ""),
            (2, "Command: Run", "payment"),
        ],
        "old-drain journal is not the unresolved payment cut",
    )
    require(all(row.get("version") == 2 and row.get("completed") is False for row in rows), "old-drain journal flags changed")
    require(order_bytes in bytes.fromhex(rows[0]["raw"]), "journal input does not contain the submitted order bytes")
    try:
        input_lite = COMPAT.lite(rows[0], "input command")
        state_lite = COMPAT.lite(rows[1], "state command")
        payment_lite = COMPAT.lite(rows[2], "payment command")
    except COMPAT.EvidenceError as error:
        raise EvidenceError(str(error)) from error
    require(input_lite == {"Command": {"Input": {}}}, "journal input command differs")
    require(state_lite == {"Command": {"SetState": {"key": "status"}}}, "journal initial state command differs")
    require(
        payment_lite == {"Command": {"Run": {"completion_id": 1, "name": "payment"}}}
        and rows[2].get("raw") == "580162077061796d656e74" and rows[2].get("raw_length") == 11,
        "journal payment command identity differs",
    )

    state_bytes = read(root, "cut-workflow-state.json")
    require(
        state_bytes == read(root, "paused-workflow-state-after-window.json"),
        "workflow state changed while the invocation was paused",
    )
    state = one_row(json_value(root, "cut-workflow-state.json"), "old-drain workflow state")
    exact_fields(state, {"service_name", "service_key", "key", "value", "value_utf8", "value_length"}, "old-drain workflow state row")
    require(state == {
        "service_name": "order-workflow", "service_key": order_id, "key": "status",
        "value": "224352454154454422", "value_utf8": '"CREATED"', "value_length": 9,
    }, "old-drain business state is not the exact CREATED cut")
    final_rows = COMPAT.validate_journal_document(json_value(root, "final-journal.json"), "final old-drain journal")
    require(len(final_rows) == final_journal_size, "final journal size differs from official invocation status")
    require(final_rows[:3] == rows, "resume rewrote the equal H0/H1 cut prefix")
    expected_final = [
        (0, "Command: Input", ""), (1, "Command: SetState", ""),
        (2, "Command: Run", "payment"), (3, "Notification: Run", ""),
        (4, "Command: SetState", ""), (5, "Command: Sleep", ""),
        (6, "Notification: Sleep", ""), (7, "Command: Run", ""),
        (8, "Notification: Run", ""), (9, "Command: SetState", ""),
        (10, "Command: GetPromise", ""), (11, "Notification: GetPromise", ""),
        (12, "Command: SetState", ""), (13, "Command: OneWayCall", ""),
        (14, "Notification: CallInvocationId", ""), (15, "Command: GetPromise", ""),
        (16, "Notification: GetPromise", ""), (17, "Command: SetState", ""),
        (18, "Command: GetPromise", ""), (19, "Notification: GetPromise", ""),
        (20, "Command: SetState", ""), (21, "Command: GetPromise", ""),
        (22, "Notification: GetPromise", ""), (23, "Command: Run", "completion"),
        (24, "Notification: Run", ""), (25, "Command: SetState", ""),
        (26, "Command: Output", ""),
    ]
    final_shape = COMPAT.row_shape(final_rows)
    require(
        final_shape == expected_final[:len(final_shape)],
        "retained v1 journal is not a prefix of the official workflow path",
    )
    if len(final_rows) >= 4:
        payment_notice = object_value(COMPAT.lite(final_rows[3], "payment notification").get("Notification"), "payment notification")
        require(
            payment_notice.get("ty") == {"Completion": "Run"}
            and payment_notice.get("id") == {"CompletionId": 1}
            and payment_notice.get("result") == "Success",
            "retained v1 did not settle the retried direct payment closure successfully",
        )

    final_state = one_row(json_value(root, "final-workflow-state.json"), "final workflow state")
    exact_fields(final_state, {"service_name", "service_key", "key", "value", "value_utf8", "value_length"}, "final workflow state row")
    require(
        final_state.get("service_name") == "order-workflow"
        and final_state.get("service_key") == order_id and final_state.get("key") == "status"
        and isinstance(final_state.get("value_utf8"), str),
        "final business state is not the source workflow state",
    )
    business_status = str(final_state["value_utf8"]).strip('"')
    if final_status == "completed":
        require(final_shape == expected_final, "completed v1 invocation omitted an official workflow stage")
        completion_notice = object_value(COMPAT.lite(final_rows[24], "completion notification").get("Notification"), "completion notification")
        output = object_value(object_value(COMPAT.lite(final_rows[26], "workflow output").get("Command"), "output command").get("Output"), "workflow output")
        require(
            completion_notice.get("ty") == {"Completion": "Run"}
            and completion_notice.get("id") == {"CompletionId": 9}
            and completion_notice.get("result") == "Success"
            and output == {"result": "Success"}
            and business_status == "DELIVERED",
            "completed source workflow did not reach the DELIVERED terminal state",
        )
    return sha256(journal_bytes + b"\0" + state_bytes).hexdigest(), business_status


def stats(root: Path, name: str, expected: dict[str, Any] | None = None) -> dict[str, Any]:
    value = object_value(json_value(root, name), name)
    exact_fields(value, {"deliveries", "commits", "paths"}, name)
    require(
        type(value.get("deliveries")) is int and value["deliveries"] >= 0
        and type(value.get("commits")) is int and value["commits"] >= 0
        and isinstance(value.get("paths"), dict)
        and all(isinstance(key, str) and type(count) is int and count >= 0 for key, count in value["paths"].items()),
        f"{name} provider counters are malformed",
    )
    if expected is not None:
        require(value == expected, f"{name} differs from the expected provider counts")
    return value


def json_lines(data: bytes, label: str) -> list[dict[str, Any]]:
    if not data:
        return []
    require(data.endswith(b"\n"), f"{label} is not newline terminated")
    output: list[dict[str, Any]] = []
    for number, line in enumerate(data.splitlines(), 1):
        try:
            item = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise EvidenceError(f"{label} line {number} is not JSON") from error
        output.append(object_value(item, f"{label} line {number}"))
    return output


def operation_id(token: str) -> str:
    digest = sha256(b"operation-id-v1\0" + b"restate-order-workflow\0" + token.encode()).hexdigest()
    return "op-" + digest


def payment_record(payment_id: str, request_hash: str, number: int) -> dict[str, str]:
    result_hash = sha256(b"charged\0" + payment_id.encode() + b"\0" + str(number).encode()).hexdigest()
    return {
        "operation_id": payment_id,
        "request_hash": request_hash,
        "result_hash": result_hash,
        "remote_reference": f"payment/{payment_id}/commit-{number}",
        "path": "/v1/charge",
    }


def validate_provider(
    root: Path, case: str, order_id: str, final_status: str, business_status: str
) -> tuple[str, str, str, int, int, int, int, bool]:
    cut_commits = 0 if case == "h0" else 1
    expected_payment = {"deliveries": 1, "commits": cut_commits, "paths": {"/v1/charge": 1}}
    payment_bytes = read(root, "payment-before-pause.json")
    require(
        payment_bytes == read(root, "payment-at-cut.json")
        and payment_bytes == read(root, "payment-after-cut-window.json"),
        "payment counters changed before the symmetric fault release",
    )
    stats(root, "payment-before-pause.json", expected_payment)
    stats(root, "payment-at-cut.json", expected_payment)
    stats(root, "payment-after-cut-window.json", expected_payment)
    completion_bytes = read(root, "completion-at-cut.json")
    require(
        completion_bytes == read(root, "completion-after-cut-window.json"),
        "completion counters changed while the source invocation was paused",
    )
    stats(root, "completion-at-cut.json", {"deliveries": 0, "commits": 0, "paths": {}})
    stats(root, "completion-after-cut-window.json", {"deliveries": 0, "commits": 0, "paths": {}})

    payment_history = read(root, "payment-at-cut.history")
    require(
        payment_history == read(root, "payment-after-cut-window.history")
        and payment_history == read(root, "payment-after-recovery.history"),
        "durable payment fact changed before the retained v1 closure resumed",
    )
    completion_history = read(root, "completion-at-cut.history")
    require(
        completion_history == read(root, "completion-after-cut-window.history") == b"",
        "completion durable history is not empty at the equal workflow cut",
    )

    log = read(root, "source-before-crash.log").decode("utf-8", errors="strict")
    matches = re.findall(
        rf"^\[{re.escape(order_id)}\] Executing payment with token ({UUID.pattern[:-2]}) for \$42$",
        log,
        flags=re.MULTILINE,
    )
    require(len(matches) == 1 and UUID.fullmatch(matches[0]) is not None, "source log does not bind exactly one stable payment token")
    require("Recording terminal delivery" not in log, "completion began before the old-drain cut")
    token = matches[0]
    expected_id = operation_id(token)
    records = json_lines(payment_history, "payment history")
    require(len(records) == cut_commits, "provider durable record count differs from the selected cut history")
    body = json.dumps({"order_id": order_id, "amount": 42}, separators=(",", ":")).encode()
    request_hash = sha256(b"POST\0/v1/charge\0" + body).hexdigest()
    if case == "h1":
        require(records[0] == payment_record(expected_id, request_hash, 1), "H1 durable payment record differs from the exact external work")

    stats(
        root,
        "payment-after-recovery.json",
        {"deliveries": 0, "commits": cut_commits, "paths": {}},
    )
    recovered = stats(root, "final-payment-stats.json")
    require(
        recovered["deliveries"] >= 1
        and recovered["paths"] == {"/v1/charge": recovered["deliveries"]}
        and recovered["commits"] == cut_commits + recovered["deliveries"],
        "recovered provider counters do not describe direct non-idempotent v1 retries",
    )
    final_payment_records = json_lines(read(root, "payment.history"), "final payment history")
    expected_payment_records = [
        payment_record(expected_id, request_hash, number)
        for number in range(1, recovered["commits"] + 1)
    ]
    require(
        final_payment_records == expected_payment_records,
        "final payment history does not contain the exact sequential direct-provider work",
    )

    completion = stats(root, "final-completion-stats.json")
    require(
        completion["commits"] in {0, 1}
        and completion["deliveries"] >= completion["commits"]
        and completion["paths"] == (
            {} if completion["deliveries"] == 0 else {"/v1/complete": completion["deliveries"]}
        ),
        "completion counters do not describe the retained v1 completion closure",
    )
    completion_id = operation_id(f"order/{order_id}/completion")
    completion_body = json.dumps({"order_id": order_id, "status": "DELIVERED"}, separators=(",", ":")).encode()
    completion_request_hash = sha256(b"POST\0/v1/complete\0" + completion_body).hexdigest()
    completion_result_hash = sha256(b"charged\0" + completion_id.encode()).hexdigest()
    expected_completion = {
        "operation_id": completion_id,
        "request_hash": completion_request_hash,
        "result_hash": completion_result_hash,
        "remote_reference": f"completion/{completion_id}",
        "path": "/v1/complete",
    }
    final_completion_records = json_lines(read(root, "completion.history"), "final completion history")
    require(
        final_completion_records == ([] if completion["commits"] == 0 else [expected_completion]),
        "completion durable history differs from the retained v1 closure",
    )

    final_log = read(root, "final-source-retained.log").decode("utf-8", errors="strict")
    final_tokens = re.findall(
        rf"^\[{re.escape(order_id)}\] Executing payment with token ({UUID.pattern[:-2]}) for \$42$",
        final_log,
        flags=re.MULTILINE,
    )
    require(
        len(final_tokens) >= 2 and all(item == token for item in final_tokens),
        "retained v1 did not re-enter the same direct-provider payment closure",
    )
    completion_logs = len(re.findall(rf"^\[{re.escape(order_id)}\] Recording terminal delivery$", final_log, flags=re.MULTILINE))
    require(
        completion_logs >= completion["deliveries"],
        "completion deliveries are not attributable to the retained v1 worker",
    )
    requirement_satisfied = (
        final_status == "completed" and business_status == "DELIVERED"
        and recovered["commits"] == 1 and completion["commits"] == 1
    )
    return (
        token, expected_id, completion_id,
        1 + int(recovered["deliveries"]), int(recovered["commits"]),
        int(completion["deliveries"]), int(completion["commits"]),
        requirement_satisfied,
    )


def inspect_one(root: Path, name: str) -> dict[str, Any]:
    values = list_value(json_value(root, name), name)
    require(len(values) == 1 and isinstance(values[0], dict), f"{name} must contain one inspected container")
    return values[0]


def container_service(value: dict[str, Any], label: str) -> str:
    config = object_value(value.get("Config"), label + " Config")
    labels = object_value(config.get("Labels"), label + " labels")
    service = labels.get("com.docker.compose.service")
    require(isinstance(service, str) and service, f"{label} has no Compose service identity")
    return service


def state_mount(value: dict[str, Any], label: str) -> tuple[str, str]:
    mounts = list_value(value.get("Mounts"), label + " mounts")
    selected = [item for item in mounts if isinstance(item, dict) and item.get("Destination") == "/state"]
    require(len(selected) == 1, f"{label} does not have exactly one durable /state mount")
    name = selected[0].get("Name")
    source = selected[0].get("Source")
    require(isinstance(name, str) and name and isinstance(source, str) and source, f"{label} state mount identity is absent")
    return name, source


def validate_source_container(root: Path, build: dict[str, str], case: str) -> tuple[str, str]:
    before = inspect_one(root, "source-before-crash.json")
    retained = inspect_one(root, "source-retained.json")
    final = inspect_one(root, "final-source-retained.json")
    source_image = build["NATIVE_ORDER_V1_IMAGE"]
    before_id = before.get("Id")
    retained_id = retained.get("Id")
    require(
        isinstance(before_id, str) and CONTAINER_ID.fullmatch(before_id) is not None
        and isinstance(retained_id, str) and CONTAINER_ID.fullmatch(retained_id) is not None
        and before_id == retained_id and final.get("Id") == retained_id,
        "Compose did not restart and retain the same immutable source container",
    )
    require(read(root, "source-crash.txt") == (before_id + "\n").encode(), "source crash artifact does not identify the killed worker")
    for value, label in ((before, "source before crash"), (retained, "retained source"), (final, "final retained source")):
        state = object_value(value.get("State"), label + " state")
        require(
            value.get("Image") == source_image and container_service(value, label) == "order-v1"
            and state.get("Running") is True and state.get("Status") == "running",
            f"{label} is not the running immutable native-v1 image",
        )
        labels = object_value(object_value(value.get("Config"), label + " Config").get("Labels"), label + " labels")
        require(
            labels.get("org.opencontainers.image.revision") == COMPAT.UPSTREAM_COMMIT
            and labels.get("org.opencontainers.image.version") == "native-v1"
            and labels.get("com.docker.compose.image") == source_image,
            f"{label} provenance labels differ",
        )
    require(
        retained.get("Created") == before.get("Created")
        and timestamp(object_value(retained.get("State"), "retained source state").get("StartedAt"), "retained worker start time")
        > timestamp(object_value(before.get("State"), "source state before crash").get("StartedAt"), "source worker initial start time"),
        "source container was not restarted after the injected kill",
    )
    require(
        object_value(final.get("State"), "final source state").get("StartedAt")
        == object_value(retained.get("State"), "retained source state").get("StartedAt"),
        "retained v1 worker restarted again instead of executing the resumed invocation",
    )

    held_payment = inspect_one(root, "payment-held-container.json")
    recovered_payment = inspect_one(root, "payment-recovered-container.json")
    held_id = held_payment.get("Id")
    recovered_id = recovered_payment.get("Id")
    require(
        isinstance(held_id, str) and CONTAINER_ID.fullmatch(held_id) is not None
        and isinstance(recovered_id, str) and CONTAINER_ID.fullmatch(recovered_id) is not None
        and held_id != recovered_id,
        "fault release did not recreate exactly the external payment process",
    )
    for value, label in ((held_payment, "held payment provider"), (recovered_payment, "recovered payment provider")):
        require(
            value.get("Image") == build["SAFE_CHANGE_RUNTIME_IMAGE"]
            and container_service(value, label) == "payment",
            f"{label} is not the frozen direct provider",
        )
    held_command = list_value(object_value(held_payment.get("Config"), "held payment Config").get("Cmd"), "held payment command")
    recovered_command = list_value(object_value(recovered_payment.get("Config"), "recovered payment Config").get("Cmd"), "recovered payment command")
    expected_held = (
        "-hold-before-commit=true" if case == "h0" else "-hold-after-commit=true"
    )
    expected_other = (
        "-hold-after-commit=false" if case == "h0" else "-hold-before-commit=false"
    )
    require(
        expected_held in held_command and expected_other in held_command
        and "-non-idempotent=true" in held_command,
        "held provider does not encode the selected deterministic cut",
    )
    require(
        "-hold-before-commit=false" in recovered_command
        and "-hold-after-commit=false" in recovered_command
        and "-non-idempotent=true" in recovered_command,
        "fault-release provider changed more than the two symmetric hold flags",
    )
    held_without_flags = [item for item in held_command if not item.startswith("-hold-before-commit=") and not item.startswith("-hold-after-commit=")]
    recovered_without_flags = [item for item in recovered_command if not item.startswith("-hold-before-commit=") and not item.startswith("-hold-after-commit=")]
    require(held_without_flags == recovered_without_flags, "fault release changed the external provider command")
    require(
        state_mount(held_payment, "held payment provider") == state_mount(recovered_payment, "recovered payment provider"),
        "fault release did not preserve the durable payment volume",
    )

    containers = list_value(json_value(root, "containers.raw.json"), "final containers")
    services: dict[str, dict[str, Any]] = {}
    for item in containers:
        value = object_value(item, "final container")
        service = container_service(value, "final container")
        require(service not in services, f"duplicate final container for {service}")
        services[service] = value
    expected_services = {
        "broker", "completion", "init-kafka", "jaeger", "order-v1", "payment",
        "restaurant-pos", "restate", "webui",
    }
    require(set(services) == expected_services, "final service set contains a target/control or omits a source dependency")
    expected_images = {
        "broker": "sha256:fbbb6fa11b258a88b83f54d4f0bddfcffbf2279f99d66a843486e3da7bdfbf41",
        "init-kafka": "sha256:fbbb6fa11b258a88b83f54d4f0bddfcffbf2279f99d66a843486e3da7bdfbf41",
        "jaeger": "sha256:ac85f812596ffb596ddcdbfe7c287eb44f781706e4232741bf9f81ff23aa1da9",
        "order-v1": source_image,
        "payment": build["SAFE_CHANGE_RUNTIME_IMAGE"],
        "completion": build["SAFE_CHANGE_RUNTIME_IMAGE"],
        "restaurant-pos": build["RESTAURANT_IMAGE"],
        "restate": COMPAT.RESTATE_IMAGE_ID,
        "webui": build["WEBUI_IMAGE"],
    }
    for service, expected_image in expected_images.items():
        value = services[service]
        require(value.get("Image") == expected_image, f"{service} did not run the frozen image")
        state = object_value(value.get("State"), service + " state")
        if service == "init-kafka":
            require(state.get("Running") is False and state.get("Status") == "exited" and state.get("ExitCode") == 0, "Kafka initializer did not complete successfully")
        else:
            require(state.get("Running") is True and state.get("Status") == "running", f"{service} was not running at the final cut")
    require(services["order-v1"].get("Id") == retained_id, "final service inventory does not contain the retained v1 worker")
    require(services["payment"].get("Id") == recovered_id, "final inventory does not contain the released payment provider")
    return str(retained_id), str(recovered_id)


def validate_cli(root: Path, invocation_id: str, order_id: str) -> None:
    require(read(root, "pause.stderr") == b"", "official pause CLI wrote stderr")
    output = read(root, "pause.stdout").decode("utf-8", errors="strict")
    require(
        invocation_id in output and f"order-workflow/{order_id}/run" in output
        and "[OK]: Paused 1 invocations" in output,
        "official pause CLI did not pause exactly the selected invocation",
    )
    require(read(root, "resume.stderr") == b"", "official resume CLI wrote stderr")
    resume = read(root, "resume.stdout").decode("utf-8", errors="strict")
    require(
        invocation_id in resume and f"order-workflow/{order_id}/run" in resume
        and "[OK]: Resumed 1 invocations" in resume,
        "official resume CLI did not resume exactly the selected invocation",
    )
    for name in ("driver-01.json", "driver-02.json"):
        driver = object_value(json_value(root, name), name)
        exact_fields(driver, {"invocationId", "status"}, name)
        require(
            driver.get("status") == "Accepted"
            and isinstance(driver.get("invocationId"), str)
            and COMPAT.INVOCATION_ID.fullmatch(driver["invocationId"]) is not None,
            f"{name} was not accepted through official Restate ingress",
        )
    require(
        json_value(root, "driver-01.json")["invocationId"]
        != json_value(root, "driver-02.json")["invocationId"],
        "the two official driver starts reused one invocation",
    )
    require(read(root, "exit-status.txt") == b"0\n", "old-drain runner did not exit successfully")
    forbidden = (
        "target-start.json", "deployment-v2.json",
        "certificate-v2.json", "active-v2.json", "control-at-cut.json",
    )
    require(not any((root / name).exists() for name in forbidden), "old-drain evidence contains a target/edit path")


REQUIRED_FILES = {
    "build.env", "versions.env", "images.env", "runner.sha256", "run-metadata.json",
    "order.json", "order.sha256", "source-submit.json", "deployment-v1.json",
    "deployments-at-cut.json", "final-deployments.json", "status-before-pause.json",
    "paused-poll.json", "cut-status.json", "paused-status-after-window.json",
    "final-status.json", "final-invocations.json", "terminal-poll.json",
    "cut-journal.json", "paused-journal-after-window.json", "final-journal.json",
    "cut-workflow-state.json", "paused-workflow-state-after-window.json",
    "final-workflow-state.json", "payment-before-pause.json", "payment-at-cut.json",
    "payment-after-cut-window.json", "payment-after-recovery.json", "final-payment-stats.json",
    "completion-at-cut.json", "completion-after-cut-window.json", "final-completion-stats.json",
    "payment-at-cut.history", "payment-after-cut-window.history", "payment-after-recovery.history",
    "payment.history", "completion-at-cut.history", "completion-after-cut-window.history",
    "completion.history", "pause.stdout", "pause.stderr", "resume.stdout", "resume.stderr",
    "driver-01.json", "driver-02.json", "source-before-crash.json",
    "source-before-crash.log", "source-crash.txt", "source-retained.json",
    "final-source-retained.json", "final-source-retained.log", "payment-held-container.json",
    "payment-held.log", "payment-recovered-container.json", "payment-recreate.stdout",
    "payment-recreate.stderr", "containers.raw.json", "compose-config.yaml", "exit-status.txt",
}


def check_evidence(path: Path, expected_case: str | None = None) -> dict[str, Any]:
    root = root_for(path)
    versions, _images, build, runner_hash = validate_inputs(root)
    case, order_id, observation, terminal = validate_metadata(root, expected_case, versions, build, runner_hash)
    order_bytes = validate_order(root, order_id)
    deployment_id, deployment_created = validate_deployment(root)
    (
        invocation_id, created, cut_modified, final_modified, runtime_status, final_journal_size,
    ) = validate_status(root, order_id, deployment_id, deployment_created)
    runtime_view_digest, business_status = validate_journal_and_state(
        root, order_id, order_bytes, runtime_status, final_journal_size
    )
    (
        payment_token, payment_id, completion_id,
        payment_deliveries, payment_commits,
        completion_deliveries, completion_commits,
        requirement_satisfied,
    ) = validate_provider(root, case, order_id, runtime_status, business_status)
    source_container_id, recovered_payment_container_id = validate_source_container(root, build, case)
    validate_cli(root, invocation_id, order_id)

    # observed.json is intentionally excluded: every returned fact above was
    # independently reconstructed from the required artifacts.
    artifact_hashes = {name: sha256(read(root, name)).hexdigest() for name in sorted(REQUIRED_FILES)}
    evidence_digest = sha256(json.dumps(artifact_hashes, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        "schema": 1,
        "valid": True,
        "cell": "old-drain",
        "system": "native-restate",
        "case": case,
        "runner_sha256": runner_hash,
        "restate_cli_image": versions["RESTATE_CLI_IMAGE"],
        "restate_server_image": versions["RESTATE_SERVER_IMAGE"],
        "order_id": order_id,
        "invocation_id": invocation_id,
        "created_at": created.isoformat(),
        "cut_modified_at": cut_modified.isoformat(),
        "final_modified_at": final_modified.isoformat(),
        "source_deployment_id": deployment_id,
        "source_image": build["NATIVE_ORDER_V1_IMAGE"],
        "source_container_id": source_container_id,
        "recovered_payment_container_id": recovered_payment_container_id,
        "payment_token": payment_token,
        "payment_operation_id": payment_id,
        "completion_operation_id": completion_id,
        "payment_at_cut_deliveries": 1,
        "payment_at_cut_commits": 0 if case == "h0" else 1,
        "payment_recovery_deliveries": payment_deliveries - 1,
        "payment_deliveries": payment_deliveries,
        "payment_commits": payment_commits,
        "completion_deliveries": completion_deliveries,
        "completion_commits": completion_commits,
        "runtime_view_digest": runtime_view_digest,
        "observation_seconds": observation,
        "terminal_seconds": terminal,
        "decision": "retain-v1",
        "runtime_status": runtime_status,
        "business_status": business_status,
        "old_code_required": True,
        "target_started": False,
        "resubmitted": False,
        "fault_release": "compose-recreate-preserve-volume",
        "v1_engaged": True,
        "duplicate_external_effect": payment_commits > 1,
        "requirement_satisfied": requirement_satisfied,
        "availability_preserved": runtime_status == "completed",
        "artifact_count": len(artifact_hashes),
        "evidence_digest": evidence_digest,
    }


def check_pair(first_path: Path, second_path: Path) -> dict[str, Any]:
    first = check_evidence(first_path)
    second = check_evidence(second_path)
    by_case = {first["case"]: (root_for(first_path), first), second["case"]: (root_for(second_path), second)}
    require(set(by_case) == {"h0", "h1"}, "paired evidence must contain one H0 and one H1 attempt")
    h0_root, h0 = by_case["h0"]
    h1_root, h1 = by_case["h1"]
    for name in ("build.env", "versions.env", "images.env", "runner.sha256", "order.json", "cut-journal.json", "cut-workflow-state.json"):
        require(read(h0_root, name) == read(h1_root, name), f"paired H0/H1 {name} differs")
    require(
        h0["order_id"] == h1["order_id"]
        and h0["invocation_id"] == h1["invocation_id"]
        and h0["payment_token"] == h1["payment_token"]
        and h0["payment_operation_id"] == h1["payment_operation_id"]
        and h0["runtime_view_digest"] == h1["runtime_view_digest"]
        and h0["observation_seconds"] == h1["observation_seconds"]
        and h0["terminal_seconds"] == h1["terminal_seconds"]
        and h0["source_deployment_id"] != h1["source_deployment_id"]
        and h0["payment_at_cut_deliveries"] == h1["payment_at_cut_deliveries"] == 1
        and h0["payment_at_cut_commits"] == 0 and h1["payment_at_cut_commits"] == 1
        and h0["v1_engaged"] is True and h1["v1_engaged"] is True,
        "paired attempts do not isolate only the durable external commit fact",
    )
    pair_material = json.dumps(
        {"h0": h0["evidence_digest"], "h1": h1["evidence_digest"]},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return {
        "schema": 1,
        "valid": True,
        "cell": "old-drain",
        "system": "native-restate",
        "order_id": h0["order_id"],
        "invocation_id": h0["invocation_id"],
        "same_runtime_view": True,
        "different_external_commit_fact": True,
        "decision_h0": "retain-v1",
        "decision_h1": "retain-v1",
        "old_code_required": True,
        "v1_engaged": True,
        "availability_preserved": h0["availability_preserved"] and h1["availability_preserved"],
        "requirement_satisfied_h0": h0["requirement_satisfied"],
        "requirement_satisfied_h1": h1["requirement_satisfied"],
        "h0": h0,
        "h1": h1,
        "pair_digest": sha256(pair_material).hexdigest(),
    }


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--evidence", required=True, type=Path, help="old-drain attempt or results directory")
    value.add_argument("--case", choices=("h0", "h1"), help="optional expected history")
    value.add_argument("--peer", type=Path, help="the matched H0/H1 peer evidence directory")
    return value


def main() -> int:
    args = parser().parse_args()
    try:
        if args.peer is None:
            result = check_evidence(args.evidence, args.case)
        else:
            result = check_pair(args.evidence, args.peer)
            if args.case is not None:
                require(result[args.case]["case"] == args.case, "requested case is absent from pair")
    except (EvidenceError, COMPAT.EvidenceError, OSError, UnicodeError) as error:
        print(f"check-old-drain: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
