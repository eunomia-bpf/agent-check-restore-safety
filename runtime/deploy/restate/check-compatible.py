#!/usr/bin/env python3
"""Independently validate one compatible live-replacement evidence bundle.

The live runner is deliberately not imported.  This checker recomputes its
verdict from the official Restate queries, provider append-only records,
container inspection, build provenance, and (for the proposed lane) control
History and a freshly checked Certificate.  ``observed.json`` is intentionally
neither read nor included in the evidence digest.
"""

from __future__ import annotations

import argparse
import base64
from datetime import datetime
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Iterable


BASE_CHECK_PATH = Path(__file__).with_name("check.py")
SPEC = importlib.util.spec_from_file_location("restate_evidence_check", BASE_CHECK_PATH)
assert SPEC is not None and SPEC.loader is not None
BASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BASE)

ZERO_HASH = "0" * 64
UPSTREAM_COMMIT = "2d429daae784d20982691fb31431702b4ad30a6b"
RESTATE_IMAGE = (
    "docker.io/restatedev/restate:1.7.3@"
    "sha256:1856961b7a16d1b00131e5704231b79e0334703df074a31867ea8ce2110d5cfa"
)
RESTATE_CLI_IMAGE = (
    "docker.io/restatedev/restate-cli:1.7.3@"
    "sha256:30b3ed1acfb3366f03b99839f0b9e336cd9f2333e128c702feeafacfe985ce51"
)
RESTATE_IMAGE_ID = "sha256:1856961b7a16d1b00131e5704231b79e0334703df074a31867ea8ce2110d5cfa"
SCRIPT_DIR = Path(__file__).resolve().parent
RUNNER_PATH = SCRIPT_DIR / "run-compatible-case.sh"
VERSIONS_PATH = SCRIPT_DIR / "versions.env"
IMAGES_PATH = SCRIPT_DIR / "images.env"
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
CONTAINER_ID = re.compile(r"[0-9a-f]{64}\Z")
ORDER_ID = re.compile(r"[A-Za-z0-9._-]{1,128}\Z")
INVOCATION_ID = re.compile(r"inv_[A-Za-z0-9]+\Z")
DEPLOYMENT_ID = re.compile(r"dp_[A-Za-z0-9]+\Z")
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")

# These source and build-input digests are frozen by the approved experiment.
# Docker image IDs are not frozen because independent builds can differ; each
# run instead binds its image IDs to the inspected source/target containers.
FROZEN_BUILD_HASHES = {
    "UPSTREAM_ARCHIVE_SHA256": "9422ccd6d5b0a9035bd207b6642f6d8decaac58839dd8abee8691b384bdd825a",
    "APP_LOCK_SHA256": "8b5462348ad0bfde8e98f6221e5bd37e69bc2f8aceaffb66306ec1b71bef3bf7",
    "PROVIDER_DIRECT_PATCH_SHA256": "b5ab1a66c0a9b140d1843c2e2204d1e4447c22754afa46159058312b0764fe85",
    "COMPATIBLE_V2_PATCH_SHA256": "93aa98df1501576c6ca9a3c174ccd1f07ce01eca06c1b31212de86866f11504e",
    "NATIVE_COMPATIBLE_V2_PATCH_SHA256": "4348fb91f80ee2bc8fe0a2d5e839a2b505c47c63531c90717e99915e53bf94c5",
    "V1_CONTEXT_SHA256": "46075311a51940e5be1d369146dca4c182a4bec08c5aac66d04fa6462af794ae",
    "COMPATIBLE_V2_CONTEXT_SHA256": "cd609b818a9b1bd45f52310d231fc7c34361de86fa75fbb31892b9672aec0b99",
    "NATIVE_V1_CONTEXT_SHA256": "7905c3adb9eb17f9ad1a04413a2e9d6cf45e69992387137638aa84be47eb2d0c",
    "NATIVE_COMPATIBLE_V2_CONTEXT_SHA256": "1f0e4a3b0ad68f58a99fe70f28cce30504825f3657481fd34cf7d92ef5dea7c6",
    "V1_PROGRAM_SHA256": "308fd539f4b612badd5d461436c2b6fae3db67dd8caea2727d2d82caa7379075",
    "COMPATIBLE_V2_WORKFLOW_SHA256": "0ea639ab69d5f48695100fa0c5061581a6c41f7bbaf40d11cda16b467242f84b",
    "COMPATIBLE_V2_COMPLETION_CLIENT_SHA256": "d89fc3e633ce914e6c6efa63a68235c2a82dfa4487e178307be55242fcf7cb0b",
    "NATIVE_COMPATIBLE_V2_COMPLETION_CLIENT_SHA256": "68420b5a2dbd1f04a4aa25149f7d021d47127ccfdfea0a88f0b0f3f469c2dd2a",
    "COMPATIBLE_V2_COMPILED_SHA256": "4ce73632b617e808534eaaa6ea88258b9000c179158022ea560832e9359df9ff",
    "NATIVE_COMPATIBLE_V2_COMPILED_SHA256": "4ce73632b617e808534eaaa6ea88258b9000c179158022ea560832e9359df9ff",
    "NATIVE_PAYMENT_CLIENT_SHA256": "8abb6789492ad8e3c82142ab783bee646403f1acafd4c625c54602d9f8af5c98",
    "NATIVE_COMPLETION_CLIENT_SHA256": "50c7fb346d842de9331b4fa255306fc3f429bd05d410683b43a6a28a0920b017",
    "NATIVE_V1_COMPILED_SHA256": "14e1423c71db968449826b6d6d7f8d611316173218fc49e6edded20d9e3e19e3",
}


