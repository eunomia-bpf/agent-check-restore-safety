#!/usr/bin/env python3
"""Check and, when requested, reap only retained Firecracker cell sessions."""

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


def _process_stat(pid: int) -> dict[str, Any] | None:
    try:
        raw = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    end = raw.rfind(")")
    fields = raw[end + 2 :].split() if end >= 0 else []
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


def _records(evidence: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(evidence.glob("*.runner-process.json")):
        try:
            value = json.loads(path.read_bytes())
        except (OSError, json.JSONDecodeError):
            continue
        if (
            isinstance(value, dict)
            and value.get("kind") == "firecracker-cell-runner"
            and type(value.get("pid")) is int
            and value["pid"] > 1
            and value.get("process_group_id") == value["pid"]
            and value.get("session_id") == value["pid"]
            and type(value.get("start_time_ticks")) is int
            and value["start_time_ticks"] > 0
            and isinstance(value.get("command_sha256"), str)
        ):
            records.append({**value, "evidence": path.name})
    return records


def _session_members(record: dict[str, Any]) -> list[dict[str, Any]]:
    members: list[dict[str, Any]] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        item = _process_stat(int(entry.name))
        if (
            item is not None
            and item["state"] != "Z"
            and item["session_id"] == record["session_id"]
            and item["start_time_ticks"] >= record["start_time_ticks"]
        ):
            members.append(item)
    return sorted(members, key=lambda item: item["pid"])


def residual(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    live: list[dict[str, Any]] = []
    for record in records:
        members = _session_members(record)
        if members:
            runner = next((item for item in members if item["pid"] == record["pid"]), None)
            if runner is not None:
                try:
                    command = Path(f"/proc/{record['pid']}/cmdline").read_bytes()
                except OSError:
                    command = b""
                if sha256(command).hexdigest() != record["command_sha256"]:
                    continue
            live.append({**record, "members": members})
    return live


def check_and_reap(evidence: Path, terminate: bool) -> dict[str, Any]:
    records = _records(evidence)
    before = residual(records)
    terminated: list[int] = []
    if terminate:
        targets = {
            member["pid"]
            for record in before
            for member in record.get("members", [])
        }
        for pid in sorted(targets, reverse=True):
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
        "checked_sessions": len(records),
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
        print(f"Firecracker residual-process check failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
