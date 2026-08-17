"""Deterministic local Anthropic Messages fixture for real Claude Code.

The Claude Code executable remains the system under test.  This server replaces
only the model endpoint and speaks the streaming Messages API shape that Claude
Code consumes, so runtime experiments need neither an account nor an external
model connection.
"""

from __future__ import annotations

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit


_MAX_REQUEST_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True)
class RecordedAnthropicRequest:
    ordinal: int
    method: str
    path: str
    time_ns: int
    body: Any


class AnthropicFixtureError(RuntimeError):
    """The client sent a request outside the bounded experiment contract."""


class DeterministicAnthropicServer:
    """Drive an ordered MCP effect sequence through the Messages API."""

    def __init__(
        self,
        effects: Sequence[str] = ("effect-A", "effect-B"),
        host: str = "127.0.0.1",
        port: int = 0,
        response_delay_seconds: float = 0.0,
    ) -> None:
        self._effects = tuple(effects)
        if (
            host not in {"127.0.0.1", "localhost"}
            or not self._effects
            or len(set(self._effects)) != len(self._effects)
            or any(not isinstance(effect, str) or not effect for effect in self._effects)
            or response_delay_seconds < 0
            or response_delay_seconds > 1
        ):
            raise ValueError("Anthropic fixture requires loopback and unique effects")
        self._host = host
        self._port = port
        self._response_delay_seconds = response_delay_seconds
        self._requests: list[RecordedAnthropicRequest] = []
        self._failure: BaseException | None = None
        self._condition = threading.Condition()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        if self._server is None:
            raise RuntimeError("Anthropic fixture has not started")
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    @property
    def requests(self) -> tuple[RecordedAnthropicRequest, ...]:
        with self._condition:
            return tuple(self._requests)

    @property
    def failure(self) -> BaseException | None:
        with self._condition:
            return self._failure

    def start(self) -> "DeterministicAnthropicServer":
        if self._server is not None:
            raise RuntimeError("Anthropic fixture is already running")
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            server_version = "authority-continuity-anthropic-fixture/1"

            def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
                try:
                    if urlsplit(self.path).path != "/health":
                        raise AnthropicFixtureError(
                            f"unexpected Anthropic health path {self.path!r}"
                        )
                    self._send_json(200, {"status": "ok"})
                except BaseException as error:
                    owner._fail(error)
                    self._send_json(
                        400,
                        {
                            "type": "error",
                            "error": {
                                "type": "invalid_request_error",
                                "message": str(error),
                            },
                        },
                    )

            def do_POST(self) -> None:  # noqa: N802 - stdlib callback name
                try:
                    body = self._read_json()
                    record = owner._record(self.command, self.path, body)
                    path = urlsplit(self.path).path
                    if path.endswith("/messages/count_tokens"):
                        self._send_json(200, {"input_tokens": 1})
                        return
                    if not path.endswith("/messages"):
                        raise AnthropicFixtureError(
                            f"unexpected Anthropic path {self.path!r}"
                        )
                    response = owner._response(record.ordinal, body)
                    if owner._response_delay_seconds:
                        time.sleep(owner._response_delay_seconds)
                    if body.get("stream") is True:
                        self._send_sse(response)
                    else:
                        self._send_json(200, response)
                except BaseException as error:
                    owner._fail(error)
                    self._send_json(
                        400,
                        {
                            "type": "error",
                            "error": {
                                "type": "invalid_request_error",
                                "message": str(error),
                            },
                        },
                    )

            def _read_json(self) -> dict[str, Any]:
                raw_length = self.headers.get("Content-Length")
                try:
                    length = int(raw_length or "")
                except ValueError as error:
                    raise AnthropicFixtureError("invalid Content-Length") from error
                if length <= 0 or length > _MAX_REQUEST_BYTES:
                    raise AnthropicFixtureError("Anthropic request size is out of range")
                try:
                    value = json.loads(self.rfile.read(length))
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise AnthropicFixtureError("Anthropic request is not JSON") from error
                if not isinstance(value, dict):
                    raise AnthropicFixtureError("Anthropic request is not an object")
                return value

            def _send_json(self, status: int, value: Mapping[str, Any]) -> None:
                encoded = json.dumps(
                    dict(value), sort_keys=True, separators=(",", ":")
                ).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(encoded)

            def _send_sse(self, value: Mapping[str, Any]) -> None:
                encoded = _message_events(value)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Content-Length", str(len(encoded)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, unused_format: str, *unused_args: object) -> None:
                return

        self._server = ThreadingHTTPServer((self._host, self._port), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="anthropic-messages-fixture",
            daemon=True,
        )
        self._thread.start()
        return self

    def close(self) -> None:
        server, thread = self._server, self._thread
        self._server = None
        self._thread = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(5)
            if thread.is_alive():
                raise RuntimeError("Anthropic fixture thread did not stop")

    def wait_for_requests(self, count: int, timeout: float = 10.0) -> None:
        deadline = time.monotonic() + timeout
        with self._condition:
            while len(self._requests) < count and self._failure is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        f"Anthropic fixture observed {len(self._requests)}, require {count}"
                    )
                self._condition.wait(remaining)
            if self._failure is not None:
                raise AnthropicFixtureError(str(self._failure)) from self._failure

    def __enter__(self) -> "DeterministicAnthropicServer":
        return self.start()

    def __exit__(self, *unused: object) -> None:
        self.close()

    def _record(self, method: str, path: str, body: Any) -> RecordedAnthropicRequest:
        with self._condition:
            record = RecordedAnthropicRequest(
                ordinal=len(self._requests) + 1,
                method=method,
                path=path,
                time_ns=time.time_ns(),
                body=body,
            )
            self._requests.append(record)
            self._condition.notify_all()
            return record

    def _fail(self, error: BaseException) -> None:
        with self._condition:
            if self._failure is None:
                self._failure = error
            self._condition.notify_all()

    def _response(self, ordinal: int, body: Mapping[str, Any]) -> dict[str, Any]:
        model = body.get("model")
        if not isinstance(model, str) or not model:
            raise AnthropicFixtureError("Messages request omits its model")
        tool_name = _continuity_tool(body.get("tools"))
        completed = _completed_effects(body.get("messages"), tool_name)
        if tuple(completed) != self._effects[: len(completed)]:
            raise AnthropicFixtureError("Messages history contains a different effect order")
        message_id = f"msg_fixture_{ordinal}"
        if len(completed) < len(self._effects):
            effect = self._effects[len(completed)]
            content = [
                {
                    "type": "tool_use",
                    "id": f"toolu_fixture_{ordinal}",
                    "name": tool_name,
                    "input": {"effect_id": effect},
                }
            ]
            stop_reason = "tool_use"
        else:
            content = [{"type": "text", "text": "DONE"}]
            stop_reason = "end_turn"
        return {
            "id": message_id,
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": content,
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }


