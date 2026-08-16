from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from adapter.check_codex_integrated_evidence import (
    EvidenceError,
    check_evidence,
    main,
)


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/tmp/bootstrap/step-0017-20260816T113812Z"


@unittest.skipUnless(EVIDENCE.exists(), "integrated Codex/VM evidence is absent")
class IntegratedEvidenceTests(unittest.TestCase):
    def copy_evidence(self, temporary: str) -> Path:
        destination = Path(temporary) / "evidence"
        shutil.copytree(EVIDENCE, destination)
        return destination

    @staticmethod
    def write_json(path: Path, value: object) -> None:
        path.write_text(
            json.dumps(value, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )

    def test_retained_run_passes_independent_replay(self) -> None:
        verdict = check_evidence(EVIDENCE)
        self.assertTrue(verdict["valid"])
        self.assertTrue(verdict["history_chain_replayed"])
        self.assertEqual(verdict["history_sequence"], 16)
        self.assertEqual(verdict["external_effects"]["deliveries"], 5)
        self.assertEqual(verdict["external_effects"]["commits"], 3)
        self.assertEqual(len(verdict["operation_ids"]), 3)
        self.assertTrue(verdict["network_isolation"]["attested"])
        self.assertTrue(verdict["codex_protocol"]["real_app_server_process"])
        self.assertTrue(verdict["fault_correlations"]["whole_vm_restored"])
        self.assertEqual(verdict["sandbox_boundary"]["generations"], [1, 2, 3])
        self.assertTrue(verdict["sandbox_boundary"]["credential_free"])

    def test_guest_routing_field_mutation_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            evidence = self.copy_evidence(temporary)
            path = evidence / "vm/guest-request.json"
            request = json.loads(path.read_text(encoding="utf-8"))
            request["url"] = "http://ledger:8081/v1/charge"
            self.write_json(path, request)
            with self.assertRaisesRegex(EvidenceError, "guest request"):
                check_evidence(evidence)

    def test_guest_bearer_mutation_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            evidence = self.copy_evidence(temporary)
            path = evidence / "vm/guest-script.sh"
            path.write_text(
                path.read_text(encoding="utf-8") + "# Authorization: Bearer forged\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(EvidenceError, "guest script"):
                check_evidence(evidence)

    def test_qemu_control_tcp_mutation_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            evidence = self.copy_evidence(temporary)
            path = evidence / "vm/qemu-command.json"
            command = json.loads(path.read_text(encoding="utf-8"))
            index = command["arguments"].index("-netdev") + 1
            command["arguments"][index] = command["arguments"][index].replace(
                "-U <host-sandbox-socket>",
                "127.0.0.1 18787",
            )
            self.write_json(path, command)
            with self.assertRaisesRegex(EvidenceError, "forwarding boundary"):
                check_evidence(evidence)

    def test_sandbox_socket_mode_mutation_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            evidence = self.copy_evidence(temporary)
            path = evidence / "sandbox-lifecycle.json"
            lifecycle = json.loads(path.read_text(encoding="utf-8"))
            lifecycle[0]["socket_mode"] = "0666"
            self.write_json(path, lifecycle)
            with self.assertRaisesRegex(EvidenceError, "private healthy socket"):
                check_evidence(evidence)

    def test_binary_history_mutation_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            evidence = self.copy_evidence(temporary)
            path = evidence / "runtime.history"
            contents = bytearray(path.read_bytes())
            contents[-2] ^= 1
            path.write_bytes(contents)
            with self.assertRaisesRegex(EvidenceError, "History"):
                check_evidence(evidence)

    def test_qmp_load_mutation_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            evidence = self.copy_evidence(temporary)
            path = evidence / "vm/qmp-protocol.jsonl"
            records = [json.loads(line) for line in path.read_text().splitlines()]
            load = next(
                record
                for record in records
                if record["direction"] == "client_to_server"
                and record["payload"].get("execute")
                == "human-monitor-command"
                and record["payload"].get("arguments", {}).get("command-line")
                == "loadvm before_purchase"
            )
            load["payload"]["arguments"]["command-line"] = "savevm before_purchase"
            path.write_text(
                "".join(
                    json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
                    for record in records
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(EvidenceError, "QMP"):
                check_evidence(evidence)

    def test_docker_network_internal_flag_mutation_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            evidence = self.copy_evidence(temporary)
            path = evidence / "docker-network-inspect.json"
            networks = json.loads(path.read_text(encoding="utf-8"))
            effects = next(
                network
                for network in networks
                if str(network.get("Name", "")).endswith("_effects")
            )
            effects["Internal"] = False
            self.write_json(path, networks)
            with self.assertRaisesRegex(EvidenceError, "internal flag"):
                check_evidence(evidence)

    def test_codex_tool_mutation_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            evidence = self.copy_evidence(temporary)
            path = evidence / "app-server.jsonl"
            records = [json.loads(line) for line in path.read_text().splitlines()]
            call = next(
                record
                for record in records
                if record["direction"] == "server_to_client"
                and record["payload"].get("method") == "item/tool/call"
            )
            call["payload"]["params"]["tool"] = "unprotected_purchase"
            path.write_text(
                "".join(
                    json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
                    for record in records
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(EvidenceError, "Codex tool"):
                check_evidence(evidence)

    def test_fabricated_inventory_v2_path_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            evidence = self.copy_evidence(temporary)
            path = evidence / "inventory.history"
            record = json.loads(path.read_text(encoding="utf-8"))
            record["path"] = "/v2/charge"
            path.write_text(
                json.dumps(record, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(EvidenceError, "durable external record"):
                check_evidence(evidence)

    def test_cli_writes_default_independent_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            evidence = self.copy_evidence(temporary)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main([str(evidence)]), 0)
            verdict = json.loads(
                (evidence / "independent-verdict.json").read_text(encoding="utf-8")
            )
            self.assertTrue(verdict["valid"])
            self.assertEqual(verdict["history_sequence"], 16)


if __name__ == "__main__":
    unittest.main()
