#!/usr/bin/env python3
"""Independently validate retained QEMU Agent Restore evidence."""

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


class EvidenceError(RuntimeError):
    pass


_CLAUDE_SHA256 = "55d281096f57d411ebbdd94dbf5e9ff3accb7c05713e37348c2c11d4b83bf9d9"
_UBUNTU_SHA256 = "d1940f7d69d343355e183dff1e08a59852d32e7309baa7a4bad8365b11b005ac"
_QEMU_SYSTEM_SHA256 = "8a35ccba41582fc6c38b9df85fc9e35fa1d42f414d2d7d8090ee9b2f5e7c0854"
_QEMU_IMG_SHA256 = "634320b91165669917123e8e79cce1c4d00cee0a4aa4d662d7c0a8186479b3fb"
_NETCAT_SHA256 = "2a6fac3d98e090468962ef18003cb8b89fbffa7219917ca12567d5e42b156948"
_QEMU_PACKAGE = "Debian 1:8.2.2+ds-0ubuntu1.18"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceError(message)


def _json(path: Path, label: str) -> Any:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as error:
        raise EvidenceError(f"{label} is not valid JSON: {path}") from error
    return value


def _object(value: Any, label: str) -> dict[str, Any]:
    _require(isinstance(value, dict), f"{label} is not an object")
    return value


def _array(value: Any, label: str) -> list[Any]:
    _require(isinstance(value, list), f"{label} is not an array")
    return value


def _jsonl(path: Path, label: str) -> list[dict[str, Any]]:
    try:
        values = [json.loads(line) for line in path.read_text().splitlines() if line]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvidenceError(f"{label} is not valid JSONL") from error
    _require(all(isinstance(item, dict) for item in values), f"{label} contains a non-object")
    return values


def _sha_file(path: Path) -> str:
    digest = sha256()
    try:
        with path.open("rb") as source:
            while chunk := source.read(1 << 20):
                digest.update(chunk)
    except OSError as error:
        raise EvidenceError(f"cannot hash {path}") from error
    return digest.hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _go_canonical(value: Any) -> bytes:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()


def _direct_file(path: Path, label: str, *, private: bool = False) -> os.stat_result:
    try:
        info = path.lstat()
    except OSError as error:
        raise EvidenceError(f"missing {label}: {path}") from error
    _require(stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode), f"{label} is not a direct regular file")
    if private:
        _require(stat.S_IMODE(info.st_mode) == 0o600, f"{label} is not mode 0600")
    return info


def _history(path: Path) -> list[dict[str, Any]]:
    _direct_file(path, "History", private=True)
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
        try:
            record = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise EvidenceError("History frame is not JSON") from error
        _require(isinstance(record, dict) and _go_canonical(record) == payload, "History frame is not canonical")
        sequence = len(records) + 1
        _require(
            record.get("version") == 1
            and record.get("sequence") == sequence
            and record.get("previous_hash") == previous
            and isinstance(record.get("operation"), str)
            and isinstance(record.get("data"), dict)
            and isinstance(record.get("hash"), str),
            "History sequence or links are inconsistent",
        )
        digest = sha256()
        digest.update(b"history-event-v1\0")
        digest.update(struct.pack(">Q", sequence))
        for part in (previous.encode(), record["operation"].encode(), _go_canonical(record["data"])):
            digest.update(struct.pack(">Q", len(part)))
            digest.update(part)
        _require(record["hash"] == digest.hexdigest(), f"History event {sequence} has a false hash")
        records.append(record)
        previous = record["hash"]
        offset = end
    _require(records, "History is empty")
    return records


