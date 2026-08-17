"""Independently verify Firecracker-to-DeathStarBench recovery evidence.

This checker deliberately imports no experiment producer code.  It reconstructs
operation identities, validates the append-only History, and cross-checks the
application audit, Firecracker records, Claude streams, and comparison matrix.
"""

from __future__ import annotations

import argparse
import base64
from hashlib import sha256
import json
from pathlib import Path
import re
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
DEATHSTAR_COMMIT = "6ecb09706140f8730b5385c08f1386c654c3c526"
DEATHSTAR_TREE = "0ac0fd6d4ccfa1472d3895384d45fef5c6246b03"
BODY = {
    "hotel_id": "1",
    "in_date": "2015-04-09",
    "out_date": "2015-04-10",
    "password": "0000000000",
    "rooms": 1,
    "username": "Cornell_30",
}
HEX32 = re.compile(r"[0-9a-f]{32}")
HEX64 = re.compile(r"[0-9a-f]{64}")


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
        return _loads(path.read_bytes(), f"{label}: {path}")
    except OSError as error:
        raise EvidenceError(f"cannot read {label}: {path}") from error


def _json_lines(path: Path, label: str) -> list[dict[str, Any]]:
    try:
        lines = path.read_bytes().splitlines()
    except OSError as error:
        raise EvidenceError(f"cannot read {label}: {path}") from error
    result: list[dict[str, Any]] = []
    for ordinal, line in enumerate(lines, 1):
        value = _loads(line, f"{label} line {ordinal}")
        if not isinstance(value, dict):
            raise EvidenceError(f"{label} line {ordinal} is not an object")
        result.append(value)
    return result


def _hash(path: Path) -> str:
    digest = sha256()
    try:
        with path.open("rb") as source:
            while block := source.read(1 << 20):
                digest.update(block)
    except OSError as error:
        raise EvidenceError(f"cannot hash {path}") from error
    return digest.hexdigest()


def _direct_file(path: Path, label: str) -> None:
    try:
        info = path.lstat()
    except OSError as error:
        raise EvidenceError(f"missing {label}: {path}") from error
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_size <= 0:
        raise EvidenceError(f"{label} is not a nonempty direct regular file")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()


def _route_call_id(key: str) -> str:
    return f"effect-route-idempotency-v1:7:reserve:{key}"


def _operation_id(key: str) -> str:
    digest = sha256(
        b"sandbox-operation-id-v2\0"
        + b"firecracker-deathstar-egress\0claude-http\0"
        + _route_call_id(key).encode()
    ).hexdigest()
    return "op-" + digest


def _request_hash(operation: dict[str, Any], body: bytes) -> str:
    headers = (
        ("accept-encoding", "identity"),
        ("idempotency-key", operation["id"]),
        ("user-agent", "safe-change-runtime/1"),
        ("x-operation-id", operation["id"]),
    )
    digest = sha256()
    digest.update(operation["method"].encode() + b"\0")
    digest.update(operation["target"].encode() + b"\0")
    for name, value in headers:
        digest.update(name.encode() + b":" + value.encode() + b"\0")
    digest.update(body)
    return digest.hexdigest()


def _history(path: Path) -> list[dict[str, Any]]:
    _direct_file(path, "History")
    data = path.read_bytes()
    records: list[dict[str, Any]] = []
    offset = 0
    previous = "0" * 64
    while offset < len(data):
        if offset + 12 > len(data) or data[offset : offset + 4] != b"HST1":
            raise EvidenceError("History has a malformed frame header")
        length = struct.unpack(">Q", data[offset + 4 : offset + 12])[0]
        offset += 12
        end = offset + length
        if length == 0 or end > len(data):
            raise EvidenceError("History has a malformed frame length")
        payload = data[offset:end]
        record = _loads(payload, "History frame")
        if not isinstance(record, dict) or _canonical(record) != payload:
            raise EvidenceError("History frame is not a canonical object")
        sequence = len(records) + 1
        if (
            record.get("version") != 1
            or record.get("sequence") != sequence
            or record.get("previous_hash") != previous
            or not isinstance(record.get("operation"), str)
            or not isinstance(record.get("data"), dict)
            or not isinstance(record.get("hash"), str)
        ):
            raise EvidenceError("History sequence or links are inconsistent")
        digest = sha256()
        digest.update(b"history-event-v1\0")
        digest.update(struct.pack(">Q", sequence))
        for part in (
            previous.encode(),
            record["operation"].encode(),
            _canonical(record["data"]),
        ):
            digest.update(struct.pack(">Q", len(part)))
            digest.update(part)
        if record["hash"] != digest.hexdigest():
            raise EvidenceError(f"History event {sequence} has a false hash")
        previous = record["hash"]
        records.append(record)
        offset = end
    if not records:
        raise EvidenceError("History is empty")
    return records


