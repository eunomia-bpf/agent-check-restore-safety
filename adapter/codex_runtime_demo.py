"""Run a real Codex tool call through the durable Go control boundary.

This is an explicit live-account experiment, not a unit test.  A logged-in
Codex model requests one application-chosen payment identity.  The payment
service commits and drops its first response, the control process is replaced
while Codex's tool callback remains pending, and the same Operation completes
without a second remote commit.
"""

from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from adapter.app_server import AppServerProtocolError, CodexAppServer


TOOL_NAME = "protected_payment"
EFFECT_ID = "codex-order-A-17"
CALL_ID = f"{TOOL_NAME}/v1/{EFFECT_ID}"
OPERATION_DOMAIN = "codex-app-server"
OPERATION_KIND = "charge-invoice"
MAX_HTTP_BYTES = 4 << 20
LIVE_TIMEOUT_SECONDS = 180.0


class DemoError(RuntimeError):
    """The live experiment failed a protocol or evidence check."""


@dataclass(frozen=True)
class HTTPResult:
    status: int
    body: Any


class ManagedProcess:
    """Small fail-closed supervisor that keeps service output out of pipes."""

    def __init__(self, name: str, command: Sequence[str], log_path: Path) -> None:
        self.name = name
        self.command = [str(value) for value in command]
        self.log_path = log_path
        self._process: subprocess.Popen[bytes] | None = None
        self._log: Any = None

    @property
    def pid(self) -> int:
        if self._process is None:
            raise DemoError(f"{self.name} has not started")
        return self._process.pid

    def poll(self) -> int | None:
        return None if self._process is None else self._process.poll()

    def start(self) -> "ManagedProcess":
        if self._process is not None:
            raise DemoError(f"{self.name} already started")
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log = self.log_path.open("wb")
        try:
            self._process = subprocess.Popen(
                self.command,
                stdin=subprocess.DEVNULL,
                stdout=self._log,
                stderr=subprocess.STDOUT,
                close_fds=True,
            )
        except BaseException:
            self._log.close()
            self._log = None
            raise
        return self

    def stop(self) -> None:
        process = self._process
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5.0)
        if self._log is not None:
            self._log.flush()
            os.fsync(self._log.fileno())
            self._log.close()
            self._log = None


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".next")
    with temporary.open("wb") as destination:
        destination.write(json.dumps(value, sort_keys=True, indent=2).encode("utf-8"))
        destination.write(b"\n")
        destination.flush()
        os.fsync(destination.fileno())
    os.replace(temporary, path)


