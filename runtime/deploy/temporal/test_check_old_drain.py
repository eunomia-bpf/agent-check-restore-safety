#!/usr/bin/env python3
"""Static and semantic unit tests for the Temporal old-drain harness."""

from __future__ import annotations

import copy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
SPEC = importlib.util.spec_from_file_location("temporal_old_drain_check", HERE / "check-old-drain.py")
assert SPEC is not None and SPEC.loader is not None
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


class OldDrainStaticTests(unittest.TestCase):
    def test_operation_id_and_provider_hashes_are_frozen(self) -> None:
        payment = CHECK.expected_record(CHECK.PAYMENT_TOKEN, "/v1/charge", "temporal-payment")
        completion = CHECK.expected_record("complete:" + CHECK.ORDER_ID, "/v1/complete", "temporal-completion")
        self.assertEqual(
            payment,
            {
                "operation_id": "op-aa7bb96565176daea185c7e944a53537c12930bec379230c914313efca29d9f7",
                "request_hash": "a0f90448e294a473cb9522275769863a602d588d3e313371f38b3e86736bd9cc",
                "result_hash": "c6e81254529f4365722a75ce8ccdc8ce2284ea8ed58868800b1cc88c76c36c39",
                "remote_reference": (
                    "temporal-payment/op-aa7bb96565176daea185c7e944a53537c12930bec379230c914313efca29d9f7/commit-1"
                ),
                "path": "/v1/charge",
            },
        )
        self.assertEqual(completion["operation_id"], "op-6cfbdb0237748fa3ce42366aa60089e18bc8dfc91944fa34aea02a5cb021ec9c")
        self.assertEqual(completion["result_hash"], "3ec979cf07fec761d8406d1ae683279b2c2c7c845ee39d484a3ffe1449297d76")

    def test_frozen_source_snapshots_are_unchanged(self) -> None:
        expected = {
            "app/internal/workerapp/variant_v1.go": CHECK.V1_SOURCE_SHA256,
            "app/internal/workerapp/activities.go": CHECK.ACTIVITIES_SOURCE_SHA256,
            "app/internal/workerapp/workflows.go": CHECK.WORKFLOWS_SOURCE_SHA256,
            "app/internal/harness/types.go": CHECK.TYPES_SOURCE_SHA256,
            "app/cmd/starter/main.go": CHECK.STARTER_SOURCE_SHA256,
        }
        for relative, digest in expected.items():
            self.assertEqual(sha256((HERE / relative).read_bytes()).hexdigest(), digest)
        app_files = [path for path in (HERE / "app").rglob("*") if path.is_file()]
        self.assertEqual(CHECK.source_digest(app_files, REPO_ROOT), CHECK.SOURCE_SHA256)

    def test_fault_tool_and_override_are_exactly_pinned(self) -> None:
        old = CHECK.parse_env((HERE / "old-drain.env").read_bytes(), "old-drain.env")
        self.assertEqual(old["TOXIPROXY_VERSION"], "2.12.0")
        self.assertEqual(old["TOXIPROXY_IMAGE"], CHECK.TOXIPROXY_IMAGE)
        self.assertEqual(old["TOXIPROXY_AMD64_MANIFEST_SHA256"], CHECK.TOXIPROXY_MANIFEST)
        override = (HERE / "compose-old-drain.yaml").read_text()
        self.assertIn("- -hold-before-commit=false", override)
        self.assertIn("- -hold-after-commit=false", override)
        self.assertIn("PAYMENT_URL: http://payment-proxy:${TOXIPROXY_LISTEN_PORT}", override)
        self.assertNotIn("ports:", override)

    def test_runner_starts_only_v1_and_captures_full_event_window(self) -> None:
        runner = (HERE / "run-old-drain-case.sh").read_text()
        up = '"${compose[@]}" up --detach --wait --wait-timeout 120'
        self.assertIn(up, runner)
        selected = runner[runner.index(up):runner.index("docker image inspect \"$TOXIPROXY_IMAGE\"")]
        self.assertIn("payment-proxy worker-v1", selected)
        self.assertNotIn("worker-v2", selected)
        self.assertNotIn("worker-compatible-v2", selected)
        self.assertLess(runner.index("docker-events-since-epoch-ns.txt"), runner.index(up))
        self.assertLess(runner.index("docker events \\\n  --since"), runner.index(up))
        self.assertGreater(runner.index("stop_docker_events\njq -s -e"), runner.index("v1-final-inspect.json"))
        self.assertIn("--request DELETE", runner)

    def test_cut_contract_keeps_the_pending_payment_boundary(self) -> None:
        self.assertEqual(len(CHECK.EXPECTED_CUT_TYPES), 5)
        self.assertEqual(CHECK.EXPECTED_CUT_TYPES[-1], "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED")
        self.assertEqual(CHECK.BUSINESS_SIGNALS, (
            "preparation_finished", "driver_selected",
            "driver_at_restaurant", "delivery_finished",
        ))

    def test_duplicate_json_keys_are_rejected(self) -> None:
        with self.assertRaises(CHECK.EvidenceError):
            CHECK.decode_json(b'{"schema":1,"schema":1}', "duplicate fixture")

    def test_history_normalization_removes_only_attempt_identity_noise(self) -> None:
        run_id = "11111111-1111-1111-1111-111111111111"
        history = {
            "events": [{
                "eventId": "1", "eventTime": "2026-01-01T00:00:00Z", "taskId": "9",
                "workflowExecutionStartedEventAttributes": {
                    "originalExecutionRunId": run_id, "firstExecutionRunId": run_id,
                    "requestId": "request", "workflowId": CHECK.WORKFLOW_ID,
                },
            }],
        }
        normalized = CHECK.normalize_history(history, run_id)
        event = normalized["events"][0]
        self.assertNotIn("eventTime", event)
        self.assertNotIn("taskId", event)
        attributes = event["workflowExecutionStartedEventAttributes"]
        self.assertEqual(attributes["originalExecutionRunId"], "<run-id>")
        self.assertEqual(attributes["workflowId"], CHECK.WORKFLOW_ID)
        self.assertNotIn("requestId", attributes)

    def test_toxic_contract_rejects_wrong_direction(self) -> None:
        value = {
            "name": CHECK.TOXIPROXY_PROXY, "listen": f"0.0.0.0:{CHECK.TOXIPROXY_PORT}",
            "upstream": "payment:8081", "enabled": True, "Logger": {},
            "toxics": [{
                "name": "history-cut", "type": "latency", "stream": "upstream", "toxicity": 1,
                "attributes": {"latency": CHECK.TOXIPROXY_LATENCY_MS, "jitter": 0},
            }],
        }
        CHECK.check_toxic_document(value, "h0", "fixture")
        value["toxics"][0]["stream"] = "downstream"
        with self.assertRaises(CHECK.EvidenceError):
            CHECK.check_toxic_document(value, "h0", "fixture")

    def test_docker_event_contract_rejects_any_v2_start(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "docker-events-since-epoch-ns.txt").write_text("1700000000000000000\n")
            (root / "docker-events-until-epoch.txt").write_text("1700000010\n")
            (root / "docker-events-since-at.txt").write_text("2023-11-14T22:13:20.000000000+00:00\n")
            events = []
            counter = 1
            for service in ("temporal", "payment", "completion", "payment-proxy", "worker-v1", "starter"):
                for action in ("create", "start"):
                    events.append({
                        "Type": "container", "Action": action, "timeNano": 1700000000000000000 + counter,
                        "Actor": {"ID": str(counter), "Attributes": {
                            "com.docker.compose.project": "fixture", "com.docker.compose.service": service,
                        }},
                    })
                    counter += 1
            (root / "docker-events.jsonl").write_text(
                "".join(json.dumps(event, separators=(",", ":")) + "\n" for event in events)
            )
            CHECK.check_no_v2_events(root, "fixture")
            target = copy.deepcopy(events[-1])
            target["Actor"]["Attributes"]["com.docker.compose.service"] = "worker-v2"
            with (root / "docker-events.jsonl").open("a") as stream:
                stream.write(json.dumps(target, separators=(",", ":")) + "\n")
            with self.assertRaises(CHECK.EvidenceError):
                CHECK.check_no_v2_events(root, "fixture")

    def test_pair_predicate_rejects_reused_run(self) -> None:
        history = {"events": []}
        common = {
            "schema": 1, "valid": True, "workflow_id": CHECK.WORKFLOW_ID,
            "build_data_sha256": CHECK.BUILD_ENV_SHA256, "static_inputs_sha256": "a" * 64,
            "payment_operation_id": CHECK.operation_id(CHECK.PAYMENT_TOKEN),
            "completion_operation_id": CHECK.operation_id("complete:" + CHECK.ORDER_ID),
            "cut_history": history, "cut_projection": {}, "settled_history": history,
            "final_history": history, "toxic_stream": "upstream", "cut_payment_commits": 0,
            "evidence_digest": "b" * 64,
        }
        h0 = dict(common, case="h0", run_id="same")
        h1 = dict(common, case="h1", run_id="same", toxic_stream="downstream", cut_payment_commits=1)
        with patch.object(CHECK, "check_evidence", side_effect=[copy.deepcopy(h0), copy.deepcopy(h1)]):
            with self.assertRaises(CHECK.EvidenceError):
                CHECK.check_pair(Path("h0"), Path("h1"))

    def test_required_artifacts_include_lifecycle_and_independent_mutations(self) -> None:
        self.assertIn("docker-events.jsonl", CHECK.REQUIRED_FILES)
        self.assertIn("proxy-after-release.json", CHECK.REQUIRED_FILES)
        self.assertIn("v1-final-inspect.json", CHECK.REQUIRED_FILES)
        mutations = (HERE / "check-old-drain-mutations.py").read_text()
        self.assertIn("rehash(candidate)", mutations)
        self.assertIn("observed_json_ignored", mutations)
        self.assertIn("H0/H1 reused one Temporal run", mutations)


if __name__ == "__main__":
    unittest.main()
