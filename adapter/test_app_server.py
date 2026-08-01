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
import json
from pathlib import Path
import shutil
import tempfile
from typing import Any, Callable, Mapping, Sequence, cast
import unittest
from urllib.request import Request, urlopen

from adapter.app_server import (
    RPC_TIMEOUT_SECONDS,
    TURN_TIMEOUT_SECONDS,
    AppServerProtocolError,
    CodexAppServer,
    PendingToolCall,
)
from adapter.mock_responses import DeterministicResponsesServer


_PREFLIGHT_EFFECT_ID = "preflight-effect-1"
_PREFLIGHT_CALL_ID = "preflight-call-1"


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
    callback_request_id: int | str,
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
        "real pending callback": _has_message(
            records,
            "server_to_client",
            lambda payload: payload.get("method") == "item/tool/call"
            and payload.get("id") == callback_request_id
            and payload.get("params", {}).get("threadId") == fork_thread_id
            and payload.get("params", {}).get("turnId") == protected_turn_id
            and payload.get("params", {}).get("tool") == "protected_commit",
        ),
        "callback response": _has_message(
            records,
            "client_to_server",
            lambda payload: payload.get("id") == callback_request_id
            and isinstance(payload.get("result"), dict),
        ),
    }
    missing = [name for name, present in checks.items() if not present]
    if missing:
        raise AssertionError(
            "raw JSONL capture omitted protocol evidence: " + ", ".join(missing)
        )


def run_preflight(
    *,
    codex_binary: str = "codex",
    workspace: str | Path | None = None,
    raw_jsonl_path: str | Path | None = None,
    tool_handler: ToolHandler | None = None,
    archive_seed: bool = True,
) -> PreflightResult:
    """Run one deterministic end-to-end App Server boundary preflight.

    ``tool_handler`` receives the pending ``item/tool/call`` before the client
    sends any callback response.  The handler must call ``pending.respond`` or
    ``pending.respond_text``; a handler that returns without doing so fails
    closed.  No controller, replay checker, or oracle is imported here.
    """

    workspace_path = Path.cwd() if workspace is None else Path(workspace)
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
    callback_request_id: int | str | None = None
    call_id: str | None = None
    initialize_result: dict[str, Any] | None = None
    seed_archived = False

    with DeterministicResponsesServer() as responses:
        responses.enqueue_assistant(
            "seed acknowledged", response_id="fixture-seed-response"
        )
        responses.enqueue_tool_call(
            "protected_commit",
            {"effect_id": _PREFLIGHT_EFFECT_ID},
            call_id=_PREFLIGHT_CALL_ID,
            response_id="fixture-tool-response",
        )
        responses.enqueue_assistant(
            "protected commit acknowledged", response_id="fixture-final-response"
        )

        client = CodexAppServer(
            model_base_url=responses.base_url,
            workspace=workspace_path,
            raw_jsonl_path=raw_path,
            codex_binary=codex_binary,
            rpc_timeout=RPC_TIMEOUT_SECONDS,
            turn_timeout=TURN_TIMEOUT_SECONDS,
        )
        with client:
            initialize_result = dict(client.initialize_result or {})
            try:
                seed = client.create_seed_thread()
                seed_thread_id = seed["id"]
                seed_turn_id, _ = client.start_turn_and_wait(
                    seed_thread_id,
                    "Acknowledge this deterministic seed turn.",
                    timeout=TURN_TIMEOUT_SECONDS,
                )

                fork = client.fork_at_turn(seed_thread_id, seed_turn_id)
                fork_thread_id = fork["id"]

                pending = client.start_protected_turn(
                    fork_thread_id,
                    "Call protected_commit once for preflight-effect-1, then finish.",
                    expected_tool="protected_commit",
                    expected_arguments={"effect_id": _PREFLIGHT_EFFECT_ID},
                    timeout=TURN_TIMEOUT_SECONDS,
                )
                protected_turn_id = pending.turn_id
                callback_request_id = pending.request_id
                call_id = pending.call_id

                # This is the experiment seam: the real App Server and its
                # pending callback remain alive while caller-owned logic runs.
                handler(pending)
                pending.wait_turn_completed(timeout=TURN_TIMEOUT_SECONDS)
                client.assert_hermetic_runtime()
            finally:
                if seed_thread_id is not None and archive_seed:
                    client.archive_thread(seed_thread_id)
                    seed_archived = True

        responses.assert_consumed()
        response_count = responses.responses_request_count
        models_count = responses.models_request_count
        if response_count != 3:
            raise AssertionError(
                "preflight expected exactly three local Responses requests; "
                f"observed {response_count}"
            )

    required_values = {
        "initialize_result": initialize_result,
        "seed_thread_id": seed_thread_id,
        "seed_turn_id": seed_turn_id,
        "fork_thread_id": fork_thread_id,
        "protected_turn_id": protected_turn_id,
        "callback_request_id": callback_request_id,
        "call_id": call_id,
    }
    missing_values = [name for name, value in required_values.items() if value is None]
    if missing_values:
        raise AppServerProtocolError(
            "preflight completed without required values: " + ", ".join(missing_values)
        )
    if call_id != _PREFLIGHT_CALL_ID:
        raise AppServerProtocolError(
            f"dynamic tool call id changed: expected={_PREFLIGHT_CALL_ID!r} "
            f"actual={call_id!r}"
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
    callback_request_id = cast(int | str, callback_request_id)
    call_id = cast(str, call_id)

    records = _read_raw_jsonl(raw_path.resolve())
    _validate_raw_protocol(
        records,
        seed_thread_id=seed_thread_id,
        seed_turn_id=seed_turn_id,
        fork_thread_id=fork_thread_id,
        protected_turn_id=protected_turn_id,
        callback_request_id=callback_request_id,
    )
    return PreflightResult(
        ok=True,
        codex_binary=str(Path(shutil.which(codex_binary) or codex_binary).resolve()),
        initialize_result=initialize_result,
        seed_thread_id=seed_thread_id,
        seed_turn_id=seed_turn_id,
        fork_thread_id=fork_thread_id,
        protected_turn_id=protected_turn_id,
        call_id=call_id,
        effect_id=_PREFLIGHT_EFFECT_ID,
        seed_archived=seed_archived,
        responses_request_count=response_count,
        models_request_count=models_count,
        raw_record_count=len(records),
        raw_jsonl_path=str(raw_path.resolve()),
    )


class DeterministicResponsesServerTests(unittest.TestCase):
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
