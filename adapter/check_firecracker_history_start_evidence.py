#!/usr/bin/env python3
"""Independently validate History-authorized Firecracker start evidence.

This module imports no experiment producer. It reconstructs History chains,
reruns Certificate verification, and joins Firecracker API traces with process,
guest, model, application, and Mongo evidence.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
import struct
import subprocess
import sys
from typing import Any, Mapping, Sequence


FIRECRACKER_SHA256 = "2fd0171309af7e24cf8dafc8a6f921c1434c49b5f9349bb996b7ed0a4deb8aa7"
KERNEL_SHA256 = "e20e46d0c36c55c0d1014eb20576171b3f3d922260d9f792017aeff53af3d4f2"
CLAUDE_SHA256 = "55d281096f57d411ebbdd94dbf5e9ff3accb7c05713e37348c2c11d4b83bf9d9"
DEATHSTAR_COMMIT = "6ecb09706140f8730b5385c08f1386c654c3c526"
HEX32 = re.compile(r"[0-9a-f]{32}")
HEX64 = re.compile(r"[0-9a-f]{64}")
BODY = {
    "hotel_id": "1",
    "in_date": "2015-04-09",
    "out_date": "2015-04-10",
    "rooms": 1,
    "username": "Cornell_30",
    "password": "0000000000",
}


class EvidenceError(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceError(message)


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        _require(key not in value, f"JSON repeats field {key!r}")
        value[key] = item
    return value


def _loads(data: bytes | str, label: str) -> Any:
    try:
        return json.loads(data, object_pairs_hook=_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvidenceError(f"{label} is not valid JSON") from error


def _json(path: Path, label: str) -> Any:
    try:
        return _loads(path.read_bytes(), f"{label}: {path}")
    except OSError as error:
        raise EvidenceError(f"cannot read {label}: {path}") from error


def _object(value: Any, label: str) -> dict[str, Any]:
    _require(isinstance(value, dict), f"{label} is not an object")
    return value


def _array(value: Any, label: str) -> list[Any]:
    _require(isinstance(value, list), f"{label} is not an array")
    return value


def _jsonl(path: Path, label: str) -> list[dict[str, Any]]:
    try:
        lines = path.read_bytes().splitlines()
    except OSError as error:
        raise EvidenceError(f"cannot read {label}: {path}") from error
    result: list[dict[str, Any]] = []
    for ordinal, line in enumerate(lines, 1):
        value = _loads(line, f"{label} line {ordinal}")
        _require(isinstance(value, dict), f"{label} line {ordinal} is not an object")
        result.append(value)
    return result


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _go_canonical(value: Any) -> bytes:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()


def _sha_file(path: Path) -> str:
    digest = sha256()
    try:
        with path.open("rb") as source:
            while block := source.read(1 << 20):
                digest.update(block)
    except OSError as error:
        raise EvidenceError(f"cannot hash {path}") from error
    return digest.hexdigest()


def _direct(path: Path, label: str, *, private: bool = False) -> os.stat_result:
    try:
        info = path.lstat()
    except OSError as error:
        raise EvidenceError(f"missing {label}: {path}") from error
    _require(stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode), f"{label} is not a direct file")
    if private:
        _require(stat.S_IMODE(info.st_mode) == 0o600, f"{label} is not mode 0600")
    return info


def _history(path: Path) -> list[dict[str, Any]]:
    _direct(path, "History", private=True)
    data = path.read_bytes()
    records: list[dict[str, Any]] = []
    offset = 0
    previous = "0" * 64
    while offset < len(data):
        _require(offset + 12 <= len(data) and data[offset : offset + 4] == b"HST1", "History frame header is malformed")
        length = struct.unpack(">Q", data[offset + 4 : offset + 12])[0]
        offset += 12
        end = offset + length
        _require(length > 0 and end <= len(data), "History frame length is malformed")
        payload = data[offset:end]
        record = _object(_loads(payload, "History frame"), "History frame")
        sequence = len(records) + 1
        _require(
            _go_canonical(record) == payload
            and record.get("version") == 1
            and record.get("sequence") == sequence
            and record.get("previous_hash") == previous,
            "History framing or links differ",
        )
        digest = sha256()
        digest.update(b"history-event-v1\0")
        digest.update(struct.pack(">Q", sequence))
        for part in (previous.encode(), str(record.get("operation", "")).encode(), _go_canonical(record.get("data"))):
            digest.update(struct.pack(">Q", len(part)))
            digest.update(part)
        _require(record.get("hash") == digest.hexdigest(), f"History event {sequence} hash is false")
        records.append(record)
        previous = record["hash"]
        offset = end
    _require(records, "History is empty")
    return records


def _head(path: Path, history: Sequence[Mapping[str, Any]]) -> None:
    anchor = _object(_json(path, "History head"), "History head")
    last = history[-1]
    digest = sha256()
    digest.update(b"history-head-anchor-v1\0")
    digest.update(struct.pack(">Q", int(last["sequence"])))
    digest.update(str(last["hash"]).encode())
    _require(
        anchor == {
            "version": 1,
            "sequence": last["sequence"],
            "hash": last["hash"],
            "checksum": digest.hexdigest(),
        },
        "History head anchor differs",
    )


def _replace(value: Any, replacements: Mapping[str, str]) -> Any:
    if isinstance(value, dict):
        return {key: _replace(item, replacements) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace(item, replacements) for item in value]
    if isinstance(value, str):
        for original, replacement in sorted(replacements.items(), key=lambda item: -len(item[0])):
            if original:
                value = value.replace(original, replacement)
    return value


def _normalized_unknown(history: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    _require(len(history) >= 4, "History lacks an unknown Operation")
    _require(
        [item.get("operation") for item in history[:4]]
        == ["rule.bindings.cutover", "operation.prepared", "operation.phase", "operation.phase"],
        "pre-recovery History operations differ",
    )
    operation = _object(_object(history[1].get("data"), "prepared data").get("operation"), "prepared Operation")
    replacements = {
        str(operation.get("id", "")): "<operation>",
        str(operation.get("request_hash", "")): "<request-hash>",
    }
    headers = operation.get("request_headers")
    if isinstance(headers, dict):
        for key in ("Idempotency-Key", "idempotency-key", "X-Operation-ID", "x-operation-id"):
            if isinstance(headers.get(key), str):
                replacements[headers[key]] = "<session>"
    first = history[0].get("data")
    if isinstance(first, dict):
        for binding in first.get("bindings", []):
            if isinstance(binding, dict) and isinstance(binding.get("host_instance_id"), str):
                replacements[binding["host_instance_id"]] = "<host-instance>"
    dispatched = history[2].get("data")
    if isinstance(dispatched, dict) and isinstance(dispatched.get("update"), dict):
        owner = dispatched["update"].get("dispatch_owner")
        if isinstance(owner, str):
            replacements[owner] = "<dispatch-owner>"
    return [
        {"operation": item.get("operation"), "data": _replace(item.get("data"), replacements)}
        for item in history[:4]
    ]


def _certificate(checker: Path, state: Path, certificate: Path, expected: str) -> dict[str, Any]:
    completed = subprocess.run(
        [os.fspath(checker), "-state", os.fspath(state), "-certificate", os.fspath(certificate)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=30,
    )
    _require(completed.returncode == 0, f"Certificate checker failed: {completed.stderr} {completed.stdout}")
    verdict = _object(_loads(completed.stdout, "Certificate verdict"), "Certificate verdict")
    _require(verdict.get("valid") is True and verdict.get("decision") == expected, f"Certificate is not {expected}")
    return verdict


def _api(path: Path, mode: str) -> list[dict[str, Any]]:
    records = _jsonl(path, "Firecracker API trace")
    paths = [item.get("path") for item in records]
    configured = ["/machine-config", "/boot-source", "/vsock", "/drives/payload"]
    if mode == "guarded-activate":
        _require(paths == configured + ["/", "/", "/", "/actions"], "guarded API order differs")
    elif mode == "guarded-denied":
        _require(paths == configured + ["/", "/"], "denied API order differs")
    elif mode == "baseline":
        _require(paths == configured + ["/actions"], "baseline API order differs")
    else:
        raise AssertionError(mode)
    starts = [item for item in records if item.get("method") == "PUT" and item.get("path") == "/actions"]
    expected_starts = 0 if mode == "guarded-denied" else 1
    _require(len(starts) == expected_starts, "Firecracker InstanceStart count differs")
    for item in starts:
        _require(item.get("request") == {"action_type": "InstanceStart"} and item.get("status") == 204, "InstanceStart call differs")
    states = [item for item in records if item.get("method") == "GET" and item.get("path") == "/"]
    _require(all(item.get("status") == 200 and item.get("response", {}).get("state") == "Not started" for item in states), "Firecracker state was not Not started")
    return records


def _machine(path: Path) -> dict[str, Any]:
    value = _object(_json(path, "machine configuration"), "machine configuration")
    _require(
        value.get("schema") == 1
        and value.get("machine") == {"vcpu_count": 1, "mem_size_mib": 1024, "smt": False, "track_dirty_pages": False}
        and value.get("tool_profile") == "http",
        "machine configuration differs",
    )
    normalized = json.loads(json.dumps(value))
    _object(normalized.get("vsock"), "vsock configuration")["uds_path"] = "<private-vsock-path>"
    return normalized


def _stream(result: Mapping[str, Any], operation_id: str, protected: bool, label: str) -> None:
    guest = _object(result.get("guest_result"), f"{label} guest result")
    body = _object(guest.get("body"), f"{label} guest body")
    stream = body.get("stream")
    _require(
        guest.get("event") == "RESULT"
        and guest.get("status") == 200
        and body.get("result") == "DONE"
        and isinstance(stream, str)
        and body.get("stream_bytes") == len(stream.encode())
        and body.get("stream_sha256") == sha256(stream.encode()).hexdigest(),
        f"{label} has no authenticated Claude result",
    )
    records = [_object(_loads(line, f"{label} Claude stream"), f"{label} Claude record") for line in stream.splitlines()]
    systems = [item for item in records if item.get("type") == "system" and item.get("subtype") == "init"]
    finals = [item for item in records if item.get("type") == "result"]
    uses = [
        block
        for item in records
        for block in item.get("message", {}).get("content", [])
        if isinstance(block, dict) and block.get("type") == "tool_use"
    ]
    tool_results = [
        block
        for item in records
        for block in item.get("message", {}).get("content", [])
        if isinstance(block, dict) and block.get("type") == "tool_result"
    ]
    _require(
        len(systems) == len(finals) == len(uses) == len(tool_results) == 1
        and systems[0].get("claude_code_version") == "2.1.233"
        and finals[0].get("subtype") == "success"
        and uses[0].get("name") == "Bash",
        f"{label} did not complete one official Claude Bash action",
    )
    command = uses[0].get("input", {}).get("command", "")
    _require(
        "$SAFE_CHANGE_EGRESS_URL" in command
        and "$SAFE_CHANGE_CALL_ID" in command
        and json.dumps(BODY, sort_keys=True, separators=(",", ":")) in command
        and "mcp__" not in stream,
        f"{label} did not use the fixed ordinary HTTP command",
    )
    response = _object(_loads(tool_results[0].get("content", ""), f"{label} tool response"), f"{label} tool response")
    _require(response.get("operation_id") == operation_id, f"{label} response Operation differs")
    if protected:
        _require(response.get("phase") == "succeeded" and response.get("recovered_by_query") is True, f"{label} did not reuse recovery")
    else:
        _require(response.get("outcome") == "succeeded", f"{label} baseline response failed")


def _cell(
    runtime: Path,
    wrapper: Mapping[str, Any],
    *,
    label: str,
    session: str,
    generation: int,
    mode: str,
    complete: bool,
    operation_id: str,
    expected_cell_sha: str,
    manifest: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    _require(
        wrapper.get("label") == label
        and wrapper.get("generation") == generation
        and wrapper.get("exit_code") == 0
        and Path(str(wrapper.get("evidence", ""))).name == label,
        f"{label} wrapper differs",
    )
    runner = _object(wrapper.get("runner"), f"{label} runner")
    retained_runner = _object(_json(runtime / f"{label}.runner-process.json", f"{label} runner record"), f"{label} runner record")
    _require(runner == retained_runner and runner.get("executable_sha256") == expected_cell_sha, f"{label} runner identity differs")
    directory = runtime / "cells" / label
    result = _object(_json(directory / "result.json", f"{label} result"), f"{label} result")
    _require(result == wrapper.get("result"), f"{label} embedded result differs")
    guarded = mode.startswith("guarded")
    decision = "impossible" if mode == "guarded-denied" else ("activate" if guarded else "baseline-unguarded")
    started = mode != "guarded-denied"
    _require(
        result.get("schema") == 1
        and result.get("valid") is True
        and result.get("backend") == "firecracker-kvm"
        and result.get("firecracker_version") == "1.16.1"
        and result.get("kernel_version") == "6.1.155"
        and result.get("generation") == generation
        and result.get("session_id") == session
        and result.get("tool_profile") == "http"
        and result.get("network_interfaces") == 0
        and result.get("root_block_devices") == 0
        and result.get("read_only_payload") is True
        and result.get("launch_guarded") is guarded
        and result.get("launch_decision") == decision
        and result.get("instance_started") is started,
        f"{label} cell contract differs",
    )
    process = _object(result.get("process"), f"{label} VMM process")
    _require(
        process.get("generation") == generation
        and process.get("executable_sha256") == FIRECRACKER_SHA256
        and type(process.get("pid")) is int
        and process["pid"] > 1
        and type(process.get("start_time_ticks")) is int
        and process["start_time_ticks"] > 0
        and process.get("started_time_ns", 0) < process.get("stopped_time_ns", 0)
        and process.get("termination") == "supervisor",
        f"{label} VMM identity differs",
    )
    artifacts = _object(result.get("artifacts"), f"{label} artifacts")
    _require(
        set(artifacts) == {"guest", "initramfs", "kernel", "payload"}
        and artifacts["kernel"].get("sha256") == KERNEL_SHA256
        and all(HEX64.fullmatch(str(item.get("sha256", ""))) for item in artifacts.values()),
        f"{label} artifacts differ",
    )
    _api(directory / "firecracker-api.jsonl", mode)
    machine = _machine(directory / "machine-config.json")
    config = _object(_json(directory / "guest-config.json", f"{label} guest config"), f"{label} guest config")
    _require(
        config.get("schema") == 2
        and config.get("profile") == "http"
        and config.get("session_id") == session
        and config.get("claude_sha256") == CLAUDE_SHA256,
        f"{label} guest configuration differs",
    )
    guard_path = directory / "launch-guard.json"
    if guarded:
        guard = _object(_json(guard_path, f"{label} launch guard"), f"{label} launch guard")
        _require(
            guard.get("guarded") is True
            and guard.get("decision") == decision
            and guard.get("certificate_decision") == decision
            and guard.get("certificate_digest") == manifest.get("certificate", {}).get("digest")
            and guard.get("binding") == manifest.get("binding")
            and guard.get("activated_history") == manifest.get("activated_history"),
            f"{label} guard is not bound to its manifest",
        )
        facts = _object(guard.get("runtime_facts"), f"{label} runtime facts")
        _require(
            facts.get("schema") == 1
            and facts.get("process", {}).get("pid") == process.get("pid")
            and facts.get("process", {}).get("executable_sha256") == FIRECRACKER_SHA256
            and facts.get("configuration_sha256")
            == sha256((directory / "machine-config.json").read_bytes().rstrip(b"\n")).hexdigest(),
            f"{label} runtime facts differ",
        )
        if started:
            _require(
                guard.get("authorization_issued") is True
                and guard.get("authorization_consumed") is True
                and guard.get("instance_start_issued") is True
                and len(guard.get("live_states", [])) == 2
                and len(guard.get("live_binding_views", [])) == 2
                and len(guard.get("runtime_state_reads", [])) == 2,
                f"{label} guarded start proof differs",
            )
        else:
            _require(
                guard.get("authorization_issued") is False
                and guard.get("instance_start_issued") is False
                and guard.get("live_states") == []
                and guard.get("live_binding_views") == []
                and guard.get("runtime_state_reads") == [],
                f"{label} denied start proof differs",
            )
    else:
        _require(not guard_path.exists(), f"{label} baseline contains protected guard evidence")
    relay = _jsonl(directory / "egress-relay.jsonl", f"{label} egress relay")
    if not started:
        _require(relay == [] and _jsonl(directory / "gate.jsonl", f"{label} gate") == [] and _jsonl(directory / "model-relay.jsonl", f"{label} model") == [], f"{label} denied guest emitted evidence")
        _require(result.get("disposition") == "launch-denied" and result.get("guest_result") is None, f"{label} denied result differs")
    else:
        byte_events = [item for item in relay if item.get("event") == "bytes"]
        _require(len(byte_events) == 1 and byte_events[0].get("guest_to_host_bytes", 0) > 0, f"{label} request did not leave the guest")
        if complete:
            _require(byte_events[0].get("host_to_guest_bytes", 0) > 0 and result.get("disposition") == "completed", f"{label} did not complete")
            _stream(result, operation_id, guarded, label)
        else:
            _require(byte_events[0].get("host_to_guest_bytes") == 0 and result.get("disposition") == "vmm-sigkill" and result.get("guest_result") is None, f"{label} did not lose the response")
    return result, machine


def _current_source_manifest(root: Path) -> dict[str, Any]:
    listed = subprocess.check_output(
        ["git", "-C", os.fspath(root), "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", "runtime", "adapter", "Makefile"]
    ).split(b"\0")
    files: list[dict[str, Any]] = []
    for encoded in sorted(item for item in listed if item):
        relative = encoded.decode()
        path = root / relative
        info = path.lstat()
        _require(stat.S_ISREG(info.st_mode), f"source path is not regular: {relative}")
        data = path.read_bytes()
        files.append({"path": relative, "mode": format(stat.S_IMODE(info.st_mode), "04o"), "size": len(data), "sha256": sha256(data).hexdigest()})
    return {"schema": 1, "files": files, "root_sha256": sha256(_canonical(files)).hexdigest()}


def check(evidence: Path, certificate_checker: Path, expected_repetitions: int | None = None) -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parent.parent
    retained_source = _object(_json(evidence / "source-manifest.json", "source manifest"), "source manifest")
    _require(retained_source == _current_source_manifest(repo_root), "retained source manifest differs from current source")
    outer = _object(_json(evidence / "result.json", "outer result"), "outer result")
    graph = _object(_json(evidence / "graph.json", "DeathStar graph"), "DeathStar graph")
    runtime = evidence / "runtime"
    result = _object(_json(runtime / "result.json", "runtime result"), "runtime result")
    driver = _object(_json(evidence / "driver-result.json", "driver result"), "driver result")
    _require(driver == result and outer.get("runtime") == result and outer.get("graph") == graph, "producer result copies differ")
    _require(
        outer.get("pass") is True
        and graph.get("pass") is True
        and graph.get("commit") == DEATHSTAR_COMMIT
        and graph.get("official_services") == 24
        and graph.get("source_modified") is False
        and graph.get("runtime_tree_hash") == retained_source.get("root_sha256"),
        "DeathStarBench or source provenance differs",
    )
    readiness = _object(_json(evidence / "reservation-readiness.json", "reservation readiness"), "reservation readiness")
    _require(
        readiness.get("schema") == 1
        and readiness.get("customer_name") == "step25-readiness"
        and readiness.get("response") == {"message": "Reserve successfully!"}
        and readiness.get("separately_identifiable_from_measured_operations") is True
        and readiness.get("shares_application_inventory") is True
        and type(readiness.get("observed_time_ns")) is int
        and readiness["observed_time_ns"] > 0,
        "DeathStar reservation dependency chain was not ready before measurement",
    )
    repetitions = result.get("repetitions")
    _require(type(repetitions) is int and 1 <= repetitions <= 5, "repetition count differs")
    if expected_repetitions is not None:
        _require(repetitions == expected_repetitions, "repetition count is not the requested count")
    _require(result.get("valid") is True and result.get("system") == "history-authorized-firecracker-instance-start", "runtime result contract differs")
    progress = _object(_json(runtime / "progress.json", "progress"), "progress")
    execution = _object(_json(evidence / "execution.json", "execution"), "execution")
    residual = _object(_json(evidence / "residual-processes.json", "residual check"), "residual check")
    _require(
        progress.get("status") == "complete"
        and execution.get("driver_exit_status") == 0
        and execution.get("timed_out") is False
        and residual.get("valid") is True
        and residual.get("checked_sessions") == repetitions * 6
        and residual.get("residual_before") == []
        and residual.get("terminated_pids") == [],
        "execution or process-reap evidence differs",
    )
    manifest = _object(_json(runtime / "run-manifest.json", "run manifest"), "run manifest")
    before = _object(_json(runtime / "requirement-v1.json", "initial Requirement"), "initial Requirement")
    target = _object(_json(runtime / "requirement-v2.json", "target Requirement"), "target Requirement")
    _require(
        manifest.get("requirement_v1_sha256") == sha256(_canonical(before)).hexdigest()
        and manifest.get("requirement_v2_sha256") == sha256(_canonical(target)).hexdigest()
        and before.get("results") == target.get("results") == {"reserved": 1, "finished": 1}
        and before.get("capacities") == target.get("capacities") == {"reservation": 1, "finish-slot": 1}
        and target.get("kinds", {}).get("reserve") == {"costs": {"reservation": 1}, "produces": {"reserved": 1}, "retry_safe": False, "queryable": False},
        "fixed Requirement pair differs",
    )
    artifacts = _object(result.get("artifacts"), "runtime artifacts")
    protected_sha = str(artifacts.get("protected_cell", ""))
    baseline_sha = str(artifacts.get("baseline_cell", ""))
    _require(HEX64.fullmatch(protected_sha) is not None and HEX64.fullmatch(baseline_sha) is not None and protected_sha != baseline_sha, "protected and baseline launchers are not distinct")
    _require(manifest.get("protected_cell_sha256") == protected_sha and manifest.get("baseline_cell_sha256") == baseline_sha, "launcher manifest hashes differ")
    protected = _array(result.get("protected"), "H1 runs")
    rejected = _array(result.get("rejected"), "H0 runs")
    baseline = _array(result.get("baseline"), "baseline runs")
    _require(len(protected) == len(rejected) == len(baseline) == repetitions, "comparison matrix is incomplete")
    audit = _jsonl(evidence / "deathstar-adapter.audit.jsonl", "DeathStar adapter audit")
    _require(len(audit) == repetitions * 3, "DeathStar delivery count differs")
    observer = _object(_json(runtime / "observer-facts.json", "Mongo observations"), "Mongo observations")
    observations = _array(observer.get("facts"), "Mongo facts")
    _require(observer.get("queries") == repetitions * 6 and len(observations) == repetitions * 6, "Mongo observation count differs")
    fences = sorted((evidence / "terminal-fences").glob("*.json"))
    _require(len(fences) == repetitions, "terminal fence count differs")
    identities: set[tuple[int, int, str]] = set()
    certificate_checks = 0
    for index in range(1, repetitions + 1):
        h1_item = _object(protected[index - 1], "H1 item")
        h0_item = _object(rejected[index - 1], "H0 item")
        baseline_item = _object(baseline[index - 1], "baseline item")
        for item, decision, rows, deliveries, completed in (
            (h1_item, "activate", 1, 1, True),
            (h0_item, "impossible", 0, 0, False),
            (baseline_item, "baseline-unguarded", 2, 2, True),
        ):
            _require(
                item.get("run") == index
                and HEX32.fullmatch(str(item.get("session", ""))) is not None
                and item.get("decision") == decision
                and item.get("mongo_rows") == rows
                and item.get("deliveries") == deliveries
                and item.get("task_completed") is completed,
                f"run {index} {decision} oracle differs",
            )
        h1_root = runtime / "runs" / f"run-{index}" / "h1"
        h0_root = runtime / "runs" / f"run-{index}" / "h0"
        h1_history = _history(h1_root / "control.history")
        h0_history = _history(h0_root / "control.history")
        _head(h1_root / "control.head", h1_history)
        _head(h0_root / "control.head", h0_history)
        _require(_normalized_unknown(h1_history) == _normalized_unknown(h0_history), "H1/H0 pre-recovery Histories differ")
        _require(
            len(h1_history) == 6
            and h1_history[4].get("data", {}).get("update", {}).get("phase") == "succeeded"
            and h1_history[5].get("operation") == "rule.bindings.cutover",
            "H1 recovery/cutover History differs",
        )
        _require(len(h0_history) == 5 and h0_history[4].get("data", {}).get("update", {}).get("phase") == "failed", "H0 recovery History differs")
        h1_certificate = _object(_json(h1_root / "target-certificate.json", "H1 Certificate"), "H1 Certificate")
        h0_certificate = _object(_json(h0_root / "target-certificate.json", "H0 Certificate"), "H0 Certificate")
        _require(h1_certificate.get("requirement") == h0_certificate.get("requirement") == target, "H1/H0 target bytes differ")
        _certificate(certificate_checker, h1_root / "target-certificate-state.json", h1_root / "target-certificate.json", "activate")
        _certificate(certificate_checker, h0_root / "target-certificate-state.json", h0_root / "target-certificate.json", "impossible")
        _certificate(certificate_checker, h1_root / "initial-certificate-state-g1.json", h1_root / "initial-certificate-g1.json", "activate")
        _certificate(certificate_checker, h0_root / "initial-certificate-state-g1.json", h0_root / "initial-certificate-g1.json", "activate")
        certificate_checks += 4
        h1_source_manifest = _object(_json(h1_root / "launch-g1.json", "H1 source manifest"), "H1 source manifest")
        h1_replacement_manifest = _object(_json(h1_root / "replacement-launch.json", "H1 replacement manifest"), "H1 replacement manifest")
        h0_source_manifest = _object(_json(h0_root / "launch-g1.json", "H0 source manifest"), "H0 source manifest")
        h0_replacement_manifest = _object(_json(h0_root / "replacement-launch.json", "H0 replacement manifest"), "H0 replacement manifest")
        h1_session = str(h1_item["session"])
        h0_session = str(h0_item["session"])
        baseline_session = str(baseline_item["session"])
        cells = [
            _cell(runtime, h1_item["source"], label=f"h1-{index}-source", session=h1_session, generation=1, mode="guarded-activate", complete=False, operation_id=str(h1_item["operation_id"]), expected_cell_sha=protected_sha, manifest=h1_source_manifest),
            _cell(runtime, h1_item["replacement"], label=f"h1-{index}-replacement", session=h1_session, generation=2, mode="guarded-activate", complete=True, operation_id=str(h1_item["operation_id"]), expected_cell_sha=protected_sha, manifest=h1_replacement_manifest),
            _cell(runtime, h0_item["source"], label=f"h0-{index}-source", session=h0_session, generation=1, mode="guarded-activate", complete=False, operation_id=str(h0_item["operation_id"]), expected_cell_sha=protected_sha, manifest=h0_source_manifest),
            _cell(runtime, h0_item["replacement"], label=f"h0-{index}-replacement", session=h0_session, generation=2, mode="guarded-denied", complete=False, operation_id=str(h0_item["operation_id"]), expected_cell_sha=protected_sha, manifest=h0_replacement_manifest),
            _cell(runtime, baseline_item["source"], label=f"baseline-{index}-source", session=baseline_session, generation=1, mode="baseline", complete=False, operation_id=str(baseline_item["operation_id"]), expected_cell_sha=baseline_sha, manifest={}),
            _cell(runtime, baseline_item["replacement"], label=f"baseline-{index}-replacement", session=baseline_session, generation=2, mode="baseline", complete=True, operation_id=str(baseline_item["operation_id"]), expected_cell_sha=baseline_sha, manifest={}),
        ]
        normalized_machines = [machine for _, machine in cells]
        _require(all(machine == normalized_machines[0] for machine in normalized_machines), "a lane changed the normalized Firecracker machine")
        for cell, _ in cells:
            process = cell["process"]
            identity = (process["pid"], process["start_time_ticks"], process["instance_id"])
            _require(identity not in identities, "two cells share one Firecracker identity")
            identities.add(identity)
        h1_audit = [item for item in audit if item.get("operation_id") == h1_item["operation_id"]]
        h0_audit = [item for item in audit if item.get("operation_id") == h0_item["operation_id"]]
        baseline_audit = [item for item in audit if item.get("operation_id") == baseline_item["operation_id"]]
        _require(len(h1_audit) == 1 and h0_audit == [] and len(baseline_audit) == 2, "application multiplicity differs from 1/0/2")
        matching_fence = evidence / "terminal-fences" / (sha256(str(h0_item["operation_id"]).encode()).hexdigest() + ".json")
        fence = _object(_json(matching_fence, "H0 terminal fence"), "H0 terminal fence")
        _require(
            fence == h0_item.get("terminal_fence")
            and fence.get("operation_id") == h0_item.get("operation_id")
            and fence.get("disposition") == "terminal-pre-upstream-abort",
            "H0 terminal fence differs",
        )
        h1_facts = [item for item in observations if item.get("operation_id") == h1_item["operation_id"]]
        h0_facts = [item for item in observations if item.get("operation_id") == h0_item["operation_id"]]
        baseline_facts = [item for item in observations if item.get("operation_id") == baseline_item["operation_id"]]
        _require(len(h1_facts) == len(h0_facts) == len(baseline_facts) == 2, "lane Mongo fact count differs")
        _require(all(item.get("count") == 1 for item in h1_facts), "H1 Mongo count differs")
        _require(all(item.get("count") == 0 and item.get("outcome") == "failed" for item in h0_facts), "H0 Mongo/fence fact differs")
        _require([item.get("count") for item in baseline_facts] == [1, 2], "baseline Mongo count did not progress 1 to 2")
    _require(result.get("model_requests", 0) > 0, "official Claude never reached the model")
    return {
        "schema": 1,
        "valid": True,
        "repetitions": repetitions,
        "certificate_checks": certificate_checks,
        "same_target": True,
        "matched_pre_recovery_history": True,
        "guarded_instance_start": True,
        "mongo_rows": {"h1": [1] * repetitions, "h0": [0] * repetitions, "baseline": [2] * repetitions},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--certificate-checker", required=True, type=Path)
    parser.add_argument("--expected-repetitions", type=int)
    args = parser.parse_args()
    try:
        verdict = check(
            args.evidence.resolve(strict=True),
            args.certificate_checker.resolve(strict=True),
            args.expected_repetitions,
        )
    except (EvidenceError, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(f"Firecracker History evidence invalid: {error}", file=sys.stderr)
        return 1
    print(json.dumps(verdict, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
