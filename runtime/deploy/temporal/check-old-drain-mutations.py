#!/usr/bin/env python3
"""Require the Temporal old-drain checker to reject decisive semantic mutations."""

from __future__ import annotations

import argparse
import base64
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
from typing import Any, Callable


CHECK_PATH = Path(__file__).with_name("check-old-drain.py")
SPEC = importlib.util.spec_from_file_location("temporal_old_drain_check", CHECK_PATH)
assert SPEC is not None and SPEC.loader is not None
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


def load_json(root: Path, name: str) -> Any:
    return json.loads((root / name).read_bytes())


def write_json(root: Path, name: str, value: Any) -> None:
    (root / name).write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")


def rehash(root: Path) -> None:
    lines = []
    for path in sorted(root.iterdir()):
        if path.name == "SHA256SUMS":
            continue
        lines.append(f"{sha256(path.read_bytes()).hexdigest()}  ./{path.name}\n")
    (root / "SHA256SUMS").write_text("".join(lines))


def service(root: Path, name: str, service_name: str) -> tuple[list[Any], dict[str, Any]]:
    values = load_json(root, name)
    item = next(
        value for value in values
        if value.get("Config", {}).get("Labels", {}).get("com.docker.compose.service") == service_name
    )
    return values, item


def mutate_exit_status(root: Path, _case: str) -> None:
    (root / "exit-status.txt").write_text("1\n")


def mutate_build(root: Path, _case: str) -> None:
    path = root / "build.env"
    path.write_text(path.read_text().replace(CHECK.V1_BINARY_SHA256, "0" * 64))


def mutate_source(root: Path, _case: str) -> None:
    path = root / "source-variant-v1.go"
    path.write_bytes(path.read_bytes() + b"\n// invented mutation\n")


def mutate_proxy_manifest(root: Path, _case: str) -> None:
    value = load_json(root, "toxiproxy-image-inspect.json")
    value[0]["RepoDigests"] = ["ghcr.io/shopify/toxiproxy@sha256:" + "0" * 64]
    write_json(root, "toxiproxy-image-inspect.json", value)


def mutate_provider_hold(root: Path, _case: str) -> None:
    values, item = service(root, "containers-final.json", "payment")
    command = item["Config"]["Cmd"]
    command[command.index("-hold-before-commit=false")] = "-hold-before-commit=true"
    write_json(root, "containers-final.json", values)


def mutate_worker_route(root: Path, _case: str) -> None:
    values, item = service(root, "containers-final.json", "worker-v1")
    environment = item["Config"]["Env"]
    environment[environment.index(f"PAYMENT_URL=http://payment-proxy:{CHECK.TOXIPROXY_PORT}")] = \
        "PAYMENT_URL=http://payment:8081"
    write_json(root, "containers-final.json", values)


def mutate_toxic_stream(root: Path, case: str) -> None:
    value = load_json(root, "toxic-create-request.json")
    value["stream"] = "downstream" if case == "h0" else "upstream"
    write_json(root, "toxic-create-request.json", value)


def mutate_toxic_type(root: Path, _case: str) -> None:
    value = load_json(root, "toxic-create-response.json")
    value["type"] = "timeout"
    write_json(root, "toxic-create-response.json", value)


def mutate_toxic_latency(root: Path, _case: str) -> None:
    value = load_json(root, "proxy-at-cut.json")
    value["toxics"][0]["attributes"]["latency"] = 1
    write_json(root, "proxy-at-cut.json", value)


def mutate_proxy_upstream(root: Path, _case: str) -> None:
    value = load_json(root, "proxy-create-request.json")
    value["upstream"] = "completion:8081"
    write_json(root, "proxy-create-request.json", value)


def mutate_delete_status(root: Path, _case: str) -> None:
    (root / "toxic-delete-status.txt").write_text("200\n")


def mutate_delete_body(root: Path, _case: str) -> None:
    (root / "toxic-delete-body.txt").write_text("invented\n")


def mutate_toxic_retained(root: Path, case: str) -> None:
    value = load_json(root, "proxy-after-release.json")
    value["toxics"] = [load_json(root, "proxy-at-cut.json")["toxics"][0]]
    write_json(root, "proxy-after-release.json", value)


