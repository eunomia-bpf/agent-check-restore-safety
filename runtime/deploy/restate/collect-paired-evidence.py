#!/usr/bin/env python3
"""Collect a paired Restate run into the checker schema-1 evidence bundle."""

from __future__ import annotations

import argparse
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Any, Mapping, Sequence


HERE = Path(__file__).resolve().parent
CHECK_SPEC = importlib.util.spec_from_file_location("restate_evidence_checker", HERE / "check.py")
if CHECK_SPEC is None or CHECK_SPEC.loader is None:  # pragma: no cover
    raise RuntimeError("cannot load check.py")
CHECK = importlib.util.module_from_spec(CHECK_SPEC)
CHECK_SPEC.loader.exec_module(CHECK)

HEX64 = re.compile(r"[0-9a-f]{64}\Z")
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
ENV_LINE = re.compile(r"([A-Z][A-Z0-9_]*)=([^\s'\"`$;|&<>]+)\Z")
TOKEN_LINE = re.compile(
    r"^\[([^\]]+)\] Executing payment with token "
    r"([0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}) "
    r"for \$([0-9]+)$"
)
MAX_JSON = 16 << 20
MAX_HISTORY = 64 << 20


class CollectionError(ValueError):
    """The paired run is incomplete, unsafe to read, or internally inconsistent."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CollectionError(message)


def _duplicate_safe(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, f"JSON contains duplicate key {key!r}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise CollectionError(f"JSON contains non-finite number {value}")


def _loads(data: bytes, label: str) -> Any:
    try:
        return json.loads(
            data,
            object_pairs_hook=_duplicate_safe,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CollectionError(f"{label} is not strict JSON") from error


def _regular(path: Path, label: str, *, limit: int = MAX_JSON) -> bytes:
    try:
        info = path.lstat()
    except FileNotFoundError as error:
        raise CollectionError(f"required input is absent: {label}: {path}") from error
    require(stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode), f"{label} is not a regular non-symlink file: {path}")
    require(info.st_size <= limit, f"{label} exceeds its size limit")
    data = path.read_bytes()
    require(len(data) == info.st_size, f"{label} changed while read")
    return data


def _json(path: Path, label: str) -> Any:
    return _loads(_regular(path, label), label)


def _object(value: Any, label: str) -> dict[str, Any]:
    require(isinstance(value, dict), f"{label} must be an object")
    return value


def _list(value: Any, label: str) -> list[Any]:
    require(isinstance(value, list), f"{label} must be an array")
    return value


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode() + b"\n"


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _reject_symlink_components(path: Path, label: str) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if os.path.lexists(current) and current.is_symlink():
            raise CollectionError(f"{label} crosses a symbolic link: {current}")


def _reject_symlinks(root: Path, label: str) -> None:
    _reject_symlink_components(root, label)
    try:
        info = root.lstat()
    except FileNotFoundError as error:
        raise CollectionError(f"{label} is absent: {root}") from error
    require(stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode), f"{label} is not a non-symlink directory")
    for current, directories, files in os.walk(root, followlinks=False):
        for name in directories + files:
            candidate = Path(current) / name
            if candidate.is_symlink():
                raise CollectionError(f"{label} contains a symbolic link: {candidate.relative_to(root)}")


COMMON_INPUTS = (
    "exit-status.txt",
    "order.json",
    "requirement-v2.json",
    "runtime.history",
    "runtime.head",
    "final-control-history.json",
    "final-control-state.json",
    "certificate-state-v2.json",
    "certificate-v2.json",
    "certificate-verdict-v2.json",
    "payment.history",
    "completion.history",
    "source-cut-status.json",
    "source-cut-status-after-window.json",
    "source-cut-journal.json",
    "source-cut-journal-after-window.json",
    "source-cut-workflow-state.json",
    "source-cut-workflow-state-after-window.json",
    "deployments.json",
    "source-v1.log",
    "source-container-before-kill.json",
    "source-container-kill.txt",
    "source-container-rm.txt",
    "source-container-rm.stderr",
    "source-container-after-rm.json",
    "source-container-after-rm.stderr",
    "source-v1-removal.json",
    "containers.raw.json",
)

CASE_INPUTS = {
    "h0": ("source-final-status.json", "source-final-whole-key-invocations.json", "source-final-inbox.json", "target-final.json"),
    "h1": (
        "source-after-kill.json", "source-after-purge.json", "continuation-submit.json",
        "continuation-invocation.json", "continuation-order-status.json",
        "target-container.json", "target-start-order.json",
    ),
}


def _preflight(pair: Path, build_env: Path) -> dict[str, Path]:
    errors: list[str] = []
    try:
        _reject_symlinks(pair, "PAIR_DIR")
    except CollectionError as error:
        errors.append(str(error))
    try:
        _reject_symlink_components(build_env, "BUILD_ENV")
        info = build_env.lstat()
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            errors.append(f"BUILD_ENV is not a regular non-symlink file: {build_env}")
    except FileNotFoundError:
        errors.append(f"BUILD_ENV is absent: {build_env}")
    paths: dict[str, Path] = {"pair_exit": pair / "exit-status.txt"}
    wanted = [pair / "exit-status.txt"]
    for case_name in ("h0", "h1"):
        base = pair / case_name / "results"
        paths[case_name] = base
        wanted.extend(base / name for name in COMMON_INPUTS + CASE_INPUTS[case_name])
    for path in wanted:
        try:
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
                errors.append(f"required input is not a regular non-symlink file: {path.relative_to(pair)}")
        except FileNotFoundError:
            errors.append(f"required input is absent: {path.relative_to(pair)}")
    if errors:
        raise CollectionError("input preflight failed:\n  - " + "\n  - ".join(sorted(set(errors))))
    return paths


def _exit_zero(path: Path, label: str) -> None:
    raw = _regular(path, label, limit=64)
    require(re.fullmatch(rb"0\r?\n?", raw) is not None, f"{label} is nonzero or malformed")


def _build_values(path: Path) -> dict[str, str]:
    data = _regular(path, "BUILD_ENV")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise CollectionError("BUILD_ENV is not UTF-8") from error
    values: dict[str, str] = {}
    for number, line in enumerate(text.splitlines(), 1):
        if not line or line.startswith("#"):
            continue
        match = ENV_LINE.fullmatch(line)
        require(match is not None, f"BUILD_ENV line {number} is not a literal assignment")
        key, value = match.groups()
        require(key not in values, f"BUILD_ENV repeats {key}")
        values[key] = value
    required = {
        "ORDER_V1_IMAGE", "ORDER_V2_IMAGE", "UPSTREAM_ARCHIVE_SHA256",
        "V1_CONTEXT_SHA256", "V2_CONTEXT_SHA256",
        "V1_PROGRAM_SHA256", "V2_PROGRAM_SHA256",
    }
    missing = sorted(required - set(values))
    require(not missing, "BUILD_ENV omits: " + ", ".join(missing))
    for key in ("ORDER_V1_IMAGE", "ORDER_V2_IMAGE"):
        require(IMAGE_ID.fullmatch(values[key]) is not None, f"BUILD_ENV {key} is not a Docker image ID")
    for key in required - {"ORDER_V1_IMAGE", "ORDER_V2_IMAGE"}:
        require(HEX64.fullmatch(values[key]) is not None, f"BUILD_ENV {key} is not SHA-256")
    require(values["ORDER_V1_IMAGE"] != values["ORDER_V2_IMAGE"], "BUILD_ENV v1/v2 images are identical")
    require(
        values["UPSTREAM_ARCHIVE_SHA256"] == "9422ccd6d5b0a9035bd207b6642f6d8decaac58839dd8abee8691b384bdd825a",
        "BUILD_ENV upstream archive differs from pinned v1.7.7",
    )
    return values


def _payment_token(log_path: Path, order_id: str, amount: int) -> str:
    raw = _regular(log_path, "source-v1.log", limit=MAX_HISTORY)
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise CollectionError("source-v1.log is not UTF-8") from error
    matches = [match for line in lines if (match := TOKEN_LINE.fullmatch(line)) is not None]
    require(len(matches) == 1, "source-v1.log does not contain exactly one canonical payment-token line")
    match = matches[0]
    require(match.group(1) == order_id and int(match.group(3)) == amount, "source-v1.log payment identity/amount differs")
    return match.group(2)


def _one_row(document: Any, label: str) -> dict[str, Any]:
    value = _object(document, label)
    require(set(value) == {"rows"}, f"{label} query envelope changed")
    rows = _list(value["rows"], label + " rows")
    require(len(rows) == 1, f"{label} did not return exactly one row")
    return _object(rows[0], label + " row")


def _journal_projection(document: Any) -> list[dict[str, Any]]:
    value = _object(document, "raw Restate journal")
    require(set(value) == {"rows"}, "raw Restate journal query envelope changed")
    rows = [_object(item, "raw Restate journal row") for item in _list(value["rows"], "raw Restate journal rows")]
    require(rows, "raw Restate journal is empty")
    projected: list[dict[str, Any]] = []
    for expected_index, row in enumerate(rows):
        require(row.get("index") == expected_index, "raw Restate journal indices are not contiguous")
        require(type(row.get("completed")) is bool, "raw Restate journal did not use COALESCE(completed,false)")
        raw_hex = row.get("raw")
        require(isinstance(raw_hex, str), "raw Restate journal payload is absent")
        try:
            payload = bytes.fromhex(raw_hex)
        except ValueError as error:
            raise CollectionError("raw Restate journal payload is not hex") from error
        require(len(payload) == row.get("raw_length"), "raw Restate journal payload length differs")
        projected.append({
            "index": expected_index,
            "kind": row.get("entry_type"),
            "name": row.get("name", ""),
            "completed": row["completed"],
            "payload_sha256": sha256(payload).hexdigest(),
        })
    payment = [item for item in projected if item["kind"] == "Command: Run" and item["name"] == "payment"]
    require(len(payment) == 1 and payment[0] is projected[-1] and payment[0]["completed"] is False, "payment Run is not the unique unresolved journal tail")
    return projected


def _workflow_projection(document: Any, order_id: str) -> dict[str, str]:
    row = _one_row(document, "raw Restate workflow state")
    require(row.get("service_name") == "order-workflow" and row.get("service_key") == order_id and row.get("key") == "status", "raw Restate workflow-state identity differs")
    encoded = row.get("value")
    require(isinstance(encoded, str), "raw Restate workflow state omits value")
    try:
        raw = bytes.fromhex(encoded)
    except ValueError as error:
        raise CollectionError("raw Restate workflow state is not hex") from error
    require(raw == b'"CREATED"' and row.get("value_utf8") == '"CREATED"' and row.get("value_length") == len(raw), "raw Restate workflow state is not CREATED")
    return {"status": "CREATED"}


def _deployment(raw: Mapping[str, Any], version: str) -> dict[str, Any]:
    uri = f"http://order-{version}:9080/"
    matches = [item for item in _list(raw.get("deployments"), "Restate deployments") if isinstance(item, dict) and item.get("uri") == uri]
    require(len(matches) == 1, f"raw Restate deployments omit unique {version}")
    return matches[0]


def _containers(raw: Any, case_name: str, target_start: Any | None) -> dict[str, Any]:
    items = [_object(item, f"{case_name} raw container") for item in _list(raw, f"{case_name} raw containers")]
    projected: list[dict[str, Any]] = []
    target_id: str | None = None
    for item in items:
        state = _object(item.get("State"), f"{case_name} container State")
        config = _object(item.get("Config"), f"{case_name} container Config")
        labels = _object(config.get("Labels"), f"{case_name} container labels")
        service = labels.get("com.docker.compose.service")
        require(isinstance(service, str) and service, f"{case_name} container omits Compose service")
        if state.get("Running") is not True:
            continue
        role = "source-v1" if service == "order-v1" else "target-v2" if service == "order-v2" else service
        networks = _object(_object(item.get("NetworkSettings"), "container NetworkSettings").get("Networks"), "container networks")
        normalized = {
            "role": role,
            "name": str(item.get("Name", "")).removeprefix("/"),
            "image_id": item.get("Image"),
            "running": True,
            "networks": sorted(networks),
        }
        if role == "target-v2":
            target_id = item.get("Id")
            start = _object(target_start, "target start order")
            require(start.get("container") == target_id, "target start order names another container")
            normalized["started_after_history_sequence"] = start.get("started_after_history_sequence")
        projected.append(normalized)
    projected.sort(key=lambda item: str(item["role"]))
    require(not any(item["role"] == "source-v1" for item in projected), f"{case_name} still contains source-v1")
    require((target_id is not None) == (case_name == "h1"), f"{case_name} target-v2 presence differs")
    return {"schema": 1, "items": projected}


def _unknown_sequence(events: Sequence[Mapping[str, Any]]) -> int:
    matches = [
        event.get("sequence")
        for event in events
        if event.get("operation") == "operation.phase"
        and isinstance(event.get("data"), dict)
        and isinstance(event["data"].get("update"), dict)
        and event["data"]["update"].get("phase") == "unknown"
    ]
    require(len(matches) == 1 and type(matches[0]) is int, "History does not contain exactly one unknown-operation boundary")
    return int(matches[0])


def _removal(base: Path, expected_image: str, events: Sequence[Mapping[str, Any]], label: str) -> dict[str, Any]:
    before = [_object(item, f"{label} source container") for item in _list(_json(base / "source-container-before-kill.json", f"{label} source container before kill"), f"{label} source containers")]
    require(len(before) == 1, f"{label} source-container inspect did not return one container")
    source = before[0]
    identifier = source.get("Id")
    config = _object(source.get("Config"), f"{label} source container Config")
    labels = _object(config.get("Labels"), f"{label} source container labels")
    require(
        isinstance(identifier, str)
        and re.fullmatch(r"[0-9a-f]{64}", identifier) is not None
        and source.get("Image") == expected_image
        and labels.get("com.docker.compose.service") == "order-v1",
        f"{label} source container is not the build-env v1 worker",
    )
    kill_stdout = _regular(base / "source-container-kill.txt", f"{label} source kill stdout", limit=256).decode().strip()
    remove_stdout = _regular(base / "source-container-rm.txt", f"{label} source removal stdout", limit=256).decode().strip()
    remove_stderr = _regular(base / "source-container-rm.stderr", f"{label} source removal stderr", limit=4096)
    after = _json(base / "source-container-after-rm.json", f"{label} source after removal")
    inspect_stderr = _regular(base / "source-container-after-rm.stderr", f"{label} source post-removal inspect stderr", limit=4096).decode().strip()
    require(kill_stdout == identifier and remove_stdout == identifier and remove_stderr == b"", f"{label} source kill/removal output differs")
    require(after == [] and identifier in inspect_stderr and "no such" in inspect_stderr.lower(), f"{label} source container still exists after removal")
    report = _object(_json(base / "source-v1-removal.json", f"{label} source removal result"), f"{label} source removal result")
    boundary = _unknown_sequence(events)
    require(
        report.get("schema") == 1
        and report.get("compose_service") == "order-v1"
        and report.get("container_id") == identifier
        and report.get("remove_exit_code") == 0
        and type(report.get("inspect_exit_code")) is int
        and report["inspect_exit_code"] != 0
        and report.get("stderr") == inspect_stderr
        and report.get("fenced_before_history_sequence") == boundary,
        f"{label} removal result differs from raw removal artifacts/History boundary",
    )
    return {
        "schema": 1,
        "compose_service": "order-v1",
        "container_id": identifier,
        "remove_exit_code": 0,
        "inspect_exit_code": report["inspect_exit_code"],
        "stderr": inspect_stderr,
        "fenced_before_history_sequence": boundary,
    }


class _Writer:
    def __init__(self, root: Path) -> None:
        self.root = root

    def bytes(self, relative: str, data: bytes) -> dict[str, str]:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return {"path": relative, "sha256": sha256(data).hexdigest()}

    def json(self, relative: str, value: Any) -> dict[str, str]:
        return self.bytes(relative, _canonical(value))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("PAIR_DIR", type=Path)
    parser.add_argument("BUILD_ENV", type=Path)
    parser.add_argument("OUTPUT_DIR", type=Path)
    args = parser.parse_args(argv)
    try:
        result = collect(args.PAIR_DIR, args.BUILD_ENV, args.OUTPUT_DIR)
    except (CollectionError, CHECK.EvidenceError, OSError, subprocess.SubprocessError, UnicodeError) as error:
        print(f"collect-paired-evidence: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


def collect(pair_dir: Path, build_env: Path, output_dir: Path) -> dict[str, Any]:
    pair = _absolute(pair_dir)
    build = _absolute(build_env)
    output = _absolute(output_dir)
    sources = _preflight(pair, build)
    _reject_symlink_components(output.parent, "OUTPUT_DIR parent")
    require(not os.path.lexists(output), f"OUTPUT_DIR already exists: {output}")
    require(not output.is_relative_to(pair), "OUTPUT_DIR must not be inside PAIR_DIR")
    output.parent.mkdir(parents=True, exist_ok=True)
    require(output.parent.is_dir() and not output.parent.is_symlink(), "OUTPUT_DIR parent is not a real directory")

    _exit_zero(sources["pair_exit"], "pair exit status")
    for case_name in ("h0", "h1"):
        _exit_zero(sources[case_name] / "exit-status.txt", f"{case_name} exit status")
    build_values = _build_values(build)

    bases = {name: sources[name] for name in ("h0", "h1")}
    order_bytes = {name: _regular(bases[name] / "order.json", f"{name} order") for name in bases}
    requirement_bytes = {name: _regular(bases[name] / "requirement-v2.json", f"{name} requirement") for name in bases}
    require(order_bytes["h0"] == order_bytes["h1"], "H0/H1 order bytes differ")
    require(requirement_bytes["h0"] == requirement_bytes["h1"], "H0/H1 target Requirement bytes differ")
    order = _object(_loads(order_bytes["h0"], "order"), "order")
    order_id = order.get("id")
    amount = order.get("totalCost")
    require(isinstance(order_id, str) and order_id and type(amount) is int and amount > 0, "order identity/amount differs")
    tokens = {
        name: _payment_token(bases[name] / "source-v1.log", order_id, amount)
        for name in bases
    }
    require(tokens["h0"] == tokens["h1"], "H0/H1 payment tokens differ")

    events: dict[str, list[dict[str, Any]]] = {}
    for name, base in bases.items():
        history_path = base / "runtime.history"
        events[name] = CHECK._history(history_path)
        CHECK._head(base / "runtime.head", events[name])
        require(_json(base / "final-control-history.json", f"{name} final control History") == events[name], f"{name} control History differs from binary History")

    raw_status: dict[str, bytes] = {}
    raw_journal: dict[str, bytes] = {}
    raw_workflow: dict[str, bytes] = {}
    status_rows: dict[str, dict[str, Any]] = {}
    journals: dict[str, list[dict[str, Any]]] = {}
    workflows: dict[str, dict[str, str]] = {}
    for name, base in bases.items():
        raw_status[name] = _regular(base / "source-cut-status.json", f"{name} raw cut status")
        raw_journal[name] = _regular(base / "source-cut-journal.json", f"{name} raw cut journal")
        raw_workflow[name] = _regular(base / "source-cut-workflow-state.json", f"{name} raw cut workflow state")
        require(raw_status[name] == _regular(base / "source-cut-status-after-window.json", f"{name} status after retry window"), f"{name} cut status changed after retry window")
        require(raw_journal[name] == _regular(base / "source-cut-journal-after-window.json", f"{name} journal after retry window"), f"{name} cut journal changed after retry window")
        require(raw_workflow[name] == _regular(base / "source-cut-workflow-state-after-window.json", f"{name} workflow state after retry window"), f"{name} workflow state changed after retry window")
        status_rows[name] = _one_row(_loads(raw_status[name], f"{name} raw status"), f"{name} raw status")
        journals[name] = _journal_projection(_loads(raw_journal[name], f"{name} raw journal"))
        workflows[name] = _workflow_projection(_loads(raw_workflow[name], f"{name} raw workflow state"), order_id)
        require(status_rows[name].get("status") == "paused", f"{name} source was not paused at the cut")
        require(status_rows[name].get("journal_size") == len(journals[name]), f"{name} status journal_size differs")
        require(order_id in str(status_rows[name].get("target", "")), f"{name} status targets another order")
    require(journals["h0"] == journals["h1"], "H0/H1 normalized Restate journals differ")
    require(workflows["h0"] == workflows["h1"], "H0/H1 workflow states differ")
    require(status_rows["h0"].get("id") == status_rows["h1"].get("id"), "H0/H1 invocation IDs differ")

    pair_deployments = {
        name: _object(_json(bases[name] / "deployments.json", f"{name} raw deployments"), f"{name} raw deployments")
        for name in bases
    }
    raw_container_values = {
        name: _json(bases[name] / "containers.raw.json", f"{name} raw containers")
        for name in bases
    }
    target_start = _json(bases["h1"] / "target-start-order.json", "H1 target start order")
    target_specific = _list(_json(bases["h1"] / "target-container.json", "H1 target container"), "H1 target container")
    require(len(target_specific) == 1 and isinstance(target_specific[0], dict), "H1 target-container inspect did not return one container")
    target_id = target_specific[0].get("Id")
    target_raw_matches = [
        item for item in _list(raw_container_values["h1"], "H1 raw containers")
        if isinstance(item, dict) and item.get("Id") == target_id
    ]
    target_item = target_specific[0]
    target_start_object = _object(target_start, "H1 target start order")
    target_state = _object(target_item.get("State"), "H1 target container state")
    target_config = _object(target_item.get("Config"), "H1 target container config")
    raw_target = target_raw_matches[0] if len(target_raw_matches) == 1 else {}
    raw_target_state = _object(raw_target.get("State"), "H1 raw target container state")
    raw_target_config = _object(raw_target.get("Config"), "H1 raw target container config")
    require(
        len(target_raw_matches) == 1
        and all(target_item.get(field) == raw_target.get(field) for field in ("Id", "Image", "Name", "Created"))
        and target_item.get("Image") == build_values["ORDER_V2_IMAGE"]
        and target_config.get("Image") == build_values["ORDER_V2_IMAGE"]
        and raw_target_config.get("Image") == build_values["ORDER_V2_IMAGE"]
        and target_state.get("StartedAt") == raw_target_state.get("StartedAt")
        and target_start_object.get("container") == target_id
        and target_start_object.get("started_at") == target_state.get("StartedAt"),
        "H1 target-specific inspect/start is not the build-env v2 in raw containers",
    )
    normalized_containers = {
        "h0": _containers(raw_container_values["h0"], "h0", None),
        "h1": _containers(raw_container_values["h1"], "h1", target_start),
    }

    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.collect.", dir=output.parent))
    writer = _Writer(staging)
    try:
        order_artifact = writer.bytes("order.json", order_bytes["h0"])
        case_artifacts: dict[str, dict[str, dict[str, str]]] = {}
        deployment_artifacts: dict[str, dict[str, dict[str, str]]] = {}
        for name, base in bases.items():
            prefix = f"{name}/"
            history_artifact = writer.bytes(prefix + "runtime.history", _regular(base / "runtime.history", f"{name} History", limit=MAX_HISTORY))
            head_artifact = writer.bytes(prefix + "runtime.head", _regular(base / "runtime.head", f"{name} head"))
            history_view_artifact = writer.json(prefix + "history-view.json", events[name])
            requirement_artifact = writer.bytes(prefix + "requirement.json", requirement_bytes[name])
            certificate_state_artifact = writer.bytes(prefix + "certificate-state.json", _regular(base / "certificate-state-v2.json", f"{name} certificate state"))
            certificate_artifact = writer.bytes(prefix + "certificate.json", _regular(base / "certificate-v2.json", f"{name} certificate"))
            certificate_verdict_artifact = writer.bytes(prefix + "certificate-verdict.json", _regular(base / "certificate-verdict-v2.json", f"{name} certificate verdict"))
            final_state_artifact = writer.bytes(prefix + "final-state.json", _regular(base / "final-control-state.json", f"{name} final control state"))
            payment_artifact = writer.bytes(prefix + "payment.history", _regular(base / "payment.history", f"{name} payment History", limit=MAX_HISTORY))
            completion_artifact = writer.bytes(prefix + "completion.history", _regular(base / "completion.history", f"{name} completion History", limit=MAX_HISTORY))
            status_artifact = writer.bytes(prefix + "restate-status.raw.json", raw_status[name])
            journal_artifact = writer.bytes(prefix + "restate-journal.raw.json", raw_journal[name])
            workflow_artifact = writer.bytes(prefix + "restate-workflow-state.raw.json", raw_workflow[name])
            container_raw_bytes = _regular(base / "containers.raw.json", f"{name} raw containers")
            containers_raw_artifact = writer.bytes(prefix + "containers.raw.json", container_raw_bytes)
            containers_artifact = writer.json(prefix + "containers.json", normalized_containers[name])
            removal_artifact = writer.json(
                prefix + "v1-removal.json",
                _removal(base, build_values["ORDER_V1_IMAGE"], events[name], name),
            )

            cut = {
                "schema": 1,
                "invocation_id": status_rows[name].get("id"),
                "deployment_id": status_rows[name].get("pinned_deployment_id"),
                "endpoint": "order-v1",
                "status": "paused",
                "order_id": order_id,
                "input_sha256": order_artifact["sha256"],
                "payment_token": tokens[name],
                "payment_run": {"name": "payment", "completed": False},
                "journal": journals[name],
                "workflow_state": workflows[name],
                "raw_status_sha256": status_artifact["sha256"],
                "raw_journal_sha256": journal_artifact["sha256"],
                "raw_workflow_state_sha256": workflow_artifact["sha256"],
            }
            cut_artifact = writer.json(prefix + "restate-cut.json", cut)

            if name == "h0":
                final_status = _one_row(_json(base / "source-final-status.json", "H0 source final status"), "H0 source final status")
                require(final_status.get("id") == cut["invocation_id"] and final_status.get("status") == "paused", "H0 source final status differs")
                whole_key = _object(_json(base / "source-final-whole-key-invocations.json", "H0 final whole-key invocations"), "H0 final whole-key invocations")
                inbox = _object(_json(base / "source-final-inbox.json", "H0 final inbox"), "H0 final inbox")
                require(whole_key == {"rows": [status_rows[name]]}, "H0 whole-key status is not exactly the cut status")
                require(inbox == {"rows": []}, "H0 workflow inbox is not empty")
                restate_final = {
                    "schema": 1,
                    "source_invocation_id": cut["invocation_id"],
                    "source_status": "fenced",
                    "order_id": order_id,
                    "planned_target_endpoint": "order-v2",
                    "planned_target_program_sha256": build_values["V2_PROGRAM_SHA256"],
                    "continuation_started": False,
                    "order_status": workflows[name]["status"],
                }
            else:
                purged = _object(_json(base / "source-after-purge.json", "H1 source after purge"), "H1 source after purge")
                require(purged == {"rows": []}, "H1 source invocation was not purged")
                continuation = _one_row(_json(base / "continuation-invocation.json", "H1 continuation invocation"), "H1 continuation invocation")
                continuation_submit = _object(_json(base / "continuation-submit.json", "H1 continuation submit"), "H1 continuation submit")
                continuation_status = _json(base / "continuation-order-status.json", "H1 continuation order status")
                require(continuation.get("id") == cut["invocation_id"] and continuation_submit.get("invocationId") == cut["invocation_id"], "H1 continuation identity differs")
                require(continuation.get("status") == "completed" and continuation_status == "DELIVERED", "H1 continuation did not complete DELIVERED")
                restate_final = {
                    "schema": 1,
                    "source_invocation_id": cut["invocation_id"],
                    "source_status": "fenced",
                    "order_id": order_id,
                    "target_endpoint": "order-v2",
                    "target_program_sha256": build_values["V2_PROGRAM_SHA256"],
                    "continuation_started": True,
                    "order_status": continuation_status,
                }
            restate_final_artifact = writer.json(prefix + "restate-final.json", restate_final)

            raw_deployments_bytes = _regular(base / "deployments.json", f"{name} raw deployments")
            raw_deployments_artifact = writer.bytes(prefix + "restate-deployments.raw.json", raw_deployments_bytes)
            v1 = _deployment(pair_deployments[name], "v1")
            normalized_v1 = {
                "deployment_id": v1.get("id"),
                "endpoint": "order-v1",
                "image_id": build_values["ORDER_V1_IMAGE"],
                "context_sha256": build_values["V1_CONTEXT_SHA256"],
                "program_sha256": build_values["V1_PROGRAM_SHA256"],
            }
            normalized_deployments: dict[str, Any] = {
                "schema": 1,
                "restate_version": CHECK.RESTATE_VERSION,
                "server_image": CHECK.RESTATE_IMAGE,
                "raw_sha256": raw_deployments_artifact["sha256"],
                "v1": normalized_v1,
            }
            if name == "h1":
                v2 = _deployment(pair_deployments[name], "v2")
                normalized_deployments.update({
                    "v2": {
                        "deployment_id": v2.get("id"),
                        "endpoint": "order-v2",
                        "image_id": build_values["ORDER_V2_IMAGE"],
                        "context_sha256": build_values["V2_CONTEXT_SHA256"],
                        "program_sha256": build_values["V2_PROGRAM_SHA256"],
                    },
                    "target_program_sha256": build_values["V2_PROGRAM_SHA256"],
                })
            else:
                normalized_deployments["planned_target_program_sha256"] = build_values["V2_PROGRAM_SHA256"]
            normalized_deployments_artifact = writer.json(prefix + "restate-deployments.normalized.json", normalized_deployments)
            deployment_artifacts[name] = {"normalized": normalized_deployments_artifact, "raw": raw_deployments_artifact}

            case_artifacts[name] = {
                "history": history_artifact,
                "head": head_artifact,
                "history_view": history_view_artifact,
                "requirement": requirement_artifact,
                "certificate_state": certificate_state_artifact,
                "certificate": certificate_artifact,
                "certificate_verdict": certificate_verdict_artifact,
                "final_state": final_state_artifact,
                "payment_records": payment_artifact,
                "completion_records": completion_artifact,
                "restate_cut": cut_artifact,
                "restate_final": restate_final_artifact,
                "restate_status_raw": status_artifact,
                "restate_journal_raw": journal_artifact,
                "restate_workflow_state_raw": workflow_artifact,
                "containers": containers_artifact,
                "containers_raw": containers_raw_artifact,
                "v1_removal": removal_artifact,
            }

        manifest = {
            "schema": 1,
            "experiment": CHECK.EXPERIMENT,
            "domain": "restate-order-workflow",
            "upstream": {
                "repository": "https://github.com/restatedev/examples.git",
                "tag": "v1.7.7",
                "commit": CHECK.UPSTREAM_COMMIT,
                "restate_version": CHECK.RESTATE_VERSION,
                "restate_image": CHECK.RESTATE_IMAGE,
            },
            "order": {
                "order_id": order_id,
                "amount": amount,
                "payment_token": tokens["h0"],
                "input_sha256": order_artifact["sha256"],
                "input": order_artifact,
            },
            "target": {
                "program_sha256": build_values["V2_PROGRAM_SHA256"],
                "v2_context_sha256": build_values["V2_CONTEXT_SHA256"],
                "v1_image_id": build_values["ORDER_V1_IMAGE"],
                "v2_image_id": build_values["ORDER_V2_IMAGE"],
                "requirement_sha256": sha256(requirement_bytes["h0"]).hexdigest(),
            },
            "cases": case_artifacts,
            "restate_deployments": deployment_artifacts,
        }
        manifest_bytes = _canonical(manifest)
        (staging / "manifest.json").write_bytes(manifest_bytes)
        checked = CHECK.check_evidence(staging)
        os.rename(staging, output)
        return {
            "valid": True,
            "output": os.fspath(output),
            "manifest_sha256": sha256(manifest_bytes).hexdigest(),
            "checker": checked,
        }
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
