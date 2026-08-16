#!/usr/bin/env python3
"""Validate that proposed/native Temporal unsafe-edit runs are matched."""

from __future__ import annotations

import argparse
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys


SCRIPT_DIR = Path(__file__).resolve().parent
CHECK_PATH = SCRIPT_DIR / "check-unsafe.py"
SPEC = importlib.util.spec_from_file_location("temporal_unsafe_check", CHECK_PATH)
assert SPEC is not None and SPEC.loader is not None
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


def canonicalize_history(events: list[dict[str, object]]) -> list[dict[str, object]]:
    for index, event in enumerate(events):
        if event.get("eventType") != "EVENT_TYPE_WORKFLOW_TASK_COMPLETED":
            continue
        attrs = event.get("workflowTaskCompletedEventAttributes")
        if not isinstance(attrs, dict):
            continue
        sdk = attrs.get("sdkMetadata")
        if not isinstance(sdk, dict) or "langUsedFlags" not in sdk:
            continue
        flags = sdk["langUsedFlags"]
        CHECK.require(
            isinstance(flags, list)
            and all(type(flag) is int and flag in CHECK.SDK_LANGUAGE_FLAGS for flag in flags)
            and len(flags) == len(set(flags)),
            f"history event {index} SDK language flags differ",
        )
        # Temporal Go gathers these flags from a map, so their wire order is
        # nondeterministic.  The flag set, not map iteration order, is semantic.
        sdk["langUsedFlags"] = sorted(flags)
    return events


def canonical_history(root: Path, name: str, run_id: str) -> list[dict[str, object]]:
    return canonicalize_history(CHECK.history_events(CHECK.jvalue(root, name), run_id, name))


def semantic_food_order_trace(events: list[dict[str, object]]) -> dict[str, object]:
    """Project away only server/WFT batching while retaining business semantics.

    Four individually submitted Signals can legitimately be batched into a
    different number of Workflow Tasks.  Each lane's independent checker
    validates every Task and lineage; pair matching compares the immutable
    workload commands/results rather than treating server scheduling as part
    of the scientific treatment.
    """
    started = CHECK.event_attrs(events[0], "workflowExecutionStartedEventAttributes", "pair workflow start")
    activities: list[dict[str, object]] = []
    results: dict[str, dict[str, object]] = {}
    for event in events:
        event_type = event.get("eventType")
        if event_type == "EVENT_TYPE_ACTIVITY_TASK_COMPLETED":
            attrs = CHECK.event_attrs(event, "activityTaskCompletedEventAttributes", "pair Activity completion")
            scheduled = str(attrs.get("scheduledEventId"))
            results[scheduled] = CHECK.payload_json(attrs.get("result"), "pair Activity result")
    for event in events:
        if event.get("eventType") != "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED":
            continue
        attrs = CHECK.event_attrs(event, "activityTaskScheduledEventAttributes", "pair Activity schedule")
        scheduled = str(event.get("eventId"))
        CHECK.require(scheduled in results, "pair Activity has no completion")
        activities.append({
            "name": CHECK.obj(attrs.get("activityType"), "pair Activity type").get("name"),
            "input": CHECK.payload_json(attrs.get("input"), "pair Activity input"),
            "result": results[scheduled],
            "start_to_close_timeout": attrs.get("startToCloseTimeout"),
            "retry_policy": attrs.get("retryPolicy"),
        })
    timers = [
        CHECK.event_attrs(event, "timerStartedEventAttributes", "pair timer start").get("startToFireTimeout")
        for event in events if event.get("eventType") == "EVENT_TYPE_TIMER_STARTED"
    ]
    signals: list[dict[str, object]] = []
    for event in events:
        if event.get("eventType") != "EVENT_TYPE_WORKFLOW_EXECUTION_SIGNALED":
            continue
        attrs = CHECK.event_attrs(event, "workflowExecutionSignaledEventAttributes", "pair Signal")
        name = str(attrs.get("signalName"))
        value = CHECK.payload_json(attrs.get("input"), "pair Signal input") if name == "driver_selected" else attrs.get("input")
        signals.append({"name": name, "identity": attrs.get("identity"), "input": value})
    completed = CHECK.event_attrs(events[-1], "workflowExecutionCompletedEventAttributes", "pair workflow completion")
    return {
        "input": CHECK.payload_json(started.get("input"), "pair workflow input"),
        "activities": activities,
        "timers": timers,
        "signals": signals,
        "result": CHECK.payload_json(completed.get("result"), "pair workflow result"),
    }


