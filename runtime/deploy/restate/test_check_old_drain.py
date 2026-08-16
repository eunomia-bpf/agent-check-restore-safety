#!/usr/bin/env python3
"""Static and semantic tests for the native Restate old-drain harness."""

from __future__ import annotations

from hashlib import sha256
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("restate_old_drain_check", HERE / "check-old-drain.py")
assert SPEC is not None and SPEC.loader is not None
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


class OldDrainStaticTests(unittest.TestCase):
    def test_runner_uses_official_resume_and_symmetric_fault_release(self) -> None:
        runner = (HERE / "run-old-drain-case.sh").read_text()
        self.assertIn('restate_cli --yes invocations resume "$invocation_id"', runner)
        self.assertNotIn('invocations resume "$invocation_id" --deployment', runner)
        self.assertIn('"${compose[@]}" up --detach --force-recreate --no-deps payment', runner)
        self.assertIn("PAYMENT_HOLD_BEFORE_COMMIT=false PAYMENT_HOLD_AFTER_COMMIT=false", runner)
        self.assertIn('"${compose[@]}" up --detach --no-deps order-v1', runner)
        self.assertIn("grep -Fc --", runner)
        self.assertNotIn("/v1/query", runner)
        self.assertNotIn("up --detach --no-deps order-v2", runner)
        syntax = subprocess.run(
            ["bash", "-n", str(HERE / "run-old-drain-case.sh")],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(syntax.returncode, 0, syntax.stderr)

    def test_shell_log_counter_matches_literal_dollar_amount(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary) / "source.log"
            line = "[order-1] Executing payment with token token-1 for $42"
            fixture.write_text(line + "\n" + line + "\n")
            script = r'''
set -Eeuo pipefail
order_id=order-1
payment_token=token-1
payment_log_count="$(grep -Fc -- \
  "[$order_id] Executing payment with token $payment_token for \$42" \
  "$1" || true)"
printf '%s\n' "$payment_log_count"
'''
            result = subprocess.run(
                ["bash", "--noprofile", "--norc", "-c", script, "_", str(fixture)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "2\n")

    def test_non_idempotent_records_are_sequential_external_facts(self) -> None:
        payment_id = CHECK.operation_id("11111111-1111-1111-1111-111111111111")
        request_hash = "a" * 64
        first = CHECK.payment_record(payment_id, request_hash, 1)
        second = CHECK.payment_record(payment_id, request_hash, 2)
        self.assertEqual(first["operation_id"], second["operation_id"])
        self.assertEqual(first["request_hash"], second["request_hash"])
        self.assertEqual(first["remote_reference"], f"payment/{payment_id}/commit-1")
        self.assertEqual(second["remote_reference"], f"payment/{payment_id}/commit-2")
        self.assertEqual(
            second["result_hash"],
            sha256(b"charged\0" + payment_id.encode() + b"\0" + b"2").hexdigest(),
        )

    def test_pair_predicate_is_cut_factual_not_outcome_circular(self) -> None:
        equal_names = (
            "build.env", "versions.env", "images.env", "runner.sha256",
            "order.json", "cut-journal.json", "cut-workflow-state.json",
        )
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            h0_root = base / "h0" / "results"
            h1_root = base / "h1" / "results"
            h0_root.mkdir(parents=True)
            h1_root.mkdir(parents=True)
            for name in equal_names:
                (h0_root / name).write_bytes(("same-" + name + "\n").encode())
                (h1_root / name).write_bytes(("same-" + name + "\n").encode())
            common = {
                "case": "h0", "order_id": "same-order", "invocation_id": "same-invocation",
                "payment_token": "same-token", "payment_operation_id": "same-operation",
                "runtime_view_digest": "a" * 64, "observation_seconds": 20,
                "terminal_seconds": 120,
                "source_deployment_id": "deployment-h0", "payment_at_cut_deliveries": 1,
                "payment_at_cut_commits": 0, "v1_engaged": True,
                "availability_preserved": True, "requirement_satisfied": True,
                "evidence_digest": "b" * 64,
            }
            h0 = dict(common)
            h1 = dict(
                common,
                case="h1",
                source_deployment_id="deployment-h1",
                payment_at_cut_commits=1,
                availability_preserved=False,
                requirement_satisfied=False,
                evidence_digest="c" * 64,
            )
            with patch.object(CHECK, "check_evidence", side_effect=[h0, h1]):
                result = CHECK.check_pair(base / "h0", base / "h1")
            self.assertTrue(result["valid"])
            self.assertTrue(result["same_runtime_view"])
            self.assertFalse(result["availability_preserved"])
            self.assertTrue(result["requirement_satisfied_h0"])
            self.assertFalse(result["requirement_satisfied_h1"])

    def test_required_evidence_covers_fault_release_and_v1_engagement(self) -> None:
        for name in (
            "paused-status-after-window.json", "payment-held-container.json",
            "payment-recovered-container.json", "payment-after-recovery.history",
            "resume.stdout", "final-source-retained.log", "final-payment-stats.json",
        ):
            self.assertIn(name, CHECK.REQUIRED_FILES)
        mutations = (HERE / "check-old-drain-mutations.py").read_text()
        self.assertIn("fault-release hold restored", mutations)
        self.assertIn("official resume result changed", mutations)
        self.assertIn("observed_json_ignored", mutations)


if __name__ == "__main__":
    unittest.main()
