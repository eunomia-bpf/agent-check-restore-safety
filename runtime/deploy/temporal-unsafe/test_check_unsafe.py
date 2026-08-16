#!/usr/bin/env python3
"""Unit tests for the independent Temporal unsafe-evidence checker."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest


SCRIPT_DIR = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("temporal_unsafe_check", SCRIPT_DIR / "check-unsafe.py")
assert SPEC is not None and SPEC.loader is not None
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)

PAIR_SPEC = importlib.util.spec_from_file_location("temporal_unsafe_pair", SCRIPT_DIR / "check-unsafe-pair.py")
assert PAIR_SPEC is not None and PAIR_SPEC.loader is not None
PAIR = importlib.util.module_from_spec(PAIR_SPEC)
PAIR_SPEC.loader.exec_module(PAIR)


def payload(value: object) -> dict[str, object]:
    encoded = json.dumps(value, separators=(",", ":")).encode()
    return {
        "payloads": [{
            "metadata": {"encoding": "anNvbi9wbGFpbg=="},
            "data": CHECK.base64.b64encode(encoded).decode(),
        }],
    }


class CheckerUnitTests(unittest.TestCase):
    def test_strict_json_rejects_duplicate_keys(self) -> None:
        with self.assertRaisesRegex(CHECK.EvidenceError, "duplicate JSON key"):
            CHECK.loads(b'{"a":1,"a":2}', "duplicate")

    def test_requirement_changes_answer_after_old_charge(self) -> None:
        _, target = CHECK.expected_requirements()
        self.assertTrue(CHECK.semantic_target_feasible(target, False))
        self.assertFalse(CHECK.semantic_target_feasible(target, True))
        target["capacities"]["approval"] = 2
        self.assertTrue(CHECK.semantic_target_feasible(target, True))

    def test_frozen_build_contract_includes_independent_control_evidence(self) -> None:
        self.assertTrue({
            "FROZEN_CONTROL_BUILD_PROFILE_SHA256",
            "CONTROL_BINARY_SHA256",
            "CONTROL_SOURCE_MANIFEST_SHA256",
            "CONTROL_DOCKERFILE_SHA256",
        } <= CHECK.FROZEN_BUILD_KEYS)
        self.assertEqual(
            CHECK.FROZEN_BUILD["SAFE_CHANGE_CONTROL_IMAGE"],
            "sha256:bf609efcccd199fb149316c83f3c9c6d67218a177e81d82858d10e54e0497c98",
        )
        self.assertEqual(
            CHECK.FROZEN_BUILD["CONTROL_SOURCE_MANIFEST_SHA256"],
            "cf6f498d6d2168c0c704a621b1ac98dd7d644ee6a927fa2f21f33d02933b383e",
        )

    def test_operation_identity_and_provider_fact_are_exact(self) -> None:
        order = "temporal-unsafe-unit-order"
        self.assertEqual(
            CHECK.operation_id(order),
            "op-" + CHECK.sha256(b"operation-id-v1\0temporal-order-workflow\0" + order.encode()).hexdigest(),
        )
        payment = CHECK.expected_provider_record(order, "/v1/charge")
        completion = CHECK.expected_provider_record(order, "/v1/complete", True, "unsafe-v2")
        self.assertEqual(payment["request_hash"], CHECK.request_hash("/v1/charge", CHECK.effect_body(order)))
        self.assertEqual(
            completion["request_hash"],
            CHECK.request_hash("/v1/complete", CHECK.effect_body(order, "unsafe-v2")),
        )
        self.assertNotEqual(payment["operation_id"], completion["operation_id"])
        gateway = CHECK.gateway_request_hash(
            "http://payment:8081/v1/charge", payment["operation_id"], CHECK.effect_body(order),
        )
        self.assertEqual(len(gateway), 64)
        self.assertNotEqual(gateway, payment["request_hash"])

    def test_history_binary_hashes_raw_data_bytes(self) -> None:
        data = {"semantic_version": 1, "note": "unit"}
        raw_data = json.dumps(data, separators=(",", ":")).encode()
        digest = CHECK.history_event_hash(1, CHECK.ZERO_HASH, "unit.event", raw_data)
        frame = {
            "version": 1, "sequence": 1, "operation": "unit.event", "data": data,
            "previous_hash": CHECK.ZERO_HASH, "hash": digest,
        }
        payload = json.dumps(frame, separators=(",", ":")).encode()
        encoded = b"HST1" + struct.pack(">Q", len(payload)) + payload
        head = {
            "version": 1, "sequence": 1, "hash": digest,
            "checksum": CHECK.sha256(b"history-head-anchor-v1\0" + struct.pack(">Q", 1) + digest.encode()).hexdigest(),
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "runtime.history").write_bytes(encoded)
            (root / "runtime.head").write_bytes(json.dumps(head, separators=(",", ":")).encode() + b"\n")
            events = CHECK.binary_history(root, "runtime.history")
            CHECK.check_history_head(root, "runtime.head", events)
            self.assertEqual(events[0]["data"], data)

    def test_effect_body_is_canonical_and_closure_sensitive(self) -> None:
        order = "o-1"
        self.assertEqual(CHECK.effect_body(order), b'{"order_id":"o-1","amount_cents":4200}')
        self.assertEqual(
            CHECK.effect_body(order, "unsafe-v2"),
            b'{"order_id":"o-1","amount_cents":4200,"closure_version":"unsafe-v2"}',
        )

    def test_full_food_order_contract_is_exact(self) -> None:
        order = "o-1"
        self.assertEqual(CHECK.order_input(order), {
            "order_id": order,
            "restaurant_id": "restaurant-1",
            "products": [{
                "product_id": "pizza-1", "description": "Margherita Pizza", "quantity": 2,
            }],
            "amount_cents": 4200,
            "delivery_delay_millis": 25,
            "payment_token": order,
        })
        self.assertEqual(CHECK.activity_input("PrepareFood", order), {
            "order_id": order,
            "restaurant_id": "restaurant-1",
            "products": [{
                "product_id": "pizza-1", "description": "Margherita Pizza", "quantity": 2,
            }],
        })
        self.assertEqual(CHECK.activity_input("ScheduleDelivery", order), {
            "order_id": order,
            "delivery_id": "delivery-o-1",
            "restaurant_id": "restaurant-1",
            "region": "San Jose (CA)",
        })
        self.assertEqual(
            CHECK.signal_input("driver_selected", order),
            {"delivery_id": "delivery-o-1", "driver_id": "driver-1"},
        )
        self.assertEqual(
            CHECK.local_activity_result("PrepareFood", order),
            {
                "schema": 1, "order_id": order, "restaurant_id": "restaurant-1",
                "product_count": 2, "outcome": "accepted",
            },
        )

    def test_full_food_order_status_preserves_every_stage(self) -> None:
        waiting = CHECK.status_value("o-1", CHECK.SOURCE_BUILD, "IN_PREPARATION")
        self.assertEqual(waiting["delivery_id"], "")
        self.assertEqual(waiting["driver_id"], "")
        self.assertEqual(waiting["stages"], [
            "RESTAURANT_SELECTED", "CREATED", "PAYMENT_PENDING", "PAYMENT_COMMITTED",
            "SCHEDULED", "IN_PREPARATION",
        ])
        final = CHECK.status_value("o-1", CHECK.TARGET_BUILD, "DELIVERED")
        self.assertEqual(final["delivery_id"], "delivery-o-1")
        self.assertEqual(final["driver_id"], "driver-1")
        self.assertEqual(final["stages"], [
            "RESTAURANT_SELECTED", "CREATED", "PAYMENT_PENDING", "PAYMENT_COMMITTED",
            "SCHEDULED", "IN_PREPARATION", "SCHEDULING_DELIVERY",
            "WAITING_FOR_DRIVER", "IN_DELIVERY", "DELIVERED",
        ])
        final["stages"].pop()
        self.assertEqual(CHECK.status_value("o-1", CHECK.TARGET_BUILD, "DELIVERED")["phase"], "DELIVERED")

    def test_full_food_order_rejects_unknown_activity_and_signal(self) -> None:
        with self.assertRaisesRegex(CHECK.EvidenceError, "unexpected food-order Activity"):
            CHECK.activity_input("CollapsedFulfillment", "o-1")
        with self.assertRaisesRegex(CHECK.EvidenceError, "unexpected food-order Signal"):
            CHECK.signal_input("complete", "o-1")
        with self.assertRaisesRegex(CHECK.EvidenceError, "unsupported expected food-order phase"):
            CHECK.status_value("o-1", CHECK.SOURCE_BUILD, "WAITING_FOR_COMPLETION")

    def test_get_version_search_attribute_is_exact(self) -> None:
        encoded = CHECK.base64.b64encode(b'["unsafe-payment-capacity-v1-1"]').decode()
        event = {
            "upsertWorkflowSearchAttributesEventAttributes": {
                "searchAttributes": {
                    "indexedFields": {
                        "TemporalChangeVersion": {
                            "metadata": {
                                "encoding": "anNvbi9wbGFpbg==",
                                "type": "S2V5d29yZExpc3Q=",
                            },
                            "data": encoded,
                        },
                    },
                },
                "workflowTaskCompletedEventId": "4",
            },
        }
        CHECK.check_change_version_upsert(event, 4)
        event["upsertWorkflowSearchAttributesEventAttributes"]["workflowTaskCompletedEventId"] = "3"
        with self.assertRaisesRegex(CHECK.EvidenceError, "lineage"):
            CHECK.check_change_version_upsert(event, 4)

    def test_docker_event_accepts_actor_id_without_optional_duplicate(self) -> None:
        event = {
            "Type": "container",
            "Action": "create",
            "Actor": {"ID": "a" * 64, "Attributes": {}},
            "scope": "local",
            "time": 1,
            "timeNano": 1_000_000_000,
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "events.jsonl"
            path.write_text(json.dumps(event, separators=(",", ":")) + "\n")
            self.assertEqual(CHECK.docker_events(root, path.name)[0]["Actor"]["ID"], "a" * 64)
            event["id"] = "b" * 64
            path.write_text(json.dumps(event, separators=(",", ":")) + "\n")
            with self.assertRaisesRegex(CHECK.EvidenceError, "duplicate container ID"):
                CHECK.docker_events(root, path.name)

    def test_docker_event_stream_allows_parallel_timestamp_reordering(self) -> None:
        first = {
            "Type": "container", "Action": "create",
            "Actor": {"ID": "a" * 64, "Attributes": {}},
            "scope": "local", "time": 2, "timeNano": 2_000_000_100,
        }
        second = {
            "Type": "container", "Action": "create",
            "Actor": {"ID": "b" * 64, "Attributes": {}},
            "scope": "local", "time": 2, "timeNano": 2_000_000_000,
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "events.jsonl"
            path.write_text(
                "\n".join(json.dumps(item, separators=(",", ":")) for item in (first, second)) + "\n"
            )
            self.assertEqual(len(CHECK.docker_events(root, path.name)), 2)

    def test_pair_history_only_canonicalizes_sdk_flag_set_order(self) -> None:
        event = {
            "eventType": "EVENT_TYPE_WORKFLOW_TASK_COMPLETED",
            "workflowTaskCompletedEventAttributes": {
                "sdkMetadata": {"langUsedFlags": [3, 1]},
                "orderedValues": [2, 1],
            },
        }
        reordered = copy.deepcopy(event)
        reordered["workflowTaskCompletedEventAttributes"]["sdkMetadata"]["langUsedFlags"] = [1, 3]
        left = PAIR.canonicalize_history([copy.deepcopy(event)])
        right = PAIR.canonicalize_history([reordered])
        self.assertEqual(left, right)
        different = copy.deepcopy(event)
        different["workflowTaskCompletedEventAttributes"]["sdkMetadata"]["langUsedFlags"] = [1, 4]
        self.assertNotEqual(left, PAIR.canonicalize_history([different]))
        ordered = copy.deepcopy(event)
        ordered["workflowTaskCompletedEventAttributes"]["orderedValues"] = [1, 2]
        self.assertNotEqual(left, PAIR.canonicalize_history([ordered]))
        wrong_type = copy.deepcopy(reordered)
        wrong_type["eventType"] = "EVENT_TYPE_WORKFLOW_TASK_STARTED"
        self.assertNotEqual(left, PAIR.canonicalize_history([wrong_type]))
        duplicate = copy.deepcopy(event)
        duplicate["workflowTaskCompletedEventAttributes"]["sdkMetadata"]["langUsedFlags"] = [1, 1]
        with self.assertRaisesRegex(PAIR.CHECK.EvidenceError, "language flags"):
            PAIR.canonicalize_history([duplicate])
        for invalid in (0, 9, 0xFFFFFFFF, 0x100000000):
            out_of_domain = copy.deepcopy(event)
            out_of_domain["workflowTaskCompletedEventAttributes"]["sdkMetadata"]["langUsedFlags"] = [1, invalid]
            with self.assertRaisesRegex(PAIR.CHECK.EvidenceError, "language flags"):
                PAIR.canonicalize_history([out_of_domain])

    def test_substantive_cut_digest_ignores_only_sdk_flag_order(self) -> None:
        left = [{
            "eventType": "EVENT_TYPE_WORKFLOW_TASK_COMPLETED",
            "workflowTaskCompletedEventAttributes": {
                "sdkMetadata": {"langUsedFlags": [3, 1]}, "identity": "worker",
            },
        }]
        right = copy.deepcopy(left)
        right[0]["workflowTaskCompletedEventAttributes"]["sdkMetadata"]["langUsedFlags"] = [1, 3]
        self.assertEqual(CHECK.substantive_history_digest(left), CHECK.substantive_history_digest(right))
        right[0]["workflowTaskCompletedEventAttributes"]["identity"] = "different"
        self.assertNotEqual(CHECK.substantive_history_digest(left), CHECK.substantive_history_digest(right))

    def test_pair_semantic_trace_ignores_only_workflow_task_batching(self) -> None:
        events = [
            {
                "eventId": "1", "eventType": "EVENT_TYPE_WORKFLOW_EXECUTION_STARTED",
                "workflowExecutionStartedEventAttributes": {"input": payload(CHECK.order_input("o-1"))},
            },
            {
                "eventId": "2", "eventType": "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED",
                "activityTaskScheduledEventAttributes": {
                    "activityType": {"name": "PrepareFood"},
                    "input": payload(CHECK.activity_input("PrepareFood", "o-1")),
                    "startToCloseTimeout": "30s", "retryPolicy": {"maximumAttempts": 1},
                },
            },
            {
                "eventId": "3", "eventType": "EVENT_TYPE_ACTIVITY_TASK_COMPLETED",
                "activityTaskCompletedEventAttributes": {
                    "scheduledEventId": "2",
                    "result": payload(CHECK.local_activity_result("PrepareFood", "o-1")),
                },
            },
            {
                "eventId": "4", "eventType": "EVENT_TYPE_TIMER_STARTED",
                "timerStartedEventAttributes": {"startToFireTimeout": "0.025s"},
            },
            {
                "eventId": "5", "eventType": "EVENT_TYPE_WORKFLOW_EXECUTION_SIGNALED",
                "workflowExecutionSignaledEventAttributes": {
                    "signalName": "preparation_finished", "identity": CHECK.SIGNAL_IDENTITY, "input": {},
                },
            },
            {
                "eventId": "6", "eventType": "EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED",
                "workflowExecutionCompletedEventAttributes": {
                    "result": payload(CHECK.status_value("o-1", CHECK.TARGET_BUILD, "DELIVERED")),
                },
            },
        ]
        batched_differently = copy.deepcopy(events)
        batched_differently.insert(1, {
            "eventId": "wft", "eventType": "EVENT_TYPE_WORKFLOW_TASK_SCHEDULED",
            "workflowTaskScheduledEventAttributes": {},
        })
        self.assertEqual(
            PAIR.semantic_food_order_trace(copy.deepcopy(events)),
            PAIR.semantic_food_order_trace(batched_differently),
        )
        changed = copy.deepcopy(events)
        changed[4]["workflowExecutionSignaledEventAttributes"]["signalName"] = "delivery_finished"
        self.assertNotEqual(
            PAIR.semantic_food_order_trace(copy.deepcopy(events)),
            PAIR.semantic_food_order_trace(changed),
        )


if __name__ == "__main__":
    unittest.main()
