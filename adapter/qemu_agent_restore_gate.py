#!/usr/bin/env python3
"""Seal source provenance and admit a checked QEMU restore preflight."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time
from typing import Any


class GateError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _sha_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        while chunk := source.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def source_manifest(root: Path) -> dict[str, Any]:
    listed = subprocess.check_output(
        [
            "git",
            "-C",
            os.fspath(root),
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
            "--",
            "runtime",
            "adapter",
            "Makefile",
        ]
    ).split(b"\0")
    files: list[dict[str, Any]] = []
    for encoded in sorted(item for item in listed if item):
        relative = encoded.decode("utf-8")
        path = root / relative
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode):
            raise GateError(f"source manifest rejects non-regular path: {relative}")
        data = path.read_bytes()
        files.append(
            {
                "path": relative,
                "mode": format(stat.S_IMODE(info.st_mode), "04o"),
                "size": len(data),
                "sha256": sha256(data).hexdigest(),
            }
        )
    return {
        "schema": 1,
        "files": files,
        "root_sha256": sha256(_canonical(files)).hexdigest(),
    }


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as error:
        raise GateError(f"{label} is not valid JSON: {path}") from error
    if not isinstance(value, dict):
        raise GateError(f"{label} is not an object")
    return value


def _write_new(path: Path, value: Any) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as output:
            output.write(_canonical(value) + b"\n")
            output.flush()
            os.fsync(output.fileno())
    finally:
        os.close(descriptor)


def verify_source_manifest(root: Path, retained: Path) -> dict[str, Any]:
    recorded = _load_object(retained, "retained source manifest")
    current = source_manifest(root)
    if recorded != current:
        raise GateError("current runtime/adapter/Makefile source differs from retained source manifest")
    return current


def create_gate(
    root: Path,
    evidence: Path,
    gate_path: Path,
    checker: Path,
    certificate_checker: Path,
) -> dict[str, Any]:
    manifest = verify_source_manifest(root, evidence / "source-manifest.json")
    result = _load_object(evidence / "result.json", "preflight result")
    runtime_result = _load_object(evidence / "runtime" / "result.json", "preflight runtime result")
    if result.get("pass") is not True or runtime_result.get("valid") is not True:
        raise GateError("preflight producer result did not pass")
    if runtime_result.get("repetitions") != 1:
        raise GateError("admission requires exactly one complete preflight triple")
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            os.fspath(checker),
            "--evidence",
            os.fspath(evidence),
            "--certificate-checker",
            os.fspath(certificate_checker),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=180,
    )
    if completed.returncode != 0:
        raise GateError(
            "independent preflight check failed: "
            + completed.stderr.decode("utf-8", "replace")[-2000:]
        )
    try:
        verdict = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise GateError("independent preflight checker output is malformed") from error
    if not isinstance(verdict, dict) or verdict.get("valid") is not True:
        raise GateError("independent preflight checker did not return valid=true")
    progress = _load_object(evidence / "runtime" / "progress.json", "preflight progress")
    if progress.get("status") != "complete" or not isinstance(progress.get("elapsed_seconds"), (int, float)):
        raise GateError("preflight lacks a complete measured-duration record")
    execution = _load_object(evidence / "execution.json", "preflight execution")
    if (
        execution.get("driver_exit_status") != 0
        or execution.get("timed_out") is not False
        or not isinstance(execution.get("total_duration_seconds"), (int, float))
        or execution["total_duration_seconds"] <= 0
    ):
        raise GateError("preflight lacks a successful total-duration record")
    gate = {
        "schema": 1,
        "admitted": True,
        "created_time_ns": time.time_ns(),
        "source_root_sha256": manifest["root_sha256"],
        "checker_sha256": _sha_file(checker),
        "certificate_checker_sha256": _sha_file(certificate_checker),
        "preflight_result_sha256": _sha_file(evidence / "result.json"),
        "preflight_runtime_result_sha256": _sha_file(evidence / "runtime" / "result.json"),
        "preflight_check_sha256": sha256(completed.stdout).hexdigest(),
        "preflight_check": verdict,
        "preflight_elapsed_seconds": execution["total_duration_seconds"],
        "preflight_evidence": os.fspath(evidence),
    }
    _write_new(gate_path, gate)
    return gate


def verify_gate(root: Path, gate_path: Path, checker: Path, certificate_checker: Path) -> dict[str, Any]:
    gate = _load_object(gate_path, "preflight admission gate")
    required = {
        "admitted": True,
        "source_root_sha256": source_manifest(root)["root_sha256"],
        "checker_sha256": _sha_file(checker),
        "certificate_checker_sha256": _sha_file(certificate_checker),
    }
    for field, expected in required.items():
        if gate.get(field) != expected:
            raise GateError(f"preflight admission gate field {field} differs")
    evidence = Path(str(gate.get("preflight_evidence", "")))
    if not isinstance(gate.get("preflight_check"), dict) or gate["preflight_check"].get("valid") is not True:
        raise GateError("preflight admission does not retain a valid independent verdict")
    if gate.get("preflight_check_sha256") != sha256(_canonical(gate["preflight_check"]) + b"\n").hexdigest():
        raise GateError("retained independent preflight verdict hash differs")
    if not evidence.is_absolute():
        raise GateError("preflight evidence path is not absolute")
    if gate.get("preflight_result_sha256") != _sha_file(evidence / "result.json"):
        raise GateError("preflight result changed after admission")
    if gate.get("preflight_runtime_result_sha256") != _sha_file(evidence / "runtime" / "result.json"):
        raise GateError("preflight runtime result changed after admission")
    verify_source_manifest(root, evidence / "source-manifest.json")
    return gate


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    manifest_parser = subparsers.add_parser("manifest")
    manifest_parser.add_argument("--repo-root", required=True, type=Path)
    manifest_parser.add_argument("--output", required=True, type=Path)
    for name in ("create", "verify"):
        command = subparsers.add_parser(name)
        command.add_argument("--repo-root", required=True, type=Path)
        command.add_argument("--gate", required=True, type=Path)
        command.add_argument("--checker", required=True, type=Path)
        command.add_argument("--certificate-checker", required=True, type=Path)
        if name == "create":
            command.add_argument("--evidence", required=True, type=Path)
    args = parser.parse_args()
    try:
        root = args.repo_root.resolve(strict=True)
        if args.command == "manifest":
            result = source_manifest(root)
            _write_new(args.output, result)
        elif args.command == "create":
            result = create_gate(
                root,
                args.evidence.resolve(strict=True),
                args.gate.resolve(strict=False),
                args.checker.resolve(strict=True),
                args.certificate_checker.resolve(strict=True),
            )
        else:
            result = verify_gate(
                root,
                args.gate.resolve(strict=True),
                args.checker.resolve(strict=True),
                args.certificate_checker.resolve(strict=True),
            )
    except (GateError, OSError, subprocess.SubprocessError, ValueError) as error:
        print(f"QEMU Agent Restore admission failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
