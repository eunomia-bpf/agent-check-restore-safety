"""Offline structural checker for the real Codex MCP continuity run."""

from __future__ import annotations

import argparse
import base64
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
from typing import Any


class EvidenceError(RuntimeError):
    pass


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in items:
        if name in result:
            raise EvidenceError(f"duplicate JSON member {name!r}")
        result[name] = value
    return result


def _decode(data: bytes, label: str) -> Any:
    try:
        return json.loads(data, object_pairs_hook=_pairs)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise EvidenceError(f"{label} is not strict JSON") from error


def _private_root(path: Path) -> Path:
    root = path.resolve(strict=True)
    info = root.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise EvidenceError("evidence root must be a current-user directory with mode 0700")
    return root


def _file(root: Path, name: str, *, mode: int | None = None) -> Path:
    path = root / name
    if path.parent != root:
        raise EvidenceError("invalid evidence filename")
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or info.st_uid != os.geteuid()
        or info.st_size <= 0
        or stat.S_IMODE(info.st_mode) & 0o022
        or (mode is not None and stat.S_IMODE(info.st_mode) != mode)
    ):
        raise EvidenceError(f"unsafe evidence file {name}")
    return path


def _sha(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        while block := source.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


def _json_file(root: Path, name: str, *, mode: int | None = None) -> Any:
    path = _file(root, name, mode=mode)
    return _decode(path.read_bytes(), name)


def _json_lines(root: Path, name: str, *, mode: int | None = None) -> list[dict[str, Any]]:
    path = _file(root, name, mode=mode)
    records: list[dict[str, Any]] = []
    for index, line in enumerate(path.read_bytes().splitlines(), start=1):
        value = _decode(line, f"{name}:{index}")
        if not isinstance(value, dict):
            raise EvidenceError(f"{name}:{index} is not an object")
        records.append(value)
    if not records:
        raise EvidenceError(f"{name} is empty")
    return records


def _external_artifact(
    artifacts: dict[str, Any], key: str, *, executable: bool
) -> Path:
    artifact = artifacts.get(key)
    value = artifact.get("path") if isinstance(artifact, dict) else None
    if not isinstance(value, str):
        raise EvidenceError(f"result omits {key} artifact path")
    path = Path(value)
    try:
        resolved = path.resolve(strict=True)
        info = path.lstat()
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
        or artifact.get("sha256") != _sha(path)
    ):
        raise EvidenceError(f"unsafe or changed {key} artifact")
    return path


def _journal(root: Path, execution_id: str) -> list[dict[str, Any]]:
    records = _json_lines(root, "mcp-calls.jsonl", mode=0o600)
    if len(records) != 4:
        raise EvidenceError(f"journal has {len(records)} records instead of four")
    previous = ""
    for index, record in enumerate(records, start=1):
        expected_call = (index + 1) // 2
        expected_event = "prepared" if index % 2 else "completed"
        expected_rpc = str(expected_call + 1)
        if (
            record.get("schema") != 1
            or record.get("record_sequence") != index
            or record.get("call_sequence") != expected_call
            or record.get("event") != expected_event
            or record.get("execution_id") != execution_id
            or record.get("rpc_id") != expected_rpc
            or record.get("call_id")
            != f"mcp-call-v1:{len(execution_id)}:{execution_id}:{expected_call}"
            or record.get("uncertain") is not False
            or record.get("previous_hash", "") != previous
        ):
            raise EvidenceError(f"journal lifecycle mismatch at record {index}")
        payload: dict[str, Any] = {
            "schema": record["schema"],
            "record_sequence": record["record_sequence"],
            "call_sequence": record["call_sequence"],
            "event": record["event"],
            "execution_id": record["execution_id"],
            "rpc_id": record["rpc_id"],
            "request_digest": record["request_digest"],
            "call_id": record["call_id"],
        }
        if "response" in record:
            payload["response"] = record["response"]
        payload["uncertain"] = record["uncertain"]
        if "previous_hash" in record:
            payload["previous_hash"] = record["previous_hash"]
        encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode()
        expected_hash = sha256(encoded).hexdigest()
        if record.get("hash") != expected_hash:
            raise EvidenceError(f"journal hash mismatch at record {index}")
        if expected_event == "prepared" and "response" in record:
            raise EvidenceError("prepared journal record contains a response")
        if expected_event == "completed" and not isinstance(record.get("response"), str):
            raise EvidenceError("completed journal record omits its response")
        previous = expected_hash
    return records


