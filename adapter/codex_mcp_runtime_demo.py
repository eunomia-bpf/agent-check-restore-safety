"""Run real Codex against the host-durable MCP continuity boundary.

The model endpoint is deterministic and loopback-only; Codex App Server, MCP
stdio, Control/History, the sandbox-bound Unix endpoint, and the external
payment service are real processes.  The first provider response is dropped
after commit.  Codex and its MCP child are then restarted, the same model tool
call is replayed, and a second distinct call is issued.
"""

from __future__ import annotations

import argparse
import base64
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import stat
import subprocess
import tempfile
import time
from typing import Any, BinaryIO, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from .app_server import CodexAppServer, MCPStdioServer
from .mock_responses import DeterministicResponsesServer, RecordedRequest


_MAX_HTTP_BYTES = 16 << 20
_SANDBOX_ID = "codex-mcp"
_MCP_NAME = "continuity"
_TOOL_NAME = "commit_effect"
_EXECUTION_ID = "codex-mcp-execution-v1"


class DemoError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        while block := source.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


def _owned_executable(value: str | os.PathLike[str], label: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or path.resolve() != path:
        raise DemoError(f"{label} must be an absolute canonical path")
    try:
        info = path.lstat()
    except OSError as error:
        raise DemoError(f"cannot inspect {label}") from error
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) & 0o022
        or not os.access(path, os.X_OK)
    ):
        raise DemoError(f"{label} must be a current-user trusted executable")
    return path


def _private_directory(value: Path | None) -> Path:
    if value is None:
        return Path(tempfile.mkdtemp(prefix="codex-mcp-runtime-"))
    path = value.resolve()
    if not path.exists():
        path.mkdir(mode=0o700, parents=True)
    info = path.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise DemoError("evidence directory must be a private current-user directory")
    if any(path.iterdir()):
        raise DemoError("evidence directory must be empty")
    return path


def _write_private_json(path: Path, value: Any) -> None:
    encoded = (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as output:
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
    finally:
        os.close(descriptor)


def _reserve_loopback_port() -> int:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])
    finally:
        listener.close()


class _Process:
    def __init__(self, name: str, command: list[str], root: Path) -> None:
        self.name = name
        self.command = command
        self._stdout: BinaryIO = (root / f"{name}.stdout.log").open("xb")
        os.chmod(self._stdout.name, 0o600)
        self._stderr: BinaryIO = (root / f"{name}.stderr.log").open("xb")
        os.chmod(self._stderr.name, 0o600)
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=self._stdout,
            stderr=self._stderr,
            cwd=root,
            start_new_session=True,
        )

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        self._stdout.close()
        self._stderr.close()
        if self.process.returncode not in {0, -15}:
            raise DemoError(f"{self.name} exited with {self.process.returncode}")


def _http_json(
    method: str,
    url: str,
    *,
    value: Mapping[str, Any] | None = None,
    token: str | None = None,
) -> dict[str, Any]:
    data = None
    headers: dict[str, str] = {}
    if value is not None:
        data = json.dumps(
            dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token is not None:
        headers["Authorization"] = "Bearer " + token
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with build_opener(ProxyHandler({})).open(request, timeout=10) as response:
            body = response.read(_MAX_HTTP_BYTES + 1)
            status = response.status
    except HTTPError as error:
        detail = error.read(4096).decode("utf-8", "replace")
        raise DemoError(f"{method} {url} returned HTTP {error.code}: {detail}") from error
    except (OSError, URLError) as error:
        raise DemoError(f"{method} {url} failed") from error
    if status != 200 or len(body) > _MAX_HTTP_BYTES:
        raise DemoError(f"{method} {url} returned an invalid response")
    try:
        result = json.loads(body)
    except json.JSONDecodeError as error:
        raise DemoError(f"{method} {url} returned invalid JSON") from error
    if not isinstance(result, dict):
        raise DemoError(f"{method} {url} did not return an object")
    return result


def _wait_healthy(origin: str, process: _Process) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.process.poll() is not None:
            raise DemoError(f"{process.name} exited before becoming healthy")
        try:
            result = _http_json("GET", origin + "/healthz")
        except DemoError:
            time.sleep(0.05)
            continue
        if result.get("status") == "ok":
            return
    raise DemoError(f"{process.name} did not become healthy")


def _read_token(path: Path) -> str:
    info = path.lstat()
    value = path.read_text(encoding="utf-8").strip()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o600
        or len(value) < 32
        or any(character.isspace() for character in value)
    ):
        raise DemoError("Control emitted an invalid admin token")
    return value


