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
        self.order_id = "paired-order-preflight-002"
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
        self.h1_source_certificate_digest = "7" * 64

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
            source_certificate = self.source_certificate()
            if name == "h1":
                source_certificate["digest"] = self.h1_source_certificate_digest
            self.add_event(events, frames, "rule.activated", {
                "semantic_version": 1, "certificate": source_certificate,
            })
            self.add_event(events, frames, "operation.prepared", {
                "semantic_version": 1, "operation": self.payment_operation(),
            })
            self.add_event(events, frames, "operation.phase", {
                "semantic_version": 1, "id": self.payment_id,
                "update": {
                    "phase": "dispatched",
                    "dispatch_owner": ("a" if name == "h0" else "c") * 32,
                    "dispatch_generation": 1,
                },
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
                gateway_result = sha256(b"200\x00" + receipt).hexdigest()
                self.add_event(events, frames, "operation.phase", {
                    "semantic_version": 1, "id": self.completion_id,
                    "update": {
                        "phase": "succeeded", "result_hash": gateway_result,
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

            prepared_operations = CHECK._prepare_events(events)
            operations = {
                operation_id: CHECK._replayed_operation(
                    operation, CHECK._updates(events, operation_id),
                )
                for operation_id, operation in prepared_operations.items()
            }
            final_state = {
                "history": {"sequence": len(events), "hash": events[-1]["hash"]},
                "requirement": (requirement if name == "h1" else self.source_certificate()["requirement"]),
                "rule": (
                    {"version": 2, "requirement_hash": self.requirement_hash, "allow": ["finish"]}
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
                    "journal_size": 3,
                    "created_at": "2026-08-15T00:02:00Z", "modified_at": "2026-08-15T00:03:00Z",
                }],
            }
            input_raw = bytes.fromhex(
                "0a4d0a16782d726573746174652d696e67726573732d7061746812332f6f72646572"
                "2d776f726b666c6f772f7061697265642d6f726465722d707265666c696768742d30"
                "30322f72756e2f73656e640a180a0a757365722d6167656e74120a6375726c2f382e"
                "352e300a0d0a0661636365707412032a2f2a0a200a0c636f6e74656e742d74797065"
                "12106170706c69636174696f6e2f6a736f6e0a150a0e636f6e74656e742d6c656e67"
                "7468120332333172ea010ae7017b0a2020226964223a20227061697265642d6f726465"
                "722d707265666c696768742d303032222c0a20202272657374617572616e744964223a"
                "202272657374617572616e742d3031222c0a20202270726f6475637473223a205b0a20"
                "2020207b0a2020202020202270726f647563744964223a202270697a7a612d3031222c"
                "0a202020202020226465736372697074696f6e223a202250697a7a61222c0a20202020"
                "2020227175616e74697479223a20310a202020207d0a20205d2c0a202022746f74616c"
                "436f7374223a2034322c0a20202264656c697665727944656c6179223a20300a7d0a"
            )
            set_state_raw = bytes.fromhex("0a067374617475731a0b0a09224352454154454422")
            payment_raw = bytes.fromhex("580162077061796d656e74")
            journal_rows = [
                {
                    "index": 0, "version": 2, "entry_type": "Command: Input", "name": "",
                    "completed": False, "raw": input_raw.hex(), "raw_length": len(input_raw),
                    "entry_lite_json": compact({"Command": {"Input": {}}}).decode(),
                },
                {
                    "index": 1, "version": 2, "entry_type": "Command: SetState", "name": "",
                    "completed": False, "raw": set_state_raw.hex(), "raw_length": len(set_state_raw),
                    "entry_lite_json": compact({"Command": {"SetState": {"key": "status"}}}).decode(),
                },
                {
                    "index": 2, "version": 2, "entry_type": "Command: Run", "name": "payment",
                    "completed": False, "raw": payment_raw.hex(), "raw_length": len(payment_raw),
                    "entry_lite_json": compact({"Command": {"Run": {"completion_id": 1, "name": "payment"}}}).decode(),
                },
            ]
            journal_raw = {"rows": journal_rows}
            workflow_state_raw = {
                "rows": [{
                    "service_name": "order-workflow", "service_key": self.order_id,
                    "key": "status", "value": "224352454154454422",
                    "value_utf8": "\"CREATED\"", "value_length": 9,
                }],
            }
            status_artifact = self.write_json(prefix + "restate-status.raw.json", status_raw)
            journal_artifact = self.write_json(prefix + "restate-journal.raw.json", journal_raw)
            workflow_state_artifact = self.write_json(
                prefix + "restate-workflow-state.raw.json", workflow_state_raw,
            )
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
                "journal": projected_journal, "workflow_state": {"status": "CREATED"},
                "raw_status_sha256": status_artifact["sha256"],
                "raw_journal_sha256": journal_artifact["sha256"],
                "raw_workflow_state_sha256": workflow_state_artifact["sha256"],
            }
            cut_artifact = self.write_json(prefix + "restate-cut.json", cut)
            restate_final = {
                "schema": 1, "source_invocation_id": invocation, "source_status": "fenced",
                "order_id": self.order_id,
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
                "schema": 1, "compose_service": "order-v1", "container_id": "f" * 64,
                "remove_exit_code": 0, "inspect_exit_code": 1,
                "stderr": "Error: No such container: " + "f" * 64,
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
                "restate_workflow_state_raw": workflow_state_artifact,
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

    def set_h1_status_field(self, field: str, value: object) -> None:
        status_relative = "h1/restate-status.raw.json"
        status = json.loads((self.root / status_relative).read_text())
        status["rows"][0][field] = value
        self.fixture.replace_json(status_relative, status)
        cut_relative = "h1/restate-cut.json"
        cut = json.loads((self.root / cut_relative).read_text())
        cut["raw_status_sha256"] = self.fixture.artifacts[status_relative]["sha256"]
        self.fixture.replace_json(cut_relative, cut)
        self.fixture.refresh_manifest()

    def test_accepts_complete_joined_evidence(self) -> None:
        verdict = self.check()
        self.assertTrue(verdict["valid"])
        self.assertEqual(verdict["h0_decision"], "impossible")
        self.assertEqual(verdict["h1_decision"], "activate")
        self.assertEqual(verdict["h1_payment_commits"], 1)

    def test_accepts_distinct_valid_dispatch_boot_ids(self) -> None:
        owners: dict[str, str] = {}
        for name in ("h0", "h1"):
            events = json.loads((self.root / name / "history-view.json").read_text())
            owners[name] = next(
                event["data"]["update"]["dispatch_owner"]
                for event in events
                if event["operation"] == "operation.phase"
                and event["data"]["update"]["phase"] == "dispatched"
            )
        self.assertNotEqual(owners["h0"], owners["h1"])
        self.assertTrue(self.check()["valid"])

    def test_rejects_non_owner_history_difference(self) -> None:
        self.fixture.h1_source_certificate_digest = "e" * 64
        self.manifest = self.fixture.build()
        with self.assertRaisesRegex(
            CHECK.EvidenceError,
            "runtime History differs before authoritative payment observation",
        ):
            self.check()

    def test_restate_status_accepts_omitted_nullable_columns(self) -> None:
        status = json.loads((self.root / "h1/restate-status.raw.json").read_text())["rows"][0]
        self.assertNotIn("last_attempt_deployment_id", status)
        self.assertNotIn("retry_count", status)
        self.assertNotIn("next_retry_at", status)
        self.assertTrue(self.check()["valid"])

    def test_rejects_bad_present_optional_last_deployment(self) -> None:
        self.set_h1_status_field("last_attempt_deployment_id", "dp_wrong")
        with self.assertRaisesRegex(CHECK.EvidenceError, "optional last Restate deployment differs"):
            self.check()

    def test_rejects_bad_present_optional_retry_count(self) -> None:
        self.set_h1_status_field("retry_count", -1)
        with self.assertRaisesRegex(CHECK.EvidenceError, "optional Restate retry count is invalid"):
            self.check()

    def test_rejects_bad_present_optional_next_retry_time(self) -> None:
        self.set_h1_status_field("next_retry_at", "not-a-time")
        with self.assertRaisesRegex(CHECK.EvidenceError, "optional Restate next retry time is not a timestamp"):
            self.check()

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
        input_payload = bytearray.fromhex(journal["rows"][0]["raw"])
        input_payload[-1] ^= 1
        journal["rows"][0]["raw"] = input_payload.hex()
        self.fixture.replace_json(journal_relative, journal)
        cut_relative = "h1/restate-cut.json"
        cut = json.loads((self.root / cut_relative).read_text())
        cut["raw_journal_sha256"] = self.fixture.artifacts[journal_relative]["sha256"]
        cut["journal"][0]["payload_sha256"] = sha256(input_payload).hexdigest()
        self.fixture.replace_json(cut_relative, cut)
        self.fixture.refresh_manifest()
        with self.assertRaisesRegex(CHECK.EvidenceError, "journal or visible workflow state differs"):
            self.check()

    def test_rejects_forged_raw_workflow_state_after_all_hashes_are_rebound(self) -> None:
        state_relative = "h1/restate-workflow-state.raw.json"
        state = json.loads((self.root / state_relative).read_text())
        forged = compact("DELIVERED")
        state["rows"][0].update({
            "value": forged.hex(),
            "value_utf8": forged.decode(),
            "value_length": len(forged),
        })
        self.fixture.replace_json(state_relative, state)

        cut_relative = "h1/restate-cut.json"
        cut = json.loads((self.root / cut_relative).read_text())
        cut["workflow_state"] = {"status": "DELIVERED"}
        cut["raw_workflow_state_sha256"] = self.fixture.artifacts[state_relative]["sha256"]
        self.fixture.replace_json(cut_relative, cut)
        self.fixture.refresh_manifest()
        with self.assertRaisesRegex(CHECK.EvidenceError, "raw Restate workflow status is not CREATED"):
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
            "index": 2, "version": 2, "entry_type": "Notification: Run", "name": "",
            "completed": True, "raw": "02", "raw_length": 1,
            "entry_lite_json": compact({"Notification": {"Run": {"completion_id": 1}}}).decode(),
        }
        payment["index"] = 3
        journal["rows"].extend([notification, payment])
        self.fixture.replace_json(journal_relative, journal)

        status_relative = "h0/restate-status.raw.json"
        status = json.loads((self.root / status_relative).read_text())
        status["rows"][0]["journal_size"] = 4
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

    def test_rejects_fixture_only_empty_final_rule(self) -> None:
        relative = "h1/final-state.json"
        state = json.loads((self.root / relative).read_text())
        state["rule"]["allow"] = []
        self.fixture.replace_json(relative, state)
        self.fixture.refresh_manifest()
        with self.assertRaisesRegex(CHECK.EvidenceError, "did not finish paid and delivered Results"):
            self.check()

    def test_rejects_different_replacement_business_order(self) -> None:
        relative = "h1/restate-final.json"
        final = json.loads((self.root / relative).read_text())
        final["order_id"] = "another-order"
        self.fixture.replace_json(relative, final)
        self.fixture.refresh_manifest()
        with self.assertRaisesRegex(CHECK.EvidenceError, "H1 did not finish under fenced-v1/v2"):
            self.check()

    def test_rejects_receipt_fact_hash_as_gateway_result_hash(self) -> None:
        relative = "h1/final-state.json"
        state = json.loads((self.root / relative).read_text())
        state["operations"][self.fixture.completion_id]["result_hash"] = self.fixture.completion_result
        self.fixture.replace_json(relative, state)
        self.fixture.refresh_manifest()
        with self.assertRaisesRegex(CHECK.EvidenceError, "final Operation differs from History replay"):
            self.check()


if __name__ == "__main__":
    unittest.main()