def _stream(cell: dict[str, Any], label: str, operation_id: str, protected: bool) -> None:
    guest = cell.get("guest_result", {})
    body = guest.get("body", {})
    stream = body.get("stream")
    if (
        guest.get("event") != "RESULT"
        or guest.get("status") != 200
        or body.get("result") != "DONE"
        or not isinstance(stream, str)
        or body.get("stream_bytes") != len(stream.encode())
        or body.get("stream_sha256") != sha256(stream.encode()).hexdigest()
    ):
        raise EvidenceError(f"{label} has no authenticated successful Claude result")
    records = [_loads(line, f"{label} Claude stream") for line in stream.splitlines()]
    systems = [record for record in records if record.get("type") == "system" and record.get("subtype") == "init"]
    finals = [record for record in records if record.get("type") == "result"]
    uses = [
        block
        for record in records
        for block in record.get("message", {}).get("content", [])
        if block.get("type") == "tool_use"
    ]
    tool_results = [
        block
        for record in records
        for block in record.get("message", {}).get("content", [])
        if block.get("type") == "tool_result"
    ]
    if (
        len(systems) != 1
        or systems[0].get("claude_code_version") != "2.1.233"
        or len(finals) != 1
        or finals[0].get("subtype") != "success"
        or finals[0].get("result") != "DONE"
        or len(uses) != 1
        or uses[0].get("name") != "Bash"
        or len(tool_results) != 1
    ):
        raise EvidenceError(f"{label} did not run one ordinary Bash action to completion")
    command = uses[0].get("input", {}).get("command", "")
    if (
        "$SAFE_CHANGE_EGRESS_URL" not in command
        or "$SAFE_CHANGE_CALL_ID" not in command
        or json.dumps(BODY, sort_keys=True, separators=(",", ":")) not in command
        or "mcp__continuity__" in stream
    ):
        raise EvidenceError(f"{label} did not use the fixed ordinary HTTP workload")
    content = _loads(tool_results[0].get("content", ""), f"{label} Bash result")
    if protected:
        if (
            content.get("operation_id") != operation_id
            or content.get("phase") != "succeeded"
            or content.get("recovered_by_query") is not True
        ):
            raise EvidenceError(f"{label} did not recover the protected operation by query")
    elif content.get("operation_id") != operation_id or content.get("outcome") != "succeeded":
        raise EvidenceError(f"{label} raw HTTP response is inconsistent")


