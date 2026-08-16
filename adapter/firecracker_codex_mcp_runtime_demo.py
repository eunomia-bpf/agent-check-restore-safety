"""Run real Codex MCP Operations across a Firecracker snapshot replacement.

The trusted MCP host, its durable journal, Control/History, and the external
provider remain outside the microVM restore domain.  One native Codex process
completes an MCP Operation before the checkpoint and another after a different
Firecracker VMM resumes the full-machine snapshot.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import stat
import sys
import time
from typing import Any, Sequence

from adapter.codex_mcp_runtime_demo import (
    _EXECUTION_ID,
    _SANDBOX_ID,
    DemoError,
    _Process,
    _decode_operation_body,
    _http_json,
    _owned_executable,
    _private_directory,
    _read_token,
    _requirement,
    _reserve_loopback_port,
    _sandbox_socket,
    _sha256_file,
    _wait_healthy,
    _write_private_json,
)
from adapter.firecracker_codex_runtime_demo import run_demo


def _artifact(path: Path) -> dict[str, Any]:
    info = path.lstat()
    return {
        "path": os.fspath(path),
        "sha256": _sha256_file(path),
        "size": info.st_size,
        "mode": stat.S_IMODE(info.st_mode),
    }


def _trusted_config(path: Path) -> Path:
    resolved = path.resolve(strict=True)
    info = path.lstat()
    if (
        not path.is_absolute()
        or path != resolved
        or not stat.S_ISREG(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) & 0o022
    ):
        raise DemoError("tools config must be a current-user trusted regular file")
    return path


def _wait_mcp_lifetimes(path: Path, process: _Process, expected: int) -> list[dict[str, Any]]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.process.poll() is not None:
            raise DemoError("trusted MCP host exited before relay shutdown")
        try:
            records = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line
            ]
        except (OSError, json.JSONDecodeError):
            time.sleep(0.05)
            continue
        events = [record.get("event") for record in records]
        if (
            len(records) == expected * 2
            and events.count("relay_accept") == expected
            and events.count("relay_disconnect") == expected
            and all(
                isinstance(record.get("pid"), int)
                and isinstance(record.get("uid"), int)
                for record in records
            )
        ):
            return records
        time.sleep(0.05)
    raise DemoError("trusted MCP host did not retain every relay lifetime")


def run(
    *,
    evidence_dir: Path,
    runner: Path,
    runner_sha256: str,
    firecracker: Path,
    firecracker_sha256: str,
    kernel: Path,
    kernel_sha256: str,
    guest: Path,
    guest_sha256: str,
    payload: Path,
    payload_sha256: str,
    repository: Path,
    repository_sha256: str,
    codex_sha256: str,
    mcp_relay: Path,
    mcp_relay_sha256: str,
    control_binary: Path,
    payment_binary: Path,
    mcp_host_binary: Path,
    tools_config: Path,
) -> dict[str, Any]:
    control_binary = _owned_executable(control_binary, "Control binary")
    payment_binary = _owned_executable(payment_binary, "payment binary")
    mcp_host_binary = _owned_executable(mcp_host_binary, "MCP host binary")
    mcp_relay = _owned_executable(mcp_relay, "MCP relay binary")
    tools_config = _trusted_config(tools_config)
    trusted_artifacts = {
        "control": _artifact(control_binary),
        "payment": _artifact(payment_binary),
        "mcp_host": _artifact(mcp_host_binary),
        "mcp_relay": _artifact(mcp_relay),
        "tools_config": _artifact(tools_config),
    }
    if trusted_artifacts["mcp_relay"]["sha256"] != mcp_relay_sha256:
        raise DemoError("MCP relay digest differs from its required identity")

    root = _private_directory(evidence_dir)
    runtime = root / "runtime"
    adapter = root / "adapter"
    workspace = root / "workspace"
    sockets = root / "sockets"
    for directory in (runtime, adapter, workspace, sockets):
        directory.mkdir(mode=0o700)

    control_port = _reserve_loopback_port()
    payment_port = _reserve_loopback_port()
    control_origin = f"http://127.0.0.1:{control_port}"
    payment_origin = f"http://127.0.0.1:{payment_port}"
    admin_token_path = root / "admin.token"
    history_path = root / "control.history"
    payment_history_path = root / "payment.history"
    journal_path = root / "mcp-calls.jsonl"
    relay_directory = root / "relay"
    relay_directory.mkdir(mode=0o700)
    relay_socket_path = relay_directory / "mcp-host.sock"
    sandbox_socket_path = _sandbox_socket(sockets)

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
                "firecracker-mcp",
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
            raise DemoError("Control refused the Firecracker MCP requirement")
        binding = {
            "sandbox_id": _SANDBOX_ID,
            "generation": 1,
            "host_instance_id": "host-" + secrets.token_hex(16),
            "domain": "firecracker-codex-mcp-runtime",
            "allowed_kinds": ["protected_commit"],
        }
        cutover = _http_json(
            "POST",
            control_origin + "/v1/cutover",
            value={"certificate": certificate, "bindings": [binding]},
            token=token,
        )
        if cutover.get("bindings") != [binding] or not sandbox_socket_path.is_socket():
            raise DemoError("Control did not publish the Firecracker MCP endpoint")

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
        processes.append(mcp_host)
        _write_private_json(
            root / "mcp-host-process.json",
            {"pid": mcp_host.process.pid, "command": mcp_host.command},
        )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not relay_socket_path.is_socket():
            if mcp_host.process.poll() is not None:
                raise DemoError("trusted MCP host exited before publishing its socket")
            time.sleep(0.05)
        if not relay_socket_path.is_socket():
            raise DemoError("trusted MCP host did not publish its socket")

        firecracker_result = run_demo(
            runner=runner,
            runner_sha256=runner_sha256,
            firecracker=firecracker,
            firecracker_sha256=firecracker_sha256,
            kernel=kernel,
            kernel_sha256=kernel_sha256,
            guest=guest,
            guest_sha256=guest_sha256,
            payload=payload,
            payload_sha256=payload_sha256,
            repository=repository,
            repository_sha256=repository_sha256,
            codex_sha256=codex_sha256,
            runtime_evidence=runtime,
            adapter_evidence=adapter,
            workspace=workspace,
            protected_effect_ids=("preflight-effect-1",),
            mcp_relay=mcp_relay,
            mcp_relay_sha256=mcp_relay_sha256,
            mcp_host_socket=relay_socket_path,
            mcp_effect_ids=("effect-A", "effect-B"),
        )

        relay_events = _wait_mcp_lifetimes(
            root / "mcp-host.stderr.log", mcp_host, expected=3
        )
        state = _http_json("GET", control_origin + "/v1/state", token=token)
        stats = _http_json("GET", payment_origin + "/v1/stats")
        operations = state.get("operations")
        if not isinstance(operations, dict) or len(operations) != 2:
            raise DemoError("History did not retain exactly two Firecracker MCP Operations")
        by_effect: dict[str, dict[str, Any]] = {}
        for operation in operations.values():
            if not isinstance(operation, dict):
                raise DemoError("History contains a malformed Operation")
            body = _decode_operation_body(operation)
            effect = body.get("effect_id")
            if not isinstance(effect, str) or effect in by_effect:
                raise DemoError("History contains ambiguous MCP effect identities")
            by_effect[effect] = operation
        if (
            set(by_effect) != {"effect-A", "effect-B"}
            or by_effect["effect-A"].get("phase") != "succeeded"
            or by_effect["effect-A"].get("settlement") != "query"
            or by_effect["effect-B"].get("phase") != "succeeded"
            or stats.get("deliveries") != 2
            or stats.get("commits") != 2
        ):
            raise DemoError(
                f"Firecracker MCP invariant failed: effects={by_effect!r} stats={stats!r}"
            )
        result = {
            "schema": 1,
            "valid": True,
            "firecracker_result": firecracker_result["result_path"],
            "runtime_evidence": os.fspath(runtime),
            "adapter_evidence": os.fspath(adapter),
            "history": os.fspath(history_path),
            "journal": os.fspath(journal_path),
            "payment_history": os.fspath(payment_history_path),
            "operations": sorted(operation["id"] for operation in by_effect.values()),
            "provider_deliveries": stats["deliveries"],
            "provider_commits": stats["commits"],
            "mcp_relay_lifetimes": len(relay_events) // 2,
            "artifacts": trusted_artifacts,
        }
        _write_private_json(root / "result.json", result)
        return result
    finally:
        failures: list[BaseException] = []
        for process in reversed(processes):
            try:
                process.close()
            except BaseException as error:
                failures.append(error)
        if failures and sys.exc_info()[0] is None:
            raise DemoError("process cleanup failed: " + "; ".join(map(str, failures)))


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run real Codex MCP Operations across a real Firecracker restore."
    )
    for name in ("runner", "firecracker", "kernel", "guest", "payload", "repository", "mcp-relay"):
        parser.add_argument(f"--{name}", required=True, type=Path)
        parser.add_argument(f"--{name}-sha256", required=True)
    parser.add_argument("--codex-sha256", required=True)
    parser.add_argument("--control-binary", required=True, type=Path)
    parser.add_argument("--payment-binary", required=True, type=Path)
    parser.add_argument("--mcp-host-binary", required=True, type=Path)
    parser.add_argument("--tools-config", required=True, type=Path)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        result = run(
            evidence_dir=args.evidence_dir,
            runner=args.runner,
            runner_sha256=args.runner_sha256,
            firecracker=args.firecracker,
            firecracker_sha256=args.firecracker_sha256,
            kernel=args.kernel,
            kernel_sha256=args.kernel_sha256,
            guest=args.guest,
            guest_sha256=args.guest_sha256,
            payload=args.payload,
            payload_sha256=args.payload_sha256,
            repository=args.repository,
            repository_sha256=args.repository_sha256,
            codex_sha256=args.codex_sha256,
            mcp_relay=args.mcp_relay,
            mcp_relay_sha256=args.mcp_relay_sha256,
            control_binary=args.control_binary,
            payment_binary=args.payment_binary,
            mcp_host_binary=args.mcp_host_binary,
            tools_config=args.tools_config,
        )
    except Exception as error:
        print(f"Firecracker Codex MCP demo failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "run"]
