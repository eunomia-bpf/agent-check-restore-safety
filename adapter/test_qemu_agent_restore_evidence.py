from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import signal
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from adapter import check_qemu_agent_restore_evidence as check
from adapter import qemu_agent_restore_cleanup as cleanup
from adapter import qemu_agent_restore_demo as demo
from adapter import qemu_agent_restore_gate as gate


def _write(path: Path, value: object) -> None:
    path.write_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n")
    os.chmod(path, 0o600)


def _history_event(sequence: int, previous: str, operation: str, data: dict[str, object]) -> dict[str, object]:
    digest = sha256()
    digest.update(b"history-event-v1\0")
    digest.update(struct.pack(">Q", sequence))
    for part in (previous.encode(), operation.encode(), check._go_canonical(data)):
        digest.update(struct.pack(">Q", len(part)))
        digest.update(part)
    return {
        "version": 1,
        "sequence": sequence,
        "previous_hash": previous,
        "operation": operation,
        "data": data,
        "hash": digest.hexdigest(),
    }


def _write_history(path: Path, events: list[dict[str, object]]) -> None:
    with path.open("wb") as output:
        for event in events:
            payload = check._go_canonical(event)
            output.write(b"HST1" + struct.pack(">Q", len(payload)) + payload)
    os.chmod(path, 0o600)


def _qmp_records(commands: list[str], statuses: list[tuple[str, bool]]) -> list[dict[str, object]]:
    records: list[dict[str, object]] = [
        {"sequence": 1, "time_ns": 1, "direction": "server_to_client", "payload": {"QMP": {"version": {"qemu": {"major": 8, "minor": 2, "micro": 2}, "package": "Debian 1:8.2.2+ds-0ubuntu1.18"}, "capabilities": []}}}
    ]
    sequence = 1
    status_index = 0
    for index, command in enumerate(commands, start=1):
        sequence += 1
        request: dict[str, object] = {"execute": command, "id": f"command-{index}"}
        records.append({"sequence": sequence, "time_ns": sequence, "direction": "client_to_server", "payload": request})
        sequence += 1
        returned: object = {}
        if command == "query-status":
            status, running = statuses[status_index]
            status_index += 1
            returned = {"status": status, "running": running}
        records.append(
            {
                "sequence": sequence,
                "time_ns": sequence,
                "direction": "server_to_client",
                "payload": {"id": f"command-{index}", "return": returned},
            }
        )
    return records