def _cell(
    runtime: Path,
    wrapper: dict[str, Any],
    *,
    label: str,
    generation: int,
    key: str,
    complete: bool,
    protected: bool,
    artifact_hashes: dict[str, str],
) -> dict[str, Any]:
    if (
        wrapper.get("label") != label
        or wrapper.get("generation") != generation
        or wrapper.get("exit_code") != 0
        or Path(wrapper.get("evidence", "")).name != label
    ):
        raise EvidenceError(f"{label} wrapper is inconsistent")
    directory = runtime / "cells" / label
    result = _json(directory / "result.json", f"{label} result")
    if result != wrapper.get("result"):
        raise EvidenceError(f"{label} embedded result differs from disk")
    if (
        result.get("schema") != 1
        or result.get("valid") is not True
        or result.get("backend") != "firecracker-kvm"
        or result.get("firecracker_version") != "1.16.1"
        or result.get("kernel_version") != "6.1.155"
        or result.get("generation") != generation
        or result.get("session_id") != key
        or result.get("tool_profile") != "http"
        or result.get("network_interfaces") != 0
        or result.get("root_block_devices") != 0
        or result.get("read_only_payload") is not True
    ):
        raise EvidenceError(f"{label} isolation contract is false")
    process = result.get("process", {})
    if (
        process.get("executable_sha256") != OFFICIAL_FIRECRACKER_SHA256
        or process.get("generation") != generation
        or not isinstance(process.get("pid"), int)
        or process.get("pid", 0) <= 1
        or not isinstance(process.get("start_time_ticks"), int)
        or process.get("start_time_ticks", 0) <= 0
        or process.get("started_time_ns", 0) >= process.get("stopped_time_ns", 0)
        or process.get("termination") != "supervisor"
    ):
        raise EvidenceError(f"{label} VMM identity is malformed")
    artifacts = result.get("artifacts", {})
    if (
        set(artifacts) != {"guest", "initramfs", "kernel", "payload"}
        or artifacts["kernel"].get("sha256") != OFFICIAL_KERNEL_SHA256
        or artifacts["payload"].get("sha256") != artifact_hashes.get("payload")
        or artifacts["guest"].get("sha256") != artifact_hashes.get("guest")
    ):
        raise EvidenceError(f"{label} boot artifacts are inconsistent")
    api = _json_lines(directory / "firecracker-api.jsonl", f"{label} Firecracker API")
    if [record.get("path") for record in api] != [
        "/machine-config",
        "/boot-source",
        "/vsock",
        "/drives/payload",
        "/actions",
    ] or any(record.get("status") != 204 for record in api):
        raise EvidenceError(f"{label} configured unexpected Firecracker devices")
    drive = api[3].get("request", {})
    if drive.get("is_root_device") is not False or drive.get("is_read_only") is not True:
        raise EvidenceError(f"{label} payload drive is not read-only and non-root")
    config = _json(directory / "guest-config.json", f"{label} guest config")
    if (
        config.get("schema") != 2
        or config.get("session_id") != key
        or config.get("profile") != "http"
        or config.get("egress_port") != 7003
        or config.get("claude_sha256") != OFFICIAL_CLAUDE_SHA256
        or config.get("busybox_sha256") != artifact_hashes.get("busybox")
        or config.get("bash_sha256") != artifact_hashes.get("bash")
    ):
        raise EvidenceError(f"{label} guest configuration is inconsistent")
    relay = _json_lines(directory / "egress-relay.jsonl", f"{label} HTTP relay")
    accepts = [record for record in relay if record.get("event") == "accept"]
    byte_events = [record for record in relay if record.get("event") == "bytes"]
    if (
        len(accepts) != 1
        or len(byte_events) != 1
        or accepts[0].get("pid") != process.get("pid")
        or byte_events[0].get("guest_to_host_bytes", 0) <= 0
    ):
        raise EvidenceError(f"{label} HTTP relay is not bound to its VMM")
    if complete:
        if byte_events[0].get("host_to_guest_bytes", 0) <= 0 or result.get("disposition") != "completed":
            raise EvidenceError(f"{label} did not receive its HTTP result")
    elif byte_events[0].get("host_to_guest_bytes") != 0 or result.get("disposition") != "vmm-sigkill" or result.get("guest_result") is not None:
        raise EvidenceError(f"{label} was not lost after request and before response")
    if complete:
        _stream(result, label, _operation_id(key) if protected else key, protected)
    else:
        console = (directory / "firecracker.log").read_text(encoding="utf-8", errors="replace")
        if '"claude_code_version":"2.1.233"' not in console or '"name":"Bash"' not in console or '"type":"tool_result"' in console:
            raise EvidenceError(f"{label} was not killed during the official Claude Bash call")
    return result


