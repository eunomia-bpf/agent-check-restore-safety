"""Run History-authorized Firecracker starts with official Claude and DeathStarBench."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import shutil
import sys
import tempfile
import time
from typing import Any, Mapping

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
from .firecracker_deathstar_egress_demo import _load_http_payload
from .mock_anthropic import DeterministicBashAnthropicServer
from .qemu_agent_restore_demo import (
    _FinishServer,
    _canonical,
    _compile,
    _cutover,
    _delivery_count,
    _fence_path,
    _http,
    _json_lines,
    _observer_query,
    _replace_private_json,
    _start_effect,
    _start_proxy,
    _wait_delivery,
    _wait_fence,
    _wait_model_request,
    _wait_operation,
)


_DOMAIN = "firecracker-history-start"
_SANDBOX_ID = "claude-history"
_KIND = "reserve"
_FINISH_KIND = "finish"
_ROUTE = "reserve"
_BODY = {
    "hotel_id": "1",
    "in_date": "2015-04-09",
    "out_date": "2015-04-10",
    "rooms": 1,
    "username": "Cornell_30",
    "password": "0000000000",
}


def _operation_id(session: str) -> str:
    call_id = f"effect-route-idempotency-v1:{len(_ROUTE)}:{_ROUTE}:{session}"
    digest = sha256(
        b"sandbox-operation-id-v2\x00"
        + _DOMAIN.encode()
        + b"\x00"
        + _SANDBOX_ID.encode()
        + b"\x00"
        + call_id.encode()
    ).hexdigest()
    return "op-" + digest


def _sandbox_socket(directory: Path) -> Path:
    name = "sandbox-" + sha256(_SANDBOX_ID.encode()).hexdigest()[:32] + ".sock"
    return directory / name


def _binding(generation: int) -> dict[str, Any]:
    return {
        "sandbox_id": _SANDBOX_ID,
        "generation": generation,
        "host_instance_id": "firecracker-host-" + secrets.token_hex(16),
        "domain": _DOMAIN,
        "allowed_kinds": [_KIND],
    }


def _requirements(
    effect_url: str, observer_url: str, finish_url: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    results = {"reserved": 1, "finished": 1}
    capacities = {"reservation": 1, "finish-slot": 1}
    reserve = {
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
    finish = {
        "costs": {"finish-slot": 1},
        "produces": {"finished": 1},
        "retry_safe": True,
        "queryable": False,
        "target": finish_url,
        "method": "POST",
        "response_classifier": "operation-receipt-v1",
    }
    before = {
        "id": "firecracker-history-v1",
        "results": results,
        "capacities": capacities,
        "kinds": {_KIND: reserve, _FINISH_KIND: finish},
    }
    after = {
        "id": "firecracker-history-v2",
        "results": results,
        "capacities": capacities,
        "kinds": {
            _KIND: {
                "costs": {"reservation": 1},
                "produces": {"reserved": 1},
                "retry_safe": False,
                "queryable": False,
            },
            _FINISH_KIND: finish,
        },
    }
    return before, after


def _bash_command() -> str:
    body = json.dumps(_BODY, sort_keys=True, separators=(",", ":"))
    return (
        "/opt/claude/bin/busybox wget -qO- "
        "--header='Content-Type: application/json' "
        ' --header="Idempotency-Key: $SAFE_CHANGE_CALL_ID" '
        ' --header="X-Operation-ID: $SAFE_CHANGE_CALL_ID" '
        f"--post-data='{body}' \"$SAFE_CHANGE_EGRESS_URL\""
    )


def _write_route(path: Path, effect_url: str) -> None:
    _write_private_json(
        path,
        {
            "schema": 2,
            "routes": [
                {
                    "name": _ROUTE,
                    "path": "/v1/reserve",
                    "kind": _KIND,
                    "method": "POST",
                    "url": effect_url,
                    "content_types": ["application/json"],
                }
            ],
        },
    )


def _start_control(
    binary: Path, root: Path, sockets: Path
) -> tuple[_Process, str, str, Path, Path]:
    port = _reserve_loopback_port()
    sockets.mkdir(mode=0o700)
    token_path = root / "admin.token"
    process = _Process(
        "control",
        [
            os.fspath(binary),
            "-listen",
            f"127.0.0.1:{port}",
            "-history",
            os.fspath(root / "control.history"),
            "-head-anchor",
            os.fspath(root / "control.head"),
            "-admin-token-file",
            os.fspath(token_path),
            "-sandbox-socket-dir",
            os.fspath(sockets),
        ],
        root,
    )
    origin = f"http://127.0.0.1:{port}"
    _wait_healthy(origin, process)
    return process, origin, _read_token(token_path), _sandbox_socket(sockets), token_path


def _write_launch_manifest(
    path: Path,
    checked: Mapping[str, Any],
    certificate: Mapping[str, Any],
    activated_history: Mapping[str, Any],
    binding: Mapping[str, Any],
    endpoint: Path,
    control_url: str,
    token_path: Path,
) -> None:
    _write_private_json(
        path,
        {
            "schema": 1,
            "checked_state": dict(checked),
            "certificate": dict(certificate),
            "activated_history": dict(activated_history),
            "binding": dict(binding),
            "endpoint_path": os.fspath(endpoint),
            "control_url": control_url,
            "control_token_path": os.fspath(token_path),
        },
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


def _new_cell(
    *,
    label: str,
    generation: int,
    session: str,
    target: str,
    model_target: str,
    root: Path,
    live_cells: Path,
    cell_binary: Path,
    guest_binary: Path,
    payload: Path,
    payload_sha256: str,
    claude_sha256: str,
    relay_sha256: str,
    busybox_sha256: str,
    bash_sha256: str,
    launch_manifest: Path | None,
) -> _ClaudeCell:
    return _ClaudeCell(
        label=label,
        generation=generation,
        session_id=session,
        cell_binary=cell_binary,
        guest_binary=guest_binary,
        payload=payload,
        payload_sha256=payload_sha256,
        claude_sha256=claude_sha256,
        relay_sha256=relay_sha256,
        model_target=model_target,
        mcp_host_socket=None,
        evidence=live_cells / label,
        root=root,
        profile="http",
        egress_target=target.removeprefix("http://"),
        busybox_sha256=busybox_sha256,
        bash_sha256=bash_sha256,
        launch_manifest=launch_manifest,
    )


def _assert_zero_response(cell: _ClaudeCell) -> dict[str, Any]:
    events = _json_lines(cell.evidence / "egress-relay.jsonl")
    byte_events = [item for item in events if item.get("event") == "bytes"]
    if (
        len(byte_events) != 1
        or not isinstance(byte_events[0].get("guest_to_host_bytes"), int)
        or byte_events[0]["guest_to_host_bytes"] <= 0
        or byte_events[0].get("host_to_guest_bytes") != 0
    ):
        raise DemoError(f"{cell.label} received response bytes before loss: {byte_events}")
    return byte_events[0]


def _assert_denied_replacement(cell: _ClaudeCell) -> dict[str, Any]:
    result = cell.result()
    if (
        result.get("disposition") != "launch-denied"
        or result.get("launch_guarded") is not True
        or result.get("launch_decision") != "impossible"
        or result.get("instance_started") is not False
        or "guest_result" in result
    ):
        raise DemoError("H0 replacement result does not prove denied launch")
    for name in ("gate.jsonl", "model-relay.jsonl", "egress-relay.jsonl"):
        if (cell.evidence / name).read_bytes() != b"":
            raise DemoError(f"H0 replacement emitted forbidden guest evidence: {name}")
    api = _json_lines(cell.evidence / "firecracker-api.jsonl")
    if any(item.get("path") == "/actions" for item in api):
        raise DemoError("H0 replacement issued Firecracker InstanceStart")
    states = [
        item
        for item in api
        if item.get("method") == "GET" and item.get("path") == "/"
    ]
    if len(states) != 2 or any(
        item.get("response", {}).get("state") != "Not started" for item in states
    ):
        raise DemoError("H0 replacement lacks two Not started observations")
    guard = json.loads((cell.evidence / "launch-guard.json").read_bytes())
    if guard.get("instance_start_issued") is not False:
        raise DemoError("H0 launch guard claims an InstanceStart")
    return {"api": api, "guard": guard, "result": result}


def _initial_activation(
    *,
    root: Path,
    control_url: str,
    token: str,
    requirement: Mapping[str, Any],
    generation: int,
    endpoint: Path,
    token_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], Path]:
    checked, certificate, projection = _compile(control_url, token, requirement)
    if certificate.get("decision") != "activate":
        raise DemoError("initial Requirement did not activate")
    binding = _binding(generation)
    activated = _cutover(control_url, token, certificate, binding)
    manifest = root / f"launch-g{generation}.json"
    _write_launch_manifest(
        manifest,
        checked,
        certificate,
        activated["history"],
        binding,
        endpoint,
        control_url,
        token_path,
    )
    _write_private_json(root / f"initial-certificate-g{generation}.json", certificate)
    _write_private_json(root / f"initial-certificate-state-g{generation}.json", projection)
    return checked, certificate, activated, binding, manifest


def _close_control(process: _Process, token_path: Path) -> None:
    try:
        process.close()
    finally:
        token_path.unlink(missing_ok=True)


def run(
    *,
    protected_cell_binary: Path,
    baseline_cell_binary: Path,
    guest_binary: Path,
    payload: Path,
    payload_result: Path,
    claude_binary: Path,
    claude_sha256: str,
    busybox: Path,
    control_binary: Path,
    effect_proxy_binary: Path,
    deathstar_adapter_binary: Path,
    frontend_url: str,
    effect_address: tuple[str, int],
    observer_url: str,
    adapter_audit: Path,
    fence_directory: Path,
    graph_evidence: Path,
    evidence_dir: Path | None,
    repetitions: int,
) -> dict[str, Any]:
    if repetitions < 1 or repetitions > 5:
        raise DemoError("repetitions must be between one and five")
    if _sha256_file(claude_binary) != claude_sha256:
        raise DemoError("official Claude artifact hash differs")
    graph = json.loads(graph_evidence.read_bytes())
    if graph.get("pass") is not True or graph.get("official_services") != 24:
        raise DemoError("DeathStarBench graph evidence is incomplete")
    payload_sha256, busybox_sha256, bash_sha256 = _load_http_payload(
        payload_result, payload, claude_sha256, busybox
    )
    payload_record = json.loads(payload_result.read_bytes())
    relay_sha256 = payload_record["inputs"]["mcp_operation_relay"]["sha256"]

    root = _private_directory(evidence_dir)
    transport = Path(tempfile.mkdtemp(prefix="fc-history-", dir="/tmp"))
    os.chmod(transport, 0o700)
    live_cells = transport / "cells"
    live_cells.mkdir(mode=0o700)
    started_time_ns = time.time_ns()
    progress_path = root / "progress.json"
    protected: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    baseline: list[dict[str, Any]] = []
    cells: list[_ClaudeCell] = []
    processes: list[_Process] = []
    source_generation = 1
    replacement_generation = 2
    effect_url = f"http://{effect_address[0]}:{effect_address[1]}/v1/reserve"
    finish = _FinishServer(_reserve_loopback_port())
    before, after = _requirements(effect_url, observer_url, finish.url)
    _write_private_json(root / "requirement-v1.json", before)
    _write_private_json(root / "requirement-v2.json", after)
    _write_private_json(
        root / "run-manifest.json",
        {
            "schema": 1,
            "requirement_v1_sha256": sha256(_canonical(before)).hexdigest(),
            "requirement_v2_sha256": sha256(_canonical(after)).hexdigest(),
            "protected_cell_sha256": _sha256_file(protected_cell_binary),
            "baseline_cell_sha256": _sha256_file(baseline_cell_binary),
            "guest_sha256": _sha256_file(guest_binary),
            "payload_sha256": payload_sha256,
            "claude_sha256": claude_sha256,
            "busybox_sha256": busybox_sha256,
            "bash_sha256": bash_sha256,
            "effect_url": effect_url,
            "observer_url": observer_url,
            "repetitions": repetitions,
        },
    )

    def progress(stage: str, status: str = "running", error: str | None = None) -> None:
        now = time.time_ns()
        value: dict[str, Any] = {
            "schema": 1,
            "status": status,
            "stage": stage,
            "started_time_ns": started_time_ns,
            "updated_time_ns": now,
            "elapsed_seconds": (now - started_time_ns) / 1_000_000_000,
            "repetitions": repetitions,
        }
        if error is not None:
            value["error"] = error
        _replace_private_json(progress_path, value)

    progress("initialized")
    try:
        with DeterministicBashAnthropicServer(_bash_command()) as model:
            model_target = model.base_url.removeprefix("http://")
            for repetition in range(1, repetitions + 1):
                progress(f"run-{repetition}-h1")
                h1 = root / "runs" / f"run-{repetition}" / "h1"
                h1.mkdir(mode=0o700, parents=True)
                effect = _start_effect(
                    deathstar_adapter_binary,
                    effect_address,
                    frontend_url,
                    adapter_audit,
                    fence_directory,
                    h1,
                    "effect-h1",
                    abort=False,
                )
                control, control_url, token, sandbox, token_path = _start_control(
                    control_binary, h1, transport / f"run-{repetition}-h1-sockets"
                )
                processes.extend([effect, control])
                route = h1 / "route.json"
                _write_route(route, effect_url)
                _, _, _, source_binding, source_manifest = _initial_activation(
                    root=h1,
                    control_url=control_url,
                    token=token,
                    requirement=before,
                    generation=source_generation,
                    endpoint=sandbox,
                    token_path=token_path,
                )
                source_proxy, _, source_origin = _start_proxy(
                    effect_proxy_binary, route, sandbox, h1, "source-proxy"
                )
                processes.append(source_proxy)
                session = secrets.token_hex(16)
                operation_id = _operation_id(session)
                h1_model_request = len(model.requests) + 1
                source = _new_cell(
                    label=f"h1-{repetition}-source",
                    generation=source_generation,
                    session=session,
                    target=source_origin,
                    model_target=model_target,
                    root=root,
                    live_cells=live_cells,
                    cell_binary=protected_cell_binary,
                    guest_binary=guest_binary,
                    payload=payload,
                    payload_sha256=payload_sha256,
                    claude_sha256=claude_sha256,
                    relay_sha256=relay_sha256,
                    busybox_sha256=busybox_sha256,
                    bash_sha256=bash_sha256,
                    launch_manifest=source_manifest,
                )
                cells.append(source)
                source.wait_ready()
                _wait_model_request(model, h1_model_request, "H1 source")
                delivery = _wait_delivery(adapter_audit, operation_id, 1)[0]
                operation = _wait_operation(control_url, token, operation_id, "dispatched")
                observation = _observer_query(
                    observer_url, operation_id, operation["request_hash"]
                )
                if observation["count"] != 1:
                    raise DemoError("H1 Mongo result is absent")
                source.kill_vmm()
                _archive_cell(source, root)
                zero_response = _assert_zero_response(source)
                _wait_operation(control_url, token, operation_id, "unknown")
                unknown = _http("GET", control_url + "/v1/state", token=token)[1]
                _write_private_json(h1 / "unknown-state.json", unknown)
                recovered = _http(
                    "POST",
                    control_url + f"/v1/operations/{operation_id}/recover",
                    token=token,
                )[1]
                if recovered.get("phase") != "succeeded":
                    raise DemoError("H1 recovery did not settle success")
                checked, certificate, projection = _compile(control_url, token, after)
                if certificate.get("decision") != "activate":
                    raise DemoError("H1 target did not activate")
                replacement_binding = _binding(replacement_generation)
                activated = _cutover(control_url, token, certificate, replacement_binding)
                replacement_manifest = h1 / "replacement-launch.json"
                _write_launch_manifest(
                    replacement_manifest,
                    checked,
                    certificate,
                    activated["history"],
                    replacement_binding,
                    sandbox,
                    control_url,
                    token_path,
                )
                _write_private_json(h1 / "target-certificate.json", certificate)
                _write_private_json(h1 / "target-certificate-state.json", projection)
                replacement_proxy, _, replacement_origin = _start_proxy(
                    effect_proxy_binary, route, sandbox, h1, "replacement-proxy"
                )
                processes.append(replacement_proxy)
                replacement = _new_cell(
                    label=f"h1-{repetition}-replacement",
                    generation=replacement_generation,
                    session=session,
                    target=replacement_origin,
                    model_target=model_target,
                    root=root,
                    live_cells=live_cells,
                    cell_binary=protected_cell_binary,
                    guest_binary=guest_binary,
                    payload=payload,
                    payload_sha256=payload_sha256,
                    claude_sha256=claude_sha256,
                    relay_sha256=relay_sha256,
                    busybox_sha256=busybox_sha256,
                    bash_sha256=bash_sha256,
                    launch_manifest=replacement_manifest,
                )
                cells.append(replacement)
                replacement.wait_ready()
                replacement.wait_success()
                _archive_cell(replacement, root)
                final = _observer_query(
                    observer_url, operation_id, operation["request_hash"]
                )
                if final["count"] != 1 or _delivery_count(adapter_audit, operation_id) != 1:
                    raise DemoError("H1 replacement duplicated the reservation")
                protected.append(
                    {
                        "run": repetition,
                        "session": session,
                        "operation_id": operation_id,
                        "decision": "activate",
                        "source_binding": source_binding,
                        "replacement_binding": replacement_binding,
                        "source_zero_response": zero_response,
                        "mongo_rows": 1,
                        "deliveries": 1,
                        "task_completed": True,
                        "source": source.record(),
                        "replacement": replacement.record(),
                    }
                )
                for item in (replacement_proxy, source_proxy, effect):
                    item.close()
                    processes.remove(item)
                _close_control(control, token_path)
                processes.remove(control)

                progress(f"run-{repetition}-h0")
                h0 = root / "runs" / f"run-{repetition}" / "h0"
                h0.mkdir(mode=0o700, parents=True)
                effect = _start_effect(
                    deathstar_adapter_binary,
                    effect_address,
                    frontend_url,
                    adapter_audit,
                    fence_directory,
                    h0,
                    "effect-h0",
                    abort=True,
                )
                control, control_url, token, sandbox, token_path = _start_control(
                    control_binary, h0, transport / f"run-{repetition}-h0-sockets"
                )
                processes.extend([effect, control])
                route = h0 / "route.json"
                _write_route(route, effect_url)
                _, _, _, source_binding, source_manifest = _initial_activation(
                    root=h0,
                    control_url=control_url,
                    token=token,
                    requirement=before,
                    generation=source_generation,
                    endpoint=sandbox,
                    token_path=token_path,
                )
                source_proxy, _, source_origin = _start_proxy(
                    effect_proxy_binary, route, sandbox, h0, "source-proxy"
                )
                processes.append(source_proxy)
                session = secrets.token_hex(16)
                operation_id = _operation_id(session)
                h0_model_request = len(model.requests) + 1
                source = _new_cell(
                    label=f"h0-{repetition}-source",
                    generation=source_generation,
                    session=session,
                    target=source_origin,
                    model_target=model_target,
                    root=root,
                    live_cells=live_cells,
                    cell_binary=protected_cell_binary,
                    guest_binary=guest_binary,
                    payload=payload,
                    payload_sha256=payload_sha256,
                    claude_sha256=claude_sha256,
                    relay_sha256=relay_sha256,
                    busybox_sha256=busybox_sha256,
                    bash_sha256=bash_sha256,
                    launch_manifest=source_manifest,
                )
                cells.append(source)
                source.wait_ready()
                _wait_model_request(model, h0_model_request, "H0 source")
                fence = _wait_fence(_fence_path(fence_directory, operation_id), operation_id)
                observation = _observer_query(
                    observer_url, operation_id, fence["request_hash"]
                )
                if observation["count"] != 0 or observation["body"].get("outcome") != "failed":
                    raise DemoError("H0 external fact is not terminal zero-row failure")
                if _delivery_count(adapter_audit, operation_id) != 0:
                    raise DemoError("H0 source reached DeathStarBench")
                source.kill_vmm()
                _archive_cell(source, root)
                zero_response = _assert_zero_response(source)
                _wait_operation(control_url, token, operation_id, "unknown")
                unknown = _http("GET", control_url + "/v1/state", token=token)[1]
                _write_private_json(h0 / "unknown-state.json", unknown)
                recovered = _http(
                    "POST",
                    control_url + f"/v1/operations/{operation_id}/recover",
                    token=token,
                )[1]
                if recovered.get("phase") != "failed":
                    raise DemoError("H0 recovery did not settle failure")
                checked, certificate, projection = _compile(control_url, token, after)
                if certificate.get("decision") != "impossible":
                    raise DemoError("H0 target did not become impossible")
                _write_private_json(h0 / "target-certificate.json", certificate)
                _write_private_json(h0 / "target-certificate-state.json", projection)
                replacement_manifest = h0 / "replacement-launch.json"
                current = _http("GET", control_url + "/v1/state", token=token)[1]
                _write_launch_manifest(
                    replacement_manifest,
                    checked,
                    certificate,
                    current["history"],
                    source_binding,
                    sandbox,
                    control_url,
                    token_path,
                )
                before_model = len(model.requests)
                replacement = _new_cell(
                    label=f"h0-{repetition}-replacement",
                    generation=replacement_generation,
                    session=session,
                    target=source_origin,
                    model_target=model_target,
                    root=root,
                    live_cells=live_cells,
                    cell_binary=protected_cell_binary,
                    guest_binary=guest_binary,
                    payload=payload,
                    payload_sha256=payload_sha256,
                    claude_sha256=claude_sha256,
                    relay_sha256=relay_sha256,
                    busybox_sha256=busybox_sha256,
                    bash_sha256=bash_sha256,
                    launch_manifest=replacement_manifest,
                )
                cells.append(replacement)
                replacement.wait_denied()
                _archive_cell(replacement, root)
                denied = _assert_denied_replacement(replacement)
                if len(model.requests) != before_model:
                    raise DemoError("H0 denied replacement reached the model")
                final = _observer_query(
                    observer_url, operation_id, fence["request_hash"]
                )
                if final["count"] != 0 or _delivery_count(adapter_audit, operation_id) != 0:
                    raise DemoError("H0 denied replacement changed the application")
                rejected.append(
                    {
                        "run": repetition,
                        "session": session,
                        "operation_id": operation_id,
                        "decision": "impossible",
                        "source_binding": source_binding,
                        "source_zero_response": zero_response,
                        "terminal_fence": fence,
                        "mongo_rows": 0,
                        "deliveries": 0,
                        "task_completed": False,
                        "source": source.record(),
                        "replacement": replacement.record(),
                        "denied": denied,
                    }
                )
                for item in (source_proxy, effect):
                    item.close()
                    processes.remove(item)
                _close_control(control, token_path)
                processes.remove(control)

                progress(f"run-{repetition}-baseline")
                native = root / "runs" / f"run-{repetition}" / "baseline"
                native.mkdir(mode=0o700, parents=True)
                effect = _start_effect(
                    deathstar_adapter_binary,
                    effect_address,
                    frontend_url,
                    adapter_audit,
                    fence_directory,
                    native,
                    "effect-baseline",
                    abort=False,
                )
                processes.append(effect)
                session = secrets.token_hex(16)
                operation_id = session
                source = _new_cell(
                    label=f"baseline-{repetition}-source",
                    generation=source_generation,
                    session=session,
                    target=effect_url.removesuffix("/v1/reserve"),
                    model_target=model_target,
                    root=root,
                    live_cells=live_cells,
                    cell_binary=baseline_cell_binary,
                    guest_binary=guest_binary,
                    payload=payload,
                    payload_sha256=payload_sha256,
                    claude_sha256=claude_sha256,
                    relay_sha256=relay_sha256,
                    busybox_sha256=busybox_sha256,
                    bash_sha256=bash_sha256,
                    launch_manifest=None,
                )
                cells.append(source)
                source.wait_ready()
                delivery = _wait_delivery(adapter_audit, operation_id, 1)[0]
                observation = _observer_query(observer_url, operation_id, "0" * 64)
                if observation["count"] != 1:
                    raise DemoError("baseline source reservation is absent")
                source.kill_vmm()
                _archive_cell(source, root)
                zero_response = _assert_zero_response(source)
                replacement = _new_cell(
                    label=f"baseline-{repetition}-replacement",
                    generation=replacement_generation,
                    session=session,
                    target=effect_url.removesuffix("/v1/reserve"),
                    model_target=model_target,
                    root=root,
                    live_cells=live_cells,
                    cell_binary=baseline_cell_binary,
                    guest_binary=guest_binary,
                    payload=payload,
                    payload_sha256=payload_sha256,
                    claude_sha256=claude_sha256,
                    relay_sha256=relay_sha256,
                    busybox_sha256=busybox_sha256,
                    bash_sha256=bash_sha256,
                    launch_manifest=None,
                )
                cells.append(replacement)
                replacement.wait_ready()
                replacement.wait_success()
                _archive_cell(replacement, root)
                _wait_delivery(adapter_audit, operation_id, 2)
                final = _observer_query(observer_url, operation_id, "0" * 64)
                if final["count"] != 2:
                    raise DemoError("unguarded baseline did not duplicate")
                baseline.append(
                    {
                        "run": repetition,
                        "session": session,
                        "operation_id": operation_id,
                        "decision": "baseline-unguarded",
                        "source_zero_response": zero_response,
                        "first_delivery": delivery,
                        "mongo_rows": 2,
                        "deliveries": 2,
                        "task_completed": True,
                        "source": source.record(),
                        "replacement": replacement.record(),
                    }
                )
                effect.close()
                processes.remove(effect)

            requests = [asdict(request) for request in model.requests]
            _write_private_json(root / "anthropic-requests.json", requests)
            if model.failure is not None:
                raise DemoError(f"model fixture failed: {model.failure}")

        observer_facts = _http(
            "GET", observer_url.removesuffix("/v1/query") + "/v1/stats/facts"
        )[1]
        _write_private_json(root / "observer-facts.json", observer_facts)
        result = {
            "schema": 1,
            "valid": (
                len(protected) == repetitions
                and len(rejected) == repetitions
                and len(baseline) == repetitions
                and all(item["mongo_rows"] == 1 for item in protected)
                and all(item["mongo_rows"] == 0 for item in rejected)
                and all(item["mongo_rows"] == 2 for item in baseline)
            ),
            "system": "history-authorized-firecracker-instance-start",
            "repetitions": repetitions,
            "protected": protected,
            "rejected": rejected,
            "baseline": baseline,
            "graph": graph,
            "artifacts": {
                "protected_cell": _sha256_file(protected_cell_binary),
                "baseline_cell": _sha256_file(baseline_cell_binary),
                "guest": _sha256_file(guest_binary),
                "payload": payload_sha256,
                "claude": claude_sha256,
                "control": _sha256_file(control_binary),
                "effect_proxy": _sha256_file(effect_proxy_binary),
                "deathstar_adapter": _sha256_file(deathstar_adapter_binary),
            },
            "model_requests": len(requests),
        }
        if result["artifacts"]["protected_cell"] == result["artifacts"]["baseline_cell"]:
            raise DemoError("protected and baseline cell hashes are identical")
        if not result["valid"]:
            raise DemoError("Firecracker History matrix is incomplete")
        _write_private_json(root / "result.json", result)
        progress("complete", status="complete")
        return result
    except BaseException as error:
        progress("failed", status="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        for cell in reversed(cells):
            cell.close()
            if cell.evidence.is_relative_to(live_cells) and cell.evidence.exists():
                _archive_cell(cell, root)
        for process in reversed(processes):
            process.close()
        finish.close()
        shutil.rmtree(transport, ignore_errors=True)
        for path in root.rglob("admin.token"):
            path.unlink(missing_ok=True)


def _path(value: str) -> Path:
    return Path(value).resolve(strict=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protected-cell-binary", required=True)
    parser.add_argument("--baseline-cell-binary", required=True)
    parser.add_argument("--guest-binary", required=True)
    parser.add_argument("--payload", required=True)
    parser.add_argument("--payload-result", required=True)
    parser.add_argument("--claude-binary", required=True)
    parser.add_argument("--claude-sha256", required=True)
    parser.add_argument("--busybox", required=True)
    parser.add_argument("--control-binary", required=True)
    parser.add_argument("--effect-proxy-binary", required=True)
    parser.add_argument("--deathstar-adapter-binary", required=True)
    parser.add_argument("--frontend-url", required=True)
    parser.add_argument("--effect-address", required=True)
    parser.add_argument("--observer-url", required=True)
    parser.add_argument("--adapter-audit", required=True)
    parser.add_argument("--fence-directory", required=True)
    parser.add_argument("--graph-evidence", required=True)
    parser.add_argument("--evidence-dir")
    parser.add_argument("--repetitions", type=int, default=3)
    args = parser.parse_args()
    try:
        host, port = args.effect_address.rsplit(":", 1)
        if host != "127.0.0.1" or not port.isdigit() or not 0 < int(port) < 65536:
            raise DemoError("effect address must be explicit loopback host:port")
        binaries = {
            "protected cell": _path(args.protected_cell_binary),
            "baseline cell": _path(args.baseline_cell_binary),
            "guest": _path(args.guest_binary),
            "Claude": _path(args.claude_binary),
            "Control": _path(args.control_binary),
            "effect proxy": _path(args.effect_proxy_binary),
            "DeathStar adapter": _path(args.deathstar_adapter_binary),
        }
        for label, path in binaries.items():
            _owned_executable(path, label)
        result = run(
            protected_cell_binary=binaries["protected cell"],
            baseline_cell_binary=binaries["baseline cell"],
            guest_binary=binaries["guest"],
            payload=_path(args.payload),
            payload_result=_path(args.payload_result),
            claude_binary=binaries["Claude"],
            claude_sha256=args.claude_sha256,
            busybox=_path(args.busybox),
            control_binary=binaries["Control"],
            effect_proxy_binary=binaries["effect proxy"],
            deathstar_adapter_binary=binaries["DeathStar adapter"],
            frontend_url=args.frontend_url,
            effect_address=(host, int(port)),
            observer_url=args.observer_url,
            adapter_audit=_path(args.adapter_audit),
            fence_directory=_path(args.fence_directory),
            graph_evidence=_path(args.graph_evidence),
            evidence_dir=(
                None
                if args.evidence_dir is None
                else Path(args.evidence_dir).resolve(strict=False)
            ),
            repetitions=args.repetitions,
        )
    except (DemoError, OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(f"Firecracker History start demo failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
