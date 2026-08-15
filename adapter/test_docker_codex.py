"""Unit tests for the Docker-backed real Codex executable."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from adapter.app_server import CodexAppServer
from adapter.docker_codex import create_docker_codex


class DockerCodexTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory(prefix="docker-codex-test-")
        self.root = Path(self._temporary.name).resolve()
        self.workspace = self.root / "workspace"
        self.codex_home = self.root / "codex-home"
        self.vendor_bundle = self.root / "vendor" / "x86_64-unknown-linux-musl"
        self.workspace.mkdir()
        self.codex_home.mkdir()
        (self.vendor_bundle / "bin").mkdir(parents=True)
        self.vendor_codex = self.vendor_bundle / "bin" / "codex"
        self.vendor_codex.write_text("native fixture", encoding="utf-8")
        self.vendor_codex.chmod(0o755)
        self.fake_docker = self.root / "docker fixture"
        self.fake_docker.write_text(
            f"#!{sys.executable}\n"
            "import json\n"
            "import sys\n"
            "print(json.dumps(sys.argv[1:]))\n",
            encoding="utf-8",
        )
        self.fake_docker.chmod(0o755)

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def create(self, **overrides: object):
        arguments: dict[str, object] = {
            "vendor_bundle": self.vendor_bundle,
            "workspace": self.workspace,
            "codex_home": self.codex_home,
            "network": "safe-change-network",
            "runtime_image": "safe-change-runtime:test",
            "docker_binary": self.fake_docker,
        }
        arguments.update(overrides)
        return create_docker_codex(**arguments)

    def test_builds_hardened_auditable_command(self) -> None:
        with self.create(container_name="safe-change-codex-fixed") as wrapper:
            command = wrapper.docker_command
            self.assertEqual(command[:4], (str(self.fake_docker), "run", "--rm", "-i"))
            self.assertEqual(wrapper.container_name, "safe-change-codex-fixed")
            self.assertEqual(
                command[command.index("--name") + 1], wrapper.container_name
            )
            self.assertEqual(
                command[command.index("--network") + 1], "safe-change-network"
            )
            self.assertIn("--read-only", command)
            self.assertEqual(command[command.index("--cap-drop") + 1], "ALL")
            self.assertEqual(
                command[command.index("--security-opt") + 1],
                "no-new-privileges=true",
            )
            self.assertEqual(
                command[command.index("--tmpfs") + 1],
                "/tmp:rw,nosuid,nodev,mode=1777",
            )
            self.assertEqual(
                command[command.index("--user") + 1],
                f"{os.getuid()}:{os.getgid()}",
            )
            self.assertEqual(
                command[command.index("--workdir") + 1], str(self.workspace)
            )
            environment = [
                command[index + 1]
                for index, argument in enumerate(command)
                if argument == "--env"
            ]
            self.assertEqual(
                environment,
                [
                    "CODEX_HOME=/var/lib/safe-change/codex-home",
                    "CODEX_MANAGED_BY_NPM=1",
                ],
            )
            self.assertEqual(
                command[command.index("--entrypoint") + 1], str(self.vendor_codex)
            )
            self.assertEqual(command[-1], "safe-change-runtime:test")

            mounts = [
                command[index + 1]
                for index, argument in enumerate(command)
                if argument == "--mount"
            ]
            self.assertEqual(
                mounts,
                [
                    f"type=bind,src={self.workspace},dst={self.workspace},readonly",
                    "type=bind,"
                    f"src={self.codex_home},dst=/var/lib/safe-change/codex-home",
                    "type=bind,"
                    f"src={self.vendor_bundle},dst={self.vendor_bundle},readonly",
                ],
            )

    def test_wrapper_preserves_arguments_without_shell_interpretation(self) -> None:
        with self.create() as wrapper:
            codex_arguments = (
                "app-server",
                "--stdio",
                "value with spaces",
                "$(must-not-run)",
                ";also-not-a-command",
            )
            completed = subprocess.run(
                [wrapper.executable, *codex_arguments],
                check=True,
                text=True,
                capture_output=True,
            )
            observed = json.loads(completed.stdout)
            self.assertEqual(
                observed,
                [*wrapper.docker_command[1:], *codex_arguments],
            )
            self.assertEqual(
                wrapper.command(codex_arguments),
                wrapper.docker_command + codex_arguments,
            )

    def test_existing_app_server_accepts_wrapper_as_codex_binary(self) -> None:
        with self.create() as wrapper:
            client = CodexAppServer(
                model_base_url="http://127.0.0.1:1",
                workspace=self.workspace,
                raw_jsonl_path=self.root / "raw.jsonl",
                codex_binary=os.fspath(wrapper),
            )
            self.assertEqual(Path(client.codex_binary), wrapper.executable)
            self.assertEqual(client._command()[0], os.fspath(wrapper.executable))

    def test_generated_names_are_fixed_and_unique(self) -> None:
        with self.create() as first, self.create() as second:
            self.assertNotEqual(first.container_name, second.container_name)
            self.assertRegex(first.container_name, r"^safe-change-codex-[0-9a-f]{16}$")
            self.assertEqual(
                first.docker_command[first.docker_command.index("--name") + 1],
                first.container_name,
            )

    def test_auth_contents_are_neither_read_nor_copied(self) -> None:
        secret = "AUTH-CONTENT-MUST-NOT-ENTER-THE-WRAPPER"
        (self.codex_home / "auth.json").write_text(secret, encoding="utf-8")
        with self.create() as wrapper:
            source = wrapper.executable.read_text(encoding="utf-8")
            self.assertNotIn(secret, source)
            self.assertNotIn(secret, "\0".join(wrapper.docker_command))
            self.assertEqual((self.codex_home / "auth.json").read_text(), secret)

    def test_explicit_uid_gid_and_root_are_supported(self) -> None:
        with self.create(uid=1234, gid=5678) as host_mapped:
            self.assertEqual(
                host_mapped.docker_command[
                    host_mapped.docker_command.index("--user") + 1
                ],
                "1234:5678",
            )
        with self.create(uid=0, gid=0) as root:
            self.assertEqual(
                root.docker_command[root.docker_command.index("--user") + 1],
                "0:0",
            )

    def test_rejects_relative_or_nonempty_workspace(self) -> None:
        with self.assertRaisesRegex(ValueError, "absolute path"):
            self.create(workspace=Path("relative-workspace"))
        (self.workspace / "unexpected").write_text("x", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "workspace must be empty"):
            self.create()

    def test_wrapper_rechecks_workspace_before_docker_exec(self) -> None:
        with self.create() as wrapper:
            (self.workspace / "appeared-late").write_text("x", encoding="utf-8")
            completed = subprocess.run(
                [wrapper.executable, "--version"],
                check=False,
                text=True,
                capture_output=True,
            )
            self.assertEqual(completed.returncode, 2)
            self.assertIn("workspace is no longer empty", completed.stderr)
            self.assertEqual(completed.stdout, "")

    def test_rejects_unsafe_names_image_paths_and_ids(self) -> None:
        cases = (
            ({"network": "bad network"}, "network"),
            ({"container_name": "--not-a-name"}, "container_name"),
            ({"runtime_image": "-option"}, "runtime_image"),
            ({"uid": 1000}, "supplied together"),
            ({"uid": -1, "gid": 1000}, "numeric IDs"),
        )
        for overrides, message in cases:
            with self.subTest(overrides=overrides):
                with self.assertRaisesRegex(ValueError, message):
                    self.create(**overrides)

        comma_workspace = self.root / "workspace,comma"
        comma_workspace.mkdir()
        with self.assertRaisesRegex(ValueError, "cannot contain"):
            self.create(workspace=comma_workspace)

    def test_rejects_missing_vendor_executable_and_overlapping_mounts(self) -> None:
        empty_vendor = self.root / "empty-vendor"
        empty_vendor.mkdir()
        with self.assertRaisesRegex(FileNotFoundError, "bin/codex"):
            self.create(vendor_bundle=empty_vendor)
        with self.assertRaisesRegex(ValueError, "must not overlap"):
            self.create(codex_home=self.workspace)

    def test_close_removes_only_the_temporary_wrapper(self) -> None:
        wrapper = self.create(container_name="safe-change-codex-cleanup")
        executable = wrapper.executable
        wrapper_directory = executable.parent
        self.assertTrue(executable.is_file())
        with patch("adapter.docker_codex.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess(
                wrapper.cleanup_command, 0, "safe-change-codex-cleanup\n", ""
            )
            wrapper.close()
            wrapper.close()
        run.assert_called_once_with(
            (
                str(self.fake_docker),
                "rm",
                "-f",
                "safe-change-codex-cleanup",
            ),
            check=False,
            capture_output=True,
            text=True,
            timeout=5.0,
        )
        self.assertFalse(wrapper_directory.exists())
        self.assertTrue(self.workspace.is_dir())
        self.assertTrue(self.codex_home.is_dir())
        self.assertTrue(self.vendor_codex.is_file())

    def test_close_allows_already_removed_container(self) -> None:
        wrapper = self.create(container_name="safe-change-codex-already-gone")
        wrapper_directory = wrapper.executable.parent
        with patch("adapter.docker_codex.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess(
                wrapper.cleanup_command,
                1,
                "",
                "Error response from daemon: No such container: "
                "safe-change-codex-already-gone\n",
            )
            wrapper.close()
        self.assertFalse(wrapper_directory.exists())

    def test_close_reports_cleanup_failure_but_still_removes_wrapper(self) -> None:
        wrapper = self.create(container_name="safe-change-codex-cleanup-error")
        wrapper_directory = wrapper.executable.parent
        with patch("adapter.docker_codex.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess(
                wrapper.cleanup_command,
                125,
                "",
                "cannot connect to daemon",
            )
            with self.assertRaisesRegex(RuntimeError, "could not remove"):
                wrapper.close()
        self.assertFalse(wrapper_directory.exists())


if __name__ == "__main__":
    unittest.main()