class HistoryAndFenceMutations(unittest.TestCase):
    def test_certificate_state_raw_history_join_mutation(self) -> None:
        previous = "0" * 64
        history: list[dict[str, object]] = []
        for sequence, operation in enumerate(
            ("rule.bindings.cutover", "operation.prepared", "operation.phase", "operation.phase", "operation.phase"),
            start=1,
        ):
            event = _history_event(sequence, previous, operation, {"value": sequence})
            history.append(event)
            previous = str(event["hash"])
        recovered = check._history_point(history[4])
        certificate = {"history": recovered, "decision": "activate"}
        binding = {"sandbox_id": "s", "generation": 2}
        final = _history_event(6, previous, "rule.bindings.cutover", {"certificate": certificate, "bindings": [binding]})
        history.append(final)
        unknown = {"history": check._history_point(history[3])}
        checked = {"history": recovered}
        projection = {"history": recovered}
        current = {"history": check._history_point(final)}
        manifest = {"checked_state": checked, "certificate": certificate, "activated_history": current["history"], "binding": binding}
        check._join_history_evidence(history, unknown, checked, certificate, projection, current, manifest, "activate")
        mutated_certificate = {**certificate, "history": check._history_point(history[3])}
        with self.assertRaises(check.EvidenceError):
            check._join_history_evidence(history, unknown, checked, mutated_certificate, projection, current, manifest, "activate")

    def test_complete_normalized_history_prefix_rejects_model_mutation(self) -> None:
        def prefix(operation: str, host: str, owner: str, body: str) -> list[dict[str, object]]:
            return [
                {"operation": "rule.bindings.cutover", "data": {"bindings": [{"host_instance_id": host, "generation": 1}]}},
                {"operation": "operation.prepared", "data": {"operation": {"id": operation, "request_hash": "a" * 64, "request_headers": {"idempotency-key": operation}, "request_body": body}}},
                {"operation": "operation.phase", "data": {"id": operation, "update": {"phase": "dispatched", "dispatch_owner": owner}}},
                {"operation": "operation.phase", "data": {"id": operation, "update": {"phase": "unknown"}}},
            ]

        first = check._normalized_history_prefix(prefix("op-one", "host-one", "owner-one", "same-model"))
        second = check._normalized_history_prefix(prefix("op-two", "host-two", "owner-two", "same-model"))
        self.assertEqual(first, second)
        mutated = check._normalized_history_prefix(prefix("op-two", "host-two", "owner-two", "changed-model"))
        self.assertNotEqual(first, mutated)

    def test_history_and_anchor_reject_mutations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = _history_event(1, "0" * 64, "rule.bindings.cutover", {"semantic_version": 1})
            second = _history_event(2, str(first["hash"]), "operation.prepared", {"operation": {"id": "op"}})
            history_path = root / "control.history"
            _write_history(history_path, [first, second])
            history = check._history(history_path)
            digest = sha256(b"history-head-anchor-v1\0" + struct.pack(">Q", 2) + str(second["hash"]).encode()).hexdigest()
            anchor_path = root / "control.head"
            _write(anchor_path, {"version": 1, "sequence": 2, "hash": second["hash"], "checksum": digest})
            check._head_anchor(anchor_path, history)
            corrupted = dict(second)
            corrupted["hash"] = "f" * 64
            _write_history(history_path, [first, corrupted])
            with self.assertRaises(check.EvidenceError):
                check._history(history_path)
            _write_history(history_path, [first, second])
            anchor = json.loads(anchor_path.read_bytes())
            anchor["checksum"] = "0" * 64
            _write(anchor_path, anchor)
            with self.assertRaises(check.EvidenceError):
                check._head_anchor(anchor_path, check._history(history_path))

    def test_terminal_fence_rejects_fact_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            operation = "op-test"
            request_hash = "a" * 64
            fact = {
                "schema": 1,
                "operation_id": operation,
                "request_hash": request_hash,
                "disposition": "terminal-pre-upstream-abort",
            }
            fence = {**fact, "fact_hash": sha256(check._go_canonical(fact)).hexdigest(), "recorded_time_ns": 1}
            path = root / (sha256(operation.encode()).hexdigest() + ".json")
            _write(path, fence)
            check._terminal_fence(path, operation, request_hash)
            fence["request_hash"] = "b" * 64
            _write(path, fence)
            with self.assertRaises(check.EvidenceError):
                check._terminal_fence(path, operation, request_hash)


