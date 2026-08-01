"""Run the fixed authority-continuity suite through a real Codex App Server.

Codex itself is not mocked: this harness launches the installed App Server,
uses native ``thread/fork`` and the real client-owned ``item/tool/call`` seam,
and keeps that callback pending while a separate controller worker is killed
and restarted.  Only the model endpoint and protected external service are
deterministic local fixtures, so no model judgment or production side effect
enters this correctness experiment.

The runner never imports the frozen oracle or the independent replay checker.
It emits raw evidence; :mod:`adapter.check_results` performs the join later.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import shutil
import sqlite3
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence

from adapter.app_server import CodexAppServer, TURN_TIMEOUT_SECONDS
from adapter.controller import DurableController
from adapter.mock_responses import DeterministicResponsesServer
from adapter.sink import AuthenticationError, AuthenticatedSink, StableKeyConflict
from adapter.spec import LitmusCase, load_litmus
from adapter.test_app_server import run_preflight
from adapter.worker import apply_in_worker, dispatch_with_recovery


POLICIES = ("P0", "P1", "P2", "P3")
WORKER_TIMEOUT_SECONDS = 5.0
CASE_TIMEOUT_SECONDS = 60.0
_SINK_SECRET = sha256(b"authority-continuity-fixed-local-sink-v1").digest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest_bytes(value: bytes) -> str:
    return sha256(value).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON document is not an object: {path}")
    return value


def _grants(case: LitmusCase) -> dict[str, int]:
    values = {
        str(operation["grant"]): int(operation["capacity"])
        for operation in case.operations
        if operation["op"] == "grant"
    }
    if not values:
        raise ValueError(f"{case.case_id} has no genesis grants")
    return values


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_runtime_lock(path: Path, codex_binary: str) -> dict[str, Any]:
    lock = _read_json(path)
    codex = lock.get("codex")
    if not isinstance(codex, dict):
        raise ValueError("runtime lock omitted codex object")
    resolved = Path(shutil.which(codex_binary) or codex_binary).resolve()
    actual_version = subprocess.run(
        [str(resolved), "--version"],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    ).stdout.strip()
    actual_hash = _sha256_file(resolved)
    mismatches = []
    if actual_version != codex.get("version"):
        mismatches.append(f"version {actual_version!r} != {codex.get('version')!r}")
    if actual_hash != codex.get("binary_sha256"):
        mismatches.append(f"binary sha256 {actual_hash} != {codex.get('binary_sha256')}")
    if mismatches:
        raise RuntimeError("runtime lock mismatch: " + "; ".join(mismatches))
    return {
        "lock": lock,
        "lock_sha256": _sha256_file(path),
        "resolved_codex_binary": str(resolved),
        "observed_codex_version": actual_version,
        "observed_codex_binary_sha256": actual_hash,
    }


class NativeTopology:
    """Ground logical branch epochs in real, fresh App Server history IDs."""

    def __init__(
        self,
        client: CodexAppServer,
        seed_thread_id: str,
        seed_turn_id: str,
        root_thread: Mapping[str, Any],
    ) -> None:
        self.client = client
        self.seed_thread_id = seed_thread_id
        self.seed_turn_id = seed_turn_id
        self.histories: dict[str, str] = {"root": str(root_thread["id"])}
        self.events: list[dict[str, Any]] = [
            {
                "kind": "native_root_fork",
                "parent_history_id": seed_thread_id,
                "history_id": str(root_thread["id"]),
                "turn_id": seed_turn_id,
                "forked_from_id": root_thread.get("forkedFromId"),
                "ephemeral": root_thread.get("ephemeral"),
            }
        ]

    def _fresh(self, logical: str, operation: str, source: str) -> None:
        child = self.client.fork_at_turn(self.seed_thread_id, self.seed_turn_id)
        self.histories[logical] = str(child["id"])
        self.events.append(
            {
                "kind": "native_history_fork",
                "operation": operation,
                "source": source,
                "target": logical,
                "parent_history_id": self.seed_thread_id,
                "history_id": str(child["id"]),
                "turn_id": self.seed_turn_id,
                "forked_from_id": child.get("forkedFromId"),
                "ephemeral": child.get("ephemeral"),
            }
        )

    def accepted(self, operation: Mapping[str, Any]) -> None:
        kind = operation["op"]
        if kind == "fork":
            source = str(operation["source"])
            for child in operation["children"]:
                self._fresh(str(child), "fork", source)
        elif kind == "restore":
            self._fresh(str(operation["target"]), "restore", str(operation["source"]))
        elif kind == "merge":
            # The history ID is real; the merge semantics and projection are
            # explicitly adapter-defined, as stated in the experiment plan.
            sources = "+".join(sorted(map(str, operation["sources"])))
            self._fresh(str(operation["target"]), "adapter_merge_target", sources)

    def dispatch_thread(self, operation: Mapping[str, Any]) -> str:
        site = str(operation.get("site", ""))
        logical = site.split(".", 1)[0]
        if logical not in self.histories:
            logical = "root"
        return self.histories[logical]


def _snapshot_case(controller_path: Path, sink_path: Path, policy: str, grants: Mapping[str, int]) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    with DurableController(controller_path, policy, grants) as controller:
        controller_snapshot = controller.snapshot()
        events = controller.events()
    with AuthenticatedSink(sink_path, _SINK_SECRET) as sink:
        sink_snapshot = sink.snapshot()
    return controller_snapshot, events, sink_snapshot


def _run_one(
    *,
    case: LitmusCase,
    policy: str,
    run_dir: Path,
    client: CodexAppServer,
    responses: DeterministicResponsesServer,
    seed_thread_id: str,
    seed_turn_id: str,
) -> dict[str, Any]:
    started = time.monotonic()
    run_dir.mkdir(parents=True, exist_ok=False)
    controller_path = run_dir / "controller.sqlite3"
    sink_path = run_dir / "sink.sqlite3"
    grants = _grants(case)
    native_root = client.fork_at_turn(seed_thread_id, seed_turn_id)
    topology = NativeTopology(client, seed_thread_id, seed_turn_id, native_root)
    decisions: list[dict[str, Any]] = []
    workers: list[dict[str, Any]] = []
    tool_calls: list[dict[str, Any]] = []
    fault: dict[str, Any] | None = None
    status = "terminal"
    non_grant_operations = [operation for operation in case.operations if operation["op"] != "grant"]

    for index, operation_value in enumerate(non_grant_operations):
        if time.monotonic() - started > CASE_TIMEOUT_SECONDS:
            raise TimeoutError(f"{case.case_id}/{policy} exceeded {CASE_TIMEOUT_SECONDS}s")
        operation = dict(operation_value)
        if operation["op"] == "dispatch":
            effect = str(operation["effect"])
            call_id = f"call-{policy.lower()}-{case.case_id.lower()}-{effect}"
            responses.enqueue_tool_call(
                "protected_commit",
                {"effect_id": effect},
                call_id=call_id,
                response_id=f"fixture-tool-{policy.lower()}-{case.case_id.lower()}",
            )
            responses.enqueue_assistant(
                f"receipt acknowledged for {effect}",
                response_id=f"fixture-final-{policy.lower()}-{case.case_id.lower()}",
            )
            thread_id = topology.dispatch_thread(operation)
            pending = client.start_protected_turn(
                thread_id,
                f"Call protected_commit once for {effect}, then finish.",
                expected_arguments={"effect_id": effect},
                timeout=TURN_TIMEOUT_SECONDS,
            )
            tool_call = {
                "method": "item/tool/call",
                "thread_id": pending.thread_id,
                "turn_id": pending.turn_id,
                "call_id": pending.call_id,
                "effect_id": effect,
                "tool": pending.tool,
                "arguments": dict(pending.arguments),
            }
            tool_calls.append(tool_call)
            dispatch = dispatch_with_recovery(
                controller_path=controller_path,
                policy=policy,
                grants=grants,
                sink_path=sink_path,
                secret=_SINK_SECRET,
                operation=operation,
                crash_mode=case.crash_mode,
                provider_call_id=pending.call_id,
                timeout=WORKER_TIMEOUT_SECONDS,
                restart_timeout=WORKER_TIMEOUT_SECONDS,
            )
            decisions.append(dict(dispatch["dispatch_decision"]))
            fault = dispatch
            reply = dispatch.get("reply")
            if not isinstance(reply, Mapping):
                raise RuntimeError(f"{case.case_id}/{policy} dispatch returned no receipt")
            pending.respond_text(_canonical_json(reply))
            pending.wait_turn_completed(timeout=TURN_TIMEOUT_SECONDS)
            workers.extend(
                record
                for record in (dispatch.get("initial_worker"), dispatch.get("recovery_worker"))
                if isinstance(record, dict)
            )
            decision = decisions[-1]
        else:
            applied = apply_in_worker(
                controller_path=controller_path,
                policy=policy,
                grants=grants,
                operation=operation,
                timeout=WORKER_TIMEOUT_SECONDS,
            )
            decision = dict(applied["decision"])
            decisions.append(decision)
            workers.append(dict(applied["worker"]))
            if decision["decision"] == "accept":
                topology.accepted(operation)

        if decision["decision"] == "reject":
            if index != len(non_grant_operations) - 1:
                status = "earliest_divergence"
            break

    controller_snapshot, controller_events, sink_snapshot = _snapshot_case(
        controller_path, sink_path, policy, grants
    )
    elapsed = time.monotonic() - started
    return {
        "run_id": f"{policy}-{case.case_id}",
        "opaque_case_id": case.opaque_worker_id,
        "case_id": case.case_id,
        "policy": policy,
        "crash_mode": case.crash_mode,
        "dispatch_site": case.dispatch_site,
        "status": status,
        "elapsed_seconds": elapsed,
        "decisions": decisions,
        "workers": workers,
        "fault": fault,
        "controller": {"snapshot": controller_snapshot, "events": controller_events},
        "sink": {"snapshot": sink_snapshot},
        "provider": {
            "root_thread_id": topology.histories["root"],
            "logical_histories": dict(sorted(topology.histories.items())),
            "topology_events": topology.events,
            "tool_calls": tool_calls,
        },
    }


def _probe_from_runs(runs: Sequence[Mapping[str, Any]], suite_path: Path) -> list[dict[str, Any]]:
    by_case = {
        str(run["case_id"]): run
        for run in runs
        if run.get("policy") == "P3"
    }
    fixture_hash = _sha256_file(suite_path)
    cases = {case.case_id: case for case in load_litmus(suite_path)}

    def prefix_state(case_id: str, request: str) -> Mapping[str, Any]:
        previous: Mapping[str, Any] | None = None
        for worker in by_case[case_id]["workers"]:
            payload = worker.get("payload")
            if not isinstance(payload, Mapping):
                continue
            decision = payload.get("decision")
            if isinstance(decision, Mapping) and decision.get("request") == request:
                if previous is None:
                    raise RuntimeError(f"no prefix snapshot before {case_id}/{request}")
                return previous["controller_snapshot"]["state"]
            if isinstance(payload.get("controller_snapshot"), Mapping):
                previous = payload
        raise RuntimeError(f"missing retained request {case_id}/{request}")

    def restore_mode(case_id: str) -> str:
        for event in by_case[case_id]["controller"]["events"]:
            operation = event.get("body", {}).get("operation", {})
            if operation.get("request") == "restore_same_bytes":
                return str(operation["mode"])
        raise RuntimeError(f"missing restore event for {case_id}")

    def topology_provider(case_id: str) -> tuple[dict[str, Any], ...]:
        events = by_case[case_id]["provider"]["topology_events"]
        restore = next(event for event in events if event.get("operation") == "restore")
        return (
            {
                "kind": "native_history_fork",
                "parent_history_id": restore["parent_history_id"],
                "history_id": restore["history_id"],
                "turn_id": restore["turn_id"],
            },
        )

    def fork_provider(case_id: str) -> tuple[dict[str, Any], ...]:
        events = [
            event
            for event in by_case[case_id]["provider"]["topology_events"]
            if event.get("operation") == "fork"
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
        call = by_case[case_id]["provider"]["tool_calls"][0]
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

    probes: list[dict[str, Any]] = []
    for case_id in ("C13", "C14"):
        prefix = prefix_state(case_id, "reserve_restored")
        probes.append(
            {
                "case_id": case_id,
                "workspace": {"bytes_sha256": fixture_hash},
                "provider_events": list(topology_provider(case_id)),
                "trusted_events": [
                    {
                        "kind": "restore",
                        "source": "root",
                        "target": "restored",
                        "mode": restore_mode(case_id),
                        "frontier": prefix["frontier"],
                    }
                ],
                "action": {
                    "kind": "reserve",
                    "operation": "reserve",
                    "source_role": "restored_copy",
                    "branch_id": "restored",
                    "grant_id": "g",
                    "demand": 1,
                },
            }
        )
    for case_id in ("C16", "C18"):
        state = prefix_state(case_id, "reserve_c2")
        next_action = next(
            operation
            for operation in cases[case_id].operations
            if operation.get("request") == "reserve_c2"
        )
        probes.append(
            {
                "case_id": case_id,
                "workspace": {"bytes_sha256": fixture_hash},
                "provider_events": list(fork_provider(case_id)),
                "trusted_events": [
                    {
                        "kind": "authority_lineage",
                        "grants": [
                            {"grant_id": grant, "capacity": capacity}
                            for grant, capacity in sorted(state["grants"].items())
                        ],
                        "delegations": [
                            {"grant_id": grant, "branch_id": branch}
                            for grant, branches in sorted(state["delegations"].items())
                            for branch in sorted(branches)
                        ],
                        "claims": [
                            {
                                "claim_id": claim_id,
                                "grant_id": claim["grant"],
                                "owner_branch": claim.get("owner"),
                                "demand": claim["demand"],
                                "status": claim["status"],
                            }
                            for claim_id, claim in sorted(state["claims"].items())
                        ],
                    }
                ],
                "action": {
                    "kind": "reserve",
                    "operation": "reserve",
                    "source_role": "parallel_sibling",
                    "branch_id": "right",
                    "grant_id": str(next_action["grant"]),
                    "demand": int(next_action["demand"]),
                },
            }
        )
    for case_id in ("C02", "C04"):
        state = by_case[case_id]["fault"]["crash_boundary"]["controller"]["state"]
        if "e1" in state["receipts"]:
            phase = "settled"
        else:
            phase = state["tickets"]["e1"]["phase"]
        probes.append(
            {
                "case_id": case_id,
                "workspace": {"bytes_sha256": fixture_hash},
                "provider_events": list(pending_provider(case_id)),
                "trusted_events": [
                    {"kind": "effect_phase", "effect_id": "e1", "phase": phase}
                ],
                "action": {
                    "kind": "attempt",
                    "operation": "sink_attempt",
                    "effect_id": "e1",
                    "same_operation": True,
                },
            }
        )
    return probes


def _sink_controls(directory: Path) -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "sink-controls.sqlite3"
    unauthenticated_rejected = False
    conflict_rejected = False
    with AuthenticatedSink(path, _SINK_SECRET) as sink:
        try:
            sink.attempt(
                effect_id="control-effect",
                stable_key="control-key",
                request_hash="request-a",
                outcome="succeeded",
                authorization=None,
            )
        except AuthenticationError:
            unauthenticated_rejected = True
        authorization = sink.authorize_attempt(
            "control-effect", "control-key", "request-a", "succeeded"
        )
        sink.attempt(
            effect_id="control-effect",
            stable_key="control-key",
            request_hash="request-a",
            outcome="succeeded",
            authorization=authorization,
        )
        conflicting_auth = sink.authorize_attempt(
            "other-effect", "control-key", "request-b", "succeeded"
        )
        try:
            sink.attempt(
                effect_id="other-effect",
                stable_key="control-key",
                request_hash="request-b",
                outcome="succeeded",
                authorization=conflicting_auth,
            )
        except StableKeyConflict:
            conflict_rejected = True
        snapshot = sink.snapshot()
    return {
        "unauthenticated_attempt_rejected": unauthenticated_rejected,
        "stable_key_conflict_rejected": conflict_rejected,
        "snapshot": snapshot,
    }


def run_worker_crash_preflight(
    *,
    workspace: Path,
    directory: Path,
    codex_binary: str,
) -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=False)
    controller_path = directory / "controller.sqlite3"
    sink_path = directory / "sink.sqlite3"
    grants = {"g": 1}
    for operation in (
        {"op": "reserve", "request": "reserve_e1", "claim": "c1", "branch": "root", "grant": "g", "demand": 1},
        {"op": "prepare", "request": "prepare_e1", "effect": "preflight-effect-1", "claim": "c1"},
    ):
        result = apply_in_worker(
            controller_path=controller_path,
            policy="P3",
            grants=grants,
            operation=operation,
            timeout=WORKER_TIMEOUT_SECONDS,
        )
        if result["decision"]["decision"] != "accept":
            raise RuntimeError(f"preflight prerequisite rejected: {result['decision']}")

    dispatch_holder: dict[str, Any] = {}

    def handler(pending: Any) -> None:
        result = dispatch_with_recovery(
            controller_path=controller_path,
            policy="P3",
            grants=grants,
            sink_path=sink_path,
            secret=_SINK_SECRET,
            operation={
                "op": "dispatch",
                "request": "dispatch_e1",
                "effect": "preflight-effect-1",
                "site": "preflight.initial",
            },
            crash_mode="after_remote_success",
            provider_call_id=pending.call_id,
            timeout=WORKER_TIMEOUT_SECONDS,
            restart_timeout=WORKER_TIMEOUT_SECONDS,
        )
        dispatch_holder.update(result)
        pending.respond_text(_canonical_json(result["reply"]))

    boundary = run_preflight(
        codex_binary=codex_binary,
        workspace=workspace,
        raw_jsonl_path=directory / "app-server.jsonl",
        tool_handler=handler,
    )
    if dispatch_holder.get("recovery_action") != "query_and_settle":
        raise RuntimeError("preflight did not exercise remote-success reconciliation")
    result = {"boundary": boundary.__dict__, "dispatch": dispatch_holder}
    (directory / "result.json").write_text(
        json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    return result


def run_suite(
    *,
    suite_path: Path,
    runtime_lock_path: Path,
    raw_dir: Path,
    output_path: Path,
    workspace: Path,
    codex_binary: str,
    run_preflight_first: bool = True,
) -> dict[str, Any]:
    runtime = verify_runtime_lock(runtime_lock_path, codex_binary)
    cases = load_litmus(suite_path)
    raw_dir.mkdir(parents=True, exist_ok=False)
    if run_preflight_first:
        run_worker_crash_preflight(
            workspace=workspace,
            directory=raw_dir / "preflight",
            codex_binary=codex_binary,
        )

    started_ns = time.time_ns()
    runs: list[dict[str, Any]] = []
    seed_thread_id: str | None = None
    seed_turn_id: str | None = None
    seed_archived = False
    with DeterministicResponsesServer() as responses:
        responses.enqueue_assistant("fixed suite seed acknowledged", response_id="fixture-suite-seed")
        client = CodexAppServer(
            model_base_url=responses.base_url,
            workspace=workspace,
            raw_jsonl_path=raw_dir / "app-server.jsonl",
            codex_binary=codex_binary,
        )
        with client:
            try:
                seed = client.create_seed_thread()
                seed_thread_id = str(seed["id"])
                seed_turn_id, _ = client.start_turn_and_wait(
                    seed_thread_id,
                    "Acknowledge the fixed authority-continuity suite seed.",
                )
                for policy in POLICIES:
                    for case in cases:
                        run_dir = raw_dir / "runs" / policy / case.case_id
                        run = _run_one(
                            case=case,
                            policy=policy,
                            run_dir=run_dir,
                            client=client,
                            responses=responses,
                            seed_thread_id=seed_thread_id,
                            seed_turn_id=seed_turn_id,
                        )
                        runs.append(run)
                        print(
                            f"RUN {len(runs):02d}/80 {policy}/{case.case_id} "
                            f"{run['status']} {run['elapsed_seconds']:.3f}s",
                            flush=True,
                        )
                client.assert_hermetic_runtime()
            finally:
                if seed_thread_id is not None:
                    client.archive_thread(seed_thread_id)
                    seed_archived = True
        responses.assert_consumed()
        provider_counts = {
            "responses_requests": responses.responses_request_count,
            "models_requests": responses.models_request_count,
        }

    if seed_thread_id is None or seed_turn_id is None or not seed_archived:
        raise RuntimeError("suite seed lifecycle was incomplete")
    controls = _sink_controls(raw_dir / "controls")
    observations = _probe_from_runs(runs, suite_path)
    document = {
        "schema_version": 1,
        "metadata": {
            "started_ns": started_ns,
            "completed_ns": time.time_ns(),
            "runtime": runtime,
            "python": sys.version,
            "sqlite": sqlite3.sqlite_version,
            "platform": platform.platform(),
            "suite_sha256": _sha256_file(suite_path),
            "seed_thread_id": seed_thread_id,
            "seed_turn_id": seed_turn_id,
            "seed_archived": seed_archived,
            "provider_counts": provider_counts,
            "model_endpoint": "deterministic loopback Responses fixture",
            "live_model_or_external_effect": False,
        },
        "runs": runs,
        "observations": observations,
        "controls": controls,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(document, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    return document


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--runtime-lock", type=Path, required=True)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--codex-binary", default="codex")
    parser.add_argument("--skip-preflight", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    arguments = parser.parse_args(argv)
    if arguments.preflight_only:
        runtime = verify_runtime_lock(arguments.runtime_lock.resolve(), arguments.codex_binary)
        result = run_worker_crash_preflight(
            workspace=arguments.workspace.resolve(),
            directory=arguments.raw_dir.resolve(),
            codex_binary=arguments.codex_binary,
        )
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(
            json.dumps({"runtime": runtime, "preflight": result}, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        return 0
    run_suite(
        suite_path=arguments.suite.resolve(),
        runtime_lock_path=arguments.runtime_lock.resolve(),
        raw_dir=arguments.raw_dir.resolve(),
        output_path=arguments.output.resolve(),
        workspace=arguments.workspace.resolve(),
        codex_binary=arguments.codex_binary,
        run_preflight_first=not arguments.skip_preflight,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CASE_TIMEOUT_SECONDS",
    "POLICIES",
    "NativeTopology",
    "run_suite",
    "run_worker_crash_preflight",
    "verify_runtime_lock",
]