class EvidenceError(ValueError):
    """Compatible evidence is absent, malformed, or internally inconsistent."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceError(message)


def evidence_root(path: Path) -> Path:
    root = path.resolve(strict=True)
    if (root / "results").is_dir() and not (root / "order.json").exists():
        root = (root / "results").resolve(strict=True)
    require(root.is_dir(), "evidence root is not a directory")
    return root


def read(root: Path, name: str, *, maximum: int = 64 << 20) -> bytes:
    path = root / name
    try:
        info = path.lstat()
    except FileNotFoundError as error:
        raise EvidenceError(f"required artifact is absent: {name}") from error
    require(path.is_file() and not path.is_symlink(), f"{name} is not a regular file")
    require(info.st_size <= maximum, f"{name} exceeds its size limit")
    data = path.read_bytes()
    require(len(data) == info.st_size, f"{name} changed while read")
    return data


def json_value(root: Path, name: str) -> Any:
    try:
        return BASE._loads(read(root, name), name)
    except BASE.EvidenceError as error:
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
    wrapper = object_value(value, label)
    exact_fields(wrapper, {"rows"}, label)
    rows = list_value(wrapper["rows"], label + " rows")
    require(len(rows) == 1 and isinstance(rows[0], dict), f"{label} must contain one row")
    return rows[0]


def timestamp(value: Any, label: str) -> datetime:
    require(isinstance(value, str) and value, f"{label} is not a timestamp")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise EvidenceError(f"{label} is not a timestamp") from error
    require(result.tzinfo is not None, f"{label} has no timezone")
    return result


def parse_build_env(data: bytes) -> dict[str, str]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise EvidenceError("build.env is not UTF-8") from error
    output: dict[str, str] = {}
    for number, line in enumerate(text.splitlines(), 1):
        require(line and "=" in line and not line.startswith("#"), f"build.env line {number} is invalid")
        key, value = line.split("=", 1)
        require(re.fullmatch(r"[A-Z][A-Z0-9_]*", key) is not None, f"build.env key {key!r} is invalid")
        require(key not in output and value, f"build.env key {key!r} is duplicate or empty")
        output[key] = value
    image_keys = {
        "ORDER_V1_IMAGE", "ORDER_COMPATIBLE_V2_IMAGE", "NATIVE_ORDER_V1_IMAGE",
        "NATIVE_ORDER_COMPATIBLE_V2_IMAGE", "SAFE_CHANGE_RUNTIME_IMAGE",
    }
    require(image_keys | set(FROZEN_BUILD_HASHES) <= set(output), "build.env omitted compatible provenance")
    for key in image_keys:
        require(IMAGE_ID.fullmatch(output[key]) is not None, f"{key} is not an immutable image ID")
    for key, expected in FROZEN_BUILD_HASHES.items():
        require(HEX64.fullmatch(output[key]) is not None, f"{key} is not SHA-256")
        require(output[key] == expected, f"{key} differs from the frozen compatible build")
    require(output["COMPATIBLE_V2_COMPILED_SHA256"] == output["NATIVE_COMPATIBLE_V2_COMPILED_SHA256"], "compatible workflow bytes differ by lane")
    require(output["ORDER_V1_IMAGE"] != output["ORDER_COMPATIBLE_V2_IMAGE"], "proposed source and target images are identical")
    require(output["NATIVE_ORDER_V1_IMAGE"] != output["NATIVE_ORDER_COMPATIBLE_V2_IMAGE"], "native source and target images are identical")
    return output


def parse_frozen_env(data: bytes, label: str) -> dict[str, str]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise EvidenceError(f"{label} is not UTF-8") from error
    output: dict[str, str] = {}
    for number, line in enumerate(text.splitlines(), 1):
        if not line or line.startswith("#"):
            continue
        require("=" in line, f"{label} line {number} is invalid")
        key, value = line.split("=", 1)
        require(
            re.fullmatch(r"[A-Z][A-Z0-9_]*", key) is not None
            and key not in output and value and not any(character.isspace() for character in value),
            f"{label} line {number} is invalid",
        )
        output[key] = value
    require(output, f"{label} has no assignments")
    return output


def local_bytes(path: Path, label: str) -> bytes:
    try:
        info = path.lstat()
    except FileNotFoundError as error:
        raise EvidenceError(f"current {label} is absent") from error
    require(path.is_file() and not path.is_symlink(), f"current {label} is not a regular file")
    data = path.read_bytes()
    require(len(data) == info.st_size, f"current {label} changed while read")
    return data


def validate_runtime_inputs(root: Path) -> tuple[dict[str, str], dict[str, str], str]:
    versions_bytes = read(root, "versions.env")
    images_bytes = read(root, "images.env")
    require(versions_bytes == local_bytes(VERSIONS_PATH, "versions.env"), "versions.env differs from the frozen harness input")
    require(images_bytes == local_bytes(IMAGES_PATH, "images.env"), "images.env differs from the frozen harness input")
    versions = parse_frozen_env(versions_bytes, "versions.env")
    images = parse_frozen_env(images_bytes, "images.env")
    require(
        versions == {
            "RESTATE_EXAMPLES_TAG": "v1.7.7",
            "RESTATE_EXAMPLES_COMMIT": UPSTREAM_COMMIT,
            "RESTATE_SERVER_IMAGE": RESTATE_IMAGE,
            "RESTATE_CLI_IMAGE": RESTATE_CLI_IMAGE,
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
            "RESTATE_EXAMPLES_ARCHIVE_SHA256": FROZEN_BUILD_HASHES["UPSTREAM_ARCHIVE_SHA256"],
        },
        "images.env differs from the frozen external-image inputs",
    )
    runner_bytes = local_bytes(RUNNER_PATH, "compatible runner")
    runner_hash = sha256(runner_bytes).hexdigest()
    checksum = read(root, "runner.sha256").decode("utf-8", errors="strict")
    match = re.fullmatch(r"([0-9a-f]{64})  (.+/run-compatible-case\.sh)\n", checksum)
    require(match is not None and match.group(1) == runner_hash, "runner.sha256 does not bind the current compatible runner")
    return versions, images, runner_hash


def validate_run_metadata(
    root: Path,
    method: str,
    order: dict[str, Any],
    build: dict[str, str],
    build_bytes: bytes,
    versions: dict[str, str],
    runner_hash: str,
) -> dict[str, Any]:
    metadata = object_value(json_value(root, "run-metadata.json"), "run metadata")
    exact_fields(metadata, {
        "schema", "recorded_at", "method", "state_dir", "order_id", "delivery_delay_ms",
        "source_image", "target_image", "restate_cli_image", "restate_server_image",
        "runner_sha256", "build_env", "skip_build", "effective_invocation",
    }, "run metadata")
    invocation = object_value(metadata.get("effective_invocation"), "effective invocation")
    exact_fields(invocation, {
        "COMPATIBLE_METHOD", "COMPATIBLE_STATE_DIR", "ORDER_ID",
        "COMPATIBLE_DELIVERY_DELAY_MS", "SKIP_BUILD", "HARNESS_BUILD_ENV", "script",
    }, "effective invocation")
    source_image = build["ORDER_V1_IMAGE" if method == "proposed" else "NATIVE_ORDER_V1_IMAGE"]
    target_image = build["ORDER_COMPATIBLE_V2_IMAGE" if method == "proposed" else "NATIVE_ORDER_COMPATIBLE_V2_IMAGE"]
    state_dir, build_env = metadata.get("state_dir"), metadata.get("build_env")
    require(isinstance(state_dir, str) and Path(state_dir).is_absolute(), "run state directory is not absolute")
    require(isinstance(build_env, str) and Path(build_env).is_absolute(), "effective build.env path is not absolute")
    skip_build = metadata.get("skip_build")
    require(type(skip_build) is bool, "skip_build is not boolean")
    timestamp(metadata.get("recorded_at"), "run metadata timestamp")
    require(
        metadata.get("schema") == 1
        and metadata.get("method") == method
        and metadata.get("order_id") == order.get("id")
        and metadata.get("delivery_delay_ms") == order.get("deliveryDelay")
        and metadata.get("source_image") == source_image
        and metadata.get("target_image") == target_image
        and metadata.get("restate_cli_image") == RESTATE_CLI_IMAGE == versions["RESTATE_CLI_IMAGE"]
        and metadata.get("restate_server_image") == RESTATE_IMAGE == versions["RESTATE_SERVER_IMAGE"]
        and metadata.get("runner_sha256") == runner_hash,
        "run metadata differs from the effective compatible inputs",
    )
    require(
        invocation == {
            "COMPATIBLE_METHOD": method,
            "COMPATIBLE_STATE_DIR": state_dir,
            "ORDER_ID": order["id"],
            "COMPATIBLE_DELIVERY_DELAY_MS": order["deliveryDelay"],
            "SKIP_BUILD": 1 if skip_build else 0,
            "HARNESS_BUILD_ENV": build_env,
            "script": "runtime/deploy/restate/run-compatible-case.sh",
        },
        "effective invocation is inconsistent with run metadata",
    )
    external_build = Path(build_env)
    if external_build.exists():
        require(
            external_build.is_file() and not external_build.is_symlink()
            and external_build.read_bytes() == build_bytes,
            "effective build.env differs from the captured build.env",
        )
    return metadata


def stats(value: Any, expected: dict[str, Any], label: str) -> dict[str, Any]:
    item = object_value(value, label)
    exact_fields(item, {"deliveries", "commits", "paths"}, label)
    require(item == expected, f"{label} differs")
    return item


def records(root: Path, name: str, label: str) -> list[dict[str, Any]]:
    try:
        return BASE._records(root / name, label)
    except BASE.EvidenceError as error:
        raise EvidenceError(str(error)) from error


def validate_order(root: Path) -> tuple[dict[str, Any], str]:
    order_bytes = read(root, "order.json")
    order = object_value(json_value(root, "order.json"), "order")
    exact_fields(order, {"id", "restaurantId", "products", "totalCost", "deliveryDelay"}, "order")
    require(
        order.get("restaurantId") == "restaurant-01"
        and order.get("products") == [{"productId": "pizza-01", "description": "Pizza", "quantity": 1}]
        and order.get("totalCost") == 42
        and type(order.get("deliveryDelay")) is int
        and 10000 <= order["deliveryDelay"] <= 60000,
        "compatible workload differs",
    )
    order_id = order.get("id")
    require(isinstance(order_id, str) and ORDER_ID.fullmatch(order_id) is not None, "order identity differs")
    checksum = read(root, "order.sha256").decode("utf-8", errors="strict")
    match = re.fullmatch(r"([0-9a-f]{64})  (.+/results/order\.json)\n", checksum)
    require(match is not None and match.group(1) == sha256(order_bytes).hexdigest(), "order checksum differs")
    return order, order_id


def deployment_pair(root: Path, build: dict[str, str], method: str) -> tuple[str, str, datetime]:
    source = object_value(json_value(root, "deployment-v1.json"), "source deployment")
    target = object_value(json_value(root, "deployment-compatible.json"), "compatible deployment")
    source_id, target_id = source.get("id"), target.get("id")
    require(
        isinstance(source_id, str) and DEPLOYMENT_ID.fullmatch(source_id) is not None
        and isinstance(target_id, str) and DEPLOYMENT_ID.fullmatch(target_id) is not None
        and source_id != target_id,
        "deployment identities differ",
    )
    expected_services = {
        "driver-digital-twin", "order-workflow", "order-status", "delivery-manager",
        "driver-delivery-matcher", "driver-mobile-app",
    }
    for value, identity, revision, label in (
        (source, source_id, 1, "source"), (target, target_id, 2, "target")
    ):
        services = list_value(value.get("services"), label + " deployment services")
        require(
            len(services) == 6
            and {item.get("name") for item in services if isinstance(item, dict)} == expected_services
            and all(item.get("deployment_id") == identity and item.get("revision") == revision for item in services),
            f"{label} deployment service revisions differ",
        )
        require(
            value.get("min_protocol_version") == 5
            and value.get("max_protocol_version") == 7
            and value.get("sdk_version") == "restate-sdk-typescript/1.16.6",
            f"{label} deployment protocol provenance differs",
        )
    listing = object_value(json_value(root, "deployments.json"), "deployment listing")
    exact_fields(listing, {"deployments"}, "deployment listing")
    items = list_value(listing["deployments"], "deployment listing")
    require(len(items) == 2, "compatible run registered an unexpected deployment")
    selected = {item.get("id"): item for item in items if isinstance(item, dict)}
    require(set(selected) == {source_id, target_id}, "source/target deployments are absent")
    variants = {
        source_id: ("http://order-v1:9080/", f"{method}-v1", 1),
        target_id: ("http://order-v2:9080/", f"{method}-compatible-v2", 2),
    }
    target_created: datetime | None = None
    for identity, (uri, variant, revision) in variants.items():
        item = selected[identity]
        require(item.get("uri") == uri, f"{variant} deployment URI differs")
        require(
            item.get("metadata") == {"method": method, "variant": variant, "upstream_commit": UPSTREAM_COMMIT},
            f"{variant} deployment metadata differs",
        )
        services = list_value(item.get("services"), f"{variant} listed services")
        require(
            len(services) == 6
            and {entry.get("name") for entry in services if isinstance(entry, dict)} == expected_services
            and all(entry.get("revision") == revision for entry in services),
            f"{variant} listed revisions differ",
        )
        created = timestamp(item.get("created_at"), f"{variant} creation time")
        if identity == target_id:
            target_created = created
    assert target_created is not None
    return source_id, target_id, target_created


def validate_journal_document(value: Any, label: str) -> list[dict[str, Any]]:
    document = object_value(value, label)
    exact_fields(document, {"rows"}, label)
    rows = list_value(document["rows"], label + " rows")
    required = {"index", "version", "entry_type", "completed", "raw", "raw_length", "entry_lite_json"}
    allowed = required | {"name"}
    for index, item in enumerate(rows):
        row = object_value(item, f"{label} row {index}")
        require(required <= set(row) <= allowed, f"{label} row {index} fields changed")
        require(
            row.get("index") == index and type(row.get("version")) is int and row["version"] > 0
            and isinstance(row.get("entry_type"), str) and type(row.get("completed")) is bool
            and isinstance(row.get("raw"), str) and type(row.get("raw_length")) is int
            and isinstance(row.get("entry_lite_json"), str),
            f"{label} row {index} is malformed",
        )
        try:
            raw = bytes.fromhex(row["raw"])
        except ValueError as error:
            raise EvidenceError(f"{label} row {index} raw payload is not hex") from error
        require(len(raw) == row["raw_length"], f"{label} row {index} raw length differs")
        try:
            BASE._loads(row["entry_lite_json"].encode(), f"{label} row {index} lite JSON")
        except BASE.EvidenceError as error:
            raise EvidenceError(str(error)) from error
    return rows


def lite(row: dict[str, Any], label: str) -> dict[str, Any]:
    try:
        return object_value(BASE._loads(row["entry_lite_json"].encode(), label), label)
    except BASE.EvidenceError as error:
        raise EvidenceError(str(error)) from error


def row_shape(rows: Iterable[dict[str, Any]]) -> list[tuple[int, str, str]]:
    return [(row["index"], row["entry_type"], str(row.get("name", ""))) for row in rows]


def validate_cut_and_final(
    root: Path, order_id: str, submit_id: str, source_deployment: str, target_deployment: str
) -> tuple[str, str, list[dict[str, Any]]]:
    cut = one_row(json_value(root, "cut-status.json"), "cut status")
    after = one_row(json_value(root, "cut-status-after-window.json"), "post-wake cut status")
    invocation_id = cut.get("id")
    require(
        invocation_id == submit_id
        and isinstance(invocation_id, str) and INVOCATION_ID.fullmatch(invocation_id) is not None
        and cut.get("target") == f"order-workflow/{order_id}/run"
        and cut.get("status") == "paused"
        and cut.get("pinned_deployment_id") == source_deployment
        and cut.get("pinned_service_protocol_version") == 6
        and cut.get("journal_size") == 6,
        "source did not establish the paused v1 compatible cut",
    )
    created_at = cut.get("created_at")
    timestamp(created_at, "source invocation creation time")
    cut_modified = timestamp(cut.get("modified_at"), "cut modification time")
    after_modified = timestamp(after.get("modified_at"), "post-wake modification time")
    require(
        after.get("journal_size") == 7
        and after_modified > cut_modified
        and {key: value for key, value in after.items() if key not in {"journal_size", "modified_at"}}
        == {key: value for key, value in cut.items() if key not in {"journal_size", "modified_at"}},
        "paused invocation changed by more than the durable Sleep notification",
    )

    cut_rows = validate_journal_document(json_value(root, "cut-journal.json"), "cut journal")
    after_rows = validate_journal_document(json_value(root, "cut-journal-after-window.json"), "post-wake cut journal")
    expected_cut = [
        (0, "Command: Input", ""), (1, "Command: SetState", ""),
        (2, "Command: Run", "payment"), (3, "Notification: Run", ""),
        (4, "Command: SetState", ""), (5, "Command: Sleep", ""),
    ]
    require(row_shape(cut_rows) == expected_cut, "v1 cut is not payment then scheduled Sleep")
    require(after_rows[:-1] == cut_rows and len(after_rows) == 7, "post-wake journal rewrote the paused cut")
    payment_command = object_value(object_value(lite(cut_rows[2], "payment Run").get("Command"), "payment Command").get("Run"), "payment Run")
    payment_notice = object_value(lite(cut_rows[3], "payment notification").get("Notification"), "payment notification")
    sleep_command = object_value(object_value(lite(cut_rows[5], "Sleep").get("Command"), "Sleep Command").get("Sleep"), "Sleep")
    sleep_notice = object_value(lite(after_rows[6], "Sleep notification").get("Notification"), "Sleep notification")
    require(payment_command == {"completion_id": 1, "name": "payment"}, "payment Run identity differs")
    require(
        payment_notice.get("ty") == {"Completion": "Run"}
        and payment_notice.get("id") == {"CompletionId": 1}
        and payment_notice.get("result") == "Success",
        "payment Run did not complete successfully at the cut",
    )
    expected_sleep_notice = {
        "Notification": {
            "ty": {"Completion": "Sleep"}, "id": {"CompletionId": 2}, "result": "Void",
        },
    }
    expected_sleep_row = {
        "index": 6,
        "version": cut_rows[-1]["version"],
        "entry_type": "Notification: Sleep",
        "completed": False,
        "raw": "08022200",
        "raw_length": 4,
        "entry_lite_json": json.dumps(expected_sleep_notice, separators=(",", ":")),
    }
    require(
        set(sleep_command) == {"wake_up_time", "completion_id"}
        and type(sleep_command.get("wake_up_time")) is int
        and sleep_command.get("completion_id") == 2
        and after_rows[6] == expected_sleep_row
        and sleep_notice == expected_sleep_notice["Notification"],
        "paused cut did not append exactly the matching Sleep notification",
    )
    require(
        [row for row in after_rows if row["entry_type"] == "Command: Run" and row.get("name") != "payment"] == [],
        "future external work began while paused",
    )

    cut_state = json_value(root, "cut-workflow-state.json")
    require(cut_state == json_value(root, "cut-workflow-state-after-window.json"), "workflow state changed while paused")
    state_row = one_row(cut_state, "cut workflow state")
    require(
        state_row.get("service_name") == "order-workflow"
        and state_row.get("service_key") == order_id
        and state_row.get("key") == "status"
        and state_row.get("value_utf8") == '"SCHEDULED"',
        "cut workflow state is not SCHEDULED",
    )

    final = one_row(json_value(root, "final-status.json"), "final status")
    final_set = one_row(json_value(root, "final-invocations.json"), "final invocation set")
    require(final_set == final, "final query did not identify exactly the same invocation")
    require(
        final.get("id") == invocation_id
        and final.get("target") == cut.get("target")
        and final.get("created_at") == created_at
        and final.get("status") == "completed"
        and final.get("pinned_deployment_id") == target_deployment
        and final.get("pinned_service_protocol_version") == cut.get("pinned_service_protocol_version")
        and final.get("journal_size") == 27,
        "replacement did not complete the same invocation on the compatible target",
    )
    timestamp(final.get("modified_at"), "final invocation modification time")
    final_rows = validate_journal_document(json_value(root, "final-journal.json"), "final journal")
    expected_final = expected_cut + [
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
    require(row_shape(final_rows) == expected_final, "completed journal shape differs")
    require(final_rows[:7] == after_rows, "replacement rewrote the post-wake cut")
    completion_command = object_value(object_value(lite(final_rows[23], "completion Run").get("Command"), "completion Command").get("Run"), "completion Run")
    completion_notice = object_value(lite(final_rows[24], "completion notification").get("Notification"), "completion notification")
    output = object_value(object_value(lite(final_rows[26], "workflow Output").get("Command"), "Output Command").get("Output"), "workflow Output")
    require(completion_command == {"completion_id": 9, "name": "completion"}, "completion Run identity differs")
    require(
        completion_notice.get("ty") == {"Completion": "Run"}
        and completion_notice.get("id") == {"CompletionId": 9}
        and completion_notice.get("result") == "Success"
        and output == {"result": "Success"},
        "completion Run or workflow output was unsuccessful",
    )
    final_state = one_row(json_value(root, "final-workflow-state.json"), "final workflow state")
    require(
        final_state.get("service_name") == "order-workflow"
        and final_state.get("service_key") == order_id
        and final_state.get("key") == "status"
        and final_state.get("value_utf8") == '"DELIVERED"',
        "final business state is not DELIVERED",
    )
    return invocation_id, str(created_at), after_rows


def validate_expected_completion(root: Path, order_id: str) -> tuple[str, bytes, str, str]:
    body = json.dumps(
        {"order_id": order_id, "status": "DELIVERED", "closure_version": "compatible-v2"},
        separators=(",", ":"),
    ).encode()
    completion_id = BASE._operation_id("restate-order-workflow", f"order/{order_id}/completion")
    provider_hash = BASE._provider_hash("/v1/complete", body)
    control_hash = BASE._gateway_hash(
        "http://completion:8081/v1/complete", completion_id, body
    )
    expected = {
        "schema": 1,
        "body_base64": base64.b64encode(body).decode(),
        "provider_request_hash": provider_hash,
        "control_request_hash": control_hash,
        "completion_operation_id": completion_id,
    }
    require(
        object_value(json_value(root, "expected-completion.json"), "expected completion") == expected,
        "expected-completion.json differs from the compatible closure",
    )
    return completion_id, body, provider_hash, control_hash


def validate_provider_evidence(root: Path, order_id: str) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    payment_one = {"deliveries": 1, "commits": 1, "paths": {"/v1/charge": 1}}
    completion_zero = {"deliveries": 0, "commits": 0, "paths": {}}
    completion_one = {"deliveries": 1, "commits": 1, "paths": {"/v1/complete": 1}}
    for name in ("payment-before-pause.json", "payment-at-cut.json", "payment-after-cut-window.json", "final-payment-stats.json"):
        stats(json_value(root, name), payment_one, name)
    for name in ("completion-before-pause.json", "completion-at-cut.json", "completion-after-cut-window.json"):
        stats(json_value(root, name), completion_zero, name)
    stats(json_value(root, "final-completion-stats.json"), completion_one, "final completion stats")

    source_log = read(root, "source-v1.log").decode("utf-8", errors="replace")
    matches = re.findall(rf"\[{re.escape(order_id)}\] Executing payment with token ([0-9a-f-]+) for \$42", source_log)
    require(len(matches) == 1 and UUID.fullmatch(matches[0]) is not None, "stable payment token is absent")
    token = matches[0]
    payment_id = BASE._operation_id("restate-order-workflow", token)
    completion_id, completion_body, completion_provider_hash, _ = validate_expected_completion(root, order_id)
    payment_body = json.dumps({"order_id": order_id, "amount": 42}, separators=(",", ":")).encode()
    payment_result = sha256(b"charged\0" + payment_id.encode() + b"\0" + b"1").hexdigest()
    completion_result = sha256(b"charged\0" + completion_id.encode()).hexdigest()
    expected_payment = {
        "operation_id": payment_id,
        "request_hash": BASE._provider_hash("/v1/charge", payment_body),
        "result_hash": payment_result,
        "remote_reference": f"payment/{payment_id}/commit-1",
        "path": "/v1/charge",
    }
    expected_completion = {
        "operation_id": completion_id,
        "request_hash": completion_provider_hash,
        "result_hash": completion_result,
        "remote_reference": f"completion/{completion_id}",
        "path": "/v1/complete",
    }
    at_cut = records(root, "payment-at-cut.history", "cut payment records")
    after_cut_payment = records(root, "payment-after-cut-window.history", "post-wake payment records")
    final_payment = records(root, "payment.history", "final payment records")
    cut_completion = records(root, "completion-at-cut.history", "cut completion records")
    after_cut_completion = records(root, "completion-after-cut-window.history", "post-wake completion records")
    final_completion = records(root, "completion.history", "final completion records")
    require(
        at_cut == [expected_payment] and after_cut_payment == at_cut and final_payment == at_cut,
        "payment was missing, duplicated, or changed after the cut",
    )
    require(
        cut_completion == [] and after_cut_completion == []
        and final_completion == [expected_completion],
        "completion was early, missing, or duplicated",
    )
    require(
        read(root, "payment-at-cut.history") == read(root, "payment-after-cut-window.history")
        == read(root, "payment.history"),
        "durable payment History bytes changed during or after the paused cut",
    )
    require(
        read(root, "completion-at-cut.history") == read(root, "completion-after-cut-window.history") == b"",
        "durable completion History changed while paused",
    )
    return payment_id, completion_id, expected_payment, expected_completion


def service_map(root: Path) -> dict[str, dict[str, Any]]:
    services: dict[str, dict[str, Any]] = {}
    for value in list_value(json_value(root, "containers.raw.json"), "container inspection"):
        item = object_value(value, "container")
        config = object_value(item.get("Config"), "container config")
        labels = object_value(config.get("Labels"), "container labels")
        service = labels.get("com.docker.compose.service")
        require(isinstance(service, str) and service and service not in services, "container service identity differs")
        services[service] = item
    return services


def validate_worker(
    item: dict[str, Any], *, image: str, service: str, version: str, method: str, running: bool
) -> None:
    require(item.get("Image") == image and item.get("State", {}).get("Running") is running, f"{service} container state/image differs")
    config = object_value(item.get("Config"), f"{service} config")
    labels = object_value(config.get("Labels"), f"{service} labels")
    require(
        config.get("Image") == image
        and labels.get("com.docker.compose.service") == service
        and labels.get("org.opencontainers.image.source") == "https://github.com/restatedev/examples"
        and labels.get("org.opencontainers.image.revision") == UPSTREAM_COMMIT
        and labels.get("org.opencontainers.image.version") == version,
        f"{service} image provenance differs",
    )
    networks = sorted(object_value(item.get("NetworkSettings"), f"{service} network settings").get("Networks", {}))
    expected_suffixes = ["_application", "_control"] if method == "proposed" else ["_application", "_effects"]
    actual_suffixes = [suffix for name in networks for suffix in expected_suffixes if name.endswith(suffix)]
    require(
        len(networks) == 2 and sorted(actual_suffixes) == sorted(expected_suffixes),
        f"{service} network path differs",
    )
    env = list_value(config.get("Env"), f"{service} environment")
    if method == "proposed":
        require(any(value == "SAFE_CHANGE_CONTROL_URL=http://control:8787" for value in env), f"{service} bypassed proposed control")
        require(not any(value.startswith("PAYMENT_ENDPOINT=") or value.startswith("COMPLETION_ENDPOINT=") for value in env), f"{service} retained direct provider endpoints")
    else:
        require("PAYMENT_ENDPOINT=http://payment:8081/v1/charge" in env and "COMPLETION_ENDPOINT=http://completion:8081/v1/complete" in env, f"{service} did not use the native direct-provider path")


def validate_containers(
    root: Path, build: dict[str, str], method: str, target_created: datetime, activation_sequence: int
) -> None:
    source_image = build["ORDER_V1_IMAGE" if method == "proposed" else "NATIVE_ORDER_V1_IMAGE"]
    target_image = build["ORDER_COMPATIBLE_V2_IMAGE" if method == "proposed" else "NATIVE_ORDER_COMPATIBLE_V2_IMAGE"]
    source_version = "v1" if method == "proposed" else "native-v1"
    target_version = "compatible-v2" if method == "proposed" else "native-compatible-v2"
    source_values = list_value(json_value(root, "source-container-before-removal.json"), "source container")
    require(len(source_values) == 1 and isinstance(source_values[0], dict), "source container identity is ambiguous")
    source = source_values[0]
    source_id = source.get("Id")
    require(isinstance(source_id, str) and CONTAINER_ID.fullmatch(source_id) is not None, "source container identity differs")
    validate_worker(source, image=source_image, service="order-v1", version=source_version, method=method, running=True)
    require(read(root, "source-container-removal.txt") == (source_id + "\n").encode(), "source removal did not name the captured v1 container")
    require(read(root, "source-container-after-removal.exit-status.txt") == b"1\n", "source remained inspectable after removal")
    require(read(root, "source-container-after-removal.json") == b"[]\n", "removed source inspection returned a container")
    require(read(root, "source-container-after-removal.stderr") == f"error: no such object: {source_id}\n".encode(), "source removal error evidence differs")

    services = service_map(root)
    require("order-v1" not in services and "order-v2" in services, "source remained or target was absent at final capture")
    require("naive-payment" not in services, "compatible run included the unsafe provider")
    restate = object_value(services.get("restate"), "Restate container")
    require(
        restate.get("Image") == RESTATE_IMAGE_ID
        and restate.get("Config", {}).get("Image") == RESTATE_IMAGE,
        "official Restate image differs",
    )
    for provider in ("payment", "completion"):
        require(services.get(provider, {}).get("Image") == build["SAFE_CHANGE_RUNTIME_IMAGE"], f"{provider} provider image differs")
    if method == "proposed":
        require(services.get("control", {}).get("Image") == build["SAFE_CHANGE_RUNTIME_IMAGE"], "proposed control was absent or unpinned")
    else:
        require("control" not in services, "native lane included proposed control")

    target = services["order-v2"]
    validate_worker(target, image=target_image, service="order-v2", version=target_version, method=method, running=True)
    target_values = list_value(json_value(root, "target-container.json"), "target start container")
    final_values = list_value(json_value(root, "final-target-container.json"), "final target container")
    require(len(target_values) == len(final_values) == 1, "target container identity is ambiguous")
    validate_worker(
        target_values[0], image=target_image, service="order-v2", version=target_version,
        method=method, running=True,
    )
    validate_worker(
        final_values[0], image=target_image, service="order-v2", version=target_version,
        method=method, running=True,
    )
    target_id = target.get("Id")
    require(
        target_values[0].get("Id") == target_id == final_values[0].get("Id")
        and target_values[0].get("Image") == target_image == final_values[0].get("Image"),
        "target inspections do not name the same compatible container",
    )
    start = object_value(json_value(root, "target-start.json"), "target start marker")
    exact_fields(start, {"container_id", "started_at", "after_history_sequence"}, "target start marker")
    started_at = timestamp(start.get("started_at"), "target start time")
    require(
        start.get("container_id") == target_id
        and start.get("started_at") == target.get("State", {}).get("StartedAt")
        and start.get("after_history_sequence") == activation_sequence
        and started_at <= target_created,
        "target start is not bound to compatible provenance/activation",
    )


def validate_cli_path(root: Path, invocation_id: str, order_id: str) -> None:
    require(read(root, "exit-status.txt") == b"0\n", "compatible runner did not complete")
    require(read(root, "resume-exit-status.txt") == b"0\n", "official resume command failed")
    require(read(root, "terminal-observed.txt") == b"1\n", "terminal Restate state was not observed")
    require(read(root, "source-pause.stderr") == b"" and read(root, "resume.stderr") == b"", "official pause/resume emitted an error")
    pause = read(root, "source-pause.stdout").decode("utf-8", errors="strict")
    resume = read(root, "resume.stdout").decode("utf-8", errors="strict")
    target = f"order-workflow/{order_id}/run"
    require(pause.count(invocation_id) == 1 and target in pause and "[OK]: Paused 1 invocations" in pause, "official pause evidence differs")
    require(resume.count(invocation_id) == 1 and target in resume and "[OK]: Resumed 1 invocations" in resume, "official resume evidence differs")


def validate_requirement(value: Any, label: str) -> dict[str, Any]:
    requirement = object_value(value, label)
    expected = {
        "id": "food-ordering-v1",
        "results": {"paid": 1, "delivered": 1},
        "capacities": {"charge": 1},
        "kinds": {
            "charge-v1": {
                "costs": {"charge": 1}, "produces": {"paid": 1},
                "retry_safe": False, "queryable": True,
                "target": "http://payment:8081/v1/charge", "method": "POST",
                "response_classifier": "operation-receipt-v1",
                "query_target": "http://payment:8081/v1/query", "query_method": "POST",
                "query_classifier": "operation-observation-v1",
            },
            "finish": {
                "costs": {}, "produces": {"delivered": 1},
                "retry_safe": True, "queryable": False,
                "target": "http://completion:8081/v1/complete", "method": "POST",
                "response_classifier": "operation-receipt-v1",
            },
        },
    }
    require(requirement == expected, f"{label} differs")
    return requirement


def validate_history_view(value: Any, label: str) -> list[dict[str, Any]]:
    events = list_value(value, label)
    previous = ZERO_HASH
    for index, item in enumerate(events, 1):
        event = object_value(item, f"{label} event {index}")
        exact_fields(event, {"sequence", "operation", "data", "previous_hash", "hash"}, f"{label} event {index}")
        require(
            event.get("sequence") == index
            and isinstance(event.get("operation"), str) and event["operation"]
            and event.get("previous_hash") == previous
            and isinstance(event.get("data"), dict),
            f"{label} event {index} envelope differs",
        )
        encoded = json.dumps(event["data"], separators=(",", ":"), ensure_ascii=True).encode()
        expected = BASE._event_hash(index, previous, event["operation"], encoded)
        require(event.get("hash") == expected, f"{label} event {index} hash differs")
        previous = expected
    require(events, f"{label} is empty")
    return events


def base64_json(value: Any, label: str) -> dict[str, Any]:
    try:
        raw = base64.b64decode(value, validate=True)
    except (TypeError, ValueError) as error:
        raise EvidenceError(f"{label} is not canonical base64") from error
    require(base64.b64encode(raw).decode() == value, f"{label} is not canonical base64")
    try:
        return object_value(BASE._loads(raw, label), label)
    except BASE.EvidenceError as error:
        raise EvidenceError(str(error)) from error


def validate_proposed_control(
    root: Path,
    runtime_root: Path,
    requirement: dict[str, Any],
    order_id: str,
    payment_id: str,
    completion_id: str,
    payment_record: dict[str, Any],
    completion_record: dict[str, Any],
) -> int:
    cut_history = validate_history_view(json_value(root, "control-history-at-cut.json"), "cut control History")
    final_history = validate_history_view(json_value(root, "final-control-history.json"), "final control History")
    require(
        [event["operation"] for event in cut_history]
        == ["rule.activated", "operation.prepared", "operation.phase", "operation.phase"]
        and [event["operation"] for event in final_history]
        == ["rule.activated", "operation.prepared", "operation.phase", "operation.phase", "rule.activated", "operation.prepared", "operation.phase", "operation.phase"]
        and final_history[:4] == cut_history,
        "proposed control History lifecycle differs",
    )
    before = object_value(json_value(root, "control-before-pause.json"), "pre-pause control state")
    at_cut = object_value(json_value(root, "control-at-cut.json"), "cut control state")
    require(before == at_cut, "control state changed during the paused cut")
    exact_fields(at_cut, {"history", "requirement", "rule", "operations"}, "cut control state")
    require(
        at_cut.get("history") == {"sequence": 4, "hash": cut_history[-1]["hash"]}
        and at_cut.get("requirement") == requirement
        and at_cut.get("rule", {}).get("version") == 1
        and at_cut.get("rule", {}).get("allow") == ["finish"],
        "cut control state is not bound to the settled payment",
    )
    operations = object_value(at_cut.get("operations"), "cut Operations")
    require(set(operations) == {payment_id}, "cut control state omitted or added an Operation")
    payment = object_value(operations[payment_id], "payment Operation")
    payment_body = {"order_id": order_id, "amount": 42}
    require(
        payment.get("id") == payment_id
        and payment.get("domain") == "restate-order-workflow"
        and payment.get("kind") == "charge-v1"
        and payment.get("rule_version") == 1
        and payment.get("phase") == "succeeded"
        and payment.get("result_hash") == payment_record["result_hash"]
        and payment.get("remote_reference") == payment_record["remote_reference"]
        and payment.get("status_code") == 200
        and base64_json(payment.get("request_body"), "payment request body") == payment_body,
        "settled payment Operation differs from the provider fact",
    )

    source_certificate = object_value(json_value(root, "certificate-v1.json"), "source Certificate")
    source_active = object_value(json_value(root, "active-v1.json"), "source activation")
    require(
        source_certificate == cut_history[0].get("data", {}).get("certificate")
        and source_certificate.get("decision") == "activate"
        and source_certificate.get("history") == {"sequence": 0, "hash": ZERO_HASH}
        and source_certificate.get("rule", {}).get("allow") == ["charge-v1", "finish"]
        and source_active.get("history") == {"sequence": 1, "hash": cut_history[0]["hash"]},
        "source Certificate activation differs",
    )

    certificate = object_value(json_value(root, "certificate-compatible.json"), "compatible Certificate")
    certificate_state = object_value(json_value(root, "certificate-compatible-state.json"), "compatible Certificate state")
    recorded_verdict = object_value(json_value(root, "certificate-compatible-verdict.json"), "compatible Certificate verdict")
    require(
        certificate.get("schema") == 1
        and certificate.get("decision") == "activate"
        and certificate.get("history") == {"sequence": 4, "hash": cut_history[-1]["hash"]}
        and certificate.get("from_rule") == 1
        and certificate.get("requirement") == requirement
        and certificate.get("rule", {}).get("version") == 2
        and certificate.get("rule", {}).get("allow") == ["finish"],
        "compatible Certificate binding or Rule differs",
    )
    require(
        certificate_state == {
            "schema": 1,
            "history": certificate["history"],
            "from_rule": 1,
            "settled": {"used": {"charge": 1}, "results": {"paid": 1}},
            "open_operations": {},
        },
        "compatible Certificate state omitted settled progress",
    )
    command = [
        "go", "run", "./cmd/check-certificate", "-state",
        str(root / "certificate-compatible-state.json"), "-certificate",
        str(root / "certificate-compatible.json"),
    ]
    completed = subprocess.run(
        command, cwd=runtime_root, check=False, capture_output=True, text=True, timeout=120
    )
    require(completed.returncode == 0, f"fresh compatible Certificate check failed: {completed.stderr.strip()}")
    try:
        fresh_verdict = object_value(BASE._loads(completed.stdout.encode(), "fresh Certificate verdict"), "fresh Certificate verdict")
    except BASE.EvidenceError as error:
        raise EvidenceError(str(error)) from error
    require(
        fresh_verdict == recorded_verdict
        and fresh_verdict == {
            "valid": True, "decision": "activate", "history_sequence": 4,
            "history_hash": cut_history[-1]["hash"], "rule_version": 2,
        },
        "fresh compatible Certificate verdict differs",
    )

    require(final_history[4].get("data", {}).get("certificate") == certificate, "compatible Certificate was not activated at event 5")
    active = object_value(json_value(root, "active-compatible.json"), "compatible activation")
    require(
        active.get("history") == {"sequence": 5, "hash": final_history[4]["hash"]}
        and active.get("requirement") == requirement
        and active.get("rule") == certificate.get("rule")
        and active.get("operations") == operations,
        "compatible Rule activation state differs",
    )
    final_state = object_value(json_value(root, "final-control-state.json"), "final control state")
    require(
        final_state.get("history") == {"sequence": 8, "hash": final_history[-1]["hash"]}
        and final_state.get("requirement") == requirement
        and final_state.get("rule") == certificate.get("rule"),
        "final control head or Rule differs",
    )
    final_operations = object_value(final_state.get("operations"), "final Operations")
    require(set(final_operations) == {payment_id, completion_id}, "final control state omitted or duplicated an Operation")
    require(final_operations[payment_id] == payment, "settled payment Operation changed after activation")
    completion = object_value(final_operations[completion_id], "completion Operation")
    completion_body = {"order_id": order_id, "status": "DELIVERED", "closure_version": "compatible-v2"}
    require(
        completion.get("id") == completion_id
        and completion.get("domain") == "restate-order-workflow"
        and completion.get("kind") == "finish"
        and completion.get("rule_version") == 2
        and completion.get("phase") == "succeeded"
        and completion.get("result_hash") == completion_record["result_hash"]
        and completion.get("remote_reference") == completion_record["remote_reference"]
        and completion.get("status_code") == 200
        and base64_json(completion.get("request_body"), "completion request body") == completion_body,
        "completion Operation differs from compatible provider fact",
    )
    prepared = object_value(final_history[5].get("data", {}).get("operation"), "prepared completion Operation")
    require(
        prepared.get("id") == completion_id and prepared.get("phase") == "prepared"
        and final_history[6].get("data", {}).get("id") == completion_id
        and final_history[6].get("data", {}).get("update", {}).get("phase") == "dispatched"
        and final_history[7].get("data", {}).get("id") == completion_id
        and final_history[7].get("data", {}).get("update", {}).get("phase") == "succeeded",
        "completion was not prepared and settled after compatible activation",
    )
    return 5


def infer_method(root: Path) -> str:
    listing = object_value(json_value(root, "deployments.json"), "deployment listing")
    methods = {
        item.get("metadata", {}).get("method")
        for item in list_value(listing.get("deployments"), "deployment listing")
        if isinstance(item, dict) and isinstance(item.get("metadata"), dict)
    }
    require(len(methods) == 1 and next(iter(methods)) in {"proposed", "native"}, "compatible method is ambiguous")
    return str(next(iter(methods)))


def check_evidence(path: Path, runtime_root: Path, expected_method: str | None = None) -> dict[str, Any]:
    root = evidence_root(path)
    runtime_root = runtime_root.resolve(strict=True)
    method = infer_method(root)
    require(expected_method is None or method == expected_method, "evidence method differs from requested method")
    build_bytes = read(root, "build.env")
    build = parse_build_env(build_bytes)
    versions, images, runner_hash = validate_runtime_inputs(root)
    require(
        images["RESTATE_EXAMPLES_ARCHIVE_SHA256"] == build["UPSTREAM_ARCHIVE_SHA256"],
        "external archive digest differs between images.env and build.env",
    )
    order, order_id = validate_order(root)
    run_metadata = validate_run_metadata(
        root, method, order, build, build_bytes, versions, runner_hash
    )
    source_submit = object_value(json_value(root, "source-submit.json"), "source submit")
    exact_fields(source_submit, {"invocationId", "status"}, "source submit")
    require(source_submit.get("status") == "Accepted", "source invocation was not accepted")
    submit_id = source_submit.get("invocationId")
    require(isinstance(submit_id, str), "source invocation identity is absent")
    source_deployment, target_deployment, target_created = deployment_pair(root, build, method)
    invocation_id, created_at, _ = validate_cut_and_final(
        root, order_id, submit_id, source_deployment, target_deployment
    )
    payment_id, completion_id, payment_record, completion_record = validate_provider_evidence(root, order_id)

    source_requirement = validate_requirement(json_value(root, "requirement-source.json"), "source Requirement")
    target_requirement = validate_requirement(json_value(root, "requirement-target.json"), "target Requirement")
    require(source_requirement == target_requirement, "compatible edit changed the Requirement")
    require(read(root, "requirement-source.json") == read(root, "requirement-target.json"), "compatible Requirement bytes differ")

    proposed_files = {
        "control-before-pause.json", "control-at-cut.json", "control-history-at-cut.json",
        "certificate-v1.json", "active-v1.json", "certificate-compatible.json",
        "certificate-compatible-state.json", "certificate-compatible-verdict.json",
        "active-compatible.json", "final-control-state.json", "final-control-history.json",
    }
    if method == "proposed":
        activation_sequence = validate_proposed_control(
            root, runtime_root, source_requirement, order_id, payment_id, completion_id,
            payment_record, completion_record,
        )
    else:
        require(not any((root / name).exists() for name in proposed_files), "native lane contains proposed control evidence")
        activation_sequence = 0

    validate_containers(root, build, method, target_created, activation_sequence)
    validate_cli_path(root, invocation_id, order_id)
    target_log = read(root, "target-v2.log").decode("utf-8", errors="replace")
    require(
        f"order-workflow/{order_id}/run][{invocation_id}] INFO: Replaying invocation." in target_log
        and f"[{order_id}] Recording terminal delivery" in target_log
        and "Found a mismatch between the code paths" not in target_log,
        "compatible target did not replay and complete cleanly",
    )

    required_files = {
        "build.env", "versions.env", "images.env", "runner.sha256", "run-metadata.json",
        "order.json", "order.sha256", "source-submit.json", "expected-completion.json",
        "deployment-v1.json", "deployment-compatible.json", "deployments.json",
        "cut-status.json", "cut-status-after-window.json", "cut-journal.json",
        "cut-journal-after-window.json", "cut-workflow-state.json",
        "cut-workflow-state-after-window.json", "final-status.json", "final-invocations.json",
        "final-journal.json", "final-workflow-state.json", "payment-before-pause.json",
        "payment-at-cut.json", "payment-after-cut-window.json", "final-payment-stats.json",
        "completion-before-pause.json", "completion-at-cut.json",
        "completion-after-cut-window.json", "final-completion-stats.json",
        "payment-at-cut.history", "completion-at-cut.history",
        "payment-after-cut-window.history", "completion-after-cut-window.history",
        "payment.history", "completion.history", "source-v1.log", "source-container-before-removal.json",
        "source-container-removal.txt", "source-container-after-removal.json",
        "source-container-after-removal.stderr", "source-container-after-removal.exit-status.txt",
        "target-container.json", "final-target-container.json", "target-start.json",
        "containers.raw.json", "source-pause.stdout", "source-pause.stderr",
        "resume.stdout", "resume.stderr", "resume-exit-status.txt", "terminal-observed.txt",
        "exit-status.txt", "target-v2.log", "requirement-source.json", "requirement-target.json",
    }
    if method == "proposed":
        required_files |= proposed_files
    # observed.json is intentionally excluded: the verdict is reconstructed
    # exclusively from the artifacts above.
    artifact_hashes = {name: sha256(read(root, name)).hexdigest() for name in sorted(required_files)}
    evidence_digest = sha256(
        json.dumps(artifact_hashes, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "schema": 1,
        "valid": True,
        "cell": "compatible",
        "method": method,
        "runner_sha256": runner_hash,
        "restate_cli_image": versions["RESTATE_CLI_IMAGE"],
        "restate_server_image": versions["RESTATE_SERVER_IMAGE"],
        "delivery_delay_ms": run_metadata["delivery_delay_ms"],
        "order_id": order_id,
        "invocation_id": invocation_id,
        "created_at": created_at,
        "source_deployment_id": source_deployment,
        "target_deployment_id": target_deployment,
        "payment_operation_id": payment_id,
        "completion_operation_id": completion_id,
        "same_invocation": True,
        "sleep_notification_only_while_paused": True,
        "source_removed": True,
        "target_repin": True,
        "runtime_status": "completed",
        "business_status": "DELIVERED",
        "payment_deliveries": 1,
        "payment_commits": 1,
        "completion_deliveries": 1,
        "completion_commits": 1,
        "duplicate_external_effect": False,
        "resubmitted": False,
        "control_activation_sequence": activation_sequence,
        "artifact_count": len(artifact_hashes),
        "evidence_digest": evidence_digest,
    }


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--evidence", required=True, type=Path, help="compatible attempt or results directory")
    value.add_argument("--method", choices=("proposed", "native"), help="optional expected lane")
    value.add_argument(
        "--runtime-root", type=Path, default=Path(__file__).resolve().parents[2],
        help="runtime source root containing cmd/check-certificate",
    )
    return value


def main() -> int:
    args = parser().parse_args()
    try:
        result = check_evidence(args.evidence, args.runtime_root, args.method)
    except (EvidenceError, BASE.EvidenceError, OSError, subprocess.SubprocessError) as error:
        print(f"check-compatible: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
