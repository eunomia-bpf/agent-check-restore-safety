"""Run official Claude Code across complete Firecracker VMM loss."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import selectors
import signal
import stat
import subprocess
import tempfile
import time
from typing import Any, BinaryIO, Mapping, Sequence

from .claude_mcp_runtime_demo import (
    _DOMAIN,
    _EFFECTS,
    _EXECUTION_ID,
    _MCP_NAME,
    _SANDBOX_ID,
    _decode_operation_body,
    _json_lines,
    _load_claude_lock,
    _requirement,
    _sandbox_socket,
    _wait_held_commit,
    _wait_journal_completion,
)
from .codex_mcp_runtime_demo import (
    DemoError,
    _Process,
    _http_json,
    _owned_executable,
    _private_directory,
    _read_token,
    _reserve_loopback_port,
    _sha256_file,
    _wait_healthy,
    _write_private_json,
)
from .mock_anthropic import DeterministicAnthropicServer


class _ClaudeCell:
    def __init__(
        self,
        *,
        label: str,
        generation: int,
        cell_binary: Path,
        guest_binary: Path,
        payload: Path,
        payload_sha256: str,
        claude_sha256: str,
        relay_sha256: str,
        model_target: str,
        mcp_host_socket: Path | None,
        evidence: Path,
        root: Path,
        profile: str = "mcp",
        egress_target: str | None = None,
        busybox_sha256: str | None = None,
        bash_sha256: str | None = None,
        session_id: str | None = None,
        launch_manifest: Path | None = None,
    ) -> None:
        self.label = label
        self.generation = generation
        self.evidence = evidence
        self.evidence.mkdir(mode=0o700)
        self.command = [
            os.fspath(cell_binary),
            "-generation",
            str(generation),
            "-guest",
            os.fspath(guest_binary),
            "-payload",
            os.fspath(payload),
            "-payload-sha256",
            payload_sha256,
            "-claude-sha256",
            claude_sha256,
            "-relay-sha256",
            relay_sha256,
            "-model-target",
            model_target,
            "-evidence-dir",
            os.fspath(evidence),
        ]
        if session_id is not None:
            self.command.extend(["-session-id", session_id])
        if launch_manifest is not None:
            self.command.extend(["-launch-manifest", os.fspath(launch_manifest)])
        if profile == "mcp":
            if mcp_host_socket is None:
                raise DemoError("MCP Claude cell requires its host socket")
            self.command.extend(["-mcp-host-socket", os.fspath(mcp_host_socket)])
        elif profile == "http":
            if egress_target is None or busybox_sha256 is None or bash_sha256 is None:
                raise DemoError("HTTP Claude cell requires egress, BusyBox, and Bash")
            self.command.extend(
                [
                    "-profile",
                    "http",
                    "-egress-target",
                    egress_target,
                    "-busybox-sha256",
                    busybox_sha256,
                    "-bash-sha256",
                    bash_sha256,
                ]
            )
        else:
            raise DemoError(f"unsupported Claude cell profile {profile!r}")
        self.stdout_path = root / f"{label}.stdout.jsonl"
        self.stderr_path = root / f"{label}.stderr.log"
        self._stdout_record: BinaryIO = self.stdout_path.open("xb")
        self._stderr: BinaryIO = self.stderr_path.open("xb")
        os.chmod(self.stdout_path, 0o600)
        os.chmod(self.stderr_path, 0o600)
        self.started_time_ns = time.time_ns()
        self.process = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._stderr,
            cwd=root,
            env={
                "PATH": "/usr/bin:/bin",
                "LANG": "C",
                "LC_ALL": "C",
                "HOME": os.fspath(Path.home()),
            },
            start_new_session=True,
        )
        try:
            identity_deadline = time.monotonic() + 1
            command = b""
            while not command:
                command = Path(f"/proc/{self.process.pid}/cmdline").read_bytes()
                if command:
                    break
                if self.process.poll() is not None or time.monotonic() >= identity_deadline:
                    raise DemoError(f"{label} runner identity is unavailable")
                time.sleep(0.01)
            raw_stat = Path(f"/proc/{self.process.pid}/stat").read_text()
            stat_end = raw_stat.rfind(")")
            fields = raw_stat[stat_end + 2 :].split() if stat_end >= 0 else []
            runner = {
                "schema": 1,
                "kind": "firecracker-cell-runner",
                "pid": self.process.pid,
                "process_group_id": os.getpgid(self.process.pid),
                "session_id": os.getsid(self.process.pid),
                "start_time_ticks": int(fields[19]) if len(fields) > 19 else 0,
                "command_sha256": sha256(command).hexdigest(),
                "executable_sha256": _sha256_file(Path(f"/proc/{self.process.pid}/exe")),
            }
            if (
                not command
                or runner["process_group_id"] != self.process.pid
                or runner["session_id"] != self.process.pid
                or runner["start_time_ticks"] <= 0
            ):
                raise DemoError(f"{label} runner identity is incomplete")
            _write_private_json(root / f"{label}.runner-process.json", runner)
            self.runner = runner
        except BaseException:
            self.close()
            raise
        if self.process.stdin is None or self.process.stdout is None:
            self.close()
            raise DemoError("Claude cell did not expose control streams")
        self.events: list[dict[str, Any]] = []
        self.stopped_time_ns = 0
        self.exit_code: int | None = None

    def wait_ready(self) -> dict[str, Any]:
        event = self._wait_event("ready", 60)
        if event.get("generation") != self.generation:
            raise DemoError(f"{self.label} READY has a different generation")
        return event

    def kill_vmm(self) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(b"kill\n")
        self.process.stdin.flush()
        event = self._wait_event("completed", 30)
        if event.get("disposition") != "vmm-sigkill":
            raise DemoError(f"{self.label} did not confirm VMM SIGKILL")
        self._wait_exit()

    def wait_success(self) -> None:
        event = self._wait_event("completed", 120)
        if event.get("disposition") != "completed":
            raise DemoError(f"{self.label} did not complete")
        self._wait_exit()

    def wait_denied(self) -> dict[str, Any]:
        event = self._wait_event("launch-denied", 60)
        if (
            event.get("generation") != self.generation
            or event.get("decision") != "impossible"
            or event.get("instance_started") is not False
        ):
            raise DemoError(f"{self.label} did not confirm denied launch")
        self._wait_exit()
        return event

    def _wait_event(self, wanted: str, timeout: float) -> dict[str, Any]:
        assert self.process.stdout is not None
        selector = selectors.DefaultSelector()
        selector.register(self.process.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + timeout
        try:
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    self._drain_stdout()
                    raise DemoError(
                        f"{self.label} exited before {wanted}: "
                        + self.stderr_path.read_text(encoding="utf-8", errors="replace")[-4096:]
                    )
                ready = selector.select(min(0.1, deadline - time.monotonic()))
                if not ready:
                    continue
                raw = self.process.stdout.readline()
                if not raw:
                    continue
                self._stdout_record.write(raw)
                self._stdout_record.flush()
                try:
                    event = json.loads(raw)
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise DemoError(f"{self.label} emitted non-JSON control output") from error
                if not isinstance(event, dict) or not isinstance(event.get("event"), str):
                    raise DemoError(f"{self.label} emitted a malformed control event")
                self.events.append(event)
                if event["event"] == wanted:
                    return event
            raise DemoError(f"{self.label} timed out waiting for {wanted}")
        finally:
            selector.close()

    def _drain_stdout(self) -> None:
        if self.process.stdout is None:
            return
        raw = self.process.stdout.read()
        if raw:
            self._stdout_record.write(raw)
            self._stdout_record.flush()

    def _wait_exit(self) -> None:
        try:
            self.exit_code = self.process.wait(timeout=10)
        except subprocess.TimeoutExpired as error:
            os.killpg(self.process.pid, signal.SIGKILL)
            self.process.wait(timeout=10)
            raise DemoError(f"{self.label} runner did not exit") from error
        self.stopped_time_ns = time.time_ns()
        self._drain_stdout()
        self._close_logs()
        if self.exit_code != 0:
            raise DemoError(f"{self.label} runner exited with {self.exit_code}")

    def result(self) -> dict[str, Any]:
        try:
            value = json.loads((self.evidence / "result.json").read_bytes())
        except (OSError, json.JSONDecodeError) as error:
            raise DemoError(f"{self.label} has no valid cell result") from error
        if not isinstance(value, dict) or value.get("valid") is not True:
            raise DemoError(f"{self.label} cell result is invalid")
        return value

    def close(self) -> None:
        if self.process.poll() is None:
            os.killpg(self.process.pid, signal.SIGTERM)
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait(timeout=5)
        self._drain_stdout()
        self._close_logs()

    def _close_logs(self) -> None:
        if not self._stdout_record.closed:
            self._stdout_record.close()
        if not self._stderr.closed:
            self._stderr.close()

    def record(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "generation": self.generation,
            "runner_pid": self.process.pid,
            "command": self.command,
            "started_time_ns": self.started_time_ns,
            "stopped_time_ns": self.stopped_time_ns,
            "exit_code": self.exit_code,
            "runner": self.runner,
            "events": self.events,
            "evidence": os.fspath(self.evidence),
            "result": self.result(),
        }


def _load_payload_result(
    path: Path, payload: Path, claude_sha256: str, relay_binary: Path
) -> dict[str, Any]:
    try:
        value = json.loads(path.read_bytes())
        built = value["payload"]
        inputs = value["inputs"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise DemoError("Claude payload result is malformed") from error
    if (
        value.get("schema") != 1
        or built.get("image_path") != os.fspath(payload)
        or built.get("image_sha256") != _sha256_file(payload)
        or inputs.get("claude", {}).get("sha256") != claude_sha256
        or inputs.get("mcp_operation_relay", {}).get("sha256")
        != _sha256_file(relay_binary)
    ):
        raise DemoError("Claude payload result does not bind the selected artifacts")
    return value


def run(
    *,
    cell_binary: Path,
    guest_binary: Path,
    payload: Path,
    payload_result: Path,
    claude_binary: Path,
    claude_sha256: str,
    claude_lock: Path,
    evidence_dir: Path | None,
    control_binary: Path,
    payment_binary: Path,
    mcp_host_binary: Path,
    mcp_relay_binary: Path,
    tools_config: Path,
) -> dict[str, Any]:
    release = _load_claude_lock(claude_lock, claude_binary, claude_sha256)
    payload_record = _load_payload_result(
        payload_result, payload, claude_sha256, mcp_relay_binary
    )
    payload_sha256 = payload_record["payload"]["image_sha256"]
    relay_sha256 = payload_record["inputs"]["mcp_operation_relay"]["sha256"]
    root = _private_directory(evidence_dir)
    if len(os.fsencode(root / "source" / "vsock_7002")) >= 108:
        raise DemoError("evidence path is too long for Firecracker Unix sockets")
    source_evidence = root / "source"
    replacement_evidence = root / "replacement"
    transport_root = Path(tempfile.mkdtemp(prefix="fc-claude-", dir="/tmp"))
    os.chmod(transport_root, 0o700)
    sockets = transport_root / "sockets"
    relay_directory = transport_root / "relay"
    for directory in (sockets, relay_directory):
        directory.mkdir(mode=0o700)

    control_port = _reserve_loopback_port()
    payment_port = _reserve_loopback_port()
    control_origin = f"http://127.0.0.1:{control_port}"
    payment_origin = f"http://127.0.0.1:{payment_port}"
    admin_token_path = root / "admin.token"
    history_path = root / "control.history"
    payment_history_path = root / "payment.history"
    journal_path = root / "mcp-calls.jsonl"
    relay_socket_path = relay_directory / "mcp-host.sock"
    sandbox_socket_path = _sandbox_socket(sockets)

    services: list[_Process] = []
    cells: list[_ClaudeCell] = []
    try:
        payment = _Process(
            "payment",
            [
                os.fspath(payment_binary),
                "-listen",
                f"127.0.0.1:{payment_port}",
                "-state",
                os.fspath(payment_history_path),
                "-hold-after-commit",
                "-non-idempotent",
                "-reference-prefix",
                "firecracker-claude",
            ],
            root,
        )
        services.append(payment)
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
        services.append(control)
        _wait_healthy(control_origin, control)
        token = _read_token(admin_token_path)
        certificate = _http_json(
            "POST",
            control_origin + "/v1/compile",
            value=_requirement(payment_origin),
            token=token,
        )
        binding = {
            "sandbox_id": _SANDBOX_ID,
            "generation": 1,
            "host_instance_id": "host-" + secrets.token_hex(16),
            "domain": _DOMAIN,
            "allowed_kinds": ["protected_commit"],
        }
        cutover = _http_json(
            "POST",
            control_origin + "/v1/cutover",
            value={"certificate": certificate, "bindings": [binding]},
            token=token,
        )
        if cutover.get("bindings") != [binding] or not sandbox_socket_path.is_socket():
            raise DemoError("Control did not activate the Claude sandbox binding")

        mcp_host = _Process(
            "mcp-host",
            [
                os.fspath(mcp_host_binary),
                "-config",
                os.fspath(tools_config),
                "-sandbox-socket",
                os.fspath(sandbox_socket_path),
                "-listen-socket",
                os.fspath(relay_socket_path),
                "-execution-id",
                _EXECUTION_ID,
                "-journal",
                os.fspath(journal_path),
            ],
            root,
        )
        services.append(mcp_host)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not relay_socket_path.is_socket():
            if mcp_host.process.poll() is not None:
                raise DemoError("MCP host exited before publishing its socket")
            time.sleep(0.05)
        if not relay_socket_path.is_socket():
            raise DemoError("MCP host did not publish its socket")

        with DeterministicAnthropicServer(
            _EFFECTS, response_delay_seconds=0.05
        ) as model:
            model_target = model.base_url.removeprefix("http://")
            source = _ClaudeCell(
                label="source-cell",
                generation=1,
                cell_binary=cell_binary,
                guest_binary=guest_binary,
                payload=payload,
                payload_sha256=payload_sha256,
                claude_sha256=claude_sha256,
                relay_sha256=relay_sha256,
                model_target=model_target,
                mcp_host_socket=relay_socket_path,
                evidence=source_evidence,
                root=root,
            )
            cells.append(source)
            source.wait_ready()
            inflight = _wait_held_commit(
                payment_origin,
                payment_history_path,
                journal_path,
                payment,
                mcp_host,
            )
            source.kill_vmm()
            source_result = source.result()
            inflight["source_vmm_sigkill_time_ns"] = source_result["process"][
                "stopped_time_ns"
            ]
            inflight["provider_release_time_ns"] = time.time_ns()
            payment.process.send_signal(signal.SIGUSR1)
            inflight["journal_completed_time_ns"] = _wait_journal_completion(
                journal_path, mcp_host
            )

            replacement = _ClaudeCell(
                label="replacement-cell",
                generation=2,
                cell_binary=cell_binary,
                guest_binary=guest_binary,
                payload=payload,
                payload_sha256=payload_sha256,
                claude_sha256=claude_sha256,
                relay_sha256=relay_sha256,
                model_target=model_target,
                mcp_host_socket=relay_socket_path,
                evidence=replacement_evidence,
                root=root,
            )
            cells.append(replacement)
            replacement.wait_ready()
            replacement.wait_success()
            replacement_result = replacement.result()
            model_requests = [asdict(request) for request in model.requests]
            _write_private_json(root / "anthropic-requests.json", model_requests)
            if model.failure is not None or len(model_requests) != 4:
                raise DemoError(
                    f"Claude model protocol failed or made {len(model_requests)} requests"
                )

        state = _http_json("GET", control_origin + "/v1/state", token=token)
        stats = _http_json("GET", payment_origin + "/v1/stats")
        operations = state.get("operations")
        if not isinstance(operations, dict) or len(operations) != 2:
            raise DemoError("History does not contain exactly two Claude Operations")
        by_effect: dict[str, dict[str, Any]] = {}
        for operation in operations.values():
            if not isinstance(operation, dict):
                raise DemoError("History contains a malformed Claude Operation")
            effect = _decode_operation_body(operation).get("effect_id")
            if not isinstance(effect, str) or effect in by_effect:
                raise DemoError("History contains ambiguous Claude effects")
            by_effect[effect] = operation
        if (
            set(by_effect) != set(_EFFECTS)
            or any(operation.get("phase") != "succeeded" for operation in by_effect.values())
            or stats.get("deliveries") != 2
            or stats.get("commits") != 2
        ):
            raise DemoError("Firecracker Claude continuity invariant failed")
        journal = _json_lines(journal_path, "final MCP journal")
        if [record.get("event") for record in journal] != [
            "prepared",
            "completed",
            "prepared",
            "completed",
        ]:
            raise DemoError("Claude MCP journal has a different lifecycle")
        relay_events = _json_lines(root / "mcp-host.stderr.log", "MCP host log")
        if [event.get("event") for event in relay_events] != [
            "relay_accept",
            "relay_disconnect",
            "relay_accept",
            "relay_disconnect",
        ]:
            raise DemoError("MCP host did not observe exactly two VM relay lifetimes")
        if (
            source_result.get("disposition") != "vmm-sigkill"
            or source_result.get("process", {}).get("termination") != "supervisor"
            or source_result.get("guest_result") is not None
            or replacement_result.get("disposition") != "completed"
            or replacement_result.get("guest_result", {}).get("body", {}).get("result")
            != "DONE"
            or tuple(
                source_result.get("process", {}).get(field)
                for field in ("pid", "start_time_ticks", "instance_id")
            )
            == tuple(
                replacement_result.get("process", {}).get(field)
                for field in ("pid", "start_time_ticks", "instance_id")
            )
        ):
            raise DemoError("cell lifecycle evidence does not prove clean VM replacement")

        result = {
            "schema": 1,
            "valid": True,
            "system": "official-claude-firecracker-vmm-loss-continuity",
            "claude_version": release["version"],
            "claude_release": release,
            "execution_id": _EXECUTION_ID,
            "cells": [cell.record() for cell in cells],
            "inflight": inflight,
            "provider_deliveries": stats["deliveries"],
            "provider_commits": stats["commits"],
            "operations": sorted(operation["id"] for operation in by_effect.values()),
            "mcp_relay_lifetimes": 2,
            "model_requests": len(model_requests),
            "network_interfaces_per_cell": 0,
            "root_block_devices_per_cell": 0,
            "artifacts": {
                "cell": {"path": os.fspath(cell_binary), "sha256": _sha256_file(cell_binary)},
                "guest": {"path": os.fspath(guest_binary), "sha256": _sha256_file(guest_binary)},
                "payload": {"path": os.fspath(payload), "sha256": payload_sha256},
                "payload_result": {"path": os.fspath(payload_result), "sha256": _sha256_file(payload_result)},
                "claude": {"path": os.fspath(claude_binary), "sha256": claude_sha256},
                "claude_lock": {"path": os.fspath(claude_lock), "sha256": release["sha256"]},
                "control": {"path": os.fspath(control_binary), "sha256": _sha256_file(control_binary)},
                "payment": {"path": os.fspath(payment_binary), "sha256": _sha256_file(payment_binary)},
                "mcp_host": {"path": os.fspath(mcp_host_binary), "sha256": _sha256_file(mcp_host_binary)},
                "mcp_relay": {"path": os.fspath(mcp_relay_binary), "sha256": relay_sha256},
                "tools_config": {"path": os.fspath(tools_config), "sha256": _sha256_file(tools_config)},
                "history": {"path": os.fspath(history_path), "sha256": _sha256_file(history_path)},
                "journal": {"path": os.fspath(journal_path), "sha256": _sha256_file(journal_path)},
                "payment_history": {"path": os.fspath(payment_history_path), "sha256": _sha256_file(payment_history_path)},
                "anthropic_requests": {"path": os.fspath(root / "anthropic-requests.json"), "sha256": _sha256_file(root / "anthropic-requests.json")},
            },
        }
        _write_private_json(root / "result.json", result)
        return {"evidence": os.fspath(root), **result}
    finally:
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
            admin_token_path.unlink(missing_ok=True)
        except OSError as error:
            failures.append(error)
        transport_lock = sockets / ".safe-change.lock"
        try:
            lock_info = transport_lock.lstat()
            if (
                not stat.S_ISREG(lock_info.st_mode)
                or lock_info.st_uid != os.geteuid()
                or stat.S_IMODE(lock_info.st_mode) != 0o600
                or lock_info.st_size != 0
            ):
                raise DemoError("ephemeral sandbox lock has an unsafe identity")
            transport_lock.unlink()
        except OSError as error:
            failures.append(error)
        for directory in (relay_directory, sockets, transport_root):
            try:
                directory.rmdir()
            except OSError as error:
                failures.append(error)
        if failures:
            raise DemoError("Firecracker Claude cleanup failed: " + "; ".join(map(str, failures)))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cell-binary", required=True, type=Path)
    parser.add_argument("--guest-binary", required=True, type=Path)
    parser.add_argument("--payload", required=True, type=Path)
    parser.add_argument("--payload-result", required=True, type=Path)
    parser.add_argument("--claude-binary", required=True, type=Path)
    parser.add_argument("--claude-sha256", required=True)
    parser.add_argument("--claude-lock", required=True, type=Path)
    parser.add_argument("--evidence-dir", type=Path)
    parser.add_argument("--control-binary", required=True, type=Path)
    parser.add_argument("--payment-binary", required=True, type=Path)
    parser.add_argument("--mcp-host-binary", required=True, type=Path)
    parser.add_argument("--mcp-relay-binary", required=True, type=Path)
    parser.add_argument("--tools-config", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = run(
            cell_binary=_owned_executable(args.cell_binary.resolve(), "Claude cell"),
            guest_binary=_owned_executable(args.guest_binary.resolve(), "Claude guest"),
            payload=args.payload.resolve(strict=True),
            payload_result=args.payload_result.resolve(strict=True),
            claude_binary=_owned_executable(args.claude_binary.resolve(), "Claude Code"),
            claude_sha256=args.claude_sha256,
            claude_lock=args.claude_lock.resolve(strict=True),
            evidence_dir=args.evidence_dir,
            control_binary=_owned_executable(args.control_binary.resolve(), "Control"),
            payment_binary=_owned_executable(args.payment_binary.resolve(), "payment"),
            mcp_host_binary=_owned_executable(args.mcp_host_binary.resolve(), "MCP host"),
            mcp_relay_binary=_owned_executable(args.mcp_relay_binary.resolve(), "MCP relay"),
            tools_config=args.tools_config.resolve(strict=True),
        )
    except (DemoError, OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
