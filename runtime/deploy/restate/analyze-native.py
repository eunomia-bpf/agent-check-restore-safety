#!/usr/bin/env python3
"""Validate and neutrally classify one paired native-Restate replacement run."""

from __future__ import annotations

import argparse
import importlib.util
import json
from hashlib import sha256
from pathlib import Path
import re
import sys
from typing import Any


BASE_CHECK_PATH = Path(__file__).with_name("check.py")
SPEC = importlib.util.spec_from_file_location("restate_evidence_check", BASE_CHECK_PATH)
assert SPEC is not None and SPEC.loader is not None
BASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BASE)

UPSTREAM_COMMIT = "2d429daae784d20982691fb31431702b4ad30a6b"
RESTATE_IMAGE = (
    "docker.io/restatedev/restate:1.7.3@"
    "sha256:1856961b7a16d1b00131e5704231b79e0334703df074a31867ea8ce2110d5cfa"
)
EXPECTED_COMMANDS = (
    b"start-target-v2\nregister-target-v2\nstart-driver-01\nstart-driver-02\n"
    b"resume-source-on-target\nfixed-observation-window\ncapture-final-evidence\n"
)
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")


class EvidenceError(ValueError):
    """Native evidence is absent, malformed, or internally inconsistent."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceError(message)


def read(root: Path, name: str, *, maximum: int = 64 << 20) -> bytes:
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


def json_value(root: Path, name: str) -> Any:
    try:
        return BASE._loads(read(root, name), name)
    except BASE.EvidenceError as error:
        raise EvidenceError(str(error)) from error


def object_value(value: Any, label: str) -> dict[str, Any]:
    require(isinstance(value, dict), f"{label} must be an object")
    return value


def list_value(value: Any, label: str) -> list[Any]:
    require(isinstance(value, list), f"{label} must be an array")
    return value


def one_row(value: Any, label: str) -> dict[str, Any]:
    wrapper = object_value(value, label)
    require(set(wrapper) == {"rows"}, f"{label} fields changed")
    rows = list_value(wrapper["rows"], label + " rows")
    require(len(rows) == 1 and isinstance(rows[0], dict), f"{label} must contain one row")
    return rows[0]


def parse_build_env(data: bytes) -> dict[str, str]:
    try:
        text = data.decode()
    except UnicodeDecodeError as error:
        raise EvidenceError("build.env is not UTF-8") from error
    output: dict[str, str] = {}
    for number, line in enumerate(text.splitlines(), 1):
        require(line and "=" in line, f"build.env line {number} is invalid")
        key, value = line.split("=", 1)
        require(re.fullmatch(r"[A-Z][A-Z0-9_]*", key) is not None and key not in output and value, f"build.env line {number} differs")
        output[key] = value
    required = {
        "NATIVE_ORDER_V1_IMAGE", "NATIVE_ORDER_V2_IMAGE", "SAFE_CHANGE_RUNTIME_IMAGE",
        "NATIVE_V1_CONTEXT_SHA256", "NATIVE_V2_CONTEXT_SHA256",
        "NATIVE_V1_COMPILED_SHA256", "NATIVE_V2_COMPILED_SHA256",
        "NATIVE_PAYMENT_CLIENT_SHA256", "NATIVE_COMPLETION_CLIENT_SHA256",
        "PROVIDER_DIRECT_PATCH_SHA256", "UPSTREAM_ARCHIVE_SHA256", "APP_LOCK_SHA256",
        "V1_PROGRAM_SHA256", "V2_PROGRAM_SHA256",
    }
    require(required <= set(output), "build.env omitted native provenance")
    for key in required:
        pattern = IMAGE_ID if key.endswith("_IMAGE") else HEX64
        require(pattern.fullmatch(output[key]) is not None, f"{key} is not immutable provenance")
    require(output["V1_PROGRAM_SHA256"] == "308fd539f4b612badd5d461436c2b6fae3db67dd8caea2727d2d82caa7379075", "native v1 program differs from frozen proposed v1")
    require(output["V2_PROGRAM_SHA256"] == "2069b3b2a33d71ac6f343e0766a1ce7a9b2aa581255cbea46ae63926aacdefbf", "native v2 program differs from frozen proposed v2")
    require(output["NATIVE_V1_COMPILED_SHA256"] != output["NATIVE_V2_COMPILED_SHA256"], "compiled native v1/v2 programs are identical")
    return output


def stats(value: Any, label: str) -> dict[str, Any]:
    item = object_value(value, label)
    require(set(item) == {"deliveries", "commits", "paths"}, f"{label} fields changed")
    deliveries, commits, paths = item["deliveries"], item["commits"], item["paths"]
    require(type(deliveries) is int and type(commits) is int and deliveries >= commits >= 0, f"{label} counts differ")
    require(isinstance(paths, dict) and all(isinstance(k, str) and type(v) is int and v >= 0 for k, v in paths.items()), f"{label} paths differ")
    require(sum(paths.values()) == deliveries, f"{label} path total differs")
    return item


def normalize_status(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key not in {
        "id", "pinned_deployment_id", "last_attempt_deployment_id",
        "created_at", "modified_at", "next_retry_at",
    }}


def container_services(root: Path, build: dict[str, str]) -> dict[str, dict[str, Any]]:
    values = list_value(json_value(root, "containers.raw.json"), "container inspection")
    services: dict[str, dict[str, Any]] = {}
    for raw in values:
        item = object_value(raw, "container")
        config = object_value(item.get("Config"), "container config")
        labels = object_value(config.get("Labels"), "container labels")
        service = labels.get("com.docker.compose.service")
        require(isinstance(service, str) and service and service not in services, "container service identity differs")
        services[service] = item
    require("control" not in services and "naive-payment" not in services, "native lane included proposed control services")
    require(services.get("order-v1", {}).get("Image") == build["NATIVE_ORDER_V1_IMAGE"], "native source image differs")
    require(services.get("order-v2", {}).get("Image") == build["NATIVE_ORDER_V2_IMAGE"], "native target image differs")
    require(services.get("restate", {}).get("Config", {}).get("Image") == RESTATE_IMAGE, "Restate image differs")
    require(services.get("payment", {}).get("Image") == build["SAFE_CHANGE_RUNTIME_IMAGE"], "payment provider image differs")
    for service in ("order-v1", "order-v2"):
        networks = sorted(object_value(services[service].get("NetworkSettings"), service + " network settings").get("Networks", {}))
        require(len(networks) == 2 and networks[0].endswith("_application") and networks[1].endswith("_effects"), f"{service} is not on native application/effect networks")
        require(services[service].get("State", {}).get("Running") is True, f"{service} was not retained running")
    return services


def deployment_pair(root: Path, build: dict[str, str]) -> tuple[str, str]:
    v1 = object_value(json_value(root, "deployment-v1.json"), "v1 deployment")
    v2 = object_value(json_value(root, "deployment-v2.json"), "v2 deployment")
    v1_id, v2_id = v1.get("id"), v2.get("id")
    require(isinstance(v1_id, str) and isinstance(v2_id, str) and v1_id != v2_id, "deployment identities differ")
    for value, identity, revision in ((v1, v1_id, 1), (v2, v2_id, 2)):
        services = list_value(value.get("services"), "deployment services")
        require(len(services) == 6 and all(item.get("deployment_id") == identity and item.get("revision") == revision for item in services), "deployment service revision differs")
    deployments = object_value(json_value(root, "deployments.json"), "deployment list")
    items = list_value(deployments.get("deployments"), "deployments")
    selected = {item.get("id"): item for item in items if item.get("id") in {v1_id, v2_id}}
    require(set(selected) == {v1_id, v2_id}, "registered native deployments are absent")
    expected = {
        v1_id: ("http://order-v1:9080/", "native-v1"),
        v2_id: ("http://order-v2:9080/", "native-v2"),
    }
    for identity, (uri, variant) in expected.items():
        item = selected[identity]
        require(item.get("uri") == uri, f"{variant} deployment URI differs")
        require(item.get("metadata") == {"method": "native-restate", "variant": variant, "upstream_commit": UPSTREAM_COMMIT}, f"{variant} metadata differs")
    return v1_id, v2_id


def check_case(root: Path, case_name: str, build_bytes: bytes) -> dict[str, Any]:
    root = root.resolve(strict=True)
    require(read(root, "exit-status.txt") == b"0\n", f"{case_name} runner did not complete")
    require(read(root, "build.env") == build_bytes, f"{case_name} build provenance differs")
    build = parse_build_env(build_bytes)
    order = object_value(json_value(root, "order.json"), f"{case_name} order")
    require(set(order) == {"id", "restaurantId", "products", "totalCost", "deliveryDelay"}, f"{case_name} order fields changed")
    require(order["restaurantId"] == "restaurant-01" and order["products"] == [{"productId": "pizza-01", "description": "Pizza", "quantity": 1}] and order["totalCost"] == 42 and order["deliveryDelay"] == 0, f"{case_name} workload differs")
    order_id = order.get("id")
    require(isinstance(order_id, str) and re.fullmatch(r"[A-Za-z0-9._-]{1,128}", order_id) is not None, f"{case_name} order identity differs")
    submit = object_value(json_value(root, "source-submit.json"), f"{case_name} submit")
    require(set(submit) == {"invocationId", "status"} and submit.get("status") == "Accepted", f"{case_name} source submit differs")

    v1_id, v2_id = deployment_pair(root, build)
    cut_status = one_row(json_value(root, "cut-status.json"), f"{case_name} cut status")
    require(cut_status == one_row(json_value(root, "cut-status-after-window.json"), f"{case_name} stable cut status"), f"{case_name} cut status changed")
    invocation_id = cut_status.get("id")
    require(invocation_id == submit.get("invocationId") and cut_status.get("target") == f"order-workflow/{order_id}/run", f"{case_name} invocation identity differs")
    require(cut_status.get("status") == "paused" and cut_status.get("pinned_deployment_id") == v1_id and cut_status.get("journal_size") == 3, f"{case_name} did not establish a paused v1 cut")
    source_created_at = cut_status.get("created_at")

    cut_journal = object_value(json_value(root, "cut-journal.json"), f"{case_name} cut journal")
    require(cut_journal == json_value(root, "cut-journal-after-window.json"), f"{case_name} journal changed at cut")
    cut_rows = list_value(cut_journal.get("rows"), f"{case_name} cut journal rows")
    require([(row.get("index"), row.get("entry_type"), row.get("name"), row.get("completed")) for row in cut_rows] == [
        (0, "Command: Input", "", False), (1, "Command: SetState", "", False), (2, "Command: Run", "payment", False)
    ], f"{case_name} cut is not the unresolved payment Run")
    cut_workflow = json_value(root, "cut-workflow-state.json")
    require(cut_workflow == json_value(root, "cut-workflow-state-after-window.json"), f"{case_name} workflow state changed at cut")
    cut_workflow_row = one_row(cut_workflow, f"{case_name} cut workflow state")
    require(cut_workflow_row.get("service_key") == order_id and cut_workflow_row.get("key") == "status" and cut_workflow_row.get("value_utf8") == '"CREATED"', f"{case_name} cut workflow position differs")
    require(read(root, "post-cut-command.log") == EXPECTED_COMMANDS, f"{case_name} post-cut command sequence differs")

    before_crash = list_value(json_value(root, "source-container-before-crash.json"), f"{case_name} source before crash")
    retained = list_value(json_value(root, "source-container-retained.json"), f"{case_name} retained source")
    require(len(before_crash) == len(retained) == 1, f"{case_name} source container identity is ambiguous")
    require(
        before_crash[0].get("Id") == retained[0].get("Id")
        and before_crash[0].get("Image") == build["NATIVE_ORDER_V1_IMAGE"]
        and retained[0].get("Image") == build["NATIVE_ORDER_V1_IMAGE"]
        and retained[0].get("State", {}).get("Running") is True,
        f"{case_name} did not restart and retain v1",
    )
    require(read(root, "source-worker-crash.txt").strip().decode() == before_crash[0].get("Id"), f"{case_name} crash evidence differs")

    payment_at_cut = stats(json_value(root, "payment-at-cut.json"), f"{case_name} cut payment stats")
    require(payment_at_cut == stats(json_value(root, "payment-after-cut-window.json"), f"{case_name} stable cut payment stats"), f"{case_name} payment changed during cut")
    expected_cut = {"deliveries": 1, "commits": 0 if case_name == "h0" else 1, "paths": {"/v1/charge": 1}}
    require(payment_at_cut == expected_cut, f"{case_name} external fact at cut differs")
    require(stats(json_value(root, "completion-at-cut.json"), f"{case_name} cut completion stats") == {"deliveries": 0, "commits": 0, "paths": {}}, f"{case_name} completion existed at cut")
    try:
        cut_payment_records = BASE._records(root / "payment-at-cut.history", f"{case_name} cut payment records")
        cut_completion_records = BASE._records(root / "completion-at-cut.history", f"{case_name} cut completion records")
        final_payment_records = BASE._records(root / "payment.history", f"{case_name} final payment records")
        final_completion_records = BASE._records(root / "completion.history", f"{case_name} final completion records")
    except BASE.EvidenceError as error:
        raise EvidenceError(str(error)) from error
    require(len(cut_payment_records) == expected_cut["commits"] and cut_completion_records == [], f"{case_name} cut provider records differ")

    log = read(root, "source-v1-before-crash.log").decode(errors="replace")
    token_match = re.findall(rf"\[{re.escape(order_id)}\] Executing payment with token ([0-9a-f-]+) for \$42", log)
    require(len(token_match) == 1, f"{case_name} stable payment token is absent")
    token = token_match[0]
    operation_id = BASE._operation_id("restate-order-workflow", token)
    request_body = json.dumps({"order_id": order_id, "amount": 42}, separators=(",", ":")).encode()
    for record in cut_payment_records:
        require(record["operation_id"] == operation_id and record["request_hash"] == BASE._provider_hash("/v1/charge", request_body) and record["path"] == "/v1/charge", f"{case_name} cut payment record differs")

    final_payment = stats(json_value(root, "final-payment-stats.json"), f"{case_name} final payment stats")
    final_completion = stats(json_value(root, "final-completion-stats.json"), f"{case_name} final completion stats")
    require(final_payment["commits"] == len(final_payment_records) and final_completion["commits"] == len(final_completion_records), f"{case_name} provider stats and fsynced records differ")
    require(final_payment["deliveries"] >= payment_at_cut["deliveries"] and final_payment["commits"] >= payment_at_cut["commits"], f"{case_name} final payment regressed")
    require(final_completion["paths"] in ({}, {"/v1/complete": final_completion["deliveries"]}), f"{case_name} completion path differs")
    for index, record in enumerate(final_payment_records, 1):
        expected_result = sha256(f"charged\0{operation_id}\0{index}".encode()).hexdigest()
        require(record == {
            "operation_id": operation_id,
            "request_hash": BASE._provider_hash("/v1/charge", request_body),
            "result_hash": expected_result,
            "remote_reference": f"payment/{operation_id}/commit-{index}",
            "path": "/v1/charge",
        }, f"{case_name} final payment record {index} differs")
    completion_operation_id = BASE._operation_id("restate-order-workflow", f"order/{order_id}/completion")
    completion_body = json.dumps({"order_id": order_id, "status": "DELIVERED"}, separators=(",", ":")).encode()
    for record in final_completion_records:
        require(record["operation_id"] == completion_operation_id and record["request_hash"] == BASE._provider_hash("/v1/complete", completion_body) and record["path"] == "/v1/complete", f"{case_name} final completion record differs")

    services = container_services(root, build)
    final_source = list_value(json_value(root, "final-source-container.json"), f"{case_name} final source")
    final_target = list_value(json_value(root, "final-target-container.json"), f"{case_name} final target")
    require(len(final_source) == len(final_target) == 1 and final_source[0].get("Id") == services["order-v1"].get("Id") and final_target[0].get("Id") == services["order-v2"].get("Id"), f"{case_name} specific container evidence differs")

    final_invocation = one_row(json_value(root, "final-invocations.json"), f"{case_name} final invocation set")
    final_status = one_row(json_value(root, "final-status.json"), f"{case_name} final status")
    require(final_invocation.get("id") == invocation_id and final_status.get("id") == invocation_id and final_invocation.get("created_at") == source_created_at and final_status.get("created_at") == source_created_at, f"{case_name} created another invocation generation")
    final_journal = object_value(json_value(root, "final-journal.json"), f"{case_name} final journal")
    final_rows = list_value(final_journal.get("rows"), f"{case_name} final journal rows")
    require(len(final_rows) >= len(cut_rows) and final_rows[:len(cut_rows)] == cut_rows, f"{case_name} final journal rewrote the cut")
    final_workflow = object_value(json_value(root, "final-workflow-state.json"), f"{case_name} final workflow state")
    status_rows = [item for item in list_value(final_workflow.get("rows"), f"{case_name} final workflow rows") if item.get("key") == "status"]
    require(len(status_rows) == 1, f"{case_name} final business status is absent")
    order_status = status_rows[0].get("value_utf8")
    require(isinstance(order_status, str), f"{case_name} final business status differs")

    resume_exit_data = read(root, "resume-exit-status.txt")
    require(re.fullmatch(rb"[0-9]+\n", resume_exit_data) is not None, f"{case_name} resume exit status differs")
    resume_exit = int(resume_exit_data)
    repin_accepted = resume_exit == 0 and final_status.get("pinned_deployment_id") == v2_id
    target_attempted = final_status.get("last_attempt_deployment_id") == v2_id
    mismatch_count = read(root, "final-v2.log").count(b"Found a mismatch between the code paths")
    completed = final_status.get("status") == "completed" and order_status == '"DELIVERED"'
    requirements_met = completed and final_payment["commits"] >= 1 and final_completion["commits"] >= 1
    replay = "completed" if completed else "code-path-mismatch" if mismatch_count else str(final_status.get("status"))

    required_files = [
        "build.env", "order.json", "source-submit.json", "deployment-v1.json", "deployment-v2.json",
        "deployments.json", "cut-status.json", "cut-status-after-window.json", "cut-journal.json",
        "cut-journal-after-window.json", "cut-workflow-state.json", "cut-workflow-state-after-window.json",
        "post-cut-command.log", "source-container-before-crash.json", "source-container-retained.json",
        "source-worker-crash.txt", "payment-at-cut.json", "payment-after-cut-window.json",
        "completion-at-cut.json", "payment-at-cut.history", "completion-at-cut.history",
        "source-v1-before-crash.log", "final-payment-stats.json", "final-completion-stats.json",
        "payment.history", "completion.history", "containers.raw.json", "final-source-container.json",
        "final-target-container.json", "final-invocations.json", "final-status.json", "final-journal.json",
        "final-workflow-state.json", "resume-exit-status.txt", "resume.stdout", "resume.stderr", "final-v2.log",
    ]
    artifact_hashes = {name: sha256(read(root, name)).hexdigest() for name in required_files}
    evidence_digest = sha256(json.dumps(artifact_hashes, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        "case": case_name, "order_id": order_id, "invocation_id": invocation_id,
        "payment_token": token, "payment_operation_id": operation_id,
        "cut_status": normalize_status(cut_status), "cut_journal": cut_journal,
        "cut_workflow": cut_workflow, "repin": "accepted" if repin_accepted else "rejected",
        "target_attempted": target_attempted, "replay": replay,
        "runtime_status": final_status.get("status"), "business_status": order_status,
        "mismatch_count": mismatch_count, "payment": final_payment, "completion": final_completion,
        "requirements_met": requirements_met,
        "delivered_without_payment": completed and final_payment["commits"] == 0,
        "duplicate_payment": final_payment["commits"] > 1,
        "old_worker_retained": True, "evidence_digest": evidence_digest,
    }


def analyze(h0_root: Path, h1_root: Path) -> dict[str, Any]:
    h0_root, h1_root = h0_root.resolve(strict=True), h1_root.resolve(strict=True)
    build_h0, build_h1 = read(h0_root, "build.env"), read(h1_root, "build.env")
    require(build_h0 == build_h1, "H0/H1 use different builds")
    h0, h1 = check_case(h0_root, "h0", build_h0), check_case(h1_root, "h1", build_h1)
    require(read(h0_root, "order.json") == read(h1_root, "order.json"), "H0/H1 order bytes differ")
    require(h0["order_id"] == h1["order_id"] and h0["invocation_id"] == h1["invocation_id"], "H0/H1 logical invocation identity differs")
    require(h0["payment_token"] == h1["payment_token"] and h0["payment_operation_id"] == h1["payment_operation_id"], "H0/H1 payment identity differs")
    require(h0["cut_status"] == h1["cut_status"], "H0/H1 normalized Restate status differs at cut")
    require(h0["cut_journal"] == h1["cut_journal"], "H0/H1 Restate journal differs at cut")
    require(h0["cut_workflow"] == h1["cut_workflow"], "H0/H1 workflow state differs at cut")
    require(read(h0_root, "post-cut-command.log") == read(h1_root, "post-cut-command.log"), "H0/H1 post-cut commands differ")
    require(h0["payment"]["commits"] >= 0 and h1["payment"]["commits"] >= 1, "H0/H1 durable fact boundary disappeared")
    for item in (h0, h1):
        item.pop("cut_status")
        item.pop("cut_journal")
        item.pop("cut_workflow")
    return {
        "schema": 1, "valid": True, "method": "native-restate",
        "matched_cut": True, "post_cut_commands_equal": True,
        "only_intended_cut_difference": "durable-payment-fact",
        "h0": h0, "h1": h1,
    }


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--h0", required=True, type=Path, help="H0 results directory")
    value.add_argument("--h1", required=True, type=Path, help="H1 results directory")
    return value


def main() -> int:
    args = parser().parse_args()
    try:
        verdict = analyze(args.h0, args.h1)
    except (EvidenceError, BASE.EvidenceError, OSError) as error:
        print(f"analyze-native: {error}", file=sys.stderr)
        return 1
    print(json.dumps(verdict, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
