#!/usr/bin/env python3
"""Independently validate one Temporal history-dependent unsafe-edit run.

The runner and ``observed.json`` are deliberately not imported as an oracle.
The verdict is reconstructed from Temporal's official History, Describe,
query, deployment, and poller output; append-only provider records; the
external control History and Certificates; immutable image/container
identity; and the resolved Docker Compose network graph.
"""

from __future__ import annotations

import argparse
import base64
import binascii
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
from typing import Any, Iterable, Mapping, Sequence

import yaml


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[2]
RUNTIME_ROOT = REPO_ROOT / "runtime"

CELL = "temporal-history-dependent-unsafe-edit"
TASK_QUEUE = "safe-change-food-orders"
DEPLOYMENT = "safe-change-food-order-worker"
WORKFLOW_NAME = "FoodOrderAutoUpgrade"
STARTER_IDENTITY = "safe-change-temporal-starter"
SIGNAL_IDENTITY = "safe-change-temporal-unsafe-harness"
SOURCE_BUILD = "food-order-v1"
SOURCE_IDENTITY = "safe-change-food-order-v1-worker"
TARGET_BUILD = "food-order-unsafe-v2"
TARGET_IDENTITY = "safe-change-food-order-unsafe-v2-worker"
OPERATION_DOMAIN = "temporal-order-workflow"
AMOUNT_CENTS = 4200
RESTAURANT_ID = "restaurant-1"
PRODUCTS = [
    {"product_id": "pizza-1", "description": "Margherita Pizza", "quantity": 2},
]
PRODUCT_COUNT = 2
DELIVERY_DELAY_MILLIS = 25
DRIVER_ID = "driver-1"
DELIVERY_REGION = "San Jose (CA)"
BUSINESS_SIGNALS = (
    "preparation_finished", "driver_selected",
    "driver_at_restaurant", "delivery_finished",
)
WAIT_STAGES = [
    "RESTAURANT_SELECTED", "CREATED", "PAYMENT_PENDING", "PAYMENT_COMMITTED",
    "SCHEDULED", "IN_PREPARATION",
]
FINAL_STAGES = WAIT_STAGES + [
    "SCHEDULING_DELIVERY", "WAITING_FOR_DRIVER", "IN_DELIVERY", "DELIVERED",
]
ZERO_HASH = "0" * 64
SDK_LANGUAGE_FLAGS = frozenset(range(1, 9))

ADAPTER_COMMAND = [
    "-config=/config/adapter.json",
    "-control-url=http://unsafe-control:8787",
    "-adapter-token-file=/operation-token/token",
    "-listen=0.0.0.0:8790",
    "-allow-nonloopback=true",
    "-execute-timeout=30s",
]
CONTROL_COMMAND = [
    "/usr/local/bin/control",
    "-listen=0.0.0.0:8787",
    "-allow-nonloopback=true",
    "-history=/state/runtime.history",
    "-head-anchor=/anchor/runtime.head",
    "-admin-token-file=/state/admin-token",
    "-operation-token-file=/operation-token/token",
    "-operation-domain=temporal-order-workflow",
    "-operation-kinds=charge-v1,finish-v1,charge-v2,finish-v2",
]

TEMPORAL_IMAGE = (
    "docker.io/temporalio/temporal:1.8.2@"
    "sha256:cf86707827fac99e4d1c4a47dc11b105382d796199c7bd41fb3213fb0471628e"
)
TEMPORAL_IMAGE_ID = "sha256:cf86707827fac99e4d1c4a47dc11b105382d796199c7bd41fb3213fb0471628e"
SOURCE_IMAGE_ID = "sha256:8a236550df67fe5cd334fd05bd092ff6457daf80ba7fd0077f1a98a6bdcd919f"
SOURCE_BINARY_SHA256 = "98a12265e86a04c3cf384ab36c05f55973f1751914c66d51c89da5b1cd1deac3"
STARTER_IMAGE_ID = "sha256:a754ee9e7301a3c22d36ac93175efae634f9224f5e2a9032b22632f6793b2feb"
EFFECTS_IMAGE_ID = "sha256:7c81b969bae3fd7372a91620854974834b27d58d9ec9f3887e90d9a553746b7f"
CONTROL_IMAGE_ID = "sha256:bf609efcccd199fb149316c83f3c9c6d67218a177e81d82858d10e54e0497c98"

FROZEN_BUILD = {
    "FROZEN_GIT_REVISION": "65988afbfc2fad82fdcc485fbc8f67dbc3b628cc",
    "FROZEN_TEMPORAL_BUILD_PROFILE_SHA256": "495e37bda60465e4be169605449a6d586f705faac95cbeb57f0ea49ab97a7fa5",
    "FROZEN_CONTROL_BUILD_PROFILE_SHA256": "9b5129f922a6737c593d3ed18dddfebc30d7f7818e39b0453c05e1652cd04ce3",
    "FROZEN_INPUTS_SHA256": "b0fe858fb41ed6a982fb2d050a7da321cc6db7b15ee095a9dd4af62e9a90860c",
    "FROZEN_VERSIONS_SHA256": "c0fbc207ce2a462f364d56173004eaad2b2a3d8dd2fe040b0123352505a0edd3",
    "FROZEN_TEMPORAL_SOURCE_SHA256": "877a7a5b71b24e3dc309af5cd23bebe77c40dab6b8aec659ef929f1dc771aade",
    "FROZEN_RUNTIME_SOURCE_SHA256": "e95760a49a36fa0dbf8136589545b5499a99e353baabae44c6c11e37ed581059",
    "WORKER_V1_ID": SOURCE_IMAGE_ID,
    "WORKER_V1_BINARY_SHA256": SOURCE_BINARY_SHA256,
    "WORKER_V1_VARIANT_SHA256": "46b82cdab94d538051928e3322cefee2eca3a5cdaf502f1ccad03d6c8b03621b",
    "WORKER_V2_ID": "sha256:0a281387a91b27c12f829cc9ab883966a8b20633ef37e1785a9616004bf1839a",
    "WORKER_V2_BINARY_SHA256": "e23020e3464e205a7237ad684d3ffb90b075d708739df3da0f31ffa319d2280c",
    "STARTER_ID": STARTER_IMAGE_ID,
    "STARTER_BINARY_SHA256": "17f3a24b1dd72e313c8853269f685a8cf854701cadc040579f754be49951b7f4",
    "EFFECTS_ID": EFFECTS_IMAGE_ID,
    "EFFECTS_BINARY_SHA256": "40e9b880f655a6c4029a68f684aa1e720fb98247a2eea73641a0f6085789ebe7",
    "SAFE_CHANGE_CONTROL_IMAGE": CONTROL_IMAGE_ID,
    "SAFE_CHANGE_RUNTIME_IMAGE": CONTROL_IMAGE_ID,
    "CONTROL_BINARY_SHA256": "c2d4cd7cbb26c47d5c3be5087cd7975aad5377f70d23ad5311ad87cb717221c5",
    "CONTROL_SOURCE_MANIFEST_SHA256": "cf6f498d6d2168c0c704a621b1ac98dd7d644ee6a927fa2f21f33d02933b383e",
    "CONTROL_DOCKERFILE_SHA256": "a364dbebde6067bc08a0488598d64643bfbae78968452e1fa9a1938f5ff43f32",
    "TEMPORAL_UNSAFE_PAYMENT_TOKEN_CONTRACT": "payment_token_equals_order_id",
    "TEMPORAL_UNSAFE_COMPOSE_PROFILES_CONTRACT": "empty",
    "TEMPORAL_UNSAFE_EXCLUDED_PROFILE": "excluded-base-worker-v2",
}

FROZEN_BUILD_KEYS = frozenset("""
GIT_REVISION FROZEN_GIT_REVISION FROZEN_TEMPORAL_BUILD_PROFILE_SHA256
FROZEN_CONTROL_BUILD_PROFILE_SHA256 FROZEN_INPUTS_SHA256 FROZEN_VERSIONS_SHA256
FROZEN_TEMPORAL_SOURCE_SHA256 FROZEN_RUNTIME_SOURCE_SHA256 TEMPORAL_IMAGE
TEMPORAL_IMAGE_ID WORKER_V1_IMAGE WORKER_V1_ID WORKER_V1_BINARY_SHA256
WORKER_V1_VARIANT_SHA256 WORKER_V2_IMAGE WORKER_V2_ID WORKER_V2_BINARY_SHA256
STARTER_IMAGE STARTER_ID STARTER_BINARY_SHA256 EFFECTS_IMAGE EFFECTS_ID
EFFECTS_BINARY_SHA256 SAFE_CHANGE_CONTROL_IMAGE SAFE_CHANGE_RUNTIME_IMAGE
CONTROL_BINARY_SHA256 CONTROL_SOURCE_MANIFEST_SHA256 CONTROL_DOCKERFILE_SHA256
TEMPORAL_UNSAFE_WORKER_IMAGE TEMPORAL_UNSAFE_WORKER_ID UNSAFE_WORKER_IMAGE
UNSAFE_WORKER_ID WORKER_UNSAFE_V2_ID TEMPORAL_UNSAFE_WORKER_BINARY_SHA256
UNSAFE_WORKER_BINARY_SHA256 PROPOSED_UNSAFE_WORKER_ID NATIVE_UNSAFE_WORKER_ID
PROPOSED_NATIVE_IMAGE_ID_EQUAL FROZEN_BASE_SOURCE_SHA256 GENERATED_SOURCE_SHA256
GENERATED_TREE_MANIFEST_SHA256 PATCH_SET_SHA256 PATCH_0001_SHA256 PATCH_0002_SHA256
PATCH_0003_SHA256 TARGET_DOCKERFILE_SHA256 UNSAFE_VARIANT_SHA256
UNSAFE_WORKER_NM_SHA256 UNSAFE_WORKER_GO_VERSION_SHA256 TARGET_BUILD_ENV_SHA256
TEMPORAL_UNSAFE_ADAPTER_IMAGE TEMPORAL_UNSAFE_ADAPTER_ID
TEMPORAL_UNSAFE_ADAPTER_SOURCE_SHA256 TEMPORAL_UNSAFE_ADAPTER_BINARY_SHA256
SOURCE_ADAPTER_CONFIG_SHA256 TARGET_ADAPTER_CONFIG_SHA256 BASE_COMPOSE_SHA256
PROPOSED_COMPOSE_SHA256 NATIVE_COMPOSE_SHA256 BUILD_IMAGES_SHA256
TARGET_BUILDER_SHA256 ADAPTER_DOCKERFILE_SHA256
TEMPORAL_UNSAFE_PAYMENT_TOKEN_CONTRACT TEMPORAL_UNSAFE_COMPOSE_PROFILES_CONTRACT
TEMPORAL_UNSAFE_EXCLUDED_PROFILE
""".split())

# These are literals, not comparisons with the live checkout. They bind an
# archived run to the build/topology inputs selected before the experiment.
# If an admitted preflight changes one of those inputs, update the literal and
# rerun every affected lane; never derive it from the evidence being checked.
FROZEN_INPUT_SHA256 = {
    "versions.env": "c0fbc207ce2a462f364d56173004eaad2b2a3d8dd2fe040b0123352505a0edd3",
    "compose-base.yaml": "715de72ed275eb9b0f9bec17092da6de7c196266badebbd922546c041e67a8b6",
    "frozen-inputs.env": "b0fe858fb41ed6a982fb2d050a7da321cc6db7b15ee095a9dd4af62e9a90860c",
    "source-adapter.json": "62aa7e3a8cffcbcf472c67f8ea9de7a5b45e506986b999be2d7e684d31094388",
    "target-adapter.json": "82bf8c0a007287853499845196013cab42154364b50bbb5864e6e61de518752e",
    "requirement-source.json": "d9a1da946a691ca3f581b06cd97edd50d89af696a9da2bcf1180f30a87925b49",
    "requirement-target.json": "44809139b75f70f9b2adb37b6309bd8e927a43f8b702ea2c5af329a14ca1280c",
}

OVERLAY_SHA256 = {
    "proposed": "911e592a221ca6f3dd6ea99eabb63331ed47dcccb4067b204fa190026c9a806c",
    "native": "90911c7a1d7c592b718bf0a933b278c3fc89bcdbd6d0b5735b7f0d7e88fe3bf1",
}

HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
OPERATION_ID = re.compile(r"op-[0-9a-f]{64}\Z")
STABLE_ID = re.compile(r"[A-Za-z0-9._-]{1,512}\Z")
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
MAX_FILE_BYTES = 128 << 20
MAX_RESULTS_BYTES = 512 << 20
MAX_HISTORY_BYTES = 128 << 20
MAX_FRAME_BYTES = 16 << 20
ACCEPTED_BUILD_ENV_SHA256 = "646c611a607556df783569332f0fbf941c31ddb790c1a32261d9bb81851e55e6"
ACCEPTED_BUILD_EVIDENCE_MANIFEST_SHA256 = (
    "2a6521bed654d07692fc46c8f189c8eb9770db4ccd92e0049f573c148bc3b785"
)


