from __future__ import annotations

import contextlib
import base64
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import adapter.check_codex_integrated_evidence as integrated_checker

from adapter.check_codex_integrated_evidence import (
    EvidenceError,
    check_evidence,
    main,
)


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/tmp/bootstrap/step-0018-20260816T125801Z"


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

    def test_qemu_executable_mutation_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            evidence = self.copy_evidence(temporary)
            path = evidence / "vm/qemu-process-command.json"
            process = json.loads(path.read_text(encoding="utf-8"))
            process["executable_sha256"] = "0" * 64
            self.write_json(path, process)
            with self.assertRaisesRegex(EvidenceError, "retained /proc QEMU"):
                check_evidence(evidence)

    def test_vm_runner_executable_mutation_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            evidence = self.copy_evidence(temporary)
            path = evidence / "vm-runner-process.json"
            process = json.loads(path.read_text(encoding="utf-8"))
            process["executable_sha256"] = "0" * 64
            self.write_json(path, process)
            with self.assertRaisesRegex(EvidenceError, "running VM runner"):
                check_evidence(evidence)

    def test_private_base_image_mutation_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            evidence = self.copy_evidence(temporary)
            path = evidence / "vm/base-image-provenance.json"
            provenance = json.loads(path.read_text(encoding="utf-8"))
            provenance["private_backing_copy"] = False
            self.write_json(path, provenance)
            with self.assertRaisesRegex(EvidenceError, "run-private"):
                check_evidence(evidence)

    def test_sigkill_exit_status_mutation_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            evidence = self.copy_evidence(temporary)
            path = evidence / "control-crash.json"
            crash = json.loads(path.read_text(encoding="utf-8"))
            crash["state"]["ExitCode"] = 143
            self.write_json(path, crash)
            with self.assertRaisesRegex(EvidenceError, "observed SIGKILL"):
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


