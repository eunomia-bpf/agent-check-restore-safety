from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import tempfile
import unittest

from adapter.codex_integrated_runtime_demo import (
    AUDIT_KIND,
    CHARGE_KIND,
    CODEX_DOMAIN,
    ORDER_DOMAIN,
    RESERVE_V1_KIND,
    RESERVE_V2_KIND,
    VM_DOMAIN,
    VM_SANDBOX_ID,
    IntegratedDeployment,
    _configure_private_state,
    _copy_vm_evidence,
    _operation_id,
    _observe_sandbox_absence,
    _observe_stale_sandbox_socket,
    _requirements,
    _sandbox_operation_id,
    _write_release,
)


class IntegratedRuntimeDemoTests(unittest.TestCase):
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
                ("result.json", "{}\n"),
                ("guest.serial.log", "guest\n"),
                ("guest-request.json", "{}\n"),
                ("guest-script.sh", "#!/bin/sh\n"),
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


if __name__ == "__main__":
    unittest.main()
