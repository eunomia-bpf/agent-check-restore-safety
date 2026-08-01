"""Crash/restart worker for one protected external effect.

The supervisor in this module deliberately keeps the controller worker in a
separate operating-system process.  Fault injection uses ``SIGKILL`` after a
specified durable boundary, so recovery must reconstruct its decision from the
controller and sink databases rather than from Python stack state.

This module is part of the mechanism under test.  It consequently imports
neither the evaluation oracle nor the independent replay checker.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import multiprocessing
from multiprocessing.connection import Connection
import os
from pathlib import Path
import signal
import time
import traceback
from typing import Any, Mapping

from .controller import DurableController, POLICIES
from .sink import AuthenticatedSink, verify_evidence


FAULT_MODES = frozenset(
    {"none", "before_dispatch", "after_remote_success", "after_controller_commit"}
)
DEFAULT_STAGE_TIMEOUT_SECONDS = 15.0
DEFAULT_RESTART_TIMEOUT_SECONDS = 5.0
_ERROR_EXIT_CODE = 70


class WorkerError(RuntimeError):
    """Base class for supervisor and child-worker failures."""


class WorkerTimeout(WorkerError):
    """Raised when a worker does not start or finish within its deadline."""


class WorkerProtocolError(WorkerError):
    """Raised when durable controller and sink evidence disagree."""


@dataclass(frozen=True)
class _Invocation:
    controller_path: str
    sink_path: str
    secret: bytes
    policy: str
    grants: dict[str, int]
    effect_id: str
    provider_call_id: str | None
    stable_key: str
    request_hash: str
    outcome: str
    dispatch_request: str
    settle_request: str
    site: str | None


@dataclass(frozen=True)
class _ApplyInvocation:
    controller_path: str
    policy: str
    grants: dict[str, int]
    operation: dict[str, Any]


def stable_key_for(
    policy: str,
    *,
    effect_id: str,
    provider_call_id: str | None,
) -> str:
    """Resolve the physical idempotency key without inventing an identifier.

    P0 has no controller-level stable effect key, so its best available key is
    the *retained* provider callback ID.  A missing P0 callback ID is an error,
    not an invitation to synthesize a replacement.  P1--P3 use the logical
    effect ID, which remains stable across worker crashes.
    """

    if policy not in POLICIES:
        raise ValueError(f"unknown policy: {policy}")
    if not isinstance(effect_id, str) or not effect_id:
        raise ValueError("effect_id must be a nonempty string")
    if policy == "P0":
        if not isinstance(provider_call_id, str) or not provider_call_id:
            raise ValueError("P0 requires the retained provider_call_id")
        return provider_call_id
    return effect_id


def _receipt_body(invocation: _Invocation, evidence: Mapping[str, Any]) -> dict[str, Any]:
    body = verify_evidence(invocation.secret, evidence)
    expected = {
        "kind": "receipt",
        "effect_id": invocation.effect_id,
        "stable_key": invocation.stable_key,
        "request_hash": invocation.request_hash,
        "outcome": invocation.outcome,
    }
    for key, value in expected.items():
        if body.get(key) != value:
            raise WorkerProtocolError(
                f"sink evidence {key} mismatch: {body.get(key)!r} != {value!r}"
            )
    return body


def _query_receipt(
    invocation: _Invocation,
    sink: AuthenticatedSink,
) -> tuple[dict[str, Any], dict[str, Any]]:
    evidence = sink.query(
        invocation.stable_key,
        authorization=sink.authorize_query(invocation.stable_key),
    )
    return evidence, _receipt_body(invocation, evidence)


def _attempt(
    invocation: _Invocation,
    sink: AuthenticatedSink,
) -> tuple[dict[str, Any], dict[str, Any]]:
    authorization = sink.authorize_attempt(
        invocation.effect_id,
        invocation.stable_key,
        invocation.request_hash,
        invocation.outcome,
    )
    evidence = sink.attempt(
        effect_id=invocation.effect_id,
        stable_key=invocation.stable_key,
        request_hash=invocation.request_hash,
        outcome=invocation.outcome,
        authorization=authorization,
    )
    return evidence, _receipt_body(invocation, evidence)


def _dispatch_operation(invocation: _Invocation) -> dict[str, Any]:
    operation: dict[str, Any] = {
        "op": "dispatch",
        "request": invocation.dispatch_request,
        "effect": invocation.effect_id,
    }
    if invocation.site is not None:
        operation["site"] = invocation.site
    return operation


def _settle_operation(invocation: _Invocation) -> dict[str, Any]:
    return {
        "op": "settle",
        "request": invocation.settle_request,
        "effect": invocation.effect_id,
        "outcome": invocation.outcome,
    }


def _reply(
    invocation: _Invocation,
    evidence: Mapping[str, Any],
    controller_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "effect_id": invocation.effect_id,
        "provider_call_id": invocation.provider_call_id,
        "stable_key": invocation.stable_key,
        "outcome": invocation.outcome,
        "sink_evidence": dict(evidence),
        "controller_receipt": dict(controller_receipt),
    }


def _hard_crash() -> None:
    """Terminate the current child without unwinding or closing databases."""

    if hasattr(signal, "SIGKILL"):
        os.kill(os.getpid(), signal.SIGKILL)
    os._exit(137)  # pragma: no cover - fallback for platforms without SIGKILL


def _run_initial(invocation: _Invocation, fault_mode: str) -> dict[str, Any]:
    with (
        DurableController(
            invocation.controller_path, invocation.policy, invocation.grants
        ) as controller,
        AuthenticatedSink(invocation.sink_path, invocation.secret) as sink,
    ):
        if fault_mode == "before_dispatch":
            _hard_crash()

        dispatch = controller.apply(_dispatch_operation(invocation))
        if not dispatch.accepted:
            return {
                "status": "rejected",
                "phase": "dispatch",
                "dispatch": dispatch.as_dict(),
            }

        evidence, body = _attempt(invocation, sink)
        if fault_mode == "after_remote_success":
            _hard_crash()

        settlement = controller.apply(_settle_operation(invocation))
        if not settlement.accepted:
            raise WorkerProtocolError(f"controller rejected settlement: {settlement.reason}")
        controller_receipt = controller.snapshot()["state"]["receipts"].get(
            invocation.effect_id
        )
        if not isinstance(controller_receipt, Mapping):
            raise WorkerProtocolError("settlement committed without a controller receipt")
        if controller_receipt.get("outcome") != body["outcome"]:
            raise WorkerProtocolError("controller receipt disagrees with sink outcome")

        if fault_mode == "after_controller_commit":
            _hard_crash()

        return {
            "status": "completed",
            "recovery_action": "none",
            "dispatch": dispatch.as_dict(),
            "settlement": settlement.as_dict(),
            "reply": _reply(invocation, evidence, controller_receipt),
        }


def _run_recovery(invocation: _Invocation, fault_mode: str) -> dict[str, Any]:
    with (
        DurableController(
            invocation.controller_path, invocation.policy, invocation.grants
        ) as controller,
        AuthenticatedSink(invocation.sink_path, invocation.secret) as sink,
    ):
        if fault_mode == "before_dispatch":
            dispatch = controller.apply(_dispatch_operation(invocation))
            if not dispatch.accepted:
                raise WorkerProtocolError(
                    f"recovery dispatch was rejected: {dispatch.reason}"
                )
            evidence, body = _attempt(invocation, sink)
            settlement = controller.apply(_settle_operation(invocation))
            if not settlement.accepted:
                raise WorkerProtocolError(
                    f"recovery settlement was rejected: {settlement.reason}"
                )
            action = "dispatch_once"
            recovery_decision: dict[str, Any] | None = None
            attempt_probe: dict[str, Any] | None = dispatch.as_dict()

        elif fault_mode == "after_remote_success":
            recovery = controller.recover_after_crash(invocation.effect_id)
            if not recovery.accepted:
                raise WorkerProtocolError(
                    f"controller crash recovery was rejected: {recovery.reason}"
                )
            evidence, body = _query_receipt(invocation, sink)
            settlement = controller.apply(_settle_operation(invocation))
            if not settlement.accepted:
                raise WorkerProtocolError(
                    f"reconciled settlement was rejected: {settlement.reason}"
                )
            dispatch = None
            action = "query_and_settle"
            recovery_decision = recovery.as_dict()
            attempt_probe = None

        elif fault_mode == "after_controller_commit":
            snapshot = controller.snapshot()
            controller_receipt = snapshot["state"]["receipts"].get(invocation.effect_id)
            if not isinstance(controller_receipt, Mapping):
                raise WorkerProtocolError("recovery found no committed controller receipt")
            # Execute the same physical-attempt admission question used by the
            # before-dispatch recovery while the App Server callback remains
            # pending.  A settled binding must reject and stutter; this is an
            # observed controller decision, not an oracle-only counterfactual.
            probe = controller.apply(
                {
                    "op": "retry",
                    "request": f"attempt_{invocation.effect_id}",
                    "effect": invocation.effect_id,
                }
            )
            if probe.accepted:
                raise WorkerProtocolError("settled effect admitted a new physical attempt")
            evidence, body = _query_receipt(invocation, sink)
            if controller_receipt.get("outcome") != body["outcome"]:
                raise WorkerProtocolError("cached controller receipt disagrees with sink")
            return {
                "status": "completed",
                "recovery_action": "return_cached_receipt",
                "dispatch": None,
                "recovery": None,
                "settlement": None,
                "attempt_probe": probe.as_dict(),
                "reply": _reply(invocation, evidence, controller_receipt),
            }

        else:  # Defensive: the supervisor never requests recovery for ``none``.
            raise WorkerProtocolError(f"invalid recovery mode: {fault_mode}")

        controller_receipt = controller.snapshot()["state"]["receipts"].get(
            invocation.effect_id
        )
        if not isinstance(controller_receipt, Mapping):
            raise WorkerProtocolError("recovery settled without a controller receipt")
        if controller_receipt.get("outcome") != body["outcome"]:
            raise WorkerProtocolError("recovered controller receipt disagrees with sink")
        return {
            "status": "completed",
            "recovery_action": action,
            "dispatch": dispatch.as_dict() if dispatch is not None else None,
            "recovery": recovery_decision,
            "settlement": settlement.as_dict(),
            "attempt_probe": attempt_probe,
            "reply": _reply(invocation, evidence, controller_receipt),
        }


def _run_apply(invocation: _ApplyInvocation) -> dict[str, Any]:
    with DurableController(
        invocation.controller_path,
        invocation.policy,
        invocation.grants,
    ) as controller:
        decision = controller.apply(invocation.operation)
        return {
            "status": "completed",
            "decision": decision.as_dict(),
            "controller_snapshot": controller.snapshot(),
        }


def _worker_entry(
    stage: str,
    invocation: _Invocation | _ApplyInvocation,
    fault_mode: str,
    ready_connection: Connection,
    result_connection: Connection,
) -> None:
    # The ready handshake gives the supervisor a distinct startup deadline.
    ready_connection.send({"pid": os.getpid(), "stage": stage})
    ready_connection.close()
    try:
        if stage == "apply" and isinstance(invocation, _ApplyInvocation):
            payload = _run_apply(invocation)
        elif stage == "initial" and isinstance(invocation, _Invocation):
            payload = _run_initial(invocation, fault_mode)
        elif stage == "recovery" and isinstance(invocation, _Invocation):
            payload = _run_recovery(invocation, fault_mode)
        else:
            raise WorkerProtocolError(f"unknown worker stage: {stage}")
    except Exception as error:  # Serialize errors without exposing the HMAC secret.
        result_connection.send(
            {
                "status": "error",
                "error_type": type(error).__name__,
                "error": str(error),
                "traceback": traceback.format_exc(),
            }
        )
        result_connection.close()
        os._exit(_ERROR_EXIT_CODE)
    else:
        result_connection.send(payload)
        result_connection.close()


def _kill_timed_out(process: multiprocessing.Process) -> None:
    if process.is_alive():
        process.terminate()
        process.join(1.0)
    if process.is_alive() and hasattr(process, "kill"):
        process.kill()
        process.join(1.0)


def _run_stage(
    context: multiprocessing.context.BaseContext,
    stage: str,
    invocation: _Invocation | _ApplyInvocation,
    fault_mode: str,
    *,
    startup_timeout_seconds: float,
    stage_timeout_seconds: float,
) -> dict[str, Any]:
    ready_recv, ready_send = context.Pipe(duplex=False)
    result_recv, result_send = context.Pipe(duplex=False)
    work_name = (
        invocation.effect_id
        if isinstance(invocation, _Invocation)
        else str(invocation.operation.get("request", invocation.operation.get("op", "operation")))
    )
    process = context.Process(
        target=_worker_entry,
        args=(stage, invocation, fault_mode, ready_send, result_send),
        name=f"authority-{stage}-{work_name}",
    )
    launched_at = time.monotonic()
    process.start()
    ready_send.close()
    result_send.close()
    try:
        if not ready_recv.poll(startup_timeout_seconds):
            _kill_timed_out(process)
            raise WorkerTimeout(
                f"{stage} worker did not start within {startup_timeout_seconds:.3f}s"
            )
        ready = ready_recv.recv()
        startup_seconds = time.monotonic() - launched_at
        process.join(stage_timeout_seconds)
        if process.is_alive():
            _kill_timed_out(process)
            raise WorkerTimeout(
                f"{stage} worker did not finish within {stage_timeout_seconds:.3f}s"
            )
        payload: dict[str, Any] | None = None
        if result_recv.poll(0.1):
            try:
                value = result_recv.recv()
            except EOFError:
                value = None
            if isinstance(value, dict):
                payload = value
        return {
            "stage": stage,
            "pid": int(ready["pid"]),
            "exitcode": process.exitcode,
            "startup_seconds": startup_seconds,
            "payload": payload,
        }
    finally:
        ready_recv.close()
        result_recv.close()


def _require_success(record: Mapping[str, Any], stage: str) -> dict[str, Any]:
    payload = record.get("payload")
    if record.get("exitcode") != 0 or not isinstance(payload, Mapping):
        raise WorkerError(
            f"{stage} worker failed with exit code {record.get('exitcode')}: {payload!r}"
        )
    if payload.get("status") == "error":
        raise WorkerError(
            f"{stage} worker raised {payload.get('error_type')}: {payload.get('error')}"
        )
    return dict(payload)


def _audit_snapshots(invocation: _Invocation) -> dict[str, Any]:
    """Read both durability domains without using either result for admission."""

    with (
        DurableController(
            invocation.controller_path, invocation.policy, invocation.grants
        ) as controller,
        AuthenticatedSink(invocation.sink_path, invocation.secret) as sink,
    ):
        return {
            "controller": controller.snapshot(),
            "sink": sink.snapshot(),
        }


def _reconstruct_dispatch_decision(
    events: list[Mapping[str, Any]], invocation: _Invocation
) -> dict[str, Any]:
    """Recover an accepted dispatch verdict whose reply died with the worker."""

    for event in reversed(events):
        if event.get("kind") != "dispatch":
            continue
        body = event.get("body")
        operation = body.get("operation") if isinstance(body, Mapping) else None
        if not isinstance(operation, Mapping):
            continue
        if operation.get("effect") != invocation.effect_id:
            continue
        if operation.get("request") != invocation.dispatch_request:
            continue
        return {
            "request": invocation.dispatch_request,
            "operation": "dispatch",
            "decision": "accept",
            "reason": "admitted",
            "abstract_label": "attempt",
            "event_seq": int(event["seq"]),
            "state_hash": str(event["state_hash"]),
        }
    raise WorkerProtocolError("durable log contains no matching dispatch decision")


def supervise_dispatch(
    *,
    controller_path: str | Path,
    sink_path: str | Path,
    secret: bytes,
    policy: str,
    grants: Mapping[str, int] | None = None,
    effect_id: str,
    provider_call_id: str | None,
    request_hash: str,
    outcome: str = "succeeded",
    fault_mode: str = "none",
    dispatch_request: str | None = None,
    settle_request: str | None = None,
    site: str | None = None,
    stage_timeout_seconds: float = DEFAULT_STAGE_TIMEOUT_SECONDS,
    restart_timeout_seconds: float = DEFAULT_RESTART_TIMEOUT_SECONDS,
    start_method: str = "spawn",
) -> dict[str, Any]:
    """Dispatch one effect and recover it after an optional hard crash.

    The controller database must already contain a prepared ticket for
    ``effect_id``.  The returned dictionary is JSON-serializable audit data and
    contains no sink secret.
    """

    if fault_mode not in FAULT_MODES:
        raise ValueError(f"unknown fault mode: {fault_mode}")
    if policy not in POLICIES:
        raise ValueError(f"unknown policy: {policy}")
    if not isinstance(secret, bytes) or not secret:
        raise ValueError("secret must be nonempty bytes")
    if not isinstance(request_hash, str) or not request_hash:
        raise ValueError("request_hash must be a nonempty string")
    if not isinstance(outcome, str) or not outcome:
        raise ValueError("outcome must be a nonempty string")
    if stage_timeout_seconds <= 0 or restart_timeout_seconds <= 0:
        raise ValueError("worker timeouts must be positive")

    resolved_key = stable_key_for(
        policy,
        effect_id=effect_id,
        provider_call_id=provider_call_id,
    )
    invocation = _Invocation(
        controller_path=str(Path(controller_path).resolve()),
        sink_path=str(Path(sink_path).resolve()),
        secret=secret,
        policy=policy,
        grants={str(key): int(value) for key, value in (grants or {}).items()},
        effect_id=effect_id,
        provider_call_id=provider_call_id,
        stable_key=resolved_key,
        request_hash=request_hash,
        outcome=outcome,
        dispatch_request=dispatch_request or f"dispatch_{effect_id}",
        settle_request=settle_request or f"settle_{effect_id}",
        site=site,
    )
    context = multiprocessing.get_context(start_method)
    initial = _run_stage(
        context,
        "initial",
        invocation,
        fault_mode,
        startup_timeout_seconds=restart_timeout_seconds,
        stage_timeout_seconds=stage_timeout_seconds,
    )

    recovery: dict[str, Any] | None = None
    crash_boundary: dict[str, Any] | None = None
    if fault_mode == "none":
        completed = _require_success(initial, "initial")
    else:
        expected_exit = -int(signal.SIGKILL) if hasattr(signal, "SIGKILL") else 137
        if initial["exitcode"] != expected_exit or initial["payload"] is not None:
            raise WorkerError(
                "faulted worker did not terminate at the requested hard-crash boundary: "
                f"exit={initial['exitcode']} payload={initial['payload']!r}"
            )
        crash_boundary = _audit_snapshots(invocation)
        recovery = _run_stage(
            context,
            "recovery",
            invocation,
            fault_mode,
            startup_timeout_seconds=restart_timeout_seconds,
            stage_timeout_seconds=stage_timeout_seconds,
        )
        if recovery["pid"] == initial["pid"]:
            raise WorkerProtocolError("recovery unexpectedly reused the crashed process")
        completed = _require_success(recovery, "recovery")

    with (
        DurableController(
            invocation.controller_path, invocation.policy, invocation.grants
        ) as controller,
        AuthenticatedSink(invocation.sink_path, invocation.secret) as sink,
    ):
        controller_snapshot = controller.snapshot()
        controller_events = controller.events()
        sink_snapshot = sink.snapshot()

    dispatch_decision = completed.get("dispatch")
    if not isinstance(dispatch_decision, Mapping):
        dispatch_decision = _reconstruct_dispatch_decision(
            controller_events, invocation
        )
    else:
        dispatch_decision = dict(dispatch_decision)

    attempts = [
        attempt
        for attempt in sink_snapshot["attempts"]
        if attempt["effect_id"] == effect_id and attempt["stable_key"] == resolved_key
    ]
    outcomes = [
        item
        for item in sink_snapshot["outcomes"]
        if item["effect_id"] == effect_id and item["stable_key"] == resolved_key
    ]
    controller_receipt = controller_snapshot["state"]["receipts"].get(effect_id)
    if completed.get("status") == "completed":
        if len(outcomes) != 1 or not isinstance(controller_receipt, Mapping):
            raise WorkerProtocolError(
                "completed dispatch lacks exactly one sink outcome and controller receipt"
            )
        if len(attempts) != 1:
            raise WorkerProtocolError(
                f"completed dispatch made {len(attempts)} sink attempts instead of one"
            )

    return {
        "status": completed.get("status"),
        "policy": policy,
        "fault_mode": fault_mode,
        "effect_id": effect_id,
        "provider_call_id": provider_call_id,
        "stable_key": resolved_key,
        "request_hash": request_hash,
        "outcome": outcome,
        "initial_worker": initial,
        "recovery_worker": recovery,
        "crash_boundary": crash_boundary,
        "recovery_action": completed.get("recovery_action"),
        "attempt_probe": completed.get("attempt_probe"),
        "dispatch_decision": dispatch_decision,
        "reply": completed.get("reply"),
        "attempt_count": len(attempts),
        "outcome_count": len(outcomes),
        "controller_receipt": controller_receipt,
        "controller_snapshot": controller_snapshot,
        "controller_events": controller_events,
        "sink_snapshot": sink_snapshot,
    }


def apply_in_worker(
    *,
    controller_path: str | Path,
    policy: str,
    grants: Mapping[str, int],
    operation: Mapping[str, Any],
    timeout: float = 5.0,
    start_method: str = "spawn",
) -> dict[str, Any]:
    """Apply one ordinary controller operation in a fresh child process."""

    if policy not in POLICIES:
        raise ValueError(f"unknown policy: {policy}")
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    if not isinstance(operation, Mapping) or not operation.get("op"):
        raise ValueError("operation must contain an op field")
    invocation = _ApplyInvocation(
        controller_path=str(Path(controller_path).resolve()),
        policy=policy,
        grants={str(key): int(value) for key, value in grants.items()},
        operation=dict(operation),
    )
    record = _run_stage(
        multiprocessing.get_context(start_method),
        "apply",
        invocation,
        "none",
        startup_timeout_seconds=timeout,
        stage_timeout_seconds=timeout,
    )
    completed = _require_success(record, "apply")
    return {
        "status": completed["status"],
        "worker": record,
        "decision": completed["decision"],
        "controller_snapshot": completed["controller_snapshot"],
    }


def _derived_request_hash(operation: Mapping[str, Any]) -> str:
    material = {
        str(key): value
        for key, value in operation.items()
        if key not in {"request_hash", "outcome"}
    }
    encoded = json.dumps(
        material,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def dispatch_with_recovery(
    *,
    controller_path: str | Path,
    policy: str,
    grants: Mapping[str, int],
    sink_path: str | Path,
    secret: bytes,
    operation: Mapping[str, Any],
    crash_mode: str,
    provider_call_id: str | None,
    timeout: float = 5.0,
    restart_timeout: float = 5.0,
    request_hash: str | None = None,
    outcome: str = "succeeded",
    start_method: str = "spawn",
) -> dict[str, Any]:
    """Runner-facing wrapper around :func:`supervise_dispatch`.

    ``operation`` is the declarative dispatch operation from the litmus case.
    If the caller does not provide a protected-request hash, a deterministic
    hash of that operation is used; this hash is evidence metadata, not a new
    effect or provider identifier.
    """

    if not isinstance(operation, Mapping) or operation.get("op") != "dispatch":
        raise ValueError("operation must be a dispatch operation")
    effect_id = operation.get("effect")
    if not isinstance(effect_id, str) or not effect_id:
        raise ValueError("dispatch operation requires a stable effect")
    resolved_request_hash = request_hash or operation.get("request_hash")
    if resolved_request_hash is None:
        resolved_request_hash = _derived_request_hash(operation)
    if not isinstance(resolved_request_hash, str) or not resolved_request_hash:
        raise ValueError("request_hash must be a nonempty string")
    request = operation.get("request")
    site = operation.get("site")
    return supervise_dispatch(
        controller_path=controller_path,
        sink_path=sink_path,
        secret=secret,
        policy=policy,
        grants=grants,
        effect_id=effect_id,
        provider_call_id=provider_call_id,
        request_hash=resolved_request_hash,
        outcome=outcome,
        fault_mode=crash_mode,
        dispatch_request=str(request) if request is not None else None,
        site=str(site) if site is not None else None,
        stage_timeout_seconds=timeout,
        restart_timeout_seconds=restart_timeout,
        start_method=start_method,
    )


__all__ = [
    "DEFAULT_RESTART_TIMEOUT_SECONDS",
    "DEFAULT_STAGE_TIMEOUT_SECONDS",
    "FAULT_MODES",
    "WorkerError",
    "WorkerProtocolError",
    "WorkerTimeout",
    "apply_in_worker",
    "dispatch_with_recovery",
    "stable_key_for",
    "supervise_dispatch",
]