def mutate_release_chronology(root: Path, _case: str) -> None:
    cut = int((root / "cut-epoch-ns.txt").read_text().strip())
    (root / "release-requested-epoch-ns.txt").write_text(f"{cut - 1}\n")


def mutate_cut_history_identity(root: Path, _case: str) -> None:
    for name in ("cut-history-before.json", "cut-history-after.json"):
        value = load_json(root, name)
        value["events"][2]["workflowTaskStartedEventAttributes"]["identity"] = "invented-worker"
        write_json(root, name, value)


def mutate_cut_pending_state(root: Path, _case: str) -> None:
    value = load_json(root, "cut-describe.json")
    value["pendingActivities"][0]["state"] = "PENDING_ACTIVITY_STATE_SCHEDULED"
    write_json(root, "cut-describe.json", value)


def mutate_cut_commit(root: Path, case: str) -> None:
    value = load_json(root, "payment-cut-stats.json")
    if case == "h0":
        value = {"deliveries": 1, "commits": 1, "paths": {"/v1/charge": 1}}
    else:
        value = {"deliveries": 0, "commits": 0, "paths": {}}
    write_json(root, "payment-cut-stats.json", value)


def mutate_payment_redispatch(root: Path, _case: str) -> None:
    value = load_json(root, "payment-final-stats.json")
    value.update({"deliveries": 2, "commits": 2, "paths": {"/v1/charge": 2}})
    write_json(root, "payment-final-stats.json", value)


def mutate_payment_record(root: Path, _case: str) -> None:
    path = root / "payment-final.history"
    path.write_bytes(path.read_bytes() * 2)


def mutate_payment_receipt(root: Path, _case: str) -> None:
    for name in ("settled-history.json", "final-history.json"):
        value = load_json(root, name)
        payload = value["events"][6]["activityTaskCompletedEventAttributes"]["result"]["payloads"][0]
        receipt = json.loads(base64.b64decode(payload["data"]))
        receipt["result_hash"] = "0" * 64
        payload["data"] = base64.b64encode(json.dumps(receipt, separators=(",", ":")).encode()).decode()
        write_json(root, name, value)


def mutate_completion_input(root: Path, _case: str) -> None:
    value = load_json(root, "final-history.json")
    scheduled = next(
        event for event in value["events"]
        if event.get("eventType") == "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED" and
        event.get("activityTaskScheduledEventAttributes", {}).get("activityType", {}).get("name") == "CompleteOrder"
    )
    payload = scheduled["activityTaskScheduledEventAttributes"]["input"]["payloads"][0]
    body = json.loads(base64.b64decode(payload["data"]))
    body["closure_version"] = "invented-v2"
    payload["data"] = base64.b64encode(json.dumps(body, separators=(",", ":")).encode()).decode()
    write_json(root, "final-history.json", value)


def mutate_final_identity(root: Path, _case: str) -> None:
    value = load_json(root, "final-history.json")
    scheduled = next(
        event for event in value["events"]
        if event.get("eventType") == "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED" and
        event.get("activityTaskScheduledEventAttributes", {}).get("activityType", {}).get("name") == "CompleteOrder"
    )
    completed = next(
        event for event in value["events"]
        if event.get("eventType") == "EVENT_TYPE_ACTIVITY_TASK_COMPLETED" and
        event.get("activityTaskCompletedEventAttributes", {}).get("scheduledEventId") == scheduled["eventId"]
    )
    completed["activityTaskCompletedEventAttributes"]["identity"] = "safe-change-food-order-v2-worker"
    write_json(root, "final-history.json", value)


def mutate_final_result(root: Path, _case: str) -> None:
    value = load_json(root, "final-history.json")
    terminal = next(
        event for event in value["events"]
        if event.get("eventType") == "EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED"
    )
    payload = terminal["workflowExecutionCompletedEventAttributes"]["result"]["payloads"][0]
    result = json.loads(base64.b64decode(payload["data"]))
    result["worker_build"] = "food-order-v2"
    payload["data"] = base64.b64encode(json.dumps(result, separators=(",", ":")).encode()).decode()
    write_json(root, "final-history.json", value)


