"""Independently verify official-Claude Firecracker VMM-loss evidence.

This checker intentionally imports no demo producer code.
"""

from __future__ import annotations

import argparse
import base64
from hashlib import sha256
import json
from pathlib import Path
import stat
import struct
from typing import Any


OFFICIAL_FIRECRACKER_SHA256 = (
    "2fd0171309af7e24cf8dafc8a6f921c1434c49b5f9349bb996b7ed0a4deb8aa7"
)
OFFICIAL_KERNEL_SHA256 = (
    "e20e46d0c36c55c0d1014eb20576171b3f3d922260d9f792017aeff53af3d4f2"
)
OFFICIAL_CLAUDE_SHA256 = (
    "55d281096f57d411ebbdd94dbf5e9ff3accb7c05713e37348c2c11d4b83bf9d9"
)
OFFICIAL_SIGNING_FINGERPRINT = "31DDDE24DDFAB679F42D7BD2BAA929FF1A7ECACE"


class EvidenceError(RuntimeError):
    pass


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise EvidenceError(f"JSON object repeats field {key!r}")
        value[key] = item
    return value


def _loads(data: bytes | str, label: str) -> Any:
    try:
        return json.loads(data, object_pairs_hook=_reject_duplicate_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvidenceError(f"{label} is not valid JSON") from error


def _json(path: Path, label: str) -> Any:
    try:
        data = path.read_bytes()
    except OSError as error:
        raise EvidenceError(f"cannot read {label}: {path}") from error
    return _loads(data, f"{label}: {path}")


def _json_lines(path: Path, label: str) -> list[dict[str, Any]]:
    try:
        lines = path.read_bytes().splitlines()
    except OSError as error:
        raise EvidenceError(f"cannot read {label}: {path}") from error
    records: list[dict[str, Any]] = []
    for ordinal, line in enumerate(lines, 1):
        value = _loads(line, f"{label} line {ordinal}")
        if not isinstance(value, dict):
            raise EvidenceError(f"{label} line {ordinal} is not an object")
        records.append(value)
    return records


def _hash(path: Path) -> str:
    digest = sha256()
    try:
        with path.open("rb") as source:
            while block := source.read(1 << 20):
                digest.update(block)
    except OSError as error:
        raise EvidenceError(f"cannot hash {path}") from error
    return digest.hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=True).encode()


def _protected_identity(effect: str) -> tuple[str, str]:
    request = {
        "schema": 1,
        "name": "commit_effect",
        "kind": "protected_commit",
        "arguments": {"effect_id": effect},
    }
    encoded = _canonical(request)
    call_key = "mcp-call-key-v1:" + sha256(
        b"mcp-operation-identity-v1\0" + encoded
    ).hexdigest()
    request_digest = sha256(b"mcp-protected-call-v2\0" + encoded).hexdigest()
    return call_key, request_digest


def _operation_config_digest(config: dict[str, Any]) -> str:
    tools: list[dict[str, Any]] = []
    for source_tool in config.get("tools", []):
        arguments: list[dict[str, Any]] = []
        for source_argument in source_tool.get("arguments", []):
            argument = {"name": source_argument["name"]}
            if source_argument.get("description"):
                argument["description"] = source_argument["description"]
            argument["type"] = source_argument["type"]
            argument["required"] = source_argument["required"]
            if source_argument.get("max_length"):
                argument["max_length"] = source_argument["max_length"]
            if source_argument.get("enum"):
                argument["enum"] = source_argument["enum"]
            arguments.append(argument)
        tool = {
            "name": source_tool["name"],
            "description": source_tool["description"],
            "kind": source_tool["kind"],
            "arguments": arguments,
        }
        if source_tool.get("identity_arguments"):
            tool["identity_arguments"] = source_tool["identity_arguments"]
        tools.append(tool)
    encoded = _canonical({"schema": config["schema"], "tools": tools})
    return sha256(b"mcp-operation-config-v1\0" + encoded).hexdigest()


def _direct_file(path: Path, label: str) -> None:
    try:
        info = path.lstat()
    except OSError as error:
        raise EvidenceError(f"missing {label}: {path}") from error
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_size <= 0:
        raise EvidenceError(f"{label} is not a nonempty direct regular file")


