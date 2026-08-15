#!/usr/bin/env python3
"""Independent checker for the Restate food-ordering H0/H1 experiment.

The live harness is intentionally not imported.  The checker accepts one
strict, content-addressed evidence manifest, replays both binary Histories,
re-runs the standalone Certificate checker, and joins runtime progress to the
payment/completion records and Restate deployment/invocation evidence.

Raw Restate 1.7.3 journal evidence is the JSON result of this fixed query
(with the invocation predicate and ordering appended by the collector):

    SELECT index,version,entry_type,name,
           COALESCE(completed,false) AS completed,
           raw,raw_length,entry_lite_json FROM sys_journal

Using COALESCE is part of schema 1: Restate omits nullable columns in JSON,
while this checker deliberately requires a boolean ``completed`` value.  H0
must contain neither a registered/running target v2 nor a continuation.  H1's
target-v2 container projection must bind its start to a History sequence at or
after the target Rule activation.  Payment, replacement completion, and the
reported terminal Restate state must all retain the manifest's business order
identity; completing a newly named order is not continuation evidence.
"""

from __future__ import annotations

import argparse
import base64
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import struct
import subprocess
from typing import Any, Mapping, Sequence


ZERO_HASH = "0" * 64
MAX_JSON_BYTES = 16 << 20
MAX_HISTORY_BYTES = 64 << 20
MAX_FRAME_BYTES = 16 << 20
EXPERIMENT = "restate-food-ordering-history-cut-v1"
RESTATE_VERSION = "1.7.3"
RESTATE_IMAGE = (
    "docker.io/restatedev/restate:1.7.3@"
    "sha256:1856961b7a16d1b00131e5704231b79e0334703df074a31867ea8ce2110d5cfa"
)
UPSTREAM_COMMIT = "2d429daae784d20982691fb31431702b4ad30a6b"
HEX_40 = re.compile(r"[0-9a-f]{40}\Z")
HEX_64 = re.compile(r"[0-9a-f]{64}\Z")
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
OPERATION_ID = re.compile(r"op-[0-9a-f]{64}\Z")
BOOT_ID = re.compile(r"[0-9a-f]{32}\Z")
CONTAINER_ID = re.compile(r"[0-9a-f]{64}\Z")