def _mcp_items(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    items: list[dict[str, Any]] = []
    versions: list[str] = []
    for record in records:
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue
        if payload.get("method") == "mcpServer/elicitation/request":
            raise EvidenceError("Codex requested interactive approval")
        if payload.get("method") == "mcpServer/startupStatus/updated":
            params = payload.get("params")
            if isinstance(params, dict) and params.get("status") == "ready":
                if params.get("name") != "continuity" or not isinstance(params.get("threadId"), str):
                    raise EvidenceError("malformed MCP ready event")
        if payload.get("method") == "thread/started":
            params = payload.get("params")
            thread = params.get("thread") if isinstance(params, dict) else None
            version = thread.get("cliVersion") if isinstance(thread, dict) else None
            if isinstance(version, str):
                versions.append(version)
        if payload.get("method") != "item/completed":
            continue
        params = payload.get("params")
        item = params.get("item") if isinstance(params, dict) else None
        if isinstance(item, dict) and item.get("type") == "mcpToolCall":
            items.append(item)
    return items, versions


def _process_command(records: list[dict[str, Any]], label: str) -> list[str]:
    commands = [
        payload.get("command")
        for record in records
        for payload in [record.get("payload")]
        if record.get("direction") == "meta"
        and isinstance(payload, dict)
        and payload.get("event") == "process_start"
    ]
    if (
        len(commands) != 1
        or not isinstance(commands[0], list)
        or not commands[0]
        or not all(isinstance(item, str) and item for item in commands[0])
    ):
        raise EvidenceError(f"{label} log does not contain one valid process command")
    return commands[0]


def _check_codex_relay_command(
    command: list[str], *, codex: Path, relay: Path, socket_path: Path
) -> None:
    expected_mcp = (
        "mcp_servers.continuity={"
        f"command={json.dumps(os.fspath(relay), ensure_ascii=True)},"
        f"args=[\"-socket\",{json.dumps(os.fspath(socket_path), ensure_ascii=True)}],"
        "startup_timeout_sec=10,tool_timeout_sec=60,enabled=true,required=true,"
        "enabled_tools=[\"commit_effect\"],default_tools_approval_mode=\"approve\","
        "tools={\"commit_effect\"={approval_mode=\"approve\"}}}"
    )
    overrides = [
        command[index + 1]
        for index, item in enumerate(command[:-1])
        if item == "-c"
    ]
    joined = "\x00".join(command)
    forbidden = (
        "-config",
        "-sandbox-socket",
        "-listen-socket",
        "-execution-id",
        "-journal",
        "mcp-operation-host",
    )
    if (
        command[0] != os.fspath(codex)
        or command[1:3] != ["app-server", "--stdio"]
        or overrides.count("mcp_servers={}") != 1
        or overrides.count(expected_mcp) != 1
        or sum(value.startswith("mcp_servers.continuity=") for value in overrides) != 1
        or any(value in joined for value in forbidden)
    ):
        raise EvidenceError("Codex was not connected through the bounded untrusted relay")


def _check_host_events(
    records: list[dict[str, Any]], *, host_pid: int
) -> None:
    expected = ["relay_accept", "relay_disconnect"] * 2
    if [record.get("event") for record in records] != expected:
        raise EvidenceError("trusted MCP host did not retain exactly two relay lifetimes")
    pids = [record.get("pid") for record in records]
    uids = [record.get("uid") for record in records]
    if (
        not all(isinstance(pid, int) and pid > 1 and pid != host_pid for pid in pids)
        or pids[0] != pids[1]
        or pids[2] != pids[3]
        or pids[0] == pids[2]
        or uids != [os.geteuid()] * 4
    ):
        raise EvidenceError("trusted MCP host peer credentials are inconsistent")


def _outcome(item: dict[str, Any], effect: str) -> dict[str, Any]:
    result = item.get("result")
    structured = result.get("structuredContent") if isinstance(result, dict) else None
    if (
        item.get("server") != "continuity"
        or item.get("tool") != "commit_effect"
        or item.get("arguments") != {"effect_id": effect}
        or item.get("status") != "completed"
        or item.get("error") is not None
        or not isinstance(structured, dict)
        or structured.get("schema") != 1
        or structured.get("phase") != "succeeded"
        or structured.get("execution_fenced") is not False
    ):
        raise EvidenceError(f"unsuccessful Codex MCP item for {effect}")
    return structured


def check(path: Path) -> dict[str, Any]:
    root = _private_root(path)
    result = _json_file(root, "result.json", mode=0o600)
    if (
        not isinstance(result, dict)
        or result.get("schema") != 1
        or result.get("success") is not True
        or result.get("system") != "real-codex-split-mcp-continuity"
        or result.get("codex_processes") != 2
        or result.get("trusted_mcp_hosts") != 1
        or result.get("mcp_relay_connections") != 2
    ):
        raise EvidenceError("result does not report a successful schema-1 run")
    execution_id = result.get("execution_id")
    if not isinstance(execution_id, str):
        raise EvidenceError("result omits execution identity")
    artifacts = result.get("artifacts")
    if not isinstance(artifacts, dict):
        raise EvidenceError("result omits artifact fingerprints")
    codex = _external_artifact(artifacts, "codex", executable=True)
    host = _external_artifact(artifacts, "mcp_host", executable=True)
    relay = _external_artifact(artifacts, "mcp_relay", executable=True)
    tools_config = _external_artifact(artifacts, "tools_config", executable=False)
    first_records = _json_lines(root, "codex-first.jsonl")
    second_records = _json_lines(root, "codex-second.jsonl")
    relay_socket = root / "relay" / "mcp-host.sock"
    _check_codex_relay_command(
        _process_command(first_records, "first Codex"),
        codex=codex,
        relay=relay,
        socket_path=relay_socket,
    )
    _check_codex_relay_command(
        _process_command(second_records, "second Codex"),
        codex=codex,
        relay=relay,
        socket_path=relay_socket,
    )
    host_process = _json_file(root, "mcp-host-process.json", mode=0o600)
    host_pid = host_process.get("pid") if isinstance(host_process, dict) else None
    host_command = host_process.get("command") if isinstance(host_process, dict) else None
    sandbox_name = "sandbox-" + sha256(b"codex-mcp").hexdigest()[:32] + ".sock"
    expected_host_command = [
        os.fspath(host),
        "-config",
        os.fspath(tools_config),
        "-sandbox-socket",
        os.fspath(root / "sockets" / sandbox_name),
        "-listen-socket",
        os.fspath(relay_socket),
        "-execution-id",
        execution_id,
        "-journal",
        os.fspath(root / "mcp-calls.jsonl"),
    ]
    if not isinstance(host_pid, int) or host_pid <= 1 or host_command != expected_host_command:
        raise EvidenceError("trusted MCP host process boundary is malformed")
    host_records = _json_lines(root, "mcp-host.stderr.log", mode=0o600)
    _check_host_events(host_records, host_pid=host_pid)
    if result.get("relay_events") != host_records:
        raise EvidenceError("result relay summary differs from the trusted host log")
    first_items, first_versions = _mcp_items(first_records)
    second_items, second_versions = _mcp_items(second_records)
    if len(first_items) != 1 or len(second_items) != 2:
        raise EvidenceError("raw App Server logs do not contain one then two MCP calls")
    first_a = _outcome(first_items[0], "effect-A")
    replay_a = _outcome(second_items[0], "effect-A")
    second_b = _outcome(second_items[1], "effect-B")
    if (
        first_a != replay_a
        or first_a.get("recovered_by_query") is not True
        or second_b.get("recovered_by_query") is not False
        or not first_versions
        or not second_versions
        or first_versions[-1] != second_versions[-1]
    ):
        raise EvidenceError("Codex restart did not return the exact recovered result")

    journal = _journal(root, execution_id)
    journal_outcomes: list[dict[str, Any]] = []
    for record in (journal[1], journal[3]):
        response = _decode(base64.b64decode(record["response"], validate=True), "journal response")
        outcome = response.get("result", {}).get("structuredContent") if isinstance(response, dict) else None
        if not isinstance(outcome, dict):
            raise EvidenceError("journal response omits structured outcome")
        journal_outcomes.append(outcome)
    if journal_outcomes != [first_a, second_b]:
        raise EvidenceError("journal responses differ from Codex-observed results")

    discovery = _json_file(root, "discovery-request.json", mode=0o600)
    metadata = discovery.get("client_metadata") if isinstance(discovery, dict) else None
    encoded = metadata.get("x-codex-turn-metadata") if isinstance(metadata, dict) else None
    turn_metadata = _decode(encoded.encode(), "Codex turn metadata") if isinstance(encoded, str) else None
    names = turn_metadata.get("code_mode_tool_names") if isinstance(turn_metadata, dict) else None
    expected_name = {"name": "commit_effect", "namespace": "mcp__continuity"}
    if not isinstance(names, dict) or names.get("mcp__continuity__commit_effect") != expected_name:
        raise EvidenceError("model request did not expose the protected MCP code-mode tool")
    responses = _json_file(root, "responses.json", mode=0o600)
    if not isinstance(responses, list) or len(responses) != 7:
        raise EvidenceError("evidence does not contain seven model requests")
    replay_threads: set[str] = set()
    second_threads: set[str] = set()
    for request in responses:
        body = request.get("body") if isinstance(request, dict) else None
        metadata = body.get("client_metadata") if isinstance(body, dict) else None
        thread_id = metadata.get("thread_id") if isinstance(metadata, dict) else None
        encoded_body = json.dumps(body, separators=(",", ":"), ensure_ascii=True)
        if "stable-model-call-A" in encoded_body and isinstance(thread_id, str):
            replay_threads.add(thread_id)
        if "stable-model-call-B" in encoded_body and isinstance(thread_id, str):
            second_threads.add(thread_id)
    if len(replay_threads) != 2 or len(second_threads) != 1 or not second_threads < replay_threads:
        raise EvidenceError("stable model call A was not replayed across two Codex threads")

    state = result.get("history")
    operations = state.get("operations") if isinstance(state, dict) else None
    payment = result.get("payment")
    if (
        state.get("history", {}).get("sequence") != 8
        or not isinstance(operations, dict)
        or len(operations) != 2
        or payment != {"deliveries": 2, "commits": 2, "paths": {"/v1/charge": 2}}
    ):
        raise EvidenceError("History or payment cardinality is wrong")
    bodies: dict[str, dict[str, Any]] = {}
    for operation in operations.values():
        if not isinstance(operation, dict) or not isinstance(operation.get("request_body"), str):
            raise EvidenceError("malformed retained Operation")
        body = _decode(base64.b64decode(operation["request_body"], validate=True), "Operation body")
        effect = body.get("effect_id") if isinstance(body, dict) else None
        if not isinstance(effect, str):
            raise EvidenceError("Operation body omits effect identity")
        bodies[effect] = operation
    if (
        set(bodies) != {"effect-A", "effect-B"}
        or bodies["effect-A"].get("settlement") != "query"
        or "settlement" in bodies["effect-B"]
        or bodies["effect-A"].get("id") != first_a.get("operation_id")
        or bodies["effect-B"].get("id") != second_b.get("operation_id")
    ):
        raise EvidenceError("History operations do not match MCP results")
    payment_records = _json_lines(root, "payment.history", mode=0o600)
    if {record.get("operation_id") for record in payment_records} != {
        first_a.get("operation_id"), second_b.get("operation_id")
    }:
        raise EvidenceError("external payment commits differ from History")

    for key, name in (
        ("mcp_host_process", "mcp-host-process.json"),
        ("mcp_host_log", "mcp-host.stderr.log"),
        ("journal", "mcp-calls.jsonl"),
        ("first_raw", "codex-first.jsonl"),
        ("second_raw", "codex-second.jsonl"),
        ("responses", "responses.json"),
    ):
        artifact = artifacts.get(key)
        if not isinstance(artifact, dict) or artifact.get("path") != os.fspath(root / name) or artifact.get("sha256") != _sha(root / name):
            raise EvidenceError(f"artifact fingerprint mismatch for {key}")
    return {
        "schema": 1,
        "valid": True,
        "codex_version": first_versions[-1],
        "codex_processes": 2,
        "trusted_mcp_hosts": 1,
        "mcp_relay_connections": 2,
        "mcp_items": 3,
        "operations": 2,
        "provider_deliveries": 2,
        "provider_commits": 2,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()
    print(json.dumps(check(args.evidence), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