def mutate_final_status(root: Path, _case: str) -> None:
    value = load_json(root, "final-describe.json")
    value["workflowExecutionInfo"]["status"] = "WORKFLOW_EXECUTION_STATUS_RUNNING"
    write_json(root, "final-describe.json", value)


def mutate_v1_stopped(root: Path, _case: str) -> None:
    value = load_json(root, "v1-final-inspect.json")
    value[0]["State"]["Running"] = False
    write_json(root, "v1-final-inspect.json", value)


def mutate_v1_replaced(root: Path, _case: str) -> None:
    values, item = service(root, "containers-final.json", "worker-v1")
    item["Id"] = "0" * 64
    write_json(root, "containers-final.json", values)


def mutate_v2_container(root: Path, _case: str) -> None:
    values, item = service(root, "containers-final.json", "worker-v1")
    target = json.loads(json.dumps(item))
    target["Id"] = "1" * 64
    target["Config"]["Labels"]["com.docker.compose.service"] = "worker-v2"
    values.append(target)
    write_json(root, "containers-final.json", values)


def mutate_v2_deployment(root: Path, _case: str) -> None:
    value = load_json(root, "deployment-final.json")
    target = json.loads(json.dumps(value["versionSummaries"][0]))
    target["BuildID"] = "food-order-v2"
    value["versionSummaries"].append(target)
    write_json(root, "deployment-final.json", value)


def mutate_v2_poller(root: Path, _case: str) -> None:
    value = load_json(root, "v1-final-activity-pollers.json")
    poller = value["pollers"][0]
    poller["identity"] = "safe-change-food-order-v2-worker"
    poller["worker_version_capabilities"]["build_id"] = "food-order-v2"
    write_json(root, "v1-final-activity-pollers.json", value)


def mutate_v2_event(root: Path, _case: str) -> None:
    events = [json.loads(line) for line in (root / "docker-events.jsonl").read_text().splitlines()]
    event = json.loads(json.dumps(next(item for item in events if item.get("Action") == "start")))
    event["Actor"]["Attributes"]["com.docker.compose.service"] = "worker-v2"
    events.append(event)
    (root / "docker-events.jsonl").write_text("".join(json.dumps(item, separators=(",", ":")) + "\n" for item in events))


def mutate_missing_v1_event(root: Path, _case: str) -> None:
    events = [json.loads(line) for line in (root / "docker-events.jsonl").read_text().splitlines()]
    events = [
        item for item in events
        if not (
            item.get("Action") == "start" and
            item.get("Actor", {}).get("Attributes", {}).get("com.docker.compose.service") == "worker-v1"
        )
    ]
    (root / "docker-events.jsonl").write_text("".join(json.dumps(item, separators=(",", ":")) + "\n" for item in events))


def mutate_duplicate_json_key(root: Path, _case: str) -> None:
    value = load_json(root, "start.json")
    (root / "start.json").write_text(
        '{"schema":1,"schema":1,"behavior":' + json.dumps(value["behavior"]) +
        ',"workflow_id":' + json.dumps(value["workflow_id"]) +
        ',"run_id":' + json.dumps(value["run_id"]) + '}\n'
    )