class EvidenceError(ValueError):
    """Evidence is absent, malformed, inconsistent, or unsafe."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceError(message)


def _object(value: Any, label: str) -> dict[str, Any]:
    _require(isinstance(value, dict), f"{label} must be an object")
    return value


def _list(value: Any, label: str) -> list[Any]:
    _require(isinstance(value, list), f"{label} must be a list")
    return value


def _digest(value: Any, label: str) -> str:
    _require(isinstance(value, str) and HEX_64.fullmatch(value) is not None, f"{label} is not SHA-256")
    return value


def _duplicate_safe(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in output, f"JSON contains duplicate key {key!r}")
        output[key] = value
    return output


def _reject_constant(value: str) -> None:
    raise EvidenceError(f"JSON contains non-finite number {value}")


def _loads(data: bytes, label: str) -> Any:
    try:
        return json.loads(
            data,
            object_pairs_hook=_duplicate_safe,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvidenceError(f"{label} is not strict JSON") from error


def _read(path: Path, label: str, *, limit: int = MAX_JSON_BYTES) -> bytes:
    try:
        info = path.lstat()
    except FileNotFoundError as error:
        raise EvidenceError(f"required artifact is absent: {label}") from error
    _require(stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode), f"{label} is not a regular file")
    _require(info.st_size <= limit, f"{label} exceeds its size limit")
    data = path.read_bytes()
    _require(len(data) == info.st_size, f"{label} changed while read")
    return data


def _json(path: Path, label: str) -> Any:
    return _loads(_read(path, label), label)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _artifact(root: Path, value: Any, label: str) -> Path:
    item = _object(value, label)
    _require(set(item) == {"path", "sha256"}, f"{label} artifact fields changed")
    relative = item.get("path")
    _require(isinstance(relative, str) and relative, f"{label} path is absent")
    pure = PurePosixPath(relative)
    _require(not pure.is_absolute() and ".." not in pure.parts and "." not in pure.parts, f"{label} path escapes evidence root")
    path = root.joinpath(*pure.parts)
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as error:
        raise EvidenceError(f"required artifact is absent: {label}") from error
    _require(resolved == path, f"{label} path crosses a symbolic link")
    data = _read(path, label, limit=MAX_HISTORY_BYTES if path.name.endswith(".history") else MAX_JSON_BYTES)
    _require(sha256(data).hexdigest() == _digest(item.get("sha256"), label + " digest"), f"{label} digest differs")
    return path


def _operation_id(domain: str, call_id: str) -> str:
    digest = sha256()
    digest.update(b"operation-id-v1\x00")
    digest.update(domain.encode())
    digest.update(b"\x00")
    digest.update(call_id.encode())
    return "op-" + digest.hexdigest()


def _gateway_hash(url: str, operation_id: str, body: bytes) -> str:
    headers = {
        "accept-encoding": "identity",
        "idempotency-key": operation_id,
        "user-agent": "safe-change-runtime/1",
        "x-operation-id": operation_id,
    }
    digest = sha256()
    digest.update(b"POST\x00" + url.encode() + b"\x00")
    for name, value in sorted(headers.items()):
        digest.update(name.encode() + b":" + value.encode() + b"\x00")
    digest.update(body)
    return digest.hexdigest()


def _provider_hash(path: str, body: bytes) -> str:
    return sha256(b"POST\x00" + path.encode() + b"\x00" + body).hexdigest()


def _hash_part(value: bytes) -> bytes:
    return struct.pack(">Q", len(value)) + value


def _skip_space(data: bytes, position: int) -> int:
    while position < len(data) and data[position] in b" \t\r\n":
        position += 1
    return position


def _string_end(data: bytes, position: int) -> int:
    _require(position < len(data) and data[position] == ord('"'), "expected JSON string")
    position += 1
    while position < len(data):
        if data[position] == ord('"'):
            return position + 1
        if data[position] == ord("\\"):
            position += 2
        else:
            position += 1
    raise EvidenceError("unterminated JSON string")


def _value_end(data: bytes, position: int) -> int:
    position = _skip_space(data, position)
    _require(position < len(data), "missing JSON value")
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
                _require(byte == expected, "mismatched JSON delimiter")
                stack.pop()
            position += 1
        _require(not stack, "unterminated JSON value")
        return position
    while position < len(data) and data[position] not in b",}] \t\r\n":
        position += 1
    return position


def _raw_member(data: bytes, wanted: str) -> bytes:
    position = _skip_space(data, 0)
    _require(position < len(data) and data[position] == ord("{"), "History frame is not an object")
    position += 1
    found: bytes | None = None
    while True:
        position = _skip_space(data, position)
        _require(position < len(data), "unterminated History frame")
        if data[position] == ord("}"):
            break
        key_end = _string_end(data, position)
        key = _loads(data[position:key_end], "History member name")
        position = _skip_space(data, key_end)
        _require(position < len(data) and data[position] == ord(":"), "History member has no colon")
        start = _skip_space(data, position + 1)
        end = _value_end(data, start)
        if key == wanted:
            _require(found is None, f"duplicate History member {wanted}")
            found = data[start:end]
        position = _skip_space(data, end)
        _require(position < len(data), "unterminated History frame")
        if data[position] == ord(","):
            position += 1
            continue
        _require(data[position] == ord("}"), "invalid History object separator")
        break
    _require(found is not None, f"History omitted {wanted}")
    return found


def _event_hash(sequence: int, previous: str, operation: str, data: bytes) -> str:
    digest = sha256()
    digest.update(b"history-event-v1\x00")
    digest.update(struct.pack(">Q", sequence))
    digest.update(_hash_part(previous.encode()))
    digest.update(_hash_part(operation.encode()))
    digest.update(_hash_part(data))
    return digest.hexdigest()


def _history(path: Path) -> list[dict[str, Any]]:
    raw = _read(path, "binary History", limit=MAX_HISTORY_BYTES)
    offset = 0
    previous = ZERO_HASH
    events: list[dict[str, Any]] = []
    while offset < len(raw):
        _require(len(raw) - offset >= 12 and raw[offset : offset + 4] == b"HST1", "History frame header is invalid")
        length = struct.unpack(">Q", raw[offset + 4 : offset + 12])[0]
        _require(0 < length <= MAX_FRAME_BYTES, "History frame length is invalid")
        start, end = offset + 12, offset + 12 + length
        _require(end <= len(raw), "History final frame is incomplete")
        payload = raw[start:end]
        stored = _object(_loads(payload, f"History frame {len(events)+1}"), "History frame")
        _require(
            set(stored) == {"version", "sequence", "operation", "data", "previous_hash", "hash"},
            "History frame fields changed",
        )
        sequence = stored.get("sequence")
        operation = stored.get("operation")
        _require(stored.get("version") == 1 and type(sequence) is int and sequence == len(events) + 1, "History sequence/version differs")
        _require(isinstance(operation, str) and operation, "History operation is absent")
        _require(stored.get("previous_hash") == previous, "History previous hash differs")
        current = _digest(stored.get("hash"), "History event hash")
        _require(current == _event_hash(sequence, previous, operation, _raw_member(payload, "data")), "History frame hash differs")
        events.append({
            "sequence": sequence,
            "operation": operation,
            "data": stored["data"],
            "previous_hash": previous,
            "hash": current,
        })
        previous = current
        offset = end
    _require(events, "History is empty")
    return events


def _head(path: Path, events: Sequence[Mapping[str, Any]]) -> None:
    raw = _read(path, "History head")
    value = _object(_loads(raw, "History head"), "History head")
    _require(set(value) == {"version", "sequence", "hash", "checksum"} and value.get("version") == 1, "History head fields changed")
    sequence, history_hash = len(events), events[-1]["hash"]
    checksum = sha256(b"history-head-anchor-v1\x00" + struct.pack(">Q", sequence) + history_hash.encode()).hexdigest()
    _require(value == {"version": 1, "sequence": sequence, "hash": history_hash, "checksum": checksum}, "History head differs from replay")
    canonical = json.dumps(value, separators=(",", ":"), ensure_ascii=True).encode() + b"\n"
    _require(raw == canonical, "History head is not canonical")


def _records(path: Path, label: str) -> list[dict[str, Any]]:
    raw = _read(path, label)
    if raw == b"":
        return []
    _require(raw.endswith(b"\n"), f"{label} is not newline terminated")
    output: list[dict[str, Any]] = []
    for index, line in enumerate(raw.splitlines(), 1):
        item = _object(_loads(line, f"{label} line {index}"), f"{label} line {index}")
        _require(
            set(item) == {"operation_id", "request_hash", "result_hash", "remote_reference", "path"},
            f"{label} record fields changed",
        )
        _require(OPERATION_ID.fullmatch(str(item.get("operation_id"))) is not None, f"{label} Operation identity differs")
        _digest(item.get("request_hash"), f"{label} request hash")
        _digest(item.get("result_hash"), f"{label} result hash")
        _require(isinstance(item.get("remote_reference"), str) and item["remote_reference"], f"{label} remote reference is absent")
        output.append(item)
    return output


def _base64_bytes(value: Any, label: str) -> bytes:
    _require(isinstance(value, str), f"{label} is not base64")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, base64.binascii.Error) as error:
        raise EvidenceError(f"{label} is not canonical base64") from error
    _require(base64.b64encode(decoded).decode() == value, f"{label} is not canonical base64")
    return decoded


def _base64_json(value: Any, label: str) -> dict[str, Any]:
    return _object(_loads(_base64_bytes(value, label), label), label)


def _prepare_events(events: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.get("operation") != "operation.prepared":
            continue
        data = _object(event.get("data"), "Operation prepare data")
        _require(set(data) == {"semantic_version", "operation"} and data.get("semantic_version") == 1, "Operation prepare envelope changed")
        operation = _object(data.get("operation"), "prepared Operation")
        identifier = operation.get("id")
        _require(isinstance(identifier, str) and OPERATION_ID.fullmatch(identifier) is not None and identifier not in output, "prepared Operation identity differs")
        output[identifier] = operation
    return output


def _updates(events: Sequence[Mapping[str, Any]], operation_id: str) -> list[tuple[int, dict[str, Any]]]:
    output: list[tuple[int, dict[str, Any]]] = []
    for event in events:
        if event.get("operation") != "operation.phase":
            continue
        data = _object(event.get("data"), "Operation phase data")
        _require(set(data) == {"semantic_version", "id", "update"} and data.get("semantic_version") == 1, "Operation phase envelope changed")
        if data.get("id") == operation_id:
            output.append((int(event["sequence"]), _object(data.get("update"), "Operation update")))
    return output


def _replayed_operation(operation: Mapping[str, Any], updates: Sequence[tuple[int, Mapping[str, Any]]]) -> dict[str, Any]:
    """Apply the kernel's durable phase updates to one prepared Operation."""
    replayed = dict(operation)
    outcome_fields = {"result_hash", "status_code", "result_body", "remote_reference", "settlement"}
    for _, update in updates:
        replayed["phase"] = update.get("phase")
        for field in outcome_fields:
            replayed.pop(field, None)
            if field in update:
                replayed[field] = update[field]
        if update.get("phase") == "dispatched":
            replayed["dispatch_owner"] = update.get("dispatch_owner")
            replayed["dispatch_generation"] = update.get("dispatch_generation")
    return replayed


