"""Run one history-dependent edit across official Claude, QEMU, and DeathStarBench."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import queue
import secrets
import selectors
import signal
import shutil
import socket
import socketserver
import stat
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Mapping, Sequence
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
from .mock_anthropic import DeterministicBashAnthropicServer


_DOMAIN = "qemu-agent-restore"
_SANDBOX_ID = "claude-qemu"
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
_MAX_HTTP_BYTES = 4 << 20


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _process_start_time(pid: int) -> int:
    raw = Path(f"/proc/{pid}/stat").read_text()
    end = raw.rfind(")")
    if end < 0:
        raise DemoError(f"process {pid} has malformed /proc stat")
    fields = raw[end + 2 :].split()
    if len(fields) <= 19:
        raise DemoError(f"process {pid} has truncated /proc stat")
    return int(fields[19])


def _read_nonempty_process_command(process: subprocess.Popen[bytes], timeout: float = 1) -> bytes:
    deadline = time.monotonic() + timeout
    path = Path(f"/proc/{process.pid}/cmdline")
    while True:
        try:
            command = path.read_bytes()
        except FileNotFoundError:
            command = b""
        if command:
            return command
        returncode = process.poll()
        if returncode is not None:
            raise DemoError(f"event runner exited before live identity capture: exit={returncode}")
        if time.monotonic() >= deadline:
            raise DemoError("event runner exposed an empty /proc command for one second")
        time.sleep(0.01)


def _replace_private_json(path: Path, value: Any) -> None:
    """Atomically replace a small progress record without relaxing its mode."""
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode() + b"\n"
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as output:
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        os.close(descriptor)
        temporary.unlink(missing_ok=True)


def _http(
    method: str,
    url: str,
    *,
    value: Mapping[str, Any] | None = None,
    token: str | None = None,
    headers: Mapping[str, str] | None = None,
    expected: frozenset[int] = frozenset({200}),
    timeout: float = 30,
) -> tuple[int, Any]:
    data = None if value is None else _canonical(dict(value))
    request_headers = dict(headers or {})
    if value is not None:
        request_headers.setdefault("Content-Type", "application/json")
    if token is not None:
        request_headers["Authorization"] = "Bearer " + token
    request = Request(url, data=data, headers=request_headers, method=method)
    try:
        with build_opener(ProxyHandler({})).open(request, timeout=timeout) as response:
            status = response.status
            raw = response.read(_MAX_HTTP_BYTES + 1)
    except HTTPError as error:
        status = error.code
        raw = error.read(_MAX_HTTP_BYTES + 1)
    except (OSError, URLError) as error:
        raise DemoError(f"{method} {url} failed") from error
    if status not in expected or len(raw) > _MAX_HTTP_BYTES:
        raise DemoError(f"{method} {url} returned HTTP {status}: {raw[:512]!r}")
    try:
        body = json.loads(raw)
    except json.JSONDecodeError as error:
        raise DemoError(f"{method} {url} did not return JSON") from error
    return status, body


def _json_lines(path: Path) -> list[dict[str, Any]]:
    try:
        values = [json.loads(line) for line in path.read_text().splitlines() if line]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DemoError(f"invalid JSONL evidence: {path}") from error
    if any(not isinstance(item, dict) for item in values):
        raise DemoError(f"non-object JSONL evidence: {path}")
    return values


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


def _fence_path(directory: Path, operation_id: str) -> Path:
    return directory / (sha256(operation_id.encode()).hexdigest() + ".json")


def _requirements(effect_url: str, observer_url: str, finish_url: str) -> tuple[dict[str, Any], dict[str, Any]]:
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
        "id": "qemu-agent-restore-v1",
        "results": results,
        "capacities": capacities,
        "kinds": {_KIND: reserve, _FINISH_KIND: finish},
    }
    disabled_reserve = {
        "costs": {"reservation": 1},
        "produces": {"reserved": 1},
        "retry_safe": False,
        "queryable": False,
    }
    after = {
        "id": "qemu-agent-restore-v2",
        "results": results,
        "capacities": capacities,
        "kinds": {_KIND: disabled_reserve, _FINISH_KIND: finish},
    }
    return before, after


def _binding(generation: int) -> dict[str, Any]:
    return {
        "sandbox_id": _SANDBOX_ID,
        "generation": generation,
        "host_instance_id": "qemu-host-" + secrets.token_hex(16),
        "domain": _DOMAIN,
        "allowed_kinds": [_KIND],
    }


class _EventProcess:
    def __init__(self, name: str, command: Sequence[str], root: Path, process_evidence: Path) -> None:
        self.name = name
        self.command = list(command)
        self.stdout_path = root / f"{name}.events.jsonl"
        self.stderr_path = root / f"{name}.stderr.log"
        self._stdout_log = self.stdout_path.open("xb")
        self._stderr_log = self.stderr_path.open("xb")
        os.chmod(self.stdout_path, 0o600)
        os.chmod(self.stderr_path, 0o600)
        self.process = subprocess.Popen(
            self.command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=self._stderr_log,
            cwd=root,
            start_new_session=True,
        )
        try:
            process_command = _read_nonempty_process_command(self.process)
            process_group = os.getpgid(self.process.pid)
            session = os.getsid(self.process.pid)
            start_time = _process_start_time(self.process.pid)
            executable_sha = _sha256_file(Path(f"/proc/{self.process.pid}/exe"))
            if not process_command or process_group != self.process.pid or session != self.process.pid:
                raise DemoError(
                    f"{name} did not start as an independent session: "
                    f"pid={self.process.pid} pgid={process_group} sid={session} command_bytes={len(process_command)}"
                )
            _write_private_json(
                process_evidence.parent / f"{process_evidence.name}.runner-process-command.json",
                {
                    "schema": 1,
                    "kind": "vm-demo-runner",
                    "pid": self.process.pid,
                    "process_group_id": process_group,
                    "session_id": session,
                    "start_time_ticks": start_time,
                    "command_sha256": sha256(process_command).hexdigest(),
                    "executable_sha256": executable_sha,
                },
            )
        except BaseException:
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            self._stdout_log.close()
            self._stderr_log.close()
            raise
        if self.process.stdout is None:
            raise AssertionError("event process has no stdout")
        self._events: queue.Queue[dict[str, Any] | BaseException | None] = queue.Queue()
        self.records: list[dict[str, Any]] = []
        self._reader = threading.Thread(target=self._read, daemon=True, name=name + "-events")
        self._reader.start()

    def _read(self) -> None:
        assert self.process.stdout is not None
        try:
            for raw in self.process.stdout:
                self._stdout_log.write(raw)
                self._stdout_log.flush()
                value = json.loads(raw)
                if not isinstance(value, dict):
                    raise DemoError(f"{self.name} emitted a non-object event")
                self.records.append(value)
                self._events.put(value)
        except BaseException as error:
            self._events.put(error)
        finally:
            self._events.put(None)

    def wait_event(self, event: str, timeout: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise DemoError(f"{self.name} timed out waiting for {event}")
            try:
                item = self._events.get(timeout=remaining)
            except queue.Empty as error:
                raise DemoError(f"{self.name} timed out waiting for {event}") from error
            if item is None:
                raise DemoError(f"{self.name} ended before {event}; exit={self.process.poll()}")
            if isinstance(item, BaseException):
                raise DemoError(f"{self.name} event stream failed") from item
            if item.get("event") == event:
                return item

    def wait(self, timeout: float = 60) -> None:
        try:
            returncode = self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as error:
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired as kill_error:
                raise DemoError(f"{self.name} remained live after SIGKILL") from kill_error
            raise DemoError(f"{self.name} did not exit") from error
        self._reader.join(timeout=3)
        self._stdout_log.close()
        self._stderr_log.close()
        if returncode != 0:
            detail = self.stderr_path.read_text(errors="replace")[-4000:]
            raise DemoError(f"{self.name} exited with {returncode}: {detail}")

    def close(self) -> None:
        try:
            os.killpg(self.process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        if self.process.poll() is None:
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired as error:
                    raise DemoError(f"{self.name} remained live after SIGKILL") from error
        if not self._stdout_log.closed:
            self._stdout_log.close()
        if not self._stderr_log.closed:
            self._stderr_log.close()


class _SwitchingRelay:
    def __init__(self, address: tuple[str, int], evidence: Path) -> None:
        owner = self

        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        class Handler(socketserver.BaseRequestHandler):
            def handle(self) -> None:
                owner._relay(self.request)

        self._server = Server(address, Handler)
        self.address = self._server.server_address
        self._lock = threading.Lock()
        self._target: tuple[str, int] | None = None
        self._label = "unset"
        self._sequence = 0
        self._active = 0
        self.records: list[dict[str, Any]] = []
        self._evidence = evidence
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True, name="qemu-egress-relay")
        self._thread.start()

    def set_target(self, label: str, target: tuple[str, int]) -> None:
        with self._lock:
            if self._active != 0:
                raise DemoError("cannot switch QEMU egress while a connection is active")
            self._target = target
            self._label = label

    def _relay(self, guest: socket.socket) -> None:
        with self._lock:
            target, label = self._target, self._label
            self._sequence += 1
            sequence = self._sequence
            self._active += 1
        guest_to_host = 0
        host_to_guest = 0
        started = time.time_ns()
        error = ""
        try:
            if target is None:
                raise DemoError("QEMU egress relay has no selected target")
            upstream = socket.create_connection(target, timeout=5)
            with upstream:
                guest.setblocking(False)
                upstream.setblocking(False)
                selector = selectors.DefaultSelector()
                selector.register(guest, selectors.EVENT_READ, (guest, upstream, "guest"))
                selector.register(upstream, selectors.EVENT_READ, (upstream, guest, "host"))
                while selector.get_map():
                    ready = selector.select(timeout=30)
                    if not ready:
                        raise TimeoutError("QEMU egress relay was idle for 30 seconds")
                    for key, _ in ready:
                        source, destination, direction = key.data
                        try:
                            data = source.recv(65536)
                        except BlockingIOError:
                            continue
                        if not data:
                            selector.unregister(source)
                            try:
                                destination.shutdown(socket.SHUT_WR)
                            except OSError:
                                pass
                            continue
                        destination.sendall(data)
                        if direction == "guest":
                            guest_to_host += len(data)
                        else:
                            host_to_guest += len(data)
        except BaseException as caught:
            error = repr(caught)
        finally:
            with self._lock:
                self._active -= 1
                self.records.append(
                    {
                        "sequence": sequence,
                        "label": label,
                        "started_time_ns": started,
                        "stopped_time_ns": time.time_ns(),
                        "guest_to_host_bytes": guest_to_host,
                        "host_to_guest_bytes": host_to_guest,
                        "error": error,
                    }
                )
                _replace_private_json(self._evidence, self.records)

    def wait_idle(self, timeout: float = 15) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if self._active == 0:
                    return
            time.sleep(0.05)
        raise DemoError("QEMU egress relay did not become idle")

    def records_for(self, label: str) -> list[dict[str, Any]]:
        self.wait_idle()
        with self._lock:
            return [dict(item) for item in self.records if item["label"] == label]

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=3)


class _FinishServer:
    def __init__(self, port: int) -> None:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self) -> None:  # noqa: N802
                operation = self.headers.get("X-Operation-ID", "")
                if not operation:
                    self.send_error(400)
                    return
                result = sha256(("finish\x00" + operation).encode()).hexdigest()
                body = _canonical(
                    {
                        "schema": 1,
                        "operation_id": operation,
                        "outcome": "succeeded",
                        "result_hash": result,
                        "remote_reference": "local-finish/" + operation,
                    }
                )
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, unused_format: str, *unused: object) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True, name="finish-service")
        self.thread.start()

    @property
    def url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}/v1/finish"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)


def _bash_command() -> str:
    body = json.dumps(_BODY, sort_keys=True, separators=(",", ":"))
    return (
        "curl --fail-with-body -sS -X POST "
        "-H 'Content-Type: application/json' "
        ' -H "Idempotency-Key: $SAFE_CHANGE_CALL_ID" '
        ' -H "X-Operation-ID: $SAFE_CHANGE_CALL_ID" '
        " -H 'X-Operation-Request-Hash: 0000000000000000000000000000000000000000000000000000000000000000' "
        f"--data '{body}' \"$SAFE_CHANGE_EGRESS_URL\""
    )


def _start_control(
    control_binary: Path, root: Path, sockets: Path
) -> tuple[_Process, str, str, Path, Path, Path]:
    port = _reserve_loopback_port()
    sockets.mkdir(mode=0o700)
    token_path = root / "admin.token"
    process = _Process(
        "control",
        [
            os.fspath(control_binary),
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
    return process, origin, _read_token(token_path), sockets, _sandbox_socket(sockets), token_path


def _compile(control_url: str, token: str, requirement: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    checked = _http("GET", control_url + "/v1/state", token=token)[1]
    certificate = _http("POST", control_url + "/v1/compile", value=requirement, token=token)[1]
    projection = _http("POST", control_url + "/v1/certificate-state", value=certificate, token=token)[1]
    return checked, certificate, projection


def _cutover(control_url: str, token: str, certificate: Mapping[str, Any], binding: Mapping[str, Any]) -> dict[str, Any]:
    response = _http(
        "POST",
        control_url + "/v1/cutover",
        value={"certificate": certificate, "bindings": [binding]},
        token=token,
        timeout=70,
    )[1]
    if not isinstance(response, dict) or not isinstance(response.get("state"), dict) or response.get("bindings") != [binding]:
        raise DemoError("Control cutover response does not contain the exact State and attached binding")
    return response["state"]


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


def _start_proxy(binary: Path, route: Path, sandbox: Path, root: Path, label: str) -> tuple[_Process, tuple[str, int], str]:
    port = _reserve_loopback_port()
    process = _Process(
        label,
        [
            os.fspath(binary),
            "-config",
            os.fspath(route),
            "-sandbox-socket",
            os.fspath(sandbox),
            "-listen",
            f"127.0.0.1:{port}",
            "-execute-timeout",
            "45s",
        ],
        root,
    )
    origin = f"http://127.0.0.1:{port}"
    _wait_healthy(origin, process)
    return process, ("127.0.0.1", port), origin


def _wait_socket(path: Path, timeout: float = 15) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: BaseException | None = None
    while time.monotonic() < deadline:
        try:
            info = path.lstat()
            if not stat.S_ISSOCK(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
                raise DemoError("sandbox endpoint is not a private Unix socket")
            with socket.socket(socket.AF_UNIX) as connection:
                connection.settimeout(2)
                connection.connect(os.fspath(path))
                connection.sendall(b"GET /healthz HTTP/1.1\r\nHost: sandbox\r\nConnection: close\r\n\r\n")
                response = connection.recv(256)
            if response.startswith(b"HTTP/1.1 200"):
                return {"path": os.fspath(path), "device": info.st_dev, "inode": info.st_ino, "time_ns": time.time_ns()}
        except (OSError, DemoError) as error:
            last = error
            time.sleep(0.05)
    raise DemoError(f"sandbox endpoint did not become healthy: {last}")


def _start_effect(
    binary: Path,
    address: tuple[str, int],
    frontend_url: str,
    audit: Path,
    fences: Path,
    root: Path,
    label: str,
    *,
    abort: bool,
) -> _Process:
    command = [
        os.fspath(binary),
        "-mode",
        "effect",
        "-listen",
        f"{address[0]}:{address[1]}",
        "-frontend",
        frontend_url,
        "-audit",
        os.fspath(audit),
        "-terminal-fence-directory",
        os.fspath(fences),
    ]
    if abort:
        command.extend(["-abort-before-upstream", "-pre-upstream-abort-delay", "8s"])
    else:
        command.extend(["-post-commit-delay", "8s"])
    process = _Process(label, command, root)
    _wait_healthy(f"http://{address[0]}:{address[1]}", process)
    return process


def _observer_query(observer_url: str, operation_id: str, request_hash: str) -> dict[str, Any]:
    body = _http(
        "POST",
        observer_url,
        value=_BODY,
        headers={"X-Operation-ID": operation_id, "X-Operation-Request-Hash": request_hash},
    )[1]
    reference = body.get("remote_reference")
    if not isinstance(reference, str) or "count=" not in reference:
        raise DemoError("observer response omits Mongo count")
    try:
        count = int(reference.split("count=", 1)[1].split(";", 1)[0])
    except ValueError as error:
        raise DemoError("observer returned malformed Mongo count") from error
    return {"time_ns": time.time_ns(), "count": count, "body": body}


def _wait_delivery(audit: Path, operation_id: str, count: int, timeout: float = 30) -> list[dict[str, Any]]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        matches = [item for item in _json_lines(audit) if item.get("operation_id") == operation_id]
        if len(matches) >= count:
            if len(matches) != count:
                raise DemoError(f"operation {operation_id} has too many application deliveries")
            return matches
        time.sleep(0.05)
    raise DemoError(f"operation {operation_id} did not reach DeathStarBench")


def _wait_model_request(
    model: DeterministicBashAnthropicServer,
    count: int,
    lane: str,
    timeout: float = 90,
) -> None:
    try:
        model.wait_for_requests(count, timeout=timeout)
    except Exception as error:
        failure = model.failure
        detail = "none" if failure is None else f"{type(failure).__name__}: {failure}"
        raise DemoError(
            f"{lane} official Claude did not reach the Anthropic Messages endpoint: "
            f"observed={len(model.requests)} required={count} fixture_failure={detail}"
        ) from error


def _delivery_count(audit: Path, operation_id: str) -> int:
    return sum(item.get("operation_id") == operation_id for item in _json_lines(audit))


def _wait_fence(path: Path, operation_id: str, timeout: float = 30) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = json.loads(path.read_bytes())
        except FileNotFoundError:
            time.sleep(0.05)
            continue
        except (OSError, json.JSONDecodeError) as error:
            raise DemoError("terminal fence is malformed") from error
        if value.get("operation_id") != operation_id or value.get("disposition") != "terminal-pre-upstream-abort":
            raise DemoError("terminal fence addresses another Operation")
        return value
    raise DemoError("terminal pre-upstream fence was not recorded")


def _wait_operation(control_url: str, token: str, operation_id: str, phase: str, timeout: float = 20) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = _http("GET", control_url + "/v1/state", token=token)[1]
        operation = (state.get("operations") or {}).get(operation_id)
        if isinstance(operation, dict) and operation.get("phase") == phase:
            return operation
        time.sleep(0.05)
    raise DemoError(f"Operation {operation_id} did not become {phase}")


def _copy_checkpoint(source: Path, destination: Path, expected: str) -> None:
    if destination.exists():
        raise DemoError(f"lane checkpoint already exists: {destination}")
    completed = subprocess.run(
        ["cp", "--reflink=auto", "--sparse=always", os.fspath(source), os.fspath(destination)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise DemoError(f"cannot copy sealed checkpoint: {completed.stdout}")
    os.chmod(destination, 0o600)
    if _sha256_file(destination) != expected:
        raise DemoError("lane checkpoint differs from sealed base before QEMU open")


def _qemu_base_command(
    qemu_binary: Path,
    image: Path,
    image_sha: str,
    claude: Path,
    claude_sha: str,
    metadata_address: tuple[str, int],
    model_address: tuple[str, int],
    relay_address: tuple[str, int],
    accel: str,
) -> list[str]:
    return [
        os.fspath(qemu_binary),
        "-accel",
        accel,
        "-timeout",
        "12m",
        "-image",
        os.fspath(image),
        "-image-url",
        "",
        "-image-sha256",
        image_sha,
        "-agent-claude",
        os.fspath(claude),
        "-agent-claude-sha256",
        claude_sha,
        "-agent-metadata-listen",
        f"{metadata_address[0]}:{metadata_address[1]}",
        "-agent-model-target",
        f"{model_address[0]}:{model_address[1]}",
        "-agent-egress-target",
        f"{relay_address[0]}:{relay_address[1]}",
    ]


def _prepare_checkpoint(command: list[str], root: Path, checkpoint: Path, evidence: Path) -> tuple[str, dict[str, Any]]:
    evidence.mkdir(mode=0o700)
    process = _EventProcess(
        "prepare",
        [*command, "-agent-mode", "prepare", "-agent-overlay", os.fspath(checkpoint), "-agent-evidence-dir", os.fspath(evidence)],
        root,
        evidence,
    )
    completed = False
    try:
        event = process.wait_event("checkpoint-sealed", 10 * 60)
        process.wait()
        completed = True
        digest = event.get("checkpoint_sha256")
        if not isinstance(digest, str) or digest != _sha256_file(checkpoint):
            raise DemoError("sealed checkpoint event differs from retained qcow2")
        return digest, event
    finally:
        if not completed:
            process.close()


def _start_qemu_phase(
    command: list[str],
    root: Path,
    *,
    name: str,
    mode: str,
    overlay: Path,
    sealed: Path,
    sealed_sha: str,
    evidence: Path,
    session: str,
    barrier: Path | None = None,
    manifest: Path | None = None,
) -> _EventProcess:
    evidence.mkdir(mode=0o700)
    arguments = [
        *command,
        "-agent-mode",
        mode,
        "-agent-overlay",
        os.fspath(overlay),
        "-agent-sealed-checkpoint",
        os.fspath(sealed),
        "-agent-sealed-sha256",
        sealed_sha,
        "-agent-preopen-sha256",
        sealed_sha,
        "-agent-evidence-dir",
        os.fspath(evidence),
        "-agent-session-id",
        session,
    ]
    if barrier is not None:
        arguments.extend(["-agent-kill-barrier", os.fspath(barrier)])
    if manifest is not None:
        arguments.extend(["-agent-guard-manifest", os.fspath(manifest)])
    return _EventProcess(name, arguments, root, evidence)


def _source_phase(
    qemu_command: list[str],
    lane_root: Path,
    sealed: Path,
    sealed_sha: str,
    session: str,
    observe: callable,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    overlay = lane_root / "source.qcow2"
    _copy_checkpoint(sealed, overlay, sealed_sha)
    evidence = lane_root / "source-vm"
    barrier = lane_root / "source-barrier.input.json"
    process = _start_qemu_phase(
        qemu_command,
        lane_root,
        name="source-vm-runner",
        mode="source",
        overlay=overlay,
        sealed=sealed,
        sealed_sha=sealed_sha,
        evidence=evidence,
        session=session,
        barrier=barrier,
    )
    completed = False
    try:
        process.wait_event("snapshot-loaded-halted", 90)
        process.wait_event("claude-started", 180)
        external = observe()
        _write_private_json(barrier, {"schema": 1, "external_fact_observed": True, **external})
        process.wait_event("source-stopped", 90)
        process.wait()
        completed = True
        overlay.unlink()
        return external, process.records
    finally:
        if not completed:
            process.close()


def _restore_phase(
    qemu_command: list[str],
    lane_root: Path,
    sealed: Path,
    sealed_sha: str,
    session: str,
    *,
    manifest: Path | None,
    expected_event: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    overlay = lane_root / "restore.qcow2"
    _copy_checkpoint(sealed, overlay, sealed_sha)
    evidence = lane_root / "restore-vm"
    process = _start_qemu_phase(
        qemu_command,
        lane_root,
        name="restore-vm-runner",
        mode="restore",
        overlay=overlay,
        sealed=sealed,
        sealed_sha=sealed_sha,
        evidence=evidence,
        session=session,
        manifest=manifest,
    )
    completed = False
    try:
        process.wait_event("snapshot-loaded-halted", 90)
        terminal = process.wait_event(expected_event, 6 * 60)
        process.wait()
        completed = True
        overlay.unlink()
        return terminal, process.records
    finally:
        if not completed:
            process.close()


def _guard_manifest(
    path: Path,
    checked: Mapping[str, Any],
    certificate: Mapping[str, Any],
    activated_history: Mapping[str, Any],
    binding: Mapping[str, Any],
    endpoint: Path,
    control_url: str,
    control_token_path: Path,
) -> None:
    _write_private_json(
        path,
        {
            "schema": 2,
            "checked_state": checked,
            "certificate": certificate,
            "activated_history": dict(activated_history),
            "binding": binding,
            "endpoint_path": os.fspath(endpoint),
            "control_url": control_url,
            "control_token_path": os.fspath(control_token_path),
        },
    )


def run(
    *,
    qemu_binary: Path,
    image: Path,
    image_sha256: str,
    claude_binary: Path,
    claude_sha256: str,
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
    accel: str,
) -> dict[str, Any]:
    if repetitions < 1 or repetitions > 5:
        raise DemoError("repetitions must be between one and five")
    if _sha256_file(claude_binary) != claude_sha256:
        raise DemoError("official Claude artifact hash differs")
    graph = json.loads(graph_evidence.read_bytes())
    if graph.get("pass") is not True or graph.get("official_services") != 24:
        raise DemoError("DeathStarBench graph evidence is incomplete")
    root = _private_directory(evidence_dir)
    started_time_ns = time.time_ns()
    completed_stages: list[str] = []

    def progress(stage: str, *, status: str = "running", error: str | None = None) -> None:
        if stage and (not completed_stages or completed_stages[-1] != stage):
            completed_stages.append(stage)
        now = time.time_ns()
        record: dict[str, Any] = {
            "schema": 1,
            "status": status,
            "stage": stage,
            "completed_stages": list(completed_stages),
            "started_time_ns": started_time_ns,
            "updated_time_ns": now,
            "elapsed_seconds": (now - started_time_ns) / 1_000_000_000,
            "repetitions": repetitions,
        }
        if error is not None:
            record["error"] = error
        _replace_private_json(root / "progress.json", record)

    progress("initialized")
    transport_root = Path(tempfile.mkdtemp(prefix="qemu-agent-restore-", dir="/tmp"))
    os.chmod(transport_root, 0o700)
    checkpoints = root / "checkpoints"
    runs = root / "runs"
    checkpoints.mkdir(mode=0o700)
    runs.mkdir(mode=0o700)
    metadata_address = ("127.0.0.1", _reserve_loopback_port())
    model_address = ("127.0.0.1", _reserve_loopback_port())
    relay_port = _reserve_loopback_port()
    finish_port = _reserve_loopback_port()
    relay = _SwitchingRelay(("127.0.0.1", relay_port), root / "egress-relay.json")
    finish = _FinishServer(finish_port)
    effect_url = f"http://{effect_address[0]}:{effect_address[1]}/v1/reserve"
    before, after = _requirements(effect_url, observer_url, finish.url)
    _write_private_json(root / "requirement-v1.json", before)
    _write_private_json(root / "requirement-v2.json", after)
    qemu_command = _qemu_base_command(
        qemu_binary,
        image,
        image_sha256,
        claude_binary,
        claude_sha256,
        metadata_address,
        model_address,
        ("127.0.0.1", relay_port),
        accel,
    )
    protected: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    native: list[dict[str, Any]] = []
    services: list[_Process] = []
    control_token_paths: list[Path] = []
    effect: _Process | None = None
    model = DeterministicBashAnthropicServer(_bash_command(), port=model_address[1])
    run_succeeded = False

    def close_effect() -> None:
        nonlocal effect
        if effect is not None:
            effect.close()
            effect = None

    def close_control(process: _Process, token_path: Path) -> None:
        try:
            process.close()
        finally:
            token_path.unlink(missing_ok=True)
            if token_path in control_token_paths:
                control_token_paths.remove(token_path)

    try:
        with model:
            for repetition in range(1, repetitions + 1):
                checkpoint_root = checkpoints / f"run-{repetition}"
                checkpoint_root.mkdir(mode=0o700)
                sealed = checkpoint_root / "sealed.qcow2"
                sealed_sha, checkpoint_event = _prepare_checkpoint(
                    qemu_command, checkpoint_root, sealed, checkpoint_root / "prepare-vm"
                )
                _write_private_json(checkpoint_root / "sealed.json", checkpoint_event)
                progress(f"run-{repetition}-checkpoint-sealed")

                # H1: the request is unknown at failure, the external result exists,
                # and the exact target is activated before guarded resume.
                h1 = runs / f"run-{repetition}" / "h1"
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
                control_process, control_url, token, sockets, sandbox, token_path = _start_control(
                    control_binary, h1, transport_root / f"run-{repetition}-h1"
                )
                control_token_paths.append(token_path)
                services.append(control_process)
                route = h1 / "route.json"
                _write_route(route, effect_url)
                _, initial_certificate, _ = _compile(control_url, token, before)
                source_binding = _binding(1)
                _cutover(control_url, token, initial_certificate, source_binding)
                _wait_socket(sandbox)
                source_proxy, source_target, source_origin = _start_proxy(
                    effect_proxy_binary, route, sandbox, h1, "source-proxy"
                )
                services.append(source_proxy)
                session = secrets.token_hex(16)
                operation_id = _operation_id(session)
                relay_label = f"run-{repetition}-h1-source"
                relay.set_target(relay_label, source_target)
                h1_model_request = len(model.requests) + 1

                def observe_h1() -> dict[str, Any]:
                    _wait_model_request(model, h1_model_request, "H1 source")
                    delivery = _wait_delivery(adapter_audit, operation_id, 1)[0]
                    operation = _wait_operation(control_url, token, operation_id, "dispatched")
                    observation = _observer_query(observer_url, operation_id, operation["request_hash"])
                    if observation["count"] != 1:
                        raise DemoError("H1 Mongo result is absent")
                    return {
                        "lane": "h1",
                        "operation_id": operation_id,
                        "request_hash": operation["request_hash"],
                        "mongo_count": 1,
                        "application_commit_time_ns": delivery["committed_time_ns"],
                        "observer_time_ns": observation["time_ns"],
                    }

                h1_external, h1_source_events = _source_phase(
                    qemu_command, h1, sealed, sealed_sha, session, observe_h1
                )
                relay_source = relay.records_for(relay_label)
                if len(relay_source) != 1 or relay_source[0]["host_to_guest_bytes"] != 0:
                    raise DemoError(f"H1 source received response bytes: {relay_source}")
                _wait_operation(control_url, token, operation_id, "unknown")
                unknown_state = _http("GET", control_url + "/v1/state", token=token)[1]
                _write_private_json(h1 / "unknown-state.json", unknown_state)
                recovered = _http(
                    "POST", control_url + f"/v1/operations/{operation_id}/recover", token=token
                )[1]
                if recovered.get("phase") != "succeeded":
                    raise DemoError("H1 authoritative recovery did not settle success")
                checked, target_certificate, projection = _compile(control_url, token, after)
                if target_certificate.get("decision") != "activate":
                    raise DemoError("H1 target did not activate")
                replacement_binding = _binding(2)
                cutover_state = _cutover(control_url, token, target_certificate, replacement_binding)
                cutover_time_ns = time.time_ns()
                _write_private_json(
                    h1 / "target-cutover.json",
                    {"schema": 1, "completed_time_ns": cutover_time_ns, "state": cutover_state},
                )
                endpoint = _wait_socket(sandbox)
                _write_private_json(h1 / "endpoint-publication.json", {"schema": 1, **endpoint})
                replacement_proxy, replacement_target, _ = _start_proxy(
                    effect_proxy_binary, route, sandbox, h1, "replacement-proxy"
                )
                services.append(replacement_proxy)
                before_stale = _delivery_count(adapter_audit, operation_id)
                stale_status, stale_response = _http(
                    "POST",
                    source_origin + "/v1/reserve",
                    value=_BODY,
                    headers={"Idempotency-Key": session},
                    expected=frozenset(range(400, 600)),
                    timeout=5,
                )
                if _delivery_count(adapter_audit, operation_id) != before_stale:
                    raise DemoError("stale H1 generation reached DeathStarBench")
                current = _http("GET", control_url + "/v1/state", token=token)[1]
                bindings = _http("GET", control_url + "/v1/sandbox-bindings", token=token)[1]
                if current != cutover_state or replacement_binding not in bindings:
                    raise DemoError("H1 live Control view differs from the completed cutover")
                manifest = h1 / "resume-manifest.json"
                _guard_manifest(
                    manifest,
                    checked,
                    target_certificate,
                    current["history"],
                    replacement_binding,
                    sandbox,
                    control_url,
                    token_path,
                )
                _write_private_json(h1 / "certificate.json", target_certificate)
                _write_private_json(h1 / "certificate-state.json", projection)
                _write_private_json(h1 / "checked-state.json", checked)
                _write_private_json(h1 / "current-state.json", current)
                relay_label = f"run-{repetition}-h1-restore"
                relay.set_target(relay_label, replacement_target)
                terminal, h1_restore_events = _restore_phase(
                    qemu_command,
                    h1,
                    sealed,
                    sealed_sha,
                    session,
                    manifest=manifest,
                    expected_event="restore-completed",
                )
                if terminal.get("decision") != "activate":
                    raise DemoError("H1 guarded restore did not use activate")
                final_h1 = _observer_query(observer_url, operation_id, checked["operations"][operation_id]["request_hash"])
                if final_h1["count"] != 1 or _delivery_count(adapter_audit, operation_id) != 1:
                    raise DemoError("H1 Restore duplicated the reservation")
                protected.append(
                    {
                        "run": repetition,
                        "session": session,
                        "operation_id": operation_id,
                        "checkpoint_sha256": sealed_sha,
                        "target_sha256": sha256(_canonical(after)).hexdigest(),
                        "decision": "activate",
                        "mongo_rows": 1,
                        "deliveries": 1,
                        "task_completed": True,
                        "source_external": h1_external,
                        "source_relay": relay_source,
                        "restore_relay": relay.records_for(relay_label),
                        "stale_status": stale_status,
                        "stale_response": stale_response,
                        "endpoint": endpoint,
                        "source_events": h1_source_events,
                        "restore_events": h1_restore_events,
                    }
                )
                close_effect()
                replacement_proxy.close()
                source_proxy.close()
                close_control(control_process, token_path)
                services = [item for item in services if item not in {replacement_proxy, source_proxy, control_process}]
                progress(f"run-{repetition}-h1-complete")

                # H0: the same unknown state is resolved by a terminal
                # pre-upstream fence plus zero Mongo rows. Resume is attempted
                # through the same guard and denied before QMP cont.
                h0 = runs / f"run-{repetition}" / "h0"
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
                control_process, control_url, token, sockets, sandbox, token_path = _start_control(
                    control_binary, h0, transport_root / f"run-{repetition}-h0"
                )
                control_token_paths.append(token_path)
                services.append(control_process)
                route = h0 / "route.json"
                _write_route(route, effect_url)
                _, initial_certificate, _ = _compile(control_url, token, before)
                source_binding = _binding(1)
                _cutover(control_url, token, initial_certificate, source_binding)
                _wait_socket(sandbox)
                source_proxy, source_target, _ = _start_proxy(
                    effect_proxy_binary, route, sandbox, h0, "source-proxy"
                )
                services.append(source_proxy)
                session = secrets.token_hex(16)
                operation_id = _operation_id(session)
                fence_path = _fence_path(fence_directory, operation_id)
                relay_label = f"run-{repetition}-h0-source"
                relay.set_target(relay_label, source_target)
                h0_model_request = len(model.requests) + 1

                def observe_h0() -> dict[str, Any]:
                    _wait_model_request(model, h0_model_request, "H0 source")
                    fence = _wait_fence(fence_path, operation_id)
                    observation = _observer_query(observer_url, operation_id, fence["request_hash"])
                    if observation["count"] != 0 or observation["body"].get("outcome") != "failed":
                        raise DemoError("H0 zero rows plus terminal fence did not settle failure")
                    if _delivery_count(adapter_audit, operation_id) != 0:
                        raise DemoError("H0 reached DeathStarBench before its terminal fence")
                    return {
                        "lane": "h0",
                        "operation_id": operation_id,
                        "request_hash": fence["request_hash"],
                        "mongo_count": 0,
                        "terminal_fence": fence,
                        "observer_time_ns": observation["time_ns"],
                    }

                h0_external, h0_source_events = _source_phase(
                    qemu_command, h0, sealed, sealed_sha, session, observe_h0
                )
                relay_source = relay.records_for(relay_label)
                if len(relay_source) != 1 or relay_source[0]["host_to_guest_bytes"] != 0:
                    raise DemoError(f"H0 source received response bytes: {relay_source}")
                _wait_operation(control_url, token, operation_id, "unknown")
                unknown_state = _http("GET", control_url + "/v1/state", token=token)[1]
                _write_private_json(h0 / "unknown-state.json", unknown_state)
                recovered = _http(
                    "POST", control_url + f"/v1/operations/{operation_id}/recover", token=token
                )[1]
                if recovered.get("phase") != "failed":
                    raise DemoError("H0 authoritative recovery did not settle failure")
                checked, target_certificate, projection = _compile(control_url, token, after)
                if target_certificate.get("decision") != "impossible":
                    raise DemoError("H0 target was not impossible")
                current = _http("GET", control_url + "/v1/state", token=token)[1]
                bindings = _http("GET", control_url + "/v1/sandbox-bindings", token=token)[1]
                if source_binding not in bindings:
                    raise DemoError("H0 source binding is absent from live Control")
                manifest = h0 / "resume-manifest.json"
                _guard_manifest(
                    manifest,
                    checked,
                    target_certificate,
                    current["history"],
                    source_binding,
                    sandbox,
                    control_url,
                    token_path,
                )
                _write_private_json(h0 / "certificate.json", target_certificate)
                _write_private_json(h0 / "certificate-state.json", projection)
                _write_private_json(h0 / "checked-state.json", checked)
                _write_private_json(h0 / "current-state.json", current)
                relay_label = f"run-{repetition}-h0-restore"
                relay.set_target(relay_label, source_target)
                terminal, h0_restore_events = _restore_phase(
                    qemu_command,
                    h0,
                    sealed,
                    sealed_sha,
                    session,
                    manifest=manifest,
                    expected_event="resume-denied",
                )
                if terminal.get("resume_denied") is not True:
                    raise DemoError("H0 actual guarded resume was not denied")
                time.sleep(0.2)
                if _delivery_count(adapter_audit, operation_id) != 0:
                    raise DemoError("H0 committed after denied resume")
                rejected.append(
                    {
                        "run": repetition,
                        "session": session,
                        "operation_id": operation_id,
                        "checkpoint_sha256": sealed_sha,
                        "target_sha256": sha256(_canonical(after)).hexdigest(),
                        "decision": "impossible",
                        "mongo_rows": 0,
                        "deliveries": 0,
                        "task_completed": False,
                        "resume_denied": True,
                        "source_external": h0_external,
                        "source_relay": relay_source,
                        "restore_relay": relay.records_for(relay_label),
                        "source_events": h0_source_events,
                        "restore_events": h0_restore_events,
                    }
                )
                close_effect()
                source_proxy.close()
                close_control(control_process, token_path)
                services = [item for item in services if item not in {source_proxy, control_process}]
                progress(f"run-{repetition}-h0-complete")

                # Native baseline: identical Agent/checkpoint/application path,
                # but the stable request goes directly to the application adapter.
                raw = runs / f"run-{repetition}" / "native"
                raw.mkdir(mode=0o700, parents=True)
                effect = _start_effect(
                    deathstar_adapter_binary,
                    effect_address,
                    frontend_url,
                    adapter_audit,
                    fence_directory,
                    raw,
                    "effect-native",
                    abort=False,
                )
                session = secrets.token_hex(16)
                operation_id = session
                relay_label = f"run-{repetition}-native-source"
                relay.set_target(relay_label, effect_address)
                native_model_request = len(model.requests) + 1

                def observe_native() -> dict[str, Any]:
                    _wait_model_request(model, native_model_request, "native source")
                    delivery = _wait_delivery(adapter_audit, operation_id, 1)[0]
                    observation = _observer_query(observer_url, operation_id, "0" * 64)
                    if observation["count"] != 1:
                        raise DemoError("native source did not commit exactly once")
                    return {
                        "lane": "native",
                        "operation_id": operation_id,
                        "request_hash": "0" * 64,
                        "mongo_count": 1,
                        "application_commit_time_ns": delivery["committed_time_ns"],
                        "observer_time_ns": observation["time_ns"],
                    }

                native_external, native_source_events = _source_phase(
                    qemu_command, raw, sealed, sealed_sha, session, observe_native
                )
                source_relay = relay.records_for(relay_label)
                if len(source_relay) != 1 or source_relay[0]["host_to_guest_bytes"] != 0:
                    raise DemoError("native source received a response before VMM loss")
                relay_label = f"run-{repetition}-native-restore"
                relay.set_target(relay_label, effect_address)
                terminal, native_restore_events = _restore_phase(
                    qemu_command,
                    raw,
                    sealed,
                    sealed_sha,
                    session,
                    manifest=None,
                    expected_event="restore-completed",
                )
                _wait_delivery(adapter_audit, operation_id, 2)
                final_native = _observer_query(observer_url, operation_id, "0" * 64)
                if final_native["count"] != 2:
                    raise DemoError("native QEMU replay did not duplicate the reservation")
                native.append(
                    {
                        "run": repetition,
                        "session": session,
                        "operation_id": operation_id,
                        "checkpoint_sha256": sealed_sha,
                        "target_sha256": sha256(_canonical(after)).hexdigest(),
                        "decision": "native-unguarded",
                        "mongo_rows": 2,
                        "deliveries": 2,
                        "task_completed": True,
                        "source_external": native_external,
                        "source_relay": source_relay,
                        "restore_relay": relay.records_for(relay_label),
                        "source_events": native_source_events,
                        "restore_events": native_restore_events,
                    }
                )
                close_effect()
                progress(f"run-{repetition}-native-complete")

            model_requests = [asdict(item) for item in model.requests]
            if model.failure is not None or len(model_requests) != repetitions * 7:
                raise DemoError(
                    f"official Claude model protocol has {len(model_requests)} requests, want {repetitions * 7}"
                )

        observer_facts = _http(
            "GET", observer_url.removesuffix("/v1/query") + "/v1/stats/facts"
        )[1]
        _write_private_json(root / "observer-facts.json", observer_facts)
        result = {
            "schema": 1,
            "valid": True,
            "system": "official-claude-full-qemu-history-dependent-restore",
            "repetitions": repetitions,
            "transparency": {
                "claude_source_modified": False,
                "deathstar_source_modified": False,
                "guest_uses_ordinary_bash_http": True,
                "agent_runtime_integration_required": False,
            },
            "h1": protected,
            "h0": rejected,
            "native": native,
            "same_target_sha256": len({item["target_sha256"] for item in [*protected, *rejected]}) == 1,
            "matched_checkpoint_per_run": all(
                protected[index]["checkpoint_sha256"]
                == rejected[index]["checkpoint_sha256"]
                == native[index]["checkpoint_sha256"]
                for index in range(repetitions)
            ),
            "model_requests": repetitions * 7,
            "graph": graph,
            "artifacts": {
                "qemu_runner": _sha256_file(qemu_binary),
                "claude": claude_sha256,
                "ubuntu_image": image_sha256,
                "control": _sha256_file(control_binary),
                "effect_proxy": _sha256_file(effect_proxy_binary),
                "deathstar_adapter": _sha256_file(deathstar_adapter_binary),
            },
        }
        result["valid"] = bool(
            result["same_target_sha256"]
            and result["matched_checkpoint_per_run"]
            and all(item["mongo_rows"] == 1 and item["task_completed"] for item in protected)
            and all(item["mongo_rows"] == 0 and item["resume_denied"] for item in rejected)
            and all(item["mongo_rows"] == 2 and item["task_completed"] for item in native)
        )
        _write_private_json(root / "result.json", result)
        progress("complete", status="complete")
        run_succeeded = True
        return result
    finally:
        active_exception = sys.exc_info()[1]
        active_error = active_exception is not None
        cleanup_errors: list[BaseException] = []
        try:
            model_requests = [asdict(item) for item in model.requests]
            _replace_private_json(root / "anthropic-requests.json", model_requests)
            model_failure = model.failure
            _replace_private_json(
                root / "anthropic-status.json",
                {
                    "schema": 1,
                    "request_count": len(model_requests),
                    "failure": None
                    if model_failure is None
                    else {
                        "type": type(model_failure).__name__,
                        "message": str(model_failure),
                    },
                },
            )
        except BaseException as error:
            cleanup_errors.append(error)
        try:
            close_effect()
        except BaseException as error:
            cleanup_errors.append(error)
        for service in reversed(services):
            try:
                service.close()
            except BaseException as error:
                cleanup_errors.append(error)
        for token_path in control_token_paths:
            try:
                token_path.unlink(missing_ok=True)
            except BaseException as error:
                cleanup_errors.append(error)
        for close in (finish.close, relay.close):
            try:
                close()
            except BaseException as error:
                cleanup_errors.append(error)
        try:
            shutil.rmtree(transport_root)
        except BaseException as error:
            cleanup_errors.append(error)
        if not run_succeeded:
            try:
                detail = (
                    "driver terminated before producing a valid result"
                    if active_exception is None
                    else f"{type(active_exception).__name__}: {active_exception}"
                )
                progress("failed", status="failed", error=detail)
            except BaseException:
                pass
        if cleanup_errors and not active_error:
            raise DemoError(f"runtime cleanup failed: {cleanup_errors[0]}")


def _parse_address(value: str) -> tuple[str, int]:
    host, separator, port = value.rpartition(":")
    if separator != ":" or host != "127.0.0.1":
        raise argparse.ArgumentTypeError("address must be 127.0.0.1:PORT")
    try:
        number = int(port)
    except ValueError as error:
        raise argparse.ArgumentTypeError("address port is invalid") from error
    if number < 1 or number > 65535:
        raise argparse.ArgumentTypeError("address port is out of range")
    return host, number


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--qemu-binary", required=True, type=Path)
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--image-sha256", required=True)
    parser.add_argument("--claude-binary", required=True, type=Path)
    parser.add_argument("--claude-sha256", required=True)
    parser.add_argument("--control-binary", required=True, type=Path)
    parser.add_argument("--effect-proxy-binary", required=True, type=Path)
    parser.add_argument("--deathstar-adapter-binary", required=True, type=Path)
    parser.add_argument("--frontend-url", required=True)
    parser.add_argument("--effect-address", required=True, type=_parse_address)
    parser.add_argument("--observer-url", required=True)
    parser.add_argument("--adapter-audit", required=True, type=Path)
    parser.add_argument("--fence-directory", required=True, type=Path)
    parser.add_argument("--graph-evidence", required=True, type=Path)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--accel", choices=("kvm", "tcg"), default="kvm")
    args = parser.parse_args()
    try:
        result = run(
            qemu_binary=_owned_executable(args.qemu_binary.resolve(), "QEMU Agent runner"),
            image=args.image.resolve(strict=True),
            image_sha256=args.image_sha256,
            claude_binary=_owned_executable(args.claude_binary.resolve(), "Claude"),
            claude_sha256=args.claude_sha256,
            control_binary=_owned_executable(args.control_binary.resolve(), "Control"),
            effect_proxy_binary=_owned_executable(args.effect_proxy_binary.resolve(), "effect proxy"),
            deathstar_adapter_binary=_owned_executable(args.deathstar_adapter_binary.resolve(), "DeathStar adapter"),
            frontend_url=args.frontend_url,
            effect_address=args.effect_address,
            observer_url=args.observer_url,
            adapter_audit=args.adapter_audit.resolve(strict=True),
            fence_directory=args.fence_directory.resolve(strict=True),
            graph_evidence=args.graph_evidence.resolve(strict=True),
            evidence_dir=args.evidence_dir.resolve(),
            repetitions=args.repetitions,
            accel=args.accel,
        )
    except (DemoError, OSError, ValueError) as error:
        print(f"qemu Agent Restore demo failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
