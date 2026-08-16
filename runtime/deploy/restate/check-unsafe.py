#!/usr/bin/env python3
"""Independently validate one Restate history-dependent unsafe-edit run.

The runner and observed.json are not imported.  The verdict is reconstructed
from official Restate SQL queries, append-only provider records, container and
resolved-Compose identity, the frozen target build, and independently checked
Certificates in the proposed lane.
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
from typing import Any

import yaml


SCRIPT_DIR = Path(__file__).resolve().parent
BASE_PATH = SCRIPT_DIR / "check.py"
SPEC = importlib.util.spec_from_file_location("restate_base_check", BASE_PATH)
assert SPEC is not None and SPEC.loader is not None
BASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BASE)

RUNNER = SCRIPT_DIR / "run-unsafe-case.sh"
DOCKERFILE = SCRIPT_DIR / "Dockerfile.worker"
PROPOSED_OVERLAY = SCRIPT_DIR / "compose-unsafe-proposed.yaml"
NATIVE_OVERLAY = SCRIPT_DIR / "compose-unsafe-native.yaml"
PROPOSED_PATCH = SCRIPT_DIR / "patches" / "unsafe-completion-v2.patch"
NATIVE_PATCH = SCRIPT_DIR / "patches" / "unsafe-completion-direct-v2.patch"
UPSTREAM_COMMIT = "2d429daae784d20982691fb31431702b4ad30a6b"
RESTATE_IMAGE = (
    "docker.io/restatedev/restate:1.7.3@"
    "sha256:1856961b7a16d1b00131e5704231b79e0334703df074a31867ea8ce2110d5cfa"
)
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
ORDER_ID = re.compile(r"[A-Za-z0-9._-]{1,128}\Z")
INVOCATION_ID = re.compile(r"inv_[A-Za-z0-9]+\Z")
DEPLOYMENT_ID = re.compile(r"dp_[A-Za-z0-9]+\Z")
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")

FROZEN_COMMON = {
    "UPSTREAM_ARCHIVE_SHA256": "9422ccd6d5b0a9035bd207b6642f6d8decaac58839dd8abee8691b384bdd825a",
    "APP_LOCK_SHA256": "8b5462348ad0bfde8e98f6221e5bd37e69bc2f8aceaffb66306ec1b71bef3bf7",
    "V1_CONTEXT_SHA256": "46075311a51940e5be1d369146dca4c182a4bec08c5aac66d04fa6462af794ae",
    "NATIVE_V1_CONTEXT_SHA256": "7905c3adb9eb17f9ad1a04413a2e9d6cf45e69992387137638aa84be47eb2d0c",
    "V1_PROGRAM_SHA256": "308fd539f4b612badd5d461436c2b6fae3db67dd8caea2727d2d82caa7379075",
    "UNSAFE_V2_WORKFLOW_SHA256": "7557b0cdd25d41a4e71688d0b0ec5dbbdb084f3ff33651629575aa5e91635295",
    "UNSAFE_V2_COMPILED_SHA256": "b113e59460e7cf951c0358413b88da1d1d09c0ae6039fc24bb19f2c11fb982cc",
    "NATIVE_UNSAFE_V2_COMPILED_SHA256": "b113e59460e7cf951c0358413b88da1d1d09c0ae6039fc24bb19f2c11fb982cc",
}
FROZEN_LANE = {
    "proposed": {
        "UNSAFE_V2_PATCH_SHA256": "40b9bcddfd2204d6a7ae0b5fe6aabd2b7d6cb2f98e9647088280b955b133c88e",
        "UNSAFE_V2_CONTEXT_SHA256": "e794c35c02eead0261766380bf678737474e8ccae1a2df9ffc0b5a5f97953cca",
        "UNSAFE_V2_COMPLETION_CLIENT_SHA256": "3e0bb63cf900dccd171d60b06b1199627ec647b3f14ecf913eb7d8b1c6e49d8a",
    },
    "native": {
        "NATIVE_UNSAFE_V2_PATCH_SHA256": "a8c33d07e6cf8b037c932f910d25d6a5a73ed3a8936c900361aea0297c8f5c5b",
        "NATIVE_UNSAFE_V2_CONTEXT_SHA256": "7fa6a2c1e720cddb4c68547da7e5dbf57ee0308c3073d7fdd8ea495adf3d2827",
        "NATIVE_UNSAFE_V2_COMPLETION_CLIENT_SHA256": "88913a7ec89a7d230c1499f95183c655c455a11b581f1d628b915c95d4783274",
        "PROVIDER_DIRECT_PATCH_SHA256": "b5ab1a66c0a9b140d1843c2e2204d1e4447c22754afa46159058312b0764fe85",
        "NATIVE_PAYMENT_CLIENT_SHA256": "8abb6789492ad8e3c82142ab783bee646403f1acafd4c625c54602d9f8af5c98",
        "NATIVE_COMPLETION_CLIENT_SHA256": "50c7fb346d842de9331b4fa255306fc3f429bd05d410683b43a6a28a0920b017",
        "NATIVE_V1_COMPILED_SHA256": "14e1423c71db968449826b6d6d7f8d611316173218fc49e6edded20d9e3e19e3",
    },
}


class EvidenceError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceError(message)


def root_path(path: Path) -> Path:
    root = path.resolve(strict=True)
    if (root / "results").is_dir() and not (root / "run-metadata.json").exists():
        root = (root / "results").resolve(strict=True)
    require(root.is_dir(), "evidence root is not a directory")
    return root


def read(root: Path, name: str, maximum: int = 64 << 20) -> bytes:
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


def jvalue(root: Path, name: str) -> Any:
    try:
        return BASE._loads(read(root, name), name)
    except BASE.EvidenceError as error:
        raise EvidenceError(str(error)) from error


def obj(value: Any, label: str) -> dict[str, Any]:
    require(isinstance(value, dict), f"{label} must be an object")
    return value


def arr(value: Any, label: str) -> list[Any]:
    require(isinstance(value, list), f"{label} must be an array")
    return value


def exact(value: dict[str, Any], fields: set[str], label: str) -> None:
    require(set(value) == fields, f"{label} fields changed")


def one_row(value: Any, label: str) -> dict[str, Any]:
    wrapper = obj(value, label)
    exact(wrapper, {"rows"}, label)
    rows = arr(wrapper["rows"], label + " rows")
    require(len(rows) == 1 and isinstance(rows[0], dict), f"{label} must contain one row")
    return rows[0]


def timestamp(value: Any, label: str) -> datetime:
    require(isinstance(value, str) and value, f"{label} is not a timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise EvidenceError(f"{label} is not a timestamp") from error
    require(parsed.tzinfo is not None, f"{label} has no timezone")
    return parsed


def parse_env(data: bytes) -> dict[str, str]:
    try:
        text = data.decode()
    except UnicodeDecodeError as error:
        raise EvidenceError("build.env is not UTF-8") from error
    result: dict[str, str] = {}
    for number, line in enumerate(text.splitlines(), 1):
        require(line and "=" in line and not line.startswith("#"), f"build.env line {number} is invalid")
        key, value = line.split("=", 1)
        require(re.fullmatch(r"[A-Z][A-Z0-9_]*", key) is not None and key not in result and value, f"build.env line {number} is invalid")
        result[key] = value
    return result


def expected_requirements() -> tuple[dict[str, Any], dict[str, Any]]:
    source = {
        "id": "food-ordering-unsafe-source-v1", "results": {"paid": 1, "delivered": 1},
        "capacities": {"approval": 1}, "kinds": {
            "charge-v1": {
                "costs": {"approval": 1}, "produces": {"paid": 1}, "retry_safe": False,
                "queryable": True, "target": "http://payment:8081/v1/charge", "method": "POST",
                "response_classifier": "operation-receipt-v1", "query_target": "http://payment:8081/v1/query",
                "query_method": "POST", "query_classifier": "operation-observation-v1",
            },
            "finish-v1": {
                "costs": {}, "produces": {"delivered": 1}, "retry_safe": True, "queryable": False,
                "target": "http://completion:8081/v1/complete", "method": "POST",
                "response_classifier": "operation-receipt-v1",
            },
        },
    }
    target = {
        "id": "food-ordering-unsafe-target-v2", "results": {"paid": 1, "delivered": 1},
        "capacities": {"approval": 1}, "kinds": {
            "charge-v1": {"costs": {"approval": 1}, "produces": {"paid": 1}, "retry_safe": False, "queryable": False},
            "finish-v1": {"costs": {}, "produces": {"delivered": 1}, "retry_safe": False, "queryable": False},
            "charge-v2": {
                "costs": {}, "produces": {"paid": 1}, "retry_safe": False, "queryable": True,
                "target": "http://payment:8081/v2/charge", "method": "POST",
                "response_classifier": "operation-receipt-v1", "query_target": "http://payment:8081/v1/query",
                "query_method": "POST", "query_classifier": "operation-observation-v1",
            },
            "finish-v2": {
                "costs": {"approval": 1}, "produces": {"delivered": 1}, "retry_safe": True,
                "queryable": False, "target": "http://completion:8081/v1/complete", "method": "POST",
                "response_classifier": "operation-receipt-v1",
            },
        },
    }
    return source, target


def validate_build_and_binding(root: Path, metadata: dict[str, Any], method: str) -> tuple[dict[str, str], str, str]:
    build_bytes = read(root, "build.env")
    build = parse_env(build_bytes)
    image_keys = {"ORDER_V1_IMAGE", "ORDER_UNSAFE_V2_IMAGE", "NATIVE_ORDER_V1_IMAGE", "NATIVE_ORDER_UNSAFE_V2_IMAGE", "SAFE_CHANGE_RUNTIME_IMAGE"}
    require(image_keys <= set(build), "build.env omitted unsafe images")
    for key in image_keys:
        require(IMAGE_ID.fullmatch(build[key]) is not None, f"{key} is not immutable")
    frozen = FROZEN_COMMON | FROZEN_LANE[method]
    for key, value in frozen.items():
        require(build.get(key) == value and HEX64.fullmatch(value) is not None, f"{key} differs from the frozen unsafe build")
    source_image = build["ORDER_V1_IMAGE" if method == "proposed" else "NATIVE_ORDER_V1_IMAGE"]
    target_image = build["ORDER_UNSAFE_V2_IMAGE" if method == "proposed" else "NATIVE_ORDER_UNSAFE_V2_IMAGE"]
    require(source_image != target_image, "source and unsafe target images are identical")
    require(metadata.get("source_image") == source_image and metadata.get("target_image") == target_image, "run metadata image identity differs")

    current_runner = RUNNER.read_bytes()
    runner_hash = sha256(current_runner).hexdigest()
    checksum = read(root, "runner.sha256").decode()
    require(checksum.split()[0] == runner_hash and checksum.endswith("run-unsafe-case.sh\n"), "runner checksum differs from current runner")
    require(metadata.get("runner_sha256") == runner_hash, "metadata runner hash differs")
    local_overlay = PROPOSED_OVERLAY if method == "proposed" else NATIVE_OVERLAY
    local_patch = PROPOSED_PATCH if method == "proposed" else NATIVE_PATCH
    for captured, local, label in (
        ("Dockerfile.worker", DOCKERFILE, "Dockerfile"),
        ("compose.unsafe.yaml", local_overlay, "unsafe overlay"),
        ("unsafe-target.patch", local_patch, "unsafe target patch"),
    ):
        require(read(root, captured) == local.read_bytes(), f"captured {label} differs from current source")
    binding = obj(metadata.get("target_binding"), "target binding")
    exact(binding, {"requirement_sha256", "patch_sha256", "dockerfile_sha256", "overlay_sha256"}, "target binding")
    require(binding == {
        "requirement_sha256": sha256(read(root, "clean-requirement-target.json")).hexdigest(),
        "patch_sha256": sha256(read(root, "unsafe-target.patch")).hexdigest(),
        "dockerfile_sha256": sha256(read(root, "Dockerfile.worker")).hexdigest(),
        "overlay_sha256": sha256(read(root, "compose.unsafe.yaml")).hexdigest(),
    }, "target binding does not match captured inputs")
    patch_key = "UNSAFE_V2_PATCH_SHA256" if method == "proposed" else "NATIVE_UNSAFE_V2_PATCH_SHA256"
    require(binding["patch_sha256"] == build[patch_key], "captured target patch differs from build provenance")
    return build, source_image, target_image


def load_compose(root: Path, name: str) -> dict[str, Any]:
    try:
        value = yaml.safe_load(read(root, name))
    except yaml.YAMLError as error:
        raise EvidenceError(f"{name} is invalid YAML") from error
    return obj(value, name)


def validate_compose(root: Path, method: str, source_image: str, target_image: str) -> tuple[dict[str, Any], dict[str, Any]]:
    clean = obj(load_compose(root, "clean-compose-config.yaml").get("services"), "clean services")
    main = obj(load_compose(root, "main-compose-config.yaml").get("services"), "main services")
    for services, label in ((clean, "clean"), (main, "main")):
        require(services.get("restate", {}).get("image") == RESTATE_IMAGE, f"{label} Restate image differs")
        require(services.get("order-v2", {}).get("image") == target_image, f"{label} target image differs")
    require(clean.get("order-v1", {}).get("image") == target_image, "clean run did not use target image")
    require(main.get("order-v1", {}).get("image") == source_image, "main run did not use source image")
    clean_env = obj(clean["order-v1"].get("environment"), "clean target environment")
    target_env = obj(main["order-v2"].get("environment"), "main target environment")
    require(clean_env == target_env, "clean and main target resolved environments differ")
    if method == "proposed":
        expected = {
            "RESTATE_DEBUG_LOGGING": "JOURNAL", "RESTAURANT_ENDPOINT": "http://restaurant-pos:5050",
            "KAFKA_BOOTSTRAP_SERVERS": "broker:29092", "SAFE_CHANGE_CONTROL_URL": "http://control:8787",
            "SAFE_CHANGE_PAYMENT_KIND": "charge-v2", "SAFE_CHANGE_PAYMENT_TARGET": "http://payment:8081/v2/charge",
            "SAFE_CHANGE_FINISH_KIND": "finish-v2", "SAFE_CHANGE_FINISH_TARGET": "http://completion:8081/v1/complete",
            "SAFE_CHANGE_OPERATION_TOKEN_FILE": "/operation-token/token",
        }
        require(clean_env == expected, "proposed target resolved environment differs")
        require("PAYMENT_ENDPOINT" not in clean_env and "COMPLETION_ENDPOINT" not in clean_env, "proposed target retained direct endpoints")
        control = obj(main.get("control"), "proposed control")
        require(control.get("command", [])[-1] == "-operation-kinds=charge-v1,finish-v1,charge-v2,finish-v2", "control kind whitelist differs")
        require(set(main["order-v2"].get("networks", {})) == {"application", "control"}, "proposed target network differs")
    else:
        expected = {
            "RESTATE_DEBUG_LOGGING": "JOURNAL", "RESTAURANT_ENDPOINT": "http://restaurant-pos:5050",
            "KAFKA_BOOTSTRAP_SERVERS": "broker:29092", "PAYMENT_ENDPOINT": "http://payment:8081/v2/charge",
            "COMPLETION_ENDPOINT": "http://completion:8081/v1/complete", "OPERATION_DOMAIN": "restate-order-workflow",
        }
        require(clean_env == expected, "native target resolved environment differs")
        require(not any(key.startswith("SAFE_CHANGE_") for key in clean_env), "native target retained proposed environment")
        require("control" not in clean and "control" not in main, "native compose included proposed control")
        require(set(main["order-v2"].get("networks", {})) == {"application", "effects"}, "native target network differs")
        require(not main["order-v2"].get("volumes"), "native target retained an Operation token mount")
    return clean, main


def stats(root: Path, name: str, expected: dict[str, Any]) -> dict[str, Any]:
    value = obj(jvalue(root, name), name)
    exact(value, {"deliveries", "commits", "paths"}, name)
    require(value == expected, f"{name} differs")
    return value


def records(root: Path, name: str) -> list[dict[str, Any]]:
    try:
        return BASE._records(root / name, name)
    except BASE.EvidenceError as error:
        raise EvidenceError(str(error)) from error


def container_services(root: Path, name: str) -> dict[str, dict[str, Any]]:
    values = arr(jvalue(root, name), name)
    result: dict[str, dict[str, Any]] = {}
    for value in values:
        item = obj(value, name + " container")
        config = obj(item.get("Config"), name + " config")
        labels = obj(config.get("Labels"), name + " labels")
        service = labels.get("com.docker.compose.service")
        require(isinstance(service, str) and service and service not in result, f"{name} service identity differs")
        result[service] = item
    return result


def env_map(container: dict[str, Any]) -> dict[str, str]:
    values = obj(container.get("Config"), "container config").get("Env")
    result: dict[str, str] = {}
    for value in arr(values, "container environment"):
        require(isinstance(value, str) and "=" in value, "container environment entry differs")
        key, item = value.split("=", 1)
        require(key not in result, "duplicate container environment")
        result[key] = item
    return result


def contains_environment(actual: dict[str, str], expected: dict[str, Any]) -> bool:
    return all(isinstance(value, str) and actual.get(key) == value for key, value in expected.items())


def validate_container_identity(root: Path, method: str, target_image: str, clean_cfg: dict[str, Any], main_cfg: dict[str, Any]) -> None:
    clean = arr(jvalue(root, "clean-target-container.json"), "clean target container")
    require(len(clean) == 1 and isinstance(clean[0], dict), "clean target container is ambiguous")
    require(clean[0].get("Image") == target_image and clean[0].get("State", {}).get("Running") is True, "clean target immutable image differs")
    require(contains_environment(env_map(clean[0]), obj(clean_cfg["order-v1"].get("environment"), "clean config environment")), "clean target runtime environment differs")
    clean_services = container_services(root, "clean-containers.raw.json")
    main_services = container_services(root, "main-containers.raw.json")
    if method == "proposed":
        require("control" in clean_services and "control" in main_services, "proposed control was absent")
        require("order-v2" not in main_services, "refused target container exists")
        source = arr(jvalue(root, "main-final-source-container.json"), "final source container")
        require(len(source) == 1 and source[0].get("Image") == main_cfg["order-v1"]["image"] and source[0].get("State", {}).get("Running") is True, "proposed did not retain source worker")
    else:
        require("control" not in clean_services and "control" not in main_services, "native run started proposed control")
        require(read(root, "main-source-after-removal.exit-status.txt") == b"1\n", "native source remained inspectable after removal")
        target = arr(jvalue(root, "main-final-target-container.json"), "final target container")
        require(len(target) == 1 and target[0].get("Image") == target_image and target[0].get("State", {}).get("Running") is True, "native target immutable image differs")
        require(contains_environment(env_map(target[0]), obj(main_cfg["order-v2"].get("environment"), "main target config environment")), "native target runtime environment differs")
        require("order-v1" not in main_services and "order-v2" in main_services, "native source/target fencing differs")


def journal_rows(root: Path, name: str) -> list[dict[str, Any]]:
    wrapper = obj(jvalue(root, name), name)
    exact(wrapper, {"rows"}, name)
    rows = arr(wrapper["rows"], name + " rows")
    for index, value in enumerate(rows):
        row = obj(value, f"{name} row {index}")
        require(row.get("index") == index and isinstance(row.get("entry_type"), str), f"{name} row index differs")
        require(isinstance(row.get("raw"), str) and isinstance(row.get("raw_length"), int), f"{name} raw evidence differs")
        try:
            raw = bytes.fromhex(row["raw"])
        except ValueError as error:
            raise EvidenceError(f"{name} row raw is not hex") from error
        require(len(raw) == row["raw_length"], f"{name} row raw length differs")
    return rows


def shape(rows: list[dict[str, Any]]) -> list[tuple[int, str, str]]:
    return [(row["index"], row["entry_type"], str(row.get("name", ""))) for row in rows]


def validate_restate(root: Path, method: str, clean_order: str, main_order: str) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    clean_submit = obj(jvalue(root, "clean-submit.json"), "clean submit")
    main_submit = obj(jvalue(root, "main-submit.json"), "main submit")
    clean_id, main_id = clean_submit.get("invocationId"), main_submit.get("invocationId")
    require(isinstance(clean_id, str) and INVOCATION_ID.fullmatch(clean_id) is not None, "clean invocation identity differs")
    require(isinstance(main_id, str) and INVOCATION_ID.fullmatch(main_id) is not None and main_id != clean_id, "main invocation identity differs")
    clean_final = one_row(jvalue(root, "clean-final-status.json"), "clean final status")
    main_cut = one_row(jvalue(root, "main-cut-status.json"), "main cut status")
    main_after = one_row(jvalue(root, "main-cut-status-after-window.json"), "main stable cut status")
    main_final = one_row(jvalue(root, "main-final-status.json"), "main final status")
    require(clean_final.get("id") == clean_id and clean_final.get("target") == f"order-workflow/{clean_order}/run" and clean_final.get("status") == "completed", "clean target workflow did not complete")
    require(main_cut.get("id") == main_id and main_cut.get("target") == f"order-workflow/{main_order}/run" and main_cut.get("status") == "paused", "main cut is not the paused source invocation")
    require(main_after.get("id") == main_id and main_after.get("status") == "paused", "main cut did not remain paused")
    require(main_after.get("journal_size") == main_cut.get("journal_size") + 1, "paused cut did not append exactly one entry")
    require({k: v for k, v in main_after.items() if k not in {"journal_size", "modified_at"}} == {k: v for k, v in main_cut.items() if k not in {"journal_size", "modified_at"}}, "paused invocation changed beyond journal size/time")
    require(timestamp(main_after.get("modified_at"), "stable cut modification") > timestamp(main_cut.get("modified_at"), "cut modification"), "stable cut timestamp did not advance")
    require(main_final.get("id") == main_id and main_final.get("target") == main_cut.get("target") and main_final.get("created_at") == main_cut.get("created_at") and main_final.get("status") == "completed", "main invocation lineage did not complete")
    require(one_row(jvalue(root, "main-final-invocations.json"), "main final invocation set") == main_final, "main invocation query admitted another lineage")

    cut_rows = journal_rows(root, "main-cut-journal.json")
    after_rows = journal_rows(root, "main-cut-journal-after-window.json")
    expected_cut = [
        (0, "Command: Input", ""), (1, "Command: SetState", ""),
        (2, "Command: Run", "payment"), (3, "Notification: Run", ""),
        (4, "Command: SetState", ""), (5, "Command: Sleep", ""),
    ]
    require(shape(cut_rows) == expected_cut, "main cut is not the completed-payment future-only cut")
    require(after_rows[:-1] == cut_rows and len(after_rows) == 7, "paused journal rewrote its cut")
    notice = after_rows[-1]
    require(notice.get("entry_type") == "Notification: Sleep" and notice.get("raw") == "08022200" and notice.get("raw_length") == 4, "paused cut appended a non-matching Sleep notification")
    require(jvalue(root, "main-cut-workflow-state.json") == jvalue(root, "main-cut-workflow-state-after-window.json"), "paused workflow state changed")
    cut_state = one_row(jvalue(root, "main-cut-workflow-state.json"), "main cut workflow state")
    require(cut_state.get("service_key") == main_order and cut_state.get("key") == "status" and cut_state.get("value_utf8") == '"SCHEDULED"', "main cut business state differs")

    final_rows = journal_rows(root, "main-final-journal.json")
    require(final_rows[:7] == after_rows, "replacement/resume rewrote the stable cut")
    require(len([row for row in final_rows if row.get("entry_type") == "Command: Run" and row.get("name") == "payment"]) == 1, "main journal changed payment count")
    require(len([row for row in final_rows if row.get("entry_type") == "Command: Run" and row.get("name") == "completion"]) == 1, "main journal does not contain one completion")
    require(final_rows[-1].get("entry_type") == "Command: Output", "main journal has no successful terminal output")
    clean_rows = journal_rows(root, "clean-final-journal.json")
    require(len([row for row in clean_rows if row.get("entry_type") == "Command: Run" and row.get("name") == "payment"]) == 1 and len([row for row in clean_rows if row.get("entry_type") == "Command: Run" and row.get("name") == "completion"]) == 1 and clean_rows[-1].get("entry_type") == "Command: Output", "clean target did not execute both external closures")
    for name, order in (("clean-final-workflow-state.json", clean_order), ("main-final-workflow-state.json", main_order)):
        row = one_row(jvalue(root, name), name)
        require(row.get("service_key") == order and row.get("key") == "status" and row.get("value_utf8") == '"DELIVERED"', f"{name} is not DELIVERED")
    return clean_id, main_id, main_cut, main_final


def expected_completion(order: str, closure: str | None) -> tuple[dict[str, str], bytes]:
    value: dict[str, str] = {"order_id": order, "status": "DELIVERED"}
    if closure is not None:
        value["closure_version"] = closure
    body = json.dumps(value, separators=(",", ":")).encode()
    return {
        "body_base64": base64.b64encode(body).decode(),
        "provider_request_hash": sha256(b"POST\0/v1/complete\0" + body).hexdigest(),
    }, body


def validate_providers(root: Path, method: str, clean_order: str, main_order: str) -> tuple[dict[str, Any], dict[str, Any]]:
    one_v2 = {"deliveries": 1, "commits": 1, "paths": {"/v2/charge": 1}}
    one_v1 = {"deliveries": 1, "commits": 1, "paths": {"/v1/charge": 1}}
    completion_one = {"deliveries": 1, "commits": 1, "paths": {"/v1/complete": 1}}
    completion_zero = {"deliveries": 0, "commits": 0, "paths": {}}
    stats(root, "clean-final-payment-stats.json", one_v2)
    stats(root, "clean-final-completion-stats.json", completion_one)
    for name in ("main-payment-before-pause.json", "main-payment-at-cut.json", "main-payment-after-window.json", "main-final-payment-stats.json"):
        stats(root, name, one_v1)
    for name in ("main-completion-before-pause.json", "main-completion-at-cut.json", "main-completion-after-window.json"):
        stats(root, name, completion_zero)
    stats(root, "main-final-completion-stats.json", completion_one)
    clean_payment, clean_completion = records(root, "clean-payment.history"), records(root, "clean-completion.history")
    main_cut_payment, main_cut_completion = records(root, "main-at-cut-payment.history"), records(root, "main-at-cut-completion.history")
    main_payment, main_completion = records(root, "main-payment.history"), records(root, "main-completion.history")
    require(len(clean_payment) == len(clean_completion) == len(main_cut_payment) == len(main_payment) == len(main_completion) == 1, "provider record count differs")
    require(main_cut_completion == [], "completion occurred before the edit decision")
    require(clean_payment[0].get("path") == "/v2/charge" and main_payment[0].get("path") == main_cut_payment[0].get("path") == "/v1/charge", "payment path evidence differs")
    require(main_payment == main_cut_payment, "main payment record changed after the cut")
    clean_expected, _ = expected_completion(clean_order, "unsafe-v2")
    main_expected, _ = expected_completion(main_order, None if method == "proposed" else "unsafe-v2")
    require(jvalue(root, "clean-expected-completion.json") == clean_expected, "clean expected completion was not independently reproducible")
    require(jvalue(root, "main-expected-completion.json") == main_expected, "main expected completion was not independently reproducible")
    require(clean_completion[0].get("path") == "/v1/complete" and clean_completion[0].get("request_hash") == clean_expected["provider_request_hash"], "clean unsafe-v2 completion marker differs")
    require(main_completion[0].get("path") == "/v1/complete" and main_completion[0].get("request_hash") == main_expected["provider_request_hash"], "main completion closure differs")
    for name, order, path in (("clean-target.log", clean_order, "/v2/charge"), ("main-source.log", main_order, "/v1/charge")):
        text = read(root, name).decode(errors="replace")
        matches = re.findall(rf"\[{re.escape(order)}\] Executing payment with token ([0-9a-f-]+) for \$42", text)
        require(len(matches) == 1 and UUID.fullmatch(matches[0]) is not None, f"{name} omitted stable payment token")
        operation = BASE._operation_id("restate-order-workflow", matches[0])
        record = clean_payment[0] if path == "/v2/charge" else main_payment[0]
        require(record.get("operation_id") == operation and record.get("path") == path, f"{name} payment identity differs")
    return main_payment[0], main_completion[0]


def fresh_certificate(root: Path, runtime_root: Path, stem: str) -> tuple[dict[str, Any], dict[str, Any]]:
    certificate = obj(jvalue(root, stem + ".json"), stem)
    state_name = stem + "-state.json"
    verdict_name = stem + "-verdict.json"
    recorded = obj(jvalue(root, verdict_name), verdict_name)
    command = ["go", "run", "./cmd/check-certificate", "-state", str(root / state_name), "-certificate", str(root / (stem + ".json"))]
    completed = subprocess.run(command, cwd=runtime_root, capture_output=True, text=True, timeout=120, check=False)
    require(completed.returncode == 0, f"fresh {stem} check failed: {completed.stderr.strip()}")
    try:
        fresh = obj(BASE._loads(completed.stdout.encode(), "fresh Certificate verdict"), "fresh Certificate verdict")
    except BASE.EvidenceError as error:
        raise EvidenceError(str(error)) from error
    require(fresh == recorded, f"fresh {stem} verdict differs from recorded verdict")
    return certificate, obj(jvalue(root, state_name), state_name)


def validate_proposed_control(root: Path, runtime_root: Path, source: dict[str, Any], target: dict[str, Any]) -> tuple[int, int]:
    clean_certificate, clean_state = fresh_certificate(root, runtime_root, "clean-certificate-target")
    require(clean_certificate.get("decision") == "activate" and clean_certificate.get("requirement") == target and clean_certificate.get("rule", {}).get("allow") == ["charge-v2", "finish-v2"], "empty-History Certificate does not prove exact target feasibility")
    require(clean_certificate.get("history") == {"sequence": 0, "hash": "0" * 64}, "clean Certificate is not bound to empty History")
    require(clean_state.get("settled") == {"used": {}, "results": {}} and clean_state.get("open_operations") == {}, "clean Certificate state invented progress")

    unsafe, unsafe_state = fresh_certificate(root, runtime_root, "main-certificate-unsafe")
    require(unsafe.get("decision") == "impossible" and unsafe.get("rule") is None and unsafe.get("requirement") == target, "History-dependent Certificate did not refuse target")
    require(unsafe.get("witness") == {"reason": "no completion fits the remaining resources for delivered:1"}, "History-dependent witness differs")
    require(unsafe_state.get("settled") == {"used": {"approval": 1}, "results": {"paid": 1}} and unsafe_state.get("open_operations") == {}, "unsafe Certificate State does not contain the succeeded source payment")
    at_cut = obj(jvalue(root, "main-control-at-cut.json"), "main control at cut")
    after = obj(jvalue(root, "main-control-after-refusal.json"), "main control after refusal")
    require(at_cut == after and at_cut.get("requirement") == source and at_cut.get("rule", {}).get("allow") == ["finish-v1"], "refusal changed the History-narrowed source Rule")
    require(jvalue(root, "main-control-history-at-cut.json") == jvalue(root, "main-control-history-after-refusal.json"), "compile refusal changed History")
    operations = obj(at_cut.get("operations"), "source operations at cut")
    charges = [op for op in operations.values() if isinstance(op, dict) and op.get("kind") == "charge-v1" and op.get("phase") == "succeeded"]
    require(len(charges) == 1 and len(operations) == 1, "source History does not contain one settled charge-v1")
    final = obj(jvalue(root, "main-final-control-state.json"), "final control state")
    require(final.get("requirement") == source and final.get("rule", {}).get("allow") == ["finish-v1"], "source Rule was not retained")
    final_ops = obj(final.get("operations"), "final source operations")
    require(len([op for op in final_ops.values() if isinstance(op, dict) and op.get("kind") == "finish-v1" and op.get("phase") == "succeeded"]) == 1, "source v1 did not finish safely")
    try:
        events = BASE._history(root / "main-runtime.history")
        BASE._head(root / "main-runtime.head", events)
    except BASE.EvidenceError as error:
        raise EvidenceError(str(error)) from error
    require(jvalue(root, "main-final-control-history.json") == events, "binary and API History differ")
    return 1, 1


def validate_deployments(root: Path, method: str, main_cut: dict[str, Any], main_final: dict[str, Any]) -> None:
    clean = obj(jvalue(root, "clean-deployment-target.json"), "clean target deployment")
    source = obj(jvalue(root, "main-deployment-source.json"), "source deployment")
    clean_id, source_id = clean.get("id"), source.get("id")
    require(isinstance(clean_id, str) and DEPLOYMENT_ID.fullmatch(clean_id) is not None, "clean deployment identity differs")
    require(isinstance(source_id, str) and DEPLOYMENT_ID.fullmatch(source_id) is not None, "source deployment identity differs")
    require(main_cut.get("pinned_deployment_id") == source_id, "main cut was not pinned to source")
    clean_listing = obj(jvalue(root, "clean-deployments.json"), "clean deployment listing")
    require(len(clean_listing.get("deployments", [])) == 1, "clean run registered more than target")
    main_listing = obj(jvalue(root, "main-deployments.json"), "main deployment listing")
    if method == "proposed":
        require(len(main_listing.get("deployments", [])) == 1 and main_final.get("pinned_deployment_id") == source_id, "proposed registered or pinned a refused target")
    else:
        target = obj(jvalue(root, "main-deployment-target.json"), "native target deployment")
        target_id = target.get("id")
        require(isinstance(target_id, str) and DEPLOYMENT_ID.fullmatch(target_id) is not None and target_id != source_id, "native target deployment identity differs")
        require(len(main_listing.get("deployments", [])) == 2 and main_final.get("pinned_deployment_id") == target_id, "native did not repin same invocation to target")


def check(root: Path, runtime_root: Path) -> dict[str, Any]:
    root = root_path(root)
    runtime_root = runtime_root.resolve(strict=True)
    require(read(root, "exit-status.txt") == b"0\n", "runner did not complete")
    metadata = obj(jvalue(root, "run-metadata.json"), "run metadata")
    exact(metadata, {"schema", "cell", "method", "state_dir", "clean_order_id", "main_order_id", "source_image", "target_image", "build_env", "runner_sha256", "skip_build", "target_binding"}, "run metadata")
    method = metadata.get("method")
    require(method in {"proposed", "native"} and metadata.get("schema") == 1 and metadata.get("cell") == "history-dependent-unsafe-edit", "run metadata lane differs")
    clean_order, main_order = metadata.get("clean_order_id"), metadata.get("main_order_id")
    require(isinstance(clean_order, str) and ORDER_ID.fullmatch(clean_order) is not None, "clean order identity differs")
    require(isinstance(main_order, str) and ORDER_ID.fullmatch(main_order) is not None and main_order != clean_order, "main order identity differs")
    build, source_image, target_image = validate_build_and_binding(root, metadata, method)
    source, target = expected_requirements()
    require(jvalue(root, "clean-requirement-source.json") == source, "source Requirement differs")
    require(jvalue(root, "clean-requirement-target.json") == target, "target Requirement differs")
    clean_cfg, main_cfg = validate_compose(root, method, source_image, target_image)
    validate_container_identity(root, method, target_image, clean_cfg, main_cfg)
    _, _, main_cut, main_final = validate_restate(root, method, clean_order, main_order)
    validate_providers(root, method, clean_order, main_order)
    validate_deployments(root, method, main_cut, main_final)
    if method == "proposed":
        used, capacity = validate_proposed_control(root, runtime_root, source, target)
        target_started = False
        decision = "impossible"
        external_requirement_violated = False
    else:
        # This is an independent reconstruction of the external Requirement,
        # not a claim that Restate implements or violated that Requirement.
        used = target["kinds"]["charge-v1"]["costs"]["approval"] + target["kinds"]["finish-v2"]["costs"]["approval"]
        capacity = target["capacities"]["approval"]
        require(used == 2 and capacity == 1, "native approval reconstruction did not exceed capacity")
        target_started = True
        decision = "runtime-completed-without-external-requirement-enforcement"
        external_requirement_violated = True

    names = sorted({
        "build.env", "run-metadata.json", "runner.sha256", "Dockerfile.worker", "compose.unsafe.yaml",
        "unsafe-target.patch", "clean-requirement-source.json", "clean-requirement-target.json",
        "clean-compose-config.yaml", "main-compose-config.yaml", "clean-submit.json", "main-submit.json",
        "clean-final-status.json", "clean-final-journal.json", "clean-final-workflow-state.json",
        "main-cut-status.json", "main-cut-status-after-window.json", "main-cut-journal.json",
        "main-cut-journal-after-window.json", "main-cut-workflow-state.json",
        "main-cut-workflow-state-after-window.json", "main-final-status.json", "main-final-invocations.json",
        "main-final-journal.json", "main-final-workflow-state.json", "clean-payment.history",
        "clean-completion.history", "main-at-cut-payment.history", "main-at-cut-completion.history",
        "main-payment.history", "main-completion.history", "clean-target-container.json",
        "clean-containers.raw.json", "main-containers-before-decision.raw.json", "main-containers.raw.json",
        "clean-deployment-target.json", "clean-deployments.json", "main-deployment-source.json", "main-deployments.json",
        "clean-expected-completion.json", "main-expected-completion.json", "exit-status.txt",
    })
    if method == "proposed":
        names += [
            "clean-certificate-target.json", "clean-certificate-target-state.json", "clean-certificate-target-verdict.json",
            "main-certificate-unsafe.json", "main-certificate-unsafe-state.json", "main-certificate-unsafe-verdict.json",
            "main-control-at-cut.json", "main-control-after-refusal.json", "main-control-history-at-cut.json",
            "main-control-history-after-refusal.json", "main-final-control-state.json", "main-final-control-history.json",
            "main-runtime.history", "main-runtime.head", "main-final-source-container.json",
        ]
    else:
        names += ["main-deployment-target.json", "main-target-container.json", "main-final-target-container.json", "main-source-after-removal.exit-status.txt"]
    hashes = {name: sha256(read(root, name)).hexdigest() for name in sorted(names)}
    digest = sha256(json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        "schema": 1, "valid": True, "cell": "history-dependent-unsafe-edit", "method": method,
        "clean_target_completed": True, "empty_history_target_allow": ["charge-v2", "finish-v2"],
        "main_decision": decision, "same_main_invocation_completed": True,
        "approval_used": used, "approval_capacity": capacity,
        "external_requirement_violated": external_requirement_violated,
        "target_started": target_started, "artifact_count": len(hashes), "evidence_digest": digest,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--runtime-root", type=Path, default=SCRIPT_DIR.parents[1])
    args = parser.parse_args()
    try:
        verdict = check(args.evidence, args.runtime_root)
    except (EvidenceError, BASE.EvidenceError, OSError, subprocess.SubprocessError) as error:
        print(f"check-unsafe: {error}", file=sys.stderr)
        return 1
    print(json.dumps(verdict, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