def _artifact(result: dict[str, Any], name: str, root: Path) -> Path:
    value = result.get("artifacts", {}).get(name)
    if not isinstance(value, dict) or set(value) != {"path", "sha256"}:
        raise EvidenceError(f"top-level artifact {name} is malformed")
    path = Path(value["path"])
    local_names = {
        "history": "control.history",
        "journal": "mcp-calls.jsonl",
        "payment_history": "payment.history",
        "anthropic_requests": "anthropic-requests.json",
    }
    if name in local_names:
        if path.name != local_names[name]:
            raise EvidenceError(f"top-level artifact {name} has an unexpected name")
        path = root / local_names[name]
    _direct_file(path, name)
    if _hash(path) != value["sha256"]:
        raise EvidenceError(f"top-level artifact {name} changed")
    return path


def _history(path: Path) -> list[dict[str, Any]]:
    try:
        data = path.read_bytes()
    except OSError as error:
        raise EvidenceError("cannot read binary History") from error
    records: list[dict[str, Any]] = []
    offset = 0
    while offset < len(data):
        if data[offset : offset + 4] != b"HST1" or offset + 12 > len(data):
            raise EvidenceError("History has a malformed frame header")
        length = struct.unpack(">Q", data[offset + 4 : offset + 12])[0]
        offset += 12
        end = offset + length
        if length == 0 or end > len(data):
            raise EvidenceError("History has a malformed frame length")
        value = _loads(data[offset:end], "History frame")
        if not isinstance(value, dict):
            raise EvidenceError("History frame is not an object")
        records.append(value)
        offset = end
    previous = "0" * 64
    for sequence, record in enumerate(records, 1):
        if (
            record.get("version") != 1
            or record.get("sequence") != sequence
            or record.get("previous_hash") != previous
            or not isinstance(record.get("hash"), str)
            or len(record["hash"]) != 64
        ):
            raise EvidenceError("History sequence or hash links are inconsistent")
        previous = record["hash"]
    return records


