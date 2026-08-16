"""Offline checker for the Firecracker + real Codex + MCP continuity run."""

from __future__ import annotations

import argparse
import base64
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import struct
from typing import Any

from adapter.check_codex_mcp_evidence import (
    EvidenceError,
    _decode,
    _journal,
    _mcp_items,
    _outcome,
    _private_root,
    _sha,
)


_EXECUTION_ID = "codex-mcp-execution-v1"
_SANDBOX_ID = "codex-mcp"
_DOMAIN = "firecracker-codex-mcp-runtime"
_EFFECTS = ("effect-A", "effect-B")
_ZERO_HASH = "0" * 64


def _canonical(value: Any, *, newline: bool = False) -> bytes:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return encoded + (b"\n" if newline else b"")


def _private_subdirectory(root: Path, name: str) -> Path:
    path = root / name
    info = path.lstat()
    if (
        path.resolve(strict=True) != path
        or not stat.S_ISDIR(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise EvidenceError(f"unsafe evidence directory {name}")
    return path


def _private_file(path: Path, label: str, *, require_mode: int = 0o600) -> bytes:
    try:
        info = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise EvidenceError(f"cannot inspect {label}") from error
    if (
        not path.is_absolute()
        or resolved != path
        or not stat.S_ISREG(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != require_mode
        or info.st_size <= 0
        or info.st_size > 64 << 20
    ):
        raise EvidenceError(f"unsafe evidence file {label}")
    return path.read_bytes()


def _json_path(path: Path, label: str, *, canonical: bool = False) -> Any:
    data = _private_file(path, label)
    value = _decode(data, label)
    if canonical and data != _canonical(value, newline=True):
        raise EvidenceError(f"{label} is not canonical JSON")
    return value


def _json_lines_path(path: Path, label: str) -> list[dict[str, Any]]:
    data = _private_file(path, label)
    if not data.endswith(b"\n"):
        raise EvidenceError(f"{label} lacks a final record delimiter")
    records: list[dict[str, Any]] = []
    for index, line in enumerate(data.splitlines(), start=1):
        value = _decode(line, f"{label}:{index}")
        if not isinstance(value, dict):
            raise EvidenceError(f"{label}:{index} is not an object")
        records.append(value)
    if not records:
        raise EvidenceError(f"{label} is empty")
    return records


def _valid_digest(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64 or value.lower() != value:
        return False
    try:
        return len(bytes.fromhex(value)) == 32
    except ValueError:
        return False


def _artifact(record: Any, label: str, *, executable: bool) -> Path:
    if not isinstance(record, dict) or set(record) != {"mode", "path", "sha256", "size"}:
        raise EvidenceError(f"{label} artifact identity is malformed")
    value = record.get("path")
    if not isinstance(value, str):
        raise EvidenceError(f"{label} artifact path is absent")
    path = Path(value)
    try:
        info = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise EvidenceError(f"cannot inspect {label} artifact") from error
    mode = stat.S_IMODE(info.st_mode)
    if (
        not path.is_absolute()
        or resolved != path
        or not stat.S_ISREG(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or info.st_uid != os.geteuid()
        or mode & 0o022
        or (executable and mode & 0o111 == 0)
        or record.get("mode") != mode
        or record.get("size") != info.st_size
        or not _valid_digest(record.get("sha256"))
        or record.get("sha256") != _sha(path)
    ):
        raise EvidenceError(f"unsafe or changed {label} artifact")
    return path


def _history(root: Path) -> list[dict[str, Any]]:
    data = _private_file(root / "control.history", "Control History")
    records: list[dict[str, Any]] = []
    offset = 0
    previous = _ZERO_HASH
    while offset < len(data):
        if len(data) - offset < 12 or data[offset : offset + 4] != b"HST1":
            raise EvidenceError("History frame header is malformed")
        length = struct.unpack(">Q", data[offset + 4 : offset + 12])[0]
        offset += 12
        if length == 0 or length > 16 << 20 or offset + length > len(data):
            raise EvidenceError("History frame length is invalid")
        raw = data[offset : offset + length]
        offset += length
        record = _decode(raw, f"History:{len(records) + 1}")
        if not isinstance(record, dict) or set(record) != {
            "version",
            "sequence",
            "operation",
            "data",
            "previous_hash",
            "hash",
        }:
            raise EvidenceError("History event shape is malformed")
        if json.dumps(record, separators=(",", ":"), ensure_ascii=True).encode() != raw:
            raise EvidenceError("History event is not canonical JSON")
        sequence = len(records) + 1
        operation = record.get("operation")
        data_bytes = json.dumps(
            record.get("data"), separators=(",", ":"), ensure_ascii=True
        ).encode()
        digest = sha256(b"history-event-v1\x00" + struct.pack(">Q", sequence))
        for part in (previous.encode(), str(operation).encode(), data_bytes):
            digest.update(struct.pack(">Q", len(part)))
            digest.update(part)
        if (
            record.get("version") != 1
            or record.get("sequence") != sequence
            or not isinstance(operation, str)
            or not operation
            or record.get("previous_hash") != previous
            or record.get("hash") != digest.hexdigest()
        ):
            raise EvidenceError(f"History event {sequence} fails its hash chain")
        previous = digest.hexdigest()
        records.append(record)
    if len(records) != 8:
        raise EvidenceError("History does not contain the exact two-Operation lifecycle")
    return records


def _check_anchor(root: Path, history: list[dict[str, Any]]) -> None:
    anchor = _json_path(root / "control.head-anchor", "History head anchor")
    if not isinstance(anchor, dict) or set(anchor) != {
        "version",
        "sequence",
        "hash",
        "checksum",
    }:
        raise EvidenceError("History head anchor is malformed")
    raw = _private_file(root / "control.head-anchor", "History head anchor")
    if raw != json.dumps(anchor, separators=(",", ":"), ensure_ascii=True).encode() + b"\n":
        raise EvidenceError("History head anchor is not canonical")
    last = history[-1]
    digest = sha256(
        b"history-head-anchor-v1\x00"
        + struct.pack(">Q", last["sequence"])
        + last["hash"].encode()
    ).hexdigest()
    if anchor != {
        "version": 1,
        "sequence": last["sequence"],
        "hash": last["hash"],
        "checksum": digest,
    }:
        raise EvidenceError("History head anchor does not bind the durable head")


def _operation_id(call_id: str) -> str:
    digest = sha256(
        b"sandbox-operation-id-v2\x00"
        + _DOMAIN.encode()
        + b"\x00"
        + _SANDBOX_ID.encode()
        + b"\x00"
        + call_id.encode()
    ).hexdigest()
    return "op-" + digest


def _protected_digest(effect: str) -> str:
    request = json.dumps(
        {
            "schema": 1,
            "name": "commit_effect",
            "kind": "protected_commit",
            "arguments": {"effect_id": effect},
        },
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode()
    return sha256(b"mcp-protected-call-v2\x00" + request).hexdigest()


def _decode_body(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, str):
        raise EvidenceError(f"{label} is absent")
    try:
        decoded = base64.b64decode(value, validate=True)
    except ValueError as error:
        raise EvidenceError(f"{label} is not canonical base64") from error
    result = _decode(decoded, label)
    if not isinstance(result, dict):
        raise EvidenceError(f"{label} is not an object")
    return result


def _check_history_and_payment(
    root: Path,
    history: list[dict[str, Any]],
    journal: list[dict[str, Any]],
    outcomes: tuple[dict[str, Any], dict[str, Any]],
) -> list[str]:
    expected_operations = [
        "rule.bindings.cutover",
        "operation.prepared",
        "operation.phase",
        "operation.phase",
        "operation.phase",
        "operation.prepared",
        "operation.phase",
        "operation.phase",
    ]
    if [record["operation"] for record in history] != expected_operations:
        raise EvidenceError("History Operation lifecycle order is wrong")
    cutover = history[0]["data"]
    requirement = cutover.get("certificate", {}).get("requirement", {}) if isinstance(cutover, dict) else {}
    if (
        requirement.get("results") != {"committed": 2}
        or requirement.get("capacities") != {"external-write": 2}
        or set(requirement.get("kinds", {})) != {"protected_commit"}
    ):
        raise EvidenceError("History Cutover does not authorize exactly two protected commits")

    prepared_events = (history[1], history[5])
    phase_groups = ((history[2], history[3], history[4]), (history[6], history[7]))
    operation_ids: list[str] = []
    for index, (effect, prepared_event, phases, outcome) in enumerate(
        zip(_EFFECTS, prepared_events, phase_groups, outcomes, strict=True)
    ):
        data = prepared_event["data"]
        operation = data.get("operation") if isinstance(data, dict) else None
        expected_id = _operation_id(journal[index * 2]["call_id"])
        if (
            not isinstance(operation, dict)
            or data.get("semantic_version") != 1
            or operation.get("id") != expected_id
            or operation.get("domain") != _DOMAIN
            or operation.get("sandbox_id") != _SANDBOX_ID
            or operation.get("kind") != "protected_commit"
            or operation.get("phase") != "prepared"
            or operation.get("queryable") is not True
            or operation.get("retry_safe") is not False
            or _decode_body(operation.get("request_body"), "Operation request")
            != {"effect_id": effect}
        ):
            raise EvidenceError(f"History prepared Operation for {effect} is malformed")
        expected_phases = ["dispatched", "unknown", "succeeded"] if index == 0 else ["dispatched", "succeeded"]
        updates: list[dict[str, Any]] = []
        for phase_event, expected_phase in zip(phases, expected_phases, strict=True):
            phase_data = phase_event["data"]
            update = phase_data.get("update") if isinstance(phase_data, dict) else None
            if (
                not isinstance(update, dict)
                or phase_data.get("semantic_version") != 1
                or phase_data.get("id") != expected_id
                or update.get("phase") != expected_phase
            ):
                raise EvidenceError(f"History phase for {effect} is malformed")
            updates.append(update)
        succeeded = updates[-1]
        if (
            succeeded.get("result_hash") != outcome.get("result_hash")
            or succeeded.get("remote_reference") != f"firecracker-mcp/{expected_id}/commit-1"
            or (index == 0 and succeeded.get("settlement") != "query")
            or (index == 1 and "settlement" in succeeded)
        ):
            raise EvidenceError(f"History outcome for {effect} differs from MCP")
        result_body = _decode_body(succeeded.get("result_body"), "History result")
        if index == 0:
            if (
                result_body.get("operation_id") != expected_id
                or result_body.get("outcome") != "succeeded"
                or result_body.get("fact_hash") != outcome.get("result_hash")
            ):
                raise EvidenceError("History query recovery result is malformed")
        elif (
            result_body.get("operation_id") != expected_id
            or result_body.get("outcome") != "succeeded"
            or result_body.get("result_hash") != outcome.get("result_hash")
        ):
            raise EvidenceError("History direct result is malformed")
        operation_ids.append(expected_id)

    payments = _json_lines_path(root / "payment.history", "payment history")
    if len(payments) != 2:
        raise EvidenceError("payment history does not contain exactly two commits")
    for effect, operation_id, outcome, payment in zip(
        _EFFECTS, operation_ids, outcomes, payments, strict=True
    ):
        body = _canonical({"effect_id": effect})
        request_hash = sha256(b"POST\x00/v1/charge\x00" + body).hexdigest()
        result_hash = sha256(
            b"charged\x00" + operation_id.encode() + b"\x001"
        ).hexdigest()
        expected = {
            "operation_id": operation_id,
            "request_hash": request_hash,
            "result_hash": result_hash,
            "remote_reference": f"firecracker-mcp/{operation_id}/commit-1",
            "path": "/v1/charge",
        }
        if payment != expected or outcome.get("result_hash") != result_hash:
            raise EvidenceError(f"provider commit for {effect} differs from History")
    return operation_ids


def check(path: Path, payload_result_path: Path) -> dict[str, Any]:
    root = _private_root(path)
    adapter_dir = _private_subdirectory(root, "adapter")
    runtime_dir = _private_subdirectory(root, "runtime")
    result = _json_path(root / "result.json", "combined result", canonical=True)
    if (
        not isinstance(result, dict)
        or result.get("schema") != 1
        or result.get("valid") is not True
        or result.get("runtime_evidence") != os.fspath(runtime_dir)
        or result.get("adapter_evidence") != os.fspath(adapter_dir)
        or result.get("firecracker_result") != os.fspath(adapter_dir / "result.json")
        or result.get("history") != os.fspath(root / "control.history")
        or result.get("journal") != os.fspath(root / "mcp-calls.jsonl")
        or result.get("payment_history") != os.fspath(root / "payment.history")
        or result.get("mcp_relay_lifetimes") != 3
        or result.get("provider_deliveries") != 2
        or result.get("provider_commits") != 2
    ):
        raise EvidenceError("combined result is not bound to this successful evidence root")

    artifacts = result.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != {
        "control",
        "payment",
        "mcp_host",
        "mcp_relay",
        "tools_config",
    }:
        raise EvidenceError("combined result omits trusted artifact identities")
    trusted = {
        name: _artifact(record, name, executable=name != "tools_config")
        for name, record in artifacts.items()
    }

    adapter = _json_path(adapter_dir / "result.json", "adapter result", canonical=True)
    if (
        not isinstance(adapter, dict)
        or adapter.get("schema") != 1
        or adapter.get("ok") is not True
        or adapter.get("result_path") != os.fspath(adapter_dir / "result.json")
        or adapter.get("independent_evidence_check") != "required"
        or adapter.get("mcp")
        != {
            "effect_ids": ["effect-A", "effect-B"],
            "guest_port": 7002,
            "guest_relay": "/opt/codex/bin/mcp-operation-relay",
        }
    ):
        raise EvidenceError("adapter result does not describe the checked MCP run")
    adapter_artifacts = adapter.get("artifacts")
    relay_summary = adapter_artifacts.get("mcp_relay") if isinstance(adapter_artifacts, dict) else None
    if (
        not isinstance(relay_summary, dict)
        or relay_summary.get("path") != os.fspath(trusted["mcp_relay"])
        or relay_summary.get("sha256") != artifacts["mcp_relay"]["sha256"]
        or relay_summary.get("size") != artifacts["mcp_relay"]["size"]
    ):
        raise EvidenceError("adapter and host disagree on the MCP relay identity")

    payload_result_path = payload_result_path.resolve(strict=True)
    payload_result = _decode(payload_result_path.read_bytes(), "payload result")
    payload = payload_result.get("payload") if isinstance(payload_result, dict) else None
    manifest = payload.get("manifest") if isinstance(payload, dict) else None
    entries = manifest.get("entries") if isinstance(manifest, dict) else None
    relay_entries = [
        entry
        for entry in entries or []
        if isinstance(entry, dict) and entry.get("path") == "bin/mcp-operation-relay"
    ]
    adapter_payload = adapter_artifacts.get("payload") if isinstance(adapter_artifacts, dict) else None
    if (
        len(relay_entries) != 1
        or relay_entries[0].get("sha256") != artifacts["mcp_relay"]["sha256"]
        or relay_entries[0].get("size") != artifacts["mcp_relay"]["size"]
        or not isinstance(adapter_payload, dict)
        or payload.get("image_sha256") != adapter_payload.get("sha256")
        or payload.get("image_size") != adapter_payload.get("size")
    ):
        raise EvidenceError("payload image is not bound to the trusted host relay")

    host_process = _json_path(root / "mcp-host-process.json", "MCP host process", canonical=True)
    host_pid = host_process.get("pid") if isinstance(host_process, dict) else None
    sandbox_name = "sandbox-" + sha256(_SANDBOX_ID.encode()).hexdigest()[:32] + ".sock"
    expected_command = [
        os.fspath(trusted["mcp_host"]),
        "-config",
        os.fspath(trusted["tools_config"]),
        "-sandbox-socket",
        os.fspath(root / "sockets" / sandbox_name),
        "-listen-socket",
        os.fspath(root / "relay" / "mcp-host.sock"),
        "-execution-id",
        _EXECUTION_ID,
        "-journal",
        os.fspath(root / "mcp-calls.jsonl"),
    ]
    if not isinstance(host_pid, int) or host_pid <= 1 or host_process.get("command") != expected_command:
        raise EvidenceError("trusted MCP host command is malformed")
    host_events = _json_lines_path(root / "mcp-host.stderr.log", "MCP host log")
    peer_pids = {event.get("pid") for event in host_events}
    if (
        len(host_events) != 6
        or [event.get("event") for event in host_events].count("relay_accept") != 3
        or [event.get("event") for event in host_events].count("relay_disconnect") != 3
        or len(peer_pids) != 1
        or host_pid in peer_pids
        or any(event.get("uid") != os.geteuid() for event in host_events)
    ):
        raise EvidenceError("trusted MCP host did not retain three bounded relay lifetimes")
    peer_pid = next(iter(peer_pids))
    if not isinstance(peer_pid, int) or peer_pid <= 1:
        raise EvidenceError("trusted MCP relay peer identity is malformed")
    for generation in ("g1", "g3"):
        relay_records = _json_lines_path(
            runtime_dir / f"firecracker-relay-{generation}.jsonl",
            f"Firecracker relay {generation}",
        )
        model_peers = {
            record.get("sandbox_peer_pid")
            for record in relay_records
            if record.get("event") == "bytes" and record.get("port") != 7002
        }
        mcp_peers = {
            record.get("sandbox_peer_pid")
            for record in relay_records
            if record.get("event") == "bytes" and record.get("port") == 7002
        }
        if model_peers != {peer_pid} or mcp_peers != {host_pid}:
            raise EvidenceError("Firecracker relay identities do not join the trusted MCP host")

    app_path = adapter_dir / "app-server.jsonl"
    app_summary = adapter.get("adapter", {}).get("app_server_jsonl")
    if (
        not isinstance(app_summary, dict)
        or app_summary.get("path") != os.fspath(app_path)
        or app_summary.get("sha256") != _sha(app_path)
        or app_summary.get("size") != app_path.stat().st_size
    ):
        raise EvidenceError("adapter raw log fingerprint is wrong")
    app_records = _json_lines_path(app_path, "App Server log")
    items, versions = _mcp_items(app_records)
    if len(items) != 3 or not versions:
        raise EvidenceError("App Server log lacks the A, replay-A, B MCP completions")
    first_a = _outcome(items[0], "effect-A")
    replay_a = _outcome(items[1], "effect-A")
    second_b = _outcome(items[2], "effect-B")
    if (
        first_a != replay_a
        or first_a.get("recovered_by_query") is not True
        or second_b.get("recovered_by_query") is not False
        or first_a.get("operation_id") == second_b.get("operation_id")
    ):
        raise EvidenceError("restored Codex did not replay A exactly before advancing to B")

    journal = _journal(root, _EXECUTION_ID)
    outcomes = (first_a, second_b)
    for index, (effect, prepared, completed, outcome) in enumerate(
        zip(_EFFECTS, journal[::2], journal[1::2], outcomes, strict=True), start=2
    ):
        if prepared.get("request_digest") != _protected_digest(effect):
            raise EvidenceError(f"journal request for {effect} is not semantically bound")
        response = _decode(
            base64.b64decode(completed["response"], validate=True),
            f"journal response for {effect}",
        )
        structured = response.get("result", {}).get("structuredContent") if isinstance(response, dict) else None
        if response.get("jsonrpc") != "2.0" or response.get("id") != index or structured != outcome:
            raise EvidenceError(f"journal result for {effect} differs from Codex")

    history = _history(root)
    _check_anchor(root, history)
    operation_ids = _check_history_and_payment(root, history, journal, outcomes)
    if result.get("operations") != sorted(operation_ids):
        raise EvidenceError("combined result names different durable Operations")

    return {
        "schema": 1,
        "valid": True,
        "containment": "firecracker",
        "codex_version": versions[-1],
        "vmm_generations": 2,
        "mcp_relay_lifetimes": 3,
        "mcp_completions": 3,
        "operations": 2,
        "provider_commits": 2,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    parser.add_argument("payload_result", type=Path)
    args = parser.parse_args()
    try:
        result = check(args.evidence, args.payload_result)
    except Exception as error:
        print(json.dumps({"schema": 1, "valid": False, "error": str(error)}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["EvidenceError", "check", "main"]