def _artifact_map(root: Path, case: Mapping[str, Any], label: str) -> dict[str, Path]:
    required = {
        "history", "head", "history_view", "requirement", "certificate_state",
        "certificate", "certificate_verdict", "final_state", "payment_records",
        "completion_records", "restate_cut", "restate_final", "restate_status_raw",
        "restate_journal_raw", "containers", "v1_removal",
    }
    _require(set(case) == required, f"{label} artifact set changed")
    return {name: _artifact(root, case[name], f"{label} {name}") for name in sorted(required)}


def _target_requirement(value: Any) -> dict[str, Any]:
    requirement = _object(value, "target Requirement")
    _require(set(requirement) == {"id", "results", "capacities", "kinds"}, "target Requirement fields changed")
    _require(requirement.get("id") == "food-ordering-v2", "target Requirement identity changed")
    _require(requirement.get("results") == {"paid": 1, "delivered": 1}, "target Requirement weakened business Results")
    _require(requirement.get("capacities") == {"charge": 1}, "target Requirement changed the one-charge cap")
    kinds = _object(requirement.get("kinds"), "target kinds")
    _require(set(kinds) == {"charge-v1", "finish"}, "target catalog changed")
    _require(
        kinds["charge-v1"]
        == {
            "costs": {"charge": 1}, "produces": {"paid": 1},
            "retry_safe": False, "queryable": False,
        },
        "target retained an executable payment producer",
    )
    _require(
        kinds["finish"]
        == {
            "costs": {}, "produces": {"delivered": 1},
            "retry_safe": True, "queryable": False,
            "target": "http://completion:8081/v1/complete", "method": "POST",
            "response_classifier": "operation-receipt-v1",
        },
        "target completion contract changed",
    )
    return requirement


def _contains_completion_id(value: Any, completion_id: int) -> bool:
    if isinstance(value, dict):
        return any(
            (key == "completion_id" and item == completion_id)
            or _contains_completion_id(item, completion_id)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_completion_id(item, completion_id) for item in value)
    return False


def _raw_restate_evidence(
    raw_status: Path,
    raw_journal: Path,
    cut: Mapping[str, Any],
    order: Mapping[str, Any],
    label: str,
) -> list[dict[str, Any]]:
    status_document = _object(_json(raw_status, label + " raw Restate status"), label + " raw Restate status")
    _require(set(status_document) == {"rows"}, f"{label} raw Restate status query fields changed")
    status_rows = [_object(item, f"{label} Restate status row") for item in _list(status_document.get("rows"), f"{label} Restate status rows")]
    _require(len(status_rows) == 1, f"{label} raw Restate status did not select one invocation")
    status = status_rows[0]
    allowed_status = {
        "id", "target", "status", "pinned_deployment_id",
        "pinned_service_protocol_version", "last_attempt_deployment_id",
        "retry_count", "next_retry_at", "journal_size", "created_at", "modified_at",
    }
    required_status = {
        "id", "target", "status", "pinned_deployment_id",
        "pinned_service_protocol_version", "last_attempt_deployment_id",
        "retry_count", "journal_size", "created_at", "modified_at",
    }
    _require(
        required_status <= set(status) <= allowed_status
        and status.get("id") == cut["invocation_id"]
        and status.get("status") == "paused"
        and status.get("pinned_deployment_id") == cut["deployment_id"]
        and status.get("last_attempt_deployment_id") == cut["deployment_id"]
        and type(status.get("pinned_service_protocol_version")) is int
        and 5 <= status["pinned_service_protocol_version"] <= 7
        and type(status.get("retry_count")) is int
        and status["retry_count"] >= 0
        and type(status.get("journal_size")) is int
        and isinstance(status.get("target"), str)
        and order["order_id"] in status["target"],
        f"{label} raw Restate invocation status differs",
    )
    for field in ("created_at", "modified_at"):
        _require(isinstance(status.get(field), str) and status[field], f"{label} Restate {field} is absent")

    journal_document = _object(_json(raw_journal, label + " raw Restate journal"), label + " raw Restate journal")
    _require(set(journal_document) == {"rows"}, f"{label} raw Restate journal query fields changed")
    raw_rows = [_object(item, f"{label} raw Restate journal row") for item in _list(journal_document.get("rows"), f"{label} raw Restate journal rows")]
    _require(raw_rows and status["journal_size"] == len(raw_rows), f"{label} journal size differs from invocation status")
    allowed_journal = {
        "index", "version", "entry_type", "name", "completed", "raw",
        "raw_length", "entry_lite_json",
    }
    required_journal = allowed_journal - {"name"}
    payment_rows: list[tuple[dict[str, Any], int]] = []
    lite_rows: list[Any] = []
    normalized = _list(cut.get("journal"), f"{label} normalized journal")
    _require(len(normalized) == len(raw_rows), f"{label} normalized/raw journal lengths differ")
    for index, (row, projected_value) in enumerate(zip(raw_rows, normalized)):
        _require(required_journal <= set(row) <= allowed_journal, f"{label} raw Restate journal columns changed")
        _require(
            row.get("index") == index
            and type(row.get("version")) is int
            and row["version"] > 0
            and isinstance(row.get("entry_type"), str)
            and type(row.get("completed")) is bool
            and isinstance(row.get("raw"), str)
            and type(row.get("raw_length")) is int
            and row["raw_length"] >= 0
            and isinstance(row.get("entry_lite_json"), str),
            f"{label} raw Restate journal row {index} is malformed",
        )
        try:
            raw_payload = bytes.fromhex(row["raw"])
        except ValueError as error:
            raise EvidenceError(f"{label} raw Restate journal row {index} is not hex") from error
        _require(len(raw_payload) == row["raw_length"], f"{label} raw Restate journal row {index} length differs")
        lite = _loads(row["entry_lite_json"].encode(), f"{label} Restate journal lite row {index}")
        lite_rows.append(lite)
        projected = _object(projected_value, f"{label} normalized journal entry")
        _require(
            projected
            == {
                "index": index,
                "kind": row["entry_type"],
                "name": row.get("name", ""),
                "completed": row["completed"],
                "payload_sha256": sha256(raw_payload).hexdigest(),
            },
            f"{label} normalized journal entry {index} differs from raw Restate data",
        )
        if row["entry_type"] == "Command: Run" and row.get("name", "") == "payment":
            command = _object(_object(lite, f"{label} payment Run lite").get("Command"), f"{label} payment Run Command")
            run = _object(command.get("Run"), f"{label} payment Run")
            completion_id = run.get("completion_id")
            _require(
                type(completion_id) is int
                and completion_id > 0
                and run.get("name") == "payment",
                f"{label} payment Run identity differs",
            )
            payment_rows.append((row, completion_id))
    _require(len(payment_rows) == 1, f"{label} raw journal omitted the unique payment Run")
    payment_row, completion_id = payment_rows[0]
    _require(payment_row is raw_rows[-1] and payment_row["completed"] is False, f"{label} payment Run was not the unresolved journal tail")
    _require(
        not any(
            row["entry_type"].startswith("Notification:")
            and _contains_completion_id(lite, completion_id)
            for row, lite in zip(raw_rows, lite_rows)
        ),
        f"{label} raw journal contains a payment completion notification",
    )
    return raw_rows