Mutation = Callable[[Path, str], None]
MUTATIONS: dict[str, Mutation] = {
    "nonzero runner exit": mutate_exit_status,
    "frozen build changed": mutate_build,
    "frozen source changed": mutate_source,
    "Toxiproxy manifest changed": mutate_proxy_manifest,
    "payment provider hold enabled": mutate_provider_hold,
    "worker bypassed proxy": mutate_worker_route,
    "toxic stream changed": mutate_toxic_stream,
    "toxic type changed": mutate_toxic_type,
    "toxic latency changed": mutate_toxic_latency,
    "proxy upstream changed": mutate_proxy_upstream,
    "DELETE status changed": mutate_delete_status,
    "DELETE body inserted": mutate_delete_body,
    "toxic remained after DELETE": mutate_toxic_retained,
    "release chronology changed": mutate_release_chronology,
    "cut worker identity changed": mutate_cut_history_identity,
    "cut pending state changed": mutate_cut_pending_state,
    "cut commit fact changed": mutate_cut_commit,
    "payment redispatched": mutate_payment_redispatch,
    "payment durable record duplicated": mutate_payment_record,
    "payment receipt changed": mutate_payment_receipt,
    "v2 closure marker inserted": mutate_completion_input,
    "final Activity moved to v2": mutate_final_identity,
    "final result moved to v2": mutate_final_result,
    "final status changed": mutate_final_status,
    "retained v1 stopped": mutate_v1_stopped,
    "retained v1 replaced": mutate_v1_replaced,
    "v2 container inserted": mutate_v2_container,
    "v2 deployment inserted": mutate_v2_deployment,
    "v2 poller inserted": mutate_v2_poller,
    "v2 Docker start inserted": mutate_v2_event,
    "v1 Docker start removed": mutate_missing_v1_event,
    "duplicate JSON key inserted": mutate_duplicate_json_key,
}


def replace_run_id(root: Path, old: str, new: str) -> None:
    old_bytes = old.encode()
    for path in root.iterdir():
        if path.name == "SHA256SUMS" or not path.is_file():
            continue
        data = path.read_bytes()
        if old_bytes in data:
            path.write_bytes(data.replace(old_bytes, new.encode()))


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--evidence", required=True, type=Path, help="old-drain case or results directory")
    value.add_argument("--case", required=True, choices=("h0", "h1"))
    value.add_argument("--peer", type=Path, help="optional opposite case for pair-specific mutations")
    return value


def main() -> int:
    args = parser().parse_args()
    source = CHECK.evidence_root(args.evidence)
    good = CHECK.check_evidence(source, args.case)
    rejected: list[str] = []
    with tempfile.TemporaryDirectory(prefix=f"temporal-old-drain-{args.case}-mutations.") as temporary:
        base = Path(temporary)
        for index, (name, mutate) in enumerate(MUTATIONS.items(), 1):
            candidate = base / f"mutation-{index:02d}"
            shutil.copytree(source, candidate)
            mutate(candidate, args.case)
            rehash(candidate)
            try:
                CHECK.check_evidence(candidate, args.case)
            except (CHECK.EvidenceError, OSError, UnicodeError, ValueError):
                rejected.append(name)
            else:
                raise SystemExit(f"checker accepted decisive mutation: {name}")

        ignored = base / "ignored-observed-json"
        shutil.copytree(source, ignored)
        (ignored / "observed.json").write_text("this derived summary is deliberately invalid\n")
        rehash(ignored)
        ignored_result = CHECK.check_evidence(ignored, args.case)
        if ignored_result != good:
            raise SystemExit("observed.json influenced the independent verdict")

        pair_rejected: list[str] = []
        if args.peer is not None:
            peer_source = CHECK.evidence_root(args.peer)
            pair_good = CHECK.check_pair(source, peer_source)
            if not pair_good["valid"]:
                raise SystemExit("positive pair control failed")
            first = base / "pair-first"
            second = base / "pair-second"
            shutil.copytree(source, first)
            shutil.copytree(peer_source, second)
            first_case = CHECK.check_evidence(first)["case"]
            h0_root, h1_root = (first, second) if first_case == "h0" else (second, first)
            h0_run = CHECK.check_evidence(h0_root)["run_id"]
            h1_run = CHECK.check_evidence(h1_root)["run_id"]
            replace_run_id(h1_root, h1_run, h0_run)
            rehash(h1_root)
            CHECK.check_evidence(h1_root, "h1")
            try:
                CHECK.check_pair(h0_root, h1_root)
            except CHECK.EvidenceError:
                pair_rejected.append("H0/H1 reused one Temporal run")
            else:
                raise SystemExit("pair checker accepted a reused Temporal run")
    print(json.dumps({
        "schema": 1, "valid": True, "case": args.case,
        "mutations": len(MUTATIONS), "rejected": rejected,
        "observed_json_ignored": True, "pair_mutations_rejected": pair_rejected,
    }, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
