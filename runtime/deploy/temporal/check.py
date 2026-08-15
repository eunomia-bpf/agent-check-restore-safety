#!/usr/bin/env python3
"""Fail-closed checker for the minimal Temporal H0/H1 baseline evidence."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Mapping


SAMPLES_GO_COMMIT = "dd33bba4f481623958da5a7119bdf49eb72a4c87"
TEMPORAL_CLI_VERSION = "1.8.2"
TEMPORAL_SERVER_VERSION = "1.31.2"
TEMPORAL_SDK_VERSION = "1.47.0"
HEX_64 = re.compile(r"[0-9a-f]{64}\Z")
EVENT_TYPE = re.compile(r"EVENT_TYPE_[A-Z0-9_]+\Z")
MODES = {"pinned", "auto_upgrade", "manual_branch"}
STATUSES = {
    "WORKFLOW_EXECUTION_STATUS_RUNNING",
    "WORKFLOW_EXECUTION_STATUS_COMPLETED",
    "WORKFLOW_EXECUTION_STATUS_FAILED",
    "WORKFLOW_EXECUTION_STATUS_CANCELED",
    "WORKFLOW_EXECUTION_STATUS_TERMINATED",
    "WORKFLOW_EXECUTION_STATUS_TIMED_OUT",
}


class EvidenceError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceError(message)


def _object(value: Any, label: str) -> dict[str, Any]:
    _require(isinstance(value, dict), f"{label} must be an object")
    return value


def _list(value: Any, label: str) -> list[Any]:
    _require(isinstance(value, list), f"{label} must be a list")
    return value


def _digest(value: Any, label: str) -> str:
    _require(isinstance(value, str) and HEX_64.fullmatch(value) is not None, f"{label} is not SHA-256")
    return value


def _loads(path: Path) -> dict[str, Any]:
    try:
        data = path.read_bytes()
    except FileNotFoundError as error:
        raise EvidenceError("Temporal evidence is absent") from error
    _require(len(data) <= 16 << 20, "Temporal evidence exceeds size limit")
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvidenceError("Temporal evidence is not JSON") from error
    return _object(value, "Temporal evidence")


def _events(value: Any, label: str) -> list[str]:
    events = _list(value, label)
    _require(
        events
        and all(isinstance(event, str) and EVENT_TYPE.fullmatch(event) is not None for event in events),
        f"{label} contains an invalid Temporal event type",
    )
    _require(events[0] == "EVENT_TYPE_WORKFLOW_EXECUTION_STARTED", f"{label} does not begin with Workflow start")
    return events


def _records(value: Any, label: str) -> list[dict[str, Any]]:
    records = [_object(item, label + " record") for item in _list(value, label)]
    for sequence, record in enumerate(records, 1):
        _require(
            set(record) == {"sequence", "operation_id", "request_sha256"}
            and record.get("sequence") == sequence
            and isinstance(record.get("operation_id"), str)
            and record["operation_id"]
            and HEX_64.fullmatch(str(record.get("request_sha256"))) is not None,
            f"{label} record differs",
        )
    return records


def _build(value: Any, label: str) -> dict[str, str]:
    build = _object(value, label)
    _require(set(build) == {"build_id", "sha256"}, f"{label} fields changed")
    _require(isinstance(build.get("build_id"), str) and build["build_id"], f"{label} ID is absent")
    _digest(build.get("sha256"), label + " hash")
    return build  # type: ignore[return-value]


def _case(value: Any, expected: str, mode: str) -> dict[str, Any]:
    case = _object(value, expected)
    _require(
        set(case) == {
            "case", "mode", "workflow_id", "input_sha256", "v1_build", "v2_build",
            "provider", "cut_history_event_types", "final_history_event_types",
            "final_status", "observed_deployment_version",
        }
        and case.get("case") == expected
        and case.get("mode") == mode,
        f"{expected} case/mode fields differ",
    )
    _require(isinstance(case.get("workflow_id"), str) and case["workflow_id"], f"{expected} workflow ID is absent")
    _digest(case.get("input_sha256"), f"{expected} input hash")
    v1 = _build(case.get("v1_build"), f"{expected} v1 build")
    v2 = _build(case.get("v2_build"), f"{expected} v2 build")
    _require(v1 != v2 and v1["build_id"] != v2["build_id"], f"{expected} v1/v2 builds are not distinct")
    provider = _object(case.get("provider"), f"{expected} provider")
    _require(set(provider) == {"deliveries", "commits"}, f"{expected} provider fields changed")
    deliveries = _records(provider.get("deliveries"), f"{expected} deliveries")
    commits = _records(provider.get("commits"), f"{expected} commits")
    _require(len(deliveries) == 1, f"{expected} did not dispatch payment exactly once")
    expected_commits = 0 if expected == "h0" else 1
    _require(len(commits) == expected_commits, f"{expected} durable payment commit count differs")
    if commits:
        _require(
            commits[0]["operation_id"] == deliveries[0]["operation_id"]
            and commits[0]["request_sha256"] == deliveries[0]["request_sha256"],
            "H1 durable commit does not match its unique delivery",
        )
    cut = _events(case.get("cut_history_event_types"), f"{expected} cut History")
    final = _events(case.get("final_history_event_types"), f"{expected} final History")
    _require(final[: len(cut)] == cut, f"{expected} final History does not extend its cut")
    status = case.get("final_status")
    _require(status in STATUSES, f"{expected} final Temporal status differs")
    observed = _object(case.get("observed_deployment_version"), f"{expected} observed deployment version")
    _require(
        set(observed) == {"deployment_name", "build_id"}
        and isinstance(observed.get("deployment_name"), str)
        and observed["deployment_name"]
        and observed.get("build_id") in {v1["build_id"], v2["build_id"]},
        f"{expected} observed deployment/build ID differs",
    )
    if expected == "h0":
        _require(
            status != "WORKFLOW_EXECUTION_STATUS_COMPLETED",
            "automatic baseline unsafely completed H0 without a durable payment",
        )
    return {
        "case": case,
        "deliveries": deliveries,
        "commits": commits,
        "cut": cut,
        "final": final,
    }


def check_evidence(path: Path) -> dict[str, Any]:
    evidence = _loads(path)
    _require(set(evidence) == {"schema", "upstream", "mode", "cases"} and evidence.get("schema") == 1, "Temporal evidence schema changed")
    upstream = _object(evidence.get("upstream"), "upstream")
    _require(
        upstream
        == {
            "samples_go_commit": SAMPLES_GO_COMMIT,
            "temporal_cli_version": TEMPORAL_CLI_VERSION,
            "temporal_server_version": TEMPORAL_SERVER_VERSION,
            "temporal_sdk_version": TEMPORAL_SDK_VERSION,
        },
        "Temporal upstream identities differ",
    )
    mode = evidence.get("mode")
    _require(mode in MODES, "Temporal baseline mode differs")
    cases = _object(evidence.get("cases"), "cases")
    _require(set(cases) == {"h0", "h1"}, "Temporal evidence must contain H0 and H1")
    checked = {name: _case(cases[name], name, str(mode)) for name in ("h0", "h1")}
    h0 = checked["h0"]["case"]
    h1 = checked["h1"]["case"]
    for field in ("workflow_id", "input_sha256", "v1_build", "v2_build"):
        _require(h0[field] == h1[field], f"H0/H1 {field} differs")
    _require(checked["h0"]["cut"] == checked["h1"]["cut"], "H0/H1 cut History projection differs")
    _require(
        checked["h0"]["deliveries"] == checked["h1"]["deliveries"],
        "H0/H1 payment delivery identity differs",
    )
    return {
        "valid": True,
        "mode": mode,
        "workflow_id": h0["workflow_id"],
        "h0_status": h0["final_status"],
        "h1_status": h1["final_status"],
        "h0_commits": 0,
        "h1_commits": 1,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()
    try:
        result = check_evidence(args.evidence)
    except EvidenceError as error:
        print(json.dumps({"valid": False, "error": str(error)}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