def _check_cut(
    path: Path,
    raw_status: Path,
    raw_journal: Path,
    order: Mapping[str, Any],
    label: str,
) -> dict[str, Any]:
    cut = _object(_json(path, label + " Restate cut"), label + " Restate cut")
    _require(
        set(cut)
        == {
            "schema", "invocation_id", "deployment_id", "endpoint", "status",
            "order_id", "input_sha256", "payment_token", "payment_run",
            "journal", "workflow_state", "raw_status_sha256", "raw_journal_sha256",
        }
        and cut.get("schema") == 1,
        f"{label} Restate cut fields changed",
    )
    _require(
        cut.get("endpoint") == "order-v1"
        and cut.get("status") == "paused"
        and cut.get("order_id") == order["order_id"]
        and cut.get("input_sha256") == order["input_sha256"]
        and cut.get("payment_token") == order["payment_token"],
        f"{label} Restate cut identity/input differs",
    )
    _require(isinstance(cut.get("invocation_id"), str) and cut["invocation_id"], f"{label} invocation identity is absent")
    _require(isinstance(cut.get("deployment_id"), str) and cut["deployment_id"], f"{label} deployment identity is absent")
    payment_run = _object(cut.get("payment_run"), f"{label} payment run")
    _require(payment_run == {"name": "payment", "completed": False}, f"{label} payment closure already returned")
    journal = [_object(value, f"{label} journal entry") for value in _list(cut.get("journal"), f"{label} journal")]
    _require(journal, f"{label} journal is empty")
    for index, entry in enumerate(journal):
        _require(
            set(entry) == {"index", "kind", "name", "completed", "payload_sha256"}
            and entry.get("index") == index
            and isinstance(entry.get("kind"), str)
            and isinstance(entry.get("name"), str)
            and type(entry.get("completed")) is bool,
            f"{label} normalized journal entry changed",
        )
        _digest(entry.get("payload_sha256"), f"{label} journal payload hash")
    payment_entries = [entry for entry in journal if entry.get("kind") == "Command: Run" and entry.get("name") == "payment"]
    _require(len(payment_entries) == 1 and payment_entries[0].get("completed") is False, f"{label} journal does not contain one unresolved payment run")
    _require(isinstance(cut.get("workflow_state"), dict), f"{label} workflow state is absent")
    _require(sha256(_read(raw_status, label + " raw Restate status")).hexdigest() == cut.get("raw_status_sha256"), f"{label} raw status hash differs")
    _require(sha256(_read(raw_journal, label + " raw Restate journal")).hexdigest() == cut.get("raw_journal_sha256"), f"{label} raw journal hash differs")
    _raw_restate_evidence(raw_status, raw_journal, cut, order, label)
    return cut


def _cut_projection(cut: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "endpoint": cut["endpoint"],
        "status": cut["status"],
        "order_id": cut["order_id"],
        "input_sha256": cut["input_sha256"],
        "payment_token": cut["payment_token"],
        "payment_run": cut["payment_run"],
        "journal": cut["journal"],
        "workflow_state": cut["workflow_state"],
    }


def _check_deployment(root: Path, value: Any, target: Mapping[str, Any], label: str) -> dict[str, Any]:
    spec = _object(value, f"{label} Restate deployment evidence")
    _require(set(spec) == {"normalized", "raw"}, f"{label} Restate deployment artifact set changed")
    normalized_path = _artifact(root, spec["normalized"], f"{label} normalized Restate deployments")
    raw_path = _artifact(root, spec["raw"], f"{label} raw Restate deployments")
    deployment = _object(_json(normalized_path, f"{label} normalized Restate deployments"), f"{label} normalized Restate deployments")
    expected_fields = (
        {"schema", "restate_version", "server_image", "raw_sha256", "v1", "v2", "target_program_sha256"}
        if label == "h1"
        else {"schema", "restate_version", "server_image", "raw_sha256", "v1", "planned_target_program_sha256"}
    )
    _require(
        set(deployment) == expected_fields
        and deployment.get("schema") == 1
        and deployment.get("restate_version") == RESTATE_VERSION
        and deployment.get("server_image") == RESTATE_IMAGE
        and deployment.get("raw_sha256") == sha256(_read(raw_path, f"{label} raw Restate deployments")).hexdigest(),
        f"{label} Restate deployment provenance differs",
    )
    v1 = _object(deployment.get("v1"), f"{label} Restate v1 deployment")
    _require(
        set(v1) == {"deployment_id", "endpoint", "image_id", "context_sha256", "program_sha256"}
        and isinstance(v1.get("deployment_id"), str)
        and v1.get("endpoint") == "order-v1"
        and v1.get("image_id") == target["v1_image_id"],
        f"{label} Restate v1 deployment differs",
    )
    _digest(v1.get("context_sha256"), f"{label} Restate v1 context hash")
    _digest(v1.get("program_sha256"), f"{label} Restate v1 program hash")
    wanted = ["v1"]
    if label == "h1":
        v2 = _object(deployment.get("v2"), "H1 Restate v2 deployment")
        _require(
            set(v2) == {"deployment_id", "endpoint", "image_id", "context_sha256", "program_sha256"}
            and isinstance(v2.get("deployment_id"), str)
            and v2.get("endpoint") == "order-v2"
            and v2.get("image_id") == target["v2_image_id"]
            and v2.get("context_sha256") == target["v2_context_sha256"]
            and v2.get("program_sha256") == target["program_sha256"]
            and deployment.get("target_program_sha256") == target["program_sha256"],
            "H1 registered target v2 hash differs",
        )
        wanted.append("v2")
    else:
        _require(
            deployment.get("planned_target_program_sha256") == target["program_sha256"],
            "H0 planned target hash differs",
        )

    raw = _object(_json(raw_path, f"{label} raw Restate deployments"), f"{label} raw Restate deployments")
    _require(set(raw) == {"deployments"}, f"{label} raw Restate deployment response fields changed")
    raw_items = [_object(item, f"{label} raw Restate deployment") for item in _list(raw.get("deployments"), f"{label} raw Restate deployments")]
    if label == "h0":
        _require(
            not any(item.get("uri") == "http://order-v2:9080/" for item in raw_items),
            "H0 registered the refused target v2 deployment",
        )
    revisions: dict[str, int] = {}
    for version in wanted:
        expected = deployment[version]
        matches = [item for item in raw_items if item.get("id") == expected["deployment_id"]]
        _require(len(matches) == 1, f"{label} raw Restate deployments omitted unique {version} deployment")
        item = matches[0]
        required = {
            "id", "uri", "protocol_type", "http_version", "metadata", "created_at",
            "min_protocol_version", "max_protocol_version", "sdk_version", "services",
        }
        _require(required <= set(item), f"{label} raw Restate {version} deployment fields changed")
        _require(
            item.get("uri") == f"http://order-{version}:9080/"
            and item.get("protocol_type") == "BidiStream"
            and item.get("http_version") == "HTTP/2.0"
            and isinstance(item.get("created_at"), str)
            and item["created_at"]
            and type(item.get("min_protocol_version")) is int
            and type(item.get("max_protocol_version")) is int
            and item["min_protocol_version"] <= item["max_protocol_version"]
            and isinstance(item.get("sdk_version"), str)
            and item["sdk_version"].startswith("restate-sdk-typescript/"),
            f"{label} raw Restate {version} endpoint/protocol differs",
        )
        metadata = _object(item.get("metadata"), f"{label} raw Restate {version} metadata")
        _require(metadata.get("variant", metadata.get("version")) == version, f"{label} raw Restate {version} metadata differs")
        services = [_object(service, f"{label} raw Restate {version} service") for service in _list(item.get("services"), f"{label} raw Restate {version} services")]
        order_services = [service for service in services if service.get("name") == "order-workflow"]
        _require(
            len(order_services) == 1
            and set(order_services[0]) == {"name", "revision"}
            and type(order_services[0].get("revision")) is int,
            f"{label} raw Restate {version} omitted order-workflow revision",
        )
        revisions[version] = order_services[0]["revision"]
    if label == "h1":
        _require(revisions["v2"] > revisions["v1"], "H1 target v2 is not a later Restate service revision")
    return deployment


