"""Run real Claude Code across process loss with host-durable MCP effects."""

from __future__ import annotations

import argparse
import base64
from dataclasses import asdict
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import signal
import stat
import subprocess
import tempfile
import time
from typing import Any, BinaryIO, Mapping, Sequence
import uuid

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


_SANDBOX_ID = "claude-mcp"
_DOMAIN = "claude-mcp-runtime"
_EXECUTION_ID = "claude-mcp-execution-v1"
_MCP_NAME = "continuity"
_TOOL_NAME = "commit_effect"
_EFFECTS = ("effect-A", "effect-B")


def _sandbox_socket(root: Path) -> Path:
    name = "sandbox-" + sha256(_SANDBOX_ID.encode("utf-8")).hexdigest()[:32]
    return root / (name + ".sock")


def _requirement(payment_origin: str) -> dict[str, Any]:
    return {
        "id": "real-claude-mcp-process-loss",
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


class _ClaudeProcess:
    def __init__(
        self,
        *,
        label: str,
        binary: Path,
        command: Sequence[str],
        environment: Mapping[str, str],
        workspace: Path,
        root: Path,
    ) -> None:
        self.label = label
        self.command = [os.fspath(binary), *command]
        self.stdout_path = root / f"{label}.stream.jsonl"
        self.stderr_path = root / f"{label}.stderr.log"
        self._stdout: BinaryIO = self.stdout_path.open("xb")
        self._stderr: BinaryIO = self.stderr_path.open("xb")
        os.chmod(self.stdout_path, 0o600)
        os.chmod(self.stderr_path, 0o600)
        self.started_time_ns = time.time_ns()
        self.process = subprocess.Popen(
            self.command,
            stdin=subprocess.DEVNULL,
            stdout=self._stdout,
            stderr=self._stderr,
            cwd=workspace,
            env=dict(environment),
            start_new_session=True,
        )
        self.pid = self.process.pid
        self.identity = _process_identity(self.pid, label)
        if self.identity["command"] != self.command:
            self.close()
            raise DemoError(f"{label} live command differs from the launch command")
        self.stopped_time_ns = 0
        self.disposition = ""
        self.exit_code: int | None = None

    def kill_for_replacement(self) -> None:
        if self.process.poll() is not None:
            raise DemoError(f"{self.label} exited before process replacement")
        os.killpg(self.pid, signal.SIGKILL)
        code = self.process.wait(timeout=10)
        self.exit_code = code
        self.stopped_time_ns = time.time_ns()
        self.disposition = "supervisor-sigkill"
        if code != -signal.SIGKILL:
            raise DemoError(f"{self.label} replacement exit is {code}, require SIGKILL")
        self._close_logs()

    def wait_success(self) -> None:
        try:
            code = self.process.wait(timeout=90)
        except subprocess.TimeoutExpired as error:
            os.killpg(self.pid, signal.SIGKILL)
            self.process.wait(timeout=10)
            raise DemoError(f"{self.label} did not finish") from error
        self.stopped_time_ns = time.time_ns()
        self.exit_code = code
        self.disposition = "completed"
        self._close_logs()
        if code != 0:
            diagnostic = self.stderr_path.read_text(
                encoding="utf-8", errors="replace"
            )[-4096:]
            raise DemoError(f"{self.label} exited with {code}: {diagnostic}")

    def close(self) -> None:
        if self.process.poll() is None:
            os.killpg(self.pid, signal.SIGTERM)
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(self.pid, signal.SIGKILL)
                self.process.wait(timeout=5)
        self._close_logs()

    def record(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "pid": self.pid,
            "command": self.command,
            "started_time_ns": self.started_time_ns,
            "stopped_time_ns": self.stopped_time_ns,
            "disposition": self.disposition,
            "exit_code": self.exit_code,
            "identity": self.identity,
            "stdout": os.fspath(self.stdout_path),
            "stderr": os.fspath(self.stderr_path),
        }

    def _close_logs(self) -> None:
        if not self._stdout.closed:
            self._stdout.close()
        if not self._stderr.closed:
            self._stderr.close()


def _process_identity(pid: int, label: str) -> dict[str, Any]:
    proc = Path("/proc") / str(pid)
    try:
        stat_line = (proc / "stat").read_text(encoding="utf-8")
        close = stat_line.rfind(")")
        fields = stat_line[close + 2 :].split()
        if close < 1 or len(fields) < 4:
            raise ValueError("short process stat")
        status = (proc / "status").read_text(encoding="utf-8").splitlines()
        status_fields = {
            line.split(":", 1)[0]: line.split(":", 1)[1].strip()
            for line in status
            if ":" in line
        }
        uid = int(status_fields["Uid"].split()[0])
        gid = int(status_fields["Gid"].split()[0])
        command = [
            part.decode("utf-8")
            for part in (proc / "cmdline").read_bytes().split(b"\x00")
            if part
        ]
        executable_target = os.readlink(proc / "exe")
        descriptor = os.open(proc / "exe", os.O_RDONLY)
        try:
            executable_info = os.fstat(descriptor)
            digest = sha256()
            while block := os.read(descriptor, 1 << 20):
                digest.update(block)
        finally:
            os.close(descriptor)
    except (OSError, KeyError, UnicodeDecodeError, ValueError) as error:
        raise DemoError(f"cannot bind {label} to its live Linux process") from error
    return {
        "pid": pid,
        "parent_pid": int(fields[1]),
        "process_group": int(fields[2]),
        "session": int(fields[3]),
        "uid": uid,
        "gid": gid,
        "command": command,
        "executable_target": executable_target,
        "executable_device": executable_info.st_dev,
        "executable_inode": executable_info.st_ino,
        "executable_size": executable_info.st_size,
        "executable_sha256": digest.hexdigest(),
    }


def _wait_relay_peer(
    path: Path,
    ordinal: int,
    agent: _ClaudeProcess,
    relay_binary: Path,
    relay_socket: Path,
) -> dict[str, Any]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if agent.process.poll() is not None:
            raise DemoError(f"{agent.label} exited before its MCP relay was inspected")
        try:
            records = _json_lines(path, "MCP host log")
        except DemoError:
            time.sleep(0.005)
            continue
        accepts = [record for record in records if record.get("event") == "relay_accept"]
        if len(accepts) < ordinal:
            time.sleep(0.005)
            continue
        peer_pid = accepts[ordinal - 1].get("pid")
        if not isinstance(peer_pid, int) or peer_pid <= 1:
            raise DemoError("MCP host logged an invalid relay peer")
        identity = _process_identity(peer_pid, f"{agent.label} MCP relay")
        expected_command = [
            os.fspath(relay_binary),
            "-socket",
            os.fspath(relay_socket),
        ]
        if (
            identity["uid"] != os.geteuid()
            or identity["process_group"] != agent.pid
            or identity["session"] != agent.pid
            or identity["executable_sha256"] != _sha256_file(relay_binary)
            or Path(identity["executable_target"]).resolve() != relay_binary
            or identity["command"] != expected_command
        ):
            raise DemoError("Claude MCP relay is outside the replaced process group")
        return identity
    raise DemoError(f"{agent.label} did not connect an inspectable MCP relay")


def _claude_environment(base_url: str, config_directory: Path) -> dict[str, str]:
    environment = {
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "SHELL": "/bin/bash",
        "ANTHROPIC_BASE_URL": base_url,
        "ANTHROPIC_API_KEY": "fixture-credential",
        "ANTHROPIC_MODEL": "claude-fixture-1",
        "CLAUDE_CONFIG_DIR": os.fspath(config_directory),
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "CLAUDE_CODE_SKIP_PROMPT_HISTORY": "1",
        "DISABLE_AUTOUPDATER": "1",
        "DISABLE_TELEMETRY": "1",
        "NO_PROXY": "127.0.0.1,localhost",
        "no_proxy": "127.0.0.1,localhost",
    }
    return environment


def _claude_arguments(mcp_config: Path) -> tuple[str, ...]:
    return (
        "--bare",
        "--print",
        "Commit effect-A and then effect-B with the continuity MCP tool. Finish with DONE.",
        "--output-format",
        "stream-json",
        "--verbose",
        "--no-session-persistence",
        "--strict-mcp-config",
        "--mcp-config",
        os.fspath(mcp_config),
        "--allowedTools",
        "mcp__continuity__commit_effect",
        "--permission-mode",
        "dontAsk",
        "--model",
        "claude-fixture-1",
        "--max-turns",
        "4",
        "--no-chrome",
        "--disable-slash-commands",
        "--prompt-suggestions",
        "false",
        "--session-id",
        str(uuid.uuid4()),
    )


def _load_claude_lock(path: Path, binary: Path, expected_sha256: str) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
        release = value["claude_code"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise DemoError("Claude release lock is malformed") from error
    expected_keys = {
        "version",
        "platform",
        "repository_url",
        "signing_key_url",
        "signing_key_fingerprint",
        "signing_key_size",
        "signing_key_sha256",
        "manifest_url",
        "manifest_size",
        "manifest_sha256",
        "manifest_signature_url",
        "manifest_signature_size",
        "manifest_signature_sha256",
        "binary_url",
        "binary_size",
        "binary_sha256",
        "version_output",
    }
    if (
        not isinstance(value, dict)
        or value.get("schema") != 1
        or not isinstance(release, dict)
        or set(release) != expected_keys
        or release.get("platform") != "linux-x64"
        or release.get("binary_sha256") != expected_sha256
        or release.get("binary_size") != binary.stat().st_size
        or release.get("version") != "2.1.233"
        or release.get("version_output") != "2.1.233 (Claude Code)"
        or release.get("signing_key_fingerprint")
        != "31DDDE24DDFAB679F42D7BD2BAA929FF1A7ECACE"
    ):
        raise DemoError("Claude release lock does not describe the pinned binary")
    version = subprocess.run(
        [os.fspath(binary), "--version"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=10,
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
    )
    try:
        observed = version.stdout.decode("utf-8").strip()
    except UnicodeDecodeError as error:
        raise DemoError("Claude version output is not UTF-8") from error
    if version.returncode != 0 or observed != release["version_output"]:
        raise DemoError("Claude executable version differs from its signed lock")
    return {
        "path": os.fspath(path),
        "sha256": sha256(raw).hexdigest(),
        "version": release["version"],
        "platform": release["platform"],
        "signing_key_fingerprint": release["signing_key_fingerprint"],
        "version_output": observed,
    }


def _private_tree_manifest(path: Path) -> list[dict[str, Any]]:
    manifest: list[dict[str, Any]] = []
    for item in sorted(path.rglob("*")):
        info = item.lstat()
        relative = item.relative_to(path).as_posix()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != os.geteuid():
            raise DemoError("Claude config tree contains an unsafe entry")
        if stat.S_ISDIR(info.st_mode):
            if stat.S_IMODE(info.st_mode) != 0o700:
                raise DemoError("Claude config directory is not private")
            manifest.append({"path": relative + "/", "mode": 0o700})
            continue
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_size > 1 << 20
        ):
            raise DemoError("Claude config file is not a bounded private file")
        manifest.append(
            {
                "path": relative,
                "mode": 0o600,
                "size": info.st_size,
                "sha256": _sha256_file(item),
            }
        )
    return manifest


def _json_lines(path: Path, label: str) -> list[dict[str, Any]]:
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise DemoError(f"cannot read {label}") from error
    if not raw or not raw.endswith(b"\n"):
        raise DemoError(f"{label} is empty or incomplete")
    records: list[dict[str, Any]] = []
    for line in raw.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise DemoError(f"{label} contains invalid JSON") from error
        if not isinstance(value, dict):
            raise DemoError(f"{label} contains a non-object")
        records.append(value)
    return records


def _wait_held_commit(
    payment_origin: str,
    payment_history: Path,
    journal: Path,
    payment: _Process,
    mcp_host: _Process,
) -> dict[str, Any]:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if payment.process.poll() is not None or mcp_host.process.poll() is not None:
            raise DemoError("provider or MCP host exited before the held commit")
        try:
            stats = _http_json("GET", payment_origin + "/v1/stats")
            payments = _json_lines(payment_history, "payment history")
            journal_records = _json_lines(journal, "MCP journal")
        except DemoError:
            time.sleep(0.05)
            continue
        if (
            stats.get("deliveries") == 1
            and stats.get("commits") == 1
            and len(payments) == 1
            and len(journal_records) == 1
            and journal_records[0].get("event") == "prepared"
        ):
            return {
                "provider_commit_observed_time_ns": time.time_ns(),
                "payment_record_sha256": _sha256_file(payment_history),
                "journal_prepared_sha256": _sha256_file(journal),
            }
        time.sleep(0.05)
    raise DemoError("Claude did not reach a provider-committed unresolved call")


def _wait_journal_completion(journal: Path, mcp_host: _Process) -> int:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if mcp_host.process.poll() is not None:
            raise DemoError("MCP host exited before journal completion")
        try:
            records = _json_lines(journal, "MCP journal")
        except DemoError:
            time.sleep(0.05)
            continue
        if (
            len(records) == 2
            and records[0].get("event") == "prepared"
            and records[1].get("event") == "completed"
        ):
            return time.time_ns()
        time.sleep(0.05)
    raise DemoError("MCP host did not complete A after Claude process loss")


def _decode_operation_body(operation: Mapping[str, Any]) -> dict[str, Any]:
    encoded = operation.get("request_body")
    if not isinstance(encoded, str):
        raise DemoError("Operation omits its retained request")
    try:
        value = json.loads(base64.b64decode(encoded, validate=True))
    except (ValueError, json.JSONDecodeError) as error:
        raise DemoError("Operation retains an invalid request") from error
    if not isinstance(value, dict):
        raise DemoError("Operation request is not an object")
    return value


def run(
    *,
    claude_binary: Path,
    claude_sha256: str,
    claude_lock: Path,
    workspace: Path,
    evidence_dir: Path | None,
    control_binary: Path,
    payment_binary: Path,
    mcp_host_binary: Path,
    mcp_relay_binary: Path,
    tools_config: Path,
) -> dict[str, Any]:
    if _sha256_file(claude_binary) != claude_sha256:
        raise DemoError("Claude binary differs from its pinned SHA-256")
    release = _load_claude_lock(claude_lock, claude_binary, claude_sha256)
    workspace = workspace.resolve()
    if not workspace.is_dir():
        raise DemoError("workspace must be an existing directory")
    root = _private_directory(evidence_dir)
    transport_root = Path(
        tempfile.mkdtemp(prefix="claude-mcp-transport-", dir="/tmp")
    )
    os.chmod(transport_root, 0o700)
    sockets = transport_root / "sockets"
    relay_directory = transport_root / "relay"
    config_first = root / "claude-config-first"
    config_second = root / "claude-config-second"
    for directory in (sockets, relay_directory, config_first, config_second):
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
    mcp_config_path = root / "mcp.json"
    _write_private_json(
        mcp_config_path,
        {
            "mcpServers": {
                _MCP_NAME: {
                    "type": "stdio",
                    "command": os.fspath(mcp_relay_binary),
                    "args": ["-socket", os.fspath(relay_socket_path)],
                    "env": {},
                }
            }
        },
    )

    services: list[_Process] = []
    agents: list[_ClaudeProcess] = []
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
                "claude-mcp",
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
            first = _ClaudeProcess(
                label="claude-first",
                binary=claude_binary,
                command=_claude_arguments(mcp_config_path),
                environment=_claude_environment(model.base_url, config_first),
                workspace=workspace,
                root=root,
            )
            agents.append(first)
            relay_peers = [
                _wait_relay_peer(
                    root / "mcp-host.stderr.log",
                    1,
                    first,
                    mcp_relay_binary,
                    relay_socket_path,
                )
            ]
            inflight = _wait_held_commit(
                payment_origin,
                payment_history_path,
                journal_path,
                payment,
                mcp_host,
            )
            first.kill_for_replacement()
            inflight["source_sigkill_time_ns"] = first.stopped_time_ns
            inflight["provider_release_time_ns"] = time.time_ns()
            payment.process.send_signal(signal.SIGUSR1)
            inflight["journal_completed_time_ns"] = _wait_journal_completion(
                journal_path, mcp_host
            )

            second = _ClaudeProcess(
                label="claude-second",
                binary=claude_binary,
                command=_claude_arguments(mcp_config_path),
                environment=_claude_environment(model.base_url, config_second),
                workspace=workspace,
                root=root,
            )
            agents.append(second)
            relay_peers.append(
                _wait_relay_peer(
                    root / "mcp-host.stderr.log",
                    2,
                    second,
                    mcp_relay_binary,
                    relay_socket_path,
                )
            )
            second.wait_success()
            model_requests = [asdict(request) for request in model.requests]
            _write_private_json(root / "anthropic-requests.json", model_requests)
            if model.failure is not None or len(model_requests) != 4:
                raise DemoError(
                    f"Claude model protocol failed or made {len(model_requests)} requests"
                )

        second_stream = _json_lines(second.stdout_path, "second Claude stream")
        final_results = [
            record
            for record in second_stream
            if record.get("type") == "result"
        ]
        if (
            len(final_results) != 1
            or final_results[0].get("subtype") != "success"
            or final_results[0].get("result") != "DONE"
        ):
            raise DemoError("replacement Claude did not complete with DONE")

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
            raise DemoError(f"Claude continuity invariant failed: {by_effect!r} {stats!r}")
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
            raise DemoError("MCP host did not observe exactly two Claude relay lifetimes")

        result = {
            "schema": 1,
            "valid": True,
            "system": "real-claude-mcp-process-continuity",
            "claude_version": release["version"],
            "claude_release": release,
            "execution_id": _EXECUTION_ID,
            "transport_root": os.fspath(transport_root),
            "transport_ephemeral": True,
            "processes": [agent.record() for agent in agents],
            "relay_peers": relay_peers,
            "services": {
                service.name: {
                    "pid": service.process.pid,
                    "command": service.command,
                }
                for service in services
            },
            "config_trees": {
                "first": _private_tree_manifest(config_first),
                "second": _private_tree_manifest(config_second),
            },
            "inflight": inflight,
            "provider_deliveries": stats["deliveries"],
            "provider_commits": stats["commits"],
            "operations": sorted(operation["id"] for operation in by_effect.values()),
            "mcp_relay_lifetimes": 2,
            "model_requests": len(model_requests),
            "artifacts": {
                "claude": {
                    "path": os.fspath(claude_binary),
                    "sha256": claude_sha256,
                    "size": claude_binary.stat().st_size,
                },
                "claude_lock": {
                    "path": os.fspath(claude_lock),
                    "sha256": release["sha256"],
                },
                "control": {
                    "path": os.fspath(control_binary),
                    "sha256": _sha256_file(control_binary),
                },
                "payment": {
                    "path": os.fspath(payment_binary),
                    "sha256": _sha256_file(payment_binary),
                },
                "mcp_host": {
                    "path": os.fspath(mcp_host_binary),
                    "sha256": _sha256_file(mcp_host_binary),
                },
                "mcp_relay": {
                    "path": os.fspath(mcp_relay_binary),
                    "sha256": _sha256_file(mcp_relay_binary),
                },
                "tools_config": {
                    "path": os.fspath(tools_config),
                    "sha256": _sha256_file(tools_config),
                },
                "history": {
                    "path": os.fspath(history_path),
                    "sha256": _sha256_file(history_path),
                },
                "journal": {
                    "path": os.fspath(journal_path),
                    "sha256": _sha256_file(journal_path),
                },
                "payment_history": {
                    "path": os.fspath(payment_history_path),
                    "sha256": _sha256_file(payment_history_path),
                },
                "anthropic_requests": {
                    "path": os.fspath(root / "anthropic-requests.json"),
                    "sha256": _sha256_file(root / "anthropic-requests.json"),
                },
            },
        }
        _write_private_json(root / "result.json", result)
        return {"evidence": os.fspath(root), **result}
    finally:
        failures: list[BaseException] = []
        for agent in reversed(agents):
            try:
                agent.close()
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
            raise DemoError("Claude demo cleanup failed: " + "; ".join(map(str, failures)))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--claude-binary", required=True, type=Path)
    parser.add_argument("--claude-sha256", required=True)
    parser.add_argument("--claude-lock", required=True, type=Path)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--evidence-dir", type=Path)
    parser.add_argument("--control-binary", required=True, type=Path)
    parser.add_argument("--payment-binary", required=True, type=Path)
    parser.add_argument("--mcp-host-binary", required=True, type=Path)
    parser.add_argument("--mcp-relay-binary", required=True, type=Path)
    parser.add_argument(
        "--tools-config",
        type=Path,
        default=Path("runtime/deploy/mcp-operation/tools.json"),
    )
    args = parser.parse_args()
    result = run(
        claude_binary=_owned_executable(
            args.claude_binary.resolve(), "Claude Code"
        ),
        claude_sha256=args.claude_sha256,
        claude_lock=args.claude_lock.resolve(),
        workspace=args.workspace,
        evidence_dir=args.evidence_dir,
        control_binary=_owned_executable(args.control_binary.resolve(), "Control"),
        payment_binary=_owned_executable(
            args.payment_binary.resolve(), "payment service"
        ),
        mcp_host_binary=_owned_executable(
            args.mcp_host_binary.resolve(), "trusted MCP host"
        ),
        mcp_relay_binary=_owned_executable(
            args.mcp_relay_binary.resolve(), "MCP relay"
        ),
        tools_config=args.tools_config.resolve(),
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
