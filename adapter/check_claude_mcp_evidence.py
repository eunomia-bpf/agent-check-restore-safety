"""Offline checker for the real Claude Code MCP process-continuity run.

The checker shares no implementation code with the producer.  It reconstructs
the durable History and MCP journal, joins them to the two raw Claude streams,
the model requests, Linux process identities, and the external provider log,
and rejects a self-reported success that lacks those facts.
"""

from __future__ import annotations

import argparse
import base64
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
import struct
from typing import Any, Mapping
from urllib.parse import urlsplit
import uuid


_CLAUDE_VERSION = "2.1.233"
_CLAUDE_VERSION_OUTPUT = "2.1.233 (Claude Code)"
_CLAUDE_SHA256 = "55d281096f57d411ebbdd94dbf5e9ff3accb7c05713e37348c2c11d4b83bf9d9"
_CLAUDE_SIZE = 324598064
_SIGNING_FINGERPRINT = "31DDDE24DDFAB679F42D7BD2BAA929FF1A7ECACE"
_EXECUTION_ID = "claude-mcp-execution-v1"
_DOMAIN = "claude-mcp-runtime"
_SANDBOX_ID = "claude-mcp"
_EFFECTS = ("effect-A", "effect-B")
_TOOL = "mcp__continuity__commit_effect"
_ZERO_HASH = "0" * 64
_PROMPT = "Commit effect-A and then effect-B with the continuity MCP tool. Finish with DONE."


class EvidenceError(RuntimeError):
    """Retained evidence does not establish the claimed execution."""


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise EvidenceError(f"duplicate JSON member {key!r}")
        result[key] = value
    return result


def _decode(data: bytes, label: str) -> Any:
    try:
        return json.loads(data, object_pairs_hook=_pairs)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise EvidenceError(f"{label} is not strict JSON") from error


def _canonical(value: Any) -> bytes:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=True).encode()


