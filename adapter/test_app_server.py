"""Executable preflight and stdlib tests for the real Codex boundary.

Run the full hermetic preflight with::

    python -m adapter.test_app_server

The preflight launches the installed ``codex app-server --stdio`` process but
routes every model request to :class:`DeterministicResponsesServer` on
loopback.  It creates and archives one persistent seed thread, forks an
ephemeral child at the seed's exact turn id, and exposes the real pending
dynamic-tool callback to a caller-supplied handler before answering it.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
import posixpath
import shutil
import tempfile
import threading
import time
from typing import Any, Callable, Mapping, Sequence, cast
import unittest
from urllib.request import Request, urlopen

from adapter.app_server import (
    RPC_TIMEOUT_SECONDS,
    TURN_TIMEOUT_SECONDS,
    AppServerProtocolError,
    CodexAppServer,
    MCPStdioServer,
    PendingToolCall,
)
from adapter.mock_responses import DeterministicResponsesServer


_PREFLIGHT_EFFECT_ID = "preflight-effect-1"
_PREFLIGHT_CALL_ID = "preflight-call-1"
_PREFLIGHT_EDIT_CALL_ID = "preflight-edit-1"
_PREFLIGHT_VALIDATION_CALL_ID = "preflight-validation-1"
_MAX_WORKSPACE_PATCH_BYTES = 1 << 20
_MAX_WORKSPACE_VALIDATION_COMMAND_BYTES = 64 << 10
_MAX_PREFLIGHT_PROTECTED_CALLS = 8


@dataclass(frozen=True)
class ProtectedCallResult:
    """Identity of one protected callback completed in the preflight turn."""

    request_id: int | str
    call_id: str
    effect_id: str


@dataclass(frozen=True)
class PreflightResult:
    """Machine-readable evidence returned by :func:`run_preflight`."""

    ok: bool
    codex_binary: str
    initialize_result: Mapping[str, Any]
    seed_thread_id: str
    seed_turn_id: str
    fork_thread_id: str
    protected_turn_id: str
    call_id: str
    effect_id: str
    seed_archived: bool
    responses_request_count: int
    models_request_count: int
    raw_record_count: int
    raw_jsonl_path: str
    workspace_edit_call_id: str | None = None
    workspace_patch_sha256: str | None = None
    workspace_validation_call_id: str | None = None
    workspace_validation_command_sha256: str | None = None
    protected_calls: tuple[ProtectedCallResult, ...] = ()
    mcp_effect_ids: tuple[str, ...] = ()


ToolHandler = Callable[[PendingToolCall], None]


def _default_tool_handler(pending: PendingToolCall) -> None:
    pending.respond_text(f"receipt:{pending.arguments['effect_id']}")


def _read_raw_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise AssertionError(
                    f"invalid raw JSONL at {path}:{line_number}: {error}"
                ) from error
            if not isinstance(record, dict):
                raise AssertionError(
                    f"raw JSONL record {line_number} is not an object"
                )
            records.append(record)
    if not records:
        raise AssertionError(f"raw JSONL capture is empty: {path}")
    expected_sequences = list(range(1, len(records) + 1))
    actual_sequences = [record.get("sequence") for record in records]
    if actual_sequences != expected_sequences:
        raise AssertionError("raw JSONL sequence numbers are not contiguous")
    return records


def _has_message(
    records: Sequence[Mapping[str, Any]],
    direction: str,
    predicate: Callable[[Mapping[str, Any]], bool],
) -> bool:
    for record in records:
        if record.get("direction") != direction:
            continue
        payload = record.get("payload")
        if isinstance(payload, dict) and predicate(payload):
            return True
    return False


def _validate_raw_protocol(
    records: Sequence[Mapping[str, Any]],
    *,
    seed_thread_id: str,
    seed_turn_id: str,
    fork_thread_id: str,
    protected_turn_id: str,
    protected_calls: Sequence[ProtectedCallResult],
    sandbox: str,
    workspace_edit_call_id: str | None,
    workspace_validation_call_id: str | None,
    mcp_effect_ids: Sequence[str] = (),
) -> None:
    checks = {
        "experimental initialize": _has_message(
            records,
            "client_to_server",
            lambda payload: payload.get("method") == "initialize"
            and payload.get("params", {}).get("capabilities", {}).get(
                "experimentalApi"
            )
            is True,
        ),
        "persistent dynamic-tool seed": _has_message(
            records,
            "client_to_server",
            lambda payload: payload.get("method") == "thread/start"
            and payload.get("params", {}).get("ephemeral") is False
            and payload.get("params", {}).get("sandbox") == sandbox
            and any(
                tool.get("name") == "protected_commit"
                for tool in payload.get("params", {}).get("dynamicTools", [])
                if isinstance(tool, dict)
            ),
        ),
        "exact native fork": _has_message(
            records,
            "client_to_server",
            lambda payload: payload.get("method") == "thread/fork"
            and payload.get("params", {}).get("threadId") == seed_thread_id
            and payload.get("params", {}).get("lastTurnId") == seed_turn_id
            and payload.get("params", {}).get("ephemeral") is True,
        ),
    }
    for index, protected in enumerate(protected_calls, start=1):
        checks[f"real pending callback {index}"] = _has_message(
            records,
            "server_to_client",
            lambda payload, protected=protected: payload.get("method")
            == "item/tool/call"
            and payload.get("id") == protected.request_id
            and payload.get("params", {}).get("threadId") == fork_thread_id
            and payload.get("params", {}).get("turnId") == protected_turn_id
            and payload.get("params", {}).get("tool") == "protected_commit"
            and payload.get("params", {}).get("callId") == protected.call_id
            and payload.get("params", {}).get("arguments")
            == {"effect_id": protected.effect_id},
        )
        checks[f"callback response {index}"] = _has_message(
            records,
            "client_to_server",
            lambda payload, protected=protected: payload.get("id")
            == protected.request_id
            and isinstance(payload.get("result"), dict),
        )
    if workspace_edit_call_id is not None:
        checks.update(
            {
                "external sandbox boundary": _has_message(
                    records,
                    "client_to_server",
                    lambda payload: payload.get("method") == "turn/start"
                    and payload.get("params", {}).get("threadId") == fork_thread_id
                    and payload.get("params", {}).get("approvalPolicy") == "never"
                    and payload.get("params", {}).get("sandboxPolicy")
                    == {
                        "type": "externalSandbox",
                        "networkAccess": "restricted",
                    },
                ),
                "completed native workspace edit": _has_message(
                    records,
                    "server_to_client",
                    lambda payload: payload.get("method") == "item/completed"
                    and payload.get("params", {}).get("threadId") == fork_thread_id
                    and payload.get("params", {}).get("turnId")
                    == protected_turn_id
                    and payload.get("params", {}).get("item", {}).get("id")
                    == workspace_edit_call_id
                    and payload.get("params", {}).get("item", {}).get("type")
                    == "fileChange"
                    and payload.get("params", {}).get("item", {}).get("status")
                    == "completed",
                ),
            }
        )
    if workspace_validation_call_id is not None:
        checks["completed workspace validation"] = _has_message(
            records,
            "server_to_client",
            lambda payload: payload.get("method") == "item/completed"
            and payload.get("params", {}).get("threadId") == fork_thread_id
            and payload.get("params", {}).get("turnId") == protected_turn_id
            and payload.get("params", {}).get("item", {}).get("id")
            == workspace_validation_call_id
            and payload.get("params", {}).get("item", {}).get("type")
            == "commandExecution"
            and payload.get("params", {}).get("item", {}).get("status")
            == "completed"
            and payload.get("params", {}).get("item", {}).get("exitCode") == 0,
        )
    if mcp_effect_ids:
        completions: list[tuple[int, str, str, str]] = []
        callback_sequence: int | None = None
        for record in records:
            sequence = record.get("sequence")
            payload = record.get("payload")
            if not isinstance(sequence, int) or not isinstance(payload, dict):
                continue
            params = payload.get("params")
            if not isinstance(params, dict):
                continue
            if (
                record.get("direction") == "server_to_client"
                and payload.get("method") == "item/tool/call"
                and params.get("threadId") == fork_thread_id
                and params.get("turnId") == protected_turn_id
            ):
                callback_sequence = sequence
            item = params.get("item")
            if (
                record.get("direction") == "server_to_client"
                and payload.get("method") == "item/completed"
                and isinstance(item, dict)
                and item.get("type") == "mcpToolCall"
                and item.get("status") == "completed"
                and item.get("server") == "continuity"
                and item.get("tool") == "commit_effect"
                and isinstance(item.get("arguments"), dict)
                and isinstance(item["arguments"].get("effect_id"), str)
            ):
                thread_id = params.get("threadId")
                turn_id = params.get("turnId")
                if isinstance(thread_id, str) and isinstance(turn_id, str):
                    completions.append(
                        (sequence, item["arguments"]["effect_id"], thread_id, turn_id)
                    )
        expected_mcp_effects = [mcp_effect_ids[0], *mcp_effect_ids]
        if (
            callback_sequence is None
            or [effect for _, effect, _, _ in completions]
            != expected_mcp_effects
            or len(completions) != 3
            or not (
                completions[0][0]
                < callback_sequence
                < completions[1][0]
                < completions[2][0]
            )
            or completions[0][2:] != (fork_thread_id, protected_turn_id)
            or completions[1][2] == fork_thread_id
            or completions[1][2:] != completions[2][2:]
        ):
            raise AssertionError(
                "MCP calls did not replay then advance across the VM checkpoint"
            )
    missing = [name for name, present in checks.items() if not present]
    if missing:
        raise AssertionError(
            "raw JSONL capture omitted protocol evidence: " + ", ".join(missing)
        )


def _validate_workspace_gate(
    records: Sequence[Mapping[str, Any]],
    *,
    fork_thread_id: str,
    protected_turn_id: str,
    callback_request_id: int | str,
    workspace_edit_call_id: str,
    workspace_validation_call_id: str | None,
    workspace_validation_command: str | None,
    workspace_validation_shell: str | None,
) -> None:
    edit_sequence: int | None = None
    validation_sequence: int | None = None
    callback_sequence: int | None = None
    edit_occurrences = 0
    validation_occurrences = 0
    callback_occurrences = 0
    for record in records:
        sequence = record.get("sequence")
        payload = record.get("payload")
        if not isinstance(sequence, int) or not isinstance(payload, dict):
            continue
        params = payload.get("params")
        if not isinstance(params, dict):
            continue
        if (
            record.get("direction") == "server_to_client"
            and payload.get("method") == "item/tool/call"
            and payload.get("id") == callback_request_id
            and params.get("threadId") == fork_thread_id
            and params.get("turnId") == protected_turn_id
        ):
            callback_occurrences += 1
            callback_sequence = sequence
        if (
            record.get("direction") != "server_to_client"
            or payload.get("method") != "item/completed"
            or params.get("threadId") != fork_thread_id
            or params.get("turnId") != protected_turn_id
        ):
            continue
        item = params.get("item")
        if not isinstance(item, dict):
            continue
        if item.get("id") == workspace_edit_call_id:
            edit_occurrences += 1
            changes = item.get("changes")
            if (
                item.get("type") == "fileChange"
                and item.get("status") == "completed"
                and isinstance(changes, list)
                and changes
            ):
                edit_sequence = sequence
        if (
            workspace_validation_call_id is not None
            and item.get("id") == workspace_validation_call_id
        ):
            validation_occurrences += 1
            actions = item.get("commandActions")
            action_command: str | None = None
            if isinstance(actions, list) and len(actions) == 1:
                action = actions[0]
                if isinstance(action, dict) and isinstance(action.get("command"), str):
                    action_command = action["command"]
            command = item.get("command")
            shell_prefix = (
                workspace_validation_shell + " -c "
                if workspace_validation_shell is not None
                else None
            )
            if (
                item.get("type") == "commandExecution"
                and item.get("status") == "completed"
                and item.get("exitCode") == 0
                and action_command == workspace_validation_command
                and isinstance(command, str)
                and shell_prefix is not None
                and command.startswith(shell_prefix)
            ):
                validation_sequence = sequence
    if callback_sequence is None or callback_occurrences != 1:
        raise AssertionError(
            "workspace gate did not observe exactly one protected callback"
        )
    if (
        edit_sequence is None
        or edit_occurrences != 1
        or edit_sequence >= callback_sequence
    ):
        raise AssertionError(
            "workspace gate did not observe a completed native edit before the "
            "protected callback"
        )
    if workspace_validation_call_id is not None and (
        validation_sequence is None
        or validation_occurrences != 1
        or edit_sequence >= validation_sequence
        or validation_sequence >= callback_sequence
    ):
        raise AssertionError(
            "workspace gate did not observe a successful declared validation "
            "between the native edit and protected callback"
        )


def _wait_mcp_ready(
    client: CodexAppServer, thread_id: str, server_name: str
) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        event = client.wait_for_message(
            lambda message: (
                message.get("method") == "mcpServer/startupStatus/updated"
                and isinstance(message.get("params"), dict)
                and message["params"].get("name") == server_name
                and message["params"].get("threadId") == thread_id
            ),
            description=f"MCP startup for {server_name}",
            timeout=max(0.1, deadline - time.monotonic()),
        )
        status = event["params"].get("status")
        if status in {"ready", "completed"}:
            return
        if status in {"failed", "error"}:
            raise AppServerProtocolError(
                f"MCP server {server_name} failed to start: {event!r}"
            )
    raise AppServerProtocolError(f"MCP server {server_name} did not become ready")


def _find_mcp_callable(
    request: Mapping[str, Any], server_name: str, tool_name: str
) -> str:
    metadata = request.get("client_metadata")
    encoded = (
        metadata.get("x-codex-turn-metadata")
        if isinstance(metadata, dict)
        else None
    )
    if not isinstance(encoded, str):
        raise AppServerProtocolError("model request omitted MCP tool metadata")
    try:
        turn_metadata = json.loads(encoded)
    except json.JSONDecodeError as error:
        raise AppServerProtocolError("model request has malformed MCP metadata") from error
    names = (
        turn_metadata.get("code_mode_tool_names")
        if isinstance(turn_metadata, dict)
        else None
    )
    if not isinstance(names, dict):
        raise AppServerProtocolError("model request omitted MCP callable names")
    matches = [
        callable_name
        for callable_name, descriptor in names.items()
        if isinstance(callable_name, str)
        and descriptor
        == {"name": tool_name, "namespace": "mcp__" + server_name}
    ]
    if len(matches) != 1:
        raise AppServerProtocolError(
            f"model request exposed {len(matches)} matching MCP callables"
        )
    return matches[0]


def _enqueue_mcp_effect(
    responses: DeterministicResponsesServer,
    callable_name: str,
    effect_id: str,
    call_id: str,
) -> None:
    arguments = json.dumps(
        {"effect_id": effect_id}, sort_keys=True, separators=(",", ":")
    )
    responses.enqueue_custom_tool_call(
        "exec",
        f"const outcome = await tools.{callable_name}({arguments}); text(outcome);",
        call_id=call_id,
        response_id="fixture-" + call_id,
    )


def run_preflight(
    *,
    codex_binary: str = "codex",
    workspace: str | Path | None = None,
    raw_jsonl_path: str | Path | None = None,
    tool_handler: ToolHandler | None = None,
    archive_seed: bool = True,
    workspace_patch: str | None = None,
    workspace_validation_command: str | None = None,
    workspace_validation_shell: str | None = None,
    protected_effect_ids: Sequence[str] | None = None,
    mcp_server: MCPStdioServer | None = None,
    mcp_effect_ids: Sequence[str] | None = None,
    mcp_inflight_wait: Callable[[], None] | None = None,
) -> PreflightResult:
    """Run one deterministic end-to-end App Server boundary preflight.

    ``tool_handler`` receives the pending ``item/tool/call`` before the client
    sends any callback response.  The handler must call ``pending.respond`` or
    ``pending.respond_text``; a handler that returns without doing so fails
    closed.  No controller, replay checker, or oracle is imported here.
    """

    workspace_path = Path.cwd() if workspace is None else Path(workspace)
    effect_ids = (
        (_PREFLIGHT_EFFECT_ID,)
        if protected_effect_ids is None
        else tuple(protected_effect_ids)
    )
    mcp_effects = () if mcp_effect_ids is None else tuple(mcp_effect_ids)
    mcp_inflight = mcp_inflight_wait is not None
    if (mcp_server is None) != (len(mcp_effects) == 0):
        raise ValueError("MCP preflight requires both a server and effect identities")
    if mcp_effects and (
        len(mcp_effects) != 2
        or len(set(mcp_effects)) != 2
        or any(not isinstance(effect, str) or not effect for effect in mcp_effects)
        or len(effect_ids) != 1
    ):
        raise ValueError(
            "MCP checkpoint preflight requires two unique MCP effects and one protected callback"
        )
    if mcp_inflight and (not mcp_effects or workspace_patch is not None):
        raise ValueError(
            "in-flight MCP checkpoint requires MCP effects and no workspace edit"
        )
    if not 1 <= len(effect_ids) <= _MAX_PREFLIGHT_PROTECTED_CALLS:
        raise ValueError(
            "preflight requires 1 to "
            f"{_MAX_PREFLIGHT_PROTECTED_CALLS} protected effects"
        )
    if len(set(effect_ids)) != len(effect_ids) or any(
        not isinstance(effect_id, str) or not effect_id for effect_id in effect_ids
    ):
        raise ValueError("preflight protected effect identities must be nonempty and unique")
    expected_call_ids = tuple(
        f"preflight-call-{index}" for index in range(1, len(effect_ids) + 1)
    )
    if workspace_patch is not None:
        encoded_patch = workspace_patch.encode("utf-8")
        if not encoded_patch or len(encoded_patch) > _MAX_WORKSPACE_PATCH_BYTES:
            raise ValueError(
                "workspace patch must contain 1 to "
                f"{_MAX_WORKSPACE_PATCH_BYTES} UTF-8 bytes"
            )
        workspace_patch_digest = sha256(encoded_patch).hexdigest()
        sandbox = "workspace-write"
    else:
        workspace_patch_digest = None
        sandbox = "read-only"
    if (workspace_validation_command is None) != (
        workspace_validation_shell is None
    ):
        raise ValueError(
            "workspace validation command and shell must be supplied together"
        )
    if workspace_validation_command is not None:
        if workspace_patch is None:
            raise ValueError("workspace validation requires a workspace patch")
        encoded_command = workspace_validation_command.encode("utf-8")
        if (
            not encoded_command
            or len(encoded_command) > _MAX_WORKSPACE_VALIDATION_COMMAND_BYTES
            or b"\x00" in encoded_command
        ):
            raise ValueError(
                "workspace validation command must contain 1 to "
                f"{_MAX_WORKSPACE_VALIDATION_COMMAND_BYTES} NUL-free UTF-8 bytes"
            )
        assert workspace_validation_shell is not None
        shell_path = Path(workspace_validation_shell)
        if (
            not shell_path.is_absolute()
            or posixpath.normpath(workspace_validation_shell)
            != workspace_validation_shell
            or "\x00" in workspace_validation_shell
        ):
            raise ValueError(
                "workspace validation shell must be an absolute canonical path"
            )
        validation_command_digest = sha256(encoded_command).hexdigest()
    else:
        validation_command_digest = None
    if raw_jsonl_path is None:
        capture_dir = Path(tempfile.mkdtemp(prefix="codex-boundary-preflight-"))
        raw_path = capture_dir / "app-server.jsonl"
    else:
        raw_path = Path(raw_jsonl_path)
    handler = tool_handler or _default_tool_handler

    seed_thread_id: str | None = None
    seed_turn_id: str | None = None
    fork_thread_id: str | None = None
    protected_turn_id: str | None = None
    protected_calls: list[ProtectedCallResult] = []
    mcp_inflight_thread_id: str | None = None
    mcp_inflight_turn_id: str | None = None
    initialize_result: dict[str, Any] | None = None
    seed_archived = False
    inflight_waiter: threading.Thread | None = None
    inflight_errors: list[Exception] = []

    with DeterministicResponsesServer() as responses:
        responses.enqueue_assistant(
            "seed acknowledged", response_id="fixture-seed-response"
        )
        client = CodexAppServer(
            model_base_url=responses.base_url,
            workspace=workspace_path,
            raw_jsonl_path=raw_path,
            codex_binary=codex_binary,
            rpc_timeout=RPC_TIMEOUT_SECONDS,
            turn_timeout=TURN_TIMEOUT_SECONDS,
            mcp_server=mcp_server,
        )
        with client:
            initialize_result = dict(client.initialize_result or {})
            try:
                seed = client.create_seed_thread(sandbox=sandbox)
                seed_thread_id = seed["id"]
                if mcp_server is not None:
                    _wait_mcp_ready(client, seed_thread_id, mcp_server.name)
                seed_turn_id, _ = client.start_turn_and_wait(
                    seed_thread_id,
                    "Acknowledge this deterministic seed turn.",
                    timeout=TURN_TIMEOUT_SECONDS,
                )

                callable_name: str | None = None
                if mcp_server is not None:
                    model_requests = [
                        request
                        for request in responses.requests
                        if request.method == "POST"
                        and request.path.endswith("/responses")
                    ]
                    if len(model_requests) != 1:
                        raise AppServerProtocolError(
                            "MCP discovery did not make exactly one model request"
                        )
                    callable_name = _find_mcp_callable(
                        model_requests[0].body,
                        mcp_server.name,
                        mcp_server.enabled_tools[0],
                    )

                if workspace_patch is not None:
                    responses.enqueue_custom_tool_call(
                        "apply_patch",
                        workspace_patch,
                        call_id=_PREFLIGHT_EDIT_CALL_ID,
                        response_id="fixture-edit-response",
                    )
                if workspace_validation_command is not None:
                    assert workspace_validation_shell is not None
                    responses.enqueue_tool_call(
                        "exec_command",
                        {
                            "cmd": workspace_validation_command,
                            "workdir": ".",
                            "shell": workspace_validation_shell,
                            "login": False,
                            "yield_time_ms": 10_000,
                            "max_output_tokens": 1_000,
                        },
                        call_id=_PREFLIGHT_VALIDATION_CALL_ID,
                        response_id="fixture-validation-response",
                    )
                if callable_name is not None:
                    _enqueue_mcp_effect(
                        responses, callable_name, mcp_effects[0], "preflight-mcp-call-1"
                    )
                if mcp_inflight:
                    assert callable_name is not None
                    assert mcp_inflight_wait is not None
                    inflight_fork = client.fork_at_turn(seed_thread_id, seed_turn_id)
                    mcp_inflight_thread_id = inflight_fork["id"]
                    mcp_inflight_turn_id = client.start_turn(
                        mcp_inflight_thread_id,
                        "Commit the protected MCP operation and wait for its result.",
                    )

                    def wait_inflight_turn() -> None:
                        try:
                            client.wait_turn_completed(
                                mcp_inflight_thread_id,
                                mcp_inflight_turn_id,
                                timeout=TURN_TIMEOUT_SECONDS,
                            )
                        except Exception as error:
                            inflight_errors.append(error)

                    inflight_waiter = threading.Thread(
                        target=wait_inflight_turn,
                        name="codex-inflight-mcp-turn",
                    )
                    inflight_waiter.start()
                    mcp_inflight_wait()
                for index, (call_id, effect_id) in enumerate(
                    zip(expected_call_ids, effect_ids, strict=True), start=1
                ):
                    responses.enqueue_tool_call(
                        "protected_commit",
                        {"effect_id": effect_id},
                        call_id=call_id,
                        response_id=f"fixture-tool-response-{index}",
                    )
                responses.enqueue_assistant(
                    "protected commit acknowledged",
                    response_id="fixture-final-response",
                )

                if mcp_inflight:
                    # The seed already owns an initialized MCP transport.  A
                    # third thread would block its MCP startup behind the
                    # deliberately unresolved protected request.
                    fork_thread_id = seed_thread_id
                else:
                    fork = client.fork_at_turn(seed_thread_id, seed_turn_id)
                    fork_thread_id = fork["id"]

                pending = client.start_protected_turn(
                    fork_thread_id,
                    "Call protected_commit in order for "
                    + ", ".join(effect_ids)
                    + ", then finish.",
                    expected_tool="protected_commit",
                    expected_arguments={"effect_id": effect_ids[0]},
                    approval_policy=("never" if workspace_patch is not None else None),
                    sandbox_policy=(
                        {
                            "type": "externalSandbox",
                            "networkAccess": "restricted",
                        }
                        if workspace_patch is not None
                        else None
                    ),
                    timeout=TURN_TIMEOUT_SECONDS,
                )
                protected_turn_id = pending.turn_id
                protected_calls.append(
                    ProtectedCallResult(
                        request_id=pending.request_id,
                        call_id=pending.call_id,
                        effect_id=effect_ids[0],
                    )
                )

                if workspace_patch is not None:
                    gate_records = _read_raw_jsonl(raw_path.resolve())
                    _validate_workspace_gate(
                        gate_records,
                        fork_thread_id=fork_thread_id,
                        protected_turn_id=protected_turn_id,
                        callback_request_id=pending.request_id,
                        workspace_edit_call_id=_PREFLIGHT_EDIT_CALL_ID,
                        workspace_validation_call_id=(
                            _PREFLIGHT_VALIDATION_CALL_ID
                            if workspace_validation_command is not None
                            else None
                        ),
                        workspace_validation_command=workspace_validation_command,
                        workspace_validation_shell=workspace_validation_shell,
                    )

                # This is the experiment seam: the real App Server and its
                # pending callback remain alive while caller-owned logic runs.
                handler(pending)
                for call_id, effect_id in zip(
                    expected_call_ids[1:], effect_ids[1:], strict=True
                ):
                    pending = client.wait_protected_call(
                        fork_thread_id,
                        protected_turn_id,
                        expected_tool="protected_commit",
                        expected_arguments={"effect_id": effect_id},
                        timeout=TURN_TIMEOUT_SECONDS,
                    )
                    protected_calls.append(
                        ProtectedCallResult(
                            request_id=pending.request_id,
                            call_id=pending.call_id,
                            effect_id=effect_id,
                        )
                    )
                    if pending.call_id != call_id:
                        raise AppServerProtocolError(
                            "dynamic tool call order changed: "
                            f"expected={call_id!r} actual={pending.call_id!r}"
                        )
                    handler(pending)
                pending.wait_turn_completed(timeout=TURN_TIMEOUT_SECONDS)
                if inflight_waiter is not None:
                    inflight_waiter.join(TURN_TIMEOUT_SECONDS)
                    if inflight_waiter.is_alive():
                        raise AppServerProtocolError(
                            "in-flight MCP turn remained live after VM replacement"
                        )
                    if len(inflight_errors) != 1 or not isinstance(
                        inflight_errors[0], AppServerProtocolError
                    ):
                        raise AppServerProtocolError(
                            "in-flight MCP turn did not fail at the replaced transport"
                        )
                if callable_name is not None:
                    assert mcp_server is not None
                    restored_thread = client.create_mcp_thread(sandbox=sandbox)
                    _wait_mcp_ready(client, restored_thread["id"], mcp_server.name)
                    _enqueue_mcp_effect(
                        responses,
                        callable_name,
                        mcp_effects[0],
                        "preflight-mcp-replay-1",
                    )
                    _enqueue_mcp_effect(
                        responses,
                        callable_name,
                        mcp_effects[1],
                        "preflight-mcp-call-2",
                    )
                    responses.enqueue_assistant(
                        "post-restore MCP operation acknowledged",
                        response_id="fixture-post-restore-response",
                    )
                    client.start_turn_and_wait(
                        restored_thread["id"],
                        "Commit the post-restore protected operation.",
                        timeout=TURN_TIMEOUT_SECONDS,
                    )
                client.assert_hermetic_runtime()
            finally:
                if seed_thread_id is not None and archive_seed:
                    client.archive_thread(seed_thread_id)
                    seed_archived = True

        responses.assert_consumed()
        response_count = responses.responses_request_count
        models_count = responses.models_request_count
        expected_response_count = (
            2 + len(effect_ids)
            + int(workspace_patch is not None)
            + int(workspace_validation_command is not None)
            + len(mcp_effects)
            + 2 * int(bool(mcp_effects))
        )
        if response_count != expected_response_count:
            raise AssertionError(
                "preflight expected exactly "
                f"{expected_response_count} local Responses requests; "
                f"observed {response_count}"
            )

    required_values = {
        "initialize_result": initialize_result,
        "seed_thread_id": seed_thread_id,
        "seed_turn_id": seed_turn_id,
        "fork_thread_id": fork_thread_id,
        "protected_turn_id": protected_turn_id,
        "protected_calls": protected_calls or None,
    }
    missing_values = [name for name, value in required_values.items() if value is None]
    if missing_values:
        raise AppServerProtocolError(
            "preflight completed without required values: " + ", ".join(missing_values)
        )
    actual_call_ids = tuple(item.call_id for item in protected_calls)
    if actual_call_ids != expected_call_ids:
        raise AppServerProtocolError(
            f"dynamic tool call ids changed: expected={expected_call_ids!r} "
            f"actual={actual_call_ids!r}"
        )
    if archive_seed and not seed_archived:
        raise AppServerProtocolError("persistent preflight seed was not archived")

    # The explicit missing-value check above establishes these casts at
    # runtime; unlike ``assert``, it is retained under optimized Python.
    initialize_result = cast(dict[str, Any], initialize_result)
    seed_thread_id = cast(str, seed_thread_id)
    seed_turn_id = cast(str, seed_turn_id)
    fork_thread_id = cast(str, fork_thread_id)
    protected_turn_id = cast(str, protected_turn_id)
    first_call = protected_calls[0]

    records = _read_raw_jsonl(raw_path.resolve())
    _validate_raw_protocol(
        records,
        seed_thread_id=seed_thread_id,
        seed_turn_id=seed_turn_id,
        fork_thread_id=fork_thread_id,
        protected_turn_id=protected_turn_id,
        protected_calls=protected_calls,
        sandbox=sandbox,
        workspace_edit_call_id=(
            _PREFLIGHT_EDIT_CALL_ID if workspace_patch is not None else None
        ),
        workspace_validation_call_id=(
            _PREFLIGHT_VALIDATION_CALL_ID
            if workspace_validation_command is not None
            else None
        ),
        mcp_effect_ids=mcp_effects,
    )
    return PreflightResult(
        ok=True,
        codex_binary=str(Path(shutil.which(codex_binary) or codex_binary).resolve()),
        initialize_result=initialize_result,
        seed_thread_id=seed_thread_id,
        seed_turn_id=seed_turn_id,
        fork_thread_id=fork_thread_id,
        protected_turn_id=protected_turn_id,
        call_id=first_call.call_id,
        effect_id=first_call.effect_id,
        seed_archived=seed_archived,
        responses_request_count=response_count,
        models_request_count=models_count,
        raw_record_count=len(records),
        raw_jsonl_path=str(raw_path.resolve()),
        workspace_edit_call_id=(
            _PREFLIGHT_EDIT_CALL_ID if workspace_patch is not None else None
        ),
        workspace_patch_sha256=workspace_patch_digest,
        workspace_validation_call_id=(
            _PREFLIGHT_VALIDATION_CALL_ID
            if workspace_validation_command is not None
            else None
        ),
        workspace_validation_command_sha256=validation_command_digest,
        protected_calls=tuple(protected_calls),
        mcp_effect_ids=mcp_effects,
    )


class DeterministicResponsesServerTests(unittest.TestCase):
    def test_private_bridge_binding_requires_explicit_opt_in(self) -> None:
        with self.assertRaisesRegex(ValueError, "explicit private Docker bridge"):
            DeterministicResponsesServer(host="172.20.0.1")
        server = DeterministicResponsesServer(
            host="172.20.0.1", allow_private_bridge=True
        )
        self.assertEqual(server.pending_fixture_count, 0)
        with self.assertRaisesRegex(ValueError, "loopback or an IPv4 literal"):
            DeterministicResponsesServer(host="model.internal", allow_private_bridge=True)

    def test_models_and_fifo_sse_fixtures(self) -> None:
        with DeterministicResponsesServer() as server:
            server.enqueue_assistant("hello", response_id="response-assistant")
            server.enqueue_tool_call(
                "protected_commit",
                {"effect_id": "effect-test"},
                call_id="call-test",
                response_id="response-tool",
            )

            with urlopen(server.base_url + "/models", timeout=2.0) as response:
                self.assertEqual(json.load(response), {"models": []})

            bodies: list[str] = []
            for _ in range(2):
                request = Request(
                    server.base_url + "/responses",
                    data=b'{"stream":true}',
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(request, timeout=2.0) as response:
                    bodies.append(response.read().decode("utf-8"))

            server.assert_consumed()
            self.assertEqual(server.models_request_count, 1)
            self.assertEqual(server.responses_request_count, 2)
            self.assertIn("response-assistant", bodies[0])
            self.assertIn('"type":"message"', bodies[0])
            self.assertIn("response-tool", bodies[1])
            self.assertIn('"call_id":"call-test"', bodies[1])
            self.assertIn('"name":"protected_commit"', bodies[1])

    def test_custom_tool_fixture_uses_official_responses_shape(self) -> None:
        patch = "*** Begin Patch\n*** Add File: proof.txt\n+proof\n*** End Patch\n"
        with DeterministicResponsesServer() as server:
            server.enqueue_custom_tool_call(
                "apply_patch",
                patch,
                call_id="patch-call",
                response_id="response-patch",
            )
            request = Request(
                server.base_url + "/responses",
                data=b'{"stream":true}',
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=2.0) as response:
                body = response.read().decode("utf-8")
            server.assert_consumed()
        self.assertIn('"type":"custom_tool_call"', body)
        self.assertIn('"name":"apply_patch"', body)
        self.assertIn('"call_id":"patch-call"', body)
        self.assertIn(json.dumps(patch, separators=(",", ":")), body)


class CodexAppServerModeTests(unittest.TestCase):
    def test_private_model_endpoint_requires_explicit_docker_opt_in(self) -> None:
        with tempfile.TemporaryDirectory(prefix="codex-private-model-") as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "unauthenticated local HTTP"):
                CodexAppServer(
                    model_base_url="http://172.20.0.1:8080/v1",
                    workspace=root,
                    raw_jsonl_path=root / "rejected.jsonl",
                )
            client = CodexAppServer(
                model_base_url="http://172.20.0.1:8080/v1",
                allow_private_model_endpoint=True,
                workspace=root,
                raw_jsonl_path=root / "accepted.jsonl",
            )
            self.assertEqual(client.model_base_url, "http://172.20.0.1:8080/v1")

    def test_explicit_mcp_command_is_bounded_and_default_remains_empty(self) -> None:
        with tempfile.TemporaryDirectory(prefix="codex-mcp-config-test-") as directory:
            root = Path(directory)
            executable = root / "mcp-server"
            executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            executable.chmod(0o500)
            mcp = MCPStdioServer(
                name="continuity",
                command=executable,
                args=("-config", "/operator/tools.json"),
                enabled_tools=("commit_effect",),
                runtime_command="/opt/codex/bin/mcp-operation-relay",
            )
            client = CodexAppServer(
                model_base_url="http://127.0.0.1:1",
                workspace=root,
                raw_jsonl_path=root / "mcp.jsonl",
                mcp_server=mcp,
            )
            command = client._command()
            joined = " ".join(command)
            self.assertIn("mcp_servers={}", command)
            self.assertIn("mcp_servers.continuity=", joined)
            self.assertIn(
                'command="/opt/codex/bin/mcp-operation-relay"', joined
            )
            self.assertNotIn(str(executable), joined)
            self.assertIn('enabled_tools=["commit_effect"]', joined)
            self.assertIn('approval_mode="approve"', joined)
            self.assertNotIn("env=", joined)
            self.assertNotIn("bearer", joined)

            default = CodexAppServer(
                model_base_url="http://127.0.0.1:1",
                workspace=root,
                raw_jsonl_path=root / "default.jsonl",
            )
            self.assertIn("mcp_servers={}", default._command())
            self.assertFalse(any("mcp_servers.continuity" in item for item in default._command()))

    def test_mcp_configuration_rejects_untrusted_command_and_unbounded_inputs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="codex-mcp-config-test-") as directory:
            root = Path(directory)
            executable = root / "mcp-server"
            executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            executable.chmod(0o500)
            with self.assertRaisesRegex(ValueError, "absolute canonical"):
                MCPStdioServer(
                    name="continuity",
                    command="relative-server",
                    args=("-serve",),
                    enabled_tools=("commit_effect",),
                )
            with self.assertRaisesRegex(ValueError, "tool allow list"):
                MCPStdioServer(
                    name="continuity",
                    command=executable,
                    args=("-serve",),
                    enabled_tools=(),
                )
            with self.assertRaisesRegex(ValueError, "runtime command"):
                MCPStdioServer(
                    name="continuity",
                    command=executable,
                    args=("-serve",),
                    enabled_tools=("commit_effect",),
                    runtime_command="relative/server",
                )

    def test_logged_in_account_requires_explicit_opt_in(self) -> None:
        with tempfile.TemporaryDirectory(prefix="codex-mode-test-") as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "explicit logged-in account"):
                CodexAppServer(
                    model_base_url=None,
                    workspace=root,
                    raw_jsonl_path=root / "implicit.jsonl",
                )
            with self.assertRaisesRegex(ValueError, "logged-in account use"):
                CodexAppServer(
                    model_base_url="http://127.0.0.1:1",
                    use_logged_in_account=True,
                    workspace=root,
                    raw_jsonl_path=root / "contradictory.jsonl",
                )

    def test_logged_in_account_command_has_no_test_provider(self) -> None:
        with tempfile.TemporaryDirectory(prefix="codex-mode-test-") as directory:
            root = Path(directory)
            client = CodexAppServer(
                model_base_url=None,
                use_logged_in_account=True,
                workspace=root,
                raw_jsonl_path=root / "live.jsonl",
            )
            command = " ".join(client._command())
            self.assertTrue(client.uses_logged_in_account)
            self.assertIsNone(client.model)
            self.assertNotIn("model_providers", command)
            self.assertNotIn("authority_continuity_mock", command)
            self.assertIn("mcp_servers={}", command)

    def test_deterministic_mode_keeps_the_pinned_default_model(self) -> None:
        with tempfile.TemporaryDirectory(prefix="codex-mode-test-") as directory:
            root = Path(directory)
            client = CodexAppServer(
                model_base_url="http://127.0.0.1:1",
                workspace=root,
                raw_jsonl_path=root / "fixture.jsonl",
            )
            self.assertFalse(client.uses_logged_in_account)
            self.assertEqual(client.model, "gpt-5.6-sol")
            self.assertIn("authority_continuity_mock", " ".join(client._command()))


@unittest.skipUnless(shutil.which("codex"), "installed codex executable required")
class RealCodexAppServerTests(unittest.TestCase):
    def test_preflight_with_real_stdio_server(self) -> None:
        with tempfile.TemporaryDirectory(prefix="codex-boundary-test-") as temp_dir:
            temp_path = Path(temp_dir)
            raw_path = temp_path / "raw" / "app-server.jsonl"
            result = run_preflight(workspace=temp_path, raw_jsonl_path=raw_path)

            self.assertTrue(result.ok)
            self.assertTrue(result.seed_archived)
            self.assertEqual(result.call_id, _PREFLIGHT_CALL_ID)
            self.assertEqual(result.effect_id, _PREFLIGHT_EFFECT_ID)
            self.assertEqual(result.responses_request_count, 3)
            self.assertGreater(result.raw_record_count, 0)
            self.assertTrue(raw_path.is_file())
            self.assertNotEqual(result.seed_thread_id, result.fork_thread_id)

    def test_preflight_multiple_protected_calls_share_one_turn(self) -> None:
        with tempfile.TemporaryDirectory(prefix="codex-multi-boundary-test-") as temp_dir:
            temp_path = Path(temp_dir)
            observed: list[tuple[str, str, str]] = []

            def handler(pending: PendingToolCall) -> None:
                observed.append(
                    (
                        pending.turn_id,
                        pending.call_id,
                        str(pending.arguments["effect_id"]),
                    )
                )
                pending.respond_text(f"receipt:{pending.arguments['effect_id']}")

            result = run_preflight(
                workspace=temp_path,
                raw_jsonl_path=temp_path / "app-server.jsonl",
                protected_effect_ids=("preflight-effect-1", "preflight-effect-2"),
                tool_handler=handler,
            )

            self.assertEqual(result.responses_request_count, 4)
            self.assertEqual(
                observed,
                [
                    (result.protected_turn_id, "preflight-call-1", "preflight-effect-1"),
                    (result.protected_turn_id, "preflight-call-2", "preflight-effect-2"),
                ],
            )
            self.assertEqual(len(result.protected_calls), 2)

    def test_preflight_applies_native_workspace_patch(self) -> None:
        with tempfile.TemporaryDirectory(prefix="codex-writable-boundary-test-") as temp_dir:
            temp_path = Path(temp_dir)
            raw_path = temp_path / "app-server.jsonl"
            shell = shutil.which("sh")
            if shell is None:
                self.skipTest("system sh executable required")
            validation_shell = temp_path / "sh"
            validation_shell.symlink_to(Path(shell).resolve())
            patch = (
                "*** Begin Patch\n"
                "*** Add File: native-edit.txt\n"
                "+edited by native Codex\n"
                "*** End Patch\n"
            )
            result = run_preflight(
                workspace=temp_path,
                raw_jsonl_path=raw_path,
                workspace_patch=patch,
                workspace_validation_command="test -f native-edit.txt",
                workspace_validation_shell=str(validation_shell),
            )

            self.assertEqual(
                (temp_path / "native-edit.txt").read_text(encoding="utf-8"),
                "edited by native Codex\n",
            )
            self.assertEqual(result.workspace_edit_call_id, _PREFLIGHT_EDIT_CALL_ID)
            self.assertEqual(
                result.workspace_patch_sha256,
                sha256(patch.encode("utf-8")).hexdigest(),
            )
            self.assertEqual(
                result.workspace_validation_call_id,
                _PREFLIGHT_VALIDATION_CALL_ID,
            )
            self.assertEqual(
                result.workspace_validation_command_sha256,
                sha256(b"test -f native-edit.txt").hexdigest(),
            )
            self.assertEqual(result.responses_request_count, 5)

    def test_failed_workspace_validation_never_reaches_protected_handler(self) -> None:
        with tempfile.TemporaryDirectory(prefix="codex-failed-validation-test-") as temp_dir:
            temp_path = Path(temp_dir)
            shell = shutil.which("sh")
            if shell is None:
                self.skipTest("system sh executable required")
            validation_shell = temp_path / "sh"
            validation_shell.symlink_to(Path(shell).resolve())
            handler_called = False

            def protected_handler(unused: PendingToolCall) -> None:
                nonlocal handler_called
                handler_called = True
                raise AssertionError("protected handler must remain unreachable")

            with self.assertRaisesRegex(
                AssertionError,
                "successful declared validation",
            ):
                run_preflight(
                    workspace=temp_path,
                    raw_jsonl_path=temp_path / "app-server.jsonl",
                    workspace_patch=(
                        "*** Begin Patch\n"
                        "*** Add File: native-edit.txt\n"
                        "+edited by native Codex\n"
                        "*** End Patch\n"
                    ),
                    workspace_validation_command="false",
                    workspace_validation_shell=str(validation_shell),
                    tool_handler=protected_handler,
                )
            self.assertFalse(handler_called)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the hermetic real-Codex App Server boundary preflight."
    )
    parser.add_argument("--codex-binary", default="codex")
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--raw-jsonl", type=Path)
    parser.add_argument(
        "--keep-seed",
        action="store_true",
        help="leave the persistent seed unarchived for manual inspection",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    result = run_preflight(
        codex_binary=args.codex_binary,
        workspace=args.workspace,
        raw_jsonl_path=args.raw_jsonl,
        archive_seed=not args.keep_seed,
    )
    print(json.dumps(asdict(result), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["PreflightResult", "ToolHandler", "main", "run_preflight"]
