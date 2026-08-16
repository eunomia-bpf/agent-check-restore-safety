from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from hashlib import sha256
from http.server import BaseHTTPRequestHandler
import io
import json
import os
from pathlib import Path
import socketserver
import tempfile
import threading
import unittest
from unittest import mock

from adapter.firecracker_codex_runtime_demo import (
    DemoError,
    _post_sandbox_json,
    _sandbox_socket_path,
    _verify_sandbox_socket,
    main,
    run_demo,
)
from adapter.test_app_server import PreflightResult


class _Wrapped:
    def __init__(self, executable: Path) -> None:
        self.executable = executable

    def __enter__(self) -> "_Wrapped":
        return self

    def __exit__(self, *unused: object) -> None:
        return None


class FirecrackerCodexRuntimeDemoTests(unittest.TestCase):
    def test_sandbox_operation_uses_private_credential_free_unix_socket(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as raw:
            directory = Path(raw)
            directory.chmod(0o700)
            socket_path = directory / "sandbox.sock"
            observed: dict[str, object] = {}

            class Handler(BaseHTTPRequestHandler):
                def do_POST(self) -> None:
                    length = int(self.headers.get("Content-Length", "0"))
                    observed.update(
                        {
                            "path": self.path,
                            "authorization": self.headers.get("Authorization"),
                            "body": json.loads(self.rfile.read(length)),
                        }
                    )
                    response = json.dumps(
                        {
                            "operation_id": "op-" + "a" * 64,
                            "phase": "succeeded",
                            "result_hash": "b" * 64,
                        },
                        separators=(",", ":"),
                    ).encode("ascii")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(response)))
                    self.end_headers()
                    self.wfile.write(response)

                def log_message(self, *unused: object) -> None:
                    return None

            server = socketserver.UnixStreamServer(os.fspath(socket_path), Handler)
            socket_path.chmod(0o600)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                canonical = _sandbox_socket_path(socket_path)
                _verify_sandbox_socket(canonical)
                outcome = _post_sandbox_json(
                    canonical,
                    {
                        "call_id": "preflight-call-1",
                        "kind": "protected_commit",
                        "body": "e30=",
                    },
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
            self.assertEqual(outcome["phase"], "succeeded")
            self.assertEqual(observed["path"], "/v1/execute")
            self.assertIsNone(observed["authorization"])
            self.assertEqual(
                observed["body"],
                {
                    "call_id": "preflight-call-1",
                    "kind": "protected_commit",
                    "body": "e30=",
                },
            )

    def test_run_demo_uses_transparent_preflight_and_publishes_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = self._fixture(Path(raw))
            wrapper = fixture["root"] / "temporary-wrapper"
            wrapper.write_bytes(b"wrapper")
            wrapper.chmod(0o700)

            def fake_preflight(**arguments: object) -> PreflightResult:
                raw_path = Path(str(arguments["raw_jsonl_path"]))
                raw_path.write_text(
                    '{"direction":"meta","payload":{},"sequence":1,"time_ns":1}\n',
                    encoding="utf-8",
                )
                raw_path.chmod(0o600)
                runtime_result = fixture["runtime"] / "result.json"
                runtime_result.write_text(
                    json.dumps(
                        {
                            "schema": 1,
                            "success": True,
                            "session_id": "0123456789abcdef0123456789abcdef",
                            "runner_sha256": fixture["digests"]["runner"],
                            "codex_sha256": fixture["digests"]["codex"],
                            "artifacts": {
                                "runner": {
                                    "name": "runner",
                                    "size": fixture["arguments"]["runner"].stat().st_size,
                                    "mode": 0o600,
                                    "sha256": fixture["digests"]["runner"],
                                }
                            },
                            "workspace_mapping": {
                                "host": str(fixture["workspace"]),
                                "guest": "/workspace",
                            },
                            "repository_change": {
                                "base_root": "a" * 64,
                                "final_root": "b" * 64,
                                "operation_count": 1,
                            },
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )
                runtime_result.chmod(0o600)
                return PreflightResult(
                    ok=True,
                    codex_binary=str(arguments["codex_binary"]),
                    initialize_result={},
                    seed_thread_id="seed-thread",
                    seed_turn_id="seed-turn",
                    fork_thread_id="fork-thread",
                    protected_turn_id="protected-turn",
                    call_id="preflight-call-1",
                    effect_id="preflight-effect-1",
                    seed_archived=True,
                    responses_request_count=5,
                    models_request_count=1,
                    raw_record_count=1,
                    raw_jsonl_path=str(raw_path),
                    workspace_edit_call_id="preflight-edit-1",
                    workspace_patch_sha256=sha256(
                        str(arguments["workspace_patch"]).encode("utf-8")
                    ).hexdigest(),
                    workspace_validation_call_id="preflight-validation-1",
                    workspace_validation_command_sha256=sha256(
                        str(arguments["workspace_validation_command"]).encode("utf-8")
                    ).hexdigest(),
                )

            with (
                mock.patch(
                    "adapter.firecracker_codex_runtime_demo.create_firecracker_codex",
                    return_value=_Wrapped(wrapper),
                ) as create,
                mock.patch(
                    "adapter.firecracker_codex_runtime_demo.run_preflight",
                    side_effect=fake_preflight,
                ) as preflight,
            ):
                result = run_demo(
                    **fixture["arguments"],
                    workspace_patch="*** Begin Patch\n*** End Patch\n",
                    workspace_validation_command="test -f changed-file",
                )

            self.assertTrue(result["ok"])
            self.assertEqual(result["independent_evidence_check"], "required")
            self.assertEqual(
                result["artifacts"]["runner"]["sha256"],
                fixture["digests"]["runner"],
            )
            self.assertNotIn("initialize_result", result["preflight"])
            self.assertEqual(
                preflight.call_args.kwargs["raw_jsonl_path"],
                fixture["adapter"] / "app-server.jsonl",
            )
            self.assertEqual(
                preflight.call_args.kwargs["workspace"], fixture["workspace"]
            )
            self.assertEqual(
                result["preflight"]["workspace_edit_call_id"],
                "preflight-edit-1",
            )
            self.assertEqual(
                result["preflight"]["workspace_validation_call_id"],
                "preflight-validation-1",
            )
            self.assertEqual(
                preflight.call_args.kwargs["workspace_validation_shell"],
                "/opt/codex/bin/sh",
            )
            self.assertEqual(
                create.call_args.kwargs["evidence_dir"], fixture["runtime"]
            )
            published = fixture["adapter"] / "result.json"
            self.assertEqual(
                json.loads(published.read_text(encoding="utf-8")), result
            )
            self.assertEqual(published.stat().st_mode & 0o777, 0o600)
            self.assertNotIn("direction", published.read_text(encoding="utf-8"))

    def test_rejects_nonempty_adapter_evidence_before_launch(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = self._fixture(Path(raw))
            (fixture["adapter"] / "existing").write_text("x", encoding="utf-8")
            with mock.patch(
                "adapter.firecracker_codex_runtime_demo.create_firecracker_codex"
            ) as create:
                with self.assertRaisesRegex(DemoError, "adapter_evidence must be empty"):
                    run_demo(**fixture["arguments"])
            create.assert_not_called()

    def test_rejects_artifact_digest_mismatch_before_launch(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = self._fixture(Path(raw))
            arguments = dict(fixture["arguments"])
            arguments["runner_sha256"] = "0" * 64
            with mock.patch(
                "adapter.firecracker_codex_runtime_demo.create_firecracker_codex"
            ) as create:
                with self.assertRaisesRegex(DemoError, "runner SHA-256"):
                    run_demo(**arguments)
            create.assert_not_called()

    def test_main_stdout_contains_only_compact_result_locator(self) -> None:
        result = {
            "result_path": "/private/adapter/result.json",
            "runtime": {"evidence_directory": "/private/runtime"},
            "adapter": {"evidence_directory": "/private/adapter"},
        }
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            mock.patch(
                "adapter.firecracker_codex_runtime_demo._parse_args",
                return_value=mock.Mock(
                    workspace_patch_file=None,
                    workspace_validation_command=None,
                ),
            ),
            mock.patch(
                "adapter.firecracker_codex_runtime_demo.run_demo",
                return_value=result,
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            self.assertEqual(main([]), 0)
        self.assertEqual(stderr.getvalue(), "")
        lines = stdout.getvalue().splitlines()
        self.assertEqual(len(lines), 1)
        summary = json.loads(lines[0])
        self.assertEqual(summary["result_path"], result["result_path"])
        self.assertNotIn("jsonl", lines[0].lower())

    def test_main_never_copies_failure_details_to_stdout(self) -> None:
        stdout, stderr = io.StringIO(), io.StringIO()
        detail = 'secret-value\n{"sequence":1,"direction":"server_to_client"}'
        with (
            mock.patch(
                "adapter.firecracker_codex_runtime_demo._parse_args",
                return_value=mock.Mock(
                    workspace_patch_file=None,
                    workspace_validation_command=None,
                ),
            ),
            mock.patch(
                "adapter.firecracker_codex_runtime_demo.run_demo",
                side_effect=DemoError(detail),
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            self.assertEqual(main([]), 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("Firecracker Codex demo failed", stderr.getvalue())

    def _fixture(self, root: Path) -> dict[str, object]:
        artifacts = root / "artifacts"
        artifacts.mkdir()
        runtime = root / "runtime-evidence"
        adapter = root / "adapter-evidence"
        workspace = root / "workspace"
        for directory in (runtime, adapter, workspace):
            directory.mkdir(mode=0o700)
        paths: dict[str, Path] = {}
        digests: dict[str, str] = {}
        for label, executable in (
            ("runner", True),
            ("firecracker", True),
            ("kernel", False),
            ("guest", True),
            ("payload", False),
            ("repository", False),
        ):
            path = artifacts / label
            contents = (label + "-fixture").encode("ascii")
            path.write_bytes(contents)
            path.chmod(0o700 if executable else 0o600)
            paths[label] = path
            digests[label] = sha256(contents).hexdigest()
        digests["codex"] = sha256(b"codex-fixture").hexdigest()
        arguments = {
            "runner": paths["runner"],
            "runner_sha256": digests["runner"],
            "firecracker": paths["firecracker"],
            "firecracker_sha256": digests["firecracker"],
            "kernel": paths["kernel"],
            "kernel_sha256": digests["kernel"],
            "guest": paths["guest"],
            "guest_sha256": digests["guest"],
            "payload": paths["payload"],
            "payload_sha256": digests["payload"],
            "repository": paths["repository"],
            "repository_sha256": digests["repository"],
            "codex_sha256": digests["codex"],
            "runtime_evidence": runtime,
            "adapter_evidence": adapter,
            "workspace": workspace,
        }
        return {
            "root": root,
            "runtime": runtime,
            "adapter": adapter,
            "workspace": workspace,
            "digests": digests,
            "arguments": arguments,
        }


if __name__ == "__main__":
    unittest.main()
