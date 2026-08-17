"""Run ordinary Claude Bash HTTP across Firecracker loss and DeathStarBench."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import shutil
import stat
import sys
import tempfile
import time
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from .codex_mcp_runtime_demo import (
    DemoError,
    _Process,
    _owned_executable,
    _private_directory,
    _read_token,
    _reserve_loopback_port,
    _sha256_file,
    _wait_healthy,
    _write_private_json,
)
from .firecracker_claude_mcp_runtime_demo import _ClaudeCell
from .mock_anthropic import DeterministicBashAnthropicServer


_DOMAIN = "firecracker-deathstar-egress"
_SANDBOX_ID = "claude-http"
_ROUTE_NAME = "reserve"
_KIND = "reserve"
_BODY = {
    "hotel_id": "1",
    "in_date": "2015-04-09",
    "out_date": "2015-04-10",
    "rooms": 1,
    "username": "Cornell_30",
    "password": "0000000000",
}
_MAX_HTTP_BYTES = 4 << 20


def _json_lines(path: Path, label: str) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        values = [json.loads(line) for line in lines if line]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DemoError(f"{label} is not valid JSONL") from error
    if any(not isinstance(value, dict) for value in values):
        raise DemoError(f"{label} contains a non-object")
    return values


def _http(
    method: str,
    url: str,
    *,
    value: Mapping[str, Any] | None = None,
    token: str | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: float = 15,
) -> tuple[int, dict[str, Any]]:
    encoded = None
    request_headers = dict(headers or {})
    if value is not None:
        encoded = json.dumps(
            dict(value), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    if token is not None:
        request_headers["Authorization"] = "Bearer " + token
    request = Request(url, data=encoded, headers=request_headers, method=method)
    try:
        with build_opener(ProxyHandler({})).open(request, timeout=timeout) as response:
            status = response.status
            raw = response.read(_MAX_HTTP_BYTES + 1)
    except HTTPError as error:
        status = error.code
        raw = error.read(_MAX_HTTP_BYTES + 1)
    except (OSError, URLError) as error:
        raise DemoError(f"{method} {url} failed") from error
    if len(raw) > _MAX_HTTP_BYTES:
        raise DemoError(f"{method} {url} response is oversized")
    try:
        body = json.loads(raw)
    except json.JSONDecodeError as error:
        raise DemoError(f"{method} {url} response is not JSON") from error
    if not isinstance(body, dict):
        raise DemoError(f"{method} {url} response is not an object")
    return status, body


def _require_ok(result: tuple[int, dict[str, Any]], label: str) -> dict[str, Any]:
    status, body = result
    if status != 200:
        raise DemoError(f"{label} returned HTTP {status}: {body}")
    return body


def _sandbox_socket(directory: Path) -> Path:
    name = "sandbox-" + sha256(_SANDBOX_ID.encode()).hexdigest()[:32] + ".sock"
    return directory / name


def _route_call_id(key: str) -> str:
    return f"effect-route-idempotency-v1:{len(_ROUTE_NAME)}:{_ROUTE_NAME}:{key}"


def _operation_id(key: str) -> str:
    call_id = _route_call_id(key)
    digest = sha256(
        b"sandbox-operation-id-v2\x00"
        + _DOMAIN.encode()
        + b"\x00"
        + _SANDBOX_ID.encode()
        + b"\x00"
        + call_id.encode()
    ).hexdigest()
    return "op-" + digest


def _requirement(effect_url: str, observer_url: str, repetitions: int) -> dict[str, Any]:
    return {
        "id": "firecracker-deathstar-http",
        "results": {"reserved": repetitions},
        "capacities": {"reservation": repetitions},
        "kinds": {
            _KIND: {
                "costs": {"reservation": 1},
                "produces": {"reserved": 1},
                "retry_safe": False,
                "queryable": True,
                "target": effect_url,
                "method": "POST",
                "response_classifier": "operation-receipt-v1",
                "query_target": observer_url,
                "query_method": "POST",
                "query_classifier": "operation-observation-v1",
            }
        },
    }


def _observer_count(observer_url: str, operation_id: str) -> dict[str, Any]:
    status, body = _http(
        "POST",
        observer_url,
        value=_BODY,
        headers={
            "X-Operation-ID": operation_id,
            "X-Operation-Request-Hash": "0" * 64,
        },
    )
    if status != 200 or not isinstance(body.get("remote_reference"), str):
        raise DemoError(f"observer query failed for {operation_id}: {status} {body}")
    reference = body["remote_reference"]
    try:
        count = int(reference.rsplit("=", 1)[1])
    except (IndexError, ValueError) as error:
        raise DemoError("observer returned a malformed Mongo count") from error
    return {"time_ns": time.time_ns(), "count": count, "body": body}


def _wait_delivery(
    audit_path: Path, operation_id: str, expected: int, timeout: float = 30
) -> list[dict[str, Any]]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        records = _json_lines(audit_path, "DeathStar adapter audit")
        matches = [record for record in records if record.get("operation_id") == operation_id]
        if len(matches) >= expected:
            if len(matches) != expected:
                raise DemoError(f"provider delivered {operation_id} more than {expected} times")
            return matches
        time.sleep(0.05)
    raise DemoError(f"provider did not commit {operation_id} {expected} times")


def _delivery_count(audit_path: Path, operation_id: str) -> int:
    return sum(
        record.get("operation_id") == operation_id
        for record in _json_lines(audit_path, "DeathStar adapter audit")
    )


def _assert_zero_response_bytes(cell: _ClaudeCell) -> dict[str, Any]:
    events = _json_lines(cell.evidence / "egress-relay.jsonl", "HTTP egress relay")
    byte_events = [event for event in events if event.get("event") == "bytes"]
    if (
        len(byte_events) != 1
        or not isinstance(byte_events[0].get("guest_to_host_bytes"), int)
        or byte_events[0]["guest_to_host_bytes"] <= 0
        or byte_events[0].get("host_to_guest_bytes") != 0
    ):
        raise DemoError(f"source guest received response bytes before VMM loss: {byte_events}")
    return byte_events[0]


def _load_http_payload(
    result_path: Path, payload: Path, claude_sha256: str, busybox: Path
) -> tuple[str, str, str]:
    try:
        record = json.loads(result_path.read_bytes())
        built = record["payload"]
        inputs = record["inputs"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise DemoError("HTTP Claude payload result is malformed") from error
    busybox_sha256 = _sha256_file(busybox)
    bash_sha256 = inputs.get("bash", {}).get("sha256")
    if (
        record.get("schema") != 2
        or built.get("image_path") != os.fspath(payload)
        or built.get("image_sha256") != _sha256_file(payload)
        or inputs.get("claude", {}).get("sha256") != claude_sha256
        or inputs.get("busybox", {}).get("path") != os.fspath(busybox)
        or inputs.get("busybox", {}).get("sha256") != busybox_sha256
        or not isinstance(bash_sha256, str)
        or len(bash_sha256) != 64
    ):
        raise DemoError("HTTP Claude payload does not bind selected artifacts")
    return built["image_sha256"], busybox_sha256, bash_sha256


def _write_route_config(path: Path, effect_url: str) -> None:
    _write_private_json(
        path,
        {
            "schema": 2,
            "routes": [
                {
                    "name": _ROUTE_NAME,
                    "path": "/v1/reserve",
                    "kind": _KIND,
                    "method": "POST",
                    "url": effect_url,
                    "content_types": ["application/json"],
                }
            ],
        },
    )


def _bash_command() -> str:
    body = json.dumps(_BODY, sort_keys=True, separators=(",", ":"))
    return (
        "/opt/claude/bin/busybox wget -qO- "
        "--header='Content-Type: application/json' "
        ' --header="Idempotency-Key: $SAFE_CHANGE_CALL_ID" '
        ' --header="X-Operation-ID: $SAFE_CHANGE_CALL_ID" '
        f"--post-data='{body}' \"$SAFE_CHANGE_EGRESS_URL\""
    )


def _cutover(
    control_url: str,
    token: str,
    requirement: Mapping[str, Any],
    generation: int,
) -> dict[str, Any]:
    deadline = time.monotonic() + 20
    last: tuple[int, dict[str, Any]] | None = None
    while time.monotonic() < deadline:
        last = _http("POST", control_url + "/v1/compile", value=requirement, token=token)
        if last[0] != 200:
            time.sleep(0.05)
            continue
        binding = {
            "sandbox_id": _SANDBOX_ID,
            "generation": generation,
            "host_instance_id": "host-" + secrets.token_hex(16),
            "domain": _DOMAIN,
            "allowed_kinds": [_KIND],
        }
        cutover = _http(
            "POST",
            control_url + "/v1/cutover",
            value={"certificate": last[1], "bindings": [binding]},
            token=token,
            timeout=70,
        )
        if cutover[0] == 200:
            return {"binding": binding, "certificate": last[1], "response": cutover[1]}
        last = cutover
        time.sleep(0.05)
    raise DemoError(f"generation {generation} cutover did not settle: {last}")


def _start_proxy(
    *,
    generation: int,
    binary: Path,
    config: Path,
    sandbox_socket: Path,
    root: Path,
) -> tuple[_Process, str]:
    port = _reserve_loopback_port()
    process = _Process(
        f"effect-proxy-g{generation}",
        [
            os.fspath(binary),
            "-config",
            os.fspath(config),
            "-sandbox-socket",
            os.fspath(sandbox_socket),
            "-listen",
            f"127.0.0.1:{port}",
            "-execute-timeout",
            "30s",
        ],
        root,
    )
    origin = f"http://127.0.0.1:{port}"
    _wait_healthy(origin, process)
    return process, origin


def _new_cell(
    *,
    label: str,
    generation: int,
    session_id: str,
    target: str,
    model_target: str,
    root: Path,
    live_evidence_root: Path,
    cell_binary: Path,
    guest_binary: Path,
    payload: Path,
    payload_sha256: str,
    claude_sha256: str,
    relay_sha256: str,
    busybox_sha256: str,
    bash_sha256: str,
) -> _ClaudeCell:
    evidence = live_evidence_root / label
    return _ClaudeCell(
        label=label,
        generation=generation,
        cell_binary=cell_binary,
        guest_binary=guest_binary,
        payload=payload,
        payload_sha256=payload_sha256,
        claude_sha256=claude_sha256,
        relay_sha256=relay_sha256,
        model_target=model_target,
        mcp_host_socket=None,
        evidence=evidence,
        root=root,
        profile="http",
        egress_target=target.removeprefix("http://"),
        busybox_sha256=busybox_sha256,
        bash_sha256=bash_sha256,
        session_id=session_id,
    )


def _archive_cell(cell: _ClaudeCell, root: Path) -> None:
    destination = root / "cells" / cell.label
    destination.parent.mkdir(mode=0o700, exist_ok=True)
    try:
        cell.evidence.rename(destination)
    except OSError:
        shutil.copytree(cell.evidence, destination)
        shutil.rmtree(cell.evidence)
    cell.evidence = destination


def run(
    *,
    cell_binary: Path,
    guest_binary: Path,
    payload: Path,
    payload_result: Path,
    claude_binary: Path,
    claude_sha256: str,
    busybox: Path,
    control_binary: Path,
    effect_proxy_binary: Path,
    effect_url: str,
    observer_url: str,
    adapter_audit: Path,
    graph_evidence: Path,
    evidence_dir: Path | None,
    repetitions: int,
) -> dict[str, Any]:
    if repetitions < 1 or repetitions > 10:
        raise DemoError("repetitions must be between 1 and 10")
    payload_sha256, busybox_sha256, bash_sha256 = _load_http_payload(
        payload_result, payload, claude_sha256, busybox
    )
    try:
        payload_record = json.loads(payload_result.read_bytes())
        relay_sha256 = payload_record["inputs"]["mcp_operation_relay"]["sha256"]
        graph = json.loads(graph_evidence.read_bytes())
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise DemoError("payload or graph evidence is malformed") from error
    if graph.get("pass") is not True or graph.get("official_services") != 24:
        raise DemoError("DeathStarBench graph evidence is incomplete")

    root = _private_directory(evidence_dir)
    transport_root = Path(tempfile.mkdtemp(prefix="fc-dsb-", dir="/tmp"))
    os.chmod(transport_root, 0o700)
    sockets = transport_root / "sockets"
    sockets.mkdir(mode=0o700)
    live_cells = transport_root / "cells"
    live_cells.mkdir(mode=0o700)
    sandbox_socket = _sandbox_socket(sockets)
    control_port = _reserve_loopback_port()
    control_url = f"http://127.0.0.1:{control_port}"
    history_path = root / "control.history"
    token_path = root / "admin.token"
    route_config = root / "effect-route.json"
    _write_route_config(route_config, effect_url)
    requirement = _requirement(effect_url, observer_url, repetitions)
    _write_private_json(root / "requirement.json", requirement)
    services: list[_Process] = []
    cells: list[_ClaudeCell] = []
    timeline: list[dict[str, Any]] = []
    protected: list[dict[str, Any]] = []
    raw: list[dict[str, Any]] = []
    stop: dict[str, Any] | None = None

    def event(name: str, **details: Any) -> int:
        when = time.time_ns()
        timeline.append({"sequence": len(timeline) + 1, "time_ns": when, "event": name, **details})
        return when

    try:
        control = _Process(
            "control",
            [
                os.fspath(control_binary),
                "-listen",
                f"127.0.0.1:{control_port}",
                "-history",
                os.fspath(history_path),
                "-head-anchor",
                os.fspath(root / "control.head-anchor"),
                "-admin-token-file",
                os.fspath(token_path),
                "-sandbox-socket-dir",
                os.fspath(sockets),
            ],
            root,
        )
        services.append(control)
        _wait_healthy(control_url, control)
        token = _read_token(token_path)
        generation = 0
        with DeterministicBashAnthropicServer(_bash_command()) as model:
            model_target = model.base_url.removeprefix("http://")
            for index in range(repetitions):
                key = secrets.token_hex(16)
                operation_id = _operation_id(key)
                generation += 1
                source_cutover = _cutover(control_url, token, requirement, generation)
                old_proxy, old_origin = _start_proxy(
                    generation=generation,
                    binary=effect_proxy_binary,
                    config=route_config,
                    sandbox_socket=sandbox_socket,
                    root=root,
                )
                services.append(old_proxy)
                source = _new_cell(
                    label=f"protected-{index + 1}-source",
                    generation=generation,
                    session_id=key,
                    target=old_origin,
                    model_target=model_target,
                    root=root,
                    live_evidence_root=live_cells,
                    cell_binary=cell_binary,
                    guest_binary=guest_binary,
                    payload=payload,
                    payload_sha256=payload_sha256,
                    claude_sha256=claude_sha256,
                    relay_sha256=relay_sha256,
                    busybox_sha256=busybox_sha256,
                    bash_sha256=bash_sha256,
                )
                cells.append(source)
                source.wait_ready()
                delivery = _wait_delivery(adapter_audit, operation_id, 1)[0]
                if delivery.get("upstream_ok") is not True:
                    raise DemoError("protected source did not receive an application success")
                committed_time = int(delivery["committed_time_ns"])
                observed = _observer_count(observer_url, operation_id)
                if observed["count"] != 1:
                    raise DemoError("protected source commit is absent from MongoDB")
                barrier_time = event(
                    "protected_commit_observed",
                    run=index + 1,
                    operation_id=operation_id,
                    committed_time_ns=committed_time,
                )
                source.kill_vmm()
                _archive_cell(source, root)
                killed = source.result()["process"]["stopped_time_ns"]
                if not (committed_time <= observed["time_ns"] <= barrier_time <= killed):
                    raise DemoError("protected failure barrier ordering is invalid")
                zero_bytes = _assert_zero_response_bytes(source)
                event("protected_source_vmm_killed", run=index + 1, source_stopped_time_ns=killed)

                generation += 1
                replacement_cutover = _cutover(control_url, token, requirement, generation)
                new_proxy, new_origin = _start_proxy(
                    generation=generation,
                    binary=effect_proxy_binary,
                    config=route_config,
                    sandbox_socket=sandbox_socket,
                    root=root,
                )
                services.append(new_proxy)
                before_stale = _delivery_count(adapter_audit, operation_id)
                stale_status, stale_body = _http(
                    "POST",
                    old_origin + "/v1/reserve",
                    value=_BODY,
                    headers={"Idempotency-Key": key},
                )
                stale_observed = _observer_count(observer_url, operation_id)
                if (
                    stale_status < 400
                    or _delivery_count(adapter_audit, operation_id) != before_stale
                    or stale_observed["count"] != 1
                ):
                    raise DemoError("old generation was not actively fenced")
                event("old_generation_rejected", run=index + 1, status=stale_status)
                replacement = _new_cell(
                    label=f"protected-{index + 1}-replacement",
                    generation=generation,
                    session_id=key,
                    target=new_origin,
                    model_target=model_target,
                    root=root,
                    live_evidence_root=live_cells,
                    cell_binary=cell_binary,
                    guest_binary=guest_binary,
                    payload=payload,
                    payload_sha256=payload_sha256,
                    claude_sha256=claude_sha256,
                    relay_sha256=relay_sha256,
                    busybox_sha256=busybox_sha256,
                    bash_sha256=bash_sha256,
                )
                cells.append(replacement)
                replacement.wait_ready()
                replacement.wait_success()
                _archive_cell(replacement, root)
                final_observed = _observer_count(observer_url, operation_id)
                if final_observed["count"] != 1 or _delivery_count(adapter_audit, operation_id) != 1:
                    raise DemoError("protected recovery duplicated the reservation")
                event("protected_replacement_completed", run=index + 1)
                protected.append(
                    {
                        "run": index + 1,
                        "key": key,
                        "operation_id": operation_id,
                        "mongo_rows": 1,
                        "provider_deliveries": 1,
                        "source_zero_response": zero_bytes,
                        "stale_probe": {"status": stale_status, "body": stale_body},
                        "source_cutover": source_cutover,
                        "replacement_cutover": replacement_cutover,
                        "source": source.record(),
                        "replacement": replacement.record(),
                    }
                )

            for index in range(repetitions):
                key = secrets.token_hex(16)
                operation_id = key
                generation += 1
                source = _new_cell(
                    label=f"raw-{index + 1}-source",
                    generation=generation,
                    session_id=key,
                    target=effect_url.removesuffix("/v1/reserve"),
                    model_target=model_target,
                    root=root,
                    live_evidence_root=live_cells,
                    cell_binary=cell_binary,
                    guest_binary=guest_binary,
                    payload=payload,
                    payload_sha256=payload_sha256,
                    claude_sha256=claude_sha256,
                    relay_sha256=relay_sha256,
                    busybox_sha256=busybox_sha256,
                    bash_sha256=bash_sha256,
                )
                cells.append(source)
                source.wait_ready()
                delivery = _wait_delivery(adapter_audit, operation_id, 1)[0]
                committed_time = int(delivery["committed_time_ns"])
                observed = _observer_count(observer_url, operation_id)
                if observed["count"] != 1:
                    raise DemoError("raw source commit is absent from MongoDB")
                barrier_time = event("raw_commit_observed", run=index + 1, operation_id=operation_id)
                source.kill_vmm()
                _archive_cell(source, root)
                killed = source.result()["process"]["stopped_time_ns"]
                if not (committed_time <= observed["time_ns"] <= barrier_time <= killed):
                    raise DemoError("raw failure barrier ordering is invalid")
                zero_bytes = _assert_zero_response_bytes(source)
                generation += 1
                replacement = _new_cell(
                    label=f"raw-{index + 1}-replacement",
                    generation=generation,
                    session_id=key,
                    target=effect_url.removesuffix("/v1/reserve"),
                    model_target=model_target,
                    root=root,
                    live_evidence_root=live_cells,
                    cell_binary=cell_binary,
                    guest_binary=guest_binary,
                    payload=payload,
                    payload_sha256=payload_sha256,
                    claude_sha256=claude_sha256,
                    relay_sha256=relay_sha256,
                    busybox_sha256=busybox_sha256,
                    bash_sha256=bash_sha256,
                )
                cells.append(replacement)
                replacement.wait_ready()
                replacement.wait_success()
                _archive_cell(replacement, root)
                _wait_delivery(adapter_audit, operation_id, 2)
                final_observed = _observer_count(observer_url, operation_id)
                if final_observed["count"] != 2:
                    raise DemoError("raw retry did not duplicate the reservation")
                event("raw_replacement_completed", run=index + 1)
                raw.append(
                    {
                        "run": index + 1,
                        "key": key,
                        "operation_id": operation_id,
                        "mongo_rows": 2,
                        "provider_deliveries": 2,
                        "source_zero_response": zero_bytes,
                        "source": source.record(),
                        "replacement": replacement.record(),
                    }
                )

            key = secrets.token_hex(16)
            operation_id = key
            generation += 1
            stopped = _new_cell(
                label="stop-source",
                generation=generation,
                session_id=key,
                target=effect_url.removesuffix("/v1/reserve"),
                model_target=model_target,
                root=root,
                live_evidence_root=live_cells,
                cell_binary=cell_binary,
                guest_binary=guest_binary,
                payload=payload,
                payload_sha256=payload_sha256,
                claude_sha256=claude_sha256,
                relay_sha256=relay_sha256,
                busybox_sha256=busybox_sha256,
                bash_sha256=bash_sha256,
            )
            cells.append(stopped)
            stopped.wait_ready()
            delivery = _wait_delivery(adapter_audit, operation_id, 1)[0]
            observed = _observer_count(observer_url, operation_id)
            if observed["count"] != 1:
                raise DemoError("stop control commit is absent from MongoDB")
            stopped.kill_vmm()
            _archive_cell(stopped, root)
            zero_bytes = _assert_zero_response_bytes(stopped)
            time.sleep(0.2)
            if _delivery_count(adapter_audit, operation_id) != 1:
                raise DemoError("stop control unexpectedly retried")
            stop = {
                "key": key,
                "operation_id": operation_id,
                "mongo_rows": 1,
                "provider_deliveries": 1,
                "task_completed": False,
                "source_zero_response": zero_bytes,
                "source": stopped.record(),
            }
            event("stop_control_ended")
            model_requests = [asdict(request) for request in model.requests]
            _write_private_json(root / "anthropic-requests.json", model_requests)
            expected_model_requests = repetitions * 6 + 1
            if model.failure is not None or len(model_requests) != expected_model_requests:
                raise DemoError(
                    f"model protocol failure or {len(model_requests)} requests, expected {expected_model_requests}"
                )

        observer_facts = _require_ok(
            _http("GET", observer_url.removesuffix("/v1/query") + "/v1/stats/facts"),
            "retained Mongo facts",
        )
        expected_observations = repetitions * 6 + 1
        if (
            observer_facts.get("mode") != "observer"
            or observer_facts.get("queries") != expected_observations
            or not isinstance(observer_facts.get("facts"), list)
            or len(observer_facts["facts"]) != expected_observations
        ):
            raise DemoError("observer did not retain every Mongo query fact")
        observer_facts_path = root / "observer-facts.json"
        _write_private_json(observer_facts_path, observer_facts)
        state = _require_ok(_http("GET", control_url + "/v1/state", token=token), "state")
        operations = state.get("operations")
        if not isinstance(operations, dict) or len(operations) != repetitions:
            raise DemoError("History has a different protected Operation count")
        for item in protected:
            operation = operations.get(item["operation_id"])
            if (
                not isinstance(operation, dict)
                or operation.get("phase") != "succeeded"
                or operation.get("settlement") != "query"
            ):
                raise DemoError("protected Operation did not settle by query")
        _write_private_json(root / "timeline.json", timeline)
        matrix = [
            {
                "condition": "protected-history-recovery",
                "repetitions": repetitions,
                "mongo_rows_per_run": [item["mongo_rows"] for item in protected],
                "task_completion": True,
                "pass": all(item["mongo_rows"] == 1 for item in protected),
            },
            {
                "condition": "raw-retry",
                "repetitions": repetitions,
                "mongo_rows_per_run": [item["mongo_rows"] for item in raw],
                "task_completion": True,
                "pass": all(item["mongo_rows"] == 2 for item in raw),
            },
            {
                "condition": "stop-after-loss",
                "repetitions": 1,
                "mongo_rows_per_run": [stop["mongo_rows"]],
                "task_completion": False,
                "pass": stop["mongo_rows"] == 1,
            },
        ]
        result = {
            "schema": 1,
            "valid": all(row["pass"] for row in matrix),
            "system": "official-claude-firecracker-deathstar-http-egress",
            "transparency": {
                "claude_source_modified": False,
                "deathstar_source_modified": False,
                "operator_route_registered": True,
            },
            "repetitions": repetitions,
            "matrix": matrix,
            "protected": protected,
            "raw": raw,
            "stop": stop,
            "history": state.get("history"),
            "network_interfaces_per_cell": 0,
            "root_block_devices_per_cell": 0,
            "model_requests": repetitions * 6 + 1,
            "mongo_observations": expected_observations,
            "graph": graph,
            "artifacts": {
                "cell": _sha256_file(cell_binary),
                "guest": _sha256_file(guest_binary),
                "payload": payload_sha256,
                "payload_result": _sha256_file(payload_result),
                "claude": claude_sha256,
                "busybox": busybox_sha256,
                "bash": bash_sha256,
                "control": _sha256_file(control_binary),
                "effect_proxy": _sha256_file(effect_proxy_binary),
                "history": _sha256_file(history_path),
                "adapter_audit": _sha256_file(adapter_audit),
                "observer_facts": _sha256_file(observer_facts_path),
            },
        }
        if not result["valid"]:
            raise DemoError("comparison matrix failed")
        _write_private_json(root / "result.json", result)
        return {"evidence": os.fspath(root), **result}
    finally:
        active_failure = sys.exc_info()[0] is not None
        failures: list[BaseException] = []
        for cell in reversed(cells):
            try:
                cell.close()
            except BaseException as error:
                failures.append(error)
        for service in reversed(services):
            try:
                service.close()
            except BaseException as error:
                failures.append(error)
        try:
            token_path.unlink(missing_ok=True)
        except OSError as error:
            failures.append(error)
        try:
            lock = sockets / ".safe-change.lock"
            if lock.exists():
                info = lock.lstat()
                if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
                    raise DemoError("sandbox manager lock is unsafe")
                lock.unlink()
            sockets.rmdir()
            for entry in list(live_cells.iterdir()):
                destination = root / "cells" / ("failed-" + entry.name)
                destination.parent.mkdir(mode=0o700, exist_ok=True)
                try:
                    entry.rename(destination)
                except OSError:
                    shutil.copytree(entry, destination)
                    shutil.rmtree(entry)
            live_cells.rmdir()
            transport_root.rmdir()
        except OSError as error:
            failures.append(error)
        if failures and not active_failure:
            raise DemoError("cross-domain cleanup failed: " + "; ".join(map(str, failures)))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cell-binary", required=True, type=Path)
    parser.add_argument("--guest-binary", required=True, type=Path)
    parser.add_argument("--payload", required=True, type=Path)
    parser.add_argument("--payload-result", required=True, type=Path)
    parser.add_argument("--claude-binary", required=True, type=Path)
    parser.add_argument("--claude-sha256", required=True)
    parser.add_argument("--busybox", required=True, type=Path)
    parser.add_argument("--control-binary", required=True, type=Path)
    parser.add_argument("--effect-proxy-binary", required=True, type=Path)
    parser.add_argument("--effect-url", required=True)
    parser.add_argument("--observer-url", required=True)
    parser.add_argument("--adapter-audit", required=True, type=Path)
    parser.add_argument("--graph-evidence", required=True, type=Path)
    parser.add_argument("--evidence-dir", type=Path)
    parser.add_argument("--repetitions", type=int, default=3)
    args = parser.parse_args()
    try:
        result = run(
            cell_binary=_owned_executable(args.cell_binary.resolve(), "Claude cell"),
            guest_binary=_owned_executable(args.guest_binary.resolve(), "Claude guest"),
            payload=args.payload.resolve(strict=True),
            payload_result=args.payload_result.resolve(strict=True),
            claude_binary=_owned_executable(args.claude_binary.resolve(), "Claude"),
            claude_sha256=args.claude_sha256,
            busybox=args.busybox.resolve(strict=True),
            control_binary=_owned_executable(args.control_binary.resolve(), "Control"),
            effect_proxy_binary=_owned_executable(args.effect_proxy_binary.resolve(), "effect proxy"),
            effect_url=args.effect_url,
            observer_url=args.observer_url,
            adapter_audit=args.adapter_audit.resolve(strict=True),
            graph_evidence=args.graph_evidence.resolve(strict=True),
            evidence_dir=args.evidence_dir,
            repetitions=args.repetitions,
        )
    except (DemoError, OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