def _head_anchor(path: Path, history: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    _direct_file(path, "History head anchor", private=True)
    anchor = _object(_json(path, "History head anchor"), "History head anchor")
    _require(set(anchor) == {"version", "sequence", "hash", "checksum"}, "History head anchor fields differ")
    last = history[-1]
    _require(
        anchor.get("version") == 1
        and anchor.get("sequence") == last.get("sequence")
        and anchor.get("hash") == last.get("hash"),
        "History head anchor does not name the retained head",
    )
    digest = sha256()
    digest.update(b"history-head-anchor-v1\0")
    digest.update(struct.pack(">Q", int(anchor["sequence"])))
    digest.update(str(anchor["hash"]).encode())
    _require(anchor.get("checksum") == digest.hexdigest(), "History head anchor checksum is false")
    return anchor


def _normalize_history_value(value: Any, replacements: Mapping[str, str]) -> Any:
    if isinstance(value, dict):
        return {key: _normalize_history_value(item, replacements) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_history_value(item, replacements) for item in value]
    if isinstance(value, str):
        normalized = value
        for original, replacement in sorted(replacements.items(), key=lambda item: -len(item[0])):
            if original:
                normalized = normalized.replace(original, replacement)
        return normalized
    return value


def _normalized_history_prefix(history: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    _require(len(history) >= 4, "History lacks the unknown-operation prefix")
    prepared = history[1]
    _require(prepared.get("operation") == "operation.prepared", "History event 2 is not operation.prepared")
    operation = _object(_object(prepared.get("data"), "prepared event data").get("operation"), "prepared Operation")
    replacements: dict[str, str] = {
        str(operation.get("id", "")): "<operation>",
        str(operation.get("request_hash", "")): "<request-hash>",
    }
    dispatched = history[2].get("data")
    if isinstance(dispatched, dict) and isinstance(dispatched.get("update"), dict):
        owner = dispatched["update"].get("dispatch_owner")
        if isinstance(owner, str):
            replacements[owner] = "<dispatch-owner>"
    headers = operation.get("request_headers")
    if isinstance(headers, dict):
        for name in ("Idempotency-Key", "idempotency-key", "X-Operation-ID", "x-operation-id"):
            if isinstance(headers.get(name), str):
                replacements[headers[name]] = "<session>"
    first_data = history[0].get("data")
    if isinstance(first_data, dict) and isinstance(first_data.get("bindings"), list):
        for binding in first_data["bindings"]:
            if isinstance(binding, dict) and isinstance(binding.get("host_instance_id"), str):
                replacements[binding["host_instance_id"]] = "<host-instance>"
    normalized: list[dict[str, Any]] = []
    for event in history[:4]:
        normalized.append(
            {
                "operation": event.get("operation"),
                "data": _normalize_history_value(event.get("data"), replacements),
            }
        )
    expected = ["rule.bindings.cutover", "operation.prepared", "operation.phase", "operation.phase"]
    _require([event["operation"] for event in normalized] == expected, "History operation sequence before recovery differs")
    _require(normalized[2]["data"].get("update", {}).get("phase") == "dispatched", "History lacks dispatched transition")
    _require(normalized[3]["data"].get("update", {}).get("phase") == "unknown", "History lacks unknown transition")
    return normalized


def _history_point(event: Mapping[str, Any]) -> dict[str, Any]:
    return {"sequence": event.get("sequence"), "hash": event.get("hash")}


def _join_history_evidence(
    history: Sequence[Mapping[str, Any]],
    unknown: Mapping[str, Any],
    checked: Mapping[str, Any],
    certificate: Mapping[str, Any],
    projection: Mapping[str, Any],
    current: Mapping[str, Any],
    manifest: Mapping[str, Any],
    decision: str,
) -> None:
    _require(len(history) >= 5, "raw History lacks recovery")
    _require(unknown.get("history") == _history_point(history[3]), "unknown State is not the exact raw History point")
    recovered_point = _history_point(history[4])
    _require(
        checked.get("history") == recovered_point
        and certificate.get("history") == recovered_point
        and projection.get("history") == recovered_point,
        "Certificate, checked State, and projection do not join the raw recovered History point",
    )
    _require(manifest.get("checked_state") == checked and manifest.get("certificate") == certificate, "resume manifest changed checked State or Certificate bytes")
    _require(current.get("history") == _history_point(history[-1]) == manifest.get("activated_history"), "current State/manifest do not join the raw activated History head")
    if decision == "activate":
        _require(len(history) == 6 and history[-1].get("operation") == "rule.bindings.cutover", "activate History lacks its exact target cutover")
        data = _object(history[-1].get("data"), "target cutover event")
        _require(data.get("certificate") == certificate and data.get("bindings") == [manifest.get("binding")], "target cutover event changed Certificate or binding bytes")
    else:
        _require(len(history) == 5 and current.get("history") == recovered_point, "impossible decision is not at the raw failed-recovery head")


def _terminal_fence(path: Path, operation_id: str, request_hash: str) -> dict[str, Any]:
    info = _direct_file(path, "terminal fence", private=True)
    _require(info.st_size > 0, "terminal fence is empty")
    expected_name = sha256(operation_id.encode()).hexdigest() + ".json"
    _require(path.name == expected_name, "terminal fence filename does not bind its Operation")
    fence = _object(_json(path, "terminal fence"), "terminal fence")
    _require(
        set(fence) == {"schema", "operation_id", "request_hash", "disposition", "fact_hash", "recorded_time_ns"},
        "terminal fence fields differ",
    )
    _require(
        fence.get("schema") == 1
        and fence.get("operation_id") == operation_id
        and fence.get("request_hash") == request_hash
        and fence.get("disposition") == "terminal-pre-upstream-abort"
        and type(fence.get("recorded_time_ns")) is int
        and fence["recorded_time_ns"] > 0,
        "terminal fence does not name the exact failed Operation",
    )
    fact = {
        "schema": 1,
        "operation_id": operation_id,
        "request_hash": request_hash,
        "disposition": "terminal-pre-upstream-abort",
    }
    _require(fence.get("fact_hash") == sha256(_go_canonical(fact)).hexdigest(), "terminal fence fact hash is false")
    return fence


def _current_source_manifest(root: Path) -> dict[str, Any]:
    listed = subprocess.check_output(
        ["git", "-C", os.fspath(root), "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", "runtime", "adapter", "Makefile"]
    ).split(b"\0")
    files: list[dict[str, Any]] = []
    for encoded in sorted(item for item in listed if item):
        relative = encoded.decode("utf-8")
        path = root / relative
        info = path.lstat()
        _require(stat.S_ISREG(info.st_mode), f"source path is not regular: {relative}")
        data = path.read_bytes()
        files.append({"path": relative, "mode": format(stat.S_IMODE(info.st_mode), "04o"), "size": len(data), "sha256": sha256(data).hexdigest()})
    return {"schema": 1, "files": files, "root_sha256": sha256(_canonical(files)).hexdigest()}


def _certificate(checker: Path, state: Path, certificate: Path, expected: str) -> dict[str, Any]:
    completed = subprocess.run(
        [os.fspath(checker), "-state", os.fspath(state), "-certificate", os.fspath(certificate)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=30,
    )
    _require(completed.returncode == 0, f"independent Certificate checker failed: {completed.stderr} {completed.stdout}")
    try:
        verdict = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise EvidenceError("Certificate checker output is malformed") from error
    _require(
        isinstance(verdict, dict)
        and verdict.get("valid") is True
        and verdict.get("decision") == expected,
        f"independent Certificate verdict is not {expected}: {verdict}",
    )
    return verdict


def _check_artifacts(artifacts: Mapping[str, Any], certificate_checker: Path) -> None:
    expected = {
        "qemu_runner": _sha_file(certificate_checker.parent / "vm-demo"),
        "claude": _CLAUDE_SHA256,
        "ubuntu_image": _UBUNTU_SHA256,
        "control": _sha_file(certificate_checker.parent / "control"),
        "effect_proxy": _sha_file(certificate_checker.parent / "effect-proxy"),
        "deathstar_adapter": _sha_file(certificate_checker.parent / "deathstar-adapter"),
    }
    _require(dict(artifacts) == expected, "executed Agent/runtime/Ubuntu artifacts differ from the pinned build and assets")


def _qmp_commands(path: Path) -> tuple[list[tuple[str, str]], list[tuple[str, bool]], list[tuple[str, int]]]:
    records = _jsonl(path, "QMP protocol")
    _require(records and records[0].get("direction") == "server_to_client", "QMP greeting is absent")
    greeting_payload = _object(records[0].get("payload"), "QMP greeting payload")
    greeting = _object(greeting_payload.get("QMP"), "QMP greeting")
    version = _object(greeting.get("version"), "QMP version")
    qemu_version = _object(version.get("qemu"), "QMP QEMU version")
    _require(
        qemu_version == {"major": 8, "minor": 2, "micro": 2}
        and version.get("package") == _QEMU_PACKAGE,
        "QMP greeting does not attest the pinned QEMU 8.2.2 package",
    )
    commands: list[tuple[str, str]] = []
    statuses: list[tuple[str, bool]] = []
    command_times: list[tuple[str, int]] = []
    pending: dict[str, str] = {}
    returned: set[str] = set()
    for record in records:
        payload = _object(record.get("payload"), "QMP payload")
        if record.get("direction") == "client_to_server":
            command = payload.get("execute")
            identity = payload.get("id")
            _require(isinstance(command, str) and isinstance(identity, str), "QMP command lacks identity")
            argument = ""
            if command == "human-monitor-command":
                arguments = _object(payload.get("arguments"), "QMP HMP arguments")
                argument = str(arguments.get("command-line", ""))
            commands.append((command, argument))
            _require(type(record.get("time_ns")) is int and record["time_ns"] > 0, "QMP command lacks time")
            command_times.append((command, record["time_ns"]))
            _require(identity not in pending, "QMP command identity repeats")
            pending[identity] = command
        elif record.get("direction") == "server_to_client" and isinstance(payload.get("id"), str):
            identity = payload["id"]
            _require(identity in pending and identity not in returned, "QMP response names an unknown command")
            _require("return" in payload and "error" not in payload, "QMP command failed")
            returned.add(identity)
            if pending[identity] == "query-status":
                status = _object(payload["return"], "QMP status result")
                _require(isinstance(status.get("status"), str), "QMP status name is absent")
                _require(type(status.get("running")) is bool, "QMP running flag is absent")
                statuses.append((status["status"], status["running"]))
    _require(set(pending) == returned, "QMP command lacks a successful response")
    return commands, statuses, command_times


def _check_qemu_phase(path: Path, kind: str) -> dict[str, Any]:
    result = _object(_json(path / "result.json", f"{kind} VM result"), f"{kind} VM result")
    _require(result.get("qemu_reaped") is True, f"{kind} QEMU was not reaped")
    command = _object(_json(path / "qemu-command.json", f"{kind} QEMU command"), "QEMU command")
    arguments = _array(command.get("arguments"), "QEMU arguments")
    joined = "\n".join(str(item) for item in arguments)
    _require("restrict=on" in joined and "-nic\nnone" in joined, f"{kind} QEMU network is not restricted")
    _require("10.0.2.100:8000" in joined and "10.0.2.100:9000" in joined and "10.0.2.100:8788" in joined, f"{kind} guest forwards differ")
    commands, statuses, command_times = _qmp_commands(path / "qmp-protocol.jsonl")
    if kind == "prepare":
        expected = [
            ("qmp_capabilities", ""),
            ("stop", ""),
            ("query-status", ""),
            ("human-monitor-command", "savevm before_agent"),
            ("quit", ""),
        ]
        expected_statuses = [("paused", False)]
        _require("-loadvm" not in arguments and "-S" not in arguments, "prepare QEMU unexpectedly loaded a snapshot")
    elif kind in {"source", "h1-restore", "native-restore"}:
        expected = [
            ("qmp_capabilities", ""),
            ("query-status", ""),
            ("cont", ""),
            ("stop", ""),
            ("query-status", ""),
            ("quit", ""),
        ]
        expected_statuses = [("prelaunch", False), ("paused", False)]
        _require("-S" in arguments and "-loadvm" in arguments and "before_agent" in arguments, f"{kind} did not start halted from the named snapshot")
    elif kind == "h0-restore":
        expected = [("qmp_capabilities", ""), ("query-status", ""), ("quit", "")]
        expected_statuses = [("prelaunch", False)]
        _require("-S" in arguments and "-loadvm" in arguments and "before_agent" in arguments, "H0 did not load the named halted snapshot")
    else:
        raise AssertionError(kind)
    _require(commands == expected, f"{kind} QMP commands differ: {commands}")
    _require(statuses == expected_statuses, f"{kind} QMP run states differ: {statuses}")
    if kind != "prepare":
        copy = _object(_json(path / "copy-verification.json", "lane copy verification"), "lane copy verification")
        _require(copy.get("verified_before_qemu_open") is True, f"{kind} lane copy was not preverified")
    serial = (path / "guest.serial.log").read_text(encoding="utf-8", errors="replace")
    if kind == "prepare":
        _require("SAFE_CHANGE_QEMU_AGENT_BASE_READY" in serial, "prepared guest lacks the official Claude ready marker")
        _require("claude_version=2.1.233" in serial, "prepared guest did not attest official Claude Code 2.1.233")
    else:
        _require("SAFE_CHANGE_QEMU_AGENT_CLAUDE_STARTED" in serial or kind == "h0-restore", f"{kind} never started official Claude")
        complete = "SAFE_CHANGE_QEMU_AGENT_COMPLETE" in serial
        _require(complete == (kind in {"h1-restore", "native-restore"}), f"{kind} completion marker is wrong")
    return {"result": result, "command": command, "command_times": command_times, "serial": serial}


def _normalized_unknown(path: Path) -> dict[str, Any]:
    state = _object(_json(path, "unknown State"), "unknown State")
    operations = _object(state.get("operations"), "unknown Operations")
    _require(len(operations) == 1, "unknown State does not contain exactly one Operation")
    operation = dict(next(iter(operations.values())))
    _require(operation.get("phase") == "unknown", "source Operation was not unknown before authoritative query")
    operation["id"] = "<operation>"
    operation["request_hash"] = "<request-hash>"
    operation["dispatch_owner"] = "<boot>"
    normalized = {
        "requirement": state.get("requirement"),
        "rule": state.get("rule"),
        "operation": operation,
    }
    return normalized


def _machine_config(path: Path) -> dict[str, Any]:
    machine = _object(_json(path / "machine-config.json", "machine configuration"), "machine configuration")
    _require(
        machine.get("schema") == 1
        and machine.get("machine") == "q35"
        and machine.get("memory_mib") == 2048
        and machine.get("cpus") == 2
        and machine.get("accelerator") == "kvm"
        and machine.get("disk") == "complete-qcow2"
        and machine.get("snapshot") == "before_agent"
        and machine.get("network") == "qemu-user-restrict-on",
        "machine configuration differs from the frozen KVM design",
    )
    _require(machine.get("claude_sha256") == _CLAUDE_SHA256, "machine configuration does not pin official Claude Code 2.1.233")
    _require(machine.get("base_image_sha256") == _UBUNTU_SHA256, "machine configuration does not pin the Ubuntu base image")
    forwards = _object(machine.get("guest_forwards"), "machine guest forwards")
    _require(set(forwards) == {"10.0.2.100:8000", "10.0.2.100:9000", "10.0.2.100:8788"}, "machine guest forwards differ")
    return machine


def _host_tools(path: Path) -> dict[str, Any]:
    manifest = _object(_json(path / "host-tools.json", "host tool manifest"), "host tool manifest")
    tools = _object(manifest.get("tools"), "host tools")
    expected = {
        "qemu-system-x86_64": (_QEMU_SYSTEM_SHA256, "QEMU emulator version 8.2.2"),
        "qemu-img": (_QEMU_IMG_SHA256, "qemu-img version 8.2.2"),
        "nc": (_NETCAT_SHA256, "OpenBSD netcat"),
    }
    _require(manifest.get("schema") == 1 and set(tools) == set(expected), "host tool manifest fields differ")
    for name, (digest, version) in expected.items():
        tool = _object(tools.get(name), f"host tool {name}")
        _require(
            set(tool) == {"path", "sha256", "version"}
            and isinstance(tool.get("path"), str)
            and str(tool["path"]).startswith("/")
            and tool.get("sha256") == digest
            and str(tool.get("version", "")).startswith(version),
            f"host tool {name} is not the pinned artifact",
        )
    return manifest


def _qemu_arguments(machine: Mapping[str, Any], host_tools: Mapping[str, Any], load_snapshot: bool) -> list[str]:
    tools = _object(host_tools.get("tools"), "host tools")
    netcat = _object(tools.get("nc"), "netcat host tool")
    netcat_path = netcat.get("path")
    _require(isinstance(netcat_path, str) and netcat_path.startswith("/"), "netcat host-tool path is not absolute")
    forwards = _object(machine.get("guest_forwards"), "machine guest forwards")

    def destination(guest: str) -> tuple[str, str]:
        host = forwards.get(guest)
        match = re.fullmatch(r"(127\.0\.0\.1):([1-9][0-9]{0,4})", str(host))
        _require(match is not None and int(match.group(2)) <= 65535, f"machine forward {guest} is invalid")
        return match.group(1), match.group(2)

    metadata_host, metadata_port = destination("10.0.2.100:8000")
    model_host, model_port = destination("10.0.2.100:9000")
    egress_host, egress_port = destination("10.0.2.100:8788")
    netdev = (
        "user,id=agentnet,restrict=on,"
        f"guestfwd=tcp:10.0.2.100:8000-cmd:{netcat_path} {metadata_host} {metadata_port},"
        f"guestfwd=tcp:10.0.2.100:9000-cmd:{netcat_path} {model_host} {model_port},"
        f"guestfwd=tcp:10.0.2.100:8788-cmd:{netcat_path} {egress_host} {egress_port}"
    )
    arguments = [
        "-name", "safe-change-full-agent-vm", "-machine", "q35", "-m", "2048", "-smp", "2",
        "-drive", "file=<host-sandbox-socket>,if=virtio,format=qcow2,cache=none",
        "-display", "none", "-serial", "file:<vm-evidence>/guest.serial.log", "-monitor", "none",
        "-qmp", "unix:<host-sandbox-socket>/qmp.sock,server=on,wait=off", "-no-reboot", "-nic", "none",
        "-netdev", netdev, "-device", "virtio-net-pci,netdev=agentnet",
        "-smbios", "type=1,serial=ds=nocloud;s=http://10.0.2.100:8000/",
    ]
    if load_snapshot:
        arguments.extend(["-S", "-loadvm", "before_agent"])
    arguments.extend(["-accel", "kvm"])
    return arguments


def _check_process_command(
    path: Path, machine: Mapping[str, Any], host_tools: Mapping[str, Any], load_snapshot: bool
) -> dict[str, Any]:
    declared = _object(_json(path / "qemu-command.json", "declared QEMU command"), "declared QEMU command")
    command = _object(_json(path / "qemu-process-command.json", "live QEMU command"), "live QEMU command")
    qemu_tool = _object(_object(host_tools.get("tools"), "host tools").get("qemu-system-x86_64"), "QEMU host tool")
    arguments = _qemu_arguments(machine, host_tools, load_snapshot)
    _require(
        declared == {"schema": 1, "executable": "qemu-system-x86_64", "arguments": arguments},
        "declared QEMU argv differs from the canonical machine configuration",
    )
    _require(
        set(command) == {
            "schema", "source", "pid", "executable", "executable_path", "executable_sha256", "command_sha256", "arguments"
        }
        and command.get("schema") == 1
        and command.get("source") == "linux-proc-cmdline-and-exe-fd"
        and command.get("executable") == "qemu-system-x86_64"
        and command.get("executable_path") == qemu_tool.get("path")
        and command.get("executable_sha256") == qemu_tool.get("sha256") == _QEMU_SYSTEM_SHA256
        and command.get("arguments") == arguments
        and re.fullmatch(r"[0-9a-f]{64}", str(command.get("command_sha256", ""))) is not None,
        "live QEMU process is not joined to the pinned binary and canonical argv",
    )
    return command


def _check_runner_process(path: Path, qemu_runner_sha256: str) -> dict[str, Any]:
    record_path = path.parent / f"{path.name}.runner-process-command.json"
    process = _object(_json(record_path, "VM runner process"), "VM runner process")
    _require(
        set(process) == {
            "schema", "kind", "pid", "process_group_id", "session_id", "start_time_ticks",
            "command_sha256", "executable_sha256",
        }
        and process.get("schema") == 1
        and process.get("kind") == "vm-demo-runner"
        and type(process.get("pid")) is int
        and process["pid"] > 1
        and process.get("process_group_id") == process["pid"]
        and process.get("session_id") == process["pid"]
        and type(process.get("start_time_ticks")) is int
        and process["start_time_ticks"] > 0
        and process.get("executable_sha256") == qemu_runner_sha256
        and re.fullmatch(r"[0-9a-f]{64}", str(process.get("command_sha256", ""))) is not None,
        "VM runner is not an independently killable instance of the pinned runner",
    )
    _require_reaped(process)
    return process


def _check_live_vm(
    path: Path, sealed_sha: str, machine: Mapping[str, Any], host_tools: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    live = _object(_json(path / "live-vm.json", "live VM identity"), "live VM identity")
    process = _object(live.get("process"), "live VM process")
    disk = _object(live.get("disk"), "live VM disk")
    command = _check_process_command(path, machine, host_tools, True)
    copy = _object(_json(path / "copy-verification.json", "lane copy verification"), "lane copy verification")
    _require(live.get("process_holds_disk") is True, "live QEMU did not hold the attested disk inode")
    _require(
        process.get("pid") == command.get("pid")
        and process.get("executable_sha256") == command.get("executable_sha256")
        and process.get("command_sha256") == command.get("command_sha256"),
        "live QEMU process identity differs from /proc argv evidence",
    )
    _require(
        disk.get("preopen_sha256") == sealed_sha == copy.get("sha256")
        and disk.get("size") == copy.get("size")
        and disk.get("device") == copy.get("device")
        and disk.get("inode") == copy.get("inode")
        and type(disk.get("device")) is int
        and type(disk.get("inode")) is int,
        "live QEMU disk identity differs from the pre-open verified lane copy",
    )
    return process, disk


def _require_reaped(process: Mapping[str, Any]) -> None:
    pid = process.get("pid")
    _require(type(pid) is int and pid > 1, "recorded QEMU PID is invalid")
    command_path = Path("/proc") / str(pid) / "cmdline"
    try:
        command = command_path.read_bytes()
    except FileNotFoundError:
        return
    except OSError as error:
        raise EvidenceError(f"cannot inspect residual QEMU PID {pid}") from error
    _require(sha256(command).hexdigest() != process.get("command_sha256"), f"recorded QEMU process {pid} is still live")


def _serial_tool_calls(serial: str, session: str, expected_calls: int, complete: bool) -> list[dict[str, Any]]:
    _require(f"SAFE_CHANGE_QEMU_AGENT_CLAUDE_STARTED session={session}" in serial or expected_calls == 0, "serial session marker differs")
    _require(f"SAFE_CHANGE_QEMU_AGENT_MODEL_READY session={session}" in serial or expected_calls == 0, "guest did not prove the Anthropic endpoint reachable")
    _require((f"SAFE_CHANGE_QEMU_AGENT_COMPLETE session={session}" in serial) is complete, "serial completion marker differs")
    values: list[dict[str, Any]] = []
    for line in serial.splitlines():
        if not line.startswith("{"):
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            values.append(value)
    calls: list[dict[str, Any]] = []
    for value in values:
        message = value.get("message")
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                calls.append(block)
    _require(len(calls) == expected_calls, f"serial contains {len(calls)} tool calls, want {expected_calls}")
    for call in calls:
        _require(call.get("name") == "Bash", "official Claude used a tool other than Bash")
        inputs = _object(call.get("input"), "Bash tool input")
        command = inputs.get("command")
        _require(isinstance(command, str) and "SAFE_CHANGE_EGRESS_URL" in command and "Idempotency-Key" in command, "Bash action differs from the fixed HTTP call")
    if complete:
        _require("DONE" in serial, "completed Claude session lacks DONE")
    return calls


def _model_requests(path: Path, repetitions: int, sessions: Sequence[str]) -> list[dict[str, Any]]:
    requests = _array(_json(path, "Anthropic model requests"), "Anthropic model requests")
    _require(len(requests) == repetitions * 7, "official Claude model request count differs")
    normalized: list[dict[str, Any]] = []
    replacements = {session: "<session>" for session in sessions}
    for index, raw in enumerate(requests, start=1):
        request = _object(raw, "Anthropic model request")
        _require(request.get("ordinal") == index and request.get("method") == "POST", "Anthropic request order/method differs")
        _require(str(request.get("path", "")).split("?", 1)[0].endswith("/messages"), "Anthropic request did not use the Messages endpoint")
        body = _object(request.get("body"), "Anthropic request body")
        _require(body.get("model") == "claude-fixture-1" and body.get("stream") is True, "Anthropic model/stream contract differs")
        tools = body.get("tools")
        _require(isinstance(tools, list) and any(isinstance(tool, dict) and tool.get("name") == "Bash" for tool in tools), "Anthropic request did not expose the real Bash tool")
        normalized_request = _normalize_history_value(request, replacements)
        normalized_body = _object(normalized_request.get("body"), "normalized Anthropic body")
        metadata = _object(normalized_body.get("metadata"), "Anthropic request metadata")
        user_id = metadata.get("user_id")
        try:
            client_identity = json.loads(user_id)
        except (TypeError, json.JSONDecodeError) as error:
            raise EvidenceError("Anthropic client identity metadata is malformed") from error
        _require(
            isinstance(client_identity, dict)
            and set(client_identity) == {"device_id", "account_uuid", "session_id"}
            and client_identity.get("account_uuid") == ""
            and re.fullmatch(r"[0-9a-f]{64}", str(client_identity.get("device_id", ""))) is not None
            and str(client_identity.get("session_id", "")).replace("-", "") in sessions,
            "Anthropic client identity does not join a lane session",
        )
        client_identity["device_id"] = "<client-device>"
        client_identity["session_id"] = "<session>"
        metadata["user_id"] = json.dumps(client_identity, sort_keys=True, separators=(",", ":"))
        normalized.append(normalized_request)
    for repetition in range(repetitions):
        base = repetition * 7
        initial = [normalized[base + offset]["body"] for offset in (0, 1, 3, 4, 5)]
        _require(all(body == initial[0] for body in initial[1:]), "H1/H0/native initial model requests differ")
    return requests


def _relay_map(path: Path) -> dict[str, list[dict[str, Any]]]:
    records = _array(_json(path, "raw egress relay"), "raw egress relay")
    by_label: dict[str, list[dict[str, Any]]] = {}
    prior_sequence = 0
    for raw in records:
        record = _object(raw, "raw relay record")
        _require(record.get("sequence") == prior_sequence + 1, "raw relay sequence is not contiguous")
        prior_sequence += 1
        label = record.get("label")
        _require(
            isinstance(label, str)
            and type(record.get("guest_to_host_bytes")) is int
            and type(record.get("host_to_guest_bytes")) is int
            and isinstance(record.get("error"), str),
            "raw relay record is malformed",
        )
        by_label.setdefault(label, []).append(record)
    return by_label


def _require_relay_shape(source: Sequence[Mapping[str, Any]], restore: Sequence[Mapping[str, Any]], restored: bool, label: str) -> None:
    _require(
        len(source) == 1
        and source[0].get("guest_to_host_bytes", 0) > 0
        and source[0].get("host_to_guest_bytes") == 0,
        f"{label} source relay bytes differ",
    )
    if restored:
        _require(
            len(restore) == 1
            and restore[0].get("guest_to_host_bytes", 0) > 0
            and restore[0].get("host_to_guest_bytes", 0) > 0,
            f"{label} restore relay bytes differ",
        )
        _require(restore[0].get("error") == "", f"{label} restored relay reports a transport error")
    else:
        _require(len(restore) == 0, f"{label} emitted bytes after denied resume")


def _check_stale(item: Mapping[str, Any]) -> None:
    _require(item.get("stale_status", 0) >= 400, "stale H1 generation was not rejected")
    stale_response = _object(item.get("stale_response"), "stale-generation response")
    _require("sandbox endpoint generation changed" in str(stale_response.get("detail", "")), "stale-generation response lacks the exact fencing reason")


def _check_execution_records(
    execution: Mapping[str, Any], residual: Mapping[str, Any], heartbeats: Sequence[Mapping[str, Any]], monitor: Mapping[str, Any]
) -> None:
    overall_started = execution.get("overall_started_time_ns")
    driver_started = execution.get("driver_started_time_ns")
    driver_finished = execution.get("driver_finished_time_ns")
    overall_finished = execution.get("overall_finished_time_ns")
    _require(
        all(type(value) is int and value > 0 for value in (overall_started, driver_started, driver_finished, overall_finished))
        and overall_started <= driver_started < driver_finished <= overall_finished
        and execution.get("driver_exit_status") == 0
        and execution.get("timed_out") is False
        and isinstance(execution.get("total_duration_seconds"), (int, float))
        and execution["total_duration_seconds"] > 0
        and isinstance(execution.get("driver_duration_seconds"), (int, float))
        and 0 < execution["driver_duration_seconds"] <= execution["total_duration_seconds"]
        and type(execution.get("timeout_seconds")) is int
        and execution["total_duration_seconds"] < execution["timeout_seconds"],
        "driver execution/deadline record is incomplete",
    )
    _require(
        abs(execution["total_duration_seconds"] - (overall_finished - overall_started) / 1_000_000_000) < 1e-6
        and abs(execution["driver_duration_seconds"] - (driver_finished - driver_started) / 1_000_000_000) < 1e-6,
        "execution durations do not match their retained clock endpoints",
    )
    _require(
        monitor == {"schema": 1, "stopped_by_launcher": True, "unexpected_failure": False, "exit_status": 0},
        "heartbeat monitor did not run until an intentional successful stop",
    )
    _require(
        residual.get("valid") is True
        and residual.get("residual_before") == []
        and residual.get("terminated_pids") == []
        and residual.get("residual_after") == [],
        "accepted run required cleanup of a residual QEMU process",
    )
    _require(len(heartbeats) >= 2, "execution has fewer than two retained heartbeats")
    allowed_stages = {
        "infrastructure-preflight", "clone-deathstar", "build-deathstar", "build-runtime",
        "deploy-deathstar", "run-agent-matrix", "verify-process-cleanup", "retain-final-evidence", "complete",
    }
    for heartbeat in heartbeats:
        _require(
            heartbeat.get("schema") == 1
            and type(heartbeat.get("time_ns")) is int
            and heartbeat.get("stage") in allowed_stages,
            "execution heartbeat is malformed",
        )
    _require(
        overall_started <= heartbeats[0]["time_ns"] <= overall_started + 35_000_000_000
        and overall_finished - 35_000_000_000 <= heartbeats[-1]["time_ns"] <= overall_finished,
        "heartbeats do not cover both endpoints of the complete execution",
    )
    for prior, current in zip(heartbeats, heartbeats[1:]):
        _require(0 < current["time_ns"] - prior["time_ns"] <= 35_000_000_000, "heartbeat interval exceeded 35 seconds")


def _check_endpoint_join(guard: Mapping[str, Any], manifest: Mapping[str, Any], publication: Mapping[str, Any]) -> None:
    endpoint = _object(guard.get("endpoint"), "guard endpoint")
    _require(
        endpoint.get("path") == publication.get("path") == manifest.get("endpoint_path")
        and endpoint.get("device") == publication.get("device")
        and endpoint.get("inode") == publication.get("inode")
        and endpoint.get("binding") == manifest.get("binding"),
        "guard endpoint does not join the published endpoint and live binding",
    )


def _check_guard(path: Path, decision: str, process: Mapping[str, Any], disk: Mapping[str, Any]) -> dict[str, Any]:
    guard = _object(_json(path / "resume-guard.json", "resume guard"), "resume guard")
    _require(guard.get("guarded") is True and guard.get("resume_attempted") is True, "guard did not receive an actual resume attempt")
    _require(guard.get("certificate_decision") == decision, "guard Certificate decision differs")
    _require(isinstance(guard.get("checkpoint_sha256"), str), "guard omitted checkpoint binding")
    _require(isinstance(guard.get("machine_config_sha256"), str), "guard omitted machine configuration binding")
    _require(isinstance(guard.get("process"), dict) and isinstance(guard.get("endpoint"), dict), "guard omitted process or endpoint binding")
    _require(guard.get("process") == process and guard.get("disk") == disk, "guard did not bind the live QEMU process and disk")
    if decision == "activate":
        _require(
            guard.get("authorization_issued") is True
            and guard.get("authorization_consumed") is True
            and guard.get("qmp_cont_issued") is True,
            "activate guard did not consume one permit before QMP cont",
        )
        for field in ("live_state_read_times_ns", "live_binding_read_times_ns", "endpoint_probe_times_ns"):
            values = guard.get(field)
            _require(isinstance(values, list) and len(values) == 2 and all(type(value) is int for value in values), f"activate guard {field} does not prove two live passes")
        _require(
            isinstance(guard.get("live_states"), list)
            and len(guard["live_states"]) == 2
            and all(isinstance(value, dict) for value in guard["live_states"])
            and isinstance(guard.get("live_binding_views"), list)
            and len(guard["live_binding_views"]) == 2
            and all(isinstance(value, list) for value in guard["live_binding_views"]),
            "activate guard omitted the two live Control views",
        )
        ordered = [
            guard.get("authorize_started_time_ns"),
            guard["live_state_read_times_ns"][0],
            guard["live_binding_read_times_ns"][0],
            guard["endpoint_probe_times_ns"][0],
            guard.get("authorization_issued_time_ns"),
            guard.get("resume_started_time_ns"),
            guard["live_state_read_times_ns"][1],
            guard["live_binding_read_times_ns"][1],
            guard["endpoint_probe_times_ns"][1],
            guard.get("qmp_cont_requested_time_ns"),
        ]
        _require(all(type(value) is int for value in ordered) and ordered == sorted(ordered), "activate guard timeline is not ordered")
    else:
        _require(
            guard.get("authorization_issued") is False
            and guard.get("qmp_cont_issued") is False
            and "invalid" in str(guard.get("resume_error", "")),
            "impossible guard did not deny the actual resume attempt",
        )
        _require(
            guard.get("live_state_read_times_ns") == []
            and guard.get("live_binding_read_times_ns") == []
            and guard.get("endpoint_probe_times_ns") == [],
            "impossible guard unexpectedly read post-decision resume facts",
        )
        _require(guard.get("live_states") == [] and guard.get("live_binding_views") == [], "impossible guard retained unexpected live Control views")
    return guard


def _fact_hash(facts: Sequence[Mapping[str, Any]]) -> str:
    ordered = sorted(
        facts,
        key=lambda item: (
            item.get("customer_name"),
            item.get("hotel_id"),
            item.get("in_date"),
            item.get("out_date"),
            item.get("rooms"),
        ),
    )
    # Go emits ReservationFact fields in this declaration order.
    canonical = [
        {
            "customer_name": item.get("customer_name"),
            "hotel_id": item.get("hotel_id"),
            "in_date": item.get("in_date"),
            "out_date": item.get("out_date"),
            "rooms": item.get("rooms"),
        }
        for item in ordered
    ]
    return sha256(json.dumps(canonical, separators=(",", ":")).encode()).hexdigest()


def _check_observation(item: Mapping[str, Any], expected_count: int, fence: Mapping[str, Any] | None = None) -> None:
    facts = _array(item.get("facts"), "retained Mongo documents")
    _require(item.get("count") == expected_count and len(facts) == expected_count, "retained Mongo document count differs")
    expected_fact = {
        "customer_name": "Cornell_30",
        "hotel_id": "1",
        "in_date": "2015-04-09",
        "out_date": "2015-04-10",
        "rooms": 1,
    }
    _require(all(fact == expected_fact for fact in facts), "Mongo document differs from the fixed reservation")
    _require(item.get("facts_hash") == _fact_hash(facts), "retained Mongo document hash differs")
    if fence is not None:
        _require(item.get("outcome") == "failed" and item.get("terminal_fence") == fence, "zero-row observation lacks the exact terminal fence")


def check(evidence: Path, checker: Path) -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parent.parent
    retained_source = _object(_json(evidence / "source-manifest.json", "source manifest"), "source manifest")
    current_source = _current_source_manifest(repo_root)
    _require(retained_source == current_source, "retained source manifest differs from the current complete source set")
    outer = _object(_json(evidence / "result.json", "outer result"), "outer result")
    graph = _object(_json(evidence / "graph.json", "DeathStar graph"), "DeathStar graph")
    runtime = evidence / "runtime"
    result = _object(_json(runtime / "result.json", "runtime result"), "runtime result")
    _require(outer.get("pass") is True and graph.get("pass") is True and result.get("valid") is True, "producer did not declare a valid run")
    _require(graph.get("commit") == "6ecb09706140f8730b5385c08f1386c654c3c526", "DeathStarBench commit differs")
    _require(graph.get("official_services") == 24 and graph.get("source_modified") is False, "DeathStarBench is not the unmodified 24-service workload")
    _require(graph.get("runtime_tree_hash") == retained_source.get("root_sha256"), "runtime image provenance differs from the retained source manifest")
    progress = _object(_json(runtime / "progress.json", "runtime progress"), "runtime progress")
    execution = _object(_json(evidence / "execution.json", "execution duration"), "execution duration")
    _require(progress.get("status") == "complete" and progress.get("stage") == "complete", "runtime progress did not reach complete")
    residual = _object(_json(evidence / "residual-processes.json", "residual process check"), "residual process check")
    heartbeats = _jsonl(evidence / "heartbeat.jsonl", "execution heartbeats")
    monitor = _object(_json(evidence / "monitor-status.json", "heartbeat monitor status"), "heartbeat monitor status")
    _check_execution_records(execution, residual, heartbeats, monitor)
    repetitions = result.get("repetitions")
    _require(type(repetitions) is int and repetitions >= 1, "invalid repetition count")
    _require(
        residual.get("checked_qemu_processes") == repetitions * 7
        and residual.get("checked_runner_processes") == repetitions * 7
        and residual.get("checked_processes") == repetitions * 14,
        "residual cleanup did not inspect every QEMU and VM-runner launch",
    )
    artifacts = _object(result.get("artifacts"), "runtime artifacts")
    _check_artifacts(artifacts, checker)
    qemu_runner_sha256 = str(artifacts.get("qemu_runner", ""))
    h1 = _array(result.get("h1"), "H1 results")
    h0 = _array(result.get("h0"), "H0 results")
    native = _array(result.get("native"), "native results")
    _require(len(h1) == len(h0) == len(native) == repetitions, "matrix repetition count differs")
    sessions = [
        str(_object(item, "lane result").get("session", ""))
        for collection in (h1, h0, native)
        for item in collection
    ]
    _require(all(re.fullmatch(r"[0-9a-f]{32}", session) for session in sessions), "lane session identity is malformed")
    _model_requests(runtime / "anthropic-requests.json", repetitions, sessions)
    requirement_v2 = _json(runtime / "requirement-v2.json", "target Requirement")
    target_sha = sha256(_canonical(requirement_v2)).hexdigest()
    audit = _jsonl(evidence / "deathstar-adapter.audit.jsonl", "DeathStar adapter audit")
    _require(len(audit) == repetitions * 3, "DeathStar adapter delivery count differs")
    for record in audit:
        _require(
            record.get("delivery") in {1, 2}
            and record.get("upstream_status") == 200
            and record.get("upstream_ok") is True
            and record.get("drop") is False
            and record.get("post_commit_delay_ms") == 8000
            and type(record.get("committed_time_ns")) is int
            and record["committed_time_ns"] > 0
            and re.fullmatch(r"[0-9a-f]{64}", str(record.get("upstream_hash", ""))) is not None,
            "DeathStar adapter retained a malformed or unexpected delivery",
        )
    observer = _object(_json(runtime / "observer-facts.json", "Mongo observations"), "Mongo observations")
    observations = _array(observer.get("facts"), "Mongo observation facts")
    relay = _relay_map(runtime / "egress-relay.json")
    expected_relay_labels = {
        f"run-{index}-{lane}-{phase}"
        for index in range(1, repetitions + 1)
        for lane, phases in (("h1", ("source", "restore")), ("h0", ("source",)), ("native", ("source", "restore")))
        for phase in phases
    }
    _require(set(relay) == expected_relay_labels, "raw relay contains a missing or unexpected connection label")
    fence_directory = evidence / "terminal-fences"
    fence_info = fence_directory.lstat()
    _require(stat.S_ISDIR(fence_info.st_mode) and not stat.S_ISLNK(fence_info.st_mode) and stat.S_IMODE(fence_info.st_mode) == 0o700, "terminal fence directory is not private")
    fences = sorted(fence_directory.glob("*.json"))
    _require(len(fences) == repetitions, "terminal fence count differs from H0 repetitions")

    certificate_verdicts: list[dict[str, Any]] = []
    for index in range(1, repetitions + 1):
        run_root = runtime / "runs" / f"run-{index}"
        checkpoint_root = runtime / "checkpoints" / f"run-{index}"
        sealed = checkpoint_root / "sealed.qcow2"
        sealed_record = _object(_json(checkpoint_root / "sealed.json", "sealed checkpoint"), "sealed checkpoint")
        sealed_sha = _sha_file(sealed)
        _require(sealed_record.get("checkpoint_sha256") == sealed_sha, "sealed qcow2 hash differs")
        prepare_phase = _check_qemu_phase(checkpoint_root / "prepare-vm", "prepare")
        machine = _machine_config(checkpoint_root / "prepare-vm")
        host_tools = _host_tools(checkpoint_root / "prepare-vm")
        prepare_process = _check_process_command(checkpoint_root / "prepare-vm", machine, host_tools, False)
        _require_reaped(prepare_process)
        _check_runner_process(checkpoint_root / "prepare-vm", qemu_runner_sha256)
        machine_hash = sha256(_go_canonical(machine)).hexdigest()
        _require(sealed_record.get("machine_config_sha256") == machine_hash, "sealed machine configuration hash differs")

        h1_root = run_root / "h1"
        h0_root = run_root / "h0"
        native_root = run_root / "native"
        h1_item = _object(h1[index - 1], "H1 item")
        h0_item = _object(h0[index - 1], "H0 item")
        native_item = _object(native[index - 1], "native item")
        _require(
            h1_item.get("checkpoint_sha256") == h0_item.get("checkpoint_sha256") == native_item.get("checkpoint_sha256") == sealed_sha,
            "H0/H1/native did not share the same sealed checkpoint",
        )
        _require(h1_item.get("target_sha256") == h0_item.get("target_sha256") == target_sha, "H0/H1 target bytes differ")
        _require(_normalized_unknown(h1_root / "unknown-state.json") == _normalized_unknown(h0_root / "unknown-state.json"), "H0/H1 histories differ before the authoritative result fact")

        h1_history = _history(h1_root / "control.history")
        h0_history = _history(h0_root / "control.history")
        h1_anchor = _head_anchor(h1_root / "control.head", h1_history)
        h0_anchor = _head_anchor(h0_root / "control.head", h0_history)
        _require(_normalized_history_prefix(h1_history) == _normalized_history_prefix(h0_history), "complete normalized H1/H0 History prefix differs")
        _require(
            len(h1_history) == 6
            and h1_history[4].get("operation") == "operation.phase"
            and h1_history[4].get("data", {}).get("update", {}).get("phase") == "succeeded"
            and h1_history[5].get("operation") == "rule.bindings.cutover",
            "H1 History does not contain exactly success recovery then target cutover",
        )
        _require(
            len(h0_history) == 5
            and h0_history[4].get("operation") == "operation.phase"
            and h0_history[4].get("data", {}).get("update", {}).get("phase") == "failed",
            "H0 History does not contain exactly failed recovery",
        )
        h1_current = _object(_json(h1_root / "current-state.json", "H1 current State"), "H1 current State")
        h0_current = _object(_json(h0_root / "current-state.json", "H0 current State"), "H0 current State")
        _require(h1_current.get("history") == {"sequence": h1_anchor["sequence"], "hash": h1_anchor["hash"]}, "H1 live State does not name its anchored History")
        _require(h0_current.get("history") == {"sequence": h0_anchor["sequence"], "hash": h0_anchor["hash"]}, "H0 live State does not name its anchored History")

        certificate_verdicts.append(
            _certificate(checker, h1_root / "certificate-state.json", h1_root / "certificate.json", "activate")
        )
        certificate_verdicts.append(
            _certificate(checker, h0_root / "certificate-state.json", h0_root / "certificate.json", "impossible")
        )
        h1_certificate = _object(_json(h1_root / "certificate.json", "H1 Certificate"), "H1 Certificate")
        h0_certificate = _object(_json(h0_root / "certificate.json", "H0 Certificate"), "H0 Certificate")
        _require(h1_certificate.get("requirement") == h0_certificate.get("requirement") == requirement_v2, "H1/H0 Certificates do not bind the byte-identical target")
        h1_source_phase = _check_qemu_phase(h1_root / "source-vm", "source")
        h1_restore_phase = _check_qemu_phase(h1_root / "restore-vm", "h1-restore")
        h0_source_phase = _check_qemu_phase(h0_root / "source-vm", "source")
        h0_restore_phase = _check_qemu_phase(h0_root / "restore-vm", "h0-restore")
        native_source_phase = _check_qemu_phase(native_root / "source-vm", "source")
        native_restore_phase = _check_qemu_phase(native_root / "restore-vm", "native-restore")
        phase_paths = [
            h1_root / "source-vm", h1_root / "restore-vm", h0_root / "source-vm",
            h0_root / "restore-vm", native_root / "source-vm", native_root / "restore-vm",
        ]
        _require(all(_machine_config(path) == machine for path in phase_paths), "a lane changed the canonical machine configuration")
        _require(all(_host_tools(path) == host_tools for path in phase_paths), "a lane changed the pinned QEMU/netcat tool set")
        live_identities = [_check_live_vm(path, sealed_sha, machine, host_tools) for path in phase_paths]
        for process, _ in live_identities:
            _require_reaped(process)
        for path in phase_paths:
            _check_runner_process(path, qemu_runner_sha256)
        h1_guard = _check_guard(h1_root / "restore-vm", "activate", *live_identities[1])
        h0_guard = _check_guard(h0_root / "restore-vm", "impossible", *live_identities[3])
        _require(h1_guard.get("checkpoint_sha256") == sealed_sha and h1_guard.get("machine_config_sha256") == machine_hash, "H1 guard checkpoint/machine binding differs")
        _require(h0_guard.get("checkpoint_sha256") == sealed_sha and h0_guard.get("machine_config_sha256") == machine_hash, "H0 guard checkpoint/machine binding differs")
        h1_manifest = _object(_json(h1_root / "resume-manifest.json", "H1 resume manifest"), "H1 resume manifest")
        h0_manifest = _object(_json(h0_root / "resume-manifest.json", "H0 resume manifest"), "H0 resume manifest")
        _require(h1_manifest.get("schema") == h0_manifest.get("schema") == 2, "resume manifest schema differs")
        h1_unknown = _object(_json(h1_root / "unknown-state.json", "H1 unknown State"), "H1 unknown State")
        h0_unknown = _object(_json(h0_root / "unknown-state.json", "H0 unknown State"), "H0 unknown State")
        h1_checked = _object(_json(h1_root / "checked-state.json", "H1 checked State"), "H1 checked State")
        h0_checked = _object(_json(h0_root / "checked-state.json", "H0 checked State"), "H0 checked State")
        h1_projection = _object(_json(h1_root / "certificate-state.json", "H1 Certificate projection"), "H1 Certificate projection")
        h0_projection = _object(_json(h0_root / "certificate-state.json", "H0 Certificate projection"), "H0 Certificate projection")
        _join_history_evidence(h1_history, h1_unknown, h1_checked, h1_certificate, h1_projection, h1_current, h1_manifest, "activate")
        _join_history_evidence(h0_history, h0_unknown, h0_checked, h0_certificate, h0_projection, h0_current, h0_manifest, "impossible")
        _require(h1_guard.get("live_states") == [h1_current, h1_current], "H1 guard live State views differ from the activated raw History head")
        _require(h1_guard.get("live_binding_views") == [[h1_manifest.get("binding")], [h1_manifest.get("binding")]], "H1 guard live binding views differ from the target cutover")
        h1_endpoint = _object(_json(h1_root / "endpoint-publication.json", "H1 endpoint publication"), "H1 endpoint publication")
        _check_endpoint_join(h1_guard, h1_manifest, h1_endpoint)
        cutover = _object(_json(h1_root / "target-cutover.json", "H1 target cutover"), "H1 target cutover")
        _require(cutover.get("state") == h1_current, "retained target cutover State differs from the later live State")
        cont_times = [time_ns for command, time_ns in h1_restore_phase["command_times"] if command == "cont"]
        _require(
            len(cont_times) == 1
            and cutover.get("completed_time_ns", 0) <= h1_endpoint.get("time_ns", 0) <= h1_guard.get("authorize_started_time_ns", 0)
            and h1_guard.get("qmp_cont_requested_time_ns", 0) <= cont_times[0],
            "H1 cutover/publication/guard/QMP timeline is not ordered",
        )
        _require(not any(command == "cont" for command, _ in h0_restore_phase["command_times"]), "H0 QMP trace contains cont")

        _serial_tool_calls(h1_source_phase["serial"], str(h1_item.get("session")), 1, False)
        _serial_tool_calls(h1_restore_phase["serial"], str(h1_item.get("session")), 1, True)
        _serial_tool_calls(h0_source_phase["serial"], str(h0_item.get("session")), 1, False)
        _serial_tool_calls(h0_restore_phase["serial"], str(h0_item.get("session")), 0, False)
        _serial_tool_calls(native_source_phase["serial"], str(native_item.get("session")), 1, False)
        _serial_tool_calls(native_restore_phase["serial"], str(native_item.get("session")), 1, True)

        for label, item, rows, deliveries, completed in (
            ("H1", h1_item, 1, 1, True),
            ("H0", h0_item, 0, 0, False),
            ("native", native_item, 2, 2, True),
        ):
            _require(
                item.get("mongo_rows") == rows
                and item.get("deliveries") == deliveries
                and item.get("task_completed") is completed,
                f"{label} terminal oracle differs",
            )
            source_relay = _array(item.get("source_relay"), f"{label} source relay")
            relay_name = label.lower()
            raw_source = relay.get(f"run-{index}-{relay_name}-source", [])
            raw_restore = relay.get(f"run-{index}-{relay_name}-restore", [])
            _require(
                source_relay == raw_source
                and item.get("restore_relay") == raw_restore,
                f"{label} producer relay summary differs from raw relay evidence",
            )
            _require_relay_shape(raw_source, raw_restore, label != "H0", label)
        _check_stale(h1_item)
        _require(h0_item.get("resume_denied") is True, "H0 resume denial is absent")

        h1_id = h1_item.get("operation_id")
        h0_id = h0_item.get("operation_id")
        native_id = native_item.get("operation_id")
        _require(all(isinstance(value, str) and value for value in (h1_id, h0_id, native_id)), "lane Operation identity is missing")
        h1_audit = [record for record in audit if record.get("operation_id") == h1_id]
        h0_audit = [record for record in audit if record.get("operation_id") == h0_id]
        native_audit = [record for record in audit if record.get("operation_id") == native_id]
        _require(len(h1_audit) == 1 and [record.get("delivery") for record in h1_audit] == [1], "H1 redispatched to DeathStarBench")
        _require(h0_audit == [], "H0 reached DeathStarBench")
        _require(len(native_audit) == 2 and [record.get("delivery") for record in native_audit] == [1, 2], "native replay did not deliver twice")

        h0_external = _object(h0_item.get("source_external"), "H0 source external fact")
        h0_request_hash = h0_external.get("request_hash")
        _require(isinstance(h0_request_hash, str), "H0 source external fact lacks request hash")
        matching_fences = [path for path in fences if path.name == sha256(h0_id.encode()).hexdigest() + ".json"]
        _require(len(matching_fences) == 1, "H0 does not have exactly one retained terminal fence")
        fence = _terminal_fence(matching_fences[0], h0_id, h0_request_hash)
        h0_operation = _object(_object(h0_current.get("operations"), "H0 current Operations").get(h0_id), "H0 current Operation")
        _require(h0_operation.get("request_hash") == h0_request_hash and h0_operation.get("phase") == "failed", "H0 fence does not join the failed History Operation")

        h1_facts = [item for item in observations if item.get("operation_id") == h1_id]
        h0_facts = [item for item in observations if item.get("operation_id") == h0_id]
        native_facts = [item for item in observations if item.get("operation_id") == native_id]
        _require(h1_facts and all(item.get("count") == 1 for item in h1_facts), "H1 Mongo facts are not exactly one row")
        _require(h0_facts and all(item.get("count") == 0 for item in h0_facts), "H0 Mongo facts are not exactly zero rows")
        _require(native_facts and native_facts[-1].get("count") == 2 and all(item.get("count") in {1, 2} for item in native_facts), "native Mongo facts do not progress from one to exactly two rows")
        for item in h1_facts:
            _check_observation(item, 1)
        for item in h0_facts:
            _check_observation(item, 0, fence)
        for item in native_facts[:-1]:
            _check_observation(item, int(item.get("count", -1)))
        _check_observation(native_facts[-1], 2)

    transparency = _object(result.get("transparency"), "transparency record")
    _require(
        transparency
        == {
            "claude_source_modified": False,
            "deathstar_source_modified": False,
            "guest_uses_ordinary_bash_http": True,
            "agent_runtime_integration_required": False,
        },
        "transparent-adoption record differs",
    )
    _require(observer.get("queries") == repetitions * 7, "Mongo query evidence count differs")
    _require(result.get("model_requests") == repetitions * 7, "official Claude model request count differs")
    summary = {
        "schema": 1,
        "valid": True,
        "repetitions": repetitions,
        "certificate_checks": len(certificate_verdicts),
        "h1_mongo_rows": [item["mongo_rows"] for item in h1],
        "h0_mongo_rows": [item["mongo_rows"] for item in h0],
        "native_mongo_rows": [item["mongo_rows"] for item in native],
        "same_target": True,
        "matched_unknown_history": True,
        "guarded_resume_enforced": True,
    }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--certificate-checker", required=True, type=Path)
    args = parser.parse_args()
    try:
        summary = check(args.evidence.resolve(strict=True), args.certificate_checker.resolve(strict=True))
    except (EvidenceError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"QEMU Agent Restore evidence invalid: {error}", file=sys.stderr)
        return 1
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
