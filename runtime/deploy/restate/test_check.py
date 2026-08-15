#!/usr/bin/env python3
"""Synthetic end-to-end and mutation tests for the Restate evidence checker."""

from __future__ import annotations

import base64
import importlib.util
import json
from hashlib import sha256
from pathlib import Path
import struct
import tempfile
import unittest


CHECK_PATH = Path(__file__).with_name("check.py")
SPEC = importlib.util.spec_from_file_location("restate_evidence_check", CHECK_PATH)
assert SPEC is not None and SPEC.loader is not None
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


def compact(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=True).encode()


class Fixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.artifacts: dict[str, dict[str, str]] = {}
        self.order_id = "order-checker-1"
        self.amount = 42
        self.token = "01234567-89ab-4def-8123-456789abcdef"
        self.domain = "restate-order-workflow"
        self.payment_id = CHECK._operation_id(self.domain, self.token)
        self.completion_id = CHECK._operation_id(self.domain, f"order/{self.order_id}/completion")
        self.payment_body = compact({"order_id": self.order_id, "amount": self.amount})
        self.completion_body = compact({"order_id": self.order_id, "status": "DELIVERED"})
        self.payment_result = sha256(b"charged\x00" + self.payment_id.encode() + b"\x001").hexdigest()
        self.completion_result = sha256(b"charged\x00" + self.completion_id.encode()).hexdigest()
        self.v1_image = "sha256:" + "1" * 64
        self.v2_image = "sha256:" + "2" * 64
        self.program_hash = "3" * 64
        self.v2_context = "4" * 64
        self.requirement_hash = "5" * 64
        self.deployment_v1 = "dp_v1_checker"
        self.deployment_v2 = "dp_v2_checker"

    def write(self, relative: str, data: bytes) -> dict[str, str]:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        descriptor = {"path": relative, "sha256": sha256(data).hexdigest()}
        self.artifacts[relative] = descriptor
        return descriptor

    def write_json(self, relative: str, value: object) -> dict[str, str]:
        return self.write(relative, compact(value) + b"\n")

    def replace_json(self, relative: str, value: object) -> None:
        data = compact(value) + b"\n"
        (self.root / relative).write_bytes(data)
        if relative in self.artifacts:
            self.artifacts[relative]["sha256"] = sha256(data).hexdigest()

    def requirement(self) -> dict[str, object]:
        return {
            "id": "food-ordering-v2",
            "results": {"paid": 1, "delivered": 1},
            "capacities": {"charge": 1},
            "kinds": {
                "charge-v1": {
                    "costs": {"charge": 1}, "produces": {"paid": 1},
                    "retry_safe": False, "queryable": False,
                },
                "finish": {
                    "costs": {}, "produces": {"delivered": 1},
                    "retry_safe": True, "queryable": False,
                    "target": "http://completion:8081/v1/complete",
                    "method": "POST", "response_classifier": "operation-receipt-v1",
                },
            },
        }

    def source_certificate(self) -> dict[str, object]:
        source_requirement = {
            "id": "food-ordering-v1",
            "results": {"paid": 1, "delivered": 1},
            "capacities": {"charge": 1},
            "kinds": {},
        }
        return {
            "schema": 1, "decision": "activate",
            "history": {"sequence": 0, "hash": CHECK.ZERO_HASH}, "from_rule": 0,
            "requirement": source_requirement,
            "rule": {"version": 1, "requirement_hash": "6" * 64, "allow": ["charge-v1", "finish"]},
            "digest": "7" * 64,
        }

    def payment_operation(self) -> dict[str, object]:
        return {
            "id": self.payment_id, "domain": self.domain, "kind": "charge-v1",
            "request_hash": CHECK._gateway_hash("http://payment:8081/v1/charge", self.payment_id, self.payment_body),
            "rule_version": 1, "costs": {"charge": 1}, "produces": {"paid": 1},
            "retry_safe": False, "queryable": True,
            "target": "http://payment:8081/v1/charge", "method": "POST",
            "response_classifier": "operation-receipt-v1",
            "query_target": "http://payment:8081/v1/query", "query_method": "POST",
            "query_classifier": "operation-observation-v1", "request_stored": True,
            "request_body": base64.b64encode(self.payment_body).decode(), "phase": "prepared",
        }

    def completion_operation(self) -> dict[str, object]:
        return {
            "id": self.completion_id, "domain": self.domain, "kind": "finish",
            "request_hash": CHECK._gateway_hash("http://completion:8081/v1/complete", self.completion_id, self.completion_body),
            "rule_version": 2, "costs": {}, "produces": {"delivered": 1},
            "retry_safe": True, "queryable": False,
            "target": "http://completion:8081/v1/complete", "method": "POST",
            "response_classifier": "operation-receipt-v1", "request_stored": True,
            "request_body": base64.b64encode(self.completion_body).decode(), "phase": "prepared",
        }

    def add_event(self, events: list[dict[str, object]], frames: list[bytes], operation: str, data: object) -> None:
        sequence = len(events) + 1
        previous = CHECK.ZERO_HASH if not events else str(events[-1]["hash"])
        data_bytes = compact(data)
        event_hash = CHECK._event_hash(sequence, previous, operation, data_bytes)
        payload = (
            b'{"version":1,"sequence":' + str(sequence).encode()
            + b',"operation":' + compact(operation)
            + b',"data":' + data_bytes
            + b',"previous_hash":' + compact(previous)
            + b',"hash":' + compact(event_hash) + b"}"
        )
        frames.append(b"HST1" + struct.pack(">Q", len(payload)) + payload)
        events.append({
            "sequence": sequence, "operation": operation, "data": data,
            "previous_hash": previous, "hash": event_hash,
        })

    def histories(self) -> dict[str, dict[str, object]]:
        histories: dict[str, dict[str, object]] = {}
        for name in ("h0", "h1"):
            events: list[dict[str, object]] = []
            frames: list[bytes] = []
            self.add_event(events, frames, "rule.activated", {
                "semantic_version": 1, "certificate": self.source_certificate(),
            })
            self.add_event(events, frames, "operation.prepared", {
                "semantic_version": 1, "operation": self.payment_operation(),
            })
            self.add_event(events, frames, "operation.phase", {
                "semantic_version": 1, "id": self.payment_id,
                "update": {"phase": "dispatched", "dispatch_owner": "a" * 32, "dispatch_generation": 1},
            })
            self.add_event(events, frames, "operation.phase", {
                "semantic_version": 1, "id": self.payment_id, "update": {"phase": "unknown"},
            })
            if name == "h0":
                certificate = {
                    "schema": 1, "decision": "impossible",
                    "history": {"sequence": 4, "hash": events[-1]["hash"]}, "from_rule": 1,
                    "requirement": self.requirement(),
                    "witness": {"reason": "no completion can produce paid"}, "digest": "8" * 64,
                }
            else:
                observation = compact({
                    "schema": 1, "operation_id": self.payment_id,
                    "request_hash": self.payment_operation()["request_hash"],
                    "outcome": "succeeded", "fact_hash": self.payment_result,
                    "remote_reference": f"payment/{self.payment_id}/commit-1",
                }) + b"\n"
                self.add_event(events, frames, "operation.phase", {
                    "semantic_version": 1, "id": self.payment_id,
                    "update": {
                        "phase": "succeeded", "result_hash": self.payment_result,
                        "status_code": 200, "result_body": base64.b64encode(observation).decode(),
                        "remote_reference": f"payment/{self.payment_id}/commit-1", "settlement": "query",
                    },
                })
                certificate = {
                    "schema": 1, "decision": "activate",
                    "history": {"sequence": 5, "hash": events[-1]["hash"]}, "from_rule": 1,
                    "requirement": self.requirement(),
                    "rule": {"version": 2, "requirement_hash": self.requirement_hash, "allow": ["finish"]},
                    "digest": "9" * 64,
                }
                self.add_event(events, frames, "rule.activated", {
                    "semantic_version": 1, "certificate": certificate,
                })
                self.add_event(events, frames, "operation.prepared", {
                    "semantic_version": 1, "operation": self.completion_operation(),
                })
                self.add_event(events, frames, "operation.phase", {
                    "semantic_version": 1, "id": self.completion_id,
                    "update": {"phase": "dispatched", "dispatch_owner": "b" * 32, "dispatch_generation": 1},
                })
                receipt = compact({
                    "schema": 1, "operation_id": self.completion_id, "outcome": "succeeded",
                    "result_hash": self.completion_result,
                    "remote_reference": f"completion/{self.completion_id}",
                }) + b"\n"
                self.add_event(events, frames, "operation.phase", {
                    "semantic_version": 1, "id": self.completion_id,
                    "update": {
                        "phase": "succeeded", "result_hash": self.completion_result,
                        "status_code": 200, "result_body": base64.b64encode(receipt).decode(),
                        "remote_reference": f"completion/{self.completion_id}",
                    },
                })
            histories[name] = {"events": events, "frames": b"".join(frames), "certificate": certificate}
        return histories

    def build(self) -> dict[str, object]:
        requirement = self.requirement()
        requirement_bytes = compact(requirement) + b"\n"
        self.requirement_hash = sha256(requirement_bytes).hexdigest()
        histories = self.histories()

        order_input = {
            "id": self.order_id, "restaurantId": "restaurant-01",
            "products": [{"productId": "pizza-01", "description": "Pizza", "quantity": 1}],
            "totalCost": self.amount, "deliveryDelay": 0,
        }
        order_artifact = self.write_json("order.json", order_input)

        raw_v1 = {
            "id": self.deployment_v1, "uri": "http://order-v1:9080/",
            "protocol_type": "BidiStream", "http_version": "HTTP/2.0",
            "metadata": {"variant": "v1"}, "created_at": "2026-08-15T00:00:00Z",
            "min_protocol_version": 5, "max_protocol_version": 7,
            "sdk_version": "restate-sdk-typescript/1.16.6",
            "services": [{"name": "order-workflow", "revision": 1}],
        }
        raw_v2 = {
            "id": self.deployment_v2, "uri": "http://order-v2:9080/",
            "protocol_type": "BidiStream", "http_version": "HTTP/2.0",
            "metadata": {"variant": "v2"}, "created_at": "2026-08-15T00:01:00Z",
            "min_protocol_version": 5, "max_protocol_version": 7,
            "sdk_version": "restate-sdk-typescript/1.16.6",
            "services": [{"name": "order-workflow", "revision": 2}],
        }
        raw_deployments = {
            "h0": self.write_json("h0/restate-deployments.raw.json", {"deployments": [raw_v1]}),
            "h1": self.write_json("h1/restate-deployments.raw.json", {"deployments": [raw_v1, raw_v2]}),
        }
        normalized_v1 = {
            "deployment_id": self.deployment_v1, "endpoint": "order-v1",
            "image_id": self.v1_image, "context_sha256": "a" * 64,
            "program_sha256": "b" * 64,
        }
        normalized_v2 = {
            "deployment_id": self.deployment_v2, "endpoint": "order-v2",
            "image_id": self.v2_image, "context_sha256": self.v2_context,
            "program_sha256": self.program_hash,
        }
        normalized_deployments = {
            "h0": self.write_json("h0/restate-deployments.normalized.json", {
                "schema": 1, "restate_version": CHECK.RESTATE_VERSION,
                "server_image": CHECK.RESTATE_IMAGE, "raw_sha256": raw_deployments["h0"]["sha256"],
                "v1": normalized_v1, "planned_target_program_sha256": self.program_hash,
            }),
            "h1": self.write_json("h1/restate-deployments.normalized.json", {
                "schema": 1, "restate_version": CHECK.RESTATE_VERSION,
                "server_image": CHECK.RESTATE_IMAGE, "raw_sha256": raw_deployments["h1"]["sha256"],
                "v1": normalized_v1, "v2": normalized_v2, "target_program_sha256": self.program_hash,
            }),
        }

        case_artifacts: dict[str, dict[str, dict[str, str]]] = {}
        for name in ("h0", "h1"):
            data = histories[name]
            events = data["events"]
            assert isinstance(events, list)
            certificate = data["certificate"]
            assert isinstance(certificate, dict)
            prefix = f"{name}/"
            history_artifact = self.write(prefix + "runtime.history", data["frames"])
            head = {"version": 1, "sequence": len(events), "hash": events[-1]["hash"]}
            head["checksum"] = sha256(
                b"history-head-anchor-v1\x00" + struct.pack(">Q", len(events)) + str(events[-1]["hash"]).encode()
            ).hexdigest()
            head_artifact = self.write_json(prefix + "runtime.head", head)
            history_view_artifact = self.write_json(prefix + "history-view.json", events)
            requirement_artifact = self.write(prefix + "requirement.json", requirement_bytes)
            state = {
                "schema": 1, "history": certificate["history"], "from_rule": 1,
                "settled": ({"used": {"charge": 1}, "results": {"paid": 1}} if name == "h1" else {"used": {}, "results": {}}),
                "open_operations": ({} if name == "h1" else {
                    self.payment_id: {
                        "id": self.payment_id, "costs": {"charge": 1},
                        "produces": {"paid": 1}, "retry_safe": False, "queryable": True,
                    },
                }),
            }
            state_artifact = self.write_json(prefix + "certificate-state.json", state)
            certificate_artifact = self.write_json(prefix + "certificate.json", certificate)
            verdict = {
                "valid": True, "decision": certificate["decision"],
                "history_sequence": certificate["history"]["sequence"],
                "history_hash": certificate["history"]["hash"],
            }
            if name == "h1":
                verdict["rule_version"] = 2
            verdict_artifact = self.write_json(prefix + "certificate-verdict.json", verdict)

            final_payment = dict(self.payment_operation())
            final_payment.update({"phase": "unknown", "dispatch_owner": "a" * 32, "dispatch_generation": 1})
            operations: dict[str, object] = {self.payment_id: final_payment}
            if name == "h1":
                final_payment.update({
                    "phase": "succeeded", "result_hash": self.payment_result, "status_code": 200,
                    "remote_reference": f"payment/{self.payment_id}/commit-1", "settlement": "query",
                })
                final_completion = dict(self.completion_operation())
                final_completion.update({
                    "phase": "succeeded", "dispatch_owner": "b" * 32, "dispatch_generation": 1,
                    "result_hash": self.completion_result, "status_code": 200,
                    "remote_reference": f"completion/{self.completion_id}",
                })
                operations[self.completion_id] = final_completion
            final_state = {
                "history": {"sequence": len(events), "hash": events[-1]["hash"]},
                "requirement": (requirement if name == "h1" else self.source_certificate()["requirement"]),
                "rule": (
                    {"version": 2, "requirement_hash": self.requirement_hash, "allow": []}
                    if name == "h1" else self.source_certificate()["rule"]
                ),
                "operations": operations,
            }
            final_state_artifact = self.write_json(prefix + "final-state.json", final_state)

            payment_records = b""
            completion_records = b""
            if name == "h1":
                payment_records = compact({
                    "operation_id": self.payment_id,
                    "request_hash": CHECK._provider_hash("/v1/charge", self.payment_body),
                    "result_hash": self.payment_result,
                    "remote_reference": f"payment/{self.payment_id}/commit-1", "path": "/v1/charge",
                }) + b"\n"
                completion_records = compact({
                    "operation_id": self.completion_id,
                    "request_hash": CHECK._provider_hash("/v1/complete", self.completion_body),
                    "result_hash": self.completion_result,
                    "remote_reference": f"completion/{self.completion_id}", "path": "/v1/complete",
                }) + b"\n"
            payment_artifact = self.write(prefix + "payment.history", payment_records)
            completion_artifact = self.write(prefix + "completion.history", completion_records)

            invocation = f"inv_{name}_checker"
            status_raw = {
                "rows": [{
                    "id": invocation, "target": f"order-workflow/{self.order_id}/run",
                    "status": "paused", "pinned_deployment_id": self.deployment_v1,
                    "pinned_service_protocol_version": 6,
                    "last_attempt_deployment_id": self.deployment_v1,
                    "retry_count": 1, "journal_size": 2,
                    "created_at": "2026-08-15T00:02:00Z", "modified_at": "2026-08-15T00:03:00Z",
                }],
            }
            payment_raw = bytes.fromhex("580162077061796d656e74")
            journal_rows = [
                {
                    "index": 0, "version": 2, "entry_type": "Command: Input", "name": "",
                    "completed": True, "raw": "00", "raw_length": 1,
                    "entry_lite_json": compact({"Command": {"Input": {}}}).decode(),
                },
                {
                    "index": 1, "version": 2, "entry_type": "Command: Run", "name": "payment",
                    "completed": False, "raw": payment_raw.hex(), "raw_length": len(payment_raw),
                    "entry_lite_json": compact({"Command": {"Run": {"completion_id": 1, "name": "payment"}}}).decode(),
                },
            ]
            journal_raw = {"rows": journal_rows}
            status_artifact = self.write_json(prefix + "restate-status.raw.json", status_raw)
            journal_artifact = self.write_json(prefix + "restate-journal.raw.json", journal_raw)
            projected_journal = [{
                "index": row["index"], "kind": row["entry_type"], "name": row["name"],
                "completed": row["completed"],
                "payload_sha256": sha256(bytes.fromhex(row["raw"])).hexdigest(),
            } for row in journal_rows]
            cut = {
                "schema": 1, "invocation_id": invocation, "deployment_id": self.deployment_v1,
                "endpoint": "order-v1", "status": "paused", "order_id": self.order_id,
                "input_sha256": order_artifact["sha256"], "payment_token": self.token,
                "payment_run": {"name": "payment", "completed": False},
                "journal": projected_journal, "workflow_state": {"status": "PAYMENT_PENDING"},
                "raw_status_sha256": status_artifact["sha256"],
                "raw_journal_sha256": journal_artifact["sha256"],
            }
            cut_artifact = self.write_json(prefix + "restate-cut.json", cut)
            restate_final = {
                "schema": 1, "source_invocation_id": invocation, "source_status": "fenced",
                "continuation_started": name == "h1",
                "order_status": "DELIVERED" if name == "h1" else "PAYMENT_PENDING",
            }
            if name == "h1":
                restate_final.update({"target_endpoint": "order-v2", "target_program_sha256": self.program_hash})
            else:
                restate_final.update({
                    "planned_target_endpoint": "order-v2",
                    "planned_target_program_sha256": self.program_hash,
                })
            restate_final_artifact = self.write_json(prefix + "restate-final.json", restate_final)
            container_items = [
                {"role": "restate", "name": "restate", "image_id": "sha256:" + "c" * 64, "running": True, "networks": ["application"]},
                {"role": "control", "name": "control", "image_id": "sha256:" + "d" * 64, "running": True, "networks": ["control", "effects"]},
            ]
            if name == "h1":
                container_items.append({
                    "role": "target-v2", "name": "order-v2", "image_id": self.v2_image,
                    "running": True, "networks": ["application", "control"],
                    "started_after_history_sequence": 6,
                })
            containers = {
                "schema": 1,
                "items": container_items,
            }
            containers_artifact = self.write_json(prefix + "containers.json", containers)
            removal_artifact = self.write_json(prefix + "v1-removal.json", {
                "schema": 1, "container": "order-v1", "inspect_exit_code": 1,
                "stderr": "Error: No such container: order-v1",
                "fenced_before_history_sequence": 5 if name == "h1" else 4,
            })
            case_artifacts[name] = {
                "history": history_artifact, "head": head_artifact,
                "history_view": history_view_artifact, "requirement": requirement_artifact,
                "certificate_state": state_artifact, "certificate": certificate_artifact,
                "certificate_verdict": verdict_artifact, "final_state": final_state_artifact,
                "payment_records": payment_artifact, "completion_records": completion_artifact,
                "restate_cut": cut_artifact, "restate_final": restate_final_artifact,
                "restate_status_raw": status_artifact, "restate_journal_raw": journal_artifact,
                "containers": containers_artifact, "v1_removal": removal_artifact,
            }

        manifest = {
            "schema": 1, "experiment": CHECK.EXPERIMENT, "domain": self.domain,
            "upstream": {
                "repository": "https://github.com/restatedev/examples.git", "tag": "v1.7.7",
                "commit": CHECK.UPSTREAM_COMMIT, "restate_version": CHECK.RESTATE_VERSION,
                "restate_image": CHECK.RESTATE_IMAGE,
            },
            "order": {
                "order_id": self.order_id, "amount": self.amount, "payment_token": self.token,
                "input_sha256": order_artifact["sha256"], "input": order_artifact,
            },
            "target": {
                "program_sha256": self.program_hash, "v2_context_sha256": self.v2_context,
                "v1_image_id": self.v1_image, "v2_image_id": self.v2_image,
                "requirement_sha256": self.requirement_hash,
            },
            "cases": case_artifacts,
            "restate_deployments": {
                name: {"normalized": normalized_deployments[name], "raw": raw_deployments[name]}
                for name in ("h0", "h1")
            },
        }
        self.manifest = manifest
        self.replace_json("manifest.json", manifest)
        return manifest

    def refresh_manifest(self) -> None:
        self.replace_json("manifest.json", self.manifest)


class CheckerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.fixture = Fixture(self.root)
        self.manifest = self.fixture.build()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def check(self) -> dict[str, object]:
        return CHECK.check_evidence(self.root, fresh_certificates=False)

    def test_accepts_complete_joined_evidence(self) -> None:
        verdict = self.check()
        self.assertTrue(verdict["valid"])
        self.assertEqual(verdict["h0_decision"], "impossible")
        self.assertEqual(verdict["h1_decision"], "activate")
        self.assertEqual(verdict["h1_payment_commits"], 1)

    def test_rejects_second_durable_charge_even_when_manifest_is_rehashed(self) -> None:
        relative = "h1/payment.history"
        second = {
            "operation_id": self.fixture.payment_id,
            "request_hash": CHECK._provider_hash("/v1/charge", self.fixture.payment_body),
            "result_hash": sha256(b"charged\x00" + self.fixture.payment_id.encode() + b"\x002").hexdigest(),
            "remote_reference": f"payment/{self.fixture.payment_id}/commit-2", "path": "/v1/charge",
        }
        path = self.root / relative
        data = path.read_bytes() + compact(second) + b"\n"
        path.write_bytes(data)
        self.manifest["cases"]["h1"]["payment_records"]["sha256"] = sha256(data).hexdigest()
        self.fixture.refresh_manifest()
        with self.assertRaisesRegex(CHECK.EvidenceError, "exactly one durable payment"):
            self.check()

    def test_rejects_journal_difference_after_all_local_hashes_are_rebound(self) -> None:
        journal_relative = "h1/restate-journal.raw.json"
        journal = json.loads((self.root / journal_relative).read_text())
        journal["rows"][0]["raw"] = "01"
        self.fixture.replace_json(journal_relative, journal)
        cut_relative = "h1/restate-cut.json"
        cut = json.loads((self.root / cut_relative).read_text())
        cut["raw_journal_sha256"] = self.fixture.artifacts[journal_relative]["sha256"]
        cut["journal"][0]["payload_sha256"] = sha256(b"\x01").hexdigest()
        self.fixture.replace_json(cut_relative, cut)
        self.fixture.refresh_manifest()
        with self.assertRaisesRegex(CHECK.EvidenceError, "journal or visible workflow state differs"):
            self.check()

    def test_rejects_h0_claimed_completion(self) -> None:
        relative = "h0/restate-final.json"
        final = json.loads((self.root / relative).read_text())
        final["continuation_started"] = True
        final["order_status"] = "DELIVERED"
        self.fixture.replace_json(relative, final)
        self.fixture.refresh_manifest()
        with self.assertRaisesRegex(CHECK.EvidenceError, "H0 did not remain safely refused"):
            self.check()

    def test_rejects_h0_target_prestart(self) -> None:
        relative = "h0/containers.json"
        containers = json.loads((self.root / relative).read_text())
        containers["items"].append({
            "role": "target-v2", "name": "order-v2", "image_id": self.fixture.v2_image,
            "running": True, "networks": ["application", "control"],
            "started_after_history_sequence": 4,
        })
        self.fixture.replace_json(relative, containers)
        self.fixture.refresh_manifest()
        with self.assertRaisesRegex(CHECK.EvidenceError, "H0 started the refused target v2 container"):
            self.check()

    def test_rejects_h1_target_started_before_activation(self) -> None:
        relative = "h1/containers.json"
        containers = json.loads((self.root / relative).read_text())
        target = next(item for item in containers["items"] if item["role"] == "target-v2")
        target["started_after_history_sequence"] = 5
        self.fixture.replace_json(relative, containers)
        self.fixture.refresh_manifest()
        with self.assertRaisesRegex(CHECK.EvidenceError, "did not start after target Rule activation"):
            self.check()

    def test_rejects_h0_registered_target_v2_after_raw_hash_rebind(self) -> None:
        raw_relative = "h0/restate-deployments.raw.json"
        h0_raw = json.loads((self.root / raw_relative).read_text())
        h1_raw = json.loads((self.root / "h1/restate-deployments.raw.json").read_text())
        h0_raw["deployments"].append(h1_raw["deployments"][1])
        self.fixture.replace_json(raw_relative, h0_raw)
        normalized_relative = "h0/restate-deployments.normalized.json"
        normalized = json.loads((self.root / normalized_relative).read_text())
        normalized["raw_sha256"] = self.fixture.artifacts[raw_relative]["sha256"]
        self.fixture.replace_json(normalized_relative, normalized)
        self.fixture.refresh_manifest()
        with self.assertRaisesRegex(CHECK.EvidenceError, "H0 registered the refused target v2 deployment"):
            self.check()

    def test_rejects_raw_payment_completion_notification(self) -> None:
        journal_relative = "h0/restate-journal.raw.json"
        journal = json.loads((self.root / journal_relative).read_text())
        payment = journal["rows"].pop()
        notification = {
            "index": 1, "version": 2, "entry_type": "Notification: Run", "name": "",
            "completed": True, "raw": "02", "raw_length": 1,
            "entry_lite_json": compact({"Notification": {"Run": {"completion_id": 1}}}).decode(),
        }
        payment["index"] = 2
        journal["rows"].extend([notification, payment])
        self.fixture.replace_json(journal_relative, journal)

        status_relative = "h0/restate-status.raw.json"
        status = json.loads((self.root / status_relative).read_text())
        status["rows"][0]["journal_size"] = 3
        self.fixture.replace_json(status_relative, status)

        cut_relative = "h0/restate-cut.json"
        cut = json.loads((self.root / cut_relative).read_text())
        cut["raw_status_sha256"] = self.fixture.artifacts[status_relative]["sha256"]
        cut["raw_journal_sha256"] = self.fixture.artifacts[journal_relative]["sha256"]
        cut["journal"] = [{
            "index": row["index"], "kind": row["entry_type"], "name": row["name"],
            "completed": row["completed"],
            "payload_sha256": sha256(bytes.fromhex(row["raw"])).hexdigest(),
        } for row in journal["rows"]]
        self.fixture.replace_json(cut_relative, cut)
        self.fixture.refresh_manifest()
        with self.assertRaisesRegex(CHECK.EvidenceError, "payment completion notification"):
            self.check()

    def test_rejects_stale_impossibility_certificate_after_rehash(self) -> None:
        events = json.loads((self.root / "h0/history-view.json").read_text())
        stale_history = {"sequence": 3, "hash": events[2]["hash"]}
        certificate_relative = "h0/certificate.json"
        certificate = json.loads((self.root / certificate_relative).read_text())
        certificate["history"] = stale_history
        certificate["digest"] = "e" * 64
        self.fixture.replace_json(certificate_relative, certificate)
        state_relative = "h0/certificate-state.json"
        state = json.loads((self.root / state_relative).read_text())
        state["history"] = stale_history
        self.fixture.replace_json(state_relative, state)
        verdict_relative = "h0/certificate-verdict.json"
        verdict = json.loads((self.root / verdict_relative).read_text())
        verdict["history_sequence"] = stale_history["sequence"]
        verdict["history_hash"] = stale_history["hash"]
        self.fixture.replace_json(verdict_relative, verdict)
        self.fixture.refresh_manifest()
        with self.assertRaisesRegex(CHECK.EvidenceError, "impossibility Certificate is stale"):
            self.check()

    def test_rejects_artifact_symlink(self) -> None:
        artifact = self.root / "h0/payment.history"
        real_file = self.root / "unlisted-empty-file"
        artifact.replace(real_file)
        artifact.symlink_to(real_file)
        with self.assertRaisesRegex(CHECK.EvidenceError, "crosses a symbolic link"):
            self.check()


if __name__ == "__main__":
    unittest.main()