def _check_containers(
    path: Path,
    target: Mapping[str, Any],
    label: str,
    activation_sequence: int,
) -> None:
    value = _object(_json(path, label + " containers"), label + " containers")
    _require(set(value) == {"schema", "items"} and value.get("schema") == 1, f"{label} container evidence fields changed")
    items = [_object(item, f"{label} container") for item in _list(value.get("items"), f"{label} containers")]
    by_role: dict[str, dict[str, Any]] = {}
    for item in items:
        expected_item_fields = {"role", "name", "image_id", "running", "networks"}
        if item.get("role") == "target-v2":
            expected_item_fields.add("started_after_history_sequence")
        _require(
            set(item) == expected_item_fields
            and isinstance(item.get("role"), str)
            and item["role"] not in by_role
            and isinstance(item.get("name"), str)
            and IMAGE_ID.fullmatch(str(item.get("image_id"))) is not None
            and item.get("running") is True
            and isinstance(item.get("networks"), list),
            f"{label} container projection is invalid",
        )
        by_role[item["role"]] = item
    _require({"restate", "control"} <= set(by_role), f"{label} omitted a required live component")
    _require("source-v1" not in by_role, f"{label} still retains the v1 worker")
    if label == "h1":
        _require(
            "target-v2" in by_role
            and by_role["target-v2"]["image_id"] == target["v2_image_id"]
            and type(by_role["target-v2"].get("started_after_history_sequence")) is int
            and by_role["target-v2"]["started_after_history_sequence"] >= activation_sequence,
            "H1 target v2 did not start after target Rule activation",
        )
    else:
        _require("target-v2" not in by_role, "H0 started the refused target v2 container")


def _check_removal(path: Path, activation_sequence: int, label: str) -> None:
    value = _object(_json(path, label + " v1 removal"), label + " v1 removal")
    _require(
        set(value) == {
            "schema", "compose_service", "container_id", "remove_exit_code",
            "inspect_exit_code", "stderr", "fenced_before_history_sequence",
        }
        and value.get("schema") == 1
        and value.get("compose_service") == "order-v1"
        and CONTAINER_ID.fullmatch(str(value.get("container_id"))) is not None
        and value.get("remove_exit_code") == 0
        and type(value.get("inspect_exit_code")) is int
        and value["inspect_exit_code"] != 0
        and isinstance(value.get("stderr"), str)
        and "no such" in value["stderr"].lower()
        and value["container_id"] in value["stderr"]
        and type(value.get("fenced_before_history_sequence")) is int
        and value["fenced_before_history_sequence"] <= activation_sequence,
        f"{label} did not prove v1 fenced by the edit decision boundary",
    )


def _fresh_certificate(
    runtime_dir: Path,
    state_path: Path,
    certificate_path: Path,
    saved: Mapping[str, Any],
    label: str,
) -> None:
    completed = subprocess.run(
        [
            "go", "run", "./cmd/check-certificate",
            "-state", os.fspath(state_path.resolve()),
            "-certificate", os.fspath(certificate_path.resolve()),
        ],
        cwd=runtime_dir,
        text=True,
        capture_output=True,
        timeout=120.0,
        check=False,
    )
    _require(completed.returncode == 0, f"fresh {label} Certificate check failed")
    fresh = _object(_loads(completed.stdout.encode(), f"fresh {label} Certificate verdict"), f"fresh {label} Certificate verdict")
    _require(fresh == saved, f"fresh {label} Certificate verdict differs")