def _sandbox_socket(root: Path) -> Path:
    name = "sandbox-" + sha256(_SANDBOX_ID.encode("utf-8")).hexdigest()[:32] + ".sock"
    return root / name


def _requirement(payment_origin: str) -> dict[str, Any]:
    return {
        "id": "real-codex-mcp-restart",
        "results": {"committed": 2},
        "capacities": {"external-write": 2},
        "kinds": {
            "protected_commit": {
                "costs": {"external-write": 1},
                "produces": {"committed": 1},
                "retry_safe": False,
                "queryable": True,
                "target": payment_origin + "/v1/charge",
                "method": "POST",
                "response_classifier": "operation-receipt-v1",
                "query_target": payment_origin + "/v1/query",
                "query_method": "POST",
                "query_classifier": "operation-observation-v1",
            }
        },
    }


def _wait_mcp_ready(client: CodexAppServer, thread_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 15
    last: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        event = client.wait_for_message(
            lambda message: (
                message.get("method") == "mcpServer/startupStatus/updated"
                and isinstance(message.get("params"), dict)
                and message["params"].get("name") == _MCP_NAME
                and message["params"].get("threadId") == thread_id
            ),
            description="configured MCP startup status",
            timeout=max(0.1, deadline - time.monotonic()),
        )
        last = event
        status = event["params"].get("status")
        if status in {"ready", "completed"}:
            return event
        if status in {"failed", "error"}:
            raise DemoError("Codex reported MCP startup failure: " + json.dumps(event))
    raise DemoError("Codex did not report a ready MCP server: " + json.dumps(last))


def _find_mcp_tool(request: RecordedRequest) -> tuple[str, dict[str, Any]]:
    body = request.body
    metadata = body.get("client_metadata") if isinstance(body, dict) else None
    encoded = metadata.get("x-codex-turn-metadata") if isinstance(metadata, dict) else None
    if not isinstance(encoded, str):
        raise DemoError("Codex model request omitted code-mode tool metadata")
    try:
        turn_metadata = json.loads(encoded)
    except json.JSONDecodeError as error:
        raise DemoError("Codex emitted malformed code-mode tool metadata") from error
    names = turn_metadata.get("code_mode_tool_names") if isinstance(turn_metadata, dict) else None
    if not isinstance(names, dict):
        raise DemoError("Codex model request omitted code-mode tool names")
    matches = [
        (callable_name, descriptor)
        for callable_name, descriptor in names.items()
        if isinstance(callable_name, str)
        and _TOOL_NAME in callable_name
        and isinstance(descriptor, dict)
    ]
    if len(matches) != 1:
        raise DemoError(f"expected one MCP code-mode tool, observed {matches!r}")
    callable_name, descriptor = matches[0]
    if descriptor != {"name": _TOOL_NAME, "namespace": "mcp__" + _MCP_NAME}:
        raise DemoError(f"Codex exposed a different MCP identity: {descriptor!r}")
    return callable_name, descriptor


def _enqueue_operation(
    responses: DeterministicResponsesServer,
    *,
    callable_name: str,
    effect_id: str,
    call_id: str,
    final_text: str,
) -> None:
    arguments = json.dumps(
        {"effect_id": effect_id}, sort_keys=True, separators=(",", ":")
    )
    responses.enqueue_custom_tool_call(
        "exec",
        f"const outcome = await tools.{callable_name}({arguments}); text(outcome);",
        call_id=call_id,
    )
    responses.enqueue_assistant(final_text)


def _decode_operation_body(operation: Mapping[str, Any]) -> dict[str, Any]:
    encoded = operation.get("request_body")
    if not isinstance(encoded, str):
        raise DemoError("History operation omitted its retained request")
    try:
        value = json.loads(base64.b64decode(encoded, validate=True))
    except (ValueError, json.JSONDecodeError) as error:
        raise DemoError("History retained a malformed operation request") from error
    if not isinstance(value, dict):
        raise DemoError("History operation request is not an object")
    return value


def _raw_mcp_completions(path: Path) -> list[dict[str, Any]]:
    completions: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        payload = record.get("payload") if isinstance(record, dict) else None
        params = payload.get("params") if isinstance(payload, dict) else None
        item = params.get("item") if isinstance(params, dict) else None
        if (
            payload.get("method") == "item/completed"
            and isinstance(item, dict)
            and item.get("type") == "mcpToolCall"
        ):
            completions.append(item)
    return completions


def run(
    *,
    workspace: Path,
    evidence_dir: Path | None,
    codex_binary: Path,
    control_binary: Path,
    payment_binary: Path,
    mcp_binary: Path,
    tools_config: Path,
) -> dict[str, Any]:
    workspace = workspace.resolve()
    if not workspace.is_dir():
        raise DemoError("workspace must be an existing directory")
    root = _private_directory(evidence_dir)
    sockets = root / "sockets"
    sockets.mkdir(mode=0o700)
    control_port = _reserve_loopback_port()
    payment_port = _reserve_loopback_port()
    control_origin = f"http://127.0.0.1:{control_port}"
    payment_origin = f"http://127.0.0.1:{payment_port}"
    admin_token_path = root / "admin.token"
    history_path = root / "control.history"
    payment_history_path = root / "payment.history"
    journal_path = root / "mcp-calls.jsonl"
    socket_path = _sandbox_socket(sockets)

    processes: list[_Process] = []
    try:
        payment = _Process(
            "payment",
            [
                os.fspath(payment_binary),
                "-listen",
                f"127.0.0.1:{payment_port}",
                "-state",
                os.fspath(payment_history_path),
                "-drop-first-response",
                "-non-idempotent",
                "-reference-prefix",
                "codex-mcp",
            ],
            root,
        )
        processes.append(payment)
        _wait_healthy(payment_origin, payment)
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
                os.fspath(admin_token_path),
                "-sandbox-socket-dir",
                os.fspath(sockets),
            ],
            root,
        )
        processes.append(control)
        _wait_healthy(control_origin, control)
        token = _read_token(admin_token_path)
        certificate = _http_json(
            "POST",
            control_origin + "/v1/compile",
            value=_requirement(payment_origin),
            token=token,
        )
        if certificate.get("decision") != "activate":
            raise DemoError("Control refused the real Codex MCP requirement")
        binding = {
            "sandbox_id": _SANDBOX_ID,
            "generation": 1,
            "host_instance_id": "host-" + secrets.token_hex(16),
            "domain": "codex-mcp-runtime",
            "allowed_kinds": ["protected_commit"],
        }
        cutover = _http_json(
            "POST",
            control_origin + "/v1/cutover",
            value={"certificate": certificate, "bindings": [binding]},
            token=token,
        )
        if cutover.get("bindings") != [binding] or not socket_path.is_socket():
            raise DemoError("Control did not publish the expected sandbox endpoint")

        mcp = MCPStdioServer(
            name=_MCP_NAME,
            command=mcp_binary,
            args=(
                "-config",
                os.fspath(tools_config),
                "-sandbox-socket",
                os.fspath(socket_path),
                "-execution-id",
                _EXECUTION_ID,
                "-journal",
                os.fspath(journal_path),
            ),
            enabled_tools=(_TOOL_NAME,),
        )
        raw_first = root / "codex-first.jsonl"
        raw_second = root / "codex-second.jsonl"
        statuses: list[dict[str, Any]] = []

        with DeterministicResponsesServer() as responses:
            responses.enqueue_assistant("MCP tool discovered.")
            first_client = CodexAppServer(
                model_base_url=responses.base_url,
                workspace=workspace,
                raw_jsonl_path=raw_first,
                codex_binary=os.fspath(codex_binary),
                mcp_server=mcp,
            )
            with first_client:
                first_thread = first_client.create_mcp_thread()
                statuses.append(_wait_mcp_ready(first_client, first_thread["id"]))
                first_client.start_turn_and_wait(
                    first_thread["id"], "Report the available protected operation."
                )
                model_requests = [
                    request
                    for request in responses.requests
                    if request.method == "POST" and request.path.endswith("/responses")
                ]
                if len(model_requests) != 1:
                    raise DemoError("tool discovery did not make exactly one model request")
                _write_private_json(root / "discovery-request.json", model_requests[0].body)
                callable_name, descriptor = _find_mcp_tool(model_requests[0])
                _enqueue_operation(
                    responses,
                    callable_name=callable_name,
                    effect_id="effect-A",
                    call_id="stable-model-call-A",
                    final_text="First operation completed.",
                )
                first_client.start_turn_and_wait(
                    first_thread["id"], "Commit effect-A using the protected operation."
                )
                first_client.assert_hermetic_runtime()

            after_first = _http_json("GET", payment_origin + "/v1/stats")
            if after_first.get("deliveries") != 1 or after_first.get("commits") != 1:
                raise DemoError(f"first lost-response recovery was not single-commit: {after_first}")

            second_client = CodexAppServer(
                model_base_url=responses.base_url,
                workspace=workspace,
                raw_jsonl_path=raw_second,
                codex_binary=os.fspath(codex_binary),
                mcp_server=mcp,
            )
            with second_client:
                second_thread = second_client.create_mcp_thread()
                statuses.append(_wait_mcp_ready(second_client, second_thread["id"]))
                _enqueue_operation(
                    responses,
                    callable_name=callable_name,
                    effect_id="effect-A",
                    call_id="stable-model-call-A",
                    final_text="Replayed operation completed.",
                )
                second_client.start_turn_and_wait(
                    second_thread["id"], "Resume and complete the interrupted effect-A call."
                )
                _enqueue_operation(
                    responses,
                    callable_name=callable_name,
                    effect_id="effect-B",
                    call_id="stable-model-call-B",
                    final_text="Second operation completed.",
                )
                second_client.start_turn_and_wait(
                    second_thread["id"], "Now commit the distinct effect-B call."
                )
                second_client.assert_hermetic_runtime()
            responses.assert_consumed()
            response_requests = [
                {
                    "ordinal": request.ordinal,
                    "method": request.method,
                    "path": request.path,
                    "body": request.body,
                }
                for request in responses.requests
                if request.method == "POST" and request.path.endswith("/responses")
            ]
            if len(response_requests) != 7:
                raise DemoError(
                    f"expected seven deterministic model requests, observed {len(response_requests)}"
                )
            _write_private_json(root / "responses.json", response_requests)

        state = _http_json("GET", control_origin + "/v1/state", token=token)
        stats = _http_json("GET", payment_origin + "/v1/stats")
        operations = state.get("operations")
        if not isinstance(operations, dict) or len(operations) != 2:
            raise DemoError(f"History did not retain exactly two Operations: {operations!r}")
        by_effect: dict[str, dict[str, Any]] = {}
        for operation in operations.values():
            if not isinstance(operation, dict):
                raise DemoError("History contains a malformed Operation")
            body = _decode_operation_body(operation)
            effect_id = body.get("effect_id")
            if not isinstance(effect_id, str) or effect_id in by_effect:
                raise DemoError("History contains ambiguous effect identities")
            by_effect[effect_id] = operation
        if (
            set(by_effect) != {"effect-A", "effect-B"}
            or by_effect["effect-A"].get("phase") != "succeeded"
            or by_effect["effect-A"].get("settlement") != "query"
            or by_effect["effect-B"].get("phase") != "succeeded"
            or by_effect["effect-B"].get("settlement") is not None
            or stats.get("deliveries") != 2
            or stats.get("commits") != 2
            or stats.get("paths", {}).get("/v1/charge") != 2
        ):
            raise DemoError(f"final invariant failed: effects={by_effect!r} stats={stats!r}")
        first_items = _raw_mcp_completions(raw_first)
        second_items = _raw_mcp_completions(raw_second)
        if len(first_items) != 1 or len(second_items) != 2:
            raise DemoError("real Codex did not emit the expected MCP tool items")
        for item in first_items + second_items:
            if item.get("server") != _MCP_NAME or item.get("tool") != _TOOL_NAME or item.get("status") != "completed":
                raise DemoError(f"Codex emitted an unsuccessful MCP item: {item!r}")

        result = {
            "schema": 1,
            "success": True,
            "system": "real-codex-mcp-continuity",
            "execution_id": _EXECUTION_ID,
            "tool_descriptor": descriptor,
            "mcp_startup_statuses": statuses,
            "codex_processes": 2,
            "codex_mcp_items": len(first_items) + len(second_items),
            "history": state,
            "payment": stats,
            "artifacts": {
                "codex": {"path": os.fspath(codex_binary), "sha256": _sha256_file(codex_binary)},
                "control": {"path": os.fspath(control_binary), "sha256": _sha256_file(control_binary)},
                "payment": {"path": os.fspath(payment_binary), "sha256": _sha256_file(payment_binary)},
                "mcp": {"path": os.fspath(mcp_binary), "sha256": _sha256_file(mcp_binary)},
                "journal": {"path": os.fspath(journal_path), "sha256": _sha256_file(journal_path)},
                "first_raw": {"path": os.fspath(raw_first), "sha256": _sha256_file(raw_first)},
                "second_raw": {"path": os.fspath(raw_second), "sha256": _sha256_file(raw_second)},
                "responses": {
                    "path": os.fspath(root / "responses.json"),
                    "sha256": _sha256_file(root / "responses.json"),
                },
            },
        }
        _write_private_json(root / "result.json", result)
        return {"evidence": os.fspath(root), **result}
    finally:
        errors: list[BaseException] = []
        for process in reversed(processes):
            try:
                process.close()
            except BaseException as error:
                errors.append(error)
        if errors:
            raise DemoError("service shutdown failed: " + "; ".join(map(str, errors)))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--evidence-dir", type=Path)
    parser.add_argument("--codex-binary", default="codex")
    parser.add_argument("--control-binary", type=Path, required=True)
    parser.add_argument("--payment-binary", type=Path, required=True)
    parser.add_argument("--mcp-binary", type=Path, required=True)
    parser.add_argument(
        "--tools-config",
        type=Path,
        default=Path("runtime/deploy/mcp-operation/tools.json"),
    )
    args = parser.parse_args()
    codex = shutil.which(args.codex_binary)
    if codex is None:
        raise DemoError("Codex executable was not found")
    result = run(
        workspace=args.workspace,
        evidence_dir=args.evidence_dir,
        codex_binary=_owned_executable(Path(codex).resolve(), "Codex"),
        control_binary=_owned_executable(args.control_binary.resolve(), "Control"),
        payment_binary=_owned_executable(args.payment_binary.resolve(), "payment service"),
        mcp_binary=_owned_executable(args.mcp_binary.resolve(), "MCP server"),
        tools_config=args.tools_config.resolve(),
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