def _cell(root: Path, cell: dict[str, Any], generation: int) -> dict[str, Any]:
    expected_label = "source-cell" if generation == 1 else "replacement-cell"
    directory_name = "source" if generation == 1 else "replacement"
    recorded_directory = Path(cell.get("evidence", ""))
    if (
        cell.get("label") != expected_label
        or cell.get("generation") != generation
        or cell.get("exit_code") != 0
        or not recorded_directory.is_absolute()
        or recorded_directory.name != directory_name
    ):
        raise EvidenceError(f"cell {generation} wrapper record is inconsistent")
    directory = root / directory_name
    file_result = _json(directory / "result.json", f"cell {generation} result")
    if file_result != cell.get("result"):
        raise EvidenceError(f"cell {generation} embedded result differs from disk")
    result = file_result
    if (
        result.get("schema") != 1
        or result.get("valid") is not True
        or result.get("backend") != "firecracker-kvm"
        or result.get("firecracker_version") != "1.16.1"
        or result.get("kernel_version") != "6.1.155"
        or result.get("generation") != generation
        or result.get("network_interfaces") != 0
        or result.get("root_block_devices") != 0
        or result.get("read_only_payload") is not True
    ):
        raise EvidenceError(f"cell {generation} isolation contract is false")
    process = result.get("process")
    if (
        not isinstance(process, dict)
        or process.get("generation") != generation
        or process.get("executable_sha256") != OFFICIAL_FIRECRACKER_SHA256
        or not isinstance(process.get("pid"), int)
        or process["pid"] <= 1
        or not isinstance(process.get("start_time_ticks"), int)
        or process["start_time_ticks"] <= 0
        or process.get("started_time_ns", 0) >= process.get("stopped_time_ns", 0)
    ):
        raise EvidenceError(f"cell {generation} VMM identity is malformed")
    artifacts = result.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != {"guest", "initramfs", "kernel", "payload"}:
        raise EvidenceError(f"cell {generation} boot artifacts are incomplete")
    if artifacts["kernel"].get("sha256") != OFFICIAL_KERNEL_SHA256:
        raise EvidenceError(f"cell {generation} used a different kernel")
    for name, artifact in artifacts.items():
        if (
            not isinstance(artifact, dict)
            or not isinstance(artifact.get("sha256"), str)
            or len(artifact["sha256"]) != 64
            or not isinstance(artifact.get("size"), int)
            or artifact["size"] <= 0
        ):
            raise EvidenceError(f"cell {generation} artifact {name} is malformed")

    api = _json_lines(directory / "firecracker-api.jsonl", "Firecracker API")
    if [record.get("path") for record in api] != [
        "/machine-config",
        "/boot-source",
        "/vsock",
        "/drives/payload",
        "/actions",
    ]:
        raise EvidenceError(f"cell {generation} configured an unexpected Firecracker device")
    drive = api[3].get("request", {})
    if drive.get("is_root_device") is not False or drive.get("is_read_only") is not True:
        raise EvidenceError(f"cell {generation} payload drive is not read-only and non-root")
    if any(record.get("status") != 204 for record in api):
        raise EvidenceError(f"cell {generation} has a failed Firecracker API call")

    gate = _json_lines(directory / "gate.jsonl", "Firecracker gate")
    gate_events = [record.get("event") for record in gate]
    expected_gate = ["accept", "ready", "allow", "go"]
    if generation == 2:
        expected_gate += ["accept", "result"]
    if gate_events != expected_gate or any(record.get("pid", process["pid"]) != process["pid"] for record in gate if "pid" in record):
        raise EvidenceError(f"cell {generation} gate is not bound to its VMM")
    for relay_name in ("model-relay.jsonl", "mcp-relay.jsonl"):
        relay = _json_lines(directory / relay_name, relay_name)
        accepts = [record for record in relay if record.get("event") == "accept"]
        byte_events = [record for record in relay if record.get("event") == "bytes"]
        if not accepts or not byte_events or any(record.get("pid") != process["pid"] for record in accepts):
            raise EvidenceError(f"cell {generation} {relay_name} is not VMM-bound")
        if any(record.get("guest_to_host_bytes", 0) <= 0 or record.get("host_to_guest_bytes", 0) <= 0 for record in byte_events):
            raise EvidenceError(f"cell {generation} {relay_name} did not carry bidirectional bytes")
    return result