class EvidenceError(ValueError):
    """Evidence is absent, malformed, internally inconsistent, or unsafe."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceError(message)


def obj(value: Any, label: str) -> dict[str, Any]:
    require(isinstance(value, dict), f"{label} must be an object")
    return value


def arr(value: Any, label: str) -> list[Any]:
    require(isinstance(value, list), f"{label} must be an array")
    return value


def exact_fields(value: Mapping[str, Any], fields: set[str], label: str) -> None:
    require(set(value) == fields, f"{label} fields differ: {sorted(set(value) ^ fields)}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def loads(data: bytes, label: str) -> Any:
    try:
        return json.loads(data, object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvidenceError(f"{label} is not strict JSON") from error


def evidence_root(path: Path) -> Path:
    try:
        root = path.resolve(strict=True)
    except OSError as error:
        raise EvidenceError("evidence root does not exist") from error
    if (root / "results").is_dir() and not (root / "run-metadata.json").exists():
        root = (root / "results").resolve(strict=True)
    require(root.is_dir() and not root.is_symlink(), "evidence root is not a safe directory")
    return root


def safe_relative_name(name: str) -> None:
    candidate = Path(name)
    require(
        name and not candidate.is_absolute() and candidate.as_posix() == name
        and all(part not in {"", ".", ".."} for part in candidate.parts),
        f"unsafe artifact path: {name}",
    )


def read(root: Path, name: str, maximum: int = MAX_FILE_BYTES) -> bytes:
    safe_relative_name(name)
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
    return loads(read(root, name), name)


def jobject(root: Path, name: str) -> dict[str, Any]:
    return obj(jvalue(root, name), name)


def jarray(root: Path, name: str) -> list[Any]:
    return arr(jvalue(root, name), name)


def parse_env(data: bytes, label: str) -> dict[str, str]:
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError as error:
        raise EvidenceError(f"{label} is not ASCII") from error
    result: dict[str, str] = {}
    for number, line in enumerate(text.splitlines(), 1):
        require(line and not line.startswith("#") and "=" in line, f"{label} line {number} is invalid")
        key, value = line.split("=", 1)
        require(
            re.fullmatch(r"[A-Z][A-Z0-9_]*", key) is not None and key not in result and value,
            f"{label} line {number} is invalid",
        )
        result[key] = value
    return result


def parse_control_profile(data: bytes, label: str) -> dict[str, str]:
    try:
        lines = data.decode("ascii").splitlines()
    except UnicodeDecodeError as error:
        raise EvidenceError(f"{label} is not ASCII") from error
    require(
        lines and lines[0] == "# Independently frozen profile for the exact control image used by Temporal unsafe.",
        f"{label} provenance header differs",
    )
    require(len(lines) > 1, f"{label} has no profile values")
    return parse_env(("\n".join(lines[1:]) + "\n").encode(), label)


def parse_timestamp(value: Any, label: str) -> datetime:
    require(isinstance(value, str) and value, f"{label} is not a timestamp")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise EvidenceError(f"{label} is not a timestamp") from error
    require(result.tzinfo is not None, f"{label} has no timezone")
    return result


def regular_files(root: Path) -> set[str]:
    names: set[str] = set()
    directories: set[str] = set()
    total = 0
    for path in root.rglob("*"):
        info = path.lstat()
        require(not path.is_symlink(), f"evidence contains a symlink: {path.relative_to(root)}")
        relative = path.relative_to(root).as_posix()
        safe_relative_name(relative)
        if path.is_dir():
            directories.add(relative)
            continue
        require(path.is_file(), f"evidence contains a special file: {relative}")
        require(info.st_size <= MAX_FILE_BYTES, f"{relative} exceeds its size limit")
        names.add(relative)
        total += info.st_size
    require(total <= MAX_RESULTS_BYTES, "results exceeds its size limit")
    expected_directories = {
        Path(name).parent.as_posix()
        for name in names
        if Path(name).parent.as_posix() != "."
    }
    for name in tuple(expected_directories):
        parent = Path(name).parent
        while parent.as_posix() != ".":
            expected_directories.add(parent.as_posix())
            parent = parent.parent
    require(directories == expected_directories, "evidence contains an empty or unexpected directory")
    return names


def checksum_entries(data: bytes, label: str, *, prefix: str = "") -> dict[str, str]:
    try:
        lines = data.decode("ascii").splitlines()
    except UnicodeDecodeError as error:
        raise EvidenceError(f"{label} is not ASCII") from error
    declared: dict[str, str] = {}
    for line in lines:
        parts = line.split("  ", 1)
        require(len(parts) == 2 and HEX64.fullmatch(parts[0]) is not None, f"invalid {label} line")
        name = parts[1]
        require(name.startswith("./") and name != "./SHA256SUMS", f"unsafe {label} path")
        name = name[2:]
        safe_relative_name(name)
        full_name = prefix + name
        require(full_name not in declared, f"duplicate {label} entry")
        declared[full_name] = parts[0]
    return declared


def verify_checksums(root: Path, required: set[str]) -> set[str]:
    require(all("/" not in name for name in required), "top-level artifact contract is not flat")
    top_entries = {item.name for item in root.iterdir()}
    expected_top = required | {"build-evidence"}
    require(
        top_entries == expected_top,
        f"evidence entry set differs: missing={sorted(expected_top-top_entries)}, "
        f"extra={sorted(top_entries-expected_top)}",
    )
    names = regular_files(root)
    build_manifest_name = "build-evidence/SHA256SUMS"
    build_manifest = read(root, build_manifest_name)
    require(
        sha256(build_manifest).hexdigest() == ACCEPTED_BUILD_EVIDENCE_MANIFEST_SHA256,
        "recursive build-evidence manifest differs from the accepted build",
    )
    build_declared = checksum_entries(
        build_manifest, build_manifest_name, prefix="build-evidence/",
    )
    actual_build = {
        name for name in names
        if name.startswith("build-evidence/") and name != build_manifest_name
    }
    require(set(build_declared) == actual_build, "build-evidence manifest does not cover its exact tree")
    for name, digest in build_declared.items():
        require(sha256(read(root, name)).hexdigest() == digest, f"build-evidence checksum mismatch: {name}")

    declared = checksum_entries(read(root, "SHA256SUMS"), "SHA256SUMS")
    require(set(declared) == names - {"SHA256SUMS"}, "SHA256SUMS does not cover the exact evidence tree")
    for name, digest in declared.items():
        require(sha256(read(root, name)).hexdigest() == digest, f"checksum mismatch: {name}")
    return names


def content_manifest(root: Path, manifest_name: str, tree_prefix: str) -> dict[str, str]:
    data = read(root, manifest_name)
    declared: dict[str, str] = {}
    try:
        lines = data.decode("ascii").splitlines()
    except UnicodeDecodeError as error:
        raise EvidenceError(f"{manifest_name} is not ASCII") from error
    for line in lines:
        parts = line.split("  ", 1)
        require(len(parts) == 2 and HEX64.fullmatch(parts[0]) is not None, f"{manifest_name} line differs")
        relative = parts[1]
        safe_relative_name(relative)
        require(relative not in declared, f"{manifest_name} duplicates a path")
        declared[relative] = parts[0]
    actual = {
        path.relative_to(root / tree_prefix).as_posix()
        for path in (root / tree_prefix).rglob("*") if path.is_file()
    }
    require(set(declared) == actual, f"{manifest_name} does not cover the exact archived source tree")
    for relative, digest in declared.items():
        require(sha256(read(root, f"{tree_prefix}/{relative}")).hexdigest() == digest, f"{manifest_name} content differs: {relative}")
    return declared


def generated_source_hash(root: Path, tree_prefix: str, logical_root: str) -> str:
    digest = sha256()
    paths = sorted(path for path in (root / tree_prefix).rglob("*") if path.is_file())
    require(paths, "generated source tree is empty")
    for path in paths:
        relative = path.relative_to(root / tree_prefix).as_posix()
        digest.update(f"{logical_root}/{relative}".encode())
        digest.update(b"\0")
        digest.update(sha256(read(root, f"{tree_prefix}/{relative}")).hexdigest().encode())
        digest.update(b"\n")
    return digest.hexdigest()


def validate_build_evidence(root: Path, build: Mapping[str, str]) -> None:
    require(read(root, "build-evidence/frozen/frozen-inputs.env") == read(root, "frozen-inputs.env"), "build-evidence frozen inputs differ")
    require(read(root, "build-evidence/frozen/versions.env") == read(root, "versions.env"), "build-evidence versions differ")
    require(read(root, "build-evidence/target/versions.env") == read(root, "versions.env"), "target build versions differ")
    generated = content_manifest(
        root, "build-evidence/target/generated-tree.manifest",
        "build-evidence/target/generated-app",
    )
    require(
        sha256(read(root, "build-evidence/target/generated-tree.manifest")).hexdigest()
        == build["GENERATED_TREE_MANIFEST_SHA256"],
        "generated-tree manifest digest differs",
    )
    require(
        generated_source_hash(
            root, "build-evidence/target/generated-app", "runtime/deploy/temporal/app",
        ) == build["GENERATED_SOURCE_SHA256"],
        "archived generated source hash differs",
    )
    require(
        generated.get("internal/workerapp/variant_v1.go") == build["WORKER_V1_VARIANT_SHA256"],
        "archived generated source changed the source v1 variant",
    )
    require(
        generated.get("internal/workerapp/variant_unsafe_v2.go") == build["UNSAFE_VARIANT_SHA256"],
        "archived unsafe target source differs",
    )
    patches = content_manifest(
        root, "build-evidence/target/patches.manifest", "build-evidence/target/patches",
    )
    require(
        sha256(read(root, "build-evidence/target/patches.manifest")).hexdigest()
        == build["PATCH_SET_SHA256"],
        "target patch-set digest differs",
    )
    for number in (1, 2, 3):
        key = f"PATCH_000{number}_SHA256"
        filename = {
            1: "0001-add-charge-payment-v2.patch",
            2: "0002-add-unsafe-worker-v2.patch",
            3: "0003-test-unsafe-worker-v2.patch",
        }[number]
        require(patches.get(filename) == build[key], f"target patch {number} differs")
    adapter_manifest = content_manifest(
        root, "build-evidence/adapter/source.manifest", "build-evidence/adapter/source",
    )
    require(adapter_manifest, "adapter source manifest is empty")
    require(
        sha256(read(root, "build-evidence/adapter/source.manifest")).hexdigest()
        == build["TEMPORAL_UNSAFE_ADAPTER_SOURCE_SHA256"],
        "adapter source digest differs",
    )
    control_manifest = content_manifest(
        root, "build-evidence/control/control-source.manifest",
        "build-evidence/control/source",
    )
    require(control_manifest, "control source manifest is empty")
    require(
        sha256(read(root, "build-evidence/control/control-source.manifest")).hexdigest()
        == build["CONTROL_SOURCE_MANIFEST_SHA256"],
        "control source manifest digest differs",
    )
    control_profile = parse_control_profile(
        read(root, "build-evidence/control/control-profile.env"),
        "build-evidence/control/control-profile.env",
    )
    require(
        control_profile == {
            "CONTROL_PROFILE_SCHEMA": "1",
            "CONTROL_GIT_REVISION": build["FROZEN_GIT_REVISION"],
            "CONTROL_IMAGE": build["SAFE_CHANGE_CONTROL_IMAGE"],
            "CONTROL_BINARY_SHA256": build["CONTROL_BINARY_SHA256"],
            "CONTROL_SOURCE_MANIFEST_SHA256": build["CONTROL_SOURCE_MANIFEST_SHA256"],
            "CONTROL_DOCKERFILE_SHA256": build["CONTROL_DOCKERFILE_SHA256"],
            "CONTROL_GO_BUILD_IMAGE": (
                "docker.io/library/golang:1.25.13-alpine@"
                "sha256:844b27705f54e73773e0f9bc3c780633b9d7f4b4831bf35cdad02a81a4c80bd0"
            ),
            "CONTROL_RUNTIME_IMAGE": (
                "docker.io/library/alpine:3.22.2@"
                "sha256:4b7ce07002c69e8f3d704a9c5d6fd3053be500b7f1c69fc0d80990c2ad8dd412"
            ),
        },
        "independent control build profile differs",
    )
    require(
        sha256(read(root, "build-evidence/control/control-profile.env")).hexdigest()
        == build["FROZEN_CONTROL_BUILD_PROFILE_SHA256"],
        "independent control build profile digest differs",
    )
    archived_control_image = image_item(
        root, "build-evidence/control/image-inspect.json", CONTROL_IMAGE_ID,
    )
    require(
        obj(archived_control_image.get("Config"), "archived control image config").get("Entrypoint") is None,
        "archived control image entrypoint differs",
    )
    archived = {
        "build-evidence/builder/build-images.sh": build["BUILD_IMAGES_SHA256"],
        "build-evidence/builder/build-target.sh": build["TARGET_BUILDER_SHA256"],
        "build-evidence/target/Dockerfile.worker": build["TARGET_DOCKERFILE_SHA256"],
        "build-evidence/adapter/Dockerfile": build["ADAPTER_DOCKERFILE_SHA256"],
        "build-evidence/control/Dockerfile.runtime": build["CONTROL_DOCKERFILE_SHA256"],
        "build-evidence/target/worker-unsafe-v2.nm": build["UNSAFE_WORKER_NM_SHA256"],
        "build-evidence/target/worker-unsafe-v2.go-version.txt": build["UNSAFE_WORKER_GO_VERSION_SHA256"],
        "build-evidence/target.env": build["TARGET_BUILD_ENV_SHA256"],
    }
    for name, digest in archived.items():
        require(sha256(read(root, name)).hexdigest() == digest, f"archived build artifact differs: {name}")


def require_commit(repo_root: Path, revision: str) -> None:
    require(HEX40.fullmatch(revision) is not None, "recorded Git revision is not full length")
    completed = subprocess.run(
        ["git", "cat-file", "-e", revision + "^{commit}"], cwd=repo_root,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=30, check=False,
    )
    require(completed.returncode == 0, f"recorded Git commit object is absent: {completed.stderr.strip()}")


def expected_requirements() -> tuple[dict[str, Any], dict[str, Any]]:
    source = {
        "id": "temporal-unsafe-source-v1",
        "results": {"paid": 1, "delivered": 1},
        "capacities": {"approval": 1},
        "kinds": {
            "charge-v1": {
                "costs": {"approval": 1}, "produces": {"paid": 1},
                "retry_safe": False, "queryable": True,
                "target": "http://payment:8081/v1/charge", "method": "POST",
                "response_classifier": "operation-receipt-v1",
                "query_target": "http://payment:8081/v1/query", "query_method": "POST",
                "query_classifier": "operation-observation-v1",
            },
            "finish-v1": {
                "costs": {}, "produces": {"delivered": 1},
                "retry_safe": True, "queryable": False,
                "target": "http://completion:8081/v1/complete", "method": "POST",
                "response_classifier": "operation-receipt-v1",
            },
        },
    }
    target = {
        "id": "temporal-unsafe-target-v2",
        "results": {"paid": 1, "delivered": 1},
        "capacities": {"approval": 1},
        "kinds": {
            "charge-v1": {
                "costs": {"approval": 1}, "produces": {"paid": 1},
                "retry_safe": False, "queryable": False,
            },
            "finish-v1": {
                "costs": {}, "produces": {"delivered": 1},
                "retry_safe": False, "queryable": False,
            },
            "charge-v2": {
                "costs": {}, "produces": {"paid": 1},
                "retry_safe": False, "queryable": True,
                "target": "http://payment:8081/v2/charge", "method": "POST",
                "response_classifier": "operation-receipt-v1",
                "query_target": "http://payment:8081/v1/query", "query_method": "POST",
                "query_classifier": "operation-observation-v1",
            },
            "finish-v2": {
                "costs": {"approval": 1}, "produces": {"delivered": 1},
                "retry_safe": True, "queryable": False,
                "target": "http://completion:8081/v1/complete", "method": "POST",
                "response_classifier": "operation-receipt-v1",
            },
        },
    }
    return source, target


def semantic_target_feasible(target: Mapping[str, Any], old_payment: bool) -> bool:
    """Independently enumerate this two-result target's executable choices."""
    capacities = obj(target.get("capacities"), "target capacities")
    kinds = obj(target.get("kinds"), "target kinds")
    requirements = obj(target.get("results"), "target results")
    capacity = capacities.get("approval")
    require(type(capacity) is int and capacity >= 0, "target approval capacity differs")
    used = 0
    achieved: dict[str, int] = {}
    if old_payment:
        old = obj(kinds.get("charge-v1"), "charge-v1")
        used = obj(old.get("costs"), "charge-v1 costs").get("approval", 0)
        achieved.update(obj(old.get("produces"), "charge-v1 produces"))
    executable = [
        obj(value, f"target kind {name}") for name, value in kinds.items()
        if isinstance(value, dict) and all(value.get(key) for key in ("target", "method", "response_classifier"))
    ]
    for mask in range(1 << len(executable)):
        cost = used
        produced = dict(achieved)
        for index, spec in enumerate(executable):
            if not mask & (1 << index):
                continue
            cost += obj(spec.get("costs"), "kind costs").get("approval", 0)
            for name, amount in obj(spec.get("produces"), "kind produces").items():
                produced[name] = produced.get(name, 0) + amount
        if cost <= capacity and all(produced.get(name, 0) >= amount for name, amount in requirements.items()):
            return True
    return False


def operation_id(call_id: str) -> str:
    raw = b"operation-id-v1\0" + OPERATION_DOMAIN.encode() + b"\0" + call_id.encode()
    return "op-" + sha256(raw).hexdigest()


def delivery_id(order_id: str) -> str:
    return "delivery-" + order_id


def order_input(order_id: str) -> dict[str, Any]:
    return {
        "order_id": order_id,
        "restaurant_id": RESTAURANT_ID,
        "products": [dict(product) for product in PRODUCTS],
        "amount_cents": AMOUNT_CENTS,
        "delivery_delay_millis": DELIVERY_DELAY_MILLIS,
        "payment_token": order_id,
    }


def status_value(order_id: str, build: str, phase: str) -> dict[str, Any]:
    require(phase in {"IN_PREPARATION", "DELIVERED"}, "unsupported expected food-order phase")
    delivered = phase == "DELIVERED"
    return {
        "schema": 1,
        "order_id": order_id,
        "restaurant_id": RESTAURANT_ID,
        "product_count": PRODUCT_COUNT,
        "worker_build": build,
        "phase": phase,
        "delivery_id": delivery_id(order_id) if delivered else "",
        "driver_id": DRIVER_ID if delivered else "",
        "stages": list(FINAL_STAGES if delivered else WAIT_STAGES),
    }


def activity_input(activity: str, order_id: str, closure: str | None = None) -> dict[str, Any]:
    if activity in {"ChargePayment", "ChargePaymentV2"}:
        require(closure is None, f"{activity} unexpectedly carries a closure version")
        return {
            "order_id": order_id,
            "amount_cents": AMOUNT_CENTS,
            "operation_id": operation_id(order_id),
        }
    if activity == "PrepareFood":
        require(closure is None, "PrepareFood unexpectedly carries a closure version")
        return {
            "order_id": order_id,
            "restaurant_id": RESTAURANT_ID,
            "products": [dict(product) for product in PRODUCTS],
        }
    if activity == "ScheduleDelivery":
        require(closure is None, "ScheduleDelivery unexpectedly carries a closure version")
        return {
            "order_id": order_id,
            "delivery_id": delivery_id(order_id),
            "restaurant_id": RESTAURANT_ID,
            "region": DELIVERY_REGION,
        }
    require(activity == "CompleteOrder", f"unexpected food-order Activity: {activity}")
    value = {
        "order_id": order_id,
        "amount_cents": AMOUNT_CENTS,
        "operation_id": operation_id("complete:" + order_id),
    }
    if closure is not None:
        value["closure_version"] = closure
    return value


def local_activity_result(activity: str, order_id: str) -> dict[str, Any]:
    if activity == "PrepareFood":
        return {
            "schema": 1,
            "order_id": order_id,
            "restaurant_id": RESTAURANT_ID,
            "product_count": PRODUCT_COUNT,
            "outcome": "accepted",
        }
    require(activity == "ScheduleDelivery", f"unexpected local Activity: {activity}")
    return {
        "schema": 1,
        "order_id": order_id,
        "delivery_id": delivery_id(order_id),
        "restaurant_id": RESTAURANT_ID,
        "region": DELIVERY_REGION,
        "outcome": "scheduled",
    }


def signal_input(name: str, order_id: str) -> dict[str, Any]:
    require(name in BUSINESS_SIGNALS, f"unexpected food-order Signal: {name}")
    if name == "driver_selected":
        return {"delivery_id": delivery_id(order_id), "driver_id": DRIVER_ID}
    return {}


def effect_body(order_id: str, closure_version: str | None = None) -> bytes:
    value: dict[str, Any] = {"order_id": order_id, "amount_cents": AMOUNT_CENTS}
    if closure_version is not None:
        value["closure_version"] = closure_version
    return json.dumps(value, separators=(",", ":")).encode()


def request_hash(path: str, body: bytes) -> str:
    return sha256(b"POST\0" + path.encode() + b"\0" + body).hexdigest()


def gateway_request_hash(target: str, identity: str, body: bytes) -> str:
    headers = {
        "accept-encoding": "identity",
        "content-type": "application/json",
        "idempotency-key": identity,
        "user-agent": "safe-change-runtime/1",
        "x-operation-id": identity,
    }
    digest = sha256()
    digest.update(b"POST\0")
    digest.update(target.encode())
    digest.update(b"\0")
    for name, value in sorted(headers.items()):
        digest.update(name.encode())
        digest.update(b":")
        digest.update(value.encode())
        digest.update(b"\0")
    digest.update(body)
    return digest.hexdigest()


def expected_provider_record(order_id: str, path: str, completion: bool = False, closure: str | None = None) -> dict[str, str]:
    call_id = "complete:" + order_id if completion else order_id
    identity = operation_id(call_id)
    body = effect_body(order_id, closure if completion else None)
    prefix = "temporal-completion" if completion else "temporal-payment"
    return {
        "operation_id": identity,
        "request_hash": request_hash(path, body),
        "result_hash": sha256(b"charged\0" + identity.encode() + b"\0" + b"1").hexdigest(),
        "remote_reference": f"{prefix}/{identity}/commit-1",
        "path": path,
    }


def provider_records(root: Path, name: str) -> list[dict[str, Any]]:
    data = read(root, name)
    if data == b"":
        return []
    require(data.endswith(b"\n"), f"{name} is not newline terminated")
    records: list[dict[str, Any]] = []
    for index, line in enumerate(data.splitlines(), 1):
        record = obj(loads(line, f"{name} line {index}"), f"{name} line {index}")
        exact_fields(record, {"operation_id", "request_hash", "result_hash", "remote_reference", "path"}, f"{name} record")
        require(OPERATION_ID.fullmatch(str(record.get("operation_id"))) is not None, f"{name} Operation identity differs")
        require(HEX64.fullmatch(str(record.get("request_hash"))) is not None, f"{name} request hash differs")
        require(HEX64.fullmatch(str(record.get("result_hash"))) is not None, f"{name} result hash differs")
        require(isinstance(record.get("remote_reference"), str) and record["remote_reference"], f"{name} reference differs")
        records.append(record)
    return records


def check_stats(root: Path, name: str, expected: Mapping[str, Any]) -> None:
    value = jobject(root, name)
    exact_fields(value, {"deliveries", "commits", "paths"}, name)
    require(value == expected, f"{name} differs")


def payload_bytes(value: Any, label: str) -> bytes:
    payload = obj(value, label)
    exact_fields(payload, {"metadata", "data"}, label)
    metadata = obj(payload["metadata"], label + " metadata")
    require(metadata.get("encoding") == "anNvbi9wbGFpbg==", f"{label} encoding differs")
    require(set(metadata) in ({"encoding"}, {"encoding", "type"}), f"{label} metadata differs")
    encoded = payload.get("data")
    require(isinstance(encoded, str), f"{label} data is not base64")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as error:
        raise EvidenceError(f"{label} data is not canonical base64") from error
    require(base64.b64encode(data).decode() == encoded, f"{label} data is not canonical base64")
    return data


def one_payload(value: Any, label: str) -> bytes:
    wrapper = obj(value, label)
    exact_fields(wrapper, {"payloads"}, label)
    values = arr(wrapper["payloads"], label + " payloads")
    require(len(values) == 1, f"{label} must contain one payload")
    return payload_bytes(values[0], label + " payload")


def payload_json(value: Any, label: str) -> dict[str, Any]:
    return obj(loads(one_payload(value, label), label), label)


def history_events(value: Any, run_id: str, label: str) -> list[dict[str, Any]]:
    history = obj(value, label)
    require(set(history) in ({"events"}, {"events", "archivalUri", "nextPageToken"}), f"{label} wrapper differs")
    events = arr(history.get("events"), label + " events")
    require(events, f"{label} is empty")
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(events, 1):
        event = obj(raw, f"{label} event {index}")
        require(event.get("eventId") == str(index), f"{label} event IDs are not contiguous")
        require(isinstance(event.get("eventType"), str), f"{label} event type differs")
        # Temporal emits task IDs/timestamps that differ between matched runs.
        # Retain every semantic attribute and strip only those server-assigned
        # observation fields plus request IDs/history byte counts below.
        copy = dict(event)
        copy.pop("eventTime", None)
        copy.pop("taskId", None)
        for key, attrs in list(copy.items()):
            if key.endswith("EventAttributes") and isinstance(attrs, dict):
                attrs = dict(attrs)
                attrs.pop("requestId", None)
                attrs.pop("historySizeBytes", None)
                queue = attrs.get("taskQueue")
                if isinstance(queue, dict) and queue.get("kind") == "TASK_QUEUE_KIND_STICKY":
                    queue = dict(queue)
                    require(
                        isinstance(queue.get("name"), str) and queue["name"] and queue["name"] != TASK_QUEUE
                        and queue.get("normalName") == TASK_QUEUE,
                        f"{label} sticky task queue identity differs",
                    )
                    queue["name"] = "<sticky>"
                    attrs["taskQueue"] = queue
                for id_key in ("originalExecutionRunId", "firstExecutionRunId"):
                    if attrs.get(id_key) == run_id:
                        attrs[id_key] = "<run>"
                copy[key] = attrs
        normalized.append(copy)
    return normalized


def event_attrs(event: Mapping[str, Any], key: str, label: str) -> dict[str, Any]:
    return obj(event.get(key), label)


def linked_event_id(value: Any, label: str) -> int:
    require(isinstance(value, str) and value.isdigit() and int(value) > 0, f"{label} is not an event ID")
    return int(value)


def check_task_scheduled(event: Mapping[str, Any], sticky: bool) -> None:
    attrs = event_attrs(event, "workflowTaskScheduledEventAttributes", "workflow task scheduled")
    queue = obj(attrs.get("taskQueue"), "workflow task queue")
    if sticky:
        require(queue.get("kind") == "TASK_QUEUE_KIND_STICKY" and queue.get("normalName") == TASK_QUEUE, "sticky queue differs")
        require(isinstance(queue.get("name"), str) and queue["name"] != TASK_QUEUE, "sticky queue identity differs")
    else:
        require(queue == {"name": TASK_QUEUE, "kind": "TASK_QUEUE_KIND_NORMAL"}, "normal workflow queue differs")
    require(attrs.get("startToCloseTimeout") == "10s" and attrs.get("attempt") == 1, "workflow task schedule differs")


def check_task_started(event: Mapping[str, Any], scheduled: int, identity: str) -> None:
    attrs = event_attrs(event, "workflowTaskStartedEventAttributes", "workflow task started")
    require(attrs.get("scheduledEventId") == str(scheduled) and attrs.get("identity") == identity, "workflow task start differs")


