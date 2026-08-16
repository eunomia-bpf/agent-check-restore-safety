"""Run the deterministic Codex preflight through one Firecracker restore.

This is an explicit real-KVM entry point.  It keeps the ordinary Codex
App Server boundary: :func:`adapter.test_app_server.run_preflight` sees only a
temporary ``codex`` executable, while that executable fixes the host-owned VM
artifacts and delegates to ``firecracker-codex-shim``.

Stdout is reserved for one compact, non-secret result locator.  The App Server
JSONL stream and all Firecracker evidence remain in caller-supplied private
directories.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any, Mapping, Sequence

from adapter.firecracker_codex import create_firecracker_codex
from adapter.test_app_server import PreflightResult, run_preflight


RESULT_SCHEMA = 1
_MAX_RUNTIME_RESULT_BYTES = 8 << 20
_CONTROL_CHARACTERS = frozenset(chr(value) for value in range(32)) | {chr(127)}


class DemoError(RuntimeError):
    """The opt-in Firecracker preflight failed a local contract check."""


def _digest(value: str, label: str) -> str:
    if (
        len(value) != 64
        or value != value.lower()
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise DemoError(f"{label} must be one lowercase SHA-256 digest")
    return value


def _canonical_existing(value: Path, label: str) -> tuple[Path, os.stat_result]:
    raw = os.fspath(value)
    if (
        not raw
        or not os.path.isabs(raw)
        or os.path.normpath(raw) != raw
        or any(character in _CONTROL_CHARACTERS for character in raw)
    ):
        raise DemoError(f"{label} must be an absolute canonical path")
    try:
        info = value.lstat()
        resolved = value.resolve(strict=True)
    except OSError as error:
        raise DemoError(f"cannot inspect {label}: {value}") from error
    if stat.S_ISLNK(info.st_mode) or resolved != value:
        raise DemoError(f"{label} must not be or traverse a symlink")
    return resolved, info


def _directory(
    value: Path,
    label: str,
    *,
    private: bool,
    empty: bool,
) -> Path:
    path, info = _canonical_existing(value, label)
    if not stat.S_ISDIR(info.st_mode):
        raise DemoError(f"{label} must be a real directory")
    if private:
        if stat.S_IMODE(info.st_mode) != 0o700:
            raise DemoError(f"{label} must have mode 0700")
        if info.st_uid != os.geteuid():
            raise DemoError(f"{label} must be owned by the current user")
    if empty:
        with os.scandir(path) as entries:
            if next(entries, None) is not None:
                raise DemoError(f"{label} must be empty")
    return path


def _verified_artifact(
    value: Path,
    expected_sha256: str,
    label: str,
    *,
    executable: bool,
) -> tuple[Path, dict[str, Any]]:
    path, initial = _canonical_existing(value, label)
    if not stat.S_ISREG(initial.st_mode) or initial.st_size <= 0:
        raise DemoError(f"{label} must be a nonempty regular file")
    if executable and initial.st_mode & 0o111 == 0:
        raise DemoError(f"{label} must be executable")
    expected = _digest(expected_sha256, f"{label}_sha256")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise DemoError(f"cannot open {label}: {path}") from error
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or (
            opened.st_dev,
            opened.st_ino,
        ) != (initial.st_dev, initial.st_ino):
            raise DemoError(f"{label} changed while it was opened")
        digest = sha256()
        size = 0
        while block := os.read(descriptor, 1 << 20):
            digest.update(block)
            size += len(block)
    finally:
        os.close(descriptor)
    current = path.lstat()
    if (current.st_dev, current.st_ino, current.st_size) != (
        initial.st_dev,
        initial.st_ino,
        initial.st_size,
    ):
        raise DemoError(f"{label} changed while it was hashed")
    actual = digest.hexdigest()
    if actual != expected:
        raise DemoError(f"{label} SHA-256 is {actual}, require {expected}")
    return path, {"path": os.fspath(path), "sha256": actual, "size": size}


def _paths_overlap(first: Path, second: Path) -> bool:
    return first == second or first in second.parents or second in first.parents


def _require_pairwise_disjoint(paths: Mapping[str, Path]) -> None:
    items = list(paths.items())
    for index, (first_label, first) in enumerate(items):
        for second_label, second in items[index + 1 :]:
            if _paths_overlap(first, second):
                raise DemoError(
                    f"{first_label} and {second_label} paths must not overlap"
                )


def _fingerprint_private_file(path: Path, label: str) -> dict[str, Any]:
    resolved, info = _canonical_existing(path, label)
    if not stat.S_ISREG(info.st_mode) or info.st_size <= 0:
        raise DemoError(f"{label} must be a nonempty regular file")
    if stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != os.geteuid():
        raise DemoError(f"{label} must be a current-user file with mode 0600")
    digest = sha256()
    with resolved.open("rb") as source:
        while block := source.read(1 << 20):
            digest.update(block)
    return {
        "path": os.fspath(resolved),
        "sha256": digest.hexdigest(),
        "size": info.st_size,
    }


def _read_runtime_result(
    path: Path,
    *,
    runner_sha256: str,
    codex_sha256: str,
    workspace: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    fingerprint = _fingerprint_private_file(path, "runtime result")
    if fingerprint["size"] > _MAX_RUNTIME_RESULT_BYTES:
        raise DemoError("runtime result exceeds the size limit")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as error:
        raise DemoError("runtime result is not valid JSON") from error
    if not isinstance(value, dict):
        raise DemoError("runtime result is not a JSON object")
    mapping = value.get("workspace_mapping")
    artifacts = value.get("artifacts")
    runner = artifacts.get("runner") if isinstance(artifacts, dict) else None
    if (
        value.get("schema") != 1
        or value.get("success") is not True
        or value.get("runner_sha256") != runner_sha256
        or value.get("codex_sha256") != codex_sha256
        or not isinstance(runner, dict)
        or runner.get("name") != "runner"
        or runner.get("sha256") != runner_sha256
        or not isinstance(runner.get("size"), int)
        or runner["size"] <= 0
        or runner.get("mode") != 0o600
        or not isinstance(mapping, dict)
        or mapping.get("host") != os.fspath(workspace)
        or mapping.get("guest") != "/workspace"
    ):
        raise DemoError("runtime result does not describe the requested successful run")
    session_id = value.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        raise DemoError("runtime result omitted its session identity")
    return value, fingerprint


def _write_exclusive_json(path: Path, value: Mapping[str, Any]) -> None:
    encoded = json.dumps(
        dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8") + b"\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as error:
        raise DemoError(f"cannot publish result: {path}") from error
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as destination:
            destination.write(encoded)
            destination.flush()
            os.fsync(destination.fileno())
    except BaseException:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def _preflight_record(result: PreflightResult) -> dict[str, Any]:
    if not result.ok or not result.seed_archived:
        raise DemoError("deterministic App Server preflight did not complete safely")
    return {
        "ok": True,
        "seed_thread_id": result.seed_thread_id,
        "seed_turn_id": result.seed_turn_id,
        "fork_thread_id": result.fork_thread_id,
        "protected_turn_id": result.protected_turn_id,
        "call_id": result.call_id,
        "effect_id": result.effect_id,
        "seed_archived": result.seed_archived,
        "responses_request_count": result.responses_request_count,
        "models_request_count": result.models_request_count,
        "raw_record_count": result.raw_record_count,
    }


def run_demo(
    *,
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
    runtime_evidence: Path,
    adapter_evidence: Path,
    workspace: Path,
) -> dict[str, Any]:
    """Run one deterministic preflight and publish sanitized evidence metadata."""

    verified: dict[str, dict[str, Any]] = {}
    artifact_paths: dict[str, Path] = {}
    for label, path, digest, executable in (
        ("runner", runner, runner_sha256, True),
        ("firecracker", firecracker, firecracker_sha256, True),
        ("kernel", kernel, kernel_sha256, False),
        ("guest", guest, guest_sha256, True),
        ("payload", payload, payload_sha256, False),
        ("repository", repository, repository_sha256, False),
    ):
        artifact_path, record = _verified_artifact(
            path, digest, label, executable=executable
        )
        artifact_paths[label] = artifact_path
        verified[label] = record

    codex_digest = _digest(codex_sha256, "codex_sha256")
    runtime_dir = _directory(
        runtime_evidence, "runtime_evidence", private=True, empty=True
    )
    adapter_dir = _directory(
        adapter_evidence, "adapter_evidence", private=True, empty=True
    )
    workspace_dir = _directory(workspace, "workspace", private=False, empty=True)
    _require_pairwise_disjoint(
        {
            **artifact_paths,
            "runtime_evidence": runtime_dir,
            "adapter_evidence": adapter_dir,
            "workspace": workspace_dir,
        }
    )

    raw_jsonl = adapter_dir / "app-server.jsonl"
    result_path = adapter_dir / "result.json"
    with create_firecracker_codex(
        runner=artifact_paths["runner"],
        runner_sha256=verified["runner"]["sha256"],
        firecracker=artifact_paths["firecracker"],
        firecracker_sha256=verified["firecracker"]["sha256"],
        kernel=artifact_paths["kernel"],
        kernel_sha256=verified["kernel"]["sha256"],
        guest=artifact_paths["guest"],
        guest_sha256=verified["guest"]["sha256"],
        payload=artifact_paths["payload"],
        payload_sha256=verified["payload"]["sha256"],
        repository=artifact_paths["repository"],
        repository_sha256=verified["repository"]["sha256"],
        codex_sha256=codex_digest,
        evidence_dir=runtime_dir,
        workspace=workspace_dir,
    ) as wrapped:
        previous_umask = os.umask(0o077)
        try:
            preflight = run_preflight(
                codex_binary=os.fspath(wrapped.executable),
                workspace=workspace_dir,
                raw_jsonl_path=raw_jsonl,
            )
        finally:
            os.umask(previous_umask)

    if Path(preflight.raw_jsonl_path) != raw_jsonl:
        raise DemoError("preflight reported an unexpected App Server capture path")
    preflight_record = _preflight_record(preflight)
    runtime_value, runtime_fingerprint = _read_runtime_result(
        runtime_dir / "result.json",
        runner_sha256=verified["runner"]["sha256"],
        codex_sha256=codex_digest,
        workspace=workspace_dir,
    )
    adapter_fingerprint = _fingerprint_private_file(
        raw_jsonl, "App Server JSONL capture"
    )
    if adapter_fingerprint["size"] <= 0 or preflight.raw_record_count <= 0:
        raise DemoError("App Server JSONL capture is empty")

    record: dict[str, Any] = {
        "schema": RESULT_SCHEMA,
        "ok": True,
        "result_path": os.fspath(result_path),
        "artifacts": {**verified, "codex": {"sha256": codex_digest}},
        "workspace": {"host": os.fspath(workspace_dir), "guest": "/workspace"},
        "runtime": {
            "evidence_directory": os.fspath(runtime_dir),
            "session_id": runtime_value["session_id"],
            "result": runtime_fingerprint,
        },
        "adapter": {
            "evidence_directory": os.fspath(adapter_dir),
            "app_server_jsonl": adapter_fingerprint,
        },
        "preflight": preflight_record,
        "independent_evidence_check": "required",
    }
    _write_exclusive_json(result_path, record)
    return record


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the deterministic App Server preflight across one real "
            "Firecracker snapshot/restore. No account credential is used."
        )
    )
    for name, help_text in (
        ("runner", "firecracker-codex-shim executable"),
        ("firecracker", "Firecracker executable"),
        ("kernel", "uncompressed guest kernel"),
        ("guest", "firecracker-agent-guest executable"),
        ("payload", "immutable native Codex SquashFS payload"),
        ("repository", "canonical read-only repository bundle"),
    ):
        parser.add_argument(f"--{name}", required=True, type=Path, help=help_text)
        parser.add_argument(
            f"--{name}-sha256", required=True, help=f"exact SHA-256 of {name}"
        )
    parser.add_argument(
        "--codex-sha256",
        required=True,
        help="exact SHA-256 of payload bin/codex",
    )
    parser.add_argument(
        "--runtime-evidence",
        required=True,
        type=Path,
        help="existing empty current-user directory with mode 0700",
    )
    parser.add_argument(
        "--adapter-evidence",
        required=True,
        type=Path,
        help="separate existing empty current-user directory with mode 0700",
    )
    parser.add_argument(
        "--workspace",
        required=True,
        type=Path,
        help="existing empty canonical host workspace",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        result = run_demo(
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
            runtime_evidence=args.runtime_evidence,
            adapter_evidence=args.adapter_evidence,
            workspace=args.workspace,
        )
    except Exception as error:
        print(f"Firecracker Codex demo failed: {error}", file=sys.stderr)
        return 1
    summary = {
        "schema": RESULT_SCHEMA,
        "ok": True,
        "result_path": result["result_path"],
        "runtime_evidence": result["runtime"]["evidence_directory"],
        "adapter_evidence": result["adapter"]["evidence_directory"],
    }
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["DemoError", "RESULT_SCHEMA", "main", "run_demo"]