class RuntimeEvidenceMutations(unittest.TestCase):
    def _phase(self, root: Path, commands: list[str], statuses: list[tuple[str, bool]]) -> None:
        root.mkdir()
        _write(root / "result.json", {"qemu_reaped": True})
        _write(
            root / "qemu-command.json",
            {
                "arguments": [
                    "-S", "-loadvm", "before_agent", "-nic", "none", "restrict=on",
                    "10.0.2.100:8000", "10.0.2.100:9000", "10.0.2.100:8788",
                ]
            },
        )
        with (root / "qmp-protocol.jsonl").open("w") as output:
            for record in _qmp_records(commands, statuses):
                output.write(json.dumps(record, separators=(",", ":")) + "\n")
        os.chmod(root / "qmp-protocol.jsonl", 0o600)
        _write(root / "copy-verification.json", {"verified_before_qemu_open": True})
        (root / "guest.serial.log").write_text(
            "SAFE_CHANGE_QEMU_AGENT_MODEL_READY session=" + "a" * 32 + "\n"
            "SAFE_CHANGE_QEMU_AGENT_CLAUDE_STARTED session=" + "a" * 32 + "\n"
            "SAFE_CHANGE_QEMU_AGENT_COMPLETE session=" + "a" * 32 + "\n"
        )

    def test_qmp_order_state_and_cont_mutations(self) -> None:
        expected = ["qmp_capabilities", "query-status", "cont", "stop", "query-status", "quit"]
        with tempfile.TemporaryDirectory() as temporary:
            valid = Path(temporary) / "valid"
            self._phase(valid, expected, [("prelaunch", False), ("paused", False)])
            check._check_qemu_phase(valid, "h1-restore")
            version_mutation = Path(temporary) / "version-mutation"
            self._phase(version_mutation, expected, [("prelaunch", False), ("paused", False)])
            version_records = check._jsonl(version_mutation / "qmp-protocol.jsonl", "QMP")
            version_records[0]["payload"]["QMP"]["version"]["qemu"]["minor"] = 3
            with (version_mutation / "qmp-protocol.jsonl").open("w") as output:
                for record in version_records:
                    output.write(json.dumps(record, separators=(",", ":")) + "\n")
            with self.assertRaises(check.EvidenceError):
                check._check_qemu_phase(version_mutation, "h1-restore")
            package_mutation = Path(temporary) / "package-mutation"
            self._phase(package_mutation, expected, [("prelaunch", False), ("paused", False)])
            package_records = check._jsonl(package_mutation / "qmp-protocol.jsonl", "QMP")
            package_records[0]["payload"]["QMP"]["version"]["package"] += ".unexpected"
            with (package_mutation / "qmp-protocol.jsonl").open("w") as output:
                for record in package_records:
                    output.write(json.dumps(record, separators=(",", ":")) + "\n")
            with self.assertRaises(check.EvidenceError):
                check._check_qemu_phase(package_mutation, "h1-restore")
            mutations = [
                (["qmp_capabilities", "query-status", "stop", "cont", "query-status", "quit"], [("prelaunch", False), ("paused", False)]),
                (expected, [("running", True), ("paused", False)]),
                (["qmp_capabilities", "query-status", "stop", "query-status", "quit"], [("prelaunch", False), ("paused", False)]),
            ]
            for index, (commands, statuses) in enumerate(mutations):
                root = Path(temporary) / f"mutation-{index}"
                self._phase(root, commands, statuses)
                with self.assertRaises(check.EvidenceError):
                    check._check_qemu_phase(root, "h1-restore")

    def test_live_process_disk_and_guard_mutations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            machine = {
                "guest_forwards": {
                    "10.0.2.100:8000": "127.0.0.1:10001",
                    "10.0.2.100:9000": "127.0.0.1:10002",
                    "10.0.2.100:8788": "127.0.0.1:10003",
                }
            }
            tools = {
                "tools": {
                    "qemu-system-x86_64": {"path": "/usr/bin/qemu-system-x86_64", "sha256": check._QEMU_SYSTEM_SHA256},
                    "nc": {"path": "/usr/bin/nc.openbsd", "sha256": check._NETCAT_SHA256},
                }
            }
            arguments = check._qemu_arguments(machine, tools, True)
            process = {"pid": 999999, "start_time_ticks": 1, "executable_sha256": check._QEMU_SYSTEM_SHA256, "command_sha256": "b" * 64}
            disk = {"path": "/tmp/restore.qcow2", "device": 1, "inode": 2, "size": 3, "preopen_sha256": "c" * 64}
            _write(root / "live-vm.json", {"process": process, "disk": disk, "process_holds_disk": True})
            _write(root / "qemu-command.json", {"schema": 1, "executable": "qemu-system-x86_64", "arguments": arguments})
            command = {
                "schema": 1,
                "source": "linux-proc-cmdline-and-exe-fd",
                "pid": 999999,
                "executable": "qemu-system-x86_64",
                "executable_path": "/usr/bin/qemu-system-x86_64",
                "executable_sha256": check._QEMU_SYSTEM_SHA256,
                "command_sha256": "b" * 64,
                "arguments": arguments,
            }
            _write(root / "qemu-process-command.json", command)
            _write(root / "copy-verification.json", {"sha256": "c" * 64, "size": 3, "device": 1, "inode": 2})
            check._check_live_vm(root, "c" * 64, machine, tools)
            guard = {
                "guarded": True,
                "resume_attempted": True,
                "certificate_decision": "activate",
                "checkpoint_sha256": "c" * 64,
                "machine_config_sha256": "d" * 64,
                "process": process,
                "disk": disk,
                "endpoint": {},
                "authorization_issued": True,
                "authorization_consumed": True,
                "qmp_cont_issued": True,
                "authorize_started_time_ns": 1,
                "live_state_read_times_ns": [2, 7],
                "live_binding_read_times_ns": [3, 8],
                "endpoint_probe_times_ns": [4, 9],
                "live_states": [{}, {}],
                "live_binding_views": [[], []],
                "authorization_issued_time_ns": 5,
                "resume_started_time_ns": 6,
                "qmp_cont_requested_time_ns": 10,
            }
            _write(root / "resume-guard.json", guard)
            check._check_guard(root, "activate", process, disk)
            binding = {"sandbox_id": "s", "generation": 2}
            guard["endpoint"] = {"path": "/tmp/e.sock", "device": 7, "inode": 8, "binding": binding}
            manifest = {"endpoint_path": "/tmp/e.sock", "binding": binding}
            publication = {"path": "/tmp/e.sock", "device": 7, "inode": 8}
            check._check_endpoint_join(guard, manifest, publication)
            with self.assertRaises(check.EvidenceError):
                check._check_endpoint_join(guard, {**manifest, "binding": {**binding, "generation": 3}}, publication)
            guard["process"] = {**process, "pid": 1}
            _write(root / "resume-guard.json", guard)
            with self.assertRaises(check.EvidenceError):
                check._check_guard(root, "activate", process, disk)
            _write(root / "copy-verification.json", {"sha256": "d" * 64, "size": 3, "device": 1, "inode": 2})
            with self.assertRaises(check.EvidenceError):
                check._check_live_vm(root, "c" * 64, machine, tools)
            _write(root / "copy-verification.json", {"sha256": "c" * 64, "size": 3, "device": 1, "inode": 2})
            _write(root / "qemu-process-command.json", {**command, "arguments": [*arguments[:-1], "tcg"]})
            with self.assertRaises(check.EvidenceError):
                check._check_live_vm(root, "c" * 64, machine, tools)
            _write(root / "qemu-process-command.json", {**command, "executable_sha256": "0" * 64})
            with self.assertRaises(check.EvidenceError):
                check._check_live_vm(root, "c" * 64, machine, tools)
            runner = {
                "schema": 1,
                "kind": "vm-demo-runner",
                "pid": 999998,
                "process_group_id": 999998,
                "session_id": 999998,
                "start_time_ticks": 1,
                "command_sha256": "e" * 64,
                "executable_sha256": "f" * 64,
            }
            phase = root / "restore-vm"
            phase.mkdir()
            _write(root / "restore-vm.runner-process-command.json", runner)
            check._check_runner_process(phase, "f" * 64)
            _write(root / "restore-vm.runner-process-command.json", {**runner, "process_group_id": 1})
            with self.assertRaises(check.EvidenceError):
                check._check_runner_process(phase, "f" * 64)

    def test_pinned_host_tool_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tools = {
                "schema": 1,
                "tools": {
                    "qemu-system-x86_64": {"path": "/usr/bin/qemu-system-x86_64", "sha256": check._QEMU_SYSTEM_SHA256, "version": "QEMU emulator version 8.2.2 (Debian)"},
                    "qemu-img": {"path": "/usr/bin/qemu-img", "sha256": check._QEMU_IMG_SHA256, "version": "qemu-img version 8.2.2 (Debian)"},
                    "nc": {"path": "/usr/bin/nc.openbsd", "sha256": check._NETCAT_SHA256, "version": "OpenBSD netcat (Debian)"},
                },
            }
            _write(root / "host-tools.json", tools)
            check._host_tools(root)
            tools["tools"]["qemu-system-x86_64"]["sha256"] = "0" * 64
            _write(root / "host-tools.json", tools)
            with self.assertRaises(check.EvidenceError):
                check._host_tools(root)

    def test_executed_artifact_hash_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("check-certificate", "vm-demo", "control", "effect-proxy", "deathstar-adapter"):
                (root / name).write_bytes(name.encode())
            artifacts = {
                "qemu_runner": check._sha_file(root / "vm-demo"),
                "claude": check._CLAUDE_SHA256,
                "ubuntu_image": check._UBUNTU_SHA256,
                "control": check._sha_file(root / "control"),
                "effect_proxy": check._sha_file(root / "effect-proxy"),
                "deathstar_adapter": check._sha_file(root / "deathstar-adapter"),
            }
            check._check_artifacts(artifacts, root / "check-certificate")
            with self.assertRaises(check.EvidenceError):
                check._check_artifacts({**artifacts, "ubuntu_image": "0" * 64}, root / "check-certificate")

    def test_relay_serial_stale_mongo_and_reaping_mutations(self) -> None:
        source = [{"guest_to_host_bytes": 10, "host_to_guest_bytes": 0}]
        restore = [{"guest_to_host_bytes": 10, "host_to_guest_bytes": 20, "error": ""}]
        check._require_relay_shape(source, restore, True, "H1")
        with self.assertRaises(check.EvidenceError):
            check._require_relay_shape(source, [], True, "H1")
        session = "a" * 32
        serial = (
            f"SAFE_CHANGE_QEMU_AGENT_MODEL_READY session={session}\n"
            f"SAFE_CHANGE_QEMU_AGENT_CLAUDE_STARTED session={session}\n"
            + json.dumps({"message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "curl $SAFE_CHANGE_EGRESS_URL -H Idempotency-Key"}}]}})
            + f"\nDONE\nSAFE_CHANGE_QEMU_AGENT_COMPLETE session={session}\n"
        )
        check._serial_tool_calls(serial, session, 1, True)
        with self.assertRaises(check.EvidenceError):
            check._serial_tool_calls(serial, "b" * 32, 1, True)
        check._check_stale({"stale_status": 502, "stale_response": {"detail": "sandbox endpoint generation changed"}})
        with self.assertRaises(check.EvidenceError):
            check._check_stale({"stale_status": 200, "stale_response": {}})
        observation = {"count": 0, "facts": [], "facts_hash": check._fact_hash([]), "outcome": "failed", "terminal_fence": {"fact": 1}}
        check._check_observation(observation, 0, {"fact": 1})
        observation["facts_hash"] = "0" * 64
        with self.assertRaises(check.EvidenceError):
            check._check_observation(observation, 0, {"fact": 1})
        current_command = Path(f"/proc/{os.getpid()}/cmdline").read_bytes()
        with self.assertRaises(check.EvidenceError):
            check._require_reaped({"pid": os.getpid(), "command_sha256": sha256(current_command).hexdigest()})
        self.assertEqual(
            cleanup.residual([{"pid": os.getpid(), "command_sha256": sha256(current_command).hexdigest(), "evidence": "self"}])[0]["pid"],
            os.getpid(),
        )

    def test_deadline_cleanup_and_heartbeat_mutations(self) -> None:
        execution = {
            "overall_started_time_ns": 1_000_000_000,
            "driver_started_time_ns": 11_000_000_000,
            "driver_finished_time_ns": 91_000_000_000,
            "overall_finished_time_ns": 101_000_000_000,
            "driver_exit_status": 0,
            "timed_out": False,
            "total_duration_seconds": 100,
            "driver_duration_seconds": 80,
            "timeout_seconds": 200,
        }
        residual = {"valid": True, "residual_before": [], "terminated_pids": [], "residual_after": []}
        heartbeats = [
            {"schema": 1, "time_ns": time_ns, "stage": "run-agent-matrix"}
            for time_ns in (2_000_000_000, 32_000_000_000, 62_000_000_000, 92_000_000_000, 100_000_000_000)
        ]
        monitor = {"schema": 1, "stopped_by_launcher": True, "unexpected_failure": False, "exit_status": 0}
        check._check_execution_records(execution, residual, heartbeats, monitor)
        with self.assertRaises(check.EvidenceError):
            check._check_execution_records({**execution, "timed_out": True}, residual, heartbeats, monitor)
        with self.assertRaises(check.EvidenceError):
            check._check_execution_records(execution, {**residual, "residual_before": [{"pid": 1}]}, heartbeats, monitor)
        with self.assertRaises(check.EvidenceError):
            bad_heartbeats = [heartbeats[0], {**heartbeats[1], "time_ns": 38_000_000_000}, *heartbeats[2:]]
            check._check_execution_records(execution, residual, bad_heartbeats, monitor)
        with self.assertRaises(check.EvidenceError):
            check._check_execution_records(execution, residual, heartbeats[:-2], monitor)
        with self.assertRaises(check.EvidenceError):
            check._check_execution_records(execution, residual, heartbeats, {**monitor, "exit_status": 137})

    def test_cleanup_discovers_runner_and_qemu_records(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            phase = root / "runs" / "run-1" / "h1" / "restore-vm"
            phase.mkdir(parents=True)
            _write(phase / "qemu-process-command.json", {"pid": 999999, "command_sha256": "a" * 64})
            _write(
                phase.parent / "restore-vm.runner-process-command.json",
                {"pid": 999998, "process_group_id": 999998, "command_sha256": "b" * 64},
            )
            records = cleanup._records(root)
            self.assertEqual({record["kind"] for record in records}, {"qemu", "runner"})
            self.assertEqual(len(records), 2)

    def test_cleanup_finds_orphaned_runner_session(self) -> None:
        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import os,time; print(os.getpid(),flush=True); time.sleep(.2); child=os.fork(); os._exit(0) if child else time.sleep(30)",
            ],
            stdout=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        assert process.stdout is not None
        self.assertEqual(int(process.stdout.readline()), process.pid)
        stat_record = cleanup._process_stat(process.pid)
        self.assertIsNotNone(stat_record)
        assert stat_record is not None
        command = Path(f"/proc/{process.pid}/cmdline").read_bytes()
        record = {
            "kind": "runner",
            "pid": process.pid,
            "process_group_id": process.pid,
            "session_id": process.pid,
            "start_time_ticks": stat_record["start_time_ticks"],
            "command_sha256": sha256(command).hexdigest(),
            "evidence": "runner",
        }
        try:
            process.wait(timeout=3)
            deadline = time.monotonic() + 3
            members: list[dict[str, object]] = []
            while time.monotonic() < deadline:
                members = cleanup._session_members(record)
                if members:
                    break
                time.sleep(0.05)
            self.assertTrue(members)
            self.assertNotIn(process.pid, {member["pid"] for member in members})
            retained = cleanup.residual([record])
            self.assertEqual(len(retained), 1)
            self.assertTrue(retained[0]["members"])
        finally:
            for member in cleanup._session_members(record):
                try:
                    os.kill(member["pid"], signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.stdout.close()

    def test_runner_identity_retries_transient_empty_proc_command(self) -> None:
        class Process:
            pid = 999999

            @staticmethod
            def poll() -> None:
                return None

        with mock.patch.object(Path, "read_bytes", side_effect=[b"", b"runner\0--argument\0"]), mock.patch.object(
            time, "sleep", return_value=None
        ):
            self.assertEqual(demo._read_nonempty_process_command(Process()), b"runner\0--argument\0")

    def test_complete_model_request_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "requests.json"
            session = "a" * 32
            uuid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
            requests = []
            for ordinal in range(1, 8):
                body = {
                    "model": "claude-fixture-1",
                    "stream": True,
                    "metadata": {"user_id": json.dumps({"device_id": f"{ordinal:064x}", "account_uuid": "", "session_id": uuid}, separators=(",", ":"))},
                    "tools": [{"name": "Bash"}],
                    "messages": [{"role": "user", "content": "fixed"}],
                }
                requests.append({"ordinal": ordinal, "method": "POST", "path": "/v1/messages?beta=true", "time_ns": ordinal, "body": body})
            _write(path, requests)
            check._model_requests(path, 1, [session])
            requests[3]["body"]["messages"][0]["content"] = "mutated"
            _write(path, requests)
            with self.assertRaises(check.EvidenceError):
                check._model_requests(path, 1, [session])


class SourceManifestMutations(unittest.TestCase):
    def test_manifest_changes_when_untracked_source_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "runtime").mkdir()
            (root / "adapter").mkdir()
            (root / "runtime" / "main.go").write_text("package main\n")
            (root / "adapter" / "driver.py").write_text("x = 1\n")
            (root / "Makefile").write_text("all:\n\ttrue\n")
            subprocess.run(["git", "init", "-q", os.fspath(root)], check=True)
            first = check._current_source_manifest(root)
            (root / "adapter" / "driver.py").write_text("x = 2\n")
            second = check._current_source_manifest(root)
            self.assertNotEqual(first["root_sha256"], second["root_sha256"])

    def test_admission_gate_rejects_checker_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "runtime").mkdir()
            (root / "adapter").mkdir()
            (root / "runtime" / "main.go").write_text("package main\n")
            checker = root / "adapter" / "checker.py"
            checker.write_text("print('valid')\n")
            (root / "Makefile").write_text("all:\n\ttrue\n")
            subprocess.run(["git", "init", "-q", os.fspath(root)], check=True)
            certificate_checker = root / "certificate-checker"
            certificate_checker.write_bytes(b"checker")
            preflight = root / "preflight"
            (preflight / "runtime").mkdir(parents=True)
            _write(preflight / "result.json", {"pass": True})
            _write(preflight / "runtime" / "result.json", {"valid": True})
            retained = gate.source_manifest(root)
            _write(preflight / "source-manifest.json", retained)
            verdict = {"valid": True}
            gate_record = {
                "admitted": True,
                "source_root_sha256": retained["root_sha256"],
                "checker_sha256": gate._sha_file(checker),
                "certificate_checker_sha256": gate._sha_file(certificate_checker),
                "preflight_result_sha256": gate._sha_file(preflight / "result.json"),
                "preflight_runtime_result_sha256": gate._sha_file(preflight / "runtime" / "result.json"),
                "preflight_evidence": os.fspath(preflight.resolve()),
                "preflight_check": verdict,
                "preflight_check_sha256": sha256(gate._canonical(verdict) + b"\n").hexdigest(),
            }
            gate_path = root / "gate.json"
            _write(gate_path, gate_record)
            gate.verify_gate(root, gate_path, checker, certificate_checker)
            checker.write_text("print('changed')\n")
            with self.assertRaises(gate.GateError):
                gate.verify_gate(root, gate_path, checker, certificate_checker)


if __name__ == "__main__":
    unittest.main()