def check_task_completed(event: Mapping[str, Any], scheduled: int, started: int, identity: str, build: str) -> None:
    attrs = event_attrs(event, "workflowTaskCompletedEventAttributes", "workflow task completed")
    require(attrs.get("scheduledEventId") == str(scheduled) and attrs.get("startedEventId") == str(started), "workflow task lineage differs")
    require(attrs.get("identity") == identity, "workflow task completion identity differs")
    require(attrs.get("workerVersion") == {"buildId": build, "useVersioning": True}, "workflow task build differs")
    require(attrs.get("versioningBehavior") == "VERSIONING_BEHAVIOR_AUTO_UPGRADE", "workflow versioning behavior differs")
    require(attrs.get("workerDeploymentName") == DEPLOYMENT, "workflow deployment differs")
    require(attrs.get("deploymentVersion") == {"buildId": build, "deploymentName": DEPLOYMENT}, "deployment version differs")
    sdk = obj(attrs.get("sdkMetadata"), "workflow SDK metadata")
    flags = sdk.get("langUsedFlags", [])
    require(
        isinstance(flags, list)
        and all(type(flag) is int and flag in SDK_LANGUAGE_FLAGS for flag in flags)
        and len(flags) == len(set(flags)),
        "workflow SDK language flags differ",
    )
    if scheduled == 2:
        require(sdk.get("sdkName") == "temporal-go" and sdk.get("sdkVersion") == "1.47.0", "workflow SDK version differs")
    elif sdk:
        require(sdk.get("sdkName") in {None, "temporal-go"} and sdk.get("sdkVersion") in {None, "1.47.0"}, "workflow SDK metadata differs")


def check_activity_scheduled(
    event: Mapping[str, Any], event_id: int, completed: int, activity: str,
    order_id: str, closure: str | None,
) -> None:
    attrs = event_attrs(event, "activityTaskScheduledEventAttributes", "activity scheduled")
    require(attrs.get("activityId") == str(event_id), "Activity identity differs")
    require(attrs.get("activityType") == {"name": activity}, "Activity type differs")
    require(attrs.get("taskQueue") == {"name": TASK_QUEUE, "kind": "TASK_QUEUE_KIND_NORMAL"}, "Activity queue differs")
    require(attrs.get("header") == {}, "Activity header differs")
    require(
        payload_json(attrs.get("input"), f"{activity} input")
        == activity_input(activity, order_id, closure),
        f"{activity} input differs",
    )
    timeout = "60s" if activity == "CompleteOrder" else "30s"
    require(attrs.get("startToCloseTimeout") == timeout, f"{activity} timeout differs")
    require(
        attrs.get("scheduleToCloseTimeout") == "0s"
        and attrs.get("scheduleToStartTimeout") == "0s"
        and attrs.get("heartbeatTimeout") == "0s",
        f"{activity} timeout contract differs",
    )
    require(attrs.get("workflowTaskCompletedEventId") == str(completed), "Activity workflow lineage differs")
    retry = obj(attrs.get("retryPolicy"), "Activity retry policy")
    require(
        retry == {
            "initialInterval": "1s", "backoffCoefficient": 2,
            "maximumInterval": "100s", "maximumAttempts": 1,
        },
        f"{activity} retry policy differs",
    )
    require(attrs.get("useWorkflowBuildId") is True, "Activity did not use workflow build ID")


def check_activity_started(event: Mapping[str, Any], scheduled: int, identity: str, build: str) -> None:
    attrs = event_attrs(event, "activityTaskStartedEventAttributes", "Activity started")
    require(attrs.get("scheduledEventId") == str(scheduled) and attrs.get("identity") == identity, "Activity start differs")
    require(attrs.get("attempt") == 1, "Activity attempt differs")
    require(attrs.get("workerVersion") == {"buildId": build, "useVersioning": True}, "Activity worker build differs")


def receipt(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": 1, "operation_id": record["operation_id"], "outcome": "succeeded",
        "result_hash": record["result_hash"], "remote_reference": record["remote_reference"],
    }


def check_activity_completed(
    event: Mapping[str, Any], scheduled: int, started: int, identity: str,
    expected_result: Mapping[str, Any], activity: str,
) -> None:
    attrs = event_attrs(event, "activityTaskCompletedEventAttributes", "Activity completed")
    require(attrs.get("scheduledEventId") == str(scheduled) and attrs.get("startedEventId") == str(started), "Activity completion lineage differs")
    require(attrs.get("identity") == identity, "Activity completion identity differs")
    require(
        payload_json(attrs.get("result"), f"{activity} result") == expected_result,
        f"{activity} result differs",
    )


def check_version_marker(event: Mapping[str, Any], completed: int) -> None:
    attrs = event_attrs(event, "markerRecordedEventAttributes", "Version marker")
    require(attrs.get("markerName") == "Version", "Version marker name differs")
    require(attrs.get("workflowTaskCompletedEventId") == str(completed), "Version marker lineage differs")
    details = obj(attrs.get("details"), "Version marker details")
    require(set(details) == {"change-id", "version"}, "Version marker fields differ")
    require(one_payload(details["change-id"], "Version change-id").decode() == '"unsafe-payment-capacity-v1"', "Version change-id differs")
    require(loads(one_payload(details["version"], "Version value"), "Version value") == 1, "Version value differs")


def check_change_version_upsert(event: Mapping[str, Any], completed: int) -> None:
    attrs = event_attrs(
        event,
        "upsertWorkflowSearchAttributesEventAttributes",
        "GetVersion search-attribute upsert",
    )
    exact_fields(
        attrs,
        {"searchAttributes", "workflowTaskCompletedEventId"},
        "GetVersion search-attribute upsert",
    )
    require(
        attrs.get("workflowTaskCompletedEventId") == str(completed),
        "GetVersion search-attribute lineage differs",
    )
    search_attributes = obj(attrs.get("searchAttributes"), "GetVersion search attributes")
    exact_fields(search_attributes, {"indexedFields"}, "GetVersion search attributes")
    indexed = obj(search_attributes.get("indexedFields"), "GetVersion indexed fields")
    exact_fields(indexed, {"TemporalChangeVersion"}, "GetVersion indexed fields")
    payload = obj(indexed["TemporalChangeVersion"], "TemporalChangeVersion payload")
    metadata = obj(payload.get("metadata"), "TemporalChangeVersion metadata")
    require(
        metadata in (
            {"encoding": "anNvbi9wbGFpbg=="},
            {"encoding": "anNvbi9wbGFpbg==", "type": "S2V5d29yZExpc3Q="},
        ),
        "TemporalChangeVersion metadata differs",
    )
    require(
        loads(payload_bytes(payload, "TemporalChangeVersion payload"), "TemporalChangeVersion value")
        == ["unsafe-payment-capacity-v1-1"],
        "TemporalChangeVersion value differs",
    )


CUT_TYPES = [
    "EVENT_TYPE_WORKFLOW_EXECUTION_STARTED", "EVENT_TYPE_WORKFLOW_TASK_SCHEDULED",
    "EVENT_TYPE_WORKFLOW_TASK_STARTED", "EVENT_TYPE_WORKFLOW_TASK_COMPLETED",
    "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED", "EVENT_TYPE_ACTIVITY_TASK_STARTED",
    "EVENT_TYPE_ACTIVITY_TASK_COMPLETED", "EVENT_TYPE_WORKFLOW_TASK_SCHEDULED",
    "EVENT_TYPE_WORKFLOW_TASK_STARTED", "EVENT_TYPE_WORKFLOW_TASK_COMPLETED",
    "EVENT_TYPE_TIMER_STARTED", "EVENT_TYPE_TIMER_FIRED",
    "EVENT_TYPE_WORKFLOW_TASK_SCHEDULED", "EVENT_TYPE_WORKFLOW_TASK_STARTED",
    "EVENT_TYPE_WORKFLOW_TASK_COMPLETED", "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED",
    "EVENT_TYPE_ACTIVITY_TASK_STARTED", "EVENT_TYPE_ACTIVITY_TASK_COMPLETED",
    "EVENT_TYPE_WORKFLOW_TASK_SCHEDULED", "EVENT_TYPE_WORKFLOW_TASK_STARTED",
    "EVENT_TYPE_WORKFLOW_TASK_COMPLETED",
]
ALLOWED_FINAL_TYPES = {
    "EVENT_TYPE_WORKFLOW_EXECUTION_STARTED", "EVENT_TYPE_WORKFLOW_TASK_SCHEDULED",
    "EVENT_TYPE_WORKFLOW_TASK_STARTED", "EVENT_TYPE_WORKFLOW_TASK_COMPLETED",
    "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED", "EVENT_TYPE_ACTIVITY_TASK_STARTED",
    "EVENT_TYPE_ACTIVITY_TASK_COMPLETED", "EVENT_TYPE_TIMER_STARTED",
    "EVENT_TYPE_TIMER_FIRED", "EVENT_TYPE_WORKFLOW_EXECUTION_SIGNALED",
    "EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED", "EVENT_TYPE_MARKER_RECORDED",
    "EVENT_TYPE_UPSERT_WORKFLOW_SEARCH_ATTRIBUTES",
}


