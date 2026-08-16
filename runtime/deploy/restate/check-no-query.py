#!/usr/bin/env python3
"""Independently check one Restate H1 run whose authoritative query is unavailable.

The runner is not imported.  This checker replays the binary History, verifies
its external anchor and the standalone Certificate, and joins those facts to
the official Restate cut, the fsynced provider record, and container identity.
"""

from __future__ import annotations

import argparse
import base64
import importlib.util
import json
from hashlib import sha256
from pathlib import Path
import re
import subprocess
import sys
from typing import Any


CHECK_PATH = Path(__file__).with_name("check.py")
SPEC = importlib.util.spec_from_file_location("restate_evidence_check", CHECK_PATH)
assert SPEC is not None and SPEC.loader is not None
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)

RESTATE_IMAGE = (
    "docker.io/restatedev/restate:1.7.3@"
    "sha256:1856961b7a16d1b00131e5704231b79e0334703df074a31867ea8ce2110d5cfa"
)
QUERY_TARGET = "http://payment:8081/v1/query-unavailable"
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")


class EvidenceError(ValueError):
    """The no-query evidence is absent, malformed, or inconsistent."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceError(message)


def read_bytes(root: Path, name: str, *, maximum: int = 64 << 20) -> bytes:
    path = root / name
    try:
        info = path.lstat()
    except FileNotFoundError as error:
        raise EvidenceError(f"required artifact is absent: {name}") from error
    require(path.is_file() and not path.is_symlink(), f"{name} is not a regular file")
    require(info.st_size <= maximum, f"{name} exceeds its size limit")
    data = path.read_bytes()
    require(len(data) == info.st_size, f"{name} changed while read")
    return data


def read_json(root: Path, name: str) -> Any:
    try:
        return CHECK._loads(read_bytes(root, name), name)
    except CHECK.EvidenceError as error:
        raise EvidenceError(str(error)) from error


def object_value(value: Any, label: str) -> dict[str, Any]:
    require(isinstance(value, dict), f"{label} must be an object")
    return value


def list_value(value: Any, label: str) -> list[Any]:
    require(isinstance(value, list), f"{label} must be an array")
    return value


def exact_fields(value: dict[str, Any], fields: set[str], label: str) -> None:
    require(set(value) == fields, f"{label} fields changed")


def parse_build_env(data: bytes) -> dict[str, str]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise EvidenceError("build.env is not UTF-8") from error
    output: dict[str, str] = {}
    for line_number, line in enumerate(text.splitlines(), 1):
        require(line and "=" in line and not line.startswith("#"), f"build.env line {line_number} is invalid")
        key, value = line.split("=", 1)
        require(re.fullmatch(r"[A-Z][A-Z0-9_]*", key) is not None, f"build.env key {key!r} is invalid")
        require(key not in output and value, f"build.env key {key!r} is duplicate or empty")
        output[key] = value
    required = {
        "ORDER_V1_IMAGE", "ORDER_V2_IMAGE", "SAFE_CHANGE_RUNTIME_IMAGE",
        "UPSTREAM_ARCHIVE_SHA256", "APP_LOCK_SHA256", "V1_PROGRAM_SHA256",
        "V2_PROGRAM_SHA256",
    }
    require(required <= set(output), "build.env omitted required provenance")
    for key in ("ORDER_V1_IMAGE", "ORDER_V2_IMAGE", "SAFE_CHANGE_RUNTIME_IMAGE"):
        require(IMAGE_ID.fullmatch(output[key]) is not None, f"{key} is not an immutable image ID")
    for key in ("UPSTREAM_ARCHIVE_SHA256", "APP_LOCK_SHA256", "V1_PROGRAM_SHA256", "V2_PROGRAM_SHA256"):
        require(HEX64.fullmatch(output[key]) is not None, f"{key} is not SHA-256")
    require(output["ORDER_V1_IMAGE"] != output["ORDER_V2_IMAGE"], "v1 and v2 images are identical")
    return output


def require_stats(value: Any, deliveries: int, commits: int, paths: dict[str, int], label: str) -> dict[str, Any]:
    item = object_value(value, label)
    exact_fields(item, {"deliveries", "commits", "paths"}, label)
    require(item == {"deliveries": deliveries, "commits": commits, "paths": paths}, f"{label} differs")
    return item


def require_single_row(value: Any, label: str) -> dict[str, Any]:
    wrapper = object_value(value, label)
    exact_fields(wrapper, {"rows"}, label)
    rows = list_value(wrapper["rows"], label + " rows")
    require(len(rows) == 1 and isinstance(rows[0], dict), f"{label} must contain one row")
    return rows[0]


def check_evidence(root: Path, runtime_root: Path) -> dict[str, Any]:
    root = root.resolve(strict=True)
    runtime_root = runtime_root.resolve(strict=True)
    build = parse_build_env(read_bytes(root, "build.env"))

    require(read_bytes(root, "base-runner-exit-status.txt") == b"22\n", "base runner did not stop at failed HTTP recovery")
    require(read_bytes(root, "exit-status.txt") == b"22\n", "base runner exit status differs")
    require(read_bytes(root, "no-query-exit-status.txt") == b"0\n", "no-query runner did not complete")
    require(read_bytes(root, "no-query-recovery.http-status.txt") == b"409\n", "recovery HTTP status differs")

    requirement_v1 = object_value(read_json(root, "requirement-v1.json"), "source Requirement")
    requirement_v2 = object_value(read_json(root, "requirement-v2.json"), "target Requirement")
    expected_results = {"paid": 1, "delivered": 1}
    require(requirement_v1.get("id") == "food-ordering-v1", "source Requirement identity changed")
    require(requirement_v2.get("id") == "food-ordering-v2", "target Requirement identity changed")
    for requirement, label in ((requirement_v1, "source"), (requirement_v2, "target")):
        exact_fields(requirement, {"id", "results", "capacities", "kinds"}, label + " Requirement")
        require(requirement["results"] == expected_results, f"{label} business Results changed")
        require(requirement["capacities"] == {"charge": 1}, f"{label} charge capacity changed")
        require(set(object_value(requirement["kinds"], label + " kinds")) == {"charge-v1", "finish"}, f"{label} kinds changed")
    source_charge = object_value(requirement_v1["kinds"]["charge-v1"], "source charge kind")
    require(source_charge.get("queryable") is True and source_charge.get("query_target") == QUERY_TARGET, "source query endpoint is not the unavailable frozen endpoint")
    target_charge = object_value(requirement_v2["kinds"]["charge-v1"], "target charge kind")
    require(target_charge == {"costs": {"charge": 1}, "produces": {"paid": 1}, "retry_safe": False, "queryable": False}, "target retained an executable payment producer")

    try:
        events = CHECK._history(root / "no-query-runtime.history")
        CHECK._head(root / "no-query-runtime.head", events)
    except CHECK.EvidenceError as error:
        raise EvidenceError(str(error)) from error
    require([event["operation"] for event in events] == [
        "rule.activated", "operation.prepared", "operation.phase", "operation.phase"
    ], "no-query History has unexpected events")
    history_view = read_json(root, "history-before-no-query.json")
    require(history_view == events, "History API view differs from binary replay")
    require(read_json(root, "history-after-no-query.json") == history_view, "failed query changed History")
    require(read_json(root, "history-before-no-query.normalized.json") == history_view, "normalized pre-query History differs")
    require(read_json(root, "history-after-no-query.normalized.json") == history_view, "normalized post-query History differs")

    before = object_value(read_json(root, "control-before-no-query.json"), "pre-query state")
    after = object_value(read_json(root, "control-after-no-query.json"), "post-query state")
    require(before == after, "failed query changed control state")
    require(read_json(root, "control-before-no-query.normalized.json") == before, "normalized pre-query state differs")
    require(read_json(root, "control-after-no-query.normalized.json") == before, "normalized post-query state differs")
    require(read_json(root, "control-unknown.json") == before, "captured unknown state differs from queried state")
    exact_fields(before, {"history", "requirement", "rule", "operations"}, "control state")
    require(before["history"] == {"sequence": 4, "hash": events[-1]["hash"]}, "control History head differs")
    require(before["requirement"] == requirement_v1, "active Requirement differs from source input")
    operations = object_value(before["operations"], "open Operations")
    require(len(operations) == 1, "control did not retain exactly one Operation")
    operation_id, operation = next(iter(operations.items()))
    operation = object_value(operation, "payment Operation")
    require(CHECK.OPERATION_ID.fullmatch(operation_id) is not None and operation.get("id") == operation_id, "payment Operation identity differs")
    require(operation.get("kind") == "charge-v1" and operation.get("phase") == "unknown", "payment Operation is not unknown")
    require(operation.get("queryable") is True and operation.get("query_target") == QUERY_TARGET, "Operation did not freeze the unavailable query endpoint")
    require(operation.get("request_stored") is True and operation.get("result_hash") is None, "unknown Operation contains an outcome")
    try:
        request_body = base64.b64decode(operation["request_body"], validate=True)
    except (KeyError, ValueError) as error:
        raise EvidenceError("payment request body is not canonical base64") from error
    require(base64.b64encode(request_body).decode() == operation["request_body"], "payment request body is not canonical base64")
    request = object_value(CHECK._loads(request_body, "payment request body"), "payment request body")
    order = object_value(read_json(root, "order.json"), "order")
    require(request == {"order_id": order.get("id"), "amount": order.get("totalCost")}, "stored payment request differs from order")

    recovery = object_value(read_json(root, "no-query-recovery.json"), "recovery response")
    exact_fields(recovery, {"outcome", "error", "code"}, "recovery response")
    outcome = object_value(recovery["outcome"], "recovery outcome")
    require(recovery["code"] == "outcome_unknown", "recovery did not fail closed")
    require(outcome == {"operation_id": operation_id, "phase": "unknown", "result_hash": "", "reused": False, "recovered_by_query": False}, "recovery outcome differs")
    require(isinstance(recovery["error"], str) and "response status is 404" in recovery["error"] and operation_id in recovery["error"], "recovery error does not establish unavailable observation")

    payment_stats = require_stats(read_json(root, "no-query-payment-stats.json"), 1, 1, {"/v1/charge": 1}, "payment stats")
    require(require_stats(read_json(root, "payment-at-commit.json"), 1, 1, {"/v1/charge": 1}, "cut payment stats") == payment_stats, "payment truth changed after cut")
    require_stats(read_json(root, "no-query-completion-stats.json"), 0, 0, {}, "completion stats")
    try:
        payment_records = CHECK._records(root / "no-query-payment.history", "payment records")
        completion_records = CHECK._records(root / "no-query-completion.history", "completion records")
    except CHECK.EvidenceError as error:
        raise EvidenceError(str(error)) from error
    require(len(payment_records) == 1 and payment_records[0]["operation_id"] == operation_id and payment_records[0]["path"] == "/v1/charge", "fsynced payment fact differs")
    require(completion_records == [], "a completion effect was delivered")

    certificate_state = object_value(read_json(root, "no-query-certificate-state-v2.json"), "Certificate state")
    certificate = object_value(read_json(root, "no-query-certificate-v2.json"), "Certificate")
    recorded_verdict = object_value(read_json(root, "no-query-certificate-verdict-v2.json"), "recorded Certificate verdict")
    require(certificate.get("decision") == "impossible" and certificate.get("rule") is None and certificate.get("witness") is not None, "target Certificate did not refuse")
    require(certificate.get("history") == before["history"] and certificate.get("requirement") == requirement_v2, "Certificate is not bound to target and History")
    require(certificate_state.get("history") == before["history"] and certificate_state.get("settled") == {"used": {}, "results": {}}, "Certificate state invented settled progress")
    open_operations = object_value(certificate_state.get("open_operations"), "Certificate open Operations")
    require(set(open_operations) == {operation_id}, "Certificate state omitted or added an open Operation")
    command = ["go", "run", "./cmd/check-certificate", "-state", str(root / "no-query-certificate-state-v2.json"), "-certificate", str(root / "no-query-certificate-v2.json")]
    completed = subprocess.run(command, cwd=runtime_root, check=False, capture_output=True, text=True, timeout=120)
    require(completed.returncode == 0, f"fresh Certificate check failed: {completed.stderr.strip()}")
    fresh_verdict = object_value(CHECK._loads(completed.stdout.encode(), "fresh Certificate verdict"), "fresh Certificate verdict")
    require(fresh_verdict == recorded_verdict and fresh_verdict == {"valid": True, "decision": "impossible", "history_sequence": 4, "history_hash": events[-1]["hash"]}, "Certificate verdict differs on replay")

    cut_status = require_single_row(read_json(root, "source-cut-status.json"), "Restate cut status")
    cut_after = require_single_row(read_json(root, "source-cut-status-after-window.json"), "Restate stable cut status")
    require(cut_status == cut_after and cut_status.get("status") == "paused" and cut_status.get("journal_size") == 3, "Restate cut was not a stable paused payment Run")
    require(cut_status.get("target") == f"order-workflow/{order.get('id')}/run", "Restate cut order identity differs")
    journal = object_value(read_json(root, "source-cut-journal.json"), "Restate journal")
    journal_after = object_value(read_json(root, "source-cut-journal-after-window.json"), "stable Restate journal")
    require(journal == journal_after, "Restate journal changed during cut window")
    rows = list_value(journal.get("rows"), "Restate journal rows")
    require([(row.get("index"), row.get("entry_type"), row.get("name"), row.get("completed")) for row in rows] == [
        (0, "Command: Input", "", False), (1, "Command: SetState", "", False), (2, "Command: Run", "payment", False)
    ], "Restate journal is not held in the unresolved payment closure")
    workflow = read_json(root, "source-cut-workflow-state.json")
    require(workflow == read_json(root, "source-cut-workflow-state-after-window.json"), "Restate workflow state changed during cut window")
    workflow_row = require_single_row(workflow, "Restate workflow state")
    require(workflow_row.get("service_key") == order.get("id") and workflow_row.get("key") == "status" and workflow_row.get("value_utf8") == '"CREATED"', "Restate workflow position differs")

    before_kill = list_value(read_json(root, "source-container-before-kill.json"), "source container")
    require(len(before_kill) == 1 and isinstance(before_kill[0], dict), "source container identity is ambiguous")
    source_container = before_kill[0]
    require(source_container.get("Image") == build["ORDER_V1_IMAGE"], "source worker did not use frozen v1 image")
    removal = object_value(read_json(root, "source-v1-removal.json"), "source removal")
    require(removal == {
        "schema": 1, "compose_service": "order-v1", "container_id": source_container.get("Id"),
        "remove_exit_code": 0, "inspect_exit_code": 1, "stderr": f"error: no such object: {source_container.get('Id')}",
        "fenced_before_history_sequence": 4,
    }, "source v1 removal evidence differs")

    containers = list_value(read_json(root, "no-query-containers.raw.json"), "container inspection")
    services: dict[str, dict[str, Any]] = {}
    for container in containers:
        item = object_value(container, "container")
        labels = object_value(object_value(item.get("Config"), "container config").get("Labels"), "container labels")
        service = labels.get("com.docker.compose.service")
        require(isinstance(service, str) and service and service not in services, "container service identity differs")
        services[service] = item
    require("order-v1" not in services and "order-v2" not in services, "a source or refused target worker remained")
    require(services.get("restate", {}).get("Config", {}).get("Image") == RESTATE_IMAGE, "official Restate image differs")
    require(services.get("control", {}).get("Image") == build["SAFE_CHANGE_RUNTIME_IMAGE"], "runtime image differs from build provenance")

    summary = object_value(read_json(root, "no-query-summary.json"), "summary")
    exact_fields(summary, {"schema", "case", "operation_id", "query_target", "durable_payment_fact", "payment", "recovery", "certificate", "planned_target_image", "target_started", "completion_started", "history_changed_by_failed_query"}, "summary")
    require(summary == {
        "schema": 1, "case": "h1-no-query", "operation_id": operation_id,
        "query_target": QUERY_TARGET, "durable_payment_fact": True, "payment": payment_stats,
        "recovery": {"http_status": 409, "body": recovery}, "certificate": certificate,
        "planned_target_image": build["ORDER_V2_IMAGE"], "target_started": False,
        "completion_started": False, "history_changed_by_failed_query": False,
    }, "summary is inconsistent with raw evidence")

    required_files = sorted({
        "build.env", "base-runner-exit-status.txt", "exit-status.txt", "no-query-exit-status.txt",
        "no-query-recovery.http-status.txt", "requirement-v1.json", "requirement-v2.json",
        "no-query-runtime.history", "no-query-runtime.head", "history-before-no-query.json",
        "history-after-no-query.json", "history-before-no-query.normalized.json",
        "history-after-no-query.normalized.json", "control-before-no-query.json",
        "control-after-no-query.json", "control-before-no-query.normalized.json",
        "control-after-no-query.normalized.json", "control-unknown.json", "order.json",
        "no-query-recovery.json", "no-query-payment-stats.json", "payment-at-commit.json",
        "no-query-completion-stats.json", "no-query-payment.history", "no-query-completion.history",
        "no-query-certificate-state-v2.json", "no-query-certificate-v2.json",
        "no-query-certificate-verdict-v2.json", "source-cut-status.json",
        "source-cut-status-after-window.json", "source-cut-journal.json",
        "source-cut-journal-after-window.json", "source-cut-workflow-state.json",
        "source-cut-workflow-state-after-window.json", "source-container-before-kill.json",
        "source-v1-removal.json", "no-query-containers.raw.json", "no-query-summary.json",
    })
    artifact_hashes = {name: sha256(read_bytes(root, name)).hexdigest() for name in required_files}
    evidence_digest = sha256(json.dumps(artifact_hashes, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        "schema": 1, "valid": True, "case": "h1-no-query", "decision": "impossible",
        "operation_id": operation_id, "history_sequence": 4, "history_hash": events[-1]["hash"],
        "payment_deliveries": 1, "payment_commits": 1, "completion_deliveries": 0,
        "target_started": False, "history_changed_by_failed_query": False,
        "artifact_count": len(artifact_hashes), "evidence_digest": evidence_digest,
    }


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--evidence", required=True, type=Path, help="completed no-query results directory")
    value.add_argument("--runtime-root", type=Path, default=Path(__file__).resolve().parents[2], help="runtime source root containing cmd/check-certificate")
    return value


def main() -> int:
    args = parser().parse_args()
    try:
        verdict = check_evidence(args.evidence, args.runtime_root)
    except (EvidenceError, CHECK.EvidenceError, OSError, subprocess.SubprocessError) as error:
        print(f"check-no-query: {error}", file=sys.stderr)
        return 1
    print(json.dumps(verdict, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
