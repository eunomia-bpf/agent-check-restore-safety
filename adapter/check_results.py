"""Independent result gate for the fixed C01--C20 runtime experiment.

This module is deliberately downstream of the run.  It is the only executable
component that joins controller output with the frozen oracle.  Neither the
controller nor its crash worker imports it.
"""

from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from adapter.observations import ProbeRecord, mixed_label_fibers
from adapter.oracle import assert_controller_oracle_separation, load_oracle
from adapter.replay import ReplayError, replay_bundle
from adapter.spec import load_litmus


POLICIES = ("P0", "P1", "P2", "P3")
EXPECTED_PROBE_PAIRS = {
    ("C02", "C04"),
    ("C13", "C14"),
    ("C16", "C18"),
}


class ResultFormatError(ValueError):
    """The run document is incomplete or structurally malformed."""


def _object(value: Any, description: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ResultFormatError(f"{description} must be an object")
    return value


def _list(value: Any, description: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ResultFormatError(f"{description} must be a list")
    return value


def _decision_map(run: Mapping[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for index, raw in enumerate(_list(run.get("decisions"), "run decisions")):
        decision = _object(raw, f"decision {index}")
        request = decision.get("request")
        verdict = decision.get("decision")
        if request is None:
            continue
        if not isinstance(request, str) or verdict not in {"accept", "reject"}:
            raise ResultFormatError("decision request/verdict is malformed")
        if request in result:
            raise ResultFormatError(f"duplicate decision for request {request}")
        result[request] = str(verdict)
    return result


def _sink_counts(run: Mapping[str, Any]) -> tuple[dict[str, int], list[Mapping[str, Any]]]:
    sink = _object(run.get("sink"), "run sink")
    snapshot = _object(sink.get("snapshot"), "sink snapshot")
    outcomes = [
        _object(value, "sink outcome")
        for value in _list(snapshot.get("outcomes"), "sink outcomes")
    ]
    counts = Counter(str(outcome.get("effect_id")) for outcome in outcomes)
    if "None" in counts:
        raise ResultFormatError("sink outcome omitted effect_id")
    return dict(counts), outcomes


def _p3_runs(document: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for raw in _list(document.get("runs"), "runs"):
        run = _object(raw, "run")
        if run.get("policy") == "P3":
            result[str(run.get("case_id"))] = run
    return result


def _prefix_state_before_request(
    run: Mapping[str, Any], request: str
) -> Mapping[str, Any]:
    previous: Mapping[str, Any] | None = None
    for raw_worker in _list(run.get("workers"), "run workers"):
        worker = _object(raw_worker, "worker record")
        payload = worker.get("payload")
        if not isinstance(payload, Mapping):
            continue
        decision = payload.get("decision")
        if isinstance(decision, Mapping) and decision.get("request") == request:
            if previous is None:
                raise ResultFormatError(f"no retained prefix before request {request}")
            return _object(
                _object(previous.get("controller_snapshot"), "prefix snapshot").get("state"),
                "prefix semantic state",
            )
        if isinstance(payload.get("controller_snapshot"), Mapping):
            previous = payload
    raise ResultFormatError(f"request {request} is absent from retained worker records")


def _actual_restore_mode(run: Mapping[str, Any]) -> str:
    controller = _object(run.get("controller"), "run controller")
    for raw_event in _list(controller.get("events"), "controller events"):
        event = _object(raw_event, "controller event")
        body = event.get("body")
        operation = body.get("operation") if isinstance(body, Mapping) else None
        if isinstance(operation, Mapping) and operation.get("request") == "restore_same_bytes":
            return str(operation.get("mode"))
    raise ResultFormatError("restore probe has no retained restore event")


def _derive_probes(
    document: Mapping[str, Any], suite: Sequence[Any], oracle: Mapping[str, Any]
) -> list[ProbeRecord]:
    """Derive observation prefixes from raw run evidence, never runner labels."""

    runs = _p3_runs(document)
    cases = {case.case_id: case for case in suite}
    # The exact byte hash is not security-relevant to grouping; all six probes
    # share one actual read-only workspace.  Use the suite digest already
    # retained by the run rather than a case/family marker.
    metadata = _object(document.get("metadata"), "metadata")
    suite_hash = metadata.get("suite_sha256")
    if not isinstance(suite_hash, str) or len(suite_hash) != 64:
        raise ResultFormatError("metadata omitted the retained suite SHA-256")

    def topology_provider(case_id: str) -> tuple[dict[str, Any], ...]:
        provider = _object(runs[case_id].get("provider"), "provider")
        event = next(
            _object(value, "topology event")
            for value in _list(provider.get("topology_events"), "topology events")
            if isinstance(value, Mapping) and value.get("operation") == "restore"
        )
        return (
            {
                "kind": "native_history_fork",
                "parent_history_id": event["parent_history_id"],
                "history_id": event["history_id"],
                "turn_id": event["turn_id"],
            },
        )

    def fork_provider(case_id: str) -> tuple[dict[str, Any], ...]:
        provider = _object(runs[case_id].get("provider"), "provider")
        events = [
            _object(value, "topology event")
            for value in _list(provider.get("topology_events"), "topology events")
            if isinstance(value, Mapping) and value.get("operation") == "fork"
        ]
        return tuple(
            {
                "kind": "native_history_fork",
                "parent_history_id": event["parent_history_id"],
                "history_id": event["history_id"],
                "turn_id": event["turn_id"],
            }
            for event in events
        )

    def pending_provider(case_id: str) -> tuple[dict[str, Any], ...]:
        provider = _object(runs[case_id].get("provider"), "provider")
        calls = _list(provider.get("tool_calls"), "provider tool calls")
        if len(calls) != 1:
            raise ResultFormatError(f"effect probe {case_id} requires one tool call")
        call = _object(calls[0], "provider tool call")
        return (
            {
                "kind": "tool_pending",
                "thread_id": call["thread_id"],
                "turn_id": call["turn_id"],
                "call_id": call["call_id"],
                "effect_id": call["effect_id"],
                "tool": call["tool"],
            },
        )

    probes: list[ProbeRecord] = []
    for case_id in ("C13", "C14"):
        mode = _actual_restore_mode(runs[case_id])
        prefix = _prefix_state_before_request(runs[case_id], "reserve_restored")
        probes.append(
            ProbeRecord(
                case_id=case_id,
                workspace={"bytes_sha256": suite_hash},
                provider_events=topology_provider(case_id),
                trusted_events=(
                    {
                        "kind": "restore",
                        "source": "root",
                        "target": "restored",
                        "mode": mode,
                        "frontier": prefix["frontier"],
                    },
                ),
                action={
                    "kind": "reserve",
                    "operation": "reserve",
                    "source_role": "restored_copy",
                    "branch_id": "restored",
                    "grant_id": "g",
                    "demand": 1,
                },
                oracle_decision=oracle[case_id].observation_probe.decision,
            )
        )

    for case_id in ("C16", "C18"):
        prefix = _prefix_state_before_request(runs[case_id], "reserve_c2")
        next_action = next(
            operation
            for operation in cases[case_id].operations
            if operation.get("request") == "reserve_c2"
        )
        grant_records = [
            {"grant_id": grant, "capacity": capacity}
            for grant, capacity in sorted(prefix["grants"].items())
        ]
        delegation_records = [
            {"grant_id": grant, "branch_id": branch}
            for grant, branches in sorted(prefix["delegations"].items())
            for branch in sorted(branches)
        ]
        claim_records = [
            {
                "claim_id": claim_id,
                "grant_id": claim["grant"],
                "owner_branch": claim.get("owner"),
                "demand": claim["demand"],
                "status": claim["status"],
            }
            for claim_id, claim in sorted(prefix["claims"].items())
        ]
        probes.append(
            ProbeRecord(
                case_id=case_id,
                workspace={"bytes_sha256": suite_hash},
                provider_events=fork_provider(case_id),
                trusted_events=(
                    {
                        "kind": "authority_lineage",
                        "grants": grant_records,
                        "delegations": delegation_records,
                        "claims": claim_records,
                    },
                ),
                action={
                    "kind": "reserve",
                    "operation": "reserve",
                    "source_role": "parallel_sibling",
                    "branch_id": "right",
                    "grant_id": str(next_action["grant"]),
                    "demand": int(next_action["demand"]),
                },
                oracle_decision=oracle[case_id].observation_probe.decision,
            )
        )

    for case_id in ("C02", "C04"):
        fault = _object(runs[case_id].get("fault"), "effect fault record")
        attempt_probe = _object(fault.get("attempt_probe"), "attempt admission probe")
        expected_probe = oracle[case_id].observation_probe
        if (
            attempt_probe.get("decision") != expected_probe.decision
            or attempt_probe.get("operation") not in {"dispatch", "retry"}
        ):
            raise ResultFormatError(
                f"{case_id} did not execute the frozen physical-attempt probe"
            )
        boundary = _object(fault.get("crash_boundary"), "crash boundary")
        controller = _object(boundary.get("controller"), "crash controller snapshot")
        state = _object(controller.get("state"), "crash semantic state")
        if "e1" in _object(state.get("receipts"), "crash receipts"):
            phase = "settled"
        else:
            ticket = _object(
                _object(state.get("tickets"), "crash tickets").get("e1"),
                "crash ticket e1",
            )
            phase = str(ticket.get("phase"))
        probes.append(
            ProbeRecord(
                case_id=case_id,
                workspace={"bytes_sha256": suite_hash},
                provider_events=pending_provider(case_id),
                trusted_events=(
                    {"kind": "effect_phase", "effect_id": "e1", "phase": phase},
                ),
                action={
                    "kind": "attempt",
                    "operation": "sink_attempt",
                    "effect_id": "e1",
                    "same_operation": True,
                },
                oracle_decision=expected_probe.decision,
            )
        )
    return probes


def _fiber_pairs(fibers: Sequence[Mapping[str, Any]]) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for fiber in fibers:
        cases = tuple(sorted(map(str, fiber.get("cases", ()))))
        if len(cases) == 2:
            pairs.add((cases[0], cases[1]))
    return pairs


def _check_raw_protocol(
    document: Mapping[str, Any], raw_jsonl_path: Path
) -> tuple[list[str], dict[str, Any]]:
    """Cross-check runner summaries against the independently retained JSONL."""

    failures: list[str] = []
    records: list[Mapping[str, Any]] = []
    digest = sha256()
    with raw_jsonl_path.open("rb") as source:
        for line_number, encoded in enumerate(source, start=1):
            digest.update(encoded)
            try:
                value = json.loads(encoded)
            except json.JSONDecodeError as error:
                raise ResultFormatError(
                    f"invalid raw App Server JSONL line {line_number}: {error}"
                ) from error
            records.append(_object(value, f"raw App Server record {line_number}"))

    expected_calls: Counter[tuple[str, str, str, str, str]] = Counter()
    expected_histories: set[str] = set()
    for raw_run in _list(document.get("runs"), "runs"):
        run = _object(raw_run, "run")
        provider = _object(run.get("provider"), "run provider")
        for raw_call in _list(provider.get("tool_calls"), "provider tool calls"):
            call = _object(raw_call, "provider tool call")
            expected_calls[
                (
                    str(call.get("thread_id")),
                    str(call.get("turn_id")),
                    str(call.get("call_id")),
                    str(call.get("tool")),
                    str(call.get("effect_id")),
                )
            ] += 1
        for raw_event in _list(provider.get("topology_events"), "topology events"):
            event = _object(raw_event, "topology event")
            history_id = event.get("history_id")
            if isinstance(history_id, str):
                expected_histories.add(history_id)

    actual_calls: Counter[tuple[str, str, str, str, str]] = Counter()
    callback_request_ids: set[int | str] = set()
    callback_response_ids: set[int | str] = set()
    started_histories: set[str] = set()
    fork_requests = 0
    for record in records:
        direction = record.get("direction")
        payload = record.get("payload")
        if not isinstance(payload, Mapping):
            continue
        method = payload.get("method")
        if direction == "server_to_client" and method == "item/tool/call":
            params = payload.get("params")
            if not isinstance(params, Mapping):
                failures.append("raw item/tool/call has malformed params")
                continue
            arguments = params.get("arguments")
            effect = arguments.get("effect_id") if isinstance(arguments, Mapping) else None
            actual_calls[
                (
                    str(params.get("threadId")),
                    str(params.get("turnId")),
                    str(params.get("callId")),
                    str(params.get("tool")),
                    str(effect),
                )
            ] += 1
            if "id" in payload:
                callback_request_ids.add(payload["id"])
        elif direction == "client_to_server" and "id" in payload and "result" in payload:
            callback_response_ids.add(payload["id"])
        elif direction == "client_to_server" and method == "thread/fork":
            fork_requests += 1
        elif direction == "server_to_client" and method == "thread/started":
            params = payload.get("params")
            thread = params.get("thread") if isinstance(params, Mapping) else None
            if isinstance(thread, Mapping) and isinstance(thread.get("id"), str):
                started_histories.add(str(thread["id"]))

    if actual_calls != expected_calls:
        failures.append(
            f"raw item/tool/call multiset differs from run summaries: "
            f"raw={sum(actual_calls.values())}, summaries={sum(expected_calls.values())}"
        )
    unanswered = callback_request_ids - callback_response_ids
    if unanswered:
        failures.append(f"raw protected callbacks lack responses: {sorted(map(str, unanswered))}")
    missing_histories = expected_histories - started_histories
    if missing_histories:
        failures.append(
            f"run summaries contain histories absent from raw thread/started: "
            f"{sorted(missing_histories)}"
        )
    if fork_requests != len(expected_histories):
        failures.append(
            f"raw native fork count {fork_requests} != summarized histories {len(expected_histories)}"
        )
    return failures, {
        "path": str(raw_jsonl_path),
        "sha256": digest.hexdigest(),
        "record_count": len(records),
        "item_tool_call_count": sum(actual_calls.values()),
        "answered_callback_count": len(callback_request_ids & callback_response_ids),
        "native_fork_count": fork_requests,
        "summarized_history_count": len(expected_histories),
    }


def _check_adapter_correspondence(
    runs: Mapping[tuple[str, str], Mapping[str, Any]], suite: Sequence[Any]
) -> tuple[list[str], dict[str, int]]:
    """Match every modeled provider edge to the executed declarative action."""

    failures: list[str] = []
    mapped_topology = 0
    mapped_dispatch = 0
    cases = {case.case_id: case for case in suite}
    for (case_id, policy), run in runs.items():
        case = cases[case_id]
        operations = [dict(value) for value in case.operations if value["op"] != "grant"]
        decisions = [
            _object(value, "decision")
            for value in _list(run.get("decisions"), "run decisions")
        ]
        if len(decisions) > len(operations):
            failures.append(f"{case_id}/{policy} has more decisions than operations")
            continue
        expected_topology: list[tuple[str, str, str]] = []
        expected_dispatches: list[str] = []
        for operation, decision in zip(operations, decisions, strict=False):
            if decision.get("operation") != operation["op"]:
                failures.append(
                    f"{case_id}/{policy} decision/action order differs at {operation['op']}"
                )
                continue
            if decision.get("decision") != "accept":
                break
            kind = operation["op"]
            if kind == "fork":
                expected_topology.extend(
                    ("fork", str(operation["source"]), str(child))
                    for child in operation["children"]
                )
            elif kind == "restore":
                expected_topology.append(
                    ("restore", str(operation["source"]), str(operation["target"]))
                )
            elif kind == "merge":
                expected_topology.append(
                    (
                        "adapter_merge_target",
                        "+".join(sorted(map(str, operation["sources"]))),
                        str(operation["target"]),
                    )
                )
            elif kind == "dispatch":
                expected_dispatches.append(str(operation["effect"]))

        provider = _object(run.get("provider"), "run provider")
        topology_events = [
            _object(value, "topology event")
            for value in _list(provider.get("topology_events"), "topology events")
        ]
        roots = [event for event in topology_events if event.get("kind") == "native_root_fork"]
        if len(roots) != 1 or roots[0].get("history_id") != provider.get("root_thread_id"):
            failures.append(f"{case_id}/{policy} lacks one matching native root fork")
        actual_topology = [
            (str(event.get("operation")), str(event.get("source")), str(event.get("target")))
            for event in topology_events
            if event.get("kind") == "native_history_fork"
        ]
        if actual_topology != expected_topology:
            failures.append(
                f"{case_id}/{policy} provider topology does not match accepted actions: "
                f"expected={expected_topology}, actual={actual_topology}"
            )
        else:
            mapped_topology += len(actual_topology) + 1

        tool_calls = [
            _object(value, "provider tool call")
            for value in _list(provider.get("tool_calls"), "provider tool calls")
        ]
        actual_dispatches = [str(call.get("effect_id")) for call in tool_calls]
        if actual_dispatches != expected_dispatches:
            failures.append(
                f"{case_id}/{policy} provider dispatches do not match accepted actions: "
                f"expected={expected_dispatches}, actual={actual_dispatches}"
            )
        else:
            mapped_dispatch += len(actual_dispatches)
    return failures, {
        "mapped_native_topology_edges": mapped_topology,
        "mapped_protected_dispatch_edges": mapped_dispatch,
    }


def _check_fault_correspondence(
    runs: Mapping[tuple[str, str], Mapping[str, Any]]
) -> tuple[list[str], dict[str, int]]:
    failures: list[str] = []
    reached = 0
    hard_crashes = 0
    recovered = 0
    probes = 0
    for (case_id, policy), run in runs.items():
        raw_fault = run.get("fault")
        if raw_fault is None:
            continue
        reached += 1
        fault = _object(raw_fault, "fault record")
        mode = str(fault.get("fault_mode"))
        initial = _object(fault.get("initial_worker"), "initial worker")
        recovery_value = fault.get("recovery_worker")
        boundary_value = fault.get("crash_boundary")
        if mode == "none":
            if initial.get("exitcode") != 0 or recovery_value is not None or boundary_value is not None:
                failures.append(f"{case_id}/{policy} malformed no-fault worker record")
        else:
            hard_crashes += 1
            recovery = _object(recovery_value, "recovery worker")
            boundary = _object(boundary_value, "crash boundary")
            if (
                initial.get("exitcode") != -9
                or recovery.get("exitcode") != 0
                or initial.get("pid") == recovery.get("pid")
            ):
                failures.append(f"{case_id}/{policy} did not hard-crash and restart a distinct worker")
            else:
                recovered += 1
            controller = _object(boundary.get("controller"), "crash controller")
            state = _object(controller.get("state"), "crash semantic state")
            sink = _object(boundary.get("sink"), "crash sink")
            sink_outcomes = _list(sink.get("outcomes"), "crash sink outcomes")
            if mode == "before_dispatch":
                ticket = _object(
                    _object(state.get("tickets"), "crash tickets").get(str(fault["effect_id"])),
                    "prepared crash ticket",
                )
                probe = _object(fault.get("attempt_probe"), "before-dispatch probe")
                if ticket.get("phase") != "prepared" or sink_outcomes or probe.get("decision") != "accept":
                    failures.append(f"{case_id}/{policy} has the wrong before-dispatch boundary/probe")
                else:
                    probes += 1
            elif mode == "after_remote_success":
                ticket = _object(
                    _object(state.get("tickets"), "crash tickets").get(str(fault["effect_id"])),
                    "inflight crash ticket",
                )
                if (
                    ticket.get("phase") != "inflight"
                    or len(sink_outcomes) != 1
                    or fault.get("recovery_action") != "query_and_settle"
                ):
                    failures.append(f"{case_id}/{policy} has the wrong remote-success boundary")
            elif mode == "after_controller_commit":
                receipts = _object(state.get("receipts"), "crash receipts")
                probe = _object(fault.get("attempt_probe"), "settled attempt probe")
                if (
                    str(fault["effect_id"]) not in receipts
                    or len(sink_outcomes) != 1
                    or probe.get("decision") != "reject"
                    or fault.get("recovery_action") != "return_cached_receipt"
                ):
                    failures.append(f"{case_id}/{policy} has the wrong committed boundary/probe")
                else:
                    probes += 1
            else:
                failures.append(f"{case_id}/{policy} has unknown fault mode {mode}")

        if (
            fault.get("attempt_count") != 1
            or fault.get("outcome_count") != 1
            or _object(fault.get("dispatch_decision"), "dispatch decision").get("decision") != "accept"
        ):
            failures.append(f"{case_id}/{policy} did not finish with one admitted effect attempt/outcome")
        expected_key = fault.get("provider_call_id") if policy == "P0" else fault.get("effect_id")
        if fault.get("stable_key") != expected_key:
            failures.append(f"{case_id}/{policy} used the wrong stable idempotency key")
    return failures, {
        "reached_dispatches": reached,
        "hard_worker_crashes": hard_crashes,
        "successful_distinct_process_recoveries": recovered,
        "executed_attempt_admission_probes": probes,
    }


def check_document(
    document: Mapping[str, Any],
    *,
    suite_path: str | Path,
    oracle_path: str | Path,
    adapter_root: str | Path | None = None,
    raw_jsonl_path: str | Path | None = None,
) -> dict[str, Any]:
    """Check one raw result document and return a machine-readable report.

    A failed scientific gate is reported in ``failures`` rather than hidden by
    an exception.  Exceptions are reserved for malformed input that cannot be
    interpreted without guessing.
    """

    suite = load_litmus(suite_path)
    oracle = load_oracle(oracle_path)
    if adapter_root is not None:
        assert_controller_oracle_separation(adapter_root)

    failures: list[str] = []
    warnings: list[str] = []
    raw_protocol: dict[str, Any] | None = None
    if raw_jsonl_path is not None:
        raw_failures, raw_protocol = _check_raw_protocol(
            document, Path(raw_jsonl_path).resolve()
        )
        failures.extend(raw_failures)
    raw_runs = _list(document.get("runs"), "runs")
    if len(raw_runs) != len(suite) * len(POLICIES):
        failures.append(f"expected 80 runs, observed {len(raw_runs)}")

    runs: dict[tuple[str, str], Mapping[str, Any]] = {}
    for raw in raw_runs:
        run = _object(raw, "run")
        case_id, policy = run.get("case_id"), run.get("policy")
        if not isinstance(case_id, str) or not isinstance(policy, str):
            raise ResultFormatError("run omitted case_id or policy")
        key = (case_id, policy)
        if key in runs:
            failures.append(f"duplicate run {case_id}/{policy}")
        runs[key] = run

    expected_keys = {(case.case_id, policy) for case in suite for policy in POLICIES}
    missing = sorted(expected_keys - set(runs))
    extra = sorted(set(runs) - expected_keys)
    if missing:
        failures.append(f"missing runs: {missing}")
    if extra:
        failures.append(f"unexpected runs: {extra}")
    correspondence_failures, correspondence = _check_adapter_correspondence(runs, suite)
    failures.extend(correspondence_failures)
    fault_failures, fault_correspondence = _check_fault_correspondence(runs)
    failures.extend(fault_failures)

    p3_agreement = 0
    p3_total = 0
    p3_replay_count = 0
    p3_unsafe_accepts: list[str] = []
    duplicate_effects: list[str] = []
    unmediated_outcomes: list[str] = []
    missing_tool_calls: list[str] = []
    baseline = {
        policy: {"false_positive": 0, "false_negative": 0, "observed": 0}
        for policy in POLICIES[:-1]
    }

    for case in suite:
        expected = oracle[case.case_id]
        for policy in POLICIES:
            run = runs.get((case.case_id, policy))
            if run is None:
                continue
            status = run.get("status")
            if status not in {"terminal", "earliest_divergence"}:
                failures.append(f"{case.case_id}/{policy} has nonterminal status {status!r}")
            decisions = _decision_map(run)
            if policy == "P3":
                p3_total += len(expected.decisions)
                for request, verdict in expected.decisions.items():
                    actual = decisions.get(request)
                    if actual == verdict:
                        p3_agreement += 1
                    else:
                        failures.append(
                            f"{case.case_id}/P3 {request}: expected {verdict}, observed {actual}"
                        )
                extras = sorted(set(decisions) - set(expected.decisions))
                if extras:
                    failures.append(f"{case.case_id}/P3 has unexpected suite decisions {extras}")
                for request in expected.unsafe_if_accepted:
                    if decisions.get(request) == "accept":
                        p3_unsafe_accepts.append(f"{case.case_id}:{request}")
            else:
                for request, actual in decisions.items():
                    expected_verdict = expected.decisions.get(request)
                    if expected_verdict is None:
                        continue
                    baseline[policy]["observed"] += 1
                    if actual == "accept" and expected_verdict == "reject":
                        baseline[policy]["false_positive"] += 1
                    elif actual == "reject" and expected_verdict == "accept":
                        baseline[policy]["false_negative"] += 1

            counts, outcomes = _sink_counts(run)
            for effect, count in counts.items():
                if count > 1:
                    duplicate_effects.append(f"{case.case_id}/{policy}:{effect}={count}")
            provider = _object(run.get("provider"), "run provider")
            tool_calls = [
                _object(value, "provider tool call")
                for value in _list(provider.get("tool_calls"), "provider tool calls")
            ]
            mediated_effects = {
                str(call.get("effect_id"))
                for call in tool_calls
                if call.get("effect_id") is not None
                and call.get("method") == "item/tool/call"
                and call.get("call_id")
            }
            for outcome in outcomes:
                effect = str(outcome["effect_id"])
                if effect not in mediated_effects:
                    unmediated_outcomes.append(f"{case.case_id}/{policy}:{effect}")
            dispatch_accepted = any(
                decision.get("operation") == "dispatch"
                and decision.get("decision") == "accept"
                for decision in _list(run.get("decisions"), "run decisions")
                if isinstance(decision, Mapping)
            )
            if dispatch_accepted and not tool_calls:
                missing_tool_calls.append(f"{case.case_id}/{policy}")

            if policy == "P3":
                if counts != expected.aggregate_sink_outcomes:
                    failures.append(
                        f"{case.case_id}/P3 sink counts: expected "
                        f"{expected.aggregate_sink_outcomes}, observed {counts}"
                    )
                controller = _object(run.get("controller"), "run controller")
                snapshot = _object(controller.get("snapshot"), "controller snapshot")
                state = _object(snapshot.get("state"), "controller semantic state")
                receipts = set(_object(state.get("receipts"), "controller receipts"))
                if receipts != set(expected.settled_receipts):
                    failures.append(
                        f"{case.case_id}/P3 receipts: expected {sorted(expected.settled_receipts)}, "
                        f"observed {sorted(receipts)}"
                    )
                try:
                    replay_bundle(
                        {
                            "events": _list(controller.get("events"), "controller events"),
                            "head_hash": snapshot.get("head_hash"),
                            "state_hash": snapshot.get("state_hash"),
                        }
                    )
                except ReplayError as error:
                    failures.append(f"{case.case_id}/P3 replay failed: {error}")
                else:
                    p3_replay_count += 1

    if p3_unsafe_accepts:
        failures.append(f"P3 admitted unsafe requests: {sorted(p3_unsafe_accepts)}")
    if duplicate_effects:
        failures.append(f"duplicate aggregate outcomes: {sorted(duplicate_effects)}")
    if unmediated_outcomes:
        failures.append(f"sink outcomes without matching App Server callback: {sorted(unmediated_outcomes)}")
    if missing_tool_calls:
        failures.append(f"accepted dispatches without item/tool/call: {sorted(missing_tool_calls)}")

    controls = _object(document.get("controls"), "controls")
    if controls.get("unauthenticated_attempt_rejected") is not True:
        failures.append("unauthenticated sink attempt control did not reject")
    if controls.get("stable_key_conflict_rejected") is not True:
        failures.append("stable-key rebinding control did not reject")

    retained_probe_ids = {
        str(_object(value, "observation probe").get("case_id"))
        for value in _list(document.get("observations"), "observations")
    }
    expected_probe_ids = {"C02", "C04", "C13", "C14", "C16", "C18"}
    if retained_probe_ids != expected_probe_ids:
        failures.append(f"retained observation cases differ: {sorted(retained_probe_ids)}")
    # Do not trust runner-supplied labels or hand-built trusted prefixes.  Join
    # the frozen labels and derive all prefixes from controller snapshots and
    # raw-cross-checked provider records here.
    probes = _derive_probes(document, suite, oracle)
    o0 = mixed_label_fibers(probes, "O0")
    o1 = mixed_label_fibers(probes, "O1")
    o2 = mixed_label_fibers(probes, "O2")
    if _fiber_pairs(o0) != EXPECTED_PROBE_PAIRS:
        failures.append(f"O0 mixed fibers differ: {_fiber_pairs(o0)}")
    if _fiber_pairs(o1) != EXPECTED_PROBE_PAIRS:
        failures.append(f"O1 mixed fibers differ: {_fiber_pairs(o1)}")
    if o2:
        failures.append(f"O2 retains mixed-label fibers: {o2}")

    if p3_replay_count != len(suite):
        failures.append(f"P3 replayed {p3_replay_count}/{len(suite)} runs")
    if p3_total == 0:
        failures.append("P3 oracle comparison had no decisions")

    return {
        "schema_version": 1,
        "ok": not failures,
        "failures": failures,
        "warnings": warnings,
        "metrics": {
            "run_count": len(raw_runs),
            "p3_decisions_matching": p3_agreement,
            "p3_decisions_total": p3_total,
            "p3_replay_count": p3_replay_count,
            "p3_unsafe_accepts": p3_unsafe_accepts,
            "duplicate_aggregate_outcomes": duplicate_effects,
            "unmediated_outcomes": unmediated_outcomes,
            "accepted_dispatches_without_tool_call": missing_tool_calls,
            "baseline": baseline,
            "mixed_fibers": {"O0": o0, "O1": o1, "O2": o2},
            "raw_protocol": raw_protocol,
            "adapter_correspondence": correspondence,
            "fault_correspondence": fault_correspondence,
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--oracle", type=Path, default=Path("adapter/oracle.yaml"))
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("adapter/results/check.json"))
    parser.add_argument("--raw-jsonl", type=Path)
    arguments = parser.parse_args(argv)
    document = json.loads(arguments.input.read_text(encoding="utf-8"))
    report = check_document(
        _object(document, "result document"),
        suite_path=arguments.suite,
        oracle_path=arguments.oracle,
        adapter_root=arguments.suite.parent,
        raw_jsonl_path=(
            arguments.raw_jsonl
            if arguments.raw_jsonl is not None
            else arguments.input.parent / "raw" / "app-server.jsonl"
        ),
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report["metrics"], sort_keys=True))
    if not report["ok"]:
        for failure in report["failures"]:
            print(f"FAIL: {failure}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["EXPECTED_PROBE_PAIRS", "ResultFormatError", "check_document", "main"]