def validate_workflow_history(
    value: Any, *, label: str, workflow_id: str, run_id: str, order_id: str,
    clean: bool, final_build: str, payment_record: Mapping[str, Any],
    completion_record: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    events = history_events(value, run_id, label)
    require(events[-1].get("eventType") == "EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED", f"{label} did not complete")
    require(all(event.get("eventType") in ALLOWED_FINAL_TYPES for event in events), f"{label} has an unexpected event type")
    require(not any(event.get("eventType") == "EVENT_TYPE_WORKFLOW_TASK_FAILED" for event in events), f"{label} contains a failed Workflow Task")
    started = event_attrs(events[0], "workflowExecutionStartedEventAttributes", "workflow start")
    require(started.get("workflowType") == {"name": WORKFLOW_NAME}, "workflow type differs")
    require(started.get("taskQueue") == {"name": TASK_QUEUE, "kind": "TASK_QUEUE_KIND_NORMAL"}, "workflow task queue differs")
    require(started.get("workflowId") == workflow_id and started.get("identity") == STARTER_IDENTITY, "workflow start identity differs")
    require(started.get("originalExecutionRunId") == "<run>" and started.get("firstExecutionRunId") == "<run>", "workflow run lineage differs")
    require(started.get("attempt") == 1 and started.get("workflowTaskTimeout") == "10s", "workflow start options differ")
    require(payload_json(started.get("input"), "workflow input") == order_input(order_id), "workflow input or payment-token contract differs")

    first_build = TARGET_BUILD if clean else SOURCE_BUILD
    first_identity = TARGET_IDENTITY if clean else SOURCE_IDENTITY
    wft_schedules = {
        int(event["eventId"]): event for event in events
        if event.get("eventType") == "EVENT_TYPE_WORKFLOW_TASK_SCHEDULED"
    }
    wft_starts = [event for event in events if event.get("eventType") == "EVENT_TYPE_WORKFLOW_TASK_STARTED"]
    wft_completions = [event for event in events if event.get("eventType") == "EVENT_TYPE_WORKFLOW_TASK_COMPLETED"]
    require(len(wft_schedules) == len(wft_starts) == len(wft_completions), "Workflow Task event counts differ")
    for index, event in enumerate(wft_schedules.values()):
        check_task_scheduled(event, index != 0)
    starts_by_schedule: dict[int, Mapping[str, Any]] = {}
    for event in wft_starts:
        attrs = event_attrs(event, "workflowTaskStartedEventAttributes", "workflow task started")
        scheduled = linked_event_id(attrs.get("scheduledEventId"), "Workflow Task scheduledEventId")
        require(scheduled in wft_schedules and scheduled not in starts_by_schedule, "Workflow Task start set differs")
        event_id = int(event["eventId"])
        identity = first_identity
        if not clean and final_build == TARGET_BUILD and event_id > len(CUT_TYPES):
            identity = TARGET_IDENTITY
        check_task_started(event, scheduled, identity)
        starts_by_schedule[scheduled] = event
    completed_wft_ids: set[int] = set()
    for event in wft_completions:
        attrs = event_attrs(event, "workflowTaskCompletedEventAttributes", "workflow task completed")
        scheduled = linked_event_id(attrs.get("scheduledEventId"), "Workflow Task completion scheduledEventId")
        start_event = starts_by_schedule.get(scheduled)
        require(start_event is not None and scheduled not in completed_wft_ids, "Workflow Task completion set differs")
        event_id = int(event["eventId"])
        identity, build = first_identity, first_build
        if not clean and final_build == TARGET_BUILD and event_id > len(CUT_TYPES):
            identity, build = TARGET_IDENTITY, TARGET_BUILD
        check_task_completed(event, scheduled, int(start_event["eventId"]), identity, build)
        completed_wft_ids.add(scheduled)
    require(completed_wft_ids == set(wft_schedules), "Workflow Task execution set differs")

    marker_events = [event for event in events if event.get("eventType") == "EVENT_TYPE_MARKER_RECORDED"]
    upsert_events = [event for event in events if event.get("eventType") == "EVENT_TYPE_UPSERT_WORKFLOW_SEARCH_ATTRIBUTES"]
    if clean:
        require(len(marker_events) == len(upsert_events) == 1, "clean target GetVersion event set differs")
        require(marker_events[0] is events[4] and upsert_events[0] is events[5], "clean target GetVersion event position differs")
        check_version_marker(marker_events[0], 4)
        check_change_version_upsert(upsert_events[0], 4)
    else:
        require(not marker_events and not upsert_events, "replayed source History invented a GetVersion marker")

    activity_schedules = [event for event in events if event.get("eventType") == "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED"]
    activity_types = [
        event.get("activityTaskScheduledEventAttributes", {}).get("activityType", {}).get("name")
        for event in activity_schedules
    ]
    payment_activity = "ChargePaymentV2" if clean else "ChargePayment"
    require(
        activity_types == [payment_activity, "PrepareFood", "ScheduleDelivery", "CompleteOrder"],
        f"{label} food-order Activity sequence differs",
    )
    schedule_by_id = {int(event["eventId"]): event for event in activity_schedules}
    starts_by_activity: dict[int, Mapping[str, Any]] = {}
    completions_by_activity: dict[int, Mapping[str, Any]] = {}
    for event in events:
        event_type = event.get("eventType")
        if event_type not in {"EVENT_TYPE_ACTIVITY_TASK_STARTED", "EVENT_TYPE_ACTIVITY_TASK_COMPLETED"}:
            continue
        key = "activityTaskStartedEventAttributes" if event_type.endswith("STARTED") else "activityTaskCompletedEventAttributes"
        scheduled = linked_event_id(
            event_attrs(event, key, "Activity execution").get("scheduledEventId"),
            "Activity scheduledEventId",
        )
        target = starts_by_activity if event_type.endswith("STARTED") else completions_by_activity
        require(scheduled in schedule_by_id and scheduled not in target, "Activity execution set differs")
        target[scheduled] = event
    require(set(starts_by_activity) == set(schedule_by_id) == set(completions_by_activity), "Activity execution set differs")

    final_identity = TARGET_IDENTITY if final_build == TARGET_BUILD else SOURCE_IDENTITY
    require(completion_record is not None, f"{label} has no completion provider record")
    closure = "unsafe-v2" if final_build == TARGET_BUILD else None
    expected_results = {
        payment_activity: receipt(payment_record),
        "PrepareFood": local_activity_result("PrepareFood", order_id),
        "ScheduleDelivery": local_activity_result("ScheduleDelivery", order_id),
        "CompleteOrder": receipt(completion_record),
    }
    for scheduled_event, activity in zip(activity_schedules, activity_types, strict=True):
        scheduled = int(scheduled_event["eventId"])
        attrs = event_attrs(scheduled_event, "activityTaskScheduledEventAttributes", f"{activity} schedule")
        completed_wft = linked_event_id(attrs.get("workflowTaskCompletedEventId"), f"{activity} Workflow Task completion")
        require(
            any(int(event["eventId"]) == completed_wft for event in wft_completions)
            and completed_wft < scheduled,
            f"{activity} Workflow Task lineage differs",
        )
        activity_closure = closure if activity == "CompleteOrder" else None
        check_activity_scheduled(scheduled_event, scheduled, completed_wft, activity, order_id, activity_closure)
        identity, build = (first_identity, first_build) if activity in {payment_activity, "PrepareFood"} else (final_identity, final_build)
        start_event = starts_by_activity[scheduled]
        completion_event = completions_by_activity[scheduled]
        require(scheduled < int(start_event["eventId"]) < int(completion_event["eventId"]), f"{activity} event order differs")
        check_activity_started(start_event, scheduled, identity, build)
        check_activity_completed(
            completion_event, scheduled, int(start_event["eventId"]), identity,
            expected_results[activity], activity,
        )

    timers_started = [event for event in events if event.get("eventType") == "EVENT_TYPE_TIMER_STARTED"]
    timers_fired = [event for event in events if event.get("eventType") == "EVENT_TYPE_TIMER_FIRED"]
    require(len(timers_started) == len(timers_fired) == 1, "preparation timer event set differs")
    timer_started = event_attrs(timers_started[0], "timerStartedEventAttributes", "preparation timer start")
    timer_fired = event_attrs(timers_fired[0], "timerFiredEventAttributes", "preparation timer fire")
    require(
        timer_started.get("startToFireTimeout") == "0.025s"
        and isinstance(timer_started.get("timerId"), str) and timer_started["timerId"]
        and timer_fired.get("timerId") == timer_started["timerId"]
        and timer_fired.get("startedEventId") == timers_started[0]["eventId"]
        and int(completions_by_activity[int(activity_schedules[0]["eventId"])]["eventId"])
        < int(timers_started[0]["eventId"]) < int(timers_fired[0]["eventId"])
        < int(activity_schedules[1]["eventId"]),
        "preparation timer semantics differ",
    )

    signal_events = [event for event in events if event.get("eventType") == "EVENT_TYPE_WORKFLOW_EXECUTION_SIGNALED"]
    require(len(signal_events) == len(BUSINESS_SIGNALS), "business Signal count differs")
    signal_attrs = [
        event_attrs(event, "workflowExecutionSignaledEventAttributes", "business Signal")
        for event in signal_events
    ]
    require([attrs.get("signalName") for attrs in signal_attrs] == list(BUSINESS_SIGNALS), "business Signal order differs")
    for attrs in signal_attrs:
        exact_fields(attrs, {"signalName", "input", "identity"}, "business Signal")
        name = str(attrs["signalName"])
        require(attrs.get("identity") == SIGNAL_IDENTITY, f"{name} Signal identity differs")
        actual_input = payload_json(attrs["input"], f"{name} Signal input") if name == "driver_selected" else attrs["input"]
        require(actual_input == signal_input(name, order_id), f"{name} Signal input differs")
    require(
        int(signal_events[0]["eventId"]) < int(activity_schedules[2]["eventId"])
        and int(signal_events[-1]["eventId"]) < int(activity_schedules[3]["eventId"]),
        "business Signal/Activity causality differs",
    )

    completed = event_attrs(events[-1], "workflowExecutionCompletedEventAttributes", "workflow completed")
    require(
        linked_event_id(completed.get("workflowTaskCompletedEventId"), "workflow completion Workflow Task")
        in {int(event["eventId"]) for event in wft_completions},
        "workflow completion lineage differs",
    )
    require(payload_json(completed.get("result"), "workflow result") == status_value(order_id, final_build, "DELIVERED"), "workflow result differs")
    return events


def validate_cut_history(value: Any, *, label: str, workflow_id: str, run_id: str, order_id: str, payment_record: Mapping[str, Any]) -> list[dict[str, Any]]:
    events = history_events(value, run_id, label)
    require([event.get("eventType") for event in events] == CUT_TYPES, f"{label} is not the paid waiting cut")
    # Complete validation by appending a semantically valid dummy tail is less
    # clear than directly checking the ten source events here.
    started = event_attrs(events[0], "workflowExecutionStartedEventAttributes", "cut workflow start")
    require(started.get("workflowType") == {"name": WORKFLOW_NAME} and started.get("workflowId") == workflow_id, "cut workflow identity differs")
    require(
        started.get("identity") == STARTER_IDENTITY
        and started.get("taskQueue") == {"name": TASK_QUEUE, "kind": "TASK_QUEUE_KIND_NORMAL"}
        and started.get("originalExecutionRunId") == "<run>"
        and started.get("firstExecutionRunId") == "<run>"
        and started.get("attempt") == 1
        and started.get("workflowTaskTimeout") == "10s",
        "cut workflow starter/options differ",
    )
    require(payload_json(started.get("input"), "cut workflow input") == order_input(order_id), "cut workflow input differs")
    check_task_scheduled(events[1], False)
    check_task_started(events[2], 2, SOURCE_IDENTITY)
    check_task_completed(events[3], 2, 3, SOURCE_IDENTITY, SOURCE_BUILD)
    check_activity_scheduled(events[4], 5, 4, "ChargePayment", order_id, None)
    check_activity_started(events[5], 5, SOURCE_IDENTITY, SOURCE_BUILD)
    check_activity_completed(events[6], 5, 6, SOURCE_IDENTITY, receipt(payment_record), "ChargePayment")
    check_task_scheduled(events[7], True)
    check_task_started(events[8], 8, SOURCE_IDENTITY)
    check_task_completed(events[9], 8, 9, SOURCE_IDENTITY, SOURCE_BUILD)
    timer_started = event_attrs(events[10], "timerStartedEventAttributes", "cut preparation timer start")
    timer_fired = event_attrs(events[11], "timerFiredEventAttributes", "cut preparation timer fire")
    require(
        timer_started.get("startToFireTimeout") == "0.025s"
        and timer_started.get("workflowTaskCompletedEventId") == "10"
        and timer_fired.get("timerId") == timer_started.get("timerId")
        and timer_fired.get("startedEventId") == "11",
        "cut preparation timer differs",
    )
    check_task_scheduled(events[12], True)
    check_task_started(events[13], 13, SOURCE_IDENTITY)
    check_task_completed(events[14], 13, 14, SOURCE_IDENTITY, SOURCE_BUILD)
    check_activity_scheduled(events[15], 16, 15, "PrepareFood", order_id, None)
    check_activity_started(events[16], 16, SOURCE_IDENTITY, SOURCE_BUILD)
    check_activity_completed(
        events[17], 16, 17, SOURCE_IDENTITY,
        local_activity_result("PrepareFood", order_id), "PrepareFood",
    )
    check_task_scheduled(events[18], True)
    check_task_started(events[19], 19, SOURCE_IDENTITY)
    check_task_completed(events[20], 19, 20, SOURCE_IDENTITY, SOURCE_BUILD)
    return events


def validate_query(root: Path, name: str, order_id: str, build: str, phase: str) -> None:
    value = jobject(root, name)
    exact_fields(value, {"queryResult"}, name)
    result = arr(value["queryResult"], name + " result")
    require(result == [status_value(order_id, build, phase)], f"{name} differs")


def validate_describe(
    root: Path, name: str, workflow_id: str, run_id: str, order_id: str,
    build: str, status: str, history_length: int,
) -> None:
    value = jobject(root, name)
    info = obj(value.get("workflowExecutionInfo"), name + " execution info")
    require(info.get("execution") == {"workflowId": workflow_id, "runId": run_id}, f"{name} workflow execution differs")
    require(info.get("type") == {"name": WORKFLOW_NAME} and info.get("taskQueue") == TASK_QUEUE, f"{name} workflow type differs")
    require(info.get("status") == status and info.get("historyLength") == str(history_length), f"{name} status/history length differs")
    require(info.get("mostRecentWorkerVersionStamp") == {"buildId": build, "useVersioning": True}, f"{name} worker build differs")
    versioning = obj(info.get("versioningInfo"), name + " versioning info")
    require(versioning.get("behavior") == "VERSIONING_BEHAVIOR_AUTO_UPGRADE", f"{name} versioning behavior differs")
    require(versioning.get("deploymentVersion") == {"buildId": build, "deploymentName": DEPLOYMENT}, f"{name} deployment version differs")
    if status == "WORKFLOW_EXECUTION_STATUS_COMPLETED":
        result = obj(value.get("result"), name + " result")
        require(result == status_value(order_id, build, "DELIVERED"), f"{name} final result differs")


def validate_poller(root: Path, name: str, build: str, identity: str, allowed_builds: set[str]) -> None:
    value = jobject(root, name)
    pollers = arr(value.get("pollers"), name + " pollers")
    require(pollers, f"{name} has no poller")
    matches = 0
    seen: set[tuple[str, str]] = set()
    for index, raw in enumerate(pollers, 1):
        poller = obj(raw, f"{name} poller {index}")
        capabilities = obj(poller.get("worker_version_capabilities"), f"{name} capabilities")
        options = obj(poller.get("deployment_options"), f"{name} deployment options")
        poller_build = capabilities.get("build_id")
        poller_identity = poller.get("identity")
        require(poller_build in allowed_builds, f"{name} admitted an unrelated build")
        expected_identity = TARGET_IDENTITY if poller_build == TARGET_BUILD else SOURCE_IDENTITY
        require(poller_identity == expected_identity, f"{name} poller identity/build differ")
        require(
            capabilities == {
                "build_id": poller_build,
                "use_versioning": True,
                "deployment_series_name": DEPLOYMENT,
            },
            f"{name} worker version capabilities differ",
        )
        require(
            options == {
                "deployment_name": DEPLOYMENT,
                "build_id": poller_build,
                "worker_versioning_mode": 2,
            },
            f"{name} deployment options differ",
        )
        key = (str(poller_identity), str(poller_build))
        require(key not in seen, f"{name} duplicate poller identity/build")
        seen.add(key)
        if poller_build == build and poller_identity == identity:
            matches += 1
    require(matches == 1, f"{name} does not contain exactly one intended poller")
    queues = arr(value.get("taskQueues"), name + " task queue partitions")
    require(len(queues) == 1 and obj(queues[0], name + " task queue").get("partition") == 0, f"{name} task queue partition differs")


def version_ref(build: str) -> dict[str, str]:
    return {"deploymentName": DEPLOYMENT, "BuildID": build}


def validate_deployment_version(root: Path, name: str, build: str, *, current: bool | None) -> None:
    value = jobject(root, name)
    require(value.get("deploymentName") == DEPLOYMENT and value.get("BuildID") == build, f"{name} version identity differs")
    queues = arr(value.get("taskQueuesInfos"), name + " task queues")
    require(
        len(queues) == 2
        and {json.dumps(item, sort_keys=True) for item in queues}
        == {
            json.dumps({"name": TASK_QUEUE, "type": "workflow"}, sort_keys=True),
            json.dumps({"name": TASK_QUEUE, "type": "activity"}, sort_keys=True),
        },
        f"{name} registered task queues differ",
    )
    create_time = parse_timestamp(value.get("createTime"), name + " create time")
    require(create_time.timestamp() > 0, f"{name} create time differs")
    if current is not None:
        current_time = parse_timestamp(value.get("currentSinceTime"), name + " current time")
        if current:
            require(current_time.timestamp() > 0, f"{name} was not current")
        else:
            require(current_time.timestamp() == 0, f"{name} was already current")
    require(value.get("rampPercentage") == 0, f"{name} ramp percentage differs")


def validate_deployment(
    root: Path, name: str, *, current_build: str | None,
    allowed_builds: set[str], require_builds: set[str],
) -> None:
    value = jobject(root, name)
    require(value.get("name") == DEPLOYMENT, f"{name} deployment name differs")
    routing = obj(value.get("routingConfig"), name + " routing")
    expected_current = "" if current_build is None else current_build
    expected_deployment = "" if current_build is None else DEPLOYMENT
    require(
        routing.get("currentVersionDeploymentName") == expected_deployment
        and routing.get("currentVersionBuildID") == expected_current,
        f"{name} current version differs",
    )
    require(
        routing.get("rampingVersionDeploymentName") == ""
        and routing.get("rampingVersionBuildID") == ""
        and routing.get("rampingVersionPercentage") == 0,
        f"{name} admitted ramping traffic",
    )
    summaries = arr(value.get("versionSummaries"), name + " version summaries")
    builds: set[str] = set()
    for raw in summaries:
        summary = obj(raw, name + " version summary")
        require(summary.get("deploymentName") == DEPLOYMENT, f"{name} summary deployment differs")
        build = summary.get("BuildID")
        require(isinstance(build, str) and build in allowed_builds and build not in builds, f"{name} summary build differs")
        builds.add(build)
        parse_timestamp(summary.get("createTime"), name + " summary create time")
    require(require_builds <= builds, f"{name} omits an intended version")
    require(current_build is None or current_build in builds, f"{name} current build has no summary")


def validate_start(root: Path, name: str, workflow_id: str, run_id: str) -> None:
    value = jobject(root, name)
    require(
        value == {
            "schema": 1, "behavior": "autoupgrade",
            "workflow_id": workflow_id, "run_id": run_id,
        },
        f"{name} start receipt differs",
    )


def validate_invocation(
    root: Path, name: str, *, phase: str, method: str, project: str,
    workflow_id: str, order_id: str, source_build: str,
) -> None:
    value = jobject(root, name)
    expected = {
        "schema": 1, "phase": phase, "cell": CELL, "method": method,
        "compose_project": project, "workflow_id": workflow_id,
        "order_id": order_id, "restaurant_id": RESTAURANT_ID,
        "products": PRODUCTS, "delivery_delay_millis": DELIVERY_DELAY_MILLIS,
        "payment_token": order_id,
        "amount_cents": AMOUNT_CENTS,
        "operation_ids": {
            "payment": operation_id(order_id),
            "completion": operation_id("complete:" + order_id),
        },
        "source_build": source_build, "target_build": TARGET_BUILD,
        "deployment": DEPLOYMENT, "behavior": "autoupgrade",
        "signals": [
            {
                "name": signal,
                "identity": SIGNAL_IDENTITY,
                **({"input": signal_input(signal, order_id)} if signal == "driver_selected" else {}),
            }
            for signal in BUSINESS_SIGNALS
        ],
    }
    require(value == expected, f"{name} invocation differs")


def validate_metadata(
    root: Path, metadata: Mapping[str, Any], method: str,
    clean_order: str, main_order: str, clean_workflow: str, main_workflow: str,
    build: Mapping[str, str],
) -> None:
    exact_fields(
        metadata,
        {
            "schema", "cell", "method", "state_root", "clean_project", "main_project",
            "clean_workflow_id", "main_workflow_id", "clean_order_id", "main_order_id",
            "projects", "clean", "main", "source_image", "target_image", "adapter_image",
            "control_image", "build_env", "build_sha256", "runner_sha256", "skip_build",
            "signal_identity", "signal_names", "input_sha256",
        },
        "run-metadata.json",
    )
    require(metadata.get("schema") == 1 and metadata.get("cell") == CELL and metadata.get("method") == method, "run metadata header differs")
    require(metadata.get("projects") == {"clean": metadata.get("clean_project"), "main": metadata.get("main_project")}, "run metadata project map differs")
    for phase, order_id, workflow_id in (
        ("clean", clean_order, clean_workflow), ("main", main_order, main_workflow),
    ):
        require(
            metadata.get(phase) == {
                "workflow_id": workflow_id, "order_id": order_id,
                "restaurant_id": RESTAURANT_ID, "products": PRODUCTS,
                "delivery_delay_millis": DELIVERY_DELAY_MILLIS,
                "amount_cents": AMOUNT_CENTS, "payment_token": order_id,
                "delivery_id": delivery_id(order_id), "driver_id": DRIVER_ID,
                "operation_ids": {
                    "payment": operation_id(order_id),
                    "completion": operation_id("complete:" + order_id),
                },
            },
            f"run metadata {phase} workload binding differs",
        )
    require(
        metadata.get("source_image") == SOURCE_IMAGE_ID
        and metadata.get("target_image") == build["TEMPORAL_UNSAFE_WORKER_ID"]
        and metadata.get("adapter_image") == build["TEMPORAL_UNSAFE_ADAPTER_ID"]
        and metadata.get("control_image") == CONTROL_IMAGE_ID,
        "run metadata immutable image binding differs",
    )
    require(metadata.get("build_sha256") == ACCEPTED_BUILD_ENV_SHA256, "run metadata build digest differs")
    require(
        metadata.get("skip_build") is True
        and metadata.get("signal_identity") == SIGNAL_IDENTITY
        and metadata.get("signal_names") == list(BUSINESS_SIGNALS),
        "run metadata execution contract differs",
    )
    state_root = metadata.get("state_root")
    build_env = metadata.get("build_env")
    require(isinstance(state_root, str) and Path(state_root).is_absolute(), "run metadata state root differs")
    require(isinstance(build_env, str) and Path(build_env).is_absolute(), "run metadata build path differs")
    runner_digest = sha256(read(root, "runner.sh")).hexdigest()
    runner_line = read(root, "runner.sha256")
    require(runner_line == f"{runner_digest}  run-unsafe-case.sh\n".encode(), "runner digest record differs")
    require(metadata.get("runner_sha256") == runner_digest, "run metadata runner digest differs")
    inputs = obj(metadata.get("input_sha256"), "run metadata input digests")
    expected_inputs = {
        "source_requirement": sha256(read(root, "requirement-source.json")).hexdigest(),
        "target_requirement": sha256(read(root, "requirement-target.json")).hexdigest(),
        "source_adapter": sha256(read(root, "source-adapter.json")).hexdigest(),
        "target_adapter": sha256(read(root, "target-adapter.json")).hexdigest(),
        "base_compose": sha256(read(root, "compose-base.yaml")).hexdigest(),
        "overlay": sha256(read(root, "compose-overlay.yaml")).hexdigest(),
        "frozen_inputs": sha256(read(root, "frozen-inputs.env")).hexdigest(),
        "versions": sha256(read(root, "versions.env")).hexdigest(),
        "artifact_contract": sha256(read(root, "ARTIFACTS.md")).hexdigest(),
    }
    require(inputs == expected_inputs, "run metadata static-input digests differ")


def load_yaml(root: Path, name: str) -> dict[str, Any]:
    try:
        return obj(yaml.safe_load(read(root, name)), name)
    except yaml.YAMLError as error:
        raise EvidenceError(f"{name} is not valid YAML") from error


def network_names(service: Mapping[str, Any]) -> set[str]:
    value = service.get("networks", {})
    if isinstance(value, list):
        return set(value)
    return set(obj(value, "service networks"))


def environment_map(service: Mapping[str, Any]) -> dict[str, str]:
    value = service.get("environment", {})
    if isinstance(value, dict):
        require(all(isinstance(key, str) and isinstance(item, (str, int, bool)) for key, item in value.items()), "service environment differs")
        return {key: str(item).lower() if isinstance(item, bool) else str(item) for key, item in value.items()}
    result: dict[str, str] = {}
    for item in arr(value, "service environment"):
        require(isinstance(item, str) and "=" in item, "service environment item differs")
        key, entry = item.split("=", 1)
        require(key not in result, "duplicate service environment")
        result[key] = entry
    return result


def command_list(service: Mapping[str, Any]) -> list[str]:
    value = service.get("command", [])
    require(isinstance(value, list) and all(isinstance(item, str) for item in value), "service command differs")
    return value


def compose_bind_mounts(service: Mapping[str, Any], label: str) -> dict[str, dict[str, Any]]:
    mounts: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(arr(service.get("volumes", []), label + " volumes"), 1):
        mount = obj(raw, f"{label} volume {index}")
        require(mount.get("type") == "bind", f"{label} volume {index} is not a bind mount")
        source = mount.get("source")
        target = mount.get("target")
        require(
            isinstance(source, str) and Path(source).is_absolute()
            and isinstance(target, str) and target.startswith("/") and target not in mounts,
            f"{label} volume {index} source/target differs",
        )
        read_only = mount.get("read_only", False)
        require(type(read_only) is bool, f"{label} volume {index} read_only differs")
        mounts[target] = {"source": source, "read_only": read_only}
    return mounts


def require_path_suffix(value: str, suffix: str, label: str) -> None:
    require(
        Path(value).as_posix().endswith(suffix),
        f"{label} source path differs",
    )


def validate_compose(root: Path, method: str, build: Mapping[str, str]) -> tuple[dict[str, Any], dict[str, Any]]:
    clean = load_yaml(root, "clean-compose-config.yaml")
    main = load_yaml(root, "main-compose-config.yaml")
    clean_all = load_yaml(root, "clean-compose-all-profiles-config.yaml")
    main_all = load_yaml(root, "main-compose-all-profiles-config.yaml")
    common_services = {"temporal", "payment", "completion", "starter"}
    all_services = common_services | {"worker-v1", "worker-unsafe-v2", "worker-v2"}
    if method == "proposed":
        all_services |= {"unsafe-control", "source-adapter", "target-adapter"}
        clean_services = common_services | {"unsafe-control", "target-adapter", "worker-unsafe-v2"}
        main_services = common_services | {"unsafe-control", "source-adapter", "worker-v1"}
        clean_networks = {"control", "effects", "source-runtime", "target-runtime", "target-workload"}
        main_networks = {"control", "effects", "source-runtime", "source-workload", "target-runtime"}
        all_networks = {"control", "effects", "source-workload", "target-workload", "source-runtime", "target-runtime"}
    else:
        clean_services = common_services | {"worker-unsafe-v2"}
        main_services = common_services | {"worker-v1", "worker-unsafe-v2"}
        clean_networks = main_networks = all_networks = {"control", "effects"}
    documents = (
        (clean, "clean selected", clean_services, clean_networks, False),
        (main, "main selected", main_services, main_networks, False),
        (clean_all, "clean all-profiles", all_services, all_networks, True),
        (main_all, "main all-profiles", all_services, all_networks, True),
    )
    for document, label, wanted_services, wanted_networks, all_profiles in documents:
        services = obj(document.get("services"), label + " services")
        require(set(services) == wanted_services, f"{label} resolved service set differs")
        networks = obj(document.get("networks"), label + " networks")
        require(set(networks) == wanted_networks, f"{label} resolved network set differs")
        require(all(obj(spec, "network").get("internal") is True for spec in networks.values()), f"{label} admitted a non-internal network")
        for service_name, raw in services.items():
            service = obj(raw, label + " " + service_name)
            require(not service.get("ports") and not service.get("network_mode"), f"{label} {service_name} gained host/broad network authority")
        require(obj(services["temporal"], "temporal").get("image") == TEMPORAL_IMAGE, f"{label} Temporal image differs")
        if "worker-v1" in services:
            require(obj(services["worker-v1"], "worker-v1").get("image") == SOURCE_IMAGE_ID, f"{label} source image differs")
        if "worker-unsafe-v2" in services:
            require(obj(services["worker-unsafe-v2"], "unsafe target").get("image") == build["TEMPORAL_UNSAFE_WORKER_ID"], f"{label} target image differs")
        require(obj(services["starter"], "starter").get("image") == STARTER_IMAGE_ID, f"{label} starter image differs")
        require(obj(services["payment"], "payment").get("image") == EFFECTS_IMAGE_ID, f"{label} payment image differs")
        require(obj(services["completion"], "completion").get("image") == EFFECTS_IMAGE_ID, f"{label} completion image differs")
        if all_profiles:
            base_v2 = obj(services["worker-v2"], "excluded base v2")
            require(base_v2.get("profiles") == ["excluded-base-worker-v2"], f"{label} unrelated base v2 is not excluded")
            require(base_v2.get("image") == build["WORKER_V2_ID"], f"{label} unrelated base v2 image differs")
            require(network_names(base_v2) == {"control"}, f"{label} excluded base v2 retained provider reachability")
            base_env = environment_map(base_v2)
            require(
                base_env.get("PAYMENT_URL") == base_env.get("COMPLETION_URL") == "http://unreachable.invalid",
                f"{label} excluded base v2 endpoints differ",
            )
    config_services = [
        (obj(document["services"], label + " services"), label)
        for document, label, _wanted_services, _wanted_networks, _all_profiles in documents
    ]
    if method == "proposed":
        expected_graph = {
            "temporal": {"control"}, "starter": {"control"}, "payment": {"effects"}, "completion": {"effects"},
            "worker-v1": {"control", "source-workload"}, "worker-unsafe-v2": {"control", "target-workload"},
            "source-adapter": {"source-workload", "source-runtime"},
            "target-adapter": {"target-workload", "target-runtime"},
            "unsafe-control": {"source-runtime", "target-runtime", "effects"},
            "worker-v2": {"control"},
        }
        for services, label in config_services:
            phase = "clean" if label.startswith("clean") else "main"
            for name, networks in expected_graph.items():
                if name not in services:
                    continue
                require(network_names(obj(services[name], name)) == networks, f"proposed network authority differs for {name}")
            if "worker-v1" in services:
                source_env = environment_map(obj(services["worker-v1"], "source worker"))
                require(source_env.get("PAYMENT_URL") == source_env.get("COMPLETION_URL") == "http://source-adapter:8790", "source worker bypasses adapter")
                require(not obj(services["worker-v1"], "worker-v1").get("volumes"), "source worker received an Operation token or host mount")
            if "worker-unsafe-v2" in services:
                target_env = environment_map(obj(services["worker-unsafe-v2"], "target worker"))
                require(target_env.get("PAYMENT_URL") == target_env.get("COMPLETION_URL") == "http://target-adapter:8790", "target worker bypasses adapter")
                require(not obj(services["worker-unsafe-v2"], "worker-unsafe-v2").get("volumes"), "target worker received an Operation token or host mount")
            control = obj(services["unsafe-control"], "unsafe control")
            require(control.get("image") == CONTROL_IMAGE_ID, "unsafe control image differs")
            require(command_list(control) == CONTROL_COMMAND, "unsafe control command differs")
            control_mounts = compose_bind_mounts(control, "unsafe control")
            require(
                set(control_mounts) == {"/state", "/anchor", "/operation-token"}
                and all(not mount["read_only"] for mount in control_mounts.values()),
                "unsafe control mount authority differs",
            )
            require_path_suffix(control_mounts["/state"]["source"], f"/{phase}/control-state", "unsafe control state")
            require_path_suffix(control_mounts["/anchor"]["source"], f"/{phase}/control-anchor", "unsafe control anchor")
            require_path_suffix(control_mounts["/operation-token"]["source"], f"/{phase}/operation-token", "unsafe control Operation token")
            require(
                len({mount["source"] for mount in control_mounts.values()}) == 3,
                "unsafe control mount sources overlap",
            )
            for name in ({"source-adapter", "target-adapter"} & set(services)):
                adapter = obj(services[name], name)
                require(adapter.get("image") == build["TEMPORAL_UNSAFE_ADAPTER_ID"], f"{name} image differs")
                require(command_list(adapter) == ADAPTER_COMMAND, f"{name} command differs")
                adapter_mounts = compose_bind_mounts(adapter, name)
                require(
                    set(adapter_mounts) == {"/config/adapter.json", "/operation-token"}
                    and all(mount["read_only"] for mount in adapter_mounts.values()),
                    f"{name} mount authority differs",
                )
                require_path_suffix(
                    adapter_mounts["/config/adapter.json"]["source"],
                    f"/runtime/deploy/temporal-unsafe/configs/{name}.json",
                    f"{name} config",
                )
                require_path_suffix(adapter_mounts["/operation-token"]["source"], f"/{phase}/operation-token", f"{name} Operation token")
                require(
                    adapter_mounts["/operation-token"]["source"]
                    == control_mounts["/operation-token"]["source"],
                    f"{name} and control do not share exactly one Operation token directory",
                )
    else:
        for services, _label in config_services:
            require(not ({"unsafe-control", "source-adapter", "target-adapter"} & set(services)), "native lane contains proposed services")
            for worker in ({"worker-v1", "worker-unsafe-v2"} & set(services)):
                service = obj(services[worker], worker)
                require(network_names(service) == {"control", "effects"}, f"native {worker} network differs")
                env = environment_map(service)
                require(env.get("PAYMENT_URL") == "http://payment:8081" and env.get("COMPLETION_URL") == "http://completion:8081", f"native {worker} provider endpoint differs")
                require(not service.get("volumes") and not any(key.startswith("SAFE_CHANGE_") for key in env), f"native {worker} retained proposed authority")
    return clean, main


def service_containers(root: Path, name: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for raw in jarray(root, name):
        item = obj(raw, name + " container")
        labels = obj(obj(item.get("Config"), name + " config").get("Labels"), name + " labels")
        service = labels.get("com.docker.compose.service")
        require(isinstance(service, str) and service and service not in result, f"{name} service labels differ")
        result[service] = item
    return result


def container_network_endpoints(item: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    settings = obj(item.get("NetworkSettings"), "container NetworkSettings")
    networks = obj(settings.get("Networks"), "container networks")
    result: dict[str, dict[str, Any]] = {}
    for network_name, value in networks.items():
        labels = obj(value, "container network endpoint")
        aliases = arr(labels.get("Aliases", []), "network aliases")
        service_aliases = [entry for entry in aliases if isinstance(entry, str) and not re.fullmatch(r"[0-9a-f]{12}", entry)]
        require(service_aliases, "container network has no stable service alias")
        # The first non-container alias is the Compose service; actual network
        # name is recovered from the network inspect artifacts below.
        network_id = labels.get("NetworkID")
        require(isinstance(network_id, str) and network_id, "container network ID differs")
        require(isinstance(network_name, str) and network_name and network_id not in result, "duplicate container network")
        result[network_id] = {"name": network_name, **labels}
    return result


def container_networks(item: Mapping[str, Any]) -> set[str]:
    return set(container_network_endpoints(item))


def check_container_security(item: Mapping[str, Any], label: str) -> None:
    state = obj(item.get("State"), label + " state")
    require(state.get("Running") is True and state.get("Restarting") is False and item.get("RestartCount") == 0, f"{label} is not one stable running container")
    host = obj(item.get("HostConfig"), label + " HostConfig")
    require(host.get("Privileged") is False and host.get("ReadonlyRootfs") is True, f"{label} container isolation differs")
    require(host.get("CapDrop") == ["ALL"] and "no-new-privileges:true" in arr(host.get("SecurityOpt"), label + " security options"), f"{label} Linux privilege boundary differs")
    require(host.get("PortBindings") in ({}, None) and host.get("PublishAllPorts") is False, f"{label} publishes a host port")


def container_bind_mounts(item: Mapping[str, Any], label: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(arr(item.get("Mounts", []), label + " mounts"), 1):
        mount = obj(raw, f"{label} mount {index}")
        require(mount.get("Type") == "bind", f"{label} mount {index} is not a bind mount")
        source = mount.get("Source")
        destination = mount.get("Destination")
        writable = mount.get("RW")
        require(
            isinstance(source, str) and Path(source).is_absolute()
            and isinstance(destination, str) and destination.startswith("/")
            and destination not in result and type(writable) is bool,
            f"{label} mount {index} source/destination/mode differs",
        )
        result[destination] = {"source": source, "read_only": not writable}
    return result


def check_network_inspects(
    root: Path, name: str, expected_logical: set[str],
    containers: Mapping[str, Mapping[str, Any]], project: str,
    expected_service_networks: Mapping[str, set[str]],
) -> None:
    values = jarray(root, name)
    require(len(values) == len(expected_logical), f"{name} network count differs")
    actual_ids: set[str] = set()
    logical: set[str] = set()
    by_id: dict[str, tuple[str, dict[str, Any]]] = {}
    for raw in values:
        network = obj(raw, name + " network")
        require(network.get("Internal") is True and network.get("Attachable") is False, f"{name} contains an egress-capable network")
        labels = obj(network.get("Labels"), name + " network labels")
        require(labels.get("com.docker.compose.project") == project, f"{name} network project differs")
        item = labels.get("com.docker.compose.network")
        require(isinstance(item, str) and item in expected_logical and item not in logical, f"{name} logical network differs")
        logical.add(item)
        network_id = network.get("Id")
        require(isinstance(network_id, str) and network_id and network_id not in actual_ids, f"{name} network identity differs")
        actual_ids.add(network_id)
        network_name = network.get("Name")
        require(network_name == f"{project}_{item}", f"{name} network name differs")
        by_id[network_id] = (item, network)
    require(logical == expected_logical, f"{name} network set differs")
    expected_endpoints: dict[str, dict[str, Mapping[str, Any]]] = {network_id: {} for network_id in actual_ids}
    for service, container in containers.items():
        endpoints = container_network_endpoints(container)
        require(set(endpoints) <= actual_ids, f"{name} {service} is attached outside the isolated project")
        attached_logical = {by_id[network_id][0] for network_id in endpoints}
        require(attached_logical == expected_service_networks[service], f"{name} {service} network authority differs")
        container_id = container.get("Id")
        require(isinstance(container_id, str) and re.fullmatch(r"[0-9a-f]{64}", container_id) is not None, f"{name} {service} container ID differs")
        for network_id, endpoint in endpoints.items():
            require(endpoint["name"] == by_id[network_id][1].get("Name"), f"{name} {service} network name/ID differ")
            require(service in endpoint.get("Aliases", []), f"{name} {service} endpoint lacks its exact service alias")
            expected_endpoints[network_id][container_id] = endpoint
    for network_id, (_logical_name, network) in by_id.items():
        observed = obj(network.get("Containers"), name + " network Containers")
        require(set(observed) == set(expected_endpoints[network_id]), f"{name} network contains a foreign or missing endpoint")
        for container_id, raw_endpoint in observed.items():
            endpoint = obj(raw_endpoint, name + " network endpoint")
            container = next(value for value in containers.values() if value.get("Id") == container_id)
            expected = expected_endpoints[network_id][container_id]
            require(endpoint.get("Name") == str(container.get("Name", "")).removeprefix("/"), f"{name} endpoint container name differs")
            for key in ("EndpointID", "MacAddress"):
                require(endpoint.get(key, "") == expected.get(key, ""), f"{name} endpoint {key} differs")
            ipv4 = str(expected.get("IPAddress", ""))
            if ipv4:
                ipv4 += "/" + str(expected.get("IPPrefixLen"))
            ipv6 = str(expected.get("GlobalIPv6Address", ""))
            if ipv6:
                ipv6 += "/" + str(expected.get("GlobalIPv6PrefixLen"))
            require(endpoint.get("IPv4Address", "") == ipv4, f"{name} endpoint IPv4Address differs")
            require(endpoint.get("IPv6Address", "") == ipv6, f"{name} endpoint IPv6Address differs")


def validate_container_item(
    item: Mapping[str, Any], *, label: str, phase: str,
    service: str, project: str, image: str,
) -> None:
    config = obj(item.get("Config"), label + " config")
    labels = obj(config.get("Labels"), label + " labels")
    require(labels.get("com.docker.compose.project") == project, f"{label} project differs")
    require(labels.get("com.docker.compose.service") == service, f"{label} service differs")
    require(item.get("Image") == image, f"{label} image differs")
    check_container_security(item, label)
    mounts = container_bind_mounts(item, label)
    if service in {"worker-v1", "worker-unsafe-v2"}:
        require(not mounts, f"{label} received a host bind mount")
    elif service in {"source-adapter", "target-adapter"}:
        require(config.get("Cmd") == ADAPTER_COMMAND, f"{label} effective command differs")
        require(
            set(mounts) == {"/config/adapter.json", "/operation-token"}
            and all(mount["read_only"] for mount in mounts.values()),
            f"{label} effective mount authority differs",
        )
        require_path_suffix(
            mounts["/config/adapter.json"]["source"],
            f"/runtime/deploy/temporal-unsafe/configs/{service}.json",
            f"{label} config",
        )
        require_path_suffix(mounts["/operation-token"]["source"], f"/{phase}/operation-token", f"{label} Operation token")
    elif service == "unsafe-control":
        require(config.get("Cmd") == CONTROL_COMMAND, f"{label} effective command differs")
        require(
            set(mounts) == {"/state", "/anchor", "/operation-token"}
            and all(not mount["read_only"] for mount in mounts.values()),
            f"{label} effective mount authority differs",
        )
        require_path_suffix(mounts["/state"]["source"], f"/{phase}/control-state", f"{label} state")
        require_path_suffix(mounts["/anchor"]["source"], f"/{phase}/control-anchor", f"{label} anchor")
        require_path_suffix(mounts["/operation-token"]["source"], f"/{phase}/operation-token", f"{label} Operation token")
        require(len({mount["source"] for mount in mounts.values()}) == 3, f"{label} mount sources overlap")


def validate_container_snapshot(
    root: Path, name: str, *, phase: str, project: str, expected_services: set[str],
    build: Mapping[str, str], expected_networks: set[str],
    service_networks: Mapping[str, set[str]],
    networks_name: str,
) -> dict[str, dict[str, Any]]:
    containers = service_containers(root, name)
    require(set(containers) == expected_services, f"{name} service set differs")
    images = {
        "temporal": TEMPORAL_IMAGE_ID,
        "payment": EFFECTS_IMAGE_ID,
        "completion": EFFECTS_IMAGE_ID,
        "worker-v1": SOURCE_IMAGE_ID,
        "worker-unsafe-v2": build["TEMPORAL_UNSAFE_WORKER_ID"],
        "unsafe-control": CONTROL_IMAGE_ID,
        "source-adapter": build["TEMPORAL_UNSAFE_ADAPTER_ID"],
        "target-adapter": build["TEMPORAL_UNSAFE_ADAPTER_ID"],
    }
    for service, item in containers.items():
        validate_container_item(
            item, label=f"{name} {service}", phase=phase, service=service,
            project=project, image=images[service],
        )
    if "unsafe-control" in containers:
        control_mounts = container_bind_mounts(containers["unsafe-control"], name + " unsafe-control")
        for adapter_name in ({"source-adapter", "target-adapter"} & set(containers)):
            adapter_mounts = container_bind_mounts(containers[adapter_name], name + " " + adapter_name)
            require(
                adapter_mounts["/operation-token"]["source"]
                == control_mounts["/operation-token"]["source"],
                f"{name} {adapter_name} and control do not use the same Operation token directory",
            )
    check_network_inspects(
        root, networks_name, expected_networks, containers, project, service_networks,
    )
    return containers


def service_ipv4(container: Mapping[str, Any], logical_network: str, project: str) -> str:
    settings = obj(obj(container.get("NetworkSettings"), "container network settings").get("Networks"), "container networks")
    endpoint = obj(settings.get(f"{project}_{logical_network}"), f"{logical_network} endpoint")
    address = endpoint.get("IPAddress")
    require(isinstance(address, str) and re.fullmatch(r"(?:[0-9]{1,3}\.){3}[0-9]{1,3}", address) is not None, "container IPv4 address differs")
    require(all(0 <= int(part) <= 255 for part in address.split(".")), "container IPv4 octet differs")
    return address


def validate_network_probes(
    root: Path, name: str, phase: str, method: str,
    project: str, containers: Mapping[str, Mapping[str, Any]],
) -> None:
    value = jobject(root, name)
    exact_fields(value, {"schema", "phase", "probes"}, name)
    require(value.get("schema") == 1 and value.get("phase") == phase, f"{name} schema/phase differs")
    worker = "worker-unsafe-v2" if phase == "clean" else "worker-v1"
    if method == "proposed":
        adapter = "target-adapter" if phase == "clean" else "source-adapter"
        payment_ip = service_ipv4(containers["payment"], "effects", project)
        completion_ip = service_ipv4(containers["completion"], "effects", project)
        control_network = "target-runtime" if phase == "clean" else "source-runtime"
        control_ip = service_ipv4(containers["unsafe-control"], control_network, project)
        expected = {
            (worker, adapter, f"http://{adapter}:8790/healthz", True),
            (worker, "payment-dns-denied", "http://payment:8081/healthz", False),
            (worker, "payment-ip-denied", f"http://{payment_ip}:8081/healthz", False),
            (worker, "completion-dns-denied", "http://completion:8081/healthz", False),
            (worker, "completion-ip-denied", f"http://{completion_ip}:8081/healthz", False),
            (worker, "control-dns-denied", "http://unsafe-control:8787/healthz", False),
            (worker, "control-ip-denied", f"http://{control_ip}:8787/healthz", False),
            (adapter, "control", "http://unsafe-control:8787/healthz", True),
            (adapter, "payment-dns-denied", "http://payment:8081/healthz", False),
            (adapter, "payment-ip-denied", f"http://{payment_ip}:8081/healthz", False),
            ("unsafe-control", "payment", "http://payment:8081/healthz", True),
            ("unsafe-control", "completion", "http://completion:8081/healthz", True),
        }
    else:
        expected = {
            (worker, "payment", "http://payment:8081/healthz", True),
            (worker, "completion", "http://completion:8081/healthz", True),
            (worker, "control", "http://unsafe-control:8787/healthz", False),
            (worker, "adapter", f"http://{'target' if phase == 'clean' else 'source'}-adapter:8790/healthz", False),
        }
    observed: set[tuple[str, str, str, bool]] = set()
    for index, raw in enumerate(arr(value.get("probes"), name + " probes"), 1):
        probe = obj(raw, f"{name} probe {index}")
        exact_fields(
            probe,
            {"phase", "service", "name", "url", "expected_reachable", "exit_status"},
            f"{name} probe {index}",
        )
        require(probe.get("phase") == phase and type(probe.get("expected_reachable")) is bool, f"{name} probe phase/expectation differs")
        status = probe.get("exit_status")
        require(type(status) is int and 0 <= status <= 255, f"{name} probe status differs")
        expected_reachable = probe["expected_reachable"]
        require((status == 0) == expected_reachable, f"{name} probe observation contradicts expectation")
        key = (str(probe.get("service")), str(probe.get("name")), str(probe.get("url")), expected_reachable)
        require(key not in observed, f"{name} duplicate probe")
        observed.add(key)
    require(observed == expected, f"{name} probe matrix differs")


def validate_control_endpoint(
    root: Path, phase: str, project: str,
    control: Mapping[str, Any], logical_network: str,
) -> None:
    value = jobject(root, f"{phase}-control-endpoint.json")
    expected_ip = service_ipv4(control, logical_network, project)
    require(
        value == {
            "schema": 1,
            "network": f"{project}_{logical_network}",
            "container_ip": expected_ip,
            "url": f"http://{expected_ip}:8787",
            "published_ports": False,
        },
        f"{phase} control endpoint differs",
    )


def validate_native_absence(
    root: Path, name: str, phase: str, present_services: set[str],
) -> None:
    value = jobject(root, name)
    require(
        value == {
            "schema": 1, "phase": phase,
            "absent_services": ["unsafe-control", "source-adapter", "target-adapter"],
            "present_services": sorted(present_services),
        },
        f"{name} native-service absence differs",
    )


def validate_proposed_absence(
    root: Path, present_services: set[str],
) -> None:
    value = jobject(root, "main-proposed-target-absence.json")
    require(
        value == {
            "schema": 1, "phase": "main",
            "absent_services": ["target-adapter", "worker-unsafe-v2", "worker-v2"],
            "target_container_ids": [], "target_adapter_container_ids": [],
            "base_worker_v2_container_ids": [],
            "present_services": sorted(present_services),
        },
        "proposed target-absence record differs",
    )


def text_line(root: Path, name: str) -> str:
    data = read(root, name)
    require(data.endswith(b"\n") and data.count(b"\n") == 1, f"{name} is not one newline-terminated line")
    try:
        value = data[:-1].decode("utf-8")
    except UnicodeDecodeError as error:
        raise EvidenceError(f"{name} is not UTF-8") from error
    require(value, f"{name} is empty")
    return value


def docker_event_time(event: Mapping[str, Any], label: str) -> int:
    value = event.get("timeNano")
    require(type(value) is int and value > 0, f"{label} timeNano differs")
    seconds = event.get("time")
    require(type(seconds) is int and seconds == value // 1_000_000_000, f"{label} time differs")
    return value


def timestamp_ns(value: str, label: str) -> int:
    parsed = parse_timestamp(value, label)
    return int(parsed.timestamp() * 1_000_000_000)


def docker_events(root: Path, name: str) -> list[dict[str, Any]]:
    data = read(root, name)
    require(data and data.endswith(b"\n"), f"{name} is empty or unterminated")
    values: list[dict[str, Any]] = []
    for index, line in enumerate(data.splitlines(), 1):
        event = obj(loads(line, f"{name} line {index}"), f"{name} line {index}")
        require(event.get("Type") == "container", f"{name} line {index} is not a container event")
        action = event.get("Action")
        require(isinstance(action, str) and action, f"{name} line {index} action differs")
        if "status" in event:
            require(event["status"] == action, f"{name} line {index} status/action differ")
        docker_event_time(event, f"{name} line {index}")
        actor = obj(event.get("Actor"), f"{name} line {index} actor")
        actor_id = actor.get("ID")
        require(
            isinstance(actor_id, str) and HEX64.fullmatch(actor_id) is not None,
            f"{name} line {index} Actor/container ID differs",
        )
        if "id" in event:
            require(actor_id == event["id"], f"{name} line {index} duplicate container ID differs")
        attrs = obj(actor.get("Attributes"), f"{name} line {index} attributes")
        require(all(isinstance(key, str) and isinstance(value, str) for key, value in attrs.items()), f"{name} line {index} attributes differ")
        values.append(event)
    return values


def validate_docker_events(
    root: Path, phase: str, method: str, project: str, decision_ns: int,
    requested_ns: int | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], bool]:
    begin_id = text_line(root, f"{phase}-event-begin-sentinel-id.txt")
    end_id = text_line(root, f"{phase}-event-end-sentinel-id.txt")
    require(re.fullmatch(r"[0-9a-f]{64}", begin_id) is not None, f"{phase} begin sentinel ID differs")
    require(re.fullmatch(r"[0-9a-f]{64}", end_id) is not None and end_id != begin_id, f"{phase} end sentinel ID differs")
    require(read(root, f"{phase}-event-listener-exit-status.txt") == b"0\n", f"{phase} event listener did not exit cleanly")
    since_ns = timestamp_ns(text_line(root, f"{phase}-events-since-at.txt"), f"{phase} events since")
    ready_ns = timestamp_ns(text_line(root, f"{phase}-event-listener-ready-at.txt"), f"{phase} listener ready")
    ended_ns = timestamp_ns(text_line(root, f"{phase}-event-listener-ended-at.txt"), f"{phase} listener ended")
    require(since_ns <= ready_ns <= ended_ns, f"{phase} listener timestamps differ")
    events = docker_events(root, f"{phase}-docker-events.jsonl")
    sentinel_indices: dict[str, int] = {}
    sentinel_events: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    services: dict[str, list[dict[str, Any]]] = {}
    service_indices: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    container_services: dict[str, str] = {}
    for index, event in enumerate(events):
        actor = obj(event["Actor"], f"{phase} event actor")
        attrs = obj(actor["Attributes"], f"{phase} event attributes")
        require(attrs.get("com.docker.compose.project") == project, f"{phase} event escaped its exact Compose project")
        service = attrs.get("com.docker.compose.service")
        require(isinstance(service, str) and service, f"{phase} event omitted its Compose service")
        actor_id = str(actor["ID"])
        owner = container_services.setdefault(actor_id, service)
        require(owner == service, f"{phase} container ID changed Compose service")
        if service in {"event-sentinel-begin", "event-sentinel-end"}:
            boundary = service.removeprefix("event-sentinel-")
            expected_id = begin_id if boundary == "begin" else end_id
            require(actor.get("ID") == expected_id, f"{phase} {boundary} sentinel ID differs")
            require(attrs.get("io.safe-change.event-sentinel") == "true", f"{phase} sentinel label differs")
            require(attrs.get("io.safe-change.event-boundary") == boundary, f"{phase} sentinel boundary differs")
            require(event.get("Action") in {"create", "destroy"}, f"{phase} sentinel action differs")
            sentinel_events.setdefault(boundary, []).append((index, event))
            if event.get("Action") == "create":
                require(boundary not in sentinel_indices, f"{phase} duplicate {boundary} sentinel create")
                sentinel_indices[boundary] = index
            continue
        services.setdefault(service, []).append(event)
        service_indices.setdefault(service, []).append((index, event))
    require(set(sentinel_indices) == {"begin", "end"}, f"{phase} event stream lacks both sentinels")
    require(set(sentinel_events) == {"begin", "end"}, f"{phase} sentinel lifecycle set differs")
    for boundary, lifecycle in sentinel_events.items():
        creates = [(index, event) for index, event in lifecycle if event.get("Action") == "create"]
        destroys = [(index, event) for index, event in lifecycle if event.get("Action") == "destroy"]
        require(len(lifecycle) == 2 and len(creates) == 1 and len(destroys) == 1, f"{phase} {boundary} sentinel lifecycle differs")
        create_index, create_event = creates[0]
        destroy_index, destroy_event = destroys[0]
        require(create_index < destroy_index, f"{phase} {boundary} sentinel was destroyed before creation")
        require(
            docker_event_time(create_event, f"{phase} {boundary} sentinel create")
            < docker_event_time(destroy_event, f"{phase} {boundary} sentinel destroy"),
            f"{phase} {boundary} sentinel lifecycle time differs",
        )
    begin_index, end_index = sentinel_indices["begin"], sentinel_indices["end"]
    require(begin_index < end_index, f"{phase} sentinel order differs")
    begin_time = docker_event_time(events[begin_index], f"{phase} begin sentinel")
    end_time = docker_event_time(events[end_index], f"{phase} end sentinel")
    require(since_ns <= begin_time <= ready_ns, f"{phase} begin sentinel/listener order differs")
    require(end_time <= ended_ns, f"{phase} end sentinel/listener order differs")
    require(ready_ns < decision_ns < end_time, f"{phase} decision escaped the live event interval")
    if requested_ns is not None:
        require(ready_ns < requested_ns <= decision_ns, f"{phase} requested decision escaped the live event interval")
    for service, values in service_indices.items():
        for index, event in values:
            if event.get("Action") in {"create", "start"}:
                require(begin_index < index < end_index, f"{phase} {service} create/start escaped listener boundaries")
                event_time = docker_event_time(event, f"{phase} {service} create/start")
                require(begin_time < event_time < end_time, f"{phase} {service} create/start timestamp escaped listener boundaries")

    def actions(service: str, action: str) -> list[dict[str, Any]]:
        return [event for event in services.get(service, []) if event.get("Action") == action]

    expected_common = {"temporal", "payment", "completion", "starter"}
    expected_phase = expected_common | ({"worker-unsafe-v2"} if phase == "clean" else {"worker-v1"})
    if method == "proposed":
        expected_phase |= {"unsafe-control", "target-adapter" if phase == "clean" else "source-adapter"}
    if method == "native" and phase == "main":
        expected_phase.add("worker-unsafe-v2")
    require(set(services) <= expected_phase, f"{phase} unexpected service emitted an event: {sorted(set(services)-expected_phase)}")
    for service in expected_phase:
        creates = actions(service, "create")
        starts = actions(service, "start")
        require(len(creates) == 1, f"{phase} {service} create count differs")
        require(len(starts) == 1, f"{phase} {service} start count differs")
        require(events.index(creates[0]) < events.index(starts[0]), f"{phase} {service} started before create")
        require(
            obj(creates[0].get("Actor"), f"{phase} {service} create actor").get("ID")
            == obj(starts[0].get("Actor"), f"{phase} {service} start actor").get("ID"),
            f"{phase} {service} create/start container IDs differ",
        )
    require(not actions("worker-v2", "create") and not actions("worker-v2", "start"), f"{phase} excluded base v2 started")
    target_creates = actions("worker-unsafe-v2", "create")
    target_starts = actions("worker-unsafe-v2", "start")
    if phase == "clean":
        require(
            docker_event_time(target_creates[0], "clean target create") > decision_ns,
            "clean target was created before the target activation decision",
        )
    elif method == "proposed":
        require(not target_creates and not target_starts, "proposed target started despite refusal")
    else:
        source_destroy = actions("worker-v1", "destroy")
        require(len(source_destroy) == 1, "native source worker was not removed exactly once")
        require(
            obj(source_destroy[0].get("Actor"), "native source destroy actor").get("ID")
            == obj(actions("worker-v1", "create")[0].get("Actor"), "native source create actor").get("ID"),
            "native removed a different source container",
        )
        target_create_time = docker_event_time(target_creates[0], "native target create")
        source_destroy_time = docker_event_time(source_destroy[0], "native source destroy")
        require(target_create_time > decision_ns, "native target was created before the decision")
        require(source_destroy_time > decision_ns, "native source was removed before the decision")
        require(source_destroy_time < target_create_time, "native target was created before source removal time")
        require(
            events.index(source_destroy[0]) < events.index(target_creates[0]),
            "native target was created before source removal",
        )
    return services, bool(target_creates and target_starts)


def image_item(root: Path, name: str, expected_id: str) -> dict[str, Any]:
    values = jarray(root, name)
    require(len(values) == 1, f"{name} must contain one image")
    item = obj(values[0], name + " image")
    require(item.get("Id") == expected_id, f"{name} image ID differs")
    return item


def image_labels(item: Mapping[str, Any], label: str) -> dict[str, str]:
    labels = obj(obj(item.get("Config"), label + " config").get("Labels"), label + " labels")
    require(all(isinstance(key, str) and isinstance(value, str) for key, value in labels.items()), f"{label} labels differ")
    return labels  # type: ignore[return-value]


def validate_image_evidence(root: Path, build: Mapping[str, str]) -> None:
    target = image_item(root, "target-image-inspect.json", build["TEMPORAL_UNSAFE_WORKER_ID"])
    labels = image_labels(target, "target image")
    expected = {
        "io.safe-change.source.sha256": build["GENERATED_SOURCE_SHA256"],
        "io.safe-change.build.target": "worker_unsafe_v2",
        "io.safe-change.worker.build-id": TARGET_BUILD,
        "io.safe-change.temporal.frozen-base-source.sha256": FROZEN_BUILD["FROZEN_TEMPORAL_SOURCE_SHA256"],
        "io.safe-change.temporal.patch-set.sha256": build["PATCH_SET_SHA256"],
    }
    require(all(labels.get(key) == value for key, value in expected.items()), "target image provenance labels differ")
    require(obj(target.get("Config"), "target image config").get("Entrypoint") == ["/usr/local/bin/worker"], "target image entrypoint differs")
    source = image_item(root, "v1-image-inspect.json", SOURCE_IMAGE_ID)
    source_labels = image_labels(source, "source image")
    require(source_labels.get("io.safe-change.source.sha256") == FROZEN_BUILD["FROZEN_TEMPORAL_SOURCE_SHA256"], "source image provenance differs")
    require(source_labels.get("io.safe-change.build.target") == "worker_v1" and source_labels.get("io.safe-change.worker.build-id") == SOURCE_BUILD, "source image target differs")
    adapter = image_item(root, "adapter-image-inspect.json", build["TEMPORAL_UNSAFE_ADAPTER_ID"])
    adapter_labels = image_labels(adapter, "adapter image")
    require(adapter_labels.get("io.safe-change.source.sha256") == build["TEMPORAL_UNSAFE_ADAPTER_SOURCE_SHA256"], "adapter source label differs")
    require(obj(adapter.get("Config"), "adapter image config").get("Entrypoint") == ["/usr/local/bin/temporal-provider-adapter"], "adapter entrypoint differs")
    image_item(root, "temporal-image-inspect.json", TEMPORAL_IMAGE_ID)
    starter = image_item(root, "starter-image-inspect.json", STARTER_IMAGE_ID)
    effects = image_item(root, "effects-image-inspect.json", EFFECTS_IMAGE_ID)
    control = image_item(root, "control-image-inspect.json", CONTROL_IMAGE_ID)
    require(
        obj(starter.get("Config"), "starter image config").get("Entrypoint")
        == ["/usr/local/bin/starter"],
        "starter image entrypoint differs",
    )
    require(
        obj(effects.get("Config"), "effects image config").get("Entrypoint")
        in (["/usr/local/bin/payment"], ["/usr/local/bin/effects"]),
        "effects image entrypoint differs",
    )
    require(
        obj(control.get("Config"), "control image config").get("Entrypoint")
        in (["/usr/local/bin/control"], None),
        "control image entrypoint differs",
    )
    verified = parse_env(read(root, "binary-verification.env"), "binary-verification.env")
    expected_binaries = {
        "WORKER_V1_BINARY_SHA256": build["WORKER_V1_BINARY_SHA256"],
        "TEMPORAL_UNSAFE_WORKER_BINARY_SHA256": build["TEMPORAL_UNSAFE_WORKER_BINARY_SHA256"],
        "STARTER_BINARY_SHA256": build["STARTER_BINARY_SHA256"],
        "EFFECTS_BINARY_SHA256": build["EFFECTS_BINARY_SHA256"],
        "TEMPORAL_UNSAFE_ADAPTER_BINARY_SHA256": build["TEMPORAL_UNSAFE_ADAPTER_BINARY_SHA256"],
        "CONTROL_BINARY_SHA256": build["CONTROL_BINARY_SHA256"],
    }
    require(verified == expected_binaries, "extracted immutable-image binaries differ")


def _skip_space(data: bytes, position: int) -> int:
    while position < len(data) and data[position] in b" \t\r\n":
        position += 1
    return position


def _string_end(data: bytes, position: int) -> int:
    require(position < len(data) and data[position] == ord('"'), "History member name is not a string")
    position += 1
    while position < len(data):
        if data[position] == ord('"'):
            return position + 1
        if data[position] == ord("\\"):
            position += 2
        else:
            position += 1
    raise EvidenceError("unterminated History string")


def _value_end(data: bytes, position: int) -> int:
    require(position < len(data), "History value is absent")
    if data[position] == ord('"'):
        return _string_end(data, position)
    if data[position] in (ord("{"), ord("[")):
        stack = [data[position]]
        position += 1
        while position < len(data) and stack:
            byte = data[position]
            if byte == ord('"'):
                position = _string_end(data, position)
                continue
            if byte in (ord("{"), ord("[")):
                stack.append(byte)
            elif byte in (ord("}"), ord("]")):
                expected = ord("}") if stack[-1] == ord("{") else ord("]")
                require(byte == expected, "mismatched History delimiter")
                stack.pop()
            position += 1
        require(not stack, "unterminated History value")
        return position
    while position < len(data) and data[position] not in b",}] \t\r\n":
        position += 1
    return position


def _raw_member(data: bytes, wanted: str) -> bytes:
    position = _skip_space(data, 0)
    require(position < len(data) and data[position] == ord("{"), "History frame is not an object")
    position += 1
    found: bytes | None = None
    while True:
        position = _skip_space(data, position)
        require(position < len(data), "unterminated History frame")
        if data[position] == ord("}"):
            break
        key_end = _string_end(data, position)
        key = loads(data[position:key_end], "History member name")
        position = _skip_space(data, key_end)
        require(position < len(data) and data[position] == ord(":"), "History member has no colon")
        start = _skip_space(data, position + 1)
        end = _value_end(data, start)
        if key == wanted:
            require(found is None, f"duplicate History member {wanted}")
            found = data[start:end]
        position = _skip_space(data, end)
        require(position < len(data), "unterminated History frame")
        if data[position] == ord(","):
            position += 1
            continue
        require(data[position] == ord("}"), "invalid History object separator")
        break
    require(found is not None, f"History omitted {wanted}")
    return found


def _hash_part(value: bytes) -> bytes:
    return struct.pack(">Q", len(value)) + value


def history_event_hash(sequence: int, previous: str, operation: str, data: bytes) -> str:
    digest = sha256()
    digest.update(b"history-event-v1\0")
    digest.update(struct.pack(">Q", sequence))
    digest.update(_hash_part(previous.encode()))
    digest.update(_hash_part(operation.encode()))
    digest.update(_hash_part(data))
    return digest.hexdigest()


def binary_history(root: Path, name: str) -> list[dict[str, Any]]:
    raw = read(root, name, MAX_HISTORY_BYTES)
    offset = 0
    previous = ZERO_HASH
    events: list[dict[str, Any]] = []
    while offset < len(raw):
        require(len(raw) - offset >= 12 and raw[offset:offset + 4] == b"HST1", "History frame header is invalid")
        length = struct.unpack(">Q", raw[offset + 4:offset + 12])[0]
        require(0 < length <= MAX_FRAME_BYTES, "History frame length is invalid")
        start, end = offset + 12, offset + 12 + length
        require(end <= len(raw), "History final frame is incomplete")
        payload = raw[start:end]
        stored = obj(loads(payload, f"History frame {len(events)+1}"), "History frame")
        exact_fields(stored, {"version", "sequence", "operation", "data", "previous_hash", "hash"}, "History frame")
        sequence, operation = stored.get("sequence"), stored.get("operation")
        require(stored.get("version") == 1 and type(sequence) is int and sequence == len(events) + 1, "History sequence/version differs")
        require(isinstance(operation, str) and operation, "History operation is absent")
        require(stored.get("previous_hash") == previous, "History previous hash differs")
        current = stored.get("hash")
        require(isinstance(current, str) and HEX64.fullmatch(current) is not None, "History event hash differs")
        require(current == history_event_hash(sequence, previous, operation, _raw_member(payload, "data")), "History frame hash is invalid")
        events.append({"sequence": sequence, "operation": operation, "data": stored["data"], "previous_hash": previous, "hash": current})
        previous = current
        offset = end
    require(events, "History is empty")
    return events


def check_history_head(root: Path, name: str, events: Sequence[Mapping[str, Any]]) -> None:
    raw = read(root, name)
    value = obj(loads(raw, name), name)
    sequence, history_hash = len(events), events[-1]["hash"]
    checksum = sha256(b"history-head-anchor-v1\0" + struct.pack(">Q", sequence) + str(history_hash).encode()).hexdigest()
    expected = {"version": 1, "sequence": sequence, "hash": history_hash, "checksum": checksum}
    require(value == expected, "History head differs from binary replay")
    require(raw == json.dumps(expected, separators=(",", ":")).encode() + b"\n", "History head is not canonical")


def fresh_certificate(root: Path, runtime_root: Path, stem: str) -> tuple[dict[str, Any], dict[str, Any]]:
    certificate = jobject(root, stem + ".json")
    state_name, verdict_name = stem + "-state.json", stem + "-verdict.json"
    state, recorded = jobject(root, state_name), jobject(root, verdict_name)
    completed = subprocess.run(
        ["go", "run", "./cmd/check-certificate", "-state", str(root / state_name), "-certificate", str(root / (stem + ".json"))],
        cwd=runtime_root, capture_output=True, text=True, timeout=120, check=False,
    )
    require(completed.returncode == 0, f"fresh {stem} validation failed: {completed.stderr.strip()}")
    fresh = obj(loads(completed.stdout.encode(), "fresh Certificate verdict"), "fresh Certificate verdict")
    require(fresh == recorded, f"fresh {stem} verdict differs from the archived verdict")
    return certificate, state


def validate_control_operation(
    value: Any, *, kind: str, expected_id: str, expected_body: bytes,
    requirement_kind: Mapping[str, Any], provider_record: Mapping[str, Any], label: str,
) -> None:
    operation = obj(value, label)
    require(operation.get("id") == expected_id and operation.get("domain") == OPERATION_DOMAIN, f"{label} identity/domain differs")
    require(operation.get("kind") == kind and operation.get("rule_version") == 1, f"{label} kind/Rule version differs")
    for field in (
        "costs", "produces", "retry_safe", "queryable", "target", "method",
        "response_classifier", "query_target", "query_method", "query_classifier",
    ):
        if field in requirement_kind:
            require(operation.get(field) == requirement_kind[field], f"{label} {field} differs")
        else:
            require(field not in operation, f"{label} invented {field}")
    require(operation.get("request_headers") == {"Content-Type": "application/json"}, f"{label} caller headers differ")
    target = requirement_kind.get("target")
    require(isinstance(target, str), f"{label} target is absent")
    require(operation.get("request_hash") == gateway_request_hash(target, expected_id, expected_body), f"{label} durable request hash differs")
    require(operation.get("request_stored") is True, f"{label} did not retain exact request bytes")
    try:
        stored_body = base64.b64decode(str(operation.get("request_body")), validate=True)
    except (ValueError, binascii.Error) as error:
        raise EvidenceError(f"{label} request body is not base64") from error
    require(stored_body == expected_body, f"{label} stored request body differs")
    require(operation.get("phase") == "succeeded" and operation.get("status_code") == 200, f"{label} is not succeeded")
    require(operation.get("result_hash") == provider_record["result_hash"], f"{label} result fact differs")
    require(operation.get("remote_reference") == provider_record["remote_reference"], f"{label} remote reference differs")
    try:
        result_body = base64.b64decode(str(operation.get("result_body")), validate=True)
    except (ValueError, binascii.Error) as error:
        raise EvidenceError(f"{label} result body is not base64") from error
    require(obj(loads(result_body, label + " result body"), label + " result body") == receipt(provider_record), f"{label} result body differs from provider receipt")


def validate_clean_control(
    root: Path, target: Mapping[str, Any], clean_order: str,
    payment_record: Mapping[str, Any], completion_record: Mapping[str, Any],
    certificate: Mapping[str, Any],
) -> None:
    events = binary_history(root, "clean-runtime.history")
    check_history_head(root, "clean-runtime.head", events)
    require(jvalue(root, "clean-final-control-history.json") == events, "clean binary and API control Histories differ")
    require(
        [event.get("operation") for event in events]
        == ["rule.activated", "operation.prepared", "operation.phase", "operation.phase", "operation.prepared", "operation.phase", "operation.phase"],
        "clean control History shape differs",
    )
    activation = obj(obj(events[0].get("data"), "clean activation data").get("certificate"), "clean activation Certificate")
    require(activation == certificate, "clean binary History activated a different target Certificate")
    require(activation.get("decision") == "activate" and activation.get("requirement") == target, "clean target Certificate was not activated")
    require(activation.get("history") == {"sequence": 0, "hash": ZERO_HASH}, "clean activation did not begin from empty History")
    require(activation.get("rule", {}).get("allow") == ["charge-v2", "finish-v2"], "clean activated Rule differs")
    activated = jobject(root, "clean-active-target.json")
    after_activate = jobject(root, "clean-control-after-activate.json")
    require(activated == after_activate, "clean activation response/state differ")
    require(
        activated.get("requirement") == target
        and activated.get("rule", {}).get("allow") == ["charge-v2", "finish-v2"]
        and activated.get("operations") == {},
        "clean activated target state differs",
    )
    require(
        jvalue(root, "clean-control-history-after-activate.json") == events[:1],
        "clean control History after activation differs",
    )
    require(activated.get("history") == {"sequence": 1, "hash": events[0]["hash"]}, "clean activated state head differs")
    state = jobject(root, "clean-final-control-state.json")
    require(state.get("history") == {"sequence": len(events), "hash": events[-1]["hash"]}, "clean final State head differs")
    require(state.get("requirement") == target, "clean target Requirement was not active during execution")
    require(state.get("rule", {}).get("version") == 1 and state.get("rule", {}).get("allow") == ["charge-v2"], "clean final Rule differs")
    operations = obj(state.get("operations"), "clean target Operations")
    payment_id, completion_id = operation_id(clean_order), operation_id("complete:" + clean_order)
    require(set(operations) == {payment_id, completion_id}, "clean target Operation set differs")
    kinds = obj(target.get("kinds"), "target kinds")
    validate_control_operation(
        operations[payment_id], kind="charge-v2", expected_id=payment_id,
        expected_body=effect_body(clean_order), requirement_kind=obj(kinds["charge-v2"], "charge-v2"),
        provider_record=payment_record, label="clean charge-v2",
    )
    validate_control_operation(
        operations[completion_id], kind="finish-v2", expected_id=completion_id,
        expected_body=effect_body(clean_order, "unsafe-v2"), requirement_kind=obj(kinds["finish-v2"], "finish-v2"),
        provider_record=completion_record, label="clean finish-v2",
    )
    used = sum(obj(operation.get("costs"), "clean Operation costs").get("approval", 0) for operation in operations.values())
    results: dict[str, int] = {}
    for operation in operations.values():
        for name, amount in obj(operation.get("produces"), "clean Operation results").items():
            results[name] = results.get(name, 0) + amount
    require(used == 1 and results.get("paid") == 1 and results.get("delivered") == 1, "clean target did not satisfy capacity/results")


def validate_certificate_semantics(
    root: Path, runtime_root: Path, source: Mapping[str, Any], target: Mapping[str, Any],
    clean_order: str, main_order: str, clean_payment: Mapping[str, Any],
    clean_completion: Mapping[str, Any], main_payment: Mapping[str, Any],
    main_completion: Mapping[str, Any],
) -> None:
    clean, clean_state = fresh_certificate(root, runtime_root, "clean-certificate-target")
    require(clean.get("decision") == "activate" and clean.get("requirement") == target, "empty-History Certificate differs")
    require(clean.get("history") == {"sequence": 0, "hash": ZERO_HASH}, "empty-History Certificate is not empty-bound")
    require(clean.get("rule", {}).get("allow") == ["charge-v2", "finish-v2"], "empty-History Rule differs")
    require(clean_state.get("settled") == {"used": {}, "results": {}} and clean_state.get("open_operations") == {}, "empty-History state invented progress")
    validate_clean_control(root, target, clean_order, clean_payment, clean_completion, clean)
    source_certificate, source_state = fresh_certificate(root, runtime_root, "main-certificate-source")
    require(
        source_certificate.get("decision") == "activate"
        and source_certificate.get("requirement") == source
        and source_certificate.get("history") == {"sequence": 0, "hash": ZERO_HASH}
        and source_certificate.get("rule", {}).get("allow") == ["charge-v1", "finish-v1"],
        "empty-History source Certificate differs",
    )
    require(
        source_state.get("settled") == {"used": {}, "results": {}}
        and source_state.get("open_operations") == {},
        "empty-History source Certificate state invented progress",
    )
    unsafe, unsafe_state = fresh_certificate(root, runtime_root, "main-certificate-unsafe")
    require(unsafe.get("decision") == "impossible" and unsafe.get("requirement") == target and unsafe.get("rule") is None, "unsafe Certificate did not refuse target")
    require(unsafe.get("witness") == {"reason": "no completion fits the remaining resources for delivered:1"}, "unsafe impossibility witness differs")
    require(unsafe_state.get("settled") == {"used": {"approval": 1}, "results": {"paid": 1}} and unsafe_state.get("open_operations") == {}, "unsafe Certificate state differs")
    at_cut = jobject(root, "main-control-at-cut.json")
    after = jobject(root, "main-control-after-refusal.json")
    require(unsafe.get("history") == at_cut.get("history") == unsafe_state.get("history"), "unsafe Certificate/State control head differs")
    require(unsafe.get("from_rule") == unsafe_state.get("from_rule") == 1, "unsafe Certificate Rule lineage differs")
    require(at_cut == after, "compile refusal changed control state")
    require(read(root, "main-control-history-at-cut.json") == read(root, "main-control-history-after-refusal.json"), "compile refusal changed control History")
    require(at_cut.get("requirement") == source and at_cut.get("rule", {}).get("allow") == ["finish-v1"], "source Rule at cut differs")
    operations = obj(at_cut.get("operations"), "source Operations at cut")
    charge = [value for value in operations.values() if isinstance(value, dict) and value.get("kind") == "charge-v1" and value.get("phase") == "succeeded"]
    require(len(operations) == len(charge) == 1, "control cut does not contain exactly one succeeded charge-v1")
    require(set(operations) == {operation_id(main_order)}, "control cut Operation map key differs")
    validate_control_operation(
        charge[0], kind="charge-v1", expected_id=operation_id(main_order),
        expected_body=effect_body(main_order),
        requirement_kind=obj(obj(source.get("kinds"), "source kinds")["charge-v1"], "charge-v1"),
        provider_record=main_payment, label="main charge-v1",
    )
    events = binary_history(root, "main-runtime.history")
    check_history_head(root, "main-runtime.head", events)
    require(jvalue(root, "main-final-control-history.json") == events, "binary and API control Histories differ")
    require(
        [event.get("operation") for event in events]
        == ["rule.activated", "operation.prepared", "operation.phase", "operation.phase", "operation.prepared", "operation.phase", "operation.phase"],
        "main control History shape differs",
    )
    activation = obj(obj(events[0].get("data"), "main activation data").get("certificate"), "main activation Certificate")
    require(activation == source_certificate, "main binary History activated a different source Certificate")
    activated = jobject(root, "main-active-source.json")
    after_activate = jobject(root, "main-control-after-source-activate.json")
    require(activated == after_activate, "main source activation response/state differ")
    require(
        activated.get("requirement") == source
        and activated.get("rule", {}).get("allow") == ["charge-v1", "finish-v1"]
        and activated.get("operations") == {},
        "main activated source state differs",
    )
    require(
        jvalue(root, "main-control-history-after-source-activate.json") == events[:1],
        "main control History after source activation differs",
    )
    require(activated.get("history") == {"sequence": 1, "hash": events[0]["hash"]}, "main activated state head differs")
    require(jvalue(root, "main-control-history-at-cut.json") == events[:4], "main control cut History differs")
    require(at_cut.get("history") == {"sequence": 4, "hash": events[3]["hash"]}, "main control cut State head differs")
    final = jobject(root, "main-final-control-state.json")
    require(final.get("history") == {"sequence": len(events), "hash": events[-1]["hash"]}, "main final State head differs")
    require(final.get("requirement") == source and final.get("rule", {}).get("allow") == ["finish-v1"], "source Rule was not retained")
    final_ops = obj(final.get("operations"), "final source Operations")
    payment_id = operation_id(main_order)
    completion_id = operation_id("complete:" + main_order)
    require(set(final_ops) == {payment_id, completion_id}, "final source Operation identities differ")
    require(final_ops[payment_id] == operations[payment_id], "final source State rewrote the settled payment")
    finishes = [value for value in final_ops.values() if isinstance(value, dict) and value.get("kind") == "finish-v1" and value.get("phase") == "succeeded"]
    require(len(final_ops) == 2 and len(finishes) == 1, "retained source did not finish through finish-v1")
    validate_control_operation(
        finishes[0], kind="finish-v1", expected_id=operation_id("complete:" + main_order),
        expected_body=effect_body(main_order),
        requirement_kind=obj(obj(source.get("kinds"), "source kinds")["finish-v1"], "finish-v1"),
        provider_record=main_completion, label="main finish-v1",
    )


def evidence_digest(root: Path, names: Iterable[str]) -> str:
    hashes = {name: sha256(read(root, name)).hexdigest() for name in sorted(set(names))}
    return sha256(json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def substantive_history_digest(events: Sequence[Mapping[str, Any]]) -> str:
    # Temporal Go gathers language flags from a map. Their wire order is not a
    # workflow command and must not make matched decision cuts look different.
    semantic = json.loads(json.dumps(events))
    for event in semantic:
        attrs = event.get("workflowTaskCompletedEventAttributes")
        if not isinstance(attrs, dict):
            continue
        sdk = attrs.get("sdkMetadata")
        if isinstance(sdk, dict) and isinstance(sdk.get("langUsedFlags"), list):
            sdk["langUsedFlags"] = sorted(sdk["langUsedFlags"])
    return sha256(json.dumps(semantic, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def names(value: str) -> set[str]:
    return set(value.split())


# Exact top-level success contract from ARTIFACTS.md. The sole directory is
# build-evidence/, validated recursively and against its independently frozen
# manifest by verify_checksums(). observed.json is packaged but never used as
# a verdict oracle or included in the scientific digest.
GLOBAL_FILES = names("""
ARTIFACTS.md build.env frozen-inputs.env versions.env runner.sh runner.sha256
compose-base.yaml compose-overlay.yaml requirement-source.json
requirement-target.json source-adapter.json target-adapter.json
git-revision.txt git-status.txt compose-environment.json
temporal-image-inspect.json v1-image-inspect.json target-image-inspect.json
starter-image-inspect.json effects-image-inspect.json
adapter-image-inspect.json control-image-inspect.json
binary-verification.env run-metadata.json observed.json exit-status.txt
SHA256SUMS
""")

EVENT_FILES = names("""
clean-events-since-at.txt clean-event-begin-sentinel-id.txt
clean-event-listener-ready-at.txt clean-event-end-sentinel-id.txt
clean-event-listener-ended-at.txt clean-event-listener-exit-status.txt
clean-docker-events.jsonl main-events-since-at.txt
main-event-begin-sentinel-id.txt main-event-listener-ready-at.txt
main-event-end-sentinel-id.txt main-event-listener-ended-at.txt
main-event-listener-exit-status.txt main-docker-events.jsonl
""")

CLEAN_COMMON_FILES = names("""
clean-compose-config.yaml clean-compose-all-profiles-config.yaml
clean-invocation.json clean-start.json clean-run-id.txt
clean-target-containers-before-decision.txt clean-decision-at.txt
clean-target-workflow-pollers.json clean-target-activity-pollers.json
clean-deployment-before-current.json clean-target-version-before-current.json
clean-set-current-target.json clean-deployment-target-current.json
clean-wait-history.json clean-wait-describe.json clean-wait-query.json
clean-payment-wait-stats.json clean-completion-wait-stats.json
clean-payment-wait.history clean-completion-wait.history clean-signal.json
clean-signal-driver-selected.json clean-signal-driver-at-restaurant.json
clean-signal-delivery-finished.json
clean-final-history.json clean-final-describe.json clean-final-query.json
clean-target-version-final.json clean-deployment-final.json
clean-payment-final-stats.json clean-completion-final-stats.json
clean-payment-final.history clean-completion-final.history
clean-target-container.json clean-network-probes.json clean-compose-ps.txt
clean-compose.log clean-containers.json clean-networks.json
""")

MAIN_COMMON_FILES = names("""
main-compose-config.yaml main-compose-all-profiles-config.yaml
main-invocation.json main-start.json main-run-id.txt
main-source-workflow-pollers.json main-source-activity-pollers.json
main-deployment-before-current.json main-source-version-before-current.json
main-set-current-source.json main-deployment-source-current.json
main-cut-history.json main-cut-describe.json main-cut-query.json
main-cut-deployment.json main-cut-source-version.json
main-payment-cut-stats.json main-completion-cut-stats.json
main-payment-cut.history main-completion-cut.history
main-source-container-at-cut.json main-target-containers-before-decision.txt
main-worker-v2-containers-before-decision.txt
main-containers-before-decision.json main-networks-before-decision.json
main-network-probes.json main-decision-requested-at.txt
main-decision-recorded-at.txt main-history-after-decision.json
main-payment-after-decision-stats.json
main-completion-after-decision-stats.json
main-payment-after-decision.history main-completion-after-decision.history
main-signal.json main-signal-driver-selected.json
main-signal-driver-at-restaurant.json main-signal-delivery-finished.json
main-final-history.json main-final-describe.json
main-final-query.json main-payment-final-stats.json
main-completion-final-stats.json main-payment-final.history
main-completion-final.history main-deployment-final.json
main-compose-ps.txt main-compose.log main-containers.json main-networks.json
""")

PROPOSED_FILES = names("""
clean-control-endpoint.json clean-control-container.json
clean-certificate-target.json clean-certificate-target-state.json
clean-certificate-target-verdict.json clean-active-target.json
clean-control-after-activate.json clean-control-history-after-activate.json
clean-final-control-state.json clean-final-control-history.json
clean-runtime.history clean-runtime.head
main-control-endpoint.json main-control-container.json
main-certificate-source.json main-certificate-source-state.json
main-certificate-source-verdict.json main-active-source.json
main-control-after-source-activate.json
main-control-history-after-source-activate.json main-control-at-cut.json
main-control-history-at-cut.json main-certificate-unsafe.json
main-certificate-unsafe-state.json main-certificate-unsafe-verdict.json
main-control-after-refusal.json main-control-history-after-refusal.json
main-final-source-container.json main-final-source-version.json
main-final-control-state.json main-final-control-history.json
main-runtime.history main-runtime.head main-proposed-target-absence.json
""")

NATIVE_FILES = names("""
clean-native-absence.json main-native-absence.json main-remove-source.txt
main-source-removed-inspect.json main-source-removed-inspect.stderr
main-source-removed-inspect-status.txt main-target-workflow-pollers.json
main-target-activity-pollers.json main-target-version-before-current.json
main-set-current-target.json main-deployment-target-current.json
main-target-container.json main-target-version-final.json
""")

COMMON_FILES = GLOBAL_FILES | EVENT_FILES | CLEAN_COMMON_FILES | MAIN_COMMON_FILES


def check(path: Path, runtime_root: Path) -> dict[str, Any]:
    root = evidence_root(path)
    runtime_root = runtime_root.resolve(strict=True)
    metadata = jobject(root, "run-metadata.json")
    method = metadata.get("method")
    require(method in {"proposed", "native"}, "run method differs")
    required = COMMON_FILES | (PROPOSED_FILES if method == "proposed" else NATIVE_FILES)
    require(required, "checker artifact contract has not been finalized")
    all_files = verify_checksums(root, required)
    require(read(root, "exit-status.txt") == b"0\n", "runner did not complete")
    require(metadata.get("schema") == 1 and metadata.get("cell") == CELL, "run metadata schema/cell differs")
    clean_order, main_order = metadata.get("clean_order_id"), metadata.get("main_order_id")
    clean_workflow, main_workflow = metadata.get("clean_workflow_id"), metadata.get("main_workflow_id")
    for value, label in ((clean_order, "clean order"), (main_order, "main order"), (clean_workflow, "clean workflow"), (main_workflow, "main workflow")):
        require(isinstance(value, str) and STABLE_ID.fullmatch(value) is not None, f"{label} identity differs")
    require(clean_order != main_order and clean_workflow != main_workflow, "clean and main identities overlap")

    build_bytes = read(root, "build.env")
    require(sha256(build_bytes).hexdigest() == ACCEPTED_BUILD_ENV_SHA256, "build.env differs from the accepted image build")
    build = parse_env(build_bytes, "build.env")
    require(set(build) == FROZEN_BUILD_KEYS, "build.env key set differs from the accepted image build")
    for key, value in FROZEN_BUILD.items():
        require(build.get(key) == value, f"frozen build key differs: {key}")
    require(build.get("TEMPORAL_IMAGE") == TEMPORAL_IMAGE, "Temporal reference differs")
    require(build.get("TEMPORAL_IMAGE_ID") == TEMPORAL_IMAGE_ID, "Temporal image identity differs")
    require(IMAGE_ID.fullmatch(str(build.get("TEMPORAL_UNSAFE_WORKER_ID"))) is not None, "target image is not immutable")
    require(build.get("TEMPORAL_UNSAFE_WORKER_ID") == build.get("PROPOSED_UNSAFE_WORKER_ID") == build.get("NATIVE_UNSAFE_WORKER_ID") == build.get("WORKER_UNSAFE_V2_ID"), "proposed/native target image IDs differ")
    require(build.get("PROPOSED_NATIVE_IMAGE_ID_EQUAL") == "true", "target image equality attestation differs")
    require(IMAGE_ID.fullmatch(str(build.get("TEMPORAL_UNSAFE_ADAPTER_ID"))) is not None, "adapter image is not immutable")
    require(HEX40.fullmatch(str(build.get("GIT_REVISION"))) is not None, "build Git revision differs")
    require_commit(REPO_ROOT, build["GIT_REVISION"])
    require_commit(REPO_ROOT, build["FROZEN_GIT_REVISION"])
    recorded_revision = text_line(root, "git-revision.txt")
    require_commit(REPO_ROOT, recorded_revision)
    try:
        read(root, "git-status.txt").decode("utf-8")
    except UnicodeDecodeError as error:
        raise EvidenceError("git-status.txt is not UTF-8") from error
    for name, digest in FROZEN_INPUT_SHA256.items():
        require(sha256(read(root, name)).hexdigest() == digest, f"archived build/topology input differs: {name}")
    require(
        sha256(read(root, "compose-overlay.yaml")).hexdigest() == OVERLAY_SHA256[method],
        "archived method overlay differs",
    )
    require(read(root, "build.env") == read(root, "build-evidence/build.env"), "case and build-evidence build.env differ")
    require(read(root, "compose-base.yaml") == read(root, "build-evidence/topology/compose-base.yaml"), "base Compose copy differs from build evidence")
    require(read(root, "compose-overlay.yaml") == read(root, f"build-evidence/topology/compose-{method}.yaml"), "overlay differs from build evidence")
    require(read(root, "source-adapter.json") == read(root, "build-evidence/topology/source-adapter.json"), "source adapter copy differs from build evidence")
    require(read(root, "target-adapter.json") == read(root, "build-evidence/topology/target-adapter.json"), "target adapter copy differs from build evidence")
    validate_build_evidence(root, build)
    source, target = expected_requirements()
    require(jobject(root, "requirement-source.json") == source, "source Requirement differs")
    require(jobject(root, "requirement-target.json") == target, "target Requirement differs")
    require(semantic_target_feasible(target, False), "target is not feasible from empty History")
    require(not semantic_target_feasible(target, True), "target is feasible after the old charge")

    validate_metadata(
        root, metadata, method, clean_order, main_order,
        clean_workflow, main_workflow, build,
    )

    validate_compose(root, method, build)
    validate_image_evidence(root, build)

    compose_environment = jobject(root, "compose-environment.json")
    require(
        compose_environment == {
            "schema": 1,
            "ambient": {
                "COMPOSE_FILE": "", "COMPOSE_PROFILES": "",
                "COMPOSE_PROJECT_NAME": "", "COMPOSE_PATH_SEPARATOR": "",
                "COMPOSE_ENV_FILES": "", "COMPOSE_DISABLE_ENV_FILE": "",
            },
            "explicit_projects": {
                "clean": metadata.get("clean_project"),
                "main": metadata.get("main_project"),
            },
            "profiles_enabled": [],
        },
        "explicit Compose environment/project binding differs",
    )
    clean_project = metadata.get("clean_project")
    main_project = metadata.get("main_project")
    require(
        isinstance(clean_project, str) and isinstance(main_project, str)
        and re.fullmatch(r"[a-z0-9][a-z0-9_-]{2,96}", clean_project) is not None
        and re.fullmatch(r"[a-z0-9][a-z0-9_-]{2,96}", main_project) is not None
        and clean_project != main_project,
        "clean/main Compose project identities differ",
    )
    validate_invocation(
        root, "clean-invocation.json", phase="clean", method=method,
        project=clean_project, workflow_id=clean_workflow,
        order_id=clean_order, source_build=TARGET_BUILD,
    )
    validate_invocation(
        root, "main-invocation.json", phase="main", method=method,
        project=main_project, workflow_id=main_workflow,
        order_id=main_order, source_build=SOURCE_BUILD,
    )
    clean_decision_ns = timestamp_ns(text_line(root, "clean-decision-at.txt"), "clean decision")
    requested_ns = timestamp_ns(text_line(root, "main-decision-requested-at.txt"), "main decision requested")
    recorded_ns = timestamp_ns(text_line(root, "main-decision-recorded-at.txt"), "main decision recorded")
    require(requested_ns <= recorded_ns, "main decision timestamp order differs")
    clean_service_events, clean_target_started = validate_docker_events(
        root, "clean", method, clean_project, clean_decision_ns,
    )
    main_service_events, main_target_started = validate_docker_events(
        root, "main", method, main_project, recorded_ns, requested_ns,
    )
    require(clean_target_started, "clean exact target never started")
    require(read(root, "clean-target-containers-before-decision.txt") == b"", "clean target existed before decision")
    require(read(root, "main-target-containers-before-decision.txt") == b"", "main target existed before decision")
    require(read(root, "main-worker-v2-containers-before-decision.txt") == b"", "excluded base v2 existed before decision")

    if method == "proposed":
        clean_services = {"temporal", "payment", "completion", "unsafe-control", "target-adapter", "worker-unsafe-v2"}
        clean_service_networks = {
            "temporal": {"control"}, "payment": {"effects"}, "completion": {"effects"},
            "unsafe-control": {"source-runtime", "target-runtime", "effects"},
            "target-adapter": {"target-workload", "target-runtime"},
            "worker-unsafe-v2": {"control", "target-workload"},
        }
        main_before_services = main_final_services = {
            "temporal", "payment", "completion", "unsafe-control", "source-adapter", "worker-v1",
        }
        main_before_networks = main_final_networks = {
            "control", "effects", "source-runtime", "source-workload", "target-runtime",
        }
        main_before_service_networks = main_final_service_networks = {
            "temporal": {"control"}, "payment": {"effects"}, "completion": {"effects"},
            "unsafe-control": {"source-runtime", "target-runtime", "effects"},
            "source-adapter": {"source-workload", "source-runtime"},
            "worker-v1": {"control", "source-workload"},
        }
        clean_networks = {"control", "effects", "source-runtime", "target-runtime", "target-workload"}
    else:
        clean_services = {"temporal", "payment", "completion", "worker-unsafe-v2"}
        clean_service_networks = {
            "temporal": {"control"}, "payment": {"effects"}, "completion": {"effects"},
            "worker-unsafe-v2": {"control", "effects"},
        }
        main_before_services = {"temporal", "payment", "completion", "worker-v1"}
        main_before_service_networks = {
            "temporal": {"control"}, "payment": {"effects"}, "completion": {"effects"},
            "worker-v1": {"control", "effects"},
        }
        main_final_services = {"temporal", "payment", "completion", "worker-unsafe-v2"}
        main_final_service_networks = {
            "temporal": {"control"}, "payment": {"effects"}, "completion": {"effects"},
            "worker-unsafe-v2": {"control", "effects"},
        }
        clean_networks = main_before_networks = main_final_networks = {"control", "effects"}
    clean_containers = validate_container_snapshot(
        root, "clean-containers.json", phase="clean", project=clean_project,
        expected_services=clean_services, build=build, expected_networks=clean_networks,
        service_networks=clean_service_networks, networks_name="clean-networks.json",
    )
    main_before_containers = validate_container_snapshot(
        root, "main-containers-before-decision.json", phase="main", project=main_project,
        expected_services=main_before_services, build=build,
        expected_networks=main_before_networks,
        service_networks=main_before_service_networks,
        networks_name="main-networks-before-decision.json",
    )
    main_final_containers = validate_container_snapshot(
        root, "main-containers.json", phase="main", project=main_project,
        expected_services=main_final_services, build=build,
        expected_networks=main_final_networks,
        service_networks=main_final_service_networks,
        networks_name="main-networks.json",
    )
    def created_id(events_by_service: Mapping[str, Sequence[Mapping[str, Any]]], service: str) -> Any:
        creates = [event for event in events_by_service[service] if event.get("Action") == "create"]
        require(len(creates) == 1, f"{service} event create count differs")
        return obj(creates[0].get("Actor"), f"{service} create actor").get("ID")

    for service, container in clean_containers.items():
        require(created_id(clean_service_events, service) == container.get("Id"), f"clean {service} event/inspect identity differs")
    for service, container in main_before_containers.items():
        require(created_id(main_service_events, service) == container.get("Id"), f"main {service} event/inspect identity differs")
    for service, container in main_final_containers.items():
        require(created_id(main_service_events, service) == container.get("Id"), f"main final {service} event/inspect identity differs")
    validate_network_probes(
        root, "clean-network-probes.json", "clean", method,
        clean_project, clean_containers,
    )
    validate_network_probes(
        root, "main-network-probes.json", "main", method,
        main_project, main_before_containers,
    )
    clean_target_specific = service_containers(root, "clean-target-container.json")
    if set(clean_target_specific) == {"worker-unsafe-v2"}:
        validate_container_item(
            clean_target_specific["worker-unsafe-v2"], label="clean target-specific container",
            phase="clean", service="worker-unsafe-v2", project=clean_project,
            image=build["TEMPORAL_UNSAFE_WORKER_ID"],
        )
    require(
        set(clean_target_specific) == {"worker-unsafe-v2"}
        and clean_target_specific["worker-unsafe-v2"].get("Id")
        == clean_containers["worker-unsafe-v2"].get("Id"),
        "clean target inspect does not match the project snapshot",
    )
    main_source_specific = service_containers(root, "main-source-container-at-cut.json")
    if set(main_source_specific) == {"worker-v1"}:
        validate_container_item(
            main_source_specific["worker-v1"], label="main source-at-cut container",
            phase="main", service="worker-v1", project=main_project, image=SOURCE_IMAGE_ID,
        )
    require(
        set(main_source_specific) == {"worker-v1"}
        and main_source_specific["worker-v1"].get("Id")
        == main_before_containers["worker-v1"].get("Id"),
        "main source inspect does not match the decision-cut snapshot",
    )
    if method == "proposed":
        clean_control_specific = service_containers(root, "clean-control-container.json")
        main_control_specific = service_containers(root, "main-control-container.json")
        if set(clean_control_specific) == {"unsafe-control"}:
            validate_container_item(
                clean_control_specific["unsafe-control"], label="clean control-specific container",
                phase="clean", service="unsafe-control", project=clean_project, image=CONTROL_IMAGE_ID,
            )
        if set(main_control_specific) == {"unsafe-control"}:
            validate_container_item(
                main_control_specific["unsafe-control"], label="main control-specific container",
                phase="main", service="unsafe-control", project=main_project, image=CONTROL_IMAGE_ID,
            )
        require(
            set(clean_control_specific) == {"unsafe-control"}
            and clean_control_specific["unsafe-control"].get("Id")
            == clean_containers["unsafe-control"].get("Id"),
            "clean control inspect does not match the project snapshot",
        )
        require(
            set(main_control_specific) == {"unsafe-control"}
            and main_control_specific["unsafe-control"].get("Id")
            == main_final_containers["unsafe-control"].get("Id"),
            "main control inspect does not match the project snapshot",
        )
        validate_control_endpoint(
            root, "clean", clean_project,
            clean_containers["unsafe-control"], "target-runtime",
        )
        validate_control_endpoint(
            root, "main", main_project,
            main_final_containers["unsafe-control"], "source-runtime",
        )
        final_source = service_containers(root, "main-final-source-container.json")
        if set(final_source) == {"worker-v1"}:
            validate_container_item(
                final_source["worker-v1"], label="main final source container",
                phase="main", service="worker-v1", project=main_project, image=SOURCE_IMAGE_ID,
            )
        require(
            set(final_source) == {"worker-v1"}
            and final_source["worker-v1"].get("Id")
            == main_source_specific["worker-v1"].get("Id")
            == main_final_containers["worker-v1"].get("Id"),
            "proposed retained source container differs",
        )
        validate_proposed_absence(root, set(main_before_containers))
    else:
        validate_native_absence(root, "clean-native-absence.json", "clean", set(clean_containers))
        validate_native_absence(root, "main-native-absence.json", "main", set(main_final_containers))
        target_specific = service_containers(root, "main-target-container.json")
        if set(target_specific) == {"worker-unsafe-v2"}:
            validate_container_item(
                target_specific["worker-unsafe-v2"], label="main target-specific container",
                phase="main", service="worker-unsafe-v2", project=main_project,
                image=build["TEMPORAL_UNSAFE_WORKER_ID"],
            )
        require(
            set(target_specific) == {"worker-unsafe-v2"}
            and target_specific["worker-unsafe-v2"].get("Id")
            == main_final_containers["worker-unsafe-v2"].get("Id"),
            "native target inspect does not match the final project snapshot",
        )
        source_id = main_source_specific["worker-v1"].get("Id")
        require(source_id not in {item.get("Id") for item in main_final_containers.values()}, "native source remained in the final project")
        require(read(root, "main-source-removed-inspect.json") == b"[]\n", "native removed-source inspect returned an object")
        require(read(root, "main-source-removed-inspect-status.txt") == b"1\n", "native removed-source inspect status differs")
        removed_error = read(root, "main-source-removed-inspect.stderr").decode("utf-8", errors="strict")
        require(
            isinstance(source_id, str) and source_id in removed_error
            and re.search(r"no such object", removed_error, re.IGNORECASE) is not None,
            "native removed-source inspect error differs",
        )

    clean_run = read(root, "clean-run-id.txt").decode().strip()
    main_run = read(root, "main-run-id.txt").decode().strip()
    require(UUID.fullmatch(clean_run) is not None and UUID.fullmatch(main_run) is not None and clean_run != main_run, "Temporal run IDs differ")
    validate_start(root, "clean-start.json", clean_workflow, clean_run)
    validate_start(root, "main-start.json", main_workflow, main_run)
    validate_poller(root, "clean-target-workflow-pollers.json", TARGET_BUILD, TARGET_IDENTITY, {TARGET_BUILD})
    validate_poller(root, "clean-target-activity-pollers.json", TARGET_BUILD, TARGET_IDENTITY, {TARGET_BUILD})
    validate_poller(root, "main-source-workflow-pollers.json", SOURCE_BUILD, SOURCE_IDENTITY, {SOURCE_BUILD})
    validate_poller(root, "main-source-activity-pollers.json", SOURCE_BUILD, SOURCE_IDENTITY, {SOURCE_BUILD})
    validate_deployment(root, "clean-deployment-before-current.json", current_build=None, allowed_builds={TARGET_BUILD}, require_builds={TARGET_BUILD})
    validate_deployment_version(root, "clean-target-version-before-current.json", TARGET_BUILD, current=False)
    validate_deployment(root, "clean-deployment-target-current.json", current_build=TARGET_BUILD, allowed_builds={TARGET_BUILD}, require_builds={TARGET_BUILD})
    validate_deployment_version(root, "clean-target-version-final.json", TARGET_BUILD, current=True)
    validate_deployment(root, "clean-deployment-final.json", current_build=TARGET_BUILD, allowed_builds={TARGET_BUILD}, require_builds={TARGET_BUILD})
    validate_deployment(root, "main-deployment-before-current.json", current_build=None, allowed_builds={SOURCE_BUILD}, require_builds={SOURCE_BUILD})
    validate_deployment_version(root, "main-source-version-before-current.json", SOURCE_BUILD, current=False)
    validate_deployment(root, "main-deployment-source-current.json", current_build=SOURCE_BUILD, allowed_builds={SOURCE_BUILD}, require_builds={SOURCE_BUILD})
    validate_deployment(root, "main-cut-deployment.json", current_build=SOURCE_BUILD, allowed_builds={SOURCE_BUILD}, require_builds={SOURCE_BUILD})
    validate_deployment_version(root, "main-cut-source-version.json", SOURCE_BUILD, current=True)
    require(read(root, "clean-set-current-target.json") == b"", "clean set-current command unexpectedly returned data")
    require(read(root, "main-set-current-source.json") == b"", "main source set-current command unexpectedly returned data")
    for phase in ("clean", "main"):
        for suffix in (
            "signal.json", "signal-driver-selected.json",
            "signal-driver-at-restaurant.json", "signal-delivery-finished.json",
        ):
            require(read(root, f"{phase}-{suffix}") == b"", f"{phase} {suffix} command unexpectedly returned data")
    if method == "proposed":
        validate_deployment_version(root, "main-final-source-version.json", SOURCE_BUILD, current=True)
        validate_deployment(root, "main-deployment-final.json", current_build=SOURCE_BUILD, allowed_builds={SOURCE_BUILD}, require_builds={SOURCE_BUILD})
    else:
        validate_poller(root, "main-target-workflow-pollers.json", TARGET_BUILD, TARGET_IDENTITY, {SOURCE_BUILD, TARGET_BUILD})
        validate_poller(root, "main-target-activity-pollers.json", TARGET_BUILD, TARGET_IDENTITY, {SOURCE_BUILD, TARGET_BUILD})
        validate_deployment_version(root, "main-target-version-before-current.json", TARGET_BUILD, current=False)
        validate_deployment(root, "main-deployment-target-current.json", current_build=TARGET_BUILD, allowed_builds={SOURCE_BUILD, TARGET_BUILD}, require_builds={SOURCE_BUILD, TARGET_BUILD})
        validate_deployment_version(root, "main-target-version-final.json", TARGET_BUILD, current=True)
        validate_deployment(root, "main-deployment-final.json", current_build=TARGET_BUILD, allowed_builds={SOURCE_BUILD, TARGET_BUILD}, require_builds={SOURCE_BUILD, TARGET_BUILD})
        require(read(root, "main-set-current-target.json") == b"", "main target set-current command unexpectedly returned data")
    clean_payment_wait = provider_records(root, "clean-payment-wait.history")
    clean_completion_wait = provider_records(root, "clean-completion-wait.history")
    clean_payment = provider_records(root, "clean-payment-final.history")
    clean_completion = provider_records(root, "clean-completion-final.history")
    main_cut_payment = provider_records(root, "main-payment-cut.history")
    main_cut_completion = provider_records(root, "main-completion-cut.history")
    main_after_payment = provider_records(root, "main-payment-after-decision.history")
    main_after_completion = provider_records(root, "main-completion-after-decision.history")
    main_payment = provider_records(root, "main-payment-final.history")
    main_completion = provider_records(root, "main-completion-final.history")
    expected_clean_payment = [expected_provider_record(clean_order, "/v2/charge")]
    require(clean_payment_wait == clean_payment == expected_clean_payment, "clean target did not execute exactly one v2 charge")
    require(clean_completion_wait == [], "clean target completed before its signal")
    require(clean_completion == [expected_provider_record(clean_order, "/v1/complete", True, "unsafe-v2")], "clean target completion differs")
    require(main_cut_payment == [expected_provider_record(main_order, "/v1/charge")], "main cut payment differs")
    require(main_cut_completion == [], "main completion happened before the edit decision")
    require(main_after_payment == main_payment == main_cut_payment, "main payment changed after the edit decision")
    require(main_after_completion == main_cut_completion, "main completion happened during the edit decision")
    main_closure = None if method == "proposed" else "unsafe-v2"
    require(main_completion == [expected_provider_record(main_order, "/v1/complete", True, main_closure)], "main completion closure differs")
    one_v2 = {"deliveries": 1, "commits": 1, "paths": {"/v2/charge": 1}}
    one_v1 = {"deliveries": 1, "commits": 1, "paths": {"/v1/charge": 1}}
    one_completion = {"deliveries": 1, "commits": 1, "paths": {"/v1/complete": 1}}
    none = {"deliveries": 0, "commits": 0, "paths": {}}
    check_stats(root, "clean-payment-wait-stats.json", one_v2)
    check_stats(root, "clean-completion-wait-stats.json", none)
    check_stats(root, "clean-payment-final-stats.json", one_v2)
    check_stats(root, "clean-completion-final-stats.json", one_completion)
    check_stats(root, "main-payment-cut-stats.json", one_v1)
    check_stats(root, "main-completion-cut-stats.json", none)
    check_stats(root, "main-payment-after-decision-stats.json", one_v1)
    check_stats(root, "main-completion-after-decision-stats.json", none)
    check_stats(root, "main-payment-final-stats.json", one_v1)
    check_stats(root, "main-completion-final-stats.json", one_completion)

    cut_before = validate_cut_history(jvalue(root, "main-cut-history.json"), label="main cut", workflow_id=main_workflow, run_id=main_run, order_id=main_order, payment_record=main_payment[0])
    cut_after = validate_cut_history(jvalue(root, "main-history-after-decision.json"), label="main after decision", workflow_id=main_workflow, run_id=main_run, order_id=main_order, payment_record=main_payment[0])
    require(cut_before == cut_after, "main cut was not stable across the edit decision")
    require(read(root, "main-cut-history.json") == read(root, "main-history-after-decision.json"), "main Temporal History bytes changed across the decision")
    require(read(root, "main-payment-cut-stats.json") == read(root, "main-payment-after-decision-stats.json"), "payment statistics changed across the decision")
    require(read(root, "main-completion-cut-stats.json") == read(root, "main-completion-after-decision-stats.json"), "completion statistics changed across the decision")
    require(read(root, "main-payment-cut.history") == read(root, "main-payment-after-decision.history"), "payment provider record changed across the decision")
    require(read(root, "main-completion-cut.history") == read(root, "main-completion-after-decision.history"), "completion provider record changed across the decision")
    clean_events = validate_workflow_history(
        jvalue(root, "clean-final-history.json"), label="clean final History", workflow_id=clean_workflow,
        run_id=clean_run, order_id=clean_order, clean=True, final_build=TARGET_BUILD,
        payment_record=clean_payment[0], completion_record=clean_completion[0],
    )
    clean_wait = history_events(jvalue(root, "clean-wait-history.json"), clean_run, "clean wait History")
    require(
        len(clean_wait) == len(CUT_TYPES) + 2 and clean_wait == clean_events[:len(clean_wait)],
        "clean IN_PREPARATION History is not the exact final target History prefix",
    )
    final_build = SOURCE_BUILD if method == "proposed" else TARGET_BUILD
    main_events = validate_workflow_history(
        jvalue(root, "main-final-history.json"), label="main final History", workflow_id=main_workflow,
        run_id=main_run, order_id=main_order, clean=False, final_build=final_build,
        payment_record=main_payment[0], completion_record=main_completion[0],
    )
    require(main_events[:len(CUT_TYPES)] == cut_before, "final History rewrote the substantive cut")
    validate_query(root, "clean-wait-query.json", clean_order, TARGET_BUILD, "IN_PREPARATION")
    validate_query(root, "clean-final-query.json", clean_order, TARGET_BUILD, "DELIVERED")
    validate_query(root, "main-cut-query.json", main_order, SOURCE_BUILD, "IN_PREPARATION")
    validate_query(root, "main-final-query.json", main_order, final_build, "DELIVERED")
    validate_describe(root, "clean-wait-describe.json", clean_workflow, clean_run, clean_order, TARGET_BUILD, "WORKFLOW_EXECUTION_STATUS_RUNNING", len(clean_wait))
    validate_describe(root, "clean-final-describe.json", clean_workflow, clean_run, clean_order, TARGET_BUILD, "WORKFLOW_EXECUTION_STATUS_COMPLETED", len(clean_events))
    validate_describe(root, "main-cut-describe.json", main_workflow, main_run, main_order, SOURCE_BUILD, "WORKFLOW_EXECUTION_STATUS_RUNNING", len(cut_before))
    validate_describe(root, "main-final-describe.json", main_workflow, main_run, main_order, final_build, "WORKFLOW_EXECUTION_STATUS_COMPLETED", len(main_events))

    if method == "proposed":
        validate_certificate_semantics(
            root, runtime_root, source, target, clean_order, main_order,
            clean_payment[0], clean_completion[0], main_payment[0], main_completion[0],
        )
        require(not main_target_started, "proposed target was observed starting")
        target_started = main_target_started
        main_decision = "impossible"
        external_violated = False
        source_completed = True
    else:
        require(main_target_started, "native target was not observed starting")
        target_started = main_target_started
        main_decision = "native-completed"
        external_violated = True
        source_completed = False
        used = target["kinds"]["charge-v1"]["costs"]["approval"] + target["kinds"]["finish-v2"]["costs"]["approval"]
        require(used == 2 and target["capacities"]["approval"] == 1, "native external Requirement reconstruction differs")

    scientific = all_files - {"SHA256SUMS", "observed.json", "clean-compose.log", "main-compose.log"}
    return {
        "schema": 1, "valid": True, "cell": CELL, "method": method,
        "clean_target_completed": True, "empty_history_target_allow": ["charge-v2", "finish-v2"],
        "main_decision": main_decision, "same_main_execution_completed": True,
        "approval_used": 1 if method == "proposed" else 2, "approval_capacity": 1,
        "external_requirement_violated": external_violated, "target_started": target_started,
        "source_completed": source_completed, "payment_operation_id": main_payment[0]["operation_id"],
        "completion_operation_id": main_completion[0]["operation_id"],
        "substantive_cut_digest": substantive_history_digest(cut_before),
        "artifact_count": len(scientific), "evidence_digest": evidence_digest(root, scientific),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--runtime-root", type=Path, default=RUNTIME_ROOT)
    args = parser.parse_args()
    try:
        verdict = check(args.evidence, args.runtime_root)
    except (EvidenceError, OSError, subprocess.SubprocessError) as error:
        print(f"check-unsafe: {error}", file=sys.stderr)
        return 1
    print(json.dumps(verdict, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