def _check_case(
    root: Path,
    name: str,
    paths: Mapping[str, Path],
    domain: str,
    order: Mapping[str, Any],
    target: Mapping[str, Any],
    requirement: Mapping[str, Any],
    cut: Mapping[str, Any],
    runtime_dir: Path,
    fresh_certificates: bool,
) -> dict[str, Any]:
    events = _history(paths["history"])
    _head(paths["head"], events)
    _require(_json(paths["history_view"], name + " History view") == events, f"{name} History view differs from replay")
    _require(
        all(event["operation"] in {"rule.activated", "operation.prepared", "operation.phase"} for event in events),
        f"{name} History contains an unsupported event type",
    )
    final_state = _object(_json(paths["final_state"], name + " final State"), name + " final State")
    _require(
        set(final_state) == {"history", "requirement", "rule", "operations"}
        and final_state.get("history") == {"sequence": len(events), "hash": events[-1]["hash"]}
        and isinstance(final_state.get("operations"), dict),
        f"{name} final State differs from the replayed head/schema",
    )

    certificate = _object(_json(paths["certificate"], name + " Certificate"), name + " Certificate")
    certificate_state = _object(_json(paths["certificate_state"], name + " Certificate state"), name + " Certificate state")
    verdict = _object(_json(paths["certificate_verdict"], name + " Certificate verdict"), name + " Certificate verdict")
    expected_decision = "activate" if name == "h1" else "impossible"
    _require(
        set(certificate)
        == ({"schema", "decision", "history", "from_rule", "requirement", "rule", "digest"} if name == "h1" else {"schema", "decision", "history", "from_rule", "requirement", "witness", "digest"})
        and certificate.get("schema") == 1
        and certificate.get("decision") == expected_decision
        and type(certificate.get("from_rule")) is int
        and certificate.get("requirement") == requirement
        and set(certificate_state) == {"schema", "history", "from_rule", "settled", "open_operations"}
        and certificate_state.get("schema") == 1
        and certificate_state.get("history") == certificate.get("history")
        and certificate_state.get("from_rule") == certificate.get("from_rule")
        and set(verdict) == ({"valid", "decision", "history_sequence", "history_hash", "rule_version"} if name == "h1" else {"valid", "decision", "history_sequence", "history_hash"})
        and verdict.get("valid") is True
        and verdict.get("decision") == expected_decision
        and verdict.get("history_sequence") == certificate["history"]["sequence"]
        and verdict.get("history_hash") == certificate["history"]["hash"],
        f"{name} Certificate binding/decision differs",
    )
    point = _object(certificate.get("history"), name + " Certificate History point")
    sequence = point.get("sequence")
    _require(type(sequence) is int and 0 <= sequence <= len(events), f"{name} Certificate sequence is invalid")
    expected_hash = ZERO_HASH if sequence == 0 else events[sequence - 1]["hash"]
    _require(point.get("hash") == expected_hash, f"{name} Certificate does not bind replayed History")
    _digest(certificate.get("digest"), f"{name} Certificate digest")
    if fresh_certificates:
        _fresh_certificate(runtime_dir, paths["certificate_state"], paths["certificate"], verdict, name)

    rule_events = [event for event in events if event["operation"] == "rule.activated"]
    _require(len(rule_events) == (2 if name == "h1" else 1), f"{name} Rule activation count differs")
    for event in rule_events:
        envelope = _object(event["data"], f"{name} Rule activation envelope")
        _require(
            set(envelope) == {"semantic_version", "certificate"}
            and envelope.get("semantic_version") == 1
            and isinstance(envelope.get("certificate"), dict),
            f"{name} Rule activation envelope changed",
        )
    source_certificate = _object(rule_events[0]["data"]["certificate"], f"{name} source Certificate")
    source_rule = _object(source_certificate.get("rule"), f"{name} source Rule")
    source_requirement = _object(source_certificate.get("requirement"), f"{name} source Requirement")
    source_allow = _list(source_rule.get("allow"), f"{name} source Rule allow")
    _require(
        rule_events[0]["sequence"] == 1
        and source_certificate.get("schema") == 1
        and source_certificate.get("decision") == "activate"
        and source_certificate.get("history") == {"sequence": 0, "hash": ZERO_HASH}
        and source_certificate.get("from_rule") == 0
        and source_requirement.get("id") == "food-ordering-v1"
        and source_requirement.get("results") == {"paid": 1, "delivered": 1}
        and source_requirement.get("capacities") == {"charge": 1}
        and source_rule.get("version") == 1
        and all(isinstance(kind, str) for kind in source_allow)
        and sorted(source_allow) == ["charge-v1", "finish"]
        and certificate.get("from_rule") == source_rule["version"],
        f"{name} source v1 Rule/Requirement differs",
    )

    payment_id = _operation_id(domain, str(order["payment_token"]))
    completion_call = f"order/{order['order_id']}/completion"
    completion_id = _operation_id(domain, completion_call)
    payment_body = json.dumps(
        {"order_id": order["order_id"], "amount": order["amount"]},
        separators=(",", ":"), ensure_ascii=True,
    ).encode()
    completion_body = json.dumps(
        {"order_id": order["order_id"], "status": "DELIVERED"},
        separators=(",", ":"), ensure_ascii=True,
    ).encode()
    prepared = _prepare_events(events)
    for event in events:
        if event["operation"] != "operation.phase":
            continue
        phase_data = _object(event["data"], f"{name} Operation phase envelope")
        _require(phase_data.get("id") in prepared, f"{name} Operation phase refers to an unprepared identity")
    _require(payment_id in prepared, f"{name} History omitted the stable payment Operation")
    payment = prepared[payment_id]
    expected_payment = {
        "id": payment_id,
        "domain": domain,
        "kind": "charge-v1",
        "request_hash": _gateway_hash("http://payment:8081/v1/charge", payment_id, payment_body),
        "rule_version": certificate["from_rule"],
        "costs": {"charge": 1},
        "produces": {"paid": 1},
        "retry_safe": False,
        "queryable": True,
        "target": "http://payment:8081/v1/charge",
        "method": "POST",
        "response_classifier": "operation-receipt-v1",
        "query_target": "http://payment:8081/v1/query",
        "query_method": "POST",
        "query_classifier": "operation-observation-v1",
        "request_stored": True,
        "request_body": base64.b64encode(payment_body).decode(),
        "phase": "prepared",
    }
    _require(
        payment == expected_payment,
        f"{name} frozen payment Operation differs",
    )
    payment_updates = _updates(events, payment_id)
    phases = [update.get("phase") for _, update in payment_updates]
    expected_phases = ["dispatched", "unknown", "succeeded"] if name == "h1" else ["dispatched", "unknown"]
    _require(phases == expected_phases, f"{name} payment lifecycle differs")
    dispatches = [(seq, update) for seq, update in payment_updates if update.get("phase") == "dispatched"]
    _require(
        len(dispatches) == 1
        and set(dispatches[0][1]) == {"phase", "dispatch_owner", "dispatch_generation"}
        and dispatches[0][1].get("dispatch_generation") == 1
        and BOOT_ID.fullmatch(str(dispatches[0][1].get("dispatch_owner"))) is not None,
        f"{name} payment was redispatched",
    )
    _require(payment_updates[1][1] == {"phase": "unknown"}, f"{name} unknown payment marker changed")

    payments = _records(paths["payment_records"], name + " payment records")
    completions = _records(paths["completion_records"], name + " completion records")
    if name == "h1":
        _require(len(payments) == 1, "H1 must contain exactly one durable payment")
        record = payments[0]
        expected_result = sha256(b"charged\x00" + payment_id.encode() + b"\x001").hexdigest()
        _require(
            record
            == {
                "operation_id": payment_id,
                "request_hash": _provider_hash("/v1/charge", payment_body),
                "result_hash": expected_result,
                "remote_reference": f"payment/{payment_id}/commit-1",
                "path": "/v1/charge",
            },
            "H1 durable payment record differs",
        )
        success = payment_updates[-1][1]
        _require(
            set(success) == {"phase", "result_hash", "status_code", "result_body", "remote_reference", "settlement"}
            and success.get("phase") == "succeeded"
            and success.get("settlement") == "query"
            and success.get("result_hash") == expected_result
            and success.get("status_code") == 200
            and success.get("remote_reference") == record["remote_reference"],
            "H1 payment was not settled from the authoritative fact",
        )
        observation = _base64_json(success.get("result_body"), "H1 payment observation")
        _require(
            observation
            == {
                "schema": 1,
                "operation_id": payment_id,
                "request_hash": payment["request_hash"],
                "outcome": "succeeded",
                "fact_hash": expected_result,
                "remote_reference": record["remote_reference"],
            },
            "H1 payment observation does not authenticate the durable payment record",
        )
    else:
        _require(payments == [], "H0 unexpectedly contains a durable payment")

    activation_sequence: int
    matching_activation = [
        event for event in events
        if event.get("operation") == "rule.activated"
        and isinstance(event.get("data"), dict)
        and event["data"].get("certificate") == certificate
    ]
    if name == "h1":
        _require(len(matching_activation) == 1, "H1 target Certificate was not activated exactly once")
        activation_sequence = int(matching_activation[0]["sequence"])
        _require(sequence + 1 == activation_sequence, "H1 target Certificate was not activated at its bound History head")
        rule = _object(certificate.get("rule"), "H1 target Rule")
        _require(
            rule.get("allow") == ["finish"]
            and type(rule.get("version")) is int
            and rule.get("version") == certificate["from_rule"] + 1,
            "H1 target Rule did not permit only completion",
        )
        _require(certificate_state.get("settled") == {"used": {"charge": 1}, "results": {"paid": 1}}, "H1 Certificate state omitted paid/charge facts")
        _require(certificate_state.get("open_operations") == {}, "H1 Certificate state retained an open payment")
        _require(completion_id in prepared, "H1 History omitted completion Operation")
        completion = prepared[completion_id]
        expected_completion = {
            "id": completion_id,
            "domain": domain,
            "kind": "finish",
            "request_hash": _gateway_hash("http://completion:8081/v1/complete", completion_id, completion_body),
            "rule_version": rule["version"],
            "costs": {},
            "produces": {"delivered": 1},
            "retry_safe": True,
            "queryable": False,
            "target": "http://completion:8081/v1/complete",
            "method": "POST",
            "response_classifier": "operation-receipt-v1",
            "request_stored": True,
            "request_body": base64.b64encode(completion_body).decode(),
            "phase": "prepared",
        }
        _require(
            completion == expected_completion,
            "H1 completion Operation differs",
        )
        completion_updates = _updates(events, completion_id)
        _require([update.get("phase") for _, update in completion_updates] == ["dispatched", "succeeded"], "H1 completion lifecycle differs")
        _require(
            set(completion_updates[0][1]) == {"phase", "dispatch_owner", "dispatch_generation"}
            and completion_updates[0][1]["dispatch_generation"] == 1
            and BOOT_ID.fullmatch(str(completion_updates[0][1]["dispatch_owner"])) is not None,
            "H1 completion dispatch marker differs",
        )
        _require(completion_updates[0][0] > activation_sequence, "H1 completion ran before target activation")
        _require(len(completions) == 1, "H1 must contain exactly one terminal completion")
        completion_record = completions[0]
        expected_completion_fact = sha256(b"charged\x00" + completion_id.encode()).hexdigest()
        _require(
            completion_record
            == {
                "operation_id": completion_id,
                "request_hash": _provider_hash("/v1/complete", completion_body),
                "result_hash": expected_completion_fact,
                "remote_reference": f"completion/{completion_id}",
                "path": "/v1/complete",
            },
            "H1 durable completion record differs",
        )
        completion_success = completion_updates[1][1]
        receipt_body = _base64_bytes(completion_success.get("result_body"), "H1 completion receipt")
        expected_gateway_result = sha256(b"200\x00" + receipt_body).hexdigest()
        _require(
            set(completion_success) == {"phase", "result_hash", "status_code", "result_body", "remote_reference"}
            and completion_success.get("result_hash") == expected_gateway_result
            and completion_success.get("status_code") == 200
            and completion_success.get("remote_reference") == completion_record["remote_reference"],
            "H1 completion success marker differs",
        )
        receipt = _object(_loads(receipt_body, "H1 completion receipt"), "H1 completion receipt")
        _require(
            receipt
            == {
                "schema": 1,
                "operation_id": completion_id,
                "outcome": "succeeded",
                "result_hash": expected_completion_fact,
                "remote_reference": completion_record["remote_reference"],
            },
            "H1 completion receipt does not authenticate the durable completion record",
        )
        final_rule = _object(final_state.get("rule"), "H1 final Rule")
        _require(
            final_state.get("requirement") == requirement
            and final_rule == {"version": rule["version"], "requirement_hash": rule["requirement_hash"], "allow": ["finish"]},
            "H1 did not finish paid and delivered Results",
        )
    else:
        _require(not matching_activation, "H0 impossible Certificate was activated")
        activation_sequence = sequence
        _require(sequence == len(events), "H0 impossibility Certificate is stale")
        _require(certificate.get("rule") is None and isinstance(certificate.get("witness"), dict), "H0 has no impossibility witness")
        open_operations = _object(certificate_state.get("open_operations"), "H0 open Operations")
        _require(
            open_operations
            == {
                payment_id: {
                    "id": payment_id,
                    "costs": {"charge": 1},
                    "produces": {"paid": 1},
                    "retry_safe": False,
                    "queryable": True,
                }
            }
            and certificate_state.get("settled") == {"used": {}, "results": {}},
            "H0 Certificate state differs from one unresolved payment",
        )
        _require(completion_id not in prepared and completions == [], "H0 executed terminal completion")

    expected_prepared = {payment_id, completion_id} if name == "h1" else {payment_id}
    _require(set(prepared) == expected_prepared, f"{name} History contains an unexpected external Operation")
    final_operations = _object(final_state.get("operations"), f"{name} final Operations")
    _require(set(final_operations) == expected_prepared, f"{name} final State contains an unexpected external Operation")
    for operation_id in expected_prepared:
        _require(
            _object(final_operations[operation_id], f"{name} final Operation")
            == _replayed_operation(prepared[operation_id], _updates(events, operation_id)),
            f"{name} final Operation differs from History replay",
        )

    _require(all(seq < activation_sequence for seq, _ in dispatches), f"{name} issued a v1 payment after target activation")
    _check_containers(paths["containers"], target, name, activation_sequence)
    _check_removal(paths["v1_removal"], activation_sequence, name)
    final = _object(_json(paths["restate_final"], name + " Restate final"), name + " Restate final")
    if name == "h1":
        _require(
            set(final) == {"schema", "source_invocation_id", "source_status", "order_id", "target_endpoint", "target_program_sha256", "continuation_started", "order_status"}
            and final.get("schema") == 1
            and final.get("source_invocation_id") == cut["invocation_id"]
            and final.get("source_status") == "fenced"
            and final.get("order_id") == order["order_id"]
            and final.get("target_endpoint") == "order-v2"
            and final.get("target_program_sha256") == target["program_sha256"]
            and final.get("continuation_started") is True
            and final.get("order_status") == "DELIVERED",
            "H1 did not finish under fenced-v1/v2",
        )
    else:
        _require(
            set(final) == {"schema", "source_invocation_id", "source_status", "order_id", "planned_target_endpoint", "planned_target_program_sha256", "continuation_started", "order_status"}
            and final.get("schema") == 1
            and final.get("source_invocation_id") == cut["invocation_id"]
            and final.get("source_status") == "fenced"
            and final.get("order_id") == order["order_id"]
            and final.get("planned_target_endpoint") == "order-v2"
            and final.get("planned_target_program_sha256") == target["program_sha256"]
            and final.get("continuation_started") is False
            and final.get("order_status") != "DELIVERED",
            "H0 did not remain safely refused",
        )
    return {
        "events": events,
        "certificate": certificate,
        "payment": payment,
        "payment_dispatches": len(dispatches),
        "payment_commits": len(payments),
        "completion_commits": len(completions),
    }


