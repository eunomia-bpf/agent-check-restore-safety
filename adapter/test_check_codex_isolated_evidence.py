from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from adapter.check_codex_isolated_evidence import EvidenceError, check_evidence


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/tmp/bootstrap/step-0013-20260815T124944Z"


@unittest.skipUnless(EVIDENCE.exists(), "isolated Codex evidence is absent")
class IsolatedCodexEvidenceTests(unittest.TestCase):
    def copy_evidence(self, temporary: str) -> Path:
        destination = Path(temporary) / "evidence"
        shutil.copytree(EVIDENCE, destination)
        return destination

    def test_retained_real_run_passes_independent_replay(self) -> None:
        verdict = check_evidence(EVIDENCE)
        self.assertTrue(verdict["valid"])
        self.assertTrue(verdict["history_chain_replayed"])
        self.assertEqual(verdict["payment_deliveries"], 2)
        self.assertEqual(verdict["payment_commits"], 1)
        self.assertEqual(verdict["codex_tool_calls"], 1)

    def test_binary_history_mutation_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            evidence = self.copy_evidence(temporary)
            path = evidence / "runtime.history"
            contents = bytearray(path.read_bytes())
            contents[-2] ^= 1
            path.write_bytes(contents)
            with self.assertRaisesRegex(EvidenceError, "History"):
                check_evidence(evidence)

    def test_duplicate_json_key_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            evidence = self.copy_evidence(temporary)
            (evidence / "payment-stats.json").write_text(
                '{"commits":1,"commits":1,"deliveries":2,'
                '"paths":{"/v1/charge":2}}\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(EvidenceError, "duplicate key"):
                check_evidence(evidence)

    def test_fabricated_runner_summary_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            evidence = self.copy_evidence(temporary)
            result_path = evidence / "result.json"
            result = json.loads(result_path.read_text(encoding="utf-8"))
            altered = deepcopy(result)
            altered["payment"]["durable_commits"] = 2
            result_path.write_text(
                json.dumps(altered, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(EvidenceError, "payment summary"):
                check_evidence(evidence)

    def test_docker_network_flag_mutation_fails_closed(self) -> None:
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
            path.write_text(
                json.dumps(networks, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(EvidenceError, "internal flag"):
                check_evidence(evidence)

    def test_callback_restart_order_mutation_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            evidence = self.copy_evidence(temporary)
            path = evidence / "control-after-restart-inspect.json"
            inspection = json.loads(path.read_text(encoding="utf-8"))
            inspection[0]["State"]["StartedAt"] = "2099-01-01T00:00:00.000000000Z"
            path.write_text(
                json.dumps(inspection, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(EvidenceError, "raw clocks"):
                check_evidence(evidence)

    def test_credential_lifecycle_mutation_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            evidence = self.copy_evidence(temporary)
            path = evidence / "credential-lifecycle.json"
            lifecycle = json.loads(path.read_text(encoding="utf-8"))
            lifecycle["temporary_auth_removed_before_effect"] = False
            path.write_text(
                json.dumps(lifecycle, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(EvidenceError, "credential lifecycle"):
                check_evidence(evidence)


if __name__ == "__main__":
    unittest.main()