def _sha(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        while block := source.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


def _private_root(value: Path) -> Path:
    root = value.resolve(strict=True)
    info = root.lstat()
    if (
        value.resolve() != root
        or not stat.S_ISDIR(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise EvidenceError("evidence root must be a private current-user directory")
    return root


def _file(root: Path, name: str, *, allow_empty: bool = False) -> Path:
    path = root / name
    try:
        info = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise EvidenceError(f"cannot inspect {name}") from error
    if (
        path.parent != root
        or resolved != path
        or not stat.S_ISREG(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o600
        or (not allow_empty and info.st_size <= 0)
        or info.st_size > 64 << 20
    ):
        raise EvidenceError(f"unsafe evidence file {name}")
    return path


def _json_file(root: Path, name: str) -> Any:
    path = _file(root, name)
    value = _decode(path.read_bytes(), name)
    if path.read_bytes() != _canonical(value) + b"\n":
        raise EvidenceError(f"{name} is not canonical JSON")
    return value


def _json_lines(
    root: Path, name: str, *, require_canonical: bool = True
) -> list[dict[str, Any]]:
    path = _file(root, name)
    raw = path.read_bytes()
    if not raw.endswith(b"\n"):
        raise EvidenceError(f"{name} has an incomplete final record")
    records: list[dict[str, Any]] = []
    for index, line in enumerate(raw.splitlines(), start=1):
        value = _decode(line, f"{name}:{index}")
        if not isinstance(value, dict) or (require_canonical and _canonical(value) != line):
            raise EvidenceError(f"{name}:{index} is not a canonical object")
        records.append(value)
    if not records:
        raise EvidenceError(f"{name} is empty")
    return records


def _external_artifact(
    artifacts: Mapping[str, Any], key: str, *, executable: bool
) -> Path:
    record = artifacts.get(key)
    raw_path = record.get("path") if isinstance(record, dict) else None
    if not isinstance(raw_path, str):
        raise EvidenceError(f"result omits {key} artifact")
    path = Path(raw_path)
    try:
        info = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise EvidenceError(f"cannot inspect {key} artifact") from error
    if (
        not path.is_absolute()
        or resolved != path
        or not stat.S_ISREG(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or info.st_uid != os.geteuid()
        or info.st_size <= 0
        or stat.S_IMODE(info.st_mode) & 0o022
        or (executable and not os.access(path, os.X_OK))
        or record.get("sha256") != _sha(path)
    ):
        raise EvidenceError(f"unsafe or changed {key} artifact")
    return path


def _history(root: Path) -> list[dict[str, Any]]:
    raw = _file(root, "control.history").read_bytes()
    offset = 0
    previous = _ZERO_HASH
    events: list[dict[str, Any]] = []
    while offset < len(raw):
        if len(raw) - offset < 12 or raw[offset : offset + 4] != b"HST1":
            raise EvidenceError("History frame header is malformed")
        size = struct.unpack(">Q", raw[offset + 4 : offset + 12])[0]
        start = offset + 12
        end = start + size
        if size == 0 or size > 16 << 20 or end > len(raw):
            raise EvidenceError("History frame length is invalid")
        encoded = raw[start:end]
        event = _decode(encoded, f"History:{len(events) + 1}")
        if (
            not isinstance(event, dict)
            or set(event)
            != {"version", "sequence", "operation", "data", "previous_hash", "hash"}
            or _canonical(event) != encoded
        ):
            raise EvidenceError("History event is not a canonical version-1 frame")
        sequence = len(events) + 1
        operation = event.get("operation")
        digest = sha256(b"history-event-v1\x00" + struct.pack(">Q", sequence))
        for part in (
            previous.encode(),
            str(operation).encode(),
            _canonical(event.get("data")),
        ):
            digest.update(struct.pack(">Q", len(part)))
            digest.update(part)
        if (
            event.get("version") != 1
            or event.get("sequence") != sequence
            or not isinstance(operation, str)
            or not operation
            or event.get("previous_hash") != previous
            or event.get("hash") != digest.hexdigest()
        ):
            raise EvidenceError(f"History hash chain fails at event {sequence}")
        previous = digest.hexdigest()
        events.append(event)
        offset = end
    if len(events) != 7:
        raise EvidenceError("History does not contain the exact two-operation execution")
    return events


def _check_anchor(root: Path, history: list[dict[str, Any]]) -> None:
    anchor = _json_file(root, "control.head-anchor")
    last = history[-1]
    checksum = sha256(
        b"history-head-anchor-v1\x00"
        + struct.pack(">Q", last["sequence"])
        + last["hash"].encode()
    ).hexdigest()
    expected = {
        "version": 1,
        "sequence": last["sequence"],
        "hash": last["hash"],
        "checksum": checksum,
    }
    if anchor != expected:
        raise EvidenceError("external head anchor differs from the History head")


def _operation_id(call_id: str) -> str:
    return "op-" + sha256(
        b"sandbox-operation-id-v2\x00"
        + _DOMAIN.encode()
        + b"\x00"
        + _SANDBOX_ID.encode()
        + b"\x00"
        + call_id.encode()
    ).hexdigest()


def _protected_digest(effect: str) -> str:
    request = _canonical(
        {
            "schema": 1,
            "name": "commit_effect",
            "kind": "protected_commit",
            "arguments": {"effect_id": effect},
        }
    )
    return sha256(b"mcp-protected-call-v2\x00" + request).hexdigest()


def _decode_base64_json(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, str):
        raise EvidenceError(f"{label} is missing")
    try:
        decoded = base64.b64decode(value, validate=True)
    except ValueError as error:
        raise EvidenceError(f"{label} is not base64") from error
    parsed = _decode(decoded.rstrip(b"\n"), label)
    if not isinstance(parsed, dict):
        raise EvidenceError(f"{label} is not an object")
    return parsed


def _check_history(root: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], int]:
    events = _history(root)
    _check_anchor(root, events)
    operations = [event["operation"] for event in events]
    if operations != [
        "rule.bindings.cutover",
        "operation.prepared",
        "operation.phase",
        "operation.phase",
        "operation.prepared",
        "operation.phase",
        "operation.phase",
    ]:
        raise EvidenceError("History lifecycle order differs from the claimed execution")
    cutover = events[0]["data"]
    try:
        certificate = cutover["certificate"]
        requirement = certificate["requirement"]
        kind = requirement["kinds"]["protected_commit"]
        binding = cutover["bindings"][0]
        target = urlsplit(kind["target"])
        query = urlsplit(kind["query_target"])
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise EvidenceError("History cutover is malformed") from error
    if (
        cutover.get("semantic_version") != 1
        or len(cutover.get("bindings", [])) != 1
        or certificate.get("schema") != 1
        or certificate.get("decision") != "activate"
        or certificate.get("history") != {"sequence": 0, "hash": _ZERO_HASH}
        or requirement.get("id") != "real-claude-mcp-process-loss"
        or requirement.get("results") != {"committed": 2}
        or requirement.get("capacities") != {"external-write": 2}
        or set(requirement.get("kinds", {})) != {"protected_commit"}
        or kind.get("costs") != {"external-write": 1}
        or kind.get("produces") != {"committed": 1}
        or kind.get("retry_safe") is not False
        or kind.get("queryable") is not True
        or kind.get("method") != "POST"
        or kind.get("response_classifier") != "operation-receipt-v1"
        or kind.get("query_method") != "POST"
        or kind.get("query_classifier") != "operation-observation-v1"
        or target.scheme != "http"
        or target.hostname != "127.0.0.1"
        or target.path != "/v1/charge"
        or target.port is None
        or query.scheme != target.scheme
        or query.netloc != target.netloc
        or query.path != "/v1/query"
        or binding.get("sandbox_id") != _SANDBOX_ID
        or binding.get("generation") != 1
        or binding.get("domain") != _DOMAIN
        or binding.get("allowed_kinds") != ["protected_commit"]
        or not re.fullmatch(r"host-[0-9a-f]{32}", str(binding.get("host_instance_id")))
    ):
        raise EvidenceError("History cutover differs from the bounded Claude contract")

    outcomes: dict[str, dict[str, Any]] = {}
    for index, effect in enumerate(_EFFECTS):
        call_id = f"mcp-call-v1:{len(_EXECUTION_ID)}:{_EXECUTION_ID}:{index + 1}"
        operation_id = _operation_id(call_id)
        prepared = events[1 + index * 3]["data"].get("operation")
        dispatched = events[2 + index * 3]["data"]
        succeeded = events[3 + index * 3]["data"]
        body = _canonical({"effect_id": effect})
        request_digest = sha256()
        request_digest.update(b"POST\x00" + kind["target"].encode() + b"\x00")
        for name, value in (
            ("accept-encoding", "identity"),
            ("idempotency-key", operation_id),
            ("user-agent", "safe-change-runtime/1"),
            ("x-operation-id", operation_id),
        ):
            request_digest.update(name.encode() + b":" + value.encode() + b"\x00")
        request_digest.update(body)
        request_hash = request_digest.hexdigest()
        result_hash = sha256(
            b"charged\x00" + operation_id.encode() + b"\x001"
        ).hexdigest()
        if (
            not isinstance(prepared, dict)
            or prepared.get("id") != operation_id
            or prepared.get("domain") != _DOMAIN
            or prepared.get("sandbox_id") != _SANDBOX_ID
            or prepared.get("kind") != "protected_commit"
            or prepared.get("request_hash") != request_hash
            or prepared.get("rule_version") != 1
            or prepared.get("request_stored") is not True
            or prepared.get("request_body")
            != base64.b64encode(body).decode("ascii")
            or prepared.get("phase") != "prepared"
            or dispatched.get("id") != operation_id
            or dispatched.get("update", {}).get("phase") != "dispatched"
            or dispatched.get("update", {}).get("dispatch_generation") != 1
            or not re.fullmatch(
                r"[0-9a-f]{32}",
                str(dispatched.get("update", {}).get("dispatch_owner")),
            )
            or succeeded.get("id") != operation_id
            or succeeded.get("update", {}).get("phase") != "succeeded"
            or succeeded.get("update", {}).get("result_hash") != result_hash
            or succeeded.get("update", {}).get("status_code") != 200
            or succeeded.get("update", {}).get("remote_reference")
            != f"claude-mcp/{operation_id}/commit-1"
        ):
            raise EvidenceError(f"History Operation for {effect} is inconsistent")
        receipt = _decode_base64_json(
            succeeded["update"].get("result_body"), f"History receipt for {effect}"
        )
        if receipt != {
            "operation_id": operation_id,
            "outcome": "succeeded",
            "remote_reference": f"claude-mcp/{operation_id}/commit-1",
            "result_hash": result_hash,
            "schema": 1,
        }:
            raise EvidenceError(f"History receipt for {effect} differs from provider fact")
        outcomes[effect] = {
            "schema": 1,
            "operation_id": operation_id,
            "phase": "succeeded",
            "result_hash": result_hash,
            "reused": False,
            "recovered_by_query": False,
            "execution_fenced": False,
        }
    return events, outcomes, target.port


def _check_journal(
    root: Path, outcomes: Mapping[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    records = _json_lines(root, "mcp-calls.jsonl")
    if len(records) != 4:
        raise EvidenceError("MCP journal does not contain two completed calls")
    previous = ""
    for index, record in enumerate(records, start=1):
        call_sequence = (index + 1) // 2
        effect = _EFFECTS[call_sequence - 1]
        event = "prepared" if index % 2 else "completed"
        rpc_id = str(call_sequence + 1)
        call_id = f"mcp-call-v1:{len(_EXECUTION_ID)}:{_EXECUTION_ID}:{call_sequence}"
        if (
            record.get("schema") != 1
            or record.get("record_sequence") != index
            or record.get("call_sequence") != call_sequence
            or record.get("event") != event
            or record.get("execution_id") != _EXECUTION_ID
            or record.get("rpc_id") != rpc_id
            or record.get("request_digest") != _protected_digest(effect)
            or record.get("call_id") != call_id
            or record.get("uncertain") is not False
            or record.get("previous_hash", "") != previous
        ):
            raise EvidenceError(f"MCP journal identity fails at record {index}")
        payload = {key: value for key, value in record.items() if key != "hash"}
        if record.get("hash") != sha256(_canonical(payload)).hexdigest():
            raise EvidenceError(f"MCP journal hash fails at record {index}")
        if event == "prepared":
            if "response" in record:
                raise EvidenceError("prepared MCP journal entry contains a response")
        else:
            response = _decode_base64_json(record.get("response"), "MCP response")
            structured = response.get("result", {}).get("structuredContent")
            if (
                response.get("jsonrpc") != "2.0"
                or response.get("id") != call_sequence + 1
                or structured != outcomes[effect]
            ):
                raise EvidenceError(f"MCP response for {effect} differs from History")
        previous = str(record["hash"])
    return records


def _check_provider(
    root: Path, outcomes: Mapping[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    payments = _json_lines(root, "payment.history")
    if len(payments) != 2:
        raise EvidenceError("provider did not commit exactly two external effects")
    for payment, effect in zip(payments, _EFFECTS, strict=True):
        outcome = outcomes[effect]
        body = _canonical({"effect_id": effect})
        expected = {
            "operation_id": outcome["operation_id"],
            "request_hash": sha256(b"POST\x00/v1/charge\x00" + body).hexdigest(),
            "result_hash": outcome["result_hash"],
            "remote_reference": f"claude-mcp/{outcome['operation_id']}/commit-1",
            "path": "/v1/charge",
        }
        if payment != expected:
            raise EvidenceError(f"provider fact for {effect} differs from History")
    return payments


def _assistant_tool(record: Mapping[str, Any], effect: str) -> str:
    content = record.get("message", {}).get("content")
    if not isinstance(content, list) or len(content) != 1:
        raise EvidenceError("Claude assistant record has unexpected content")
    block = content[0]
    tool_id = block.get("id") if isinstance(block, dict) else None
    if (
        not isinstance(block, dict)
        or block.get("type") != "tool_use"
        or block.get("name") != _TOOL
        or block.get("input") != {"effect_id": effect}
        or not isinstance(tool_id, str)
    ):
        raise EvidenceError(f"Claude did not call the protected tool for {effect}")
    return tool_id


def _tool_result(
    record: Mapping[str, Any], tool_id: str, outcome: Mapping[str, Any]
) -> None:
    content = record.get("message", {}).get("content")
    if not isinstance(content, list) or len(content) != 1:
        raise EvidenceError("Claude tool result record has unexpected content")
    block = content[0]
    if not isinstance(block, dict) or block.get("tool_use_id") != tool_id:
        raise EvidenceError("Claude tool result is bound to another invocation")
    decoded = _decode(str(block.get("content", "")).encode(), "Claude tool result")
    structured = record.get("tool_use_result", {}).get("structuredContent")
    if decoded != outcome or structured != outcome:
        raise EvidenceError("Claude-observed result differs from the host journal")


def _check_init(record: Mapping[str, Any]) -> str:
    session_id = record.get("session_id")
    try:
        uuid.UUID(str(session_id))
    except ValueError as error:
        raise EvidenceError("Claude stream has an invalid session identity") from error
    if (
        record.get("type") != "system"
        or record.get("subtype") != "init"
        or record.get("tools") != ["Bash", "Edit", "Read", _TOOL]
        or record.get("mcp_servers") != [{"name": "continuity", "status": "connected"}]
        or record.get("model") != "claude-fixture-1"
        or record.get("permissionMode") != "dontAsk"
        or record.get("apiKeySource") != "ANTHROPIC_API_KEY"
        or record.get("claude_code_version") != _CLAUDE_VERSION
        or record.get("skills") != []
        or record.get("plugins") != []
        or record.get("analytics_disabled") is not True
        or record.get("product_feedback_disabled") is not True
    ):
        raise EvidenceError("Claude initialization did not use the bounded bare MCP mode")
    return str(session_id)


def _check_streams(
    root: Path, outcomes: Mapping[str, dict[str, Any]]
) -> tuple[str, str]:
    first = _json_lines(root, "claude-first.stream.jsonl", require_canonical=False)
    second = _json_lines(root, "claude-second.stream.jsonl", require_canonical=False)
    if len(first) != 2 or len(second) != 7:
        raise EvidenceError("Claude streams do not show one interrupted and one complete run")
    first_session = _check_init(first[0])
    second_session = _check_init(second[0])
    if first_session == second_session:
        raise EvidenceError("replacement Claude reused the source session")
    first_tool = _assistant_tool(first[1], "effect-A")
    if any(record.get("type") in {"user", "result"} for record in first):
        raise EvidenceError("source Claude received a result before process replacement")
    second_a = _assistant_tool(second[1], "effect-A")
    _tool_result(second[2], second_a, outcomes["effect-A"])
    second_b = _assistant_tool(second[3], "effect-B")
    _tool_result(second[4], second_b, outcomes["effect-B"])
    final_content = second[5].get("message", {}).get("content")
    final = second[6]
    if (
        first_tool == second_a
        or second_a == second_b
        or final_content != [{"text": "DONE", "type": "text"}]
        or final.get("type") != "result"
        or final.get("subtype") != "success"
        or final.get("result") != "DONE"
        or final.get("is_error") is not False
        or final.get("permission_denials") != []
    ):
        raise EvidenceError("replacement Claude did not finish only the intended effects")
    return first_session, second_session


def _conversation_effects(messages: Any) -> tuple[list[str], list[str]]:
    if not isinstance(messages, list):
        raise EvidenceError("Anthropic request omits its message history")
    calls: dict[str, str] = {}
    order: list[str] = []
    completed: list[str] = []
    for message in messages:
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and block.get("name") == _TOOL:
                tool_id = block.get("id")
                effect = block.get("input", {}).get("effect_id")
                if not isinstance(tool_id, str) or effect not in _EFFECTS:
                    raise EvidenceError("Anthropic history contains a malformed protected call")
                calls[tool_id] = effect
                order.append(effect)
            if block.get("type") == "tool_result":
                tool_id = block.get("tool_use_id")
                if tool_id in calls:
                    completed.append(calls[tool_id])
    return order, completed


def _check_model_requests(
    root: Path, processes: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    requests = _json_file(root, "anthropic-requests.json")
    if not isinstance(requests, list) or len(requests) != 4:
        raise EvidenceError("model fixture did not retain four Claude requests")
    expected_histories = [([], []), ([], []), (["effect-A"], ["effect-A"]), (list(_EFFECTS), list(_EFFECTS))]
    for index, (request, expected) in enumerate(
        zip(requests, expected_histories, strict=True), start=1
    ):
        body = request.get("body") if isinstance(request, dict) else None
        tools = body.get("tools") if isinstance(body, dict) else None
        names = [tool.get("name") for tool in tools] if isinstance(tools, list) else []
        if (
            request.get("ordinal") != index
            or request.get("method") != "POST"
            or request.get("path") != "/v1/messages?beta=true"
            or not isinstance(request.get("time_ns"), int)
            or body.get("model") != "claude-fixture-1"
            or body.get("stream") is not True
            or names != ["Bash", "Edit", "Read", _TOOL]
            or _conversation_effects(body.get("messages")) != expected
        ):
            raise EvidenceError(f"Anthropic request {index} differs from the fixed protocol")
    times = [request["time_ns"] for request in requests]
    first, second = processes
    if (
        times != sorted(times)
        or not first["started_time_ns"] < times[0] < first["stopped_time_ns"]
        or not all(second["started_time_ns"] < value < second["stopped_time_ns"] for value in times[1:])
    ):
        raise EvidenceError("model requests do not belong to the two claimed process lifetimes")
    return requests


def _check_command(command: Any, binary: Path, mcp_config: Path, session_id: str) -> None:
    expected = [
        os.fspath(binary),
        "--bare",
        "--print",
        _PROMPT,
        "--output-format",
        "stream-json",
        "--verbose",
        "--no-session-persistence",
        "--strict-mcp-config",
        "--mcp-config",
        os.fspath(mcp_config),
        "--allowedTools",
        _TOOL,
        "--permission-mode",
        "dontAsk",
        "--model",
        "claude-fixture-1",
        "--max-turns",
        "4",
        "--no-chrome",
        "--disable-slash-commands",
        "--prompt-suggestions",
        "false",
        "--session-id",
        session_id,
    ]
    if command != expected:
        raise EvidenceError("Claude command weakens or bypasses the bounded MCP mode")


def _check_processes(
    root: Path,
    result: Mapping[str, Any],
    claude: Path,
    relay: Path,
    sessions: tuple[str, str],
    transport_root: Path,
) -> list[dict[str, Any]]:
    processes = result.get("processes")
    peers = result.get("relay_peers")
    if not isinstance(processes, list) or len(processes) != 2:
        raise EvidenceError("result does not bind two Claude processes")
    if not isinstance(peers, list) or len(peers) != 2:
        raise EvidenceError("result does not bind two MCP relay children")
    mcp_config = root / "mcp.json"
    expected_dispositions = [("claude-first", "supervisor-sigkill", -9), ("claude-second", "completed", 0)]
    for process, peer, session_id, expected in zip(
        processes, peers, sessions, expected_dispositions, strict=True
    ):
        label, disposition, exit_code = expected
        identity = process.get("identity") if isinstance(process, dict) else None
        if not isinstance(identity, dict):
            raise EvidenceError("Claude process omits its live /proc identity")
        _check_command(process.get("command"), claude, mcp_config, session_id)
        if (
            process.get("label") != label
            or process.get("disposition") != disposition
            or process.get("exit_code") != exit_code
            or not isinstance(process.get("pid"), int)
            or process.get("pid") <= 1
            or process.get("pid") != identity.get("pid")
            or identity.get("command") != process.get("command")
            or identity.get("process_group") != process.get("pid")
            or identity.get("session") != process.get("pid")
            or identity.get("uid") != os.geteuid()
            or identity.get("gid") != os.getegid()
            or identity.get("executable_sha256") != _CLAUDE_SHA256
            or identity.get("executable_size") != _CLAUDE_SIZE
            or Path(str(identity.get("executable_target"))).resolve() != claude
            or not isinstance(process.get("started_time_ns"), int)
            or not isinstance(process.get("stopped_time_ns"), int)
            or process.get("started_time_ns") >= process.get("stopped_time_ns")
            or process.get("stdout") != os.fspath(root / f"{label}.stream.jsonl")
            or process.get("stderr") != os.fspath(root / f"{label}.stderr.log")
        ):
            raise EvidenceError(f"{label} process identity is inconsistent")
        expected_relay_command = [
            os.fspath(relay),
            "-socket",
            os.fspath(transport_root / "relay" / "mcp-host.sock"),
        ]
        if (
            peer.get("parent_pid") != process.get("pid")
            or peer.get("process_group") != process.get("pid")
            or peer.get("session") != process.get("pid")
            or peer.get("uid") != os.geteuid()
            or peer.get("gid") != os.getegid()
            or peer.get("command") != expected_relay_command
            or peer.get("executable_sha256") != _sha(relay)
            or Path(str(peer.get("executable_target"))).resolve() != relay
        ):
            raise EvidenceError(f"{label} MCP relay was outside its replacement unit")
    if processes[0]["pid"] == processes[1]["pid"]:
        raise EvidenceError("Claude process replacement reused the source PID")
    return processes


def _check_services(
    root: Path,
    result: Mapping[str, Any],
    artifacts: Mapping[str, Any],
    provider_port: int,
    transport_root: Path,
) -> None:
    services = result.get("services")
    if not isinstance(services, dict) or set(services) != {"payment", "control", "mcp-host"}:
        raise EvidenceError("result omits the three host services")
    control = _external_artifact(artifacts, "control", executable=True)
    payment = _external_artifact(artifacts, "payment", executable=True)
    host = _external_artifact(artifacts, "mcp_host", executable=True)
    tools = _external_artifact(artifacts, "tools_config", executable=False)
    commands = {name: value.get("command") for name, value in services.items()}
    payment_command = commands["payment"]
    control_command = commands["control"]
    host_command = commands["mcp-host"]
    if (
        not isinstance(payment_command, list)
        or payment_command
        != [
            os.fspath(payment), "-listen", f"127.0.0.1:{provider_port}",
            "-state", os.fspath(root / "payment.history"), "-hold-after-commit",
            "-non-idempotent", "-reference-prefix", "claude-mcp",
        ]
        or not isinstance(control_command, list)
        or len(control_command) != 11
        or control_command[0] != os.fspath(control)
        or control_command[1] != "-listen"
        or not re.fullmatch(r"127\.0\.0\.1:[0-9]+", control_command[2])
        or control_command[3:]
        != [
            "-history", os.fspath(root / "control.history"),
            "-head-anchor", os.fspath(root / "control.head-anchor"),
            "-admin-token-file", os.fspath(root / "admin.token"),
            "-sandbox-socket-dir", os.fspath(transport_root / "sockets"),
        ]
        or not isinstance(host_command, list)
        or host_command
        != [
            os.fspath(host), "-config", os.fspath(tools), "-sandbox-socket",
            os.fspath(transport_root / "sockets" / ("sandbox-" + sha256(_SANDBOX_ID.encode()).hexdigest()[:32] + ".sock")),
            "-listen-socket", os.fspath(transport_root / "relay" / "mcp-host.sock"),
            "-execution-id", _EXECUTION_ID, "-journal", os.fspath(root / "mcp-calls.jsonl"),
        ]
    ):
        raise EvidenceError("host service commands differ from the continuity boundary")
    pids = [service.get("pid") for service in services.values()]
    if not all(isinstance(pid, int) and pid > 1 for pid in pids) or len(set(pids)) != 3:
        raise EvidenceError("host service process identities are malformed")


def _tree_manifest(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for item in sorted(path.rglob("*")):
        info = item.lstat()
        relative = item.relative_to(path).as_posix()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != os.geteuid():
            raise EvidenceError("Claude config tree contains an unsafe entry")
        if stat.S_ISDIR(info.st_mode):
            if stat.S_IMODE(info.st_mode) != 0o700:
                raise EvidenceError("Claude config directory is not mode 0700")
            records.append({"path": relative + "/", "mode": 0o700})
        elif stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600:
            records.append(
                {
                    "path": relative,
                    "mode": 0o600,
                    "size": info.st_size,
                    "sha256": _sha(item),
                }
            )
        else:
            raise EvidenceError("Claude config tree contains a non-private file")
    return records


def _check_private_inputs(
    root: Path,
    result: Mapping[str, Any],
    relay: Path,
    transport_root: Path,
) -> None:
    mcp = _json_file(root, "mcp.json")
    if mcp != {
        "mcpServers": {
            "continuity": {
                "args": [
                    "-socket", os.fspath(transport_root / "relay" / "mcp-host.sock")
                ],
                "command": os.fspath(relay),
                "env": {},
                "type": "stdio",
            }
        }
    }:
        raise EvidenceError("Claude MCP configuration contains another authority path")
    trees = result.get("config_trees")
    if not isinstance(trees, dict) or set(trees) != {"first", "second"}:
        raise EvidenceError("result omits isolated Claude config trees")
    for label in ("first", "second"):
        directory = root / f"claude-config-{label}"
        info = directory.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o700
            or trees[label] != _tree_manifest(directory)
        ):
            raise EvidenceError(f"{label} Claude config tree differs from its evidence")
    if (root / "admin.token").exists():
        raise EvidenceError("runtime admin credential remained in retained evidence")
    for path in root.rglob("*"):
        if path.is_file() and not path.is_symlink() and path.stat().st_size <= 64 << 20:
            if b"fixture-credential" in path.read_bytes():
                raise EvidenceError("fixture API credential leaked into retained evidence")


def _check_timeline(
    result: Mapping[str, Any],
    processes: list[dict[str, Any]],
    payments: list[dict[str, Any]],
    journal: list[dict[str, Any]],
) -> None:
    inflight = result.get("inflight")
    if not isinstance(inflight, dict):
        raise EvidenceError("result omits the process-loss cut")
    first_payment = _canonical(payments[0]) + b"\n"
    first_journal = _canonical(journal[0]) + b"\n"
    values = [
        inflight.get("provider_commit_observed_time_ns"),
        inflight.get("source_sigkill_time_ns"),
        inflight.get("provider_release_time_ns"),
        inflight.get("journal_completed_time_ns"),
        processes[1].get("started_time_ns"),
    ]
    if (
        not all(isinstance(value, int) for value in values)
        or not values[0] < values[1] <= values[2] <= values[3] < values[4]
        or values[1] != processes[0].get("stopped_time_ns")
        or inflight.get("payment_record_sha256") != sha256(first_payment).hexdigest()
        or inflight.get("journal_prepared_sha256") != sha256(first_journal).hexdigest()
    ):
        raise EvidenceError("retained clocks do not establish the in-flight replacement cut")


def check(path: Path) -> dict[str, Any]:
    root = _private_root(path)
    result = _json_file(root, "result.json")
    if (
        not isinstance(result, dict)
        or result.get("schema") != 1
        or result.get("valid") is not True
        or result.get("system") != "real-claude-mcp-process-continuity"
        or result.get("claude_version") != _CLAUDE_VERSION
        or result.get("execution_id") != _EXECUTION_ID
        or result.get("provider_deliveries") != 2
        or result.get("provider_commits") != 2
        or result.get("mcp_relay_lifetimes") != 2
        or result.get("model_requests") != 4
    ):
        raise EvidenceError("result does not claim the exact schema-1 Claude run")
    artifacts = result.get("artifacts")
    if not isinstance(artifacts, dict):
        raise EvidenceError("result omits artifact fingerprints")
    claude = _external_artifact(artifacts, "claude", executable=True)
    relay = _external_artifact(artifacts, "mcp_relay", executable=True)
    if (
        claude.stat().st_size != _CLAUDE_SIZE
        or _sha(claude) != _CLAUDE_SHA256
        or result.get("claude_release")
        != {
            "path": artifacts.get("claude_lock", {}).get("path"),
            "sha256": artifacts.get("claude_lock", {}).get("sha256"),
            "version": _CLAUDE_VERSION,
            "platform": "linux-x64",
            "signing_key_fingerprint": _SIGNING_FINGERPRINT,
            "version_output": _CLAUDE_VERSION_OUTPUT,
        }
    ):
        raise EvidenceError("Claude binary differs from its signed pinned release")
    claude_lock = _external_artifact(artifacts, "claude_lock", executable=False)
    lock = _decode(claude_lock.read_bytes(), "Claude release lock")
    release = lock.get("claude_code") if isinstance(lock, dict) else None
    if (
        lock.get("schema") != 1
        or not isinstance(release, dict)
        or release.get("version") != _CLAUDE_VERSION
        or release.get("platform") != "linux-x64"
        or release.get("binary_size") != _CLAUDE_SIZE
        or release.get("binary_sha256") != _CLAUDE_SHA256
        or release.get("version_output") != _CLAUDE_VERSION_OUTPUT
        or release.get("signing_key_fingerprint") != _SIGNING_FINGERPRINT
    ):
        raise EvidenceError("Claude release lock does not bind the tested binary")

    transport_value = result.get("transport_root")
    if not isinstance(transport_value, str):
        raise EvidenceError("result omits its ephemeral transport directory")
    transport_root = Path(transport_value)
    if (
        not transport_root.is_absolute()
        or transport_root.parent != Path("/tmp")
        or not transport_root.name.startswith("claude-mcp-transport-")
        or result.get("transport_ephemeral") is not True
        or transport_root.exists()
    ):
        raise EvidenceError("ephemeral transport directory was unsafe or retained")

    history, outcomes, provider_port = _check_history(root)
    journal = _check_journal(root, outcomes)
    payments = _check_provider(root, outcomes)
    sessions = _check_streams(root, outcomes)
    processes = _check_processes(
        root, result, claude, relay, sessions, transport_root
    )
    _check_model_requests(root, processes)
    _check_services(root, result, artifacts, provider_port, transport_root)
    _check_private_inputs(root, result, relay, transport_root)
    _check_timeline(result, processes, payments, journal)

    host_events = _json_lines(root, "mcp-host.stderr.log")
    expected_events = ["relay_accept", "relay_disconnect"] * 2
    if (
        [event.get("event") for event in host_events] != expected_events
        or [event.get("pid") for event in host_events]
        != [
            result["relay_peers"][0]["pid"],
            result["relay_peers"][0]["pid"],
            result["relay_peers"][1]["pid"],
            result["relay_peers"][1]["pid"],
        ]
        or any(event.get("uid") != os.geteuid() for event in host_events)
    ):
        raise EvidenceError("trusted MCP host did not observe two exact relay lifetimes")

    for key, name in (
        ("history", "control.history"),
        ("journal", "mcp-calls.jsonl"),
        ("payment_history", "payment.history"),
        ("anthropic_requests", "anthropic-requests.json"),
    ):
        record = artifacts.get(key)
        if (
            not isinstance(record, dict)
            or record.get("path") != os.fspath(root / name)
            or record.get("sha256") != _sha(root / name)
        ):
            raise EvidenceError(f"artifact fingerprint mismatch for {key}")
    if set(result.get("operations", [])) != {
        outcomes["effect-A"]["operation_id"], outcomes["effect-B"]["operation_id"]
    }:
        raise EvidenceError("result Operation summary differs from reconstructed History")
    return {
        "schema": 1,
        "valid": True,
        "claude_version": _CLAUDE_VERSION,
        "claude_processes": 2,
        "source_exit_code": -9,
        "replacement_exit_code": 0,
        "trusted_mcp_hosts": 1,
        "mcp_relay_lifetimes": 2,
        "history_events": len(history),
        "operations": 2,
        "provider_deliveries": 2,
        "provider_commits": 2,
        "credentials_retained": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()
    print(json.dumps(check(args.evidence), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