def check(root: Path) -> dict[str, Any]:
    root = root.resolve()
    info = root.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise EvidenceError("evidence root is not a direct directory")
    result = _json(root / "result.json", "combined result")
    if (
        not isinstance(result, dict)
        or result.get("schema") != 1
        or result.get("valid") is not True
        or result.get("system") != "official-claude-firecracker-vmm-loss-continuity"
        or result.get("claude_version") != "2.1.233"
        or result.get("execution_id") != "claude-mcp-execution-v1"
        or result.get("provider_deliveries") != 2
        or result.get("provider_commits") != 2
        or result.get("mcp_relay_lifetimes") != 2
        or result.get("model_requests") != 4
        or result.get("network_interfaces_per_cell") != 0
        or result.get("root_block_devices_per_cell") != 0
    ):
        raise EvidenceError("combined result contract is false")
    release = result.get("claude_release", {})
    if (
        release.get("version") != "2.1.233"
        or release.get("platform") != "linux-x64"
        or release.get("signing_key_fingerprint") != OFFICIAL_SIGNING_FINGERPRINT
        or release.get("version_output") != "2.1.233 (Claude Code)"
    ):
        raise EvidenceError("Claude signed-release record is wrong")
    artifact_paths = {name: _artifact(result, name, root) for name in result["artifacts"]}
    if result["artifacts"]["claude"]["sha256"] != OFFICIAL_CLAUDE_SHA256:
        raise EvidenceError("combined evidence used a different Claude binary")
    payload_result = _json(artifact_paths["payload_result"], "payload result")
    if (
        payload_result.get("schema") != 1
        or payload_result.get("payload", {}).get("image_sha256") != result["artifacts"]["payload"]["sha256"]
        or payload_result.get("inputs", {}).get("claude", {}).get("sha256") != OFFICIAL_CLAUDE_SHA256
        or payload_result.get("inputs", {}).get("mcp_operation_relay", {}).get("sha256")
        != result["artifacts"]["mcp_relay"]["sha256"]
    ):
        raise EvidenceError("payload result does not bind Claude and the MCP relay")

    cells = result.get("cells")
    if not isinstance(cells, list) or len(cells) != 2:
        raise EvidenceError("combined evidence must contain two cells")
    source = _cell(root, cells[0], 1)
    replacement = _cell(root, cells[1], 2)
    source_process, replacement_process = source["process"], replacement["process"]
    if (
        source.get("disposition") != "vmm-sigkill"
        or source_process.get("termination") != "supervisor"
        or source.get("guest_result") is not None
        or replacement.get("disposition") != "completed"
        or replacement_process.get("termination") not in {"supervisor", "already-exited"}
        or (source_process["pid"], source_process["start_time_ticks"], source_process["instance_id"])
        == (replacement_process["pid"], replacement_process["start_time_ticks"], replacement_process["instance_id"])
        or source.get("session_id") == replacement.get("session_id")
    ):
        raise EvidenceError("source destruction or clean replacement is not proven")
    if source["artifacts"]["payload"]["sha256"] != replacement["artifacts"]["payload"]["sha256"]:
        raise EvidenceError("the two cells did not use the same immutable payload")

    guest_result = replacement.get("guest_result", {})
    body = guest_result.get("body", {})
    stream = body.get("stream")
    if (
        guest_result.get("event") != "RESULT"
        or guest_result.get("status") != 200
        or body.get("result") != "DONE"
        or not isinstance(stream, str)
        or body.get("stream_bytes") != len(stream)
        or body.get("stream_sha256") != sha256(stream.encode()).hexdigest()
    ):
        raise EvidenceError("replacement authenticated result is inconsistent")
    stream_records = []
    for ordinal, line in enumerate(stream.splitlines(), 1):
        stream_records.append(_loads(line, f"replacement Claude stream line {ordinal}"))
    system = [record for record in stream_records if record.get("type") == "system"]
    final = [record for record in stream_records if record.get("type") == "result"]
    effects = [
        block.get("input", {}).get("effect_id")
        for record in stream_records
        for block in record.get("message", {}).get("content", [])
        if block.get("type") == "tool_use"
    ]
    if (
        len(system) != 1
        or system[0].get("claude_code_version") != "2.1.233"
        or system[0].get("mcp_servers") != [{"name": "continuity", "status": "connected"}]
        or effects != ["effect-A", "effect-B"]
        or len(final) != 1
        or final[0].get("subtype") != "success"
        or final[0].get("result") != "DONE"
    ):
        raise EvidenceError("replacement did not run the official two-effect Claude workload")
    source_console = (root / "source" / "firecracker.log").read_text(encoding="utf-8", errors="replace")
    if '"effect_id":"effect-A"' not in source_console or '"type":"tool_result"' in source_console:
        raise EvidenceError("source VM was not lost between tool request and result")

    inflight = result.get("inflight", {})
    ordered = [
        inflight.get("provider_commit_observed_time_ns"),
        inflight.get("source_vmm_sigkill_time_ns"),
        inflight.get("provider_release_time_ns"),
        inflight.get("journal_completed_time_ns"),
    ]
    if any(not isinstance(value, int) or value <= 0 for value in ordered) or ordered != sorted(ordered) or len(set(ordered)) != 4:
        raise EvidenceError("in-flight fault timeline is not strictly ordered")

    payments = _json_lines(artifact_paths["payment_history"], "payment history")
    operations = result.get("operations")
    if (
        not isinstance(operations, list)
        or len(operations) != 2
        or len(set(operations)) != 2
        or {payment.get("operation_id") for payment in payments} != set(operations)
        or any(payment.get("path") != "/v1/charge" for payment in payments)
    ):
        raise EvidenceError("provider history does not prove exactly two unique commits")
    journal = _json_lines(artifact_paths["journal"], "MCP journal")
    journal_schema = journal[0].get("schema") if journal else None
    tools_config = _json(artifact_paths["tools_config"], "tools config")
    if not isinstance(tools_config, dict) or tools_config.get("schema") != journal_schema:
        raise EvidenceError("MCP journal and tools config use different schemas")
    config_digest = _operation_config_digest(tools_config) if journal_schema == 2 else ""
    if (
        [record.get("event") for record in journal] != ["prepared", "completed", "prepared", "completed"]
        or [record.get("call_sequence") for record in journal] != [1, 1, 2, 2]
        or any(record.get("execution_id") != "claude-mcp-execution-v1" for record in journal)
        or journal_schema not in {1, 2}
        or any(record.get("schema") != journal_schema for record in journal)
    ):
        raise EvidenceError("MCP journal lifecycle is not exactly two calls")
    journal_operations = []
    previous = ""
    for index, record in enumerate(journal, 1):
        call_sequence = (index + 1) // 2
        effect = ("effect-A", "effect-B")[call_sequence - 1]
        call_key, request_digest = _protected_identity(effect)
        call_id = (
            f"mcp-call-v1:23:claude-mcp-execution-v1:{call_sequence}"
            if journal_schema == 1
            else "mcp-call-v2:23:claude-mcp-execution-v1:"
            + call_key.removeprefix("mcp-call-key-v1:")
        )
        if (
            record.get("record_sequence") != index
            or record.get("rpc_id") != str(call_sequence + 1)
            or record.get("request_digest") != request_digest
            or record.get("call_id") != call_id
            or (journal_schema == 1 and "config_digest" in record)
            or (journal_schema == 2 and record.get("config_digest") != config_digest)
            or record.get("uncertain") is not False
            or record.get("previous_hash", "") != previous
            or (journal_schema == 1 and "call_key" in record)
            or (journal_schema == 2 and record.get("call_key") != call_key)
        ):
            raise EvidenceError(f"MCP journal identity fails at record {index}")
        payload = {key: value for key, value in record.items() if key != "hash"}
        expected_hash = sha256(_canonical(payload)).hexdigest()
        if record.get("hash") != expected_hash:
            raise EvidenceError(f"MCP journal hash fails at record {index}")
        if index % 2:
            if "response" in record:
                raise EvidenceError("prepared MCP journal record contains a response")
        else:
            try:
                response = _loads(
                    base64.b64decode(record["response"], validate=True),
                    "MCP completed response",
                )
                if response.get("id") != (call_sequence + 1 if journal_schema == 1 else None):
                    raise EvidenceError("MCP saved response has the wrong RPC binding")
                journal_operations.append(response["result"]["structuredContent"]["operation_id"])
            except (KeyError, TypeError, ValueError) as error:
                raise EvidenceError("MCP completed response is malformed") from error
        previous = expected_hash
    if set(journal_operations) != set(operations) or len(journal_operations) != 2:
        raise EvidenceError("MCP journal and provider operations differ")

    history = _history(artifact_paths["history"])
    prepared = [record for record in history if record.get("operation") == "operation.prepared"]
    succeeded = [
        record
        for record in history
        if record.get("operation") == "operation.phase"
        and record.get("data", {}).get("update", {}).get("phase") == "succeeded"
    ]
    if (
        len(prepared) != 2
        or len(succeeded) != 2
        or {record["data"]["operation"]["id"] for record in prepared} != set(operations)
        or {record["data"]["id"] for record in succeeded} != set(operations)
    ):
        raise EvidenceError("History does not contain two prepared-to-succeeded Operations")

    model_requests = _json(artifact_paths["anthropic_requests"], "Anthropic requests")
    if not isinstance(model_requests, list) or len(model_requests) != 4:
        raise EvidenceError("model fixture did not observe four ordered requests")
    return {
        "valid": True,
        "system": result["system"],
        "claude_version": result["claude_version"],
        "source_vmm_pid": source_process["pid"],
        "replacement_vmm_pid": replacement_process["pid"],
        "provider_commits": len(payments),
        "operations": operations,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()
    try:
        summary = check(args.evidence)
    except (EvidenceError, OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