class FirecrackerDelegationTests(unittest.TestCase):
    @staticmethod
    def _host_instance_ids() -> dict[int, str]:
        run_id = "purchase-v1-0123456789abcdef"
        return {
            generation: f"firecracker-{run_id}-g{generation}"
            for generation in (1, 2, 3)
        }

    def _provenance(self, source: bytes, guest_sha: str) -> dict[str, object]:
        checker_path = "runtime/cmd/check-firecracker-evidence/main.go"
        return {
            "revision": "trusted-revision",
            "source_files": {checker_path: hashlib.sha256(source).hexdigest()},
            "firecracker_guest_sha256": guest_sha,
        }

    def _write_vm(
        self, root: Path, guest_sha: str, *, first_reused: bool = False
    ) -> None:
        vm = root / "vm"
        vm.mkdir()
        host_instance_ids = self._host_instance_ids()
        payload = {
            "backend": "firecracker", "accelerator": "kvm",
            "firecracker_pids": [101, 202],
            "first_operation_reused": first_reused,
            "restored_operation_reused": True,
            "operation_call_id": "purchase/A-17-0123456789abcdef/audit",
            "operation_id": "vm-operation", "direct_probe_host": "172.30.0.9:8081",
            "successor_termination": "host-after-final-result",
        }
        (vm / "result.json").write_text(json.dumps(payload), encoding="utf-8")
        (vm / "assets.json").write_text(json.dumps({"guest": {"sha256": guest_sha}}), encoding="utf-8")
        request = {"call_id": payload["operation_call_id"], "kind": integrated_checker.AUDIT_KIND, "body": base64.b64encode(json.dumps({"purchase_id": "A-17-0123456789abcdef", "run_id": "purchase-v1-0123456789abcdef"}, sort_keys=True, separators=(",", ":")).encode()).decode()}
        (vm / "guest-request.json").write_text(json.dumps(request), encoding="utf-8")

        outcome = {
            "operation_id": "vm-operation",
            "phase": "succeeded",
            "status_code": 200,
            "body": base64.b64encode(b"receipt\n").decode(),
            "result_hash": "b" * 64,
            "recovered_by_query": False,
        }
        (vm / "guest-results.json").write_text(
            json.dumps(
                {
                    "schema": 1,
                    "first": {
                        "event": "RESULT",
                        "status": 200,
                        "body": {**outcome, "reused": first_reused},
                    },
                    "restored": {
                        "event": "RESULT",
                        "status": 200,
                        "body": {**outcome, "reused": True},
                    },
                }
            ),
            encoding="utf-8",
        )
        (vm / "firecracker-processes.json").write_text(
            json.dumps(
                {
                    "schema": 1,
                    "processes": [
                        {
                            "generation": generation,
                            "id": host_instance_ids[generation],
                            "pid": pid,
                            "termination": "supervisor",
                        }
                        for generation, pid in ((1, 101), (3, 202))
                    ],
                }
            ),
            encoding="utf-8",
        )
        expected_events = [
            ("run-started", 0),
            ("process-started", 1),
            ("guest-ready", 1),
            ("snapshot-created-paused", 1),
            ("relay-armed-paused", 1),
            ("vm-resumed", 1),
            ("operation-result", 1),
            ("vm-paused", 1),
            ("process-stopped", 1),
            ("process-started", 3),
            ("snapshot-loaded-paused", 3),
            ("relay-armed-paused", 3),
            ("vm-resumed", 3),
            ("operation-result", 3),
            ("process-stopped", 3),
            ("run-completed", 0),
        ]
        supervisor = []
        for index, (event, generation) in enumerate(expected_events, 1):
            record = {
                "schema": 1,
                "sequence": index,
                "event": event,
                "time_ns": index * 10,
                "elapsed_ns": index,
            }
            if generation:
                record.update(
                    {
                        "generation": generation,
                        "instance_id": host_instance_ids[generation],
                        "pid": 101 if generation == 1 else 202,
                        "start_time_ticks": 1000 + generation,
                    }
                )
                if event == "process-stopped":
                    record["details"] = {
                        "exit_confirmed": True,
                        "termination": "supervisor",
                    }
                elif event == "operation-result":
                    record["details"] = {
                        "operation_id": "vm-operation",
                        "reused": first_reused if generation == 1 else True,
                    }
            supervisor.append(record)
        (vm / "firecracker-supervisor.jsonl").write_text(
            "".join(json.dumps(record) + "\n" for record in supervisor),
            encoding="utf-8",
        )

        def api_record(
            sequence: int,
            method: str,
            path: str,
            *,
            request: object | None = None,
            response: object | None = None,
        ) -> dict[str, object]:
            record: dict[str, object] = {
                "sequence": sequence,
                "time_ns": sequence * 10,
                "method": method,
                "path": path,
                "status": 200 if method == "GET" else 204,
            }
            if request is not None:
                record["request"] = request
            if response is not None:
                record["response"] = response
            return record

        api = {
            1: [
                api_record(
                    1,
                    "GET",
                    "/",
                    response={"id": host_instance_ids[1]},
                ),
                api_record(
                    2,
                    "PUT",
                    "/vsock",
                    request={"uds_path": "<vm-evidence>/vsock-g1"},
                ),
                api_record(
                    3,
                    "PUT",
                    "/snapshot/create",
                    request={
                        "snapshot_path": "<vm-evidence>/snapshot.state",
                        "mem_file_path": "<vm-evidence>/snapshot.memory",
                    },
                ),
            ],
            3: [
                api_record(
                    1,
                    "GET",
                    "/",
                    response={"id": host_instance_ids[3]},
                ),
                api_record(
                    2,
                    "PUT",
                    "/snapshot/load",
                    request={
                        "vsock_override": {
                            "uds_path": "<vm-evidence>/vsock-g3"
                        }
                    },
                ),
            ],
        }
        for generation, records in api.items():
            (vm / f"firecracker-api-g{generation}.jsonl").write_text(
                "".join(json.dumps(record) + "\n" for record in records),
                encoding="utf-8",
            )
        for generation in (1, 3):
            identity = {
                "sandbox_device": 7,
                "sandbox_inode": 1000 + generation,
            }
            records = []
            if generation == 1 and first_reused:
                records.extend(
                    [
                        {"event": "accept", **identity},
                        {
                            "event": "bytes",
                            "sandbox_peer_pid": 500 + generation,
                            "guest_to_host_bytes": 128,
                            "host_to_guest_bytes": 0,
                            **identity,
                        },
                    ]
                )
            records.extend(
                [
                    {"event": "accept", **identity},
                    {
                        "event": "bytes",
                        "sandbox_peer_pid": 500 + generation,
                        "guest_to_host_bytes": 128,
                        "host_to_guest_bytes": 256,
                        **identity,
                    },
                ]
            )
            (vm / f"firecracker-relay-g{generation}.jsonl").write_text(
                "".join(json.dumps(record) + "\n" for record in records),
                encoding="utf-8",
            )

    @staticmethod
    def _external() -> dict[str, object]:
        return {"receipt_body": b"receipt\n", "gateway_result_hash": "b" * 64}

    @staticmethod
    def _runtime(root: Path, source: bytes) -> Path:
        runtime = root / "runtime"
        checker = runtime / "cmd/check-firecracker-evidence/main.go"
        checker.parent.mkdir(parents=True)
        checker.write_bytes(source)
        return runtime

    def test_firecracker_fetch_inputs_are_source_provenance_inputs(self) -> None:
        self.assertTrue(
            integrated_checker._selected_source_path(
                "runtime/deploy/firecracker/fetch-assets.sh"
            )
        )
        self.assertTrue(
            integrated_checker._selected_source_path(
                "runtime/deploy/firecracker/assets.lock.json"
            )
        )

    def test_firecracker_vm_summary_requires_two_distinct_pids_and_checker_success(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = b"package main\nfunc main() {}\n"
            guest_sha = "a" * 64
            self._write_vm(root, guest_sha)
            runtime = self._runtime(root, source)
            completed = subprocess.CompletedProcess([], 0, "", "")
            with mock.patch.object(integrated_checker.subprocess, "run", return_value=completed) as run:
                facts = integrated_checker._check_firecracker_vm(root, runtime, self._provenance(source, guest_sha), "purchase-v1-0123456789abcdef", "A-17-0123456789abcdef", self._host_instance_ids(), "vm-operation", self._external(), "172.30.0.9")
            self.assertEqual(facts["firecracker_pids"], [101, 202])
            self.assertEqual(
                facts["sandbox_identities"],
                {
                    1: {
                        "device": 7,
                        "inode": 1001,
                        "sandbox_peer_pid": 501,
                    },
                    3: {
                        "device": 7,
                        "inode": 1003,
                        "sandbox_peer_pid": 503,
                    },
                },
            )
            self.assertIn("./cmd/check-firecracker-evidence", run.call_args.args[0])

            payload = json.loads((root / "vm" / "result.json").read_text(encoding="utf-8"))
            payload["firecracker_pids"] = [101, 101]
            (root / "vm" / "result.json").write_text(json.dumps(payload), encoding="utf-8")
            with mock.patch.object(integrated_checker.subprocess, "run", return_value=completed):
                with self.assertRaisesRegex(EvidenceError, "Firecracker VM summary"):
                    integrated_checker._check_firecracker_vm(root, runtime, self._provenance(source, guest_sha), "purchase-v1-0123456789abcdef", "A-17-0123456789abcdef", self._host_instance_ids(), "vm-operation", self._external(), "172.30.0.9")

    def test_firecracker_first_reuse_requires_a_lost_response_and_exact_agreement(
        self,
    ) -> None:
        completed = subprocess.CompletedProcess([], 0, "", "")

        def check(root: Path, runtime: Path, source: bytes, guest_sha: str) -> None:
            with mock.patch.object(
                integrated_checker.subprocess, "run", return_value=completed
            ):
                integrated_checker._check_firecracker_vm(
                    root,
                    runtime,
                    self._provenance(source, guest_sha),
                    "purchase-v1-0123456789abcdef",
                    "A-17-0123456789abcdef",
                    self._host_instance_ids(),
                    "vm-operation",
                    self._external(),
                    "172.30.0.9",
                )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = b"package main\nfunc main() {}\n"
            guest_sha = "a" * 64
            self._write_vm(root, guest_sha, first_reused=True)
            runtime = self._runtime(root, source)
            check(root, runtime, source, guest_sha)

        for mutation in ("result", "guest", "supervisor", "relay", "restored"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = b"package main\nfunc main() {}\n"
                guest_sha = "a" * 64
                self._write_vm(root, guest_sha, first_reused=True)
                runtime = self._runtime(root, source)
                if mutation == "result":
                    path = root / "vm/result.json"
                    value = json.loads(path.read_text(encoding="utf-8"))
                    value["first_operation_reused"] = False
                    path.write_text(json.dumps(value), encoding="utf-8")
                elif mutation == "guest":
                    path = root / "vm/guest-results.json"
                    value = json.loads(path.read_text(encoding="utf-8"))
                    value["first"]["body"]["reused"] = False
                    path.write_text(json.dumps(value), encoding="utf-8")
                elif mutation == "supervisor":
                    path = root / "vm/firecracker-supervisor.jsonl"
                    records = [
                        json.loads(line)
                        for line in path.read_text(encoding="utf-8").splitlines()
                    ]
                    first = next(
                        record
                        for record in records
                        if record.get("event") == "operation-result"
                        and record.get("generation") == 1
                    )
                    first["details"]["reused"] = False
                    path.write_text(
                        "".join(json.dumps(record) + "\n" for record in records),
                        encoding="utf-8",
                    )
                elif mutation == "relay":
                    path = root / "vm/firecracker-relay-g1.jsonl"
                    records = [
                        json.loads(line)
                        for line in path.read_text(encoding="utf-8").splitlines()
                    ]
                    records[1]["host_to_guest_bytes"] = 1
                    path.write_text(
                        "".join(json.dumps(record) + "\n" for record in records),
                        encoding="utf-8",
                    )
                else:
                    path = root / "vm/guest-results.json"
                    value = json.loads(path.read_text(encoding="utf-8"))
                    value["restored"]["body"]["reused"] = False
                    path.write_text(json.dumps(value), encoding="utf-8")
                with self.assertRaises(EvidenceError):
                    check(root, runtime, source, guest_sha)

    def test_firecracker_host_identity_chain_and_canonical_paths_fail_closed(self) -> None:
        completed = subprocess.CompletedProcess([], 0, "", "")
        for mutation in ("process", "supervisor", "api-id", "api-path"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = b"package main\nfunc main() {}\n"
                guest_sha = "a" * 64
                self._write_vm(root, guest_sha)
                runtime = self._runtime(root, source)
                if mutation == "process":
                    path = root / "vm/firecracker-processes.json"
                    value = json.loads(path.read_text(encoding="utf-8"))
                    value["processes"][0]["id"] = "another-instance"
                elif mutation == "supervisor":
                    path = root / "vm/firecracker-supervisor.jsonl"
                    value = [
                        json.loads(line)
                        for line in path.read_text(encoding="utf-8").splitlines()
                    ]
                    value[1]["instance_id"] = "another-instance"
                    path.write_text(
                        "".join(json.dumps(record) + "\n" for record in value),
                        encoding="utf-8",
                    )
                    value = None
                else:
                    path = root / "vm/firecracker-api-g1.jsonl"
                    value = [
                        json.loads(line)
                        for line in path.read_text(encoding="utf-8").splitlines()
                    ]
                    if mutation == "api-id":
                        value[0]["response"]["id"] = "another-instance"
                    else:
                        value[1]["request"]["uds_path"] = "/tmp/private/vsock-g1"
                    path.write_text(
                        "".join(json.dumps(record) + "\n" for record in value),
                        encoding="utf-8",
                    )
                    value = None
                if value is not None:
                    path.write_text(json.dumps(value), encoding="utf-8")
                with mock.patch.object(
                    integrated_checker.subprocess, "run", return_value=completed
                ):
                    with self.assertRaises(EvidenceError):
                        integrated_checker._check_firecracker_vm(
                            root,
                            runtime,
                            self._provenance(source, guest_sha),
                            "purchase-v1-0123456789abcdef",
                            "A-17-0123456789abcdef",
                            self._host_instance_ids(),
                            "vm-operation",
                            self._external(),
                            "172.30.0.9",
                        )

    def test_firecracker_sandbox_peer_identity_binds_control_generation(self) -> None:
        basename = (
            "sandbox-"
            + hashlib.sha256(integrated_checker.VM_SANDBOX_ID.encode()).hexdigest()[
                :32
            ]
            + ".sock"
        )
        lifecycle = [
            {
                "event": "published",
                "generation": 1,
                "observed_time_ns": 20,
                "path_basename": basename,
                "parent_mode": "0700",
                "socket_mode": "0600",
                "owner_uid": 1000,
                "device": 7,
                "inode": 101,
                "peer_pid": 112,
                "peer_tgid": 112,
                "peer_ppid": 111,
                "peer_comm": "control",
                "peer_uid": 1000,
                "peer_gid": 1001,
                "health_status": 200,
            },
            {
                "event": "published",
                "generation": 2,
                "observed_time_ns": 50,
                "path_basename": basename,
                "parent_mode": "0700",
                "socket_mode": "0600",
                "owner_uid": 1000,
                "device": 7,
                "inode": 102,
                "peer_pid": 112,
                "peer_tgid": 112,
                "peer_ppid": 111,
                "peer_comm": "control",
                "peer_uid": 1000,
                "peer_gid": 1001,
                "health_status": 200,
            },
            {
                "event": "stale-after-control-sigkill",
                "generation": 2,
                "observed_time_ns": 80,
                "path_basename": basename,
                "socket_mode": "0600",
                "owner_uid": 1000,
                "inode": 102,
                "connect_errno": 111,
            },
            {
                "event": "absent-after-control-reopen",
                "prior_generation": 2,
                "observed_time_ns": 110,
                "path_basename": basename,
                "lstat_errno": 2,
                "connect_errno": 2,
            },
            {
                "event": "published",
                "generation": 3,
                "observed_time_ns": 130,
                "path_basename": basename,
                "parent_mode": "0700",
                "socket_mode": "0600",
                "owner_uid": 1000,
                "device": 7,
                "inode": 103,
                "peer_pid": 223,
                "peer_tgid": 223,
                "peer_ppid": 222,
                "peer_comm": "control",
                "peer_uid": 1000,
                "peer_gid": 1001,
                "health_status": 200,
            },
        ]
        docker = {
            "runtime_uid": 1000,
            "runtime_gid": 1001,
            "control_pid_before": 111,
            "control_pid_after": 222,
            "control_crash_finished_ns": 70,
            "control_restart_start_ns": 90,
        }
        timeline = {
            "rule_v1_activated_ns": 10,
            "vm_snapshot_ready_ns": 30,
            "rule_v2_activated_ns": 40,
            "order_replaced_ns": 60,
            "control_restarted_ns": 100,
            "vm_restore_loaded_ns": 120,
            "sandbox_generation_3_ns": 130,
        }
        vm = {
            "sandbox_identities": {
                1: {"device": 7, "inode": 101, "sandbox_peer_pid": 112},
                3: {"device": 7, "inode": 103, "sandbox_peer_pid": 223},
            }
        }
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "sandbox-lifecycle.json").write_text(
                json.dumps(lifecycle), encoding="utf-8"
            )
            boundary = integrated_checker._check_sandbox_lifecycle(
                directory,
                docker,
                timeline,
                vm_backend="firecracker",
                vm=vm,
            )
            self.assertTrue(boundary["credential_free"])
            vm["sandbox_identities"][3]["sandbox_peer_pid"] = 222
            with self.assertRaisesRegex(EvidenceError, "published control sockets"):
                integrated_checker._check_sandbox_lifecycle(
                    directory,
                    docker,
                    timeline,
                    vm_backend="firecracker",
                    vm=vm,
                )
            vm["sandbox_identities"][3]["sandbox_peer_pid"] = 223

            identity_mutations = (
                (0, "peer_tgid", 113, "single control process"),
                (4, "peer_ppid", 111, "Docker control containers"),
                (0, "peer_uid", 999, "observed peer identity"),
                (0, "peer_gid", 999, "observed peer identity"),
                (0, "peer_comm", "tini", "observed peer identity"),
            )
            for index, field, replacement, message in identity_mutations:
                with self.subTest(field=field):
                    original = lifecycle[index][field]
                    lifecycle[index][field] = replacement
                    (directory / "sandbox-lifecycle.json").write_text(
                        json.dumps(lifecycle), encoding="utf-8"
                    )
                    with self.assertRaisesRegex(EvidenceError, message):
                        integrated_checker._check_sandbox_lifecycle(
                            directory,
                            docker,
                            timeline,
                            vm_backend="firecracker",
                            vm=vm,
                        )
                    lifecycle[index][field] = original

    def test_firecracker_already_exited_termination_fails_closed(self) -> None:
        completed = subprocess.CompletedProcess([], 0, "", "")
        for mutation in ("result", "process", "supervisor"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = b"package main\nfunc main() {}\n"
                guest_sha = "a" * 64
                self._write_vm(root, guest_sha)
                runtime = self._runtime(root, source)
                if mutation == "result":
                    path = root / "vm/result.json"
                    value = json.loads(path.read_text(encoding="utf-8"))
                    value["successor_termination"] = (
                        "already-exited-after-final-result"
                    )
                    path.write_text(json.dumps(value), encoding="utf-8")
                elif mutation == "process":
                    path = root / "vm/firecracker-processes.json"
                    value = json.loads(path.read_text(encoding="utf-8"))
                    value["processes"][1]["termination"] = "already-exited"
                    path.write_text(json.dumps(value), encoding="utf-8")
                else:
                    path = root / "vm/firecracker-supervisor.jsonl"
                    value = [
                        json.loads(line)
                        for line in path.read_text(encoding="utf-8").splitlines()
                    ]
                    stopped = next(
                        record
                        for record in value
                        if record.get("event") == "process-stopped"
                        and record.get("generation") == 3
                    )
                    stopped["details"]["termination"] = "already-exited"
                    path.write_text(
                        "".join(json.dumps(record) + "\n" for record in value),
                        encoding="utf-8",
                    )
                with mock.patch.object(
                    integrated_checker.subprocess, "run", return_value=completed
                ):
                    with self.assertRaises(EvidenceError):
                        integrated_checker._check_firecracker_vm(
                            root,
                            runtime,
                            self._provenance(source, guest_sha),
                            "purchase-v1-0123456789abcdef",
                            "A-17-0123456789abcdef",
                            self._host_instance_ids(),
                            "vm-operation",
                            self._external(),
                            "172.30.0.9",
                        )

    def test_firecracker_trace_checker_failure_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = b"package main\nfunc main() {}\n"
            guest_sha = "a" * 64
            self._write_vm(root, guest_sha)
            runtime = self._runtime(root, source)
            failed = subprocess.CompletedProcess([], 1, "", "tampered trace")
            with mock.patch.object(integrated_checker.subprocess, "run", return_value=failed):
                with self.assertRaisesRegex(EvidenceError, "Firecracker evidence checker"):
                    integrated_checker._check_firecracker_vm(root, runtime, self._provenance(source, guest_sha), "purchase-v1-0123456789abcdef", "A-17-0123456789abcdef", self._host_instance_ids(), "vm-operation", self._external(), "172.30.0.9")

    def test_firecracker_runner_summary_binds_common_effect_facts(self) -> None:
        run_id = "run-1"
        purchase_id = "A-17-0123456789abcdef"
        operation_ids = {"vm": "vm-operation"}
        stats = {"ledger": {"deliveries": 1, "commits": 1}}
        topology = {"paths": {"vm": "firecracker-vsock->host-sandbox-socket"}}
        history = {"operation_ids": operation_ids, "history_hash": "h", "stats": stats}
        docker = {
            "effect_ips": {"ledger": "172.30.0.9"}, "topology": topology,
            "control_pid_after": 20, "control_pid_before": 10,
            "order_id_after": "order-new", "order_id_before": "order-old",
        }
        protocol = {"model": "gpt-5", "raw_records": 1}
        provenance = {
            "revision": "r", "source_tree_sha256": "t", "image_id": "sha256:image",
            "vm_backend": "firecracker", "vm_demo_sha256": "d" * 64,
            "firecracker_guest_sha256": "g" * 64,
        }
        vm = {
            "result": {
                "accelerator": "kvm",
                "first_operation_reused": False,
                "restored_operation_reused": True,
            },
            "firecracker_pids": [101, 202],
        }
        result = {
            "run_id": run_id, "purchase_id": purchase_id, "evidence_directory": "bundle",
            "history": {"active_requirement": f"purchase-v2/{run_id}", "hash": "h", "operations": operation_ids, "sequence": 16},
            "effects": stats, "effect_ips": docker["effect_ips"], "network": topology,
            "protocol": protocol,
            "faults": {"control_pid_after": 20, "control_pid_before": 10, "control_process_restarted": True, "control_restart_mode": "sigkill", "order_container_after": "order-new", "order_container_before": "order-old", "order_process_replaced": True, "whole_vm_restored": True},
            "codex": {"login_status": "Logged in using ChatGPT", "model": "gpt-5", "model_provider": "openai", "native_binary_sha256": integrated_checker.NATIVE_CODEX_SHA, "real_app_server": True, "version": "codex-cli 0.147.0"},
            "vm": {"backend": "firecracker", "runner_pid": 303, "accelerator": "kvm", "snapshot": "before_purchase", "first_reused": False, "restored_reused": True, "credential_free": True, "sandbox_generation": 3, "transport": "host-unix-socket", "firecracker_pids": [101, 202]},
            "provenance": {"revision": "r", "source_tree_sha256": "t", "runtime_image_id": "sha256:image", "vm_backend": "firecracker", "firecracker_demo_sha256": "d" * 64, "firecracker_guest_sha256": "g" * 64},
        }
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "result.json").write_text(json.dumps(result), encoding="utf-8")
            (directory / "vm-runner-process.json").write_text(json.dumps({"schema": 1, "source": "linux-proc-exe-fd", "pid": 303, "executable": "firecracker-demo", "executable_sha256": "d" * 64, "backend": "firecracker"}), encoding="utf-8")
            integrated_checker._check_runner_result(directory, run_id, purchase_id, history, docker, vm, protocol, provenance)
            vm["result"]["first_operation_reused"] = True
            result["vm"]["first_reused"] = True
            (directory / "result.json").write_text(json.dumps(result), encoding="utf-8")
            integrated_checker._check_runner_result(directory, run_id, purchase_id, history, docker, vm, protocol, provenance)
            result["vm"]["first_reused"] = False
            (directory / "result.json").write_text(json.dumps(result), encoding="utf-8")
            with self.assertRaisesRegex(EvidenceError, "VM summary"):
                integrated_checker._check_runner_result(directory, run_id, purchase_id, history, docker, vm, protocol, provenance)
            result["vm"]["first_reused"] = True
            result["effects"] = {"ledger": {"deliveries": 9, "commits": 1}}
            (directory / "result.json").write_text(json.dumps(result), encoding="utf-8")
            with self.assertRaisesRegex(EvidenceError, "effect summary"):
                integrated_checker._check_runner_result(directory, run_id, purchase_id, history, docker, vm, protocol, provenance)

    def test_firecracker_supervisor_uses_its_own_strict_envelope(self) -> None:
        expected = [
            ("run-started", 0),
            ("process-started", 1),
            ("guest-ready", 1),
            ("snapshot-created-paused", 1),
            ("relay-armed-paused", 1),
            ("vm-resumed", 1),
            ("operation-result", 1),
            ("vm-paused", 1),
            ("process-stopped", 1),
            ("process-started", 3),
            ("snapshot-loaded-paused", 3),
            ("relay-armed-paused", 3),
            ("vm-resumed", 3),
            ("operation-result", 3),
            ("process-stopped", 3),
            ("run-completed", 0),
        ]
        records = []
        for index, (event, generation) in enumerate(expected, 1):
            record = {
                "schema": 1,
                "sequence": index,
                "event": event,
                "time_ns": index * 10,
                "elapsed_ns": index,
            }
            if generation:
                record.update(
                    {
                        "generation": generation,
                        "instance_id": f"instance-{generation}",
                        "pid": 100 + generation,
                        "start_time_ticks": 1000 + generation,
                    }
                )
                if event == "process-stopped":
                    record["details"] = {
                        "exit_confirmed": True,
                        "termination": "supervisor",
                    }
            records.append(record)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "firecracker-supervisor.jsonl"
            path.write_text(
                "".join(json.dumps(record) + "\n" for record in records),
                encoding="utf-8",
            )
            parsed = integrated_checker._firecracker_supervisor_jsonl(
                path,
                {1: "instance-1", 3: "instance-3"},
            )
            self.assertEqual([record["event"] for record in parsed], [x[0] for x in expected])

            records[9]["direction"] = "server_to_client"
            path.write_text(
                "".join(json.dumps(record) + "\n" for record in records),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(EvidenceError, "sequence or clock"):
                integrated_checker._firecracker_supervisor_jsonl(path)


if __name__ == "__main__":
    unittest.main()
