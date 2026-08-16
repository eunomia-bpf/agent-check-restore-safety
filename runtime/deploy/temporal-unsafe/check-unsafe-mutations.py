#!/usr/bin/env python3
"""Mutation-test the independent Temporal unsafe-edit evidence checker."""

from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Callable

import yaml


Mutation = Callable[[Path], None]


@dataclass(frozen=True)
class Case:
    name: str
    mutate: Mutation
    accept: bool = False


def read_json(path: Path) -> Any:
    return json.loads(path.read_bytes())


def write_bytes(path: Path, data: bytes) -> None:
    temporary = path.with_name(path.name + ".mutation-tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def write_json(path: Path, value: Any) -> None:
    write_bytes(path, json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n")


def json_mutation(name: str, change: Callable[[Any], None]) -> Mutation:
    def mutate(root: Path) -> None:
        path = root / name
        value = read_json(path)
        change(value)
        write_json(path, value)
    return mutate


def yaml_mutation(name: str, change: Callable[[Any], None]) -> Mutation:
    def mutate(root: Path) -> None:
        path = root / name
        value = yaml.safe_load(path.read_bytes())
        change(value)
        write_bytes(path, yaml.safe_dump(value, sort_keys=True).encode())
    return mutate


def jsonl_mutation(name: str, change: Callable[[list[Any]], None]) -> Mutation:
    def mutate(root: Path) -> None:
        path = root / name
        values = [json.loads(line) for line in path.read_bytes().splitlines()]
        change(values)
        write_bytes(
            path,
            b"".join(
                json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"
                for value in values
            ),
        )
    return mutate


def replace(name: str, old: bytes, new: bytes) -> Mutation:
    def mutate(root: Path) -> None:
        path = root / name
        data = path.read_bytes()
        if old not in data:
            raise RuntimeError(f"mutation source {old!r} absent from {name}")
        write_bytes(path, data.replace(old, new, 1))
    return mutate


def mutate_payload(history_name: str, event_index: int, field: str, value: Any) -> Mutation:
    def mutate(root: Path) -> None:
        path = root / history_name
        history = read_json(path)
        event = history["events"][event_index]
        attrs = next(item for key, item in event.items() if key.endswith("EventAttributes"))
        wrapper = attrs["input"]
        payload = wrapper["payloads"][0]
        decoded = json.loads(base64.b64decode(payload["data"], validate=True))
        decoded[field] = value
        payload["data"] = base64.b64encode(json.dumps(decoded, separators=(",", ":")).encode()).decode()
        write_json(path, history)
    return mutate


def mutate_activity_payload(history_name: str, activity: str, result: bool, field: str, value: Any) -> Mutation:
    def mutate(root: Path) -> None:
        path = root / history_name
        history = read_json(path)
        schedules = [
            event for event in history["events"]
            if event.get("eventType") == "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED"
            and event.get("activityTaskScheduledEventAttributes", {}).get("activityType", {}).get("name") == activity
        ]
        if len(schedules) != 1:
            raise RuntimeError(f"did not find exact {activity} schedule")
        if result:
            scheduled_id = schedules[0]["eventId"]
            matches = [
                event for event in history["events"]
                if event.get("eventType") == "EVENT_TYPE_ACTIVITY_TASK_COMPLETED"
                and event.get("activityTaskCompletedEventAttributes", {}).get("scheduledEventId") == scheduled_id
            ]
            if len(matches) != 1:
                raise RuntimeError(f"did not find exact {activity} completion")
            wrapper = matches[0]["activityTaskCompletedEventAttributes"]["result"]
        else:
            wrapper = schedules[0]["activityTaskScheduledEventAttributes"]["input"]
        payload = wrapper["payloads"][0]
        decoded = json.loads(base64.b64decode(payload["data"], validate=True))
        decoded[field] = value
        payload["data"] = base64.b64encode(json.dumps(decoded, separators=(",", ":")).encode()).decode()
        write_json(path, history)
    return mutate


def mutate_driver_signal(root: Path) -> None:
    path = root / "main-final-history.json"
    history = read_json(path)
    matches = [
        event for event in history["events"]
        if event.get("eventType") == "EVENT_TYPE_WORKFLOW_EXECUTION_SIGNALED"
        and event.get("workflowExecutionSignaledEventAttributes", {}).get("signalName") == "driver_selected"
    ]
    if len(matches) != 1:
        raise RuntimeError("did not find exact driver_selected Signal")
    payload = matches[0]["workflowExecutionSignaledEventAttributes"]["input"]["payloads"][0]
    decoded = json.loads(base64.b64decode(payload["data"], validate=True))
    decoded["delivery_id"] = "wrong-delivery"
    payload["data"] = base64.b64encode(json.dumps(decoded, separators=(",", ":")).encode()).decode()
    write_json(path, history)


def mutate_timer_timeout(root: Path) -> None:
    path = root / "main-final-history.json"
    history = read_json(path)
    matches = [
        event for event in history["events"]
        if event.get("eventType") == "EVENT_TYPE_TIMER_STARTED"
    ]
    if len(matches) != 1:
        raise RuntimeError("did not find exact preparation timer")
    matches[0]["timerStartedEventAttributes"]["startToFireTimeout"] = "0.026s"
    write_json(path, history)


def mutate_marker_version(root: Path) -> None:
    path = root / "clean-final-history.json"
    history = read_json(path)
    marker = history["events"][4]["markerRecordedEventAttributes"]
    marker["details"]["version"]["payloads"][0]["data"] = base64.b64encode(b"2").decode()
    write_json(path, history)


def mutate_change_version_upsert(root: Path) -> None:
    path = root / "clean-final-history.json"
    history = read_json(path)
    payload = history["events"][5]["upsertWorkflowSearchAttributesEventAttributes"]["searchAttributes"]["indexedFields"]["TemporalChangeVersion"]
    payload["data"] = base64.b64encode(b'["wrong-change-1"]').decode()
    write_json(path, history)


def mutate_sdk_language_flag(root: Path) -> None:
    path = root / "clean-final-history.json"
    history = read_json(path)
    matches = [
        event["workflowTaskCompletedEventAttributes"]["sdkMetadata"]
        for event in history["events"]
        if event.get("eventType") == "EVENT_TYPE_WORKFLOW_TASK_COMPLETED"
        and event.get("workflowTaskCompletedEventAttributes", {}).get("sdkMetadata", {}).get("langUsedFlags")
    ]
    if len(matches) != 1:
        raise RuntimeError("did not find exact clean SDK language flag set")
    matches[0]["langUsedFlags"][-1] = 9
    write_json(path, history)


def mutate_completion_closure(root: Path) -> None:
    path = root / "main-final-history.json"
    history = read_json(path)
    scheduled = [
        event for event in history["events"]
        if event.get("eventType") == "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED"
        and event.get("activityTaskScheduledEventAttributes", {}).get("activityType", {}).get("name") == "CompleteOrder"
    ][0]
    payload = scheduled["activityTaskScheduledEventAttributes"]["input"]["payloads"][0]
    decoded = json.loads(base64.b64decode(payload["data"], validate=True))
    decoded["closure_version"] = "tampered"
    payload["data"] = base64.b64encode(json.dumps(decoded, separators=(",", ":")).encode()).decode()
    write_json(path, history)


def mutate_provider_record(name: str, field: str, value: str) -> Mutation:
    def mutate(root: Path) -> None:
        path = root / name
        lines = path.read_bytes().splitlines()
        record = json.loads(lines[0])
        record[field] = value
        lines[0] = json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
        write_bytes(path, b"\n".join(lines) + b"\n")
    return mutate


def mutate_event_service(name: str, old: str, new: str) -> Mutation:
    def change(values: list[Any]) -> None:
        changed = 0
        for event in values:
            attrs = event.get("Actor", {}).get("Attributes", {})
            if attrs.get("com.docker.compose.service") == old and event.get("Action") in {"create", "start"}:
                attrs["com.docker.compose.service"] = new
                changed += 1
        if changed != 2:
            raise RuntimeError(f"did not find one create/start pair for {old}")
    return jsonl_mutation(name, change)


def mutate_event_time_relative(
    name: str, service: str, action: str, boundary: str, offset_ns: int,
) -> Mutation:
    def change(values: list[Any]) -> None:
        sentinels = [
            event for event in values
            if event.get("Action") == "create"
            and event.get("Actor", {}).get("Attributes", {}).get("io.safe-change.event-boundary") == boundary
        ]
        targets = [
            event for event in values
            if event.get("Action") == action
            and event.get("Actor", {}).get("Attributes", {}).get("com.docker.compose.service") == service
        ]
        if len(sentinels) != 1 or len(targets) != 1:
            raise RuntimeError(f"did not find exact {boundary} sentinel and {service}/{action}")
        time_ns = sentinels[0]["timeNano"] + offset_ns
        targets[0]["timeNano"] = time_ns
        targets[0]["time"] = time_ns // 1_000_000_000
    return jsonl_mutation(name, change)


def mutate_native_destroy_after_target_create(root: Path) -> None:
    path = root / "main-docker-events.jsonl"
    values = [json.loads(line) for line in path.read_bytes().splitlines()]
    source = [
        event for event in values
        if event.get("Action") == "destroy"
        and event.get("Actor", {}).get("Attributes", {}).get("com.docker.compose.service") == "worker-v1"
    ]
    target = [
        event for event in values
        if event.get("Action") == "create"
        and event.get("Actor", {}).get("Attributes", {}).get("com.docker.compose.service") == "worker-unsafe-v2"
    ]
    if len(source) != 1 or len(target) != 1:
        raise RuntimeError("did not find exact native source destroy and target create")
    time_ns = target[0]["timeNano"] + 1
    source[0]["timeNano"] = time_ns
    source[0]["time"] = time_ns // 1_000_000_000
    write_bytes(
        path,
        b"".join(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"
            for value in values
        ),
    )


def mutate_begin_sentinel_id_collision(root: Path) -> None:
    path = root / "main-docker-events.jsonl"
    values = [json.loads(line) for line in path.read_bytes().splitlines()]
    source = [
        event for event in values
        if event.get("Action") == "create"
        and event.get("Actor", {}).get("Attributes", {}).get("com.docker.compose.service") == "worker-v1"
    ]
    sentinels = [
        event for event in values
        if event.get("Actor", {}).get("Attributes", {}).get("io.safe-change.event-boundary") == "begin"
    ]
    if len(source) != 1 or len(sentinels) != 2:
        raise RuntimeError("did not find exact main source and begin sentinel lifecycle")
    collided = source[0]["Actor"]["ID"]
    for event in sentinels:
        event["Actor"]["ID"] = collided
        if "id" in event:
            event["id"] = collided
    write_bytes(
        path,
        b"".join(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"
            for value in values
        ),
    )
    write_bytes(root / "main-event-begin-sentinel-id.txt", (collided + "\n").encode())


def mutate_begin_sentinel_destroy_id(root: Path) -> None:
    def change(values: list[Any]) -> None:
        matches = [
            event for event in values
            if event.get("Action") == "destroy"
            and event.get("Actor", {}).get("Attributes", {}).get("io.safe-change.event-boundary") == "begin"
        ]
        if len(matches) != 1:
            raise RuntimeError("did not find exact begin sentinel destroy")
        matches[0]["Actor"]["ID"] = "0" * 64
        if "id" in matches[0]:
            matches[0]["id"] = "0" * 64
    jsonl_mutation("main-docker-events.jsonl", change)(root)


def duplicate_begin_sentinel_destroy(root: Path) -> None:
    def change(values: list[Any]) -> None:
        matches = [
            index for index, event in enumerate(values)
            if event.get("Action") == "destroy"
            and event.get("Actor", {}).get("Attributes", {}).get("io.safe-change.event-boundary") == "begin"
        ]
        if len(matches) != 1:
            raise RuntimeError("did not find exact begin sentinel destroy")
        index = matches[0]
        values.insert(index + 1, json.loads(json.dumps(values[index])))
    jsonl_mutation("main-docker-events.jsonl", change)(root)


def add_foreign_network_endpoint(root: Path) -> None:
    path = root / "main-networks.json"
    networks = read_json(path)
    endpoints = networks[0]["Containers"]
    endpoint = next(iter(endpoints.values()))
    endpoints["0" * 64] = endpoint
    write_json(path, networks)


def refresh_checksums(root: Path) -> None:
    files: list[Path] = []
    for path in root.rglob("*"):
        if path.is_symlink() or (not path.is_dir() and not path.is_file()):
            raise RuntimeError(f"unsafe mutation candidate entry: {path}")
        if path.is_file():
            files.append(path)
    build_root = root / "build-evidence"
    build_lines = []
    for path in sorted(
        (path for path in files if build_root in path.parents and path.name != "SHA256SUMS"),
        key=lambda item: item.relative_to(build_root).as_posix(),
    ):
        relative = path.relative_to(build_root).as_posix()
        build_lines.append(f"{sha256(path.read_bytes()).hexdigest()}  ./{relative}\n")
    write_bytes(build_root / "SHA256SUMS", "".join(build_lines).encode())
    files = [path for path in root.rglob("*") if path.is_file() and path != root / "SHA256SUMS"]
    lines = []
    for path in sorted(files, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        lines.append(f"{sha256(path.read_bytes()).hexdigest()}  ./{relative}\n")
    write_bytes(root / "SHA256SUMS", "".join(lines).encode())


def hardlink_copy(source: Path, destination: Path) -> None:
    destination.mkdir()
    for path in source.rglob("*"):
        if path.is_symlink() or (not path.is_dir() and not path.is_file()):
            raise RuntimeError(f"unsafe source entry: {path}")
        target = destination / path.relative_to(source)
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            os.link(path, target)


def checker_command(checker: Path, evidence: Path, runtime_root: Path) -> list[str]:
    return [sys.executable, str(checker), "--evidence", str(evidence), "--runtime-root", str(runtime_root)]


def cases(method: str) -> list[Case]:
    common = [
        Case("observed-is-not-oracle", json_mutation("observed.json", lambda value: value.update({"valid": False})), True),
        Case("target-capacity", json_mutation("requirement-target.json", lambda value: value["capacities"].update({"approval": 2}))),
        Case("target-finish-cost", json_mutation("requirement-target.json", lambda value: value["kinds"]["finish-v2"].update({"costs": {}}))),
        Case("source-requirement", json_mutation("requirement-source.json", lambda value: value.update({"id": "tampered"}))),
        Case("frozen-source-image", replace("build.env", b"WORKER_V1_ID=sha256:", b"WORKER_V1_ID=sha256:0")),
        Case("same-target-image", replace("build.env", b"NATIVE_UNSAFE_WORKER_ID=sha256:", b"NATIVE_UNSAFE_WORKER_ID=sha256:0")),
        Case("target-patch", replace("build-evidence/target/patches/0002-add-unsafe-worker-v2.patch", b"unsafe-v2", b"unsafe-x2")),
        Case("control-profile", replace("build-evidence/control/control-profile.env", b"CONTROL_PROFILE_SCHEMA=1", b"CONTROL_PROFILE_SCHEMA=2")),
        Case("control-source", replace("build-evidence/control/source/runtime/cmd/control/main.go", b"package main", b"package main\n// tampered")),
        Case("control-dockerfile", replace("build-evidence/control/Dockerfile.runtime", b"FROM ", b"FROM  ")),
        Case("source-adapter-config", replace("source-adapter.json", b'"kind": "charge-v1"', b'"kind": "charge-v2"')),
        Case("target-image-inspect", json_mutation("target-image-inspect.json", lambda value: value[0].update({"Id": "sha256:" + "0" * 64}))),
        Case("metadata-operation", json_mutation("run-metadata.json", lambda value: value["main"]["operation_ids"].update({"payment": "op-" + "0" * 64}))),
        Case("invocation-token", json_mutation("main-invocation.json", lambda value: value.update({"payment_token": "different-token"}))),
        Case("payment-token-contract", mutate_payload("main-cut-history.json", 0, "payment_token", "different-token")),
        Case("workflow-restaurant", mutate_payload("main-cut-history.json", 0, "restaurant_id", "wrong-restaurant")),
        Case("cut-activity-type", json_mutation("main-cut-history.json", lambda value: value["events"][4]["activityTaskScheduledEventAttributes"]["activityType"].update({"name": "ChargePaymentV2"}))),
        Case("unstable-cut", json_mutation("main-history-after-decision.json", lambda value: value["events"].pop())),
        Case("clean-version-marker", mutate_marker_version),
        Case("clean-change-version-upsert", mutate_change_version_upsert),
        Case("sdk-language-flag", mutate_sdk_language_flag),
        Case("completion-closure", mutate_completion_closure),
        Case("prepare-receipt", mutate_activity_payload("main-final-history.json", "PrepareFood", True, "restaurant_id", "wrong-restaurant")),
        Case("delivery-request", mutate_activity_payload("main-final-history.json", "ScheduleDelivery", False, "region", "wrong-region")),
        Case("driver-assignment-signal", mutate_driver_signal),
        Case("preparation-timer", mutate_timer_timeout),
        Case("final-stage-list", json_mutation("main-final-query.json", lambda value: value["queryResult"][0]["stages"].pop())),
        Case("provider-operation", mutate_provider_record("main-payment-cut.history", "operation_id", "op-" + "0" * 64)),
        Case("provider-request", mutate_provider_record("main-payment-final.history", "request_hash", "0" * 64)),
        Case("clean-payment-path", mutate_provider_record("clean-payment-final.history", "path", "/v1/charge")),
        Case("provider-count", json_mutation("main-payment-final-stats.json", lambda value: value.update({"commits": 2}))),
        Case("final-worker-build", json_mutation("main-final-describe.json", lambda value: value["workflowExecutionInfo"]["mostRecentWorkerVersionStamp"].update({"buildId": "wrong"}))),
        Case("resolved-compose-egress", yaml_mutation("main-compose-config.yaml", lambda value: value["networks"]["effects"].update({"internal": False}))),
        Case("actual-network-egress", json_mutation("main-networks.json", lambda value: value[0].update({"Internal": False}))),
        Case("foreign-network-endpoint", add_foreign_network_endpoint),
        Case("extra-container", json_mutation("main-containers.json", lambda value: value.append(value[0]))),
        Case("poller-build", json_mutation("main-source-workflow-pollers.json", lambda value: value["pollers"][0]["worker_version_capabilities"].update({"build_id": "wrong"}))),
        Case("deployment-current", json_mutation("main-deployment-final.json", lambda value: value["routingConfig"].update({"currentVersionBuildID": "wrong"}))),
        Case("missing-end-sentinel", jsonl_mutation("main-docker-events.jsonl", lambda values: values.pop(next(index for index, event in enumerate(values) if event.get("Action") == "create" and event.get("Actor", {}).get("Attributes", {}).get("io.safe-change.event-boundary") == "end")))),
        Case("base-worker-event", mutate_event_service("clean-docker-events.jsonl", "worker-unsafe-v2", "worker-v2")),
        Case("create-before-begin", mutate_event_time_relative("main-docker-events.jsonl", "payment", "create", "begin", -1)),
        Case("create-after-end", mutate_event_time_relative("clean-docker-events.jsonl", "worker-unsafe-v2", "create", "end", 1)),
        Case("sentinel-id-collision", mutate_begin_sentinel_id_collision),
        Case("sentinel-destroy-id", mutate_begin_sentinel_destroy_id),
        Case("missing-sentinel-destroy", jsonl_mutation("main-docker-events.jsonl", lambda values: values.pop(next(index for index, event in enumerate(values) if event.get("Action") == "destroy" and event.get("Actor", {}).get("Attributes", {}).get("io.safe-change.event-boundary") == "begin")))),
        Case("duplicate-sentinel-destroy", duplicate_begin_sentinel_destroy),
    ]
    if method == "proposed":
        common.extend([
            Case("clean-control-not-target", json_mutation("clean-final-control-state.json", lambda value: value["requirement"].update({"id": "tampered"}))),
            Case("clean-control-operation", json_mutation("clean-final-control-state.json", lambda value: next(iter(value["operations"].values())).update({"request_hash": "0" * 64}))),
            Case("unsafe-certificate", json_mutation("main-certificate-unsafe.json", lambda value: value.update({"decision": "activate"}))),
            Case("unsafe-witness", json_mutation("main-certificate-unsafe.json", lambda value: value["witness"].update({"reason": "tampered"}))),
            Case("refusal-mutates-state", json_mutation("main-control-after-refusal.json", lambda value: value["rule"].update({"allow": ["charge-v2"]}))),
            Case("refusal-mutates-history", json_mutation("main-control-history-after-refusal.json", lambda value: value.pop())),
            Case("target-started", mutate_event_service("main-docker-events.jsonl", "worker-v1", "worker-unsafe-v2")),
            Case("target-absence-record", json_mutation("main-proposed-target-absence.json", lambda value: value["target_container_ids"].append("0" * 64))),
            Case("source-finish-kind", json_mutation("main-final-control-state.json", lambda value: next(item for item in value["operations"].values() if item["kind"] == "finish-v1").update({"kind": "finish-v2"}))),
        ])
    else:
        common.extend([
            Case("source-not-removed", replace("main-source-removed-inspect-status.txt", b"1\n", b"0\n")),
            Case("native-source-destroy-after-target-create", mutate_native_destroy_after_target_create),
            Case("target-container-image", json_mutation("main-target-container.json", lambda value: value[0].update({"Image": "sha256:" + "0" * 64}))),
            Case("native-added-control", yaml_mutation("main-compose-config.yaml", lambda value: value["services"].update({"unsafe-control": value["services"]["temporal"]}))),
            Case("native-new-charge", json_mutation("main-payment-final-stats.json", lambda value: value.update({"deliveries": 2, "commits": 2}))),
            Case("native-target-event-missing", jsonl_mutation("main-docker-events.jsonl", lambda values: values.pop(next(index for index, event in enumerate(values) if event.get("Action") == "start" and event.get("Actor", {}).get("Attributes", {}).get("com.docker.compose.service") == "worker-unsafe-v2")))),
        ])
    return common


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--checker", type=Path, default=Path(__file__).with_name("check-unsafe.py"))
    parser.add_argument("--runtime-root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    evidence = args.evidence.resolve(strict=True)
    if (evidence / "results").is_dir() and not (evidence / "run-metadata.json").exists():
        evidence = (evidence / "results").resolve(strict=True)
    checker = args.checker.resolve(strict=True)
    runtime_root = args.runtime_root.resolve(strict=True)
    baseline = subprocess.run(checker_command(checker, evidence, runtime_root), capture_output=True, text=True, timeout=180)
    if baseline.returncode != 0:
        print(f"baseline checker failed: {baseline.stderr.strip()}", file=sys.stderr)
        return 1
    baseline_verdict = json.loads(baseline.stdout)
    method = baseline_verdict["method"]
    mutations = cases(method)
    verdicts: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="temporal-unsafe-mutations-") as temporary:
        temporary_root = Path(temporary)
        for index, case in enumerate(mutations):
            candidate = temporary_root / f"{index:02d}-{case.name}"
            hardlink_copy(evidence, candidate)
            case.mutate(candidate)
            refresh_checksums(candidate)
            completed = subprocess.run(checker_command(checker, candidate, runtime_root), capture_output=True, text=True, timeout=180)
            accepted = completed.returncode == 0
            if accepted != case.accept:
                print(f"mutation {case.name} accepted={accepted}, expected={case.accept}: {completed.stderr.strip()}", file=sys.stderr)
                return 1
            if case.accept:
                changed = json.loads(completed.stdout)
                if changed.get("evidence_digest") != baseline_verdict.get("evidence_digest"):
                    print("observed.json changed the scientific evidence digest", file=sys.stderr)
                    return 1
            verdicts.append({"name": case.name, "accepted": accepted, "expected_accept": case.accept})
            shutil.rmtree(candidate)
    return_value = {
        "schema": 1, "valid": True, "method": method,
        "baseline_evidence_digest": baseline_verdict["evidence_digest"],
        "mutation_count": len(verdicts),
        "rejected_count": sum(not item["accepted"] for item in verdicts),
        "positive_control_count": sum(item["accepted"] for item in verdicts),
        "mutations": verdicts,
    }
    print(json.dumps(return_value, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