class DeterministicBashAnthropicServer(DeterministicAnthropicServer):
    """Drive one ordinary Claude Code Bash action, then return DONE."""

    def __init__(
        self,
        command: str,
        host: str = "127.0.0.1",
        port: int = 0,
        response_delay_seconds: float = 0.0,
    ) -> None:
        if not isinstance(command, str) or not command or "\x00" in command:
            raise ValueError("Bash fixture requires one nonempty command")
        super().__init__(
            effects=("bash-action",),
            host=host,
            port=port,
            response_delay_seconds=response_delay_seconds,
        )
        self._command = command

    def _response(self, ordinal: int, body: Mapping[str, Any]) -> dict[str, Any]:
        model = body.get("model")
        if not isinstance(model, str) or not model:
            raise AnthropicFixtureError("Messages request omits its model")
        tool_name = _bash_tool(body.get("tools"))
        completed = _bash_completed(body.get("messages"), tool_name)
        message_id = f"msg_fixture_{ordinal}"
        if not completed:
            content = [
                {
                    "type": "tool_use",
                    "id": f"toolu_fixture_{ordinal}",
                    "name": tool_name,
                    "input": {
                        "command": self._command,
                        "description": "Submit the fixed reservation",
                    },
                }
            ]
            stop_reason = "tool_use"
        else:
            content = [{"type": "text", "text": "DONE"}]
            stop_reason = "end_turn"
        return {
            "id": message_id,
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": content,
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }


def _continuity_tool(raw_tools: Any) -> str:
    matches = [
        tool.get("name")
        for tool in raw_tools or []
        if isinstance(tool, dict)
        and isinstance(tool.get("name"), str)
        and tool["name"].endswith("__commit_effect")
    ]
    if len(matches) != 1:
        raise AnthropicFixtureError("Messages request lacks one continuity MCP tool")
    return matches[0]


def _bash_tool(raw_tools: Any) -> str:
    matches = [
        tool.get("name")
        for tool in raw_tools or []
        if isinstance(tool, dict) and tool.get("name") == "Bash"
    ]
    if len(matches) != 1:
        raise AnthropicFixtureError("Messages request lacks one Bash tool")
    return matches[0]


def _bash_completed(raw_messages: Any, tool_name: str) -> bool:
    if not isinstance(raw_messages, list):
        raise AnthropicFixtureError("Messages request omits its history")
    calls: set[str] = set()
    completions = 0
    for message in raw_messages:
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and block.get("name") == tool_name:
                tool_id = block.get("id")
                arguments = block.get("input")
                if (
                    not isinstance(tool_id, str)
                    or not isinstance(arguments, dict)
                    or arguments.get("command") is None
                ):
                    raise AnthropicFixtureError("Bash tool history is malformed")
                calls.add(tool_id)
            elif block.get("type") == "tool_result":
                tool_id = block.get("tool_use_id")
                if isinstance(tool_id, str) and tool_id in calls:
                    if block.get("is_error") is True:
                        raise AnthropicFixtureError("Bash tool result reports an error")
                    completions += 1
    if completions > 1:
        raise AnthropicFixtureError("Messages history repeats the Bash completion")
    return completions == 1


def _completed_effects(raw_messages: Any, tool_name: str) -> list[str]:
    if not isinstance(raw_messages, list):
        raise AnthropicFixtureError("Messages request omits its history")
    calls: dict[str, str] = {}
    completed: list[str] = []
    for message in raw_messages:
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and block.get("name") == tool_name:
                tool_id = block.get("id")
                arguments = block.get("input")
                effect = arguments.get("effect_id") if isinstance(arguments, dict) else None
                if not isinstance(tool_id, str) or not isinstance(effect, str):
                    raise AnthropicFixtureError("continuity tool history is malformed")
                calls[tool_id] = effect
            elif block.get("type") == "tool_result":
                tool_id = block.get("tool_use_id")
                if isinstance(tool_id, str) and tool_id in calls:
                    completed.append(calls[tool_id])
    return completed


def _message_events(message: Mapping[str, Any]) -> bytes:
    content = message["content"]
    block = content[0]
    start_message = dict(message)
    start_message["content"] = []
    start_message["stop_reason"] = None
    events: list[dict[str, Any]] = [
        {"type": "message_start", "message": start_message},
    ]
    if block["type"] == "tool_use":
        events.extend(
            [
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {
                        "type": "tool_use",
                        "id": block["id"],
                        "name": block["name"],
                        "input": {},
                    },
                },
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {
                        "type": "input_json_delta",
                        "partial_json": json.dumps(
                            block["input"], sort_keys=True, separators=(",", ":")
                        ),
                    },
                },
            ]
        )
    else:
        events.extend(
            [
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                },
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": block["text"]},
                },
            ]
        )
    events.extend(
        [
            {"type": "content_block_stop", "index": 0},
            {
                "type": "message_delta",
                "delta": {
                    "stop_reason": message["stop_reason"],
                    "stop_sequence": None,
                },
                "usage": {"output_tokens": 1},
            },
            {"type": "message_stop"},
        ]
    )
    chunks: list[str] = []
    for event in events:
        chunks.append(f"event: {event['type']}\n")
        chunks.append(
            "data: "
            + json.dumps(event, sort_keys=True, separators=(",", ":"))
            + "\n\n"
        )
    return "".join(chunks).encode("utf-8")


__all__ = [
    "AnthropicFixtureError",
    "DeterministicAnthropicServer",
    "DeterministicBashAnthropicServer",
    "RecordedAnthropicRequest",
]