def _http_json(
    url: str,
    *,
    method: str = "GET",
    token: str | None = None,
    payload: Mapping[str, Any] | None = None,
    expected: frozenset[int] = frozenset({200}),
    timeout: float = 15.0,
    require_object: bool = True,
) -> HTTPResult:
    data = None if payload is None else _canonical_json(payload)
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if token is not None:
        headers["Authorization"] = "Bearer " + token
    request = Request(url, data=data, headers=headers, method=method)
    opener = build_opener(ProxyHandler({}))
    try:
        response: Any = opener.open(request, timeout=timeout)
    except HTTPError as error:
        response = error
    try:
        body = response.read(MAX_HTTP_BYTES + 1)
        status = int(response.status)
    finally:
        response.close()
    if len(body) > MAX_HTTP_BYTES:
        raise DemoError(f"HTTP response from {url} exceeded the size limit")
    try:
        decoded = json.loads(body)
    except json.JSONDecodeError as error:
        raise DemoError(f"HTTP {status} from {url} was not JSON") from error
    if require_object and not isinstance(decoded, dict):
        raise DemoError(f"HTTP {status} from {url} was not a JSON object")
    if status not in expected:
        raise DemoError(f"unexpected HTTP {status} from {url}: {decoded}")
    return HTTPResult(status=status, body=decoded)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _tail(path: Path, limit: int = 4000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[-limit:]
    except OSError:
        return "<unavailable>"


def _wait_healthy(url: str, process: ManagedProcess, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    last_error = "not attempted"
    while time.monotonic() < deadline:
        code = process.poll()
        if code is not None:
            raise DemoError(
                f"{process.name} exited with {code} before health: {_tail(process.log_path)}"
            )
        try:
            result = _http_json(url, timeout=1.0)
            if result.body.get("status") == "ok":
                return
            last_error = f"unexpected health body {result.body}"
        except (DemoError, URLError, OSError) as error:
            last_error = str(error)
        time.sleep(0.1)
    raise DemoError(f"timed out waiting for {url}: {last_error}")


def _read_private_token(path: Path) -> str:
    info = path.stat()
    if not path.is_file() or info.st_mode & 0o077:
        raise DemoError(f"token file is not private: {path}")
    token = path.read_text(encoding="utf-8").strip()
    if len(token) < 32:
        raise DemoError(f"token file is too short: {path}")
    return token


def _operation_id() -> str:
    digest = sha256()
    digest.update(b"operation-id-v1\x00")
    digest.update(OPERATION_DOMAIN.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(CALL_ID.encode("utf-8"))
    return "op-" + digest.hexdigest()


def _decode_receipt(outcome: Mapping[str, Any]) -> dict[str, Any]:
    encoded = outcome.get("body")
    if not isinstance(encoded, str):
        raise DemoError("successful runtime outcome omitted its receipt body")
    try:
        raw = base64.b64decode(encoded, validate=True)
        receipt = json.loads(raw)
    except (ValueError, json.JSONDecodeError) as error:
        raise DemoError("runtime receipt body is not canonical base64 JSON") from error
    if not isinstance(receipt, dict):
        raise DemoError("runtime receipt is not a JSON object")
    return receipt


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        while block := source.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise DemoError(f"invalid App Server JSONL line {line_number}") from error
            if not isinstance(value, dict):
                raise DemoError(f"App Server JSONL line {line_number} is not an object")
            records.append(value)
    if [record.get("sequence") for record in records] != list(
        range(1, len(records) + 1)
    ):
        raise DemoError("App Server JSONL sequence is not contiguous")
    return records


def _protocol_evidence(
    path: Path,
    *,
    thread_id: str,
    turn_id: str,
    provider_call_id: str,
    callback_request_id: int | str,
    expected_tool: str = TOOL_NAME,
    expected_arguments: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if expected_arguments is None:
        expected_arguments = {"effect_id": EFFECT_ID}
    records = _read_jsonl(path)
    payloads = [
        (record.get("direction"), record.get("payload")) for record in records
    ]
    starts = [
        payload
        for direction, payload in payloads
        if direction == "meta"
        and isinstance(payload, dict)
        and payload.get("event") == "process_start"
    ]
    if len(starts) != 1 or not isinstance(starts[0].get("command"), list):
        raise DemoError("raw protocol omitted the App Server process command")
    command_text = json.dumps(starts[0]["command"], sort_keys=True)
    if "model_providers" in command_text or "authority_continuity_mock" in command_text:
        raise DemoError("live App Server unexpectedly installed the test provider")

    thread_starts = [
        payload
        for direction, payload in payloads
        if direction == "client_to_server"
        and isinstance(payload, dict)
        and payload.get("method") == "thread/start"
    ]
    if len(thread_starts) != 1:
        raise DemoError(f"expected one thread/start, observed {len(thread_starts)}")
    thread_start_id = thread_starts[0].get("id")
    thread_start_responses = [
        payload
        for direction, payload in payloads
        if direction == "server_to_client"
        and isinstance(payload, dict)
        and payload.get("id") == thread_start_id
        and isinstance(payload.get("result"), dict)
    ]
    if len(thread_start_responses) != 1:
        raise DemoError("raw protocol omitted the thread/start response")
    thread_result = thread_start_responses[0]["result"]
    model = thread_result.get("model")
    model_provider = thread_result.get("modelProvider")
    sandbox = thread_result.get("sandbox")
    if (
        not isinstance(model, str)
        or not isinstance(model_provider, str)
        or model_provider == "authority_continuity_mock"
        or not isinstance(sandbox, dict)
        or sandbox.get("type") != "readOnly"
        or sandbox.get("networkAccess") is not False
        or thread_result.get("approvalPolicy") != "never"
    ):
        raise DemoError("live thread did not retain the required account and sandbox boundary")

    tool_calls = [
        payload
        for direction, payload in payloads
        if direction == "server_to_client"
        and isinstance(payload, dict)
        and payload.get("method") == "item/tool/call"
        and payload.get("params", {}).get("threadId") == thread_id
        and payload.get("params", {}).get("turnId") == turn_id
    ]
    if len(tool_calls) != 1:
        raise DemoError(f"expected one Codex tool call, observed {len(tool_calls)}")
    tool_call = tool_calls[0]
    params = tool_call.get("params")
    if not isinstance(params, dict) or params.get("tool") != expected_tool:
        raise DemoError("Codex called an unexpected dynamic tool")
    if (
        params.get("callId") != provider_call_id
        or params.get("arguments") != expected_arguments
    ):
        raise DemoError("Codex tool identity or arguments changed in the raw protocol")
    callback_responses = [
        payload
        for direction, payload in payloads
        if direction == "client_to_server"
        and isinstance(payload, dict)
        and payload.get("id") == callback_request_id
        and isinstance(payload.get("result"), dict)
    ]
    completions = [
        payload
        for direction, payload in payloads
        if direction == "server_to_client"
        and isinstance(payload, dict)
        and payload.get("method") == "turn/completed"
        and payload.get("params", {}).get("threadId") == thread_id
        and payload.get("params", {}).get("turn", {}).get("id") == turn_id
    ]
    final_messages = [
        payload.get("params", {}).get("item")
        for direction, payload in payloads
        if direction == "server_to_client"
        and isinstance(payload, dict)
        and payload.get("method") == "item/completed"
        and payload.get("params", {}).get("threadId") == thread_id
        and payload.get("params", {}).get("turnId") == turn_id
        and payload.get("params", {}).get("item", {}).get("type") == "agentMessage"
        and payload.get("params", {}).get("item", {}).get("phase") == "final_answer"
    ]
    if len(callback_responses) != 1 or len(completions) != 1:
        raise DemoError("raw protocol omitted the unique callback response or completion")
    if len(final_messages) != 1 or final_messages[0].get("text") != "DONE":
        raise DemoError("Codex did not finish the live turn with the expected answer")
    return {
        "raw_records": len(records),
        "real_app_server_process": True,
        "custom_model_provider_installed": False,
        "model": model,
        "model_provider": model_provider,
        "sandbox_network_access": False,
        "sandbox_type": "readOnly",
        "approval_policy": "never",
        "dynamic_tool_calls": 1,
        "callback_responses": 1,
        "completed_turns": 1,
        "final_agent_message": "DONE",
        "thread_id": thread_id,
        "turn_id": turn_id,
        "provider_call_id": provider_call_id,
    }


def _build_binary(runtime_dir: Path, output: Path, package: str) -> None:
    completed = subprocess.run(
        ["go", "build", "-trimpath", "-o", str(output), package],
        cwd=runtime_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=120.0,
        check=False,
    )
    if completed.returncode != 0:
        raise DemoError(f"go build {package} failed: {completed.stdout[-4000:]}")


def _login_status(codex_binary: str) -> str:
    completed = subprocess.run(
        [codex_binary, "login", "status"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=15.0,
        check=False,
    )
    status = completed.stdout.strip()
    if completed.returncode != 0 or not status.startswith("Logged in"):
        raise DemoError("the live Codex demo requires an existing logged-in account")
    return status


def run_demo(
    *,
    output_dir: Path,
    codex_binary: str,
    model: str | None,
) -> dict[str, Any]:
    repository = Path(__file__).resolve().parents[1]
    runtime_dir = repository / "runtime"
    resolved_codex = shutil.which(codex_binary)
    if resolved_codex is None:
        raise DemoError(f"Codex executable not found: {codex_binary}")
    output_dir.mkdir(parents=True, exist_ok=False)
    output_dir.chmod(0o700)
    (output_dir / "logs").mkdir(mode=0o700)
    raw_protocol = output_dir / "app-server.jsonl"
    login_status = _login_status(resolved_codex)
    version = subprocess.run(
        [resolved_codex, "--version"],
        capture_output=True,
        text=True,
        timeout=15.0,
        check=True,
    ).stdout.strip()

    result: dict[str, Any] | None = None
    with tempfile.TemporaryDirectory(prefix="safe-change-codex-private-") as private:
        private_dir = Path(private)
        private_dir.chmod(0o700)
        binary_dir = private_dir / "bin"
        control_state = private_dir / "control"
        anchor_state = private_dir / "anchor"
        payment_state = private_dir / "payment"
        agent_workspace = private_dir / "agent-workspace"
        for directory in (
            binary_dir,
            control_state,
            anchor_state,
            payment_state,
            agent_workspace,
        ):
            directory.mkdir(mode=0o700)
        control_binary = binary_dir / "control"
        payment_binary = binary_dir / "payment"
        _build_binary(runtime_dir, control_binary, "./cmd/control")
        _build_binary(runtime_dir, payment_binary, "./cmd/payment")

        payment_port = _free_port()
        control_port = _free_port()
        while control_port == payment_port:
            control_port = _free_port()
        payment_url = f"http://127.0.0.1:{payment_port}"
        control_url = f"http://127.0.0.1:{control_port}"
        payment_history = payment_state / "payment.history"
        runtime_history = control_state / "runtime.history"
        head_anchor = anchor_state / "runtime.head"
        admin_token_path = control_state / "admin-token"
        operation_token_path = control_state / "operation-token"

        payment = ManagedProcess(
            "payment",
            [
                str(payment_binary),
                f"-listen=127.0.0.1:{payment_port}",
                f"-state={payment_history}",
                "-drop-first-response=true",
            ],
            output_dir / "logs" / "payment.log",
        ).start()
        controls: list[ManagedProcess] = []

        control_command = [
            str(control_binary),
            f"-listen=127.0.0.1:{control_port}",
            f"-history={runtime_history}",
            f"-head-anchor={head_anchor}",
            f"-admin-token-file={admin_token_path}",
            f"-operation-token-file={operation_token_path}",
            f"-operation-domain={OPERATION_DOMAIN}",
            f"-operation-kinds={OPERATION_KIND}",
        ]

        try:
            _wait_healthy(payment_url + "/healthz", payment)
            first_control = ManagedProcess(
                "control-first",
                control_command,
                output_dir / "logs" / "control-first.log",
            ).start()
            controls.append(first_control)
            _wait_healthy(control_url + "/healthz", first_control)
            admin_token = _read_private_token(admin_token_path)
            operation_token = _read_private_token(operation_token_path)

            target = payment_url + "/v1/charge"
            requirement = {
                "id": "codex-payment-v1",
                "results": {"paid": 1},
                "capacities": {"charge": 1},
                "kinds": {
                    OPERATION_KIND: {
                        "costs": {"charge": 1},
                        "produces": {"paid": 1},
                        "retry_safe": True,
                        "queryable": False,
                        "target": target,
                        "method": "POST",
                        "response_classifier": "operation-receipt-v1",
                    }
                },
            }
            _write_json(output_dir / "requirement.json", requirement)
            certificate = _http_json(
                control_url + "/v1/compile",
                method="POST",
                token=admin_token,
                payload=requirement,
            ).body
            if certificate.get("decision") != "activate" or not isinstance(
                certificate.get("rule"), dict
            ):
                raise DemoError(f"Requirement did not compile to a Rule: {certificate}")
            _write_json(output_dir / "certificate.json", certificate)
            active = _http_json(
                control_url + "/v1/activate",
                method="POST",
                token=admin_token,
                payload=certificate,
            ).body
            _write_json(output_dir / "active-state.json", active)

            payment_body = _canonical_json({"amount": 42, "order_id": EFFECT_ID})
            execute_payload = {
                "call_id": CALL_ID,
                "kind": OPERATION_KIND,
                "method": "POST",
                "url": target,
                "headers": {"Content-Type": "application/json"},
                "body": base64.b64encode(payment_body).decode("ascii"),
            }
            first_pid = first_control.pid
            thread_id = ""
            turn_id = ""
            provider_call_id = ""
            callback_request_id: int | str = ""

            client = CodexAppServer(
                model_base_url=None,
                use_logged_in_account=True,
                model=model,
                workspace=agent_workspace,
                raw_jsonl_path=raw_protocol,
                codex_binary=resolved_codex,
                rpc_timeout=30.0,
                turn_timeout=LIVE_TIMEOUT_SECONDS,
            )
            with client:
                thread = client.create_account_thread(
                    tool_name=TOOL_NAME,
                    tool_description=(
                        "Submit the one application-approved payment identity. "
                        "Call exactly once and do not invent or alter the identity."
                    ),
                    input_schema={
                        "type": "object",
                        "required": ["effect_id"],
                        "properties": {
                            "effect_id": {"type": "string", "enum": [EFFECT_ID]}
                        },
                        "additionalProperties": False,
                    },
                    developer_instructions=(
                        "This isolated experiment permits only protected_payment. "
                        "Do not run commands, inspect files, or call another tool."
                    ),
                )
                thread_id = str(thread["id"])
                pending = client.start_protected_turn(
                    thread_id,
                    (
                        f"Call {TOOL_NAME} exactly once with effect_id {EFFECT_ID}. "
                        "After the tool returns, reply with exactly DONE."
                    ),
                    expected_tool=TOOL_NAME,
                    expected_arguments={"effect_id": EFFECT_ID},
                    timeout=LIVE_TIMEOUT_SECONDS,
                )
                turn_id = pending.turn_id
                provider_call_id = pending.call_id
                callback_request_id = pending.request_id

                first = _http_json(
                    control_url + "/v1/execute",
                    method="POST",
                    token=operation_token,
                    payload=execute_payload,
                    expected=frozenset({409}),
                    timeout=40.0,
                )
                first_outcome = first.body.get("outcome")
                if not isinstance(first_outcome, dict) or first_outcome.get("phase") != "unknown":
                    raise DemoError(f"lost response did not produce unknown: {first.body}")
                _write_json(output_dir / "first-outcome.json", first.body)

                first_control.stop()
                second_control = ManagedProcess(
                    "control-second",
                    control_command,
                    output_dir / "logs" / "control-second.log",
                ).start()
                controls.append(second_control)
                _wait_healthy(control_url + "/healthz", second_control)
                second_pid = second_control.pid
                if second_pid == first_pid:
                    raise DemoError("control process replacement did not change the PID")

                recovered = _http_json(
                    control_url + "/v1/execute",
                    method="POST",
                    token=operation_token,
                    payload=execute_payload,
                    timeout=40.0,
                ).body
                if recovered.get("phase") != "succeeded" or recovered.get("reused") is not False:
                    raise DemoError(f"Operation did not recover through payment: {recovered}")
                receipt = _decode_receipt(recovered)
                expected_operation_id = _operation_id()
                if (
                    recovered.get("operation_id") != expected_operation_id
                    or receipt.get("operation_id") != expected_operation_id
                    or receipt.get("outcome") != "succeeded"
                    or not isinstance(receipt.get("remote_reference"), str)
                ):
                    raise DemoError("recovered receipt did not bind the expected Operation")
                _write_json(output_dir / "recovered-outcome.json", recovered)

                reused = _http_json(
                    control_url + "/v1/execute",
                    method="POST",
                    token=operation_token,
                    payload=execute_payload,
                ).body
                if reused.get("phase") != "succeeded" or reused.get("reused") is not True:
                    raise DemoError(f"settled Operation was not reused: {reused}")
                _write_json(output_dir / "reused-outcome.json", reused)

                pending.respond_text(
                    json.dumps(
                        {
                            "effect_id": EFFECT_ID,
                            "remote_reference": receipt["remote_reference"],
                            "status": "succeeded",
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )
                pending.wait_turn_completed(timeout=LIVE_TIMEOUT_SECONDS)
                client.assert_hermetic_runtime()

            stats = _http_json(payment_url + "/v1/stats").body
            if (
                stats.get("deliveries") != 2
                or stats.get("commits") != 1
                or stats.get("paths", {}).get("/v1/charge") != 2
            ):
                raise DemoError(f"payment was not exactly-once: {stats}")
            state = _http_json(
                control_url + "/v1/state", token=admin_token
            ).body
            history = _http_json(
                control_url + "/v1/history",
                token=admin_token,
                require_object=False,
            ).body
            operations = state.get("operations")
            expected_operation_id = _operation_id()
            operation = (
                operations.get(expected_operation_id)
                if isinstance(operations, dict)
                else None
            )
            if (
                not isinstance(operation, dict)
                or operation.get("phase") != "succeeded"
                or operation.get("domain") != OPERATION_DOMAIN
                or operation.get("kind") != OPERATION_KIND
                or operation.get("target") != target
            ):
                raise DemoError(f"final control state is inconsistent: {state}")
            if not isinstance(history, dict) and not isinstance(history, list):
                raise DemoError("History endpoint returned an invalid document")
            _write_json(output_dir / "payment-stats.json", stats)
            _write_json(output_dir / "final-state.json", state)
            _write_json(output_dir / "history.json", history)
            protocol = _protocol_evidence(
                raw_protocol,
                thread_id=thread_id,
                turn_id=turn_id,
                provider_call_id=provider_call_id,
                callback_request_id=callback_request_id,
            )
            payment_lines = payment_history.read_text(encoding="utf-8").splitlines()
            if len(payment_lines) != 1:
                raise DemoError(
                    f"payment durability file contains {len(payment_lines)} records"
                )
            result = {
                "codex": {
                    "binary": str(Path(resolved_codex).resolve()),
                    "binary_sha256": _sha256_file(Path(resolved_codex)),
                    "login_status": login_status,
                    "model": protocol["model"],
                    "model_provider": protocol["model_provider"],
                    "mock_model_endpoint": False,
                    "version": version,
                },
                "protocol": protocol,
                "operation": {
                    "effect_id": EFFECT_ID,
                    "stable_call_id": CALL_ID,
                    "provider_call_id_is_operation_identity": False,
                    "operation_id": expected_operation_id,
                    "first_result": "unknown",
                    "recovered_result": "succeeded",
                    "settled_retry_reused": True,
                },
                "fault": {
                    "control_pid_before": first_pid,
                    "control_pid_after": second_pid,
                    "control_process_replaced_while_callback_pending": True,
                },
                "payment": {
                    "deliveries": 2,
                    "durable_commits": 1,
                    "durability_records": 1,
                },
                "boundaries": {
                    "control_history_outside_codex_process": True,
                    "payment_state_outside_control_process": True,
                    "codex_workspace": "empty temporary read-only workspace",
                    "codex_sandbox_network_access": False,
                    "payment_in_disjoint_network_namespace": False,
                },
                "evidence_directory": str(output_dir.resolve()),
            }
        finally:
            for control_process in reversed(controls):
                control_process.stop()
            payment.stop()
            for source, name in (
                (runtime_history, "runtime.history"),
                (head_anchor, "runtime.head"),
                (payment_history, "payment.history"),
            ):
                if source.is_file():
                    shutil.copy2(source, output_dir / name)

    if result is None:
        raise DemoError("live experiment ended without a result")
    _write_json(output_dir / "result.json", result)
    return result


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--codex-binary", default="codex")
    parser.add_argument(
        "--model",
        help="optional explicit logged-in model; omitted uses the account default",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_args(argv)
    output = arguments.output_dir
    if output is None:
        output = Path(tempfile.mkdtemp(prefix="safe-change-codex-evidence-"))
        output.rmdir()
    try:
        result = run_demo(
            output_dir=output.resolve(),
            codex_binary=arguments.codex_binary,
            model=arguments.model,
        )
    except BaseException as error:
        if output.exists():
            _write_json(
                output / "failure.json",
                {"error_type": type(error).__name__, "error": str(error)},
            )
        raise
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["CALL_ID", "EFFECT_ID", "TOOL_NAME", "DemoError", "run_demo"]