def check_evidence(
    directory: Path | str,
    *,
    runtime_dir: Path | str | None = None,
    fresh_certificates: bool = True,
) -> dict[str, Any]:
    root = Path(directory).resolve()
    manifest = _object(_json(root / "manifest.json", "manifest"), "manifest")
    _require(
        set(manifest) == {"schema", "experiment", "domain", "upstream", "order", "target", "cases", "restate_deployments"}
        and manifest.get("schema") == 1
        and manifest.get("experiment") == EXPERIMENT,
        "manifest schema/experiment differs",
    )
    domain = manifest.get("domain")
    _require(domain == "restate-order-workflow", "Operation domain differs")
    upstream = _object(manifest.get("upstream"), "upstream provenance")
    _require(
        upstream
        == {
            "repository": "https://github.com/restatedev/examples.git",
            "tag": "v1.7.7",
            "commit": UPSTREAM_COMMIT,
            "restate_version": RESTATE_VERSION,
            "restate_image": RESTATE_IMAGE,
        },
        "upstream Restate provenance differs",
    )
    order = _object(manifest.get("order"), "order")
    _require(
        set(order) == {"order_id", "amount", "payment_token", "input_sha256", "input"}
        and isinstance(order.get("order_id"), str)
        and order.get("order_id")
        and type(order.get("amount")) is int
        and order["amount"] > 0
        and isinstance(order.get("payment_token"), str)
        and order.get("payment_token"),
        "order identity/body fields differ",
    )
    input_path = _artifact(root, order["input"], "order input")
    input_bytes = _read(input_path, "order input")
    _require(sha256(input_bytes).hexdigest() == _digest(order.get("input_sha256"), "order input hash"), "order input hash differs")
    input_value = _object(_loads(input_bytes, "order input"), "order input")
    _require(
        input_value.get("id") == order["order_id"]
        and input_value.get("totalCost") == order["amount"],
        "order input identity/amount differs",
    )

    target = _object(manifest.get("target"), "target v2")
    _require(
        set(target) == {"program_sha256", "v2_context_sha256", "v1_image_id", "v2_image_id", "requirement_sha256"},
        "target v2 fields changed",
    )
    for key in ("program_sha256", "v2_context_sha256", "requirement_sha256"):
        _digest(target.get(key), "target " + key)
    for key in ("v1_image_id", "v2_image_id"):
        _require(IMAGE_ID.fullmatch(str(target.get(key))) is not None, "target image identity differs")
    _require(target["v1_image_id"] != target["v2_image_id"], "v1 and v2 images are identical")
    deployment_specs = _object(manifest.get("restate_deployments"), "Restate deployment cases")
    _require(set(deployment_specs) == {"h0", "h1"}, "Restate deployment evidence must distinguish H0 and H1")
    deployments = {
        name: _check_deployment(root, deployment_specs[name], target, name)
        for name in ("h0", "h1")
    }

    cases = _object(manifest.get("cases"), "cases")
    _require(set(cases) == {"h0", "h1"}, "manifest must contain exactly H0 and H1")
    paths = {name: _artifact_map(root, _object(cases[name], name), name) for name in ("h0", "h1")}
    requirement_bytes = {name: _read(paths[name]["requirement"], name + " Requirement") for name in paths}
    _require(requirement_bytes["h0"] == requirement_bytes["h1"], "H0/H1 target Requirement bytes differ")
    _require(sha256(requirement_bytes["h0"]).hexdigest() == target["requirement_sha256"], "target Requirement hash differs")
    requirement = _target_requirement(_loads(requirement_bytes["h0"], "target Requirement"))

    cuts = {
        name: _check_cut(
            paths[name]["restate_cut"],
            paths[name]["restate_status_raw"],
            paths[name]["restate_journal_raw"],
            order,
            name,
        )
        for name in ("h0", "h1")
    }
    _require(
        all(cuts[name]["deployment_id"] == deployments[name]["v1"]["deployment_id"] for name in ("h0", "h1")),
        "H0/H1 cut was not pinned to the registered v1 deployment",
    )
    _require(_cut_projection(cuts["h0"]) == _cut_projection(cuts["h1"]), "H0/H1 Restate journal or visible workflow state differs")

    resolved_runtime = Path(runtime_dir).resolve() if runtime_dir is not None else Path(__file__).resolve().parents[2]
    if fresh_certificates:
        _require((resolved_runtime / "go.mod").is_file(), "runtime source for fresh Certificate checks is absent")
    checked = {
        name: _check_case(
            root,
            name,
            paths[name],
            str(domain),
            order,
            target,
            requirement,
            cuts[name],
            resolved_runtime,
            fresh_certificates,
        )
        for name in ("h0", "h1")
    }
    _require(
        checked["h0"]["events"] == checked["h1"]["events"][: len(checked["h0"]["events"])],
        "H0/H1 runtime History differs before authoritative payment observation",
    )
    payment_core = {
        key: value
        for key, value in checked["h0"]["payment"].items()
        if key not in {"phase"}
    }
    _require(
        payment_core
        == {key: value for key, value in checked["h1"]["payment"].items() if key != "phase"},
        "H0/H1 frozen payment Operation differs",
    )
    return {
        "valid": True,
        "experiment": EXPERIMENT,
        "journal_equal": True,
        "target_program_sha256": target["program_sha256"],
        "h0_decision": "impossible",
        "h1_decision": "activate",
        "h0_payment_commits": checked["h0"]["payment_commits"],
        "h1_payment_commits": checked["h1"]["payment_commits"],
        "h1_completion_commits": checked["h1"]["completion_commits"],
        "h1_payment_dispatches": checked["h1"]["payment_dispatches"],
        "v1_fenced": True,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--runtime-dir", type=Path, default=Path(__file__).resolve().parents[2])
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        verdict = check_evidence(args.evidence, runtime_dir=args.runtime_dir)
    except (EvidenceError, OSError, subprocess.SubprocessError) as error:
        print(json.dumps({"valid": False, "error": str(error)}, sort_keys=True))
        return 1
    print(json.dumps(verdict, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