def check(root: Path, expected_repetitions: int) -> dict[str, Any]:
    root = root.resolve()
    try:
        info = root.lstat()
    except OSError as error:
        raise EvidenceError(f"cannot inspect evidence root: {root}") from error
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise EvidenceError("evidence root is not a direct directory")
    runtime = root / "runtime"
    result = _json(runtime / "result.json", "runtime result")
    driver = _json(root / "driver-result.json", "driver result")
    driver_without_path = dict(driver)
    driver_without_path.pop("evidence", None)
    if driver_without_path != result or Path(driver.get("evidence", "")).name != "runtime":
        raise EvidenceError("driver and archived runtime results differ")
    if (
        result.get("schema") != 1
        or result.get("valid") is not True
        or result.get("system") != "official-claude-firecracker-deathstar-http-egress"
        or result.get("repetitions") != expected_repetitions
        or result.get("network_interfaces_per_cell") != 0
        or result.get("root_block_devices_per_cell") != 0
        or result.get("model_requests") != expected_repetitions * 6 + 1
        or result.get("mongo_observations") != expected_repetitions * 6 + 1
        or result.get("transparency") != {
            "claude_source_modified": False,
            "deathstar_source_modified": False,
            "operator_route_registered": True,
        }
    ):
        raise EvidenceError("runtime result contract is false")
    graph = _json(root / "graph.json", "application graph")
    if graph != result.get("graph") or (
        graph.get("schema") != 1
        or graph.get("repository") != "https://github.com/delimitrou/DeathStarBench.git"
        or graph.get("tag") != "hotelReservation-0.3.5"
        or graph.get("commit") != DEATHSTAR_COMMIT
        or graph.get("tree") != DEATHSTAR_TREE
        or graph.get("official_services") != 24
        or graph.get("official_compose_running") != 23
        or graph.get("compose_frontend_scaled_to_zero") is not True
        or graph.get("custom_unmodified_frontend_running") is not True
        or graph.get("source_modified") is not False
        or graph.get("pass") is not True
    ):
        raise EvidenceError("DeathStarBench graph provenance is false")
    hashes = result.get("artifacts", {})
    if (
        not isinstance(hashes, dict)
        or any(not isinstance(value, str) or HEX64.fullmatch(value) is None for value in hashes.values())
        or hashes.get("claude") != OFFICIAL_CLAUDE_SHA256
        or _hash(runtime / "control.history") != hashes.get("history")
        or _hash(root / "deathstar-adapter.audit.jsonl") != hashes.get("adapter_audit")
        or _hash(runtime / "observer-facts.json") != hashes.get("observer_facts")
    ):
        raise EvidenceError("recorded artifact hashes are inconsistent")
    route = _json(runtime / "effect-route.json", "effect route")
    if (
        route.get("schema") != 2
        or len(route.get("routes", [])) != 1
        or {key: route["routes"][0].get(key) for key in ("name", "path", "kind", "method", "content_types")}
        != {
            "name": "reserve",
            "path": "/v1/reserve",
            "kind": "reserve",
            "method": "POST",
            "content_types": ["application/json"],
        }
    ):
        raise EvidenceError("operator HTTP route is not exact")

    protected = result.get("protected")
    raw = result.get("raw")
    stop = result.get("stop")
    if not isinstance(protected, list) or len(protected) != expected_repetitions or not isinstance(raw, list) or len(raw) != expected_repetitions or not isinstance(stop, dict):
        raise EvidenceError("comparison runs are incomplete")
    expected_matrix = [
        {"condition": "protected-history-recovery", "repetitions": expected_repetitions, "mongo_rows_per_run": [1] * expected_repetitions, "task_completion": True, "pass": True},
        {"condition": "raw-retry", "repetitions": expected_repetitions, "mongo_rows_per_run": [2] * expected_repetitions, "task_completion": True, "pass": True},
        {"condition": "stop-after-loss", "repetitions": 1, "mongo_rows_per_run": [1], "task_completion": False, "pass": True},
    ]
    if result.get("matrix") != expected_matrix:
        raise EvidenceError("comparison matrix does not show recovery versus retry and stop")

    all_keys: list[str] = []
    cell_identities: set[tuple[int, int, str]] = set()
    generation = 0
    for index, item in enumerate(protected, 1):
        key = item.get("key", "")
        operation_id = item.get("operation_id")
        if (
            item.get("run") != index
            or HEX32.fullmatch(key) is None
            or operation_id != _operation_id(key)
            or item.get("mongo_rows") != 1
            or item.get("provider_deliveries") != 1
            or item.get("stale_probe", {}).get("status", 0) < 400
            or item.get("stale_probe", {}).get("body", {}).get("detail") != "sandbox endpoint generation changed"
        ):
            raise EvidenceError(f"protected run {index} is inconsistent")
        all_keys.append(key)
        generation += 1
        source = _cell(runtime, item["source"], label=f"protected-{index}-source", generation=generation, key=key, complete=False, protected=True, artifact_hashes=hashes)
        if item.get("source_zero_response") != _json_lines(runtime / "cells" / f"protected-{index}-source" / "egress-relay.jsonl", "source relay")[-1]:
            raise EvidenceError(f"protected run {index} zero-response record differs")
        generation += 1
        replacement = _cell(runtime, item["replacement"], label=f"protected-{index}-replacement", generation=generation, key=key, complete=True, protected=True, artifact_hashes=hashes)
        for cell in (source, replacement):
            process = cell["process"]
            identity = (process["pid"], process["start_time_ticks"], process["instance_id"])
            if identity in cell_identities:
                raise EvidenceError("two cells share one VMM identity")
            cell_identities.add(identity)
    for index, item in enumerate(raw, 1):
        key = item.get("key", "")
        if (
            item.get("run") != index
            or HEX32.fullmatch(key) is None
            or item.get("operation_id") != key
            or item.get("mongo_rows") != 2
            or item.get("provider_deliveries") != 2
        ):
            raise EvidenceError(f"raw run {index} is inconsistent")
        all_keys.append(key)
        generation += 1
        source = _cell(runtime, item["source"], label=f"raw-{index}-source", generation=generation, key=key, complete=False, protected=False, artifact_hashes=hashes)
        if item.get("source_zero_response") != _json_lines(runtime / "cells" / f"raw-{index}-source" / "egress-relay.jsonl", "raw source relay")[-1]:
            raise EvidenceError(f"raw run {index} zero-response record differs")
        generation += 1
        replacement = _cell(runtime, item["replacement"], label=f"raw-{index}-replacement", generation=generation, key=key, complete=True, protected=False, artifact_hashes=hashes)
        for cell in (source, replacement):
            process = cell["process"]
            identity = (process["pid"], process["start_time_ticks"], process["instance_id"])
            if identity in cell_identities:
                raise EvidenceError("two cells share one VMM identity")
            cell_identities.add(identity)
    stop_key = stop.get("key", "")
    if (
        HEX32.fullmatch(stop_key) is None
        or stop.get("operation_id") != stop_key
        or stop.get("mongo_rows") != 1
        or stop.get("provider_deliveries") != 1
        or stop.get("task_completed") is not False
    ):
        raise EvidenceError("stop control is inconsistent")
    all_keys.append(stop_key)
    generation += 1
    stopped = _cell(runtime, stop["source"], label="stop-source", generation=generation, key=stop_key, complete=False, protected=False, artifact_hashes=hashes)
    if stop.get("source_zero_response") != _json_lines(runtime / "cells" / "stop-source" / "egress-relay.jsonl", "stop relay")[-1]:
        raise EvidenceError("stop zero-response record differs")
    process = stopped["process"]
    identity = (process["pid"], process["start_time_ticks"], process["instance_id"])
    if identity in cell_identities or len(set(all_keys)) != len(all_keys):
        raise EvidenceError("keys or VMM identities are reused across runs")

    audit = _json_lines(root / "deathstar-adapter.audit.jsonl", "DeathStar adapter audit")
    expected_deliveries = expected_repetitions * 3 + 1
    if len(audit) != expected_deliveries:
        raise EvidenceError("application adapter has the wrong delivery count")
    by_operation: dict[str, list[dict[str, Any]]] = {}
    for ordinal, record in enumerate(audit, 1):
        if (
            record.get("delivery") != ordinal
            or record.get("upstream_status") != 200
            or record.get("upstream_ok") is not True
            or record.get("drop") is not False
            or record.get("post_commit_delay_ms") != 8000
            or not isinstance(record.get("committed_time_ns"), int)
            or record.get("committed_time_ns", 0) <= 0
        ):
            raise EvidenceError(f"application audit record {ordinal} is malformed")
        by_operation.setdefault(record.get("operation_id", ""), []).append(record)
    expected_counts = {_operation_id(item["key"]): 1 for item in protected}
    expected_counts.update({item["key"]: 2 for item in raw})
    expected_counts[stop_key] = 1
    if {key: len(value) for key, value in by_operation.items()} != expected_counts:
        raise EvidenceError("application audit does not match the comparison matrix")

    history = _history(runtime / "control.history")
    if result.get("history") != {"sequence": len(history), "hash": history[-1]["hash"]}:
        raise EvidenceError("runtime result is not bound to the History head")
    prepared = [record["data"]["operation"] for record in history if record["operation"] == "operation.prepared"]
    succeeded = [record for record in history if record["operation"] == "operation.phase" and record["data"].get("update", {}).get("phase") == "succeeded"]
    protected_ids = {_operation_id(item["key"]) for item in protected}
    if len(prepared) != expected_repetitions or len(succeeded) != expected_repetitions or {item.get("id") for item in prepared} != protected_ids or {item["data"].get("id") for item in succeeded} != protected_ids:
        raise EvidenceError("History lacks the protected prepared-to-succeeded operations")
    expected_body = base64.b64encode(_canonical(BODY)).decode()
    for operation in prepared:
        if (
            operation.get("domain") != "firecracker-deathstar-egress"
            or operation.get("sandbox_id") != "claude-http"
            or operation.get("kind") != "reserve"
            or operation.get("method") != "POST"
            or operation.get("retry_safe") is not False
            or operation.get("queryable") is not True
            or operation.get("request_stored") is not True
            or operation.get("request_body") != expected_body
            or operation.get("request_hash") != _request_hash(operation, _canonical(BODY))
        ):
            raise EvidenceError("History prepared a different operation contract")
    for record in succeeded:
        update = record["data"]["update"]
        if update.get("settlement") != "query" or update.get("status_code") != 200:
            raise EvidenceError("protected operation did not settle by provider query")

    observer = _json(runtime / "observer-facts.json", "retained Mongo facts")
    observation_records = observer.get("facts", []) if isinstance(observer, dict) else []
    expected_observations: list[tuple[str, int, str]] = []
    prepared_by_id = {operation["id"]: operation for operation in prepared}
    for item in protected:
        operation_id = item["operation_id"]
        request_hash = prepared_by_id[operation_id]["request_hash"]
        expected_observations.extend(
            [
                (operation_id, 1, "0" * 64),
                (operation_id, 1, "0" * 64),
                (operation_id, 1, request_hash),
                (operation_id, 1, "0" * 64),
            ]
        )
    for item in raw:
        expected_observations.extend(
            [(item["operation_id"], 1, "0" * 64), (item["operation_id"], 2, "0" * 64)]
        )
    expected_observations.append((stop_key, 1, "0" * 64))
    if (
        observer.get("mode") != "observer"
        or observer.get("queries") != len(expected_observations)
        or observer.get("outcomes")
        != {"succeeded": expected_repetitions * 5 + 1, "inconclusive": expected_repetitions}
        or not isinstance(observation_records, list)
        or len(observation_records) != len(expected_observations)
    ):
        raise EvidenceError("retained Mongo query summary is incomplete")
    observation_times: list[int] = []
    for ordinal, (record, expected) in enumerate(zip(observation_records, expected_observations, strict=True), 1):
        operation_id, count, request_hash = expected
        expected_fact = {
            "customer_name": "safe-" + operation_id,
            "hotel_id": BODY["hotel_id"],
            "in_date": BODY["in_date"],
            "out_date": BODY["out_date"],
            "rooms": BODY["rooms"],
        }
        expected_facts = [expected_fact] * count
        facts_hash = sha256(_canonical(expected_facts)).hexdigest()
        observed_time = record.get("observed_time_ns")
        if (
            record.get("schema") != 1
            or record.get("operation_id") != operation_id
            or record.get("request_hash") != request_hash
            or record.get("count") != count
            or record.get("facts") != expected_facts
            or record.get("facts_hash") != facts_hash
            or record.get("outcome") != ("succeeded" if count == 1 else "inconclusive")
            or record.get("fact_hash") != (facts_hash if count == 1 else "")
            or record.get("remote_reference") != f"reservation-db.reservation/count={count}"
            or not isinstance(observed_time, int)
            or observed_time <= 0
        ):
            raise EvidenceError(f"retained Mongo observation {ordinal} is inconsistent")
        observation_times.append(observed_time)
    if observation_times != sorted(observation_times) or len(set(observation_times)) != len(observation_times):
        raise EvidenceError("retained Mongo observations are not strictly ordered")

    timeline = _json(runtime / "timeline.json", "fault timeline")
    expected_events: list[str] = []
    for _ in protected:
        expected_events += ["protected_commit_observed", "protected_source_vmm_killed", "old_generation_rejected", "protected_replacement_completed"]
    for _ in raw:
        expected_events += ["raw_commit_observed", "raw_replacement_completed"]
    expected_events.append("stop_control_ended")
    if (
        not isinstance(timeline, list)
        or [record.get("event") for record in timeline] != expected_events
        or [record.get("sequence") for record in timeline] != list(range(1, len(timeline) + 1))
        or [record.get("time_ns") for record in timeline] != sorted(record.get("time_ns") for record in timeline)
    ):
        raise EvidenceError("fault timeline is incomplete or unordered")
    for index, item in enumerate(protected, 1):
        commit = timeline[(index - 1) * 4]
        killed = timeline[(index - 1) * 4 + 1]
        delivery = by_operation[item["operation_id"]][0]
        first_observation = observation_records[(index - 1) * 4]
        source_stopped = item["source"]["result"]["process"]["stopped_time_ns"]
        if commit.get("operation_id") != item["operation_id"] or commit.get("committed_time_ns") != delivery["committed_time_ns"] or killed.get("source_stopped_time_ns") != source_stopped or not (delivery["committed_time_ns"] <= first_observation["observed_time_ns"] <= commit["time_ns"] <= source_stopped <= killed["time_ns"]):
            raise EvidenceError(f"protected run {index} commit barrier is false")
    observation_offset = expected_repetitions * 4
    timeline_offset = expected_repetitions * 4
    for index, item in enumerate(raw, 1):
        commit = timeline[timeline_offset + (index - 1) * 2]
        deliveries = by_operation[item["operation_id"]]
        source_observation = observation_records[observation_offset + (index - 1) * 2]
        final_observation = observation_records[observation_offset + (index - 1) * 2 + 1]
        source_stopped = item["source"]["result"]["process"]["stopped_time_ns"]
        if (
            commit.get("operation_id") != item["operation_id"]
            or not (
                deliveries[0]["committed_time_ns"]
                <= source_observation["observed_time_ns"]
                <= commit["time_ns"]
                <= source_stopped
                <= timeline[timeline_offset + (index - 1) * 2 + 1]["time_ns"]
            )
            or deliveries[1]["committed_time_ns"] > final_observation["observed_time_ns"]
        ):
            raise EvidenceError(f"raw run {index} commit barrier is false")
    stop_event = timeline[-1]
    stop_observation = observation_records[-1]
    stop_delivery = by_operation[stop_key][0]
    stop_stopped = stop["source"]["result"]["process"]["stopped_time_ns"]
    if not (
        stop_delivery["committed_time_ns"]
        <= stop_observation["observed_time_ns"]
        <= stop_stopped
        <= stop_event["time_ns"]
    ):
        raise EvidenceError("stop control commit barrier is false")

    requests = _json(runtime / "anthropic-requests.json", "model requests")
    if not isinstance(requests, list) or len(requests) != expected_repetitions * 6 + 1:
        raise EvidenceError("model fixture request count is wrong")
    for request in requests:
        body = request.get("body", {})
        tool_names = [tool.get("name") for tool in body.get("tools", [])]
        if request.get("path") != "/v1/messages?beta=true" or request.get("method") != "POST" or "Bash" not in tool_names or any(name.startswith("mcp__") for name in tool_names if isinstance(name, str)):
            raise EvidenceError("model request did not expose the ordinary Bash interface")
    return {
        "valid": True,
        "system": result["system"],
        "repetitions": expected_repetitions,
        "official_services": graph["official_services"],
        "firecracker_cells": generation,
        "protected_rows_per_run": [1] * expected_repetitions,
        "raw_rows_per_run": [2] * expected_repetitions,
        "stop_task_completion": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--expected-repetitions", type=int, default=3)
    args = parser.parse_args()
    try:
        summary = check(args.evidence, args.expected_repetitions)
    except (EvidenceError, OSError, TypeError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
