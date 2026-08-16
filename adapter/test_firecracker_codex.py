from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import time
import unittest

from adapter.firecracker_codex import (
    _RUNNER_STOP_SECONDS,
    _STDERR_LIMIT_EXIT,
    _STDERR_MAX_LINE_BYTES,
    _STDERR_MAX_TOTAL_BYTES,
    create_firecracker_codex,
)


_DIGESTS = {
    "runner_sha256": "0" * 64,
    "firecracker_sha256": "1" * 64,
    "kernel_sha256": "2" * 64,
    "guest_sha256": "5" * 64,
    "payload_sha256": "3" * 64,
    "codex_sha256": "4" * 64,
}


class FirecrackerCodexTests(unittest.TestCase):
    def test_wrapper_preserves_argv_and_fixes_environment(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            runner = root / "runner"
            runner.write_text(
                "#!/usr/bin/env python3\n"
                "import json,os,sys\n"
                "print('bounded warning', file=sys.stderr)\n"
                "sys.stderr.write('tail')\n"
                "print(json.dumps({'argv':sys.argv,'env':dict(os.environ)},sort_keys=True))\n",
                encoding="utf-8",
            )
            runner.chmod(0o700)
            inputs = self._inputs(root)
            with create_firecracker_codex(
                runner=runner,
                **inputs,
                **_DIGESTS,
            ) as wrapped:
                arguments = ("app-server", "--stdio", "-c", "x=y with space")
                completed = subprocess.run(
                    [os.fspath(wrapped), *arguments],
                    check=True,
                    capture_output=True,
                    text=True,
                    env={"PATH": "/malicious", "SECRET": "must-not-cross"},
                )
                record = json.loads(completed.stdout)
                self.assertEqual(completed.stderr, "bounded warning\ntail")
                self.assertEqual(record["argv"], [os.fspath(runner), *arguments])
                self.assertNotIn("SECRET", record["env"])
                self.assertEqual(record["env"]["PATH"], "/usr/bin:/bin")
                self.assertEqual(record["env"], {
                    "LANG": "C.UTF-8",
                    "LC_ALL": "C.UTF-8",
                    "PATH": "/usr/bin:/bin",
                    "SAFE_CHANGE_EVIDENCE_DIR": os.fspath(inputs["evidence_dir"]),
                    "SAFE_CHANGE_RUNNER_SHA256": _DIGESTS["runner_sha256"],
                    "SAFE_CHANGE_CODEX_SHA256": _DIGESTS["codex_sha256"],
                    "SAFE_CHANGE_FIRECRACKER": os.fspath(inputs["firecracker"]),
                    "SAFE_CHANGE_FIRECRACKER_SHA256": _DIGESTS["firecracker_sha256"],
                    "SAFE_CHANGE_GUEST": os.fspath(inputs["guest"]),
                    "SAFE_CHANGE_GUEST_SHA256": _DIGESTS["guest_sha256"],
                    "SAFE_CHANGE_KERNEL": os.fspath(inputs["kernel"]),
                    "SAFE_CHANGE_KERNEL_SHA256": _DIGESTS["kernel_sha256"],
                    "SAFE_CHANGE_PAYLOAD": os.fspath(inputs["payload"]),
                    "SAFE_CHANGE_PAYLOAD_SHA256": _DIGESTS["payload_sha256"],
                    "SAFE_CHANGE_WORKSPACE": os.fspath(inputs["workspace"]),
                })
                self.assertEqual(
                    wrapped.command(arguments), (os.fspath(runner), *arguments)
                )

    def test_wrapper_fails_closed_on_oversized_stderr_line(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            runner = root / "runner"
            pid_file = root / "runner.pid"
            runner.write_text(
                "#!/usr/bin/env python3\n"
                "import os,time\n"
                f"open({os.fspath(pid_file)!r}, 'w').write(str(os.getpid()))\n"
                f"os.write(2, b'x' * {_STDERR_MAX_LINE_BYTES + 1})\n"
                "time.sleep(30)\n",
                encoding="utf-8",
            )
            runner.chmod(0o700)
            inputs = self._inputs(root)
            with create_firecracker_codex(
                runner=runner,
                **inputs,
                **_DIGESTS,
            ) as wrapped:
                completed = subprocess.run(
                    [os.fspath(wrapped)],
                    capture_output=True,
                    timeout=5,
                )
            self.assertEqual(completed.returncode, _STDERR_LIMIT_EXIT)
            self.assertEqual(completed.stdout, b"")
            self.assertIn(
                f"line exceeded the {_STDERR_MAX_LINE_BYTES}-byte limit".encode(),
                completed.stderr,
            )
            self.assertLess(len(completed.stderr), 1024)
            runner_pid = int(pid_file.read_text(encoding="utf-8"))
            with self.assertRaises(ProcessLookupError):
                os.kill(runner_pid, 0)

    def test_wrapper_accepts_stderr_at_line_limit(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            runner = root / "runner"
            runner.write_text(
                "#!/usr/bin/env python3\n"
                "import os\n"
                f"os.write(2, b'x' * {_STDERR_MAX_LINE_BYTES} + b'\\n')\n",
                encoding="utf-8",
            )
            runner.chmod(0o700)
            inputs = self._inputs(root)
            with create_firecracker_codex(
                runner=runner,
                **inputs,
                **_DIGESTS,
            ) as wrapped:
                completed = subprocess.run(
                    [os.fspath(wrapped)],
                    capture_output=True,
                    timeout=5,
                )
            self.assertEqual(completed.returncode, 0)
            self.assertEqual(len(completed.stderr), _STDERR_MAX_LINE_BYTES + 1)

    def test_wrapper_fails_closed_on_cumulative_stderr_limit(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            runner = root / "runner"
            runner.write_text(
                "#!/usr/bin/env python3\n"
                "import os,time\n"
                "line = b'x' * 1023 + b'\\n'\n"
                f"for _ in range({_STDERR_MAX_TOTAL_BYTES // 1024 + 1}):\n"
                "    os.write(2, line)\n"
                "time.sleep(30)\n",
                encoding="utf-8",
            )
            runner.chmod(0o700)
            inputs = self._inputs(root)
            with create_firecracker_codex(
                runner=runner,
                **inputs,
                **_DIGESTS,
            ) as wrapped:
                completed = subprocess.run(
                    [os.fspath(wrapped)],
                    capture_output=True,
                    timeout=5,
                )
            self.assertEqual(completed.returncode, _STDERR_LIMIT_EXIT)
            self.assertEqual(completed.stdout, b"")
            self.assertIn(
                f"exceeded the {_STDERR_MAX_TOTAL_BYTES}-byte total limit".encode(),
                completed.stderr,
            )
            self.assertLessEqual(
                len(completed.stderr), _STDERR_MAX_TOTAL_BYTES + 128
            )

    def test_wrapper_accepts_stderr_at_cumulative_limit(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            runner = root / "runner"
            runner.write_text(
                "#!/usr/bin/env python3\n"
                "import os\n"
                "line = b'x' * 1023 + b'\\n'\n"
                f"for _ in range({_STDERR_MAX_TOTAL_BYTES // 1024}):\n"
                "    os.write(2, line)\n",
                encoding="utf-8",
            )
            runner.chmod(0o700)
            inputs = self._inputs(root)
            with create_firecracker_codex(
                runner=runner,
                **inputs,
                **_DIGESTS,
            ) as wrapped:
                completed = subprocess.run(
                    [os.fspath(wrapped)],
                    capture_output=True,
                    timeout=5,
                )
            self.assertEqual(completed.returncode, 0)
            self.assertEqual(len(completed.stderr), _STDERR_MAX_TOTAL_BYTES)

    def test_wrapper_kills_runner_that_ignores_forwarded_signal(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            runner = root / "runner"
            pid_file = root / "runner.pid"
            runner.write_text(
                "#!/usr/bin/env python3\n"
                "import os,signal,time\n"
                "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                f"with open({os.fspath(pid_file)!r}, 'w') as stream:\n"
                "    stream.write(str(os.getpid()))\n"
                "os.close(2)\n"
                "time.sleep(30)\n",
                encoding="utf-8",
            )
            runner.chmod(0o700)
            inputs = self._inputs(root)
            with create_firecracker_codex(
                runner=runner,
                **inputs,
                **_DIGESTS,
            ) as wrapped:
                process = subprocess.Popen(
                    [os.fspath(wrapped)], stdout=subprocess.PIPE, stderr=subprocess.PIPE
                )
                for _ in range(100):
                    if pid_file.exists():
                        break
                    time.sleep(0.01)
                else:
                    process.kill()
                    process.wait(timeout=1)
                    self.fail("runner did not start")
                process.terminate()
                process.communicate(timeout=_RUNNER_STOP_SECONDS + 2)
            self.assertNotEqual(process.returncode, 0)
            runner_pid = int(pid_file.read_text(encoding="utf-8"))
            with self.assertRaises(ProcessLookupError):
                os.kill(runner_pid, 0)

    def test_rejects_nonempty_or_public_state_and_bad_digest(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            runner = self._file(root / "runner", executable=True)
            inputs = self._inputs(root)
            (inputs["workspace"] / "unexpected").write_text("x", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "workspace must be empty"):
                create_firecracker_codex(
                    runner=runner, **inputs, **_DIGESTS
                )
            (inputs["workspace"] / "unexpected").unlink()
            inputs["evidence_dir"].chmod(0o755)
            with self.assertRaisesRegex(PermissionError, "evidence_dir"):
                create_firecracker_codex(
                    runner=runner, **inputs, **_DIGESTS
                )
            inputs["evidence_dir"].chmod(0o700)
            with self.assertRaisesRegex(ValueError, "payload_sha256"):
                create_firecracker_codex(
                    runner=runner,
                    **inputs,
                    **{**_DIGESTS, "payload_sha256": "no"},
                )

    def test_rejects_symlinked_artifact_and_overlapping_paths(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            runner = self._file(root / "runner", executable=True)
            inputs = self._inputs(root)
            link = root / "payload-link"
            link.symlink_to(inputs["payload"])
            with self.assertRaisesRegex(ValueError, "payload must not be a symlink"):
                create_firecracker_codex(
                    runner=runner,
                    **{**inputs, "payload": link},
                    **_DIGESTS,
                )

            nested = inputs["workspace"] / "evidence"
            nested.mkdir()
            nested.chmod(0o700)
            with self.assertRaisesRegex(ValueError, "workspace and evidence_dir"):
                create_firecracker_codex(
                    runner=runner,
                    **{**inputs, "evidence_dir": nested},
                    **_DIGESTS,
                )

    def _inputs(self, root: Path) -> dict[str, Path]:
        artifacts = root / "artifacts"
        artifacts.mkdir()
        workspace = root / "workspace"
        workspace.mkdir()
        evidence = root / "evidence"
        evidence.mkdir(mode=0o700)
        return {
            "firecracker": self._file(artifacts / "firecracker", executable=True),
            "kernel": self._file(artifacts / "kernel"),
            "guest": self._file(artifacts / "guest", executable=True),
            "payload": self._file(artifacts / "payload"),
            "workspace": workspace,
            "evidence_dir": evidence,
        }

    @staticmethod
    def _file(path: Path, *, executable: bool = False) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(hashlib.sha256(os.fspath(path).encode()).digest())
        path.chmod(0o700 if executable else 0o600)
        return path


if __name__ == "__main__":
    unittest.main()