def check_pair(proposed_path: Path, native_path: Path, runtime_root: Path) -> dict[str, object]:
    proposed_root = CHECK.evidence_root(proposed_path)
    native_root = CHECK.evidence_root(native_path)
    proposed = CHECK.check(proposed_root, runtime_root)
    native = CHECK.check(native_root, runtime_root)
    CHECK.require(proposed["method"] == "proposed" and native["method"] == "native", "pair lane identities differ")

    proposed_metadata = CHECK.jobject(proposed_root, "run-metadata.json")
    native_metadata = CHECK.jobject(native_root, "run-metadata.json")
    for key in ("clean_order_id", "main_order_id", "clean_workflow_id", "main_workflow_id"):
        CHECK.require(proposed_metadata.get(key) == native_metadata.get(key), f"pair workload identity differs: {key}")
    for name in (
        "requirement-source.json", "requirement-target.json", "source-adapter.json",
        "target-adapter.json", "frozen-inputs.env", "versions.env",
        "compose-base.yaml", "binary-verification.env",
        "build-evidence/SHA256SUMS",
    ):
        CHECK.require(CHECK.read(proposed_root, name) == CHECK.read(native_root, name), f"pair archived input differs: {name}")
    proposed_build_bytes = CHECK.read(proposed_root, "build.env")
    native_build_bytes = CHECK.read(native_root, "build.env")
    CHECK.require(proposed_build_bytes == native_build_bytes, "pair immutable build.env bytes differ")
    build = CHECK.parse_env(proposed_build_bytes, "pair build.env")
    CHECK.require(build["PROPOSED_UNSAFE_WORKER_ID"] == build["NATIVE_UNSAFE_WORKER_ID"], "pair target image ID differs")
    CHECK.require(proposed["payment_operation_id"] == native["payment_operation_id"], "pair payment Operation identity differs")
    CHECK.require(proposed["completion_operation_id"] == native["completion_operation_id"], "pair completion Operation identity differs")
    CHECK.require(CHECK.read(proposed_root, "main-payment-cut.history") == CHECK.read(native_root, "main-payment-cut.history"), "pair provider fact at the cut differs")
    CHECK.require(CHECK.read(proposed_root, "main-completion-cut.history") == CHECK.read(native_root, "main-completion-cut.history") == b"", "pair completed before the decision")
    CHECK.require(CHECK.read(proposed_root, "clean-payment-final.history") == CHECK.read(native_root, "clean-payment-final.history"), "pair clean payment fact differs")
    CHECK.require(CHECK.read(proposed_root, "clean-completion-final.history") == CHECK.read(native_root, "clean-completion-final.history"), "pair clean completion fact differs")
    CHECK.require(proposed["substantive_cut_digest"] == native["substantive_cut_digest"], "pair substantive Temporal cut differs")

    proposed_main_run = CHECK.read(proposed_root, "main-run-id.txt").decode().strip()
    native_main_run = CHECK.read(native_root, "main-run-id.txt").decode().strip()

    proposed_clean_run = CHECK.read(proposed_root, "clean-run-id.txt").decode().strip()
    native_clean_run = CHECK.read(native_root, "clean-run-id.txt").decode().strip()
    CHECK.require(
        len({proposed_clean_run, native_clean_run, proposed_main_run, native_main_run}) == 4,
        "pair reused a Temporal run ID",
    )
    proposed_clean = canonical_history(proposed_root, "clean-final-history.json", proposed_clean_run)
    native_clean = canonical_history(native_root, "clean-final-history.json", native_clean_run)
    CHECK.require(
        semantic_food_order_trace(proposed_clean) == semantic_food_order_trace(native_clean),
        "pair clean executions of the exact target differ semantically",
    )
    proposed_cut = canonical_history(proposed_root, "main-cut-history.json", proposed_main_run)
    native_cut = canonical_history(native_root, "main-cut-history.json", native_main_run)
    CHECK.require(proposed_cut == native_cut, "pair Temporal decision cuts differ")
    CHECK.require(
        proposed["clean_target_completed"] is True and native["clean_target_completed"] is True,
        "one clean target feasibility control did not complete",
    )
    CHECK.require(
        proposed["main_decision"] == "impossible" and proposed["target_started"] is False
        and proposed["source_completed"] is True,
        "proposed lane did not refuse before target start and retain source",
    )
    CHECK.require(
        native["main_decision"] == "native-completed" and native["target_started"] is True
        and native["external_requirement_violated"] is True,
        "native lane did not expose the external Requirement overuse",
    )

    payload = {
        "proposed_digest": proposed["evidence_digest"],
        "native_digest": native["evidence_digest"],
        "target_image": build["TEMPORAL_UNSAFE_WORKER_ID"],
        "target_binary": build["TEMPORAL_UNSAFE_WORKER_BINARY_SHA256"],
        "substantive_cut": proposed["substantive_cut_digest"],
        "payment_operation_id": proposed["payment_operation_id"],
        "completion_operation_id": proposed["completion_operation_id"],
    }
    return {
        "schema": 1, "valid": True, "cell": CHECK.CELL,
        "matched_workload": True, "same_source_image": True, "same_target_image": True,
        "same_target_binary": True, "same_substantive_cut": True,
        "clean_target_completed_both": True,
        "clean_order_id": proposed_metadata["clean_order_id"],
        "main_order_id": proposed_metadata["main_order_id"],
        "main_payment_operation_id": proposed["payment_operation_id"],
        "main_completion_operation_id": proposed["completion_operation_id"],
        "proposed_decision": "impossible", "proposed_target_started": False,
        "native_runtime_status": "completed", "native_approval_used": 2,
        "native_approval_capacity": 1,
        "pair_digest": sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proposed", required=True, type=Path)
    parser.add_argument("--native", required=True, type=Path)
    parser.add_argument("--runtime-root", type=Path, default=CHECK.RUNTIME_ROOT)
    args = parser.parse_args()
    try:
        verdict = check_pair(args.proposed, args.native, args.runtime_root.resolve(strict=True))
    except (CHECK.EvidenceError, OSError, CHECK.subprocess.SubprocessError) as error:
        print(f"check-unsafe-pair: {error}", file=sys.stderr)
        return 1
    print(json.dumps(verdict, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
