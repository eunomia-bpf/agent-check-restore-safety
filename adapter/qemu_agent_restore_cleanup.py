#!/usr/bin/env python3
"""Find and reap only VM runners and QEMUs named by retained process evidence."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import signal
import sys
import time
from typing import Any


def _records(evidence: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    paths = [
        *( ("qemu", path) for path in evidence.rglob("qemu-process-command.json") ),
        *( ("runner", path) for path in evidence.rglob("*.runner-process-command.json") ),
    ]
    for kind, path in sorted(paths, key=lambda item: os.fspath(item[1])):
        try:
            value = json.loads(path.read_bytes())
        except (OSError, json.JSONDecodeError):
            continue
        if (
            isinstance(value, dict)
            and type(value.get("pid")) is int
            and value["pid"] > 1
            and isinstance(value.get("command_sha256"), str)
            and len(value["command_sha256"]) == 64
        ):
            records.append(
                {
                    "kind": kind,
                    "pid": value["pid"],
                    "command_sha256": value["command_sha256"],
                    "evidence": os.fspath(path.relative_to(evidence)),
                    **(
                        {
                            "process_group_id": value.get("process_group_id"),
                            "session_id": value.get("session_id"),
                            "start_time_ticks": value.get("start_time_ticks"),
                        }
                        if kind == "runner"
                        else {}
                    ),
                }
            )
    return records


def _process_stat(pid: int) -> dict[str, Any] | None:
    try:
        raw = Path(f"/proc/{pid}/stat").read_text()
    except (FileNotFoundError, ProcessLookupError):
        return None
    except OSError:
        return None
    end = raw.rfind(")")
    if end < 0:
        return None
    fields = raw[end + 2 :].split()
    if len(fields) <= 19:
        return None
    try:
        return {
            "pid": pid,
            "state": fields[0],
            "process_group_id": int(fields[2]),
            "session_id": int(fields[3]),
            "start_time_ticks": int(fields[19]),
        }
    except ValueError:
        return None


def _session_members(record: dict[str, Any]) -> list[dict[str, Any]]:
    session_id = record.get("session_id")
    start_time = record.get("start_time_ticks")
    if (
        type(session_id) is not int
        or session_id != record.get("pid")
        or record.get("process_group_id") != session_id
        or type(start_time) is not int
        or start_time <= 0
    ):
        return []
    members: list[dict[str, Any]] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        item = _process_stat(int(entry.name))
        if (
            item is not None
            and item["state"] != "Z"
            and item["session_id"] == session_id
            and item["start_time_ticks"] >= start_time
        ):
            members.append(item)
    return sorted(members, key=lambda item: item["pid"])


def residual(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    live: list[dict[str, Any]] = []
    for record in records:
        if record.get("kind") == "runner":
            members = _session_members(record)
            if members:
                live.append({**record, "members": members})
            continue
        try:
            command = Path(f"/proc/{record['pid']}/cmdline").read_bytes()
        except FileNotFoundError:
            continue
        except OSError:
            continue
        if command and sha256(command).hexdigest() == record["command_sha256"]:
            live.append(record)
    return live


def check_and_reap(evidence: Path, terminate: bool) -> dict[str, Any]:
    records = _records(evidence)
    before = residual(records)
    terminated: list[int] = []
    if terminate:
        targets: set[int] = set()
        for record in before:
            if record.get("kind") == "runner":
                targets.update(member["pid"] for member in record.get("members", []))
            else:
                targets.add(record["pid"])
        for pid in sorted(targets):
            try:
                os.kill(pid, signal.SIGKILL)
                terminated.append(pid)
            except (ProcessLookupError, PermissionError):
                pass
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and residual(records):
            time.sleep(0.05)
    after = residual(records)
    return {
        "schema": 1,
        "checked_processes": len(records),
        "checked_qemu_processes": sum(record["kind"] == "qemu" for record in records),
        "checked_runner_processes": sum(record["kind"] == "runner" for record in records),
        "residual_before": before,
        "terminated_pids": terminated,
        "residual_after": after,
        "valid": not after,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--terminate", action="store_true")
    args = parser.parse_args()
    try:
        result = check_and_reap(args.evidence.resolve(strict=True), args.terminate)
    except (OSError, ValueError) as error:
        print(f"QEMU residual-process check failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
