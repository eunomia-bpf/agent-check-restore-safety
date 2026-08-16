"""Minimal real Codex App Server boundary used by the runtime experiments.

The client owns one protected dynamic-tool callback.  It intentionally has no
dependency on the authority controller, replay checker, or evaluation oracle;
callers decide when and how to answer the pending callback.  Deterministic
tests use a loopback model endpoint; the locally logged-in Codex account is
available only through an explicit opt-in and never installs a custom provider.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import queue
import re
import shutil
import stat
import subprocess
import threading
import time
from typing import Any, Callable, Mapping, TextIO
from urllib.parse import urlsplit


RPC_TIMEOUT_SECONDS = 15.0
TURN_TIMEOUT_SECONDS = 30.0
_PROCESS_STOP_TIMEOUT_SECONDS = 3.0
_PROVIDER_ID = "authority_continuity_mock"
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_MCP_SERVER_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}\Z")
_MAX_MCP_ARGUMENT_BYTES = 4096


class AppServerError(RuntimeError):
    """Base error for the Codex App Server boundary."""


class AppServerTimeout(AppServerError):
    """A bounded RPC, event, or turn wait expired."""


class AppServerProtocolError(AppServerError):
    """The server emitted a malformed or contradictory protocol message."""


class AppServerRPCError(AppServerError):
    """An App Server request returned a JSON-RPC error."""

    def __init__(self, method: str, error: Mapping[str, Any]) -> None:
        self.method = method
        self.error = dict(error)
        super().__init__(f"{method} failed: {json.dumps(self.error, sort_keys=True)}")


@dataclass(frozen=True)
class MCPStdioServer:
    """One operator-selected local MCP process exposed to real Codex.

    This deliberately omits environment forwarding, network endpoints, and
    authentication material.  The continuity supervisor passes only paths and
    non-secret execution identity to the credential-free stdio process.
    """

    name: str
    command: str | os.PathLike[str]
    args: tuple[str, ...]
    enabled_tools: tuple[str, ...]
    startup_timeout_sec: int = 10
    tool_timeout_sec: int = 60

    def __post_init__(self) -> None:
        if _MCP_SERVER_NAME.fullmatch(self.name) is None:
            raise ValueError("MCP server name must be a bounded safe identifier")
        command = Path(self.command)
        if not command.is_absolute() or command.resolve() != command:
            raise ValueError("MCP server command must be an absolute canonical path")
        try:
            info = command.lstat()
        except OSError as error:
            raise ValueError("MCP server command does not exist") from error
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) & 0o022 != 0
            or not os.access(command, os.X_OK)
        ):
            raise ValueError(
                "MCP server command must be a direct executable regular file owned by the current user"
            )
        if not self.args or not self.enabled_tools:
            raise ValueError("MCP server requires fixed arguments and a tool allow list")
        for label, values in (("argument", self.args), ("tool", self.enabled_tools)):
            if not isinstance(values, tuple) or len(values) > 256:
                raise ValueError(f"MCP server {label}s must be a bounded tuple")
            for value in values:
                if (
                    not isinstance(value, str)
                    or not value
                    or len(value.encode("utf-8")) > _MAX_MCP_ARGUMENT_BYTES
                    or any(ord(character) < 0x20 for character in value)
                ):
                    raise ValueError(f"MCP server {label} is malformed")
            if len(set(values)) != len(values):
                raise ValueError(f"MCP server {label}s are duplicated")
        if not 1 <= self.startup_timeout_sec <= 60:
            raise ValueError("MCP startup timeout must be between 1 and 60 seconds")
        if not 1 <= self.tool_timeout_sec <= 600:
            raise ValueError("MCP tool timeout must be between 1 and 600 seconds")

    @property
    def command_path(self) -> str:
        return os.fspath(Path(self.command))


@dataclass
class PendingToolCall:
    """A real pending ``item/tool/call`` request owned by the client.

    The object is deliberately handed to the experiment layer before any
    response is sent, allowing that layer to durably Prepare, dispatch, crash,
    and recover while Codex keeps the callback pending.
    """

    request_id: int | str
    thread_id: str
    turn_id: str
    call_id: str
    namespace: str | None
    tool: str
    arguments: Mapping[str, Any]
    _client: "CodexAppServer" = field(repr=False, compare=False)
    _responded: bool = field(default=False, init=False, repr=False, compare=False)

    def respond(
        self,
        *,
        content_items: list[Mapping[str, Any]],
        success: bool,
    ) -> None:
        if self._responded:
            raise AppServerProtocolError(
                f"tool callback {self.call_id} has already been answered"
            )
        result = {
            "contentItems": [dict(item) for item in content_items],
            "success": bool(success),
        }
        self._client.respond(self.request_id, result)
        self._responded = True

    def respond_text(self, text: str, *, success: bool = True) -> None:
        self.respond(
            content_items=[{"type": "inputText", "text": text}],
            success=success,
        )

    def wait_turn_completed(self, timeout: float = TURN_TIMEOUT_SECONDS) -> dict[str, Any]:
        if not self._responded:
            raise AppServerProtocolError(
                "cannot wait for turn completion before answering the tool callback"
            )
        return self._client.wait_turn_completed(
            self.thread_id, self.turn_id, timeout=timeout
        )


def _toml_string(value: str) -> str:
    # JSON basic strings are valid TOML basic strings for the characters used
    # in the pinned provider name, URL, and model identifier.
    return json.dumps(value, ensure_ascii=True)


def _toml_array(values: tuple[str, ...]) -> str:
    return "[" + ",".join(_toml_string(value) for value in values) + "]"


class CodexAppServer:
    """Thread-safe JSONL client for ``codex app-server --stdio``."""

    def __init__(
        self,
        *,
        model_base_url: str | None,
        workspace: str | os.PathLike[str],
        raw_jsonl_path: str | os.PathLike[str],
        codex_binary: str = "codex",
        model: str | None = None,
        use_logged_in_account: bool = False,
        mcp_server: MCPStdioServer | None = None,
        rpc_timeout: float = RPC_TIMEOUT_SECONDS,
        turn_timeout: float = TURN_TIMEOUT_SECONDS,
    ) -> None:
        if use_logged_in_account != (model_base_url is None):
            raise ValueError(
                "explicit logged-in account use requires both model_base_url=None and "
                "use_logged_in_account=True"
            )
        if model_base_url is not None:
            parsed = urlsplit(model_base_url)
            if (
                parsed.scheme != "http"
                or parsed.hostname not in _LOOPBACK_HOSTS
                or parsed.username is not None
                or parsed.password is not None
            ):
                raise ValueError(
                    "the deterministic model endpoint must be unauthenticated loopback HTTP"
                )
        resolved_binary = shutil.which(codex_binary)
        if resolved_binary is None:
            raise FileNotFoundError(f"Codex executable not found: {codex_binary}")
        workspace_path = Path(workspace).resolve()
        if not workspace_path.is_dir():
            raise NotADirectoryError(workspace_path)
        if rpc_timeout <= 0 or turn_timeout <= 0:
            raise ValueError("timeouts must be positive")

        self.model_base_url = (
            model_base_url.rstrip("/") if model_base_url is not None else None
        )
        self.workspace = workspace_path
        self.raw_jsonl_path = Path(raw_jsonl_path).resolve()
        self.codex_binary = resolved_binary
        self.model = (
            model
            if model is not None or use_logged_in_account
            else "gpt-5.6-sol"
        )
        self._uses_logged_in_account = use_logged_in_account
        self.mcp_server = mcp_server
        self.rpc_timeout = float(rpc_timeout)
        self.turn_timeout = float(turn_timeout)

        self._process: subprocess.Popen[str] | None = None
        self._stdout_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._pending: dict[int, queue.Queue[dict[str, Any] | BaseException]] = {}
        self._pending_lock = threading.Lock()
        self._next_request_id = 1
        self._send_lock = threading.Lock()
        self._events: list[dict[str, Any]] = []
        self._events_condition = threading.Condition()
        self._fatal: BaseException | None = None
        self._stopping = False
        self._raw_file: TextIO | None = None
        self._raw_lock = threading.Lock()
        self._raw_sequence = 0
        self._unexpected_mcp_events: list[dict[str, Any]] = []
        self._mcp_startup_events: list[dict[str, Any]] = []
        self.initialize_result: dict[str, Any] | None = None

    @property
    def process_id(self) -> int | None:
        return self._process.pid if self._process is not None else None

    @property
    def unexpected_mcp_events(self) -> tuple[dict[str, Any], ...]:
        with self._events_condition:
            return tuple(self._unexpected_mcp_events)

    @property
    def mcp_startup_events(self) -> tuple[dict[str, Any], ...]:
        with self._events_condition:
            return tuple(self._mcp_startup_events)

    @property
    def uses_logged_in_account(self) -> bool:
        return self._uses_logged_in_account

    def _command(self) -> list[str]:
        mcp_overrides = ["mcp_servers={}"]
        if self.mcp_server is not None:
            configured = (
                "{"
                f"command={_toml_string(self.mcp_server.command_path)},"
                f"args={_toml_array(self.mcp_server.args)},"
                f"startup_timeout_sec={self.mcp_server.startup_timeout_sec},"
                f"tool_timeout_sec={self.mcp_server.tool_timeout_sec},"
                "enabled=true,required=true,"
                f"enabled_tools={_toml_array(self.mcp_server.enabled_tools)},"
                'default_tools_approval_mode="approve",'
                "tools={"
                + ",".join(
                    f"{_toml_string(tool)}={{approval_mode=\"approve\"}}"
                    for tool in self.mcp_server.enabled_tools
                )
                + "}"
                "}"
            )
            mcp_overrides.append(
                f"mcp_servers.{self.mcp_server.name}={configured}"
            )
        if self.uses_logged_in_account:
            overrides = [
                "analytics.enabled=false",
                "features.responses_websockets=false",
                "features.apps=false",
                "features.enable_mcp_apps=false",
                "features.plugins=false",
            ] + mcp_overrides
            command = [self.codex_binary, "app-server", "--stdio"]
            for override in overrides:
                command.extend(("-c", override))
            return command

        provider = (
            "{"
            f"name={_toml_string('Authority Continuity deterministic fixture')},"
            f"base_url={_toml_string(self.model_base_url)},"
            'wire_api="responses",'
            "request_max_retries=0,"
            "stream_max_retries=0,"
            "requires_openai_auth=false,"
            "supports_websockets=false"
            "}"
        )
        overrides = [
            f"model={_toml_string(self.model)}",
            f"model_provider={_toml_string(_PROVIDER_ID)}",
            f"model_providers.{_PROVIDER_ID}={provider}",
            "analytics.enabled=false",
            "features.responses_websockets=false",
            "features.remote_models=false",
            "features.apps=false",
            "features.enable_mcp_apps=false",
            "features.plugins=false",
        ] + mcp_overrides
        command = [self.codex_binary, "app-server", "--stdio"]
        for override in overrides:
            command.extend(("-c", override))
        return command

    def start(self) -> "CodexAppServer":
        if self._process is not None:
            raise RuntimeError("App Server client is already running")
        self.raw_jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        self._raw_file = self.raw_jsonl_path.open("w", encoding="utf-8")
        command = self._command()
        self._record_raw("meta", {"event": "process_start", "command": command})
        try:
            self._process = subprocess.Popen(
                command,
                cwd=self.workspace,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except BaseException:
            self._close_raw_file()
            raise
        assert self._process.stdout is not None
        assert self._process.stderr is not None
        self._stdout_thread = threading.Thread(
            target=self._read_stdout,
            name="codex-app-server-stdout",
            daemon=True,
        )
        self._stderr_thread = threading.Thread(
            target=self._read_stderr,
            name="codex-app-server-stderr",
            daemon=True,
        )
        self._stdout_thread.start()
        self._stderr_thread.start()
        try:
            self.initialize_result = self.request(
                "initialize",
                {
                    "clientInfo": {
                        "name": "authority_continuity_adapter",
                        "title": "Authority Continuity RQ3 Adapter",
                        "version": "0.1.0",
                    },
                    "capabilities": {"experimentalApi": True},
                },
                timeout=self.rpc_timeout,
            )
            self.notify("initialized", {})
        except BaseException:
            self.stop()
            raise
        return self

    def _read_stdout(self) -> None:
        process = self._process
        assert process is not None and process.stdout is not None
        try:
            for raw_line in process.stdout:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError as error:
                    self._record_raw(
                        "server_stdout_invalid", {"line": line, "error": str(error)}
                    )
                    self._set_fatal(
                        AppServerProtocolError(
                            f"App Server emitted non-JSON stdout: {line[:200]}"
                        )
                    )
                    return
                if not isinstance(message, dict):
                    self._set_fatal(
                        AppServerProtocolError("App Server JSONL message is not an object")
                    )
                    return
                self._record_raw("server_to_client", message)
                self._route_message(message)
        except BaseException as error:
            if not self._stopping:
                self._set_fatal(error)
        finally:
            if not self._stopping:
                code = process.poll()
                self._set_fatal(
                    AppServerProtocolError(
                        f"App Server stdout closed unexpectedly (exit={code})"
                    )
                )

    def _read_stderr(self) -> None:
        process = self._process
        assert process is not None and process.stderr is not None
        try:
            for raw_line in process.stderr:
                line = raw_line.rstrip("\r\n")
                if line:
                    self._record_raw("server_stderr", {"line": line})
        except BaseException as error:
            if not self._stopping:
                self._set_fatal(error)

    def _route_message(self, message: dict[str, Any]) -> None:
        if "id" in message and "method" not in message:
            response_id = message["id"]
            with self._pending_lock:
                destination = self._pending.get(response_id)
            if destination is None:
                self._set_fatal(
                    AppServerProtocolError(
                        f"response for unknown client request id: {response_id!r}"
                    )
                )
                return
            try:
                destination.put_nowait(message)
            except queue.Full:
                self._set_fatal(
                    AppServerProtocolError(
                        f"duplicate response for client request id: {response_id!r}"
                    )
                )
            return

        if "method" not in message:
            self._set_fatal(
                AppServerProtocolError(
                    f"unrecognized App Server message: {json.dumps(message, sort_keys=True)}"
                )
            )
            return

        with self._events_condition:
            self._events.append(message)
            if message.get("method") == "mcpServer/startupStatus/updated":
                self._mcp_startup_events.append(message)
                params = message.get("params")
                configured_name = (
                    self.mcp_server.name if self.mcp_server is not None else None
                )
                if not isinstance(params, dict) or params.get("name") != configured_name:
                    self._unexpected_mcp_events.append(message)
            self._events_condition.notify_all()

    def _set_fatal(self, error: BaseException) -> None:
        # The event condition owns both the fatal state and wake-up.  Keeping
        # those under one lock prevents a missed fatal notification and avoids
        # an events-lock/fatal-lock inversion in wait_for_message().
        with self._events_condition:
            if self._fatal is not None:
                return
            self._fatal = error
            self._events_condition.notify_all()
        with self._pending_lock:
            destinations = list(self._pending.values())
        for destination in destinations:
            # A completed response may already occupy this one-shot queue.
            # Never let the stdout reader deadlock while reporting a later
            # process-wide failure.
            try:
                destination.put_nowait(error)
            except queue.Full:
                pass

    def _raise_if_fatal(self) -> None:
        with self._events_condition:
            error = self._fatal
        if error is not None:
            raise error

    def _record_raw(self, direction: str, payload: Mapping[str, Any]) -> None:
        with self._raw_lock:
            if self._raw_file is None:
                return
            self._raw_sequence += 1
            record = {
                "sequence": self._raw_sequence,
                "time_ns": time.time_ns(),
                "direction": direction,
                "payload": dict(payload),
            }
            self._raw_file.write(
                json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
            )
            self._raw_file.flush()

    def _send(self, message: Mapping[str, Any]) -> None:
        process = self._process
        if process is None or process.stdin is None:
            raise AppServerProtocolError("App Server is not running")
        self._raise_if_fatal()
        encoded = json.dumps(dict(message), sort_keys=True, separators=(",", ":"))
        with self._send_lock:
            if process.poll() is not None:
                raise AppServerProtocolError(
                    f"App Server exited before send (exit={process.returncode})"
                )
            try:
                process.stdin.write(encoded + "\n")
                process.stdin.flush()
            except (BrokenPipeError, OSError) as error:
                raise AppServerProtocolError("App Server stdin closed") from error
            self._record_raw("client_to_server", dict(message))

    def request(
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        if timeout is None:
            timeout = self.rpc_timeout
        if timeout <= 0:
            raise ValueError("request timeout must be positive")
        with self._pending_lock:
            request_id = self._next_request_id
            self._next_request_id += 1
            destination: queue.Queue[dict[str, Any] | BaseException] = queue.Queue(
                maxsize=1
            )
            self._pending[request_id] = destination
        message: dict[str, Any] = {"id": request_id, "method": method}
        if params is not None:
            message["params"] = dict(params)
        try:
            self._send(message)
            try:
                response = destination.get(timeout=timeout)
            except queue.Empty as error:
                raise AppServerTimeout(
                    f"{method} request {request_id} exceeded {timeout:.1f}s"
                ) from error
            if isinstance(response, BaseException):
                raise response
            if "error" in response:
                error_value = response["error"]
                if not isinstance(error_value, dict):
                    raise AppServerProtocolError(
                        f"{method} returned a malformed error object"
                    )
                raise AppServerRPCError(method, error_value)
            result = response.get("result")
            if not isinstance(result, dict):
                raise AppServerProtocolError(
                    f"{method} response result is not an object"
                )
            return result
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)

    def notify(self, method: str, params: Mapping[str, Any] | None = None) -> None:
        message: dict[str, Any] = {"method": method}
        if params is not None:
            message["params"] = dict(params)
        self._send(message)

    def respond(self, request_id: int | str, result: Mapping[str, Any]) -> None:
        self._send({"id": request_id, "result": dict(result)})

    def wait_for_message(
        self,
        predicate: Callable[[dict[str, Any]], bool],
        *,
        description: str,
        timeout: float,
    ) -> dict[str, Any]:
        if timeout <= 0:
            raise ValueError("event timeout must be positive")
        deadline = time.monotonic() + timeout
        with self._events_condition:
            while True:
                self._raise_if_fatal()
                for index, message in enumerate(self._events):
                    if predicate(message):
                        return self._events.pop(index)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AppServerTimeout(
                        f"timed out after {timeout:.1f}s waiting for {description}"
                    )
                self._events_condition.wait(remaining)

    def create_seed_thread(
        self,
        *,
        tool_name: str = "protected_commit",
        tool_description: str = "Commit one protected test effect",
        sandbox: str = "read-only",
    ) -> dict[str, Any]:
        if sandbox not in {"read-only", "workspace-write"}:
            raise ValueError("seed thread sandbox must be read-only or workspace-write")
        result = self.request(
            "thread/start",
            {
                "cwd": str(self.workspace),
                "ephemeral": False,
                "model": self.model,
                "modelProvider": _PROVIDER_ID,
                "sandbox": sandbox,
                "approvalPolicy": "never",
                "environments": [],
                "serviceName": "authority_continuity_adapter",
                "dynamicTools": [
                    {
                        "type": "function",
                        "name": tool_name,
                        "description": tool_description,
                        "inputSchema": {
                            "type": "object",
                            "required": ["effect_id"],
                            "properties": {"effect_id": {"type": "string"}},
                            "additionalProperties": False,
                        },
                    }
                ],
            },
        )
        thread = result.get("thread")
        if not isinstance(thread, dict) or not isinstance(thread.get("id"), str):
            raise AppServerProtocolError("thread/start omitted the seed thread id")
        if thread.get("ephemeral") is not False:
            raise AppServerProtocolError("seed thread was not persisted")
        if thread.get("path") is None:
            raise AppServerProtocolError("persisted seed thread has no rollout path")
        if result.get("modelProvider") != _PROVIDER_ID:
            raise AppServerProtocolError("seed thread escaped the local model provider")
        return thread

    def create_account_thread(
        self,
        *,
        tool_name: str,
        tool_description: str,
        input_schema: Mapping[str, Any],
        developer_instructions: str | None = None,
    ) -> dict[str, Any]:
        """Create one ephemeral thread backed by the locally logged-in account."""

        if not self.uses_logged_in_account:
            raise AppServerProtocolError(
                "account-backed thread requires explicit logged-in account mode"
            )
        if not tool_name or not tool_description or not isinstance(input_schema, Mapping):
            raise ValueError("a named dynamic tool with an input schema is required")
        params: dict[str, Any] = {
            "cwd": str(self.workspace),
            "ephemeral": True,
            "sandbox": "read-only",
            "approvalPolicy": "never",
            "environments": [],
            "serviceName": "safe_change_runtime",
            "dynamicTools": [
                {
                    "type": "function",
                    "name": tool_name,
                    "description": tool_description,
                    "inputSchema": dict(input_schema),
                }
            ],
        }
        if self.model:
            params["model"] = self.model
        if developer_instructions:
            params["developerInstructions"] = developer_instructions
        result = self.request("thread/start", params)
        thread = result.get("thread")
        if not isinstance(thread, dict) or not isinstance(thread.get("id"), str):
            raise AppServerProtocolError("thread/start omitted the account thread id")
        if thread.get("ephemeral") is not True or thread.get("path") is not None:
            raise AppServerProtocolError("account thread is not ephemeral")
        if result.get("modelProvider") == _PROVIDER_ID:
            raise AppServerProtocolError("account thread escaped to the test provider")
        return thread

    def create_mcp_thread(
        self,
        *,
        sandbox: str = "read-only",
        ephemeral: bool = True,
        developer_instructions: str | None = None,
    ) -> dict[str, Any]:
        """Create a real Codex thread with only the configured MCP tools."""

        if self.mcp_server is None:
            raise AppServerProtocolError("MCP thread requires an explicit stdio server")
        if sandbox not in {"read-only", "workspace-write"}:
            raise ValueError("MCP thread sandbox must be read-only or workspace-write")
        params: dict[str, Any] = {
            "cwd": str(self.workspace),
            "ephemeral": bool(ephemeral),
            "sandbox": sandbox,
            "approvalPolicy": "never",
            "environments": [],
            "serviceName": "continuity_runtime_mcp",
        }
        if self.model:
            params["model"] = self.model
        if not self.uses_logged_in_account:
            params["modelProvider"] = _PROVIDER_ID
        if developer_instructions:
            params["developerInstructions"] = developer_instructions
        result = self.request("thread/start", params)
        thread = result.get("thread")
        if not isinstance(thread, dict) or not isinstance(thread.get("id"), str):
            raise AppServerProtocolError("thread/start omitted the MCP thread id")
        if thread.get("ephemeral") is not bool(ephemeral):
            raise AppServerProtocolError("MCP thread persistence differs from the request")
        if (thread.get("path") is None) != bool(ephemeral):
            raise AppServerProtocolError("MCP thread rollout path is inconsistent")
        if not self.uses_logged_in_account and result.get("modelProvider") != _PROVIDER_ID:
            raise AppServerProtocolError("MCP thread escaped the local model provider")
        return thread

    def start_turn_and_wait(
        self,
        thread_id: str,
        text: str,
        *,
        timeout: float | None = None,
    ) -> tuple[str, dict[str, Any]]:
        if timeout is None:
            timeout = self.turn_timeout
        result = self.request(
            "turn/start",
            {"threadId": thread_id, "input": [{"type": "text", "text": text}]},
        )
        turn = result.get("turn")
        if not isinstance(turn, dict) or not isinstance(turn.get("id"), str):
            raise AppServerProtocolError("turn/start omitted the turn id")
        turn_id = turn["id"]
        completed = self.wait_turn_completed(thread_id, turn_id, timeout=timeout)
        return turn_id, completed

    def fork_at_turn(
        self,
        source_thread_id: str,
        last_turn_id: str,
    ) -> dict[str, Any]:
        result = self.request(
            "thread/fork",
            {
                "threadId": source_thread_id,
                "lastTurnId": last_turn_id,
                "ephemeral": True,
                "excludeTurns": True,
            },
        )
        thread = result.get("thread")
        if not isinstance(thread, dict) or not isinstance(thread.get("id"), str):
            raise AppServerProtocolError("thread/fork omitted the child thread id")
        if thread["id"] == source_thread_id:
            raise AppServerProtocolError("thread/fork reused the source thread id")
        if thread.get("forkedFromId") != source_thread_id:
            raise AppServerProtocolError("thread/fork omitted native fork lineage")
        if thread.get("ephemeral") is not True or thread.get("path") is not None:
            raise AppServerProtocolError("fork target is not an ephemeral child")
        return thread

    def start_protected_turn(
        self,
        thread_id: str,
        text: str,
        *,
        expected_tool: str = "protected_commit",
        expected_arguments: Mapping[str, Any] | None = None,
        approval_policy: str | None = None,
        sandbox_policy: Mapping[str, Any] | None = None,
        timeout: float | None = None,
    ) -> PendingToolCall:
        if timeout is None:
            timeout = self.turn_timeout
        params: dict[str, Any] = {
            "threadId": thread_id,
            "input": [{"type": "text", "text": text}],
        }
        if approval_policy is not None:
            params["approvalPolicy"] = approval_policy
        if sandbox_policy is not None:
            params["sandboxPolicy"] = dict(sandbox_policy)
        result = self.request(
            "turn/start",
            params,
        )
        turn = result.get("turn")
        if not isinstance(turn, dict) or not isinstance(turn.get("id"), str):
            raise AppServerProtocolError("turn/start omitted the protected turn id")
        turn_id = turn["id"]

        return self.wait_protected_call(
            thread_id,
            turn_id,
            expected_tool=expected_tool,
            expected_arguments=expected_arguments,
            timeout=timeout,
        )

    def wait_protected_call(
        self,
        thread_id: str,
        turn_id: str,
        *,
        expected_tool: str = "protected_commit",
        expected_arguments: Mapping[str, Any] | None = None,
        timeout: float | None = None,
    ) -> PendingToolCall:
        """Wait for the next protected callback in an already running turn."""

        if timeout is None:
            timeout = self.turn_timeout

        def matches(message: dict[str, Any]) -> bool:
            if message.get("method") != "item/tool/call" or "id" not in message:
                return False
            params = message.get("params")
            return (
                isinstance(params, dict)
                and params.get("threadId") == thread_id
                and params.get("turnId") == turn_id
                and params.get("tool") == expected_tool
            )

        message = self.wait_for_message(
            matches,
            description=(
                f"item/tool/call for thread={thread_id} turn={turn_id} "
                f"tool={expected_tool}"
            ),
            timeout=timeout,
        )
        params = message.get("params")
        assert isinstance(params, dict)
        call_id = params.get("callId")
        arguments = params.get("arguments")
        if not isinstance(call_id, str) or not call_id:
            raise AppServerProtocolError("item/tool/call omitted callId")
        if not isinstance(arguments, dict):
            raise AppServerProtocolError("item/tool/call arguments are not an object")
        if expected_arguments is not None and arguments != dict(expected_arguments):
            raise AppServerProtocolError(
                "item/tool/call arguments differ from the deterministic fixture: "
                f"expected={dict(expected_arguments)!r} actual={arguments!r}"
            )
        namespace = params.get("namespace")
        if namespace is not None and not isinstance(namespace, str):
            raise AppServerProtocolError("item/tool/call namespace is malformed")
        return PendingToolCall(
            request_id=message["id"],
            thread_id=thread_id,
            turn_id=turn_id,
            call_id=call_id,
            namespace=namespace,
            tool=expected_tool,
            arguments=dict(arguments),
            _client=self,
        )

    def wait_turn_completed(
        self,
        thread_id: str,
        turn_id: str,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        if timeout is None:
            timeout = self.turn_timeout

        def matches(message: dict[str, Any]) -> bool:
            params = message.get("params")
            turn = params.get("turn") if isinstance(params, dict) else None
            return (
                message.get("method") == "turn/completed"
                and isinstance(params, dict)
                and params.get("threadId") == thread_id
                and isinstance(turn, dict)
                and turn.get("id") == turn_id
            )

        message = self.wait_for_message(
            matches,
            description=f"turn/completed for thread={thread_id} turn={turn_id}",
            timeout=timeout,
        )
        params = message["params"]
        turn = params["turn"]
        if turn.get("status") != "completed":
            raise AppServerProtocolError(
                f"turn {turn_id} ended with status={turn.get('status')!r}: "
                f"{turn.get('error')!r}"
            )
        return message

    def archive_thread(self, thread_id: str) -> None:
        self.request("thread/archive", {"threadId": thread_id})

    def assert_hermetic_runtime(self) -> None:
        events = self.unexpected_mcp_events
        if events:
            names = sorted(
                {
                    str(event.get("params", {}).get("name"))
                    for event in events
                    if isinstance(event.get("params"), dict)
                }
            )
            raise AppServerProtocolError(
                "unexpected MCP startup under hermetic preflight: " + ", ".join(names)
            )

    def stop(self) -> None:
        process = self._process
        if process is None:
            self._close_raw_file()
            return
        self._stopping = True
        try:
            if process.stdin is not None:
                try:
                    process.stdin.close()
                except OSError:
                    pass
            try:
                process.wait(timeout=_PROCESS_STOP_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=_PROCESS_STOP_TIMEOUT_SECONDS)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=_PROCESS_STOP_TIMEOUT_SECONDS)
        finally:
            self._record_raw(
                "meta", {"event": "process_stop", "returncode": process.poll()}
            )
            for thread in (self._stdout_thread, self._stderr_thread):
                if thread is not None:
                    thread.join(timeout=1.0)
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass
            self._process = None
            self._stdout_thread = None
            self._stderr_thread = None
            self._close_raw_file()

    def _close_raw_file(self) -> None:
        with self._raw_lock:
            if self._raw_file is not None:
                self._raw_file.flush()
                self._raw_file.close()
                self._raw_file = None

    def __enter__(self) -> "CodexAppServer":
        return self.start()

    def __exit__(self, _exc_type: Any, _exc: Any, _tb: Any) -> None:
        self.stop()


__all__ = [
    "RPC_TIMEOUT_SECONDS",
    "TURN_TIMEOUT_SECONDS",
    "AppServerError",
    "AppServerProtocolError",
    "AppServerRPCError",
    "AppServerTimeout",
    "CodexAppServer",
    "PendingToolCall",
]
