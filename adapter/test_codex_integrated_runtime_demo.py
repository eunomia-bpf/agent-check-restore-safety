from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import tempfile
import unittest
from hashlib import sha256

from adapter.codex_integrated_runtime_demo import (
    AUDIT_KIND,
    CHARGE_KIND,
    CODEX_DOMAIN,
    ORDER_DOMAIN,
    RESERVE_V1_KIND,
    RESERVE_V2_KIND,
    VM_DOMAIN,
    VM_SANDBOX_ID,
    DemoError,
    IntegratedDeployment,
    _configure_private_state,
    _copy_vm_evidence,
    _operation_id,
    _parse_args,
    _observe_sandbox_absence,
    _observe_stale_sandbox_socket,
    _requirements,
    _sandbox_operation_id,
    _selected_source_path,
    _sha256_fd,
    _untracked_python_import_path,
    _write_release,
    _vm_binding,
    _vm_result_summary,
    _vm_runner_command,
)


class IntegratedRuntimeDemoTests(unittest.TestCase):
    def test_source_manifest_ignores_unrelated_retained_scripts(self) -> None:
        retained = "docs/tmp/bootstrap/raw/checker-snapshot/check.py"
        self.assertFalse(_selected_source_path(retained))
        self.assertFalse(_untracked_python_import_path(retained))
        self.assertTrue(_selected_source_path("adapter/app_server.py"))
        self.assertTrue(
            _selected_source_path(
                "runtime/deploy/firecracker/fetch-assets.sh"
            )
        )
        self.assertTrue(
            _selected_source_path(
                "runtime/deploy/firecracker/assets.lock.json"
            )
        )
        self.assertTrue(_untracked_python_import_path("json.py"))

    def test_open_executable_fd_pins_bytes_across_path_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "runner"
            replacement = Path(temporary) / "replacement"
            original = b"original executable bytes"
            path.write_bytes(original)
            descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
            try:
                replacement.write_bytes(b"different bytes")
                replacement.replace(path)
                self.assertEqual(
                    _sha256_fd(descriptor),
                    sha256(original).hexdigest(),
                )
            finally:
                os.close(descriptor)

    def test_operation_identity_separates_three_actor_domains(self) -> None:
        call = "purchase/A-17/audit"
        identities = {
            _operation_id(domain, call)
            for domain in (CODEX_DOMAIN, ORDER_DOMAIN, VM_DOMAIN)
        }
        self.assertEqual(len(identities), 3)
        for identity in identities:
            self.assertRegex(identity, r"^op-[0-9a-f]{64}$")
        sandbox_identity = _sandbox_operation_id(
            VM_DOMAIN,
            VM_SANDBOX_ID,
            call,
        )
        self.assertRegex(sandbox_identity, r"^op-[0-9a-f]{64}$")
        self.assertNotEqual(sandbox_identity, _operation_id(VM_DOMAIN, call))

    def test_rule_change_replaces_only_new_inventory_kind(self) -> None:
        first, second = _requirements("safe-change-integrated-test")
        self.assertEqual(first["results"], second["results"])
        self.assertEqual(first["capacities"], second["capacities"])
        self.assertEqual(
            set(first["kinds"]),
            {CHARGE_KIND, RESERVE_V1_KIND, AUDIT_KIND},
        )
        self.assertEqual(
            set(second["kinds"]),
            {CHARGE_KIND, RESERVE_V2_KIND, AUDIT_KIND},
        )
        self.assertEqual(
            first["kinds"][RESERVE_V1_KIND]["target"],
            "http://inventory:8081/v1/charge",
        )
        self.assertEqual(
            second["kinds"][RESERVE_V2_KIND]["target"],
            "http://inventory:8081/v2/charge",
        )

    def test_private_state_has_distinct_scoped_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary) / "state"
            state.mkdir(mode=0o700)
            tokens = _configure_private_state(state)
            self.assertEqual(set(tokens), {"admin", "codex", "order"})
            self.assertEqual(len(set(tokens.values())), 3)
            for name in ("admin-token", "codex-token", "order-token"):
                path = state / "credentials" / name
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertFalse((state / "credentials/vm-token").exists())
            manifest = json.loads(
                (state / "control-config/adapters.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(manifest["schema"], 1)
            self.assertEqual(
                {entry["domain"] for entry in manifest["adapters"]},
                {CODEX_DOMAIN, ORDER_DOMAIN},
            )

    def test_deployment_names_three_disjoint_networks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            deployment = IntegratedDeployment(
                compose_file=root / "compose.yaml",
                state_dir=root / "state",
                output_dir=root / "output",
                project="safe-change-integrated-test",
                image="safe-change-runtime:test",
                source_revision="a" * 40,
                source_tree_sha256="b" * 64,
                control_port=18787,
                order_port=18080,
            )
            self.assertEqual(
                {
                    deployment.agent_network,
                    deployment.application_network,
                    deployment.effects_network,
                },
                {
                    "safe-change-integrated-test_agent",
                    "safe-change-integrated-test_application",
                    "safe-change-integrated-test_effects",
                },
            )
            self.assertEqual(deployment.environment["CONTROL_PORT"], "18787")
            self.assertEqual(deployment.environment["ORDER_PORT"], "18080")
            self.assertEqual(deployment.environment["SOURCE_REVISION"], "a" * 40)
            self.assertEqual(
                deployment.environment["SOURCE_TREE_SHA256"], "b" * 64
            )

    def test_sigkill_socket_witness_distinguishes_stale_and_absent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            parent.chmod(0o700)
            stale = parent / "stale.sock"
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            listener.bind(str(stale))
            stale.chmod(0o600)
            inode = stale.lstat().st_ino
            listener.close()
            observed = _observe_stale_sandbox_socket(stale, generation=2)
            self.assertEqual(observed["inode"], inode)
            self.assertEqual(observed["event"], "stale-after-control-sigkill")

            absent = _observe_sandbox_absence(
                parent / "absent.sock",
                prior_generation=2,
            )
            self.assertEqual(absent["lstat_errno"], 2)
            self.assertEqual(absent["connect_errno"], 2)

    def test_release_write_and_vm_copy_do_not_retain_private_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            release = root / "order.json"
            _write_release(
                release,
                "v2",
                RESERVE_V2_KIND,
                "http://inventory:8081/v2/charge",
            )
            self.assertEqual(
                json.loads(release.read_text(encoding="utf-8"))["version"],
                "v2",
            )

            source = root / "source"
            destination = root / "destination"
            source.mkdir(mode=0o700)
            for name, value in (
                ("base-image-provenance.json", "{}\n"),
                ("result.json", "{}\n"),
                ("guest.serial.log", "guest\n"),
                ("guest-request.json", "{}\n"),
                ("guest-script.sh", "#!/bin/sh\n"),
                ("host-tools.json", "{}\n"),
                ("snapshots.txt", "before_purchase\n"),
                ("qemu-command.json", "{}\n"),
                ("qemu-process-command.json", "{}\n"),
                ("qmp-protocol.jsonl", "{}\n"),
                ("qemu.log", f"private={root}\n"),
            ):
                (source / name).write_text(value, encoding="utf-8")
            _copy_vm_evidence(source, destination, root)
            self.assertNotIn(
                os.fspath(root),
                (destination / "qemu.log").read_text(encoding="utf-8"),
            )
            self.assertIn(
                "<redacted-private>",
                (destination / "qemu.log").read_text(encoding="utf-8"),
            )

    def test_firecracker_backend_binding_cli_and_evidence_copy(self) -> None:
        self.assertEqual(_parse_args([]).vm_backend, "qemu")
        self.assertEqual(
            _parse_args(["--vm-backend", "firecracker"]).vm_backend,
            "firecracker",
        )
        self.assertEqual(
            _vm_binding("demo", 3, "firecracker")["host_instance_id"],
            "firecracker-demo-g3",
        )
        firecracker_command = _vm_runner_command(
            binary=Path("/private/firecracker-demo"), backend="firecracker",
            accel="kvm", guest_binary=Path("/private/firecracker-guest"),
            host_instance_ids={1: "firecracker-demo-g1", 3: "firecracker-demo-g3"},
            sandbox_socket=Path("/private/sandbox.sock"),
            request_path=Path("/private/request.json"),
            direct_probe="http://127.0.0.1:9/", evidence_dir=Path("/private/evidence"),
        )
        self.assertEqual(
            firecracker_command[firecracker_command.index("-guest") + 1],
            "/private/firecracker-guest",
        )
        self.assertEqual(
            firecracker_command[
                firecracker_command.index("-host-instance-id-g1") + 1
            ],
            "firecracker-demo-g1",
        )
        self.assertEqual(
            firecracker_command[
                firecracker_command.index("-host-instance-id-g3") + 1
            ],
            "firecracker-demo-g3",
        )
        qemu_command = _vm_runner_command(
            binary=Path("/private/vm-demo"), backend="qemu", accel="tcg",
            guest_binary=None, host_instance_ids=None,
            sandbox_socket=Path("/private/sandbox.sock"),
            request_path=Path("/private/request.json"),
            direct_probe="http://127.0.0.1:9/", evidence_dir=Path("/private/evidence"),
        )
        self.assertNotIn("-guest", qemu_command)
        qemu_summary = _vm_result_summary(
            backend="qemu",
            runner_pid=10,
            accel="tcg",
            completed={
                "qemu_pid": 11,
                "first_operation_reused": False,
                "restored_operation_reused": True,
            },
        )
        self.assertNotIn("backend", qemu_summary)
        firecracker_summary = _vm_result_summary(
            backend="firecracker",
            runner_pid=10,
            accel="kvm",
            completed={
                "firecracker_pids": [11, 12],
                "first_operation_reused": False,
                "restored_operation_reused": True,
            },
        )
        self.assertEqual(firecracker_summary["backend"], "firecracker")
        lost_response_summary = _vm_result_summary(
            backend="firecracker",
            runner_pid=10,
            accel="kvm",
            completed={
                "firecracker_pids": [11, 12],
                "first_operation_reused": True,
                "restored_operation_reused": True,
            },
        )
        self.assertTrue(lost_response_summary["first_reused"])
        with self.assertRaisesRegex(DemoError, "QEMU first Operation"):
            _vm_result_summary(
                backend="qemu",
                runner_pid=10,
                accel="tcg",
                completed={
                    "qemu_pid": 11,
                    "first_operation_reused": True,
                    "restored_operation_reused": True,
                },
            )
        with self.assertRaisesRegex(DemoError, "exact Operation reuse outcomes"):
            _vm_result_summary(
                backend="firecracker",
                runner_pid=10,
                accel="kvm",
                completed={
                    "firecracker_pids": [11, 12],
                    "first_operation_reused": False,
                    "restored_operation_reused": False,
                },
            )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "destination"
            source.mkdir(mode=0o700)
            names = (
                "result.json", "assets.json", "guest-request.json",
                "guest-results.json", "snapshot-provenance.json",
                "firecracker-processes.json", "firecracker-supervisor.jsonl",
                "timeline.json", "firecracker-api-g1.jsonl", "firecracker-api-g3.jsonl",
                "firecracker-gate-g1.jsonl", "firecracker-gate-g3.jsonl",
                "firecracker-relay-g1.jsonl", "firecracker-relay-g3.jsonl",
                "snapshot.state", "snapshot.memory", "guest-initramfs.cpio",
            )
            for name in names:
                (source / name).write_text("{}\n", encoding="utf-8")
            (source / "firecracker-api-g1.jsonl").write_text(
                json.dumps(
                    {
                        "request": {
                            "uds_path": os.fspath(source / "vsock-g1"),
                            "snapshot_path": os.fspath(source / "snapshot.state"),
                            "mem_file_path": os.fspath(source / "snapshot.memory"),
                            "kernel_image_path": "/proc/self/fd/4",
                        }
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (source / "firecracker-api-g3.jsonl").write_text(
                json.dumps(
                    {
                        "request": {
                            "mem_backend": {"backend_path": "/proc/self/fd/5"},
                            "vsock_override": {
                                "uds_path": os.fspath(source / "vsock-g3")
                            },
                        }
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            for name in ("firecracker-g1.log", "firecracker-g3.log"):
                (source / name).write_text(f"private={root}\n", encoding="utf-8")
            _copy_vm_evidence(source, destination, root, backend="firecracker")
            self.assertTrue((destination / "firecracker-processes.json").is_file())
            copied_log = (destination / "firecracker-g3.log").read_text(encoding="utf-8")
            self.assertNotIn(os.fspath(root), copied_log)
            self.assertIn("<redacted-private>", copied_log)
            g1_api = json.loads(
                (destination / "firecracker-api-g1.jsonl").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                g1_api["request"]["uds_path"], "<vm-evidence>/vsock-g1"
            )
            self.assertEqual(
                g1_api["request"]["snapshot_path"],
                "<vm-evidence>/snapshot.state",
            )
            self.assertEqual(
                g1_api["request"]["kernel_image_path"], "/proc/self/fd/4"
            )
            g3_api_text = (
                destination / "firecracker-api-g3.jsonl"
            ).read_text(encoding="utf-8")
            self.assertNotIn(os.fspath(root), g3_api_text)
            self.assertEqual(
                json.loads(g3_api_text)["request"]["vsock_override"][
                    "uds_path"
                ],
                "<vm-evidence>/vsock-g3",
            )


if __name__ == "__main__":
    unittest.main()
