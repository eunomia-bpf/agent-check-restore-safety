from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from . import check_firecracker_history_start_evidence as check
from . import firecracker_history_start_demo as producer


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(item, separators=(",", ":")) + "\n" for item in records))


def _configured() -> list[dict[str, object]]:
    return [
        {"method": "PUT", "path": "/machine-config", "status": 204},
        {"method": "PUT", "path": "/boot-source", "status": 204},
        {"method": "PUT", "path": "/vsock", "status": 204},
        {"method": "PUT", "path": "/drives/payload", "status": 204},
    ]


def _state() -> dict[str, object]:
    return {
        "method": "GET",
        "path": "/",
        "status": 200,
        "response": {"state": "Not started"},
    }


def _start() -> dict[str, object]:
    return {
        "method": "PUT",
        "path": "/actions",
        "request": {"action_type": "InstanceStart"},
        "status": 204,
    }


class FirecrackerHistoryCheckerTests(unittest.TestCase):
    def test_api_shapes_distinguish_guarded_denial_and_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "api.jsonl"
            _write_jsonl(path, _configured() + [_state(), _state(), _state(), _start()])
            check._api(path, "guarded-activate")
            _write_jsonl(path, _configured() + [_state(), _state()])
            check._api(path, "guarded-denied")
            _write_jsonl(path, _configured() + [_start()])
            check._api(path, "baseline")

    def test_denied_trace_rejects_one_instance_start(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "api.jsonl"
            _write_jsonl(path, _configured() + [_state(), _start(), _state()])
            with self.assertRaisesRegex(check.EvidenceError, "denied API order"):
                check._api(path, "guarded-denied")

    def test_history_normalization_changes_only_declared_identities(self) -> None:
        def history(operation: str, request_hash: str, session: str, owner: str, host: str) -> list[dict[str, object]]:
            return [
                {
                    "operation": "rule.bindings.cutover",
                    "data": {"bindings": [{"generation": 1, "host_instance_id": host}]},
                },
                {
                    "operation": "operation.prepared",
                    "data": {
                        "operation": {
                            "id": operation,
                            "request_hash": request_hash,
                            "request_headers": {"X-Operation-ID": session},
                        }
                    },
                },
                {
                    "operation": "operation.phase",
                    "data": {"update": {"phase": "dispatched", "dispatch_owner": owner}},
                },
                {"operation": "operation.phase", "data": {"update": {"phase": "unknown"}}},
            ]

        left = history("op-left", "a" * 64, "1" * 32, "owner-left", "host-left")
        right = history("op-right", "b" * 64, "2" * 32, "owner-right", "host-right")
        self.assertEqual(check._normalized_unknown(left), check._normalized_unknown(right))
        right[0]["data"]["bindings"][0]["generation"] = 2  # type: ignore[index]
        self.assertNotEqual(check._normalized_unknown(left), check._normalized_unknown(right))

    def test_target_disables_only_reserve_execution(self) -> None:
        before, target = producer._requirements(
            "http://127.0.0.1:1/v1/reserve",
            "http://127.0.0.1:2/v1/query",
            "http://127.0.0.1:3/v1/finish",
        )
        self.assertEqual(before["results"], target["results"])
        self.assertEqual(before["capacities"], target["capacities"])
        self.assertEqual(before["kinds"]["finish"], target["kinds"]["finish"])
        self.assertEqual(
            target["kinds"]["reserve"],
            {
                "costs": {"reservation": 1},
                "produces": {"reserved": 1},
                "retry_safe": False,
                "queryable": False,
            },
        )

    def test_operation_identity_is_domain_bound(self) -> None:
        session = "1" * 32
        self.assertEqual(producer._operation_id(session), producer._operation_id(session))
        self.assertNotEqual(producer._operation_id(session), producer._operation_id("2" * 32))


if __name__ == "__main__":
    unittest.main()
