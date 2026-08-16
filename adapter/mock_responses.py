"""Deterministic loopback-only Responses API fixture for Codex App Server.

The real Codex App Server is the system under test.  This module replaces only
the model endpoint, following the SSE shape used by Codex's official tests, so
the experiment never depends on a live model, credentials, or external
network access.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time
from typing import Any, Mapping
from urllib.parse import urlsplit


_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost"})
_MAX_REQUEST_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True)
class ResponseFixture:
    """One response returned for the next ``POST .../responses`` request."""

    kind: str
    response_id: str
    message_id: str | None = None
    text: str | None = None
    call_id: str | None = None
    namespace: str | None = None
    tool: str | None = None
    arguments: Mapping[str, Any] | None = None
    input: str | None = None


@dataclass(frozen=True)
class RecordedRequest:
    """A request observed by the local fixture server."""

    ordinal: int
    method: str
    path: str
    body: Any


def _event_stream(events: list[dict[str, Any]]) -> bytes:
    chunks: list[str] = []
    for event in events:
        event_type = event["type"]
        chunks.append(f"event: {event_type}\n")
        chunks.append(
            "data: "
            + json.dumps(event, sort_keys=True, separators=(",", ":"))
            + "\n\n"
        )
    return "".join(chunks).encode("utf-8")


def _created(response_id: str) -> dict[str, Any]:
    return {"type": "response.created", "response": {"id": response_id}}


def _completed(response_id: str) -> dict[str, Any]:
    return {
        "type": "response.completed",
        "response": {
            "id": response_id,
            "usage": {
                "input_tokens": 0,
                "input_tokens_details": None,
                "output_tokens": 0,
                "output_tokens_details": None,
                "total_tokens": 0,
            },
        },
    }


def _render_fixture(fixture: ResponseFixture) -> bytes:
    if fixture.kind == "assistant":
        if fixture.message_id is None or fixture.text is None:
            raise ValueError("assistant fixture requires message_id and text")
        output = {
            "type": "response.output_item.done",
            "item": {
                "type": "message",
                "role": "assistant",
                "id": fixture.message_id,
                "content": [{"type": "output_text", "text": fixture.text}],
            },
        }
    elif fixture.kind == "tool_call":
        if fixture.call_id is None or fixture.tool is None:
            raise ValueError("tool fixture requires call_id and tool")
        item: dict[str, Any] = {
            "type": "function_call",
            "call_id": fixture.call_id,
            "name": fixture.tool,
            "arguments": json.dumps(
                dict(fixture.arguments or {}),
                sort_keys=True,
                separators=(",", ":"),
            ),
        }
        if fixture.namespace is not None:
            item["namespace"] = fixture.namespace
        output = {"type": "response.output_item.done", "item": item}
    elif fixture.kind == "custom_tool_call":
        if fixture.call_id is None or fixture.tool is None or fixture.input is None:
            raise ValueError("custom tool fixture requires call_id, tool, and input")
        item = {
            "type": "custom_tool_call",
            "call_id": fixture.call_id,
            "name": fixture.tool,
            "input": fixture.input,
        }
        if fixture.namespace is not None:
            item["namespace"] = fixture.namespace
        output = {"type": "response.output_item.done", "item": item}
    else:
        raise ValueError(f"unknown fixture kind: {fixture.kind}")

    return _event_stream(
        [_created(fixture.response_id), output, _completed(fixture.response_id)]
    )


class DeterministicResponsesServer:
    """A queued, deterministic Responses API server bound to loopback.

    Fixtures are consumed in FIFO order only by ``POST`` requests whose path
    ends in ``/responses``.  Codex's background ``GET /models`` request is
    answered with the empty catalog used by the upstream test suite and does
    not consume a fixture.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 0) -> None:
        if host not in _LOOPBACK_HOSTS:
            raise ValueError("the deterministic model fixture must bind to loopback")
        self._host = host
        self._port = port
        self._fixtures: deque[ResponseFixture] = deque()
        self._requests: list[RecordedRequest] = []
        self._condition = threading.Condition()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._next_response_number = 1
        self._next_message_number = 1

    @property
    def base_url(self) -> str:
        if self._server is None:
            raise RuntimeError("fixture server has not started")
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}/v1"

    @property
    def requests(self) -> tuple[RecordedRequest, ...]:
        with self._condition:
            return tuple(self._requests)

    @property
    def responses_request_count(self) -> int:
        return sum(
            request.method == "POST" and urlsplit(request.path).path.endswith("/responses")
            for request in self.requests
        )

    @property
    def models_request_count(self) -> int:
        return sum(
            request.method == "GET" and urlsplit(request.path).path.endswith("/models")
            for request in self.requests
        )

    @property
    def pending_fixture_count(self) -> int:
        with self._condition:
            return len(self._fixtures)

    def enqueue_assistant(self, text: str, *, response_id: str | None = None) -> None:
        if response_id is None:
            response_id = self._allocate_response_id()
        with self._condition:
            message_id = f"fixture-message-{self._next_message_number}"
            self._next_message_number += 1
            self._fixtures.append(
                ResponseFixture(
                    kind="assistant",
                    response_id=response_id,
                    message_id=message_id,
                    text=text,
                )
            )
            self._condition.notify_all()

    def enqueue_tool_call(
        self,
        tool: str,
        arguments: Mapping[str, Any],
        *,
        call_id: str,
        namespace: str | None = None,
        response_id: str | None = None,
    ) -> None:
        if not tool or not call_id:
            raise ValueError("tool and call_id must be nonempty")
        # Validate serializability before the request-handling thread needs it.
        json.dumps(dict(arguments), sort_keys=True, separators=(",", ":"))
        if response_id is None:
            response_id = self._allocate_response_id()
        with self._condition:
            self._fixtures.append(
                ResponseFixture(
                    kind="tool_call",
                    response_id=response_id,
                    call_id=call_id,
                    namespace=namespace,
                    tool=tool,
                    arguments=dict(arguments),
                )
            )
            self._condition.notify_all()

    def enqueue_custom_tool_call(
        self,
        tool: str,
        input: str,
        *,
        call_id: str,
        namespace: str | None = None,
        response_id: str | None = None,
    ) -> None:
        """Queue one Responses API custom-tool call with its exact raw input."""

        if not tool or not call_id or not input:
            raise ValueError("tool, call_id, and input must be nonempty")
        if response_id is None:
            response_id = self._allocate_response_id()
        with self._condition:
            self._fixtures.append(
                ResponseFixture(
                    kind="custom_tool_call",
                    response_id=response_id,
                    call_id=call_id,
                    namespace=namespace,
                    tool=tool,
                    input=input,
                )
            )
            self._condition.notify_all()

    def _allocate_response_id(self) -> str:
        with self._condition:
            response_id = f"fixture-response-{self._next_response_number}"
            self._next_response_number += 1
            return response_id

    def start(self) -> "DeterministicResponsesServer":
        if self._server is not None:
            raise RuntimeError("fixture server is already running")
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            server_version = "authority-continuity-responses-fixture/1"

            def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
                owner._record(self.command, self.path, None)
                if urlsplit(self.path).path.endswith("/models"):
                    self._send_json(200, {"models": []})
                else:
                    self._send_json(404, {"error": "not found"})

            def do_POST(self) -> None:  # noqa: N802 - stdlib callback name
                path = urlsplit(self.path).path
                if not path.endswith("/responses"):
                    owner._record(self.command, self.path, None)
                    self._send_json(404, {"error": "not found"})
                    return

                raw_length = self.headers.get("Content-Length")
                try:
                    length = int(raw_length or "0")
                except ValueError:
                    self._send_json(400, {"error": "invalid content length"})
                    return
                if length < 0 or length > _MAX_REQUEST_BYTES:
                    self._send_json(413, {"error": "request too large"})
                    return
                body_bytes = self.rfile.read(length)
                try:
                    body = json.loads(body_bytes) if body_bytes else None
                except json.JSONDecodeError:
                    owner._record(self.command, self.path, "<invalid-json>")
                    self._send_json(400, {"error": "invalid JSON"})
                    return
                owner._record(self.command, self.path, body)

                with owner._condition:
                    fixture = owner._fixtures.popleft() if owner._fixtures else None
                    owner._condition.notify_all()
                if fixture is None:
                    self._send_json(500, {"error": "no queued response fixture"})
                    return

                payload = _render_fixture(fixture)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(payload)
                self.wfile.flush()
                self.close_connection = True

            def _send_json(self, status: int, value: Mapping[str, Any]) -> None:
                payload = json.dumps(
                    dict(value), sort_keys=True, separators=(",", ":")
                ).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(payload)
                self.wfile.flush()
                self.close_connection = True

            def log_message(self, _format: str, *_args: Any) -> None:
                return

        self._server = ThreadingHTTPServer((self._host, self._port), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="deterministic-responses-server",
            daemon=True,
        )
        self._thread.start()
        return self

    def _record(self, method: str, path: str, body: Any) -> None:
        with self._condition:
            self._requests.append(
                RecordedRequest(
                    ordinal=len(self._requests) + 1,
                    method=method,
                    path=path,
                    body=body,
                )
            )
            self._condition.notify_all()

    def wait_for_responses_requests(self, count: int, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        with self._condition:
            while self.responses_request_count < count:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        f"timed out waiting for {count} Responses requests; "
                        f"observed {self.responses_request_count}"
                    )
                self._condition.wait(remaining)

    def assert_consumed(self) -> None:
        count = self.pending_fixture_count
        if count:
            raise AssertionError(f"{count} deterministic response fixtures were unused")

    def stop(self) -> None:
        server, thread = self._server, self._thread
        self._server = None
        self._thread = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=2.0)

    def __enter__(self) -> "DeterministicResponsesServer":
        return self.start()

    def __exit__(self, _exc_type: Any, _exc: Any, _tb: Any) -> None:
        self.stop()


__all__ = [
    "DeterministicResponsesServer",
    "RecordedRequest",
    "ResponseFixture",
]
