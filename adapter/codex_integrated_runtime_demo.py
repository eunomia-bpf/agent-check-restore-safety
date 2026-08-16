"""Run one purchase across real Codex, containers, and a restored VM.

This explicit live-account experiment is the first vertical composition.  One
Codex dynamic-tool callback stays pending while three independently scoped
actors use one durable control History: the Codex adapter charges payment, a
replaceable order service reserves inventory, and a complete Linux guest
records an audit result.  The run changes the Rule, replaces the order process,
restarts control, and restores the whole VM without duplicating any external
commit.
"""

from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
import errno
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import selectors
import secrets
import shutil
import socket
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
from typing import Any, Mapping, Sequence, TextIO

from adapter.app_server import CodexAppServer
from adapter.codex_isolated_runtime_demo import (
    _capture_docker_inspect,
    _capture_docker_network_inspect,
    _container_networks,
    _find_vendor_bundle,
    _free_port,
    _network_ip,
    _network_probe,
    _prepare_account_home,
    _redact_protocol,
    _run,
    _wait_health,
)
from adapter.codex_runtime_demo import (
    DemoError,
    _canonical_json,
    _decode_receipt,
    _http_json,
    _login_status,
    _protocol_evidence,
    _read_private_token,
    _sha256_file,
    _write_json,
)
from adapter.docker_codex import create_docker_codex


TOOL_NAME = "complete_purchase"
PURCHASE_STEM = "A-17"
AMOUNT = 42
CODEX_DOMAIN = "codex-app-server"
ORDER_DOMAIN = "orders"
VM_DOMAIN = "full-linux-vm"
VM_SANDBOX_ID = "integrated-vm"
CHARGE_KIND = "charge-invoice"
RESERVE_V1_KIND = "reserve-v1"
RESERVE_V2_KIND = "reserve-v2"
AUDIT_KIND = "append-audit"
LIVE_TIMEOUT_SECONDS = 20 * 60.0
PROVENANCE_LABEL_NAMES = (
    "com.docker.compose.version",
    "io.safe-change.source-tree.sha256",
    "org.opencontainers.image.revision",
)


def _selected_source_path(path: str) -> bool:
    return (
        (
            path.endswith(".py")
            and ("/" not in path or path.startswith("adapter/"))
        )
        or (
            path.startswith("runtime/")
            and (
                path.endswith(".go")
                or path.endswith("/Dockerfile")
                or path.endswith("/compose.yaml")
                or path
                in {
                    "runtime/go.mod",
                    "runtime/go.sum",
                    "runtime/deploy/firecracker/assets.lock.json",
                    "runtime/deploy/firecracker/fetch-assets.sh",
                }
            )
        )
    )


def _untracked_python_import_path(path: str) -> bool:
    return path.endswith(".py") and (
        "/" not in path or path.startswith("adapter/")
    )


def _sha256_fd(descriptor: int) -> str:
    digest = sha256()
    offset = 0
    while True:
        chunk = os.pread(descriptor, 1 << 20, offset)
        if not chunk:
            return digest.hexdigest()
        digest.update(chunk)
        offset += len(chunk)


def _source_provenance_snapshot() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[1]
    listed = _run(
        ["git", "ls-files", "-z"],
        cwd=root,
    ).stdout.split("\0")
    files = sorted(path for path in listed if path and _selected_source_path(path))
    selected_files = set(files)
    required = {
        "adapter/__init__.py",
        "adapter/app_server.py",
        "adapter/codex_integrated_runtime_demo.py",
        "adapter/codex_isolated_runtime_demo.py",
        "adapter/codex_runtime_demo.py",
        "adapter/docker_codex.py",
        "adapter/mock_responses.py",
    }
    if not required <= set(files):
        raise DemoError("source provenance omitted an imported adapter implementation")
    status = _run(
        [
            "git",
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--no-renames",
        ],
        cwd=root,
    ).stdout.splitlines()
    dirty_paths: list[str] = []
    for line in status:
        path = line[3:].split(" -> ")[-1]
        if path in selected_files or (
            line.startswith("?? ") and _untracked_python_import_path(path)
        ):
            dirty_paths.append(path)
    if dirty_paths:
        raise DemoError(
            "integrated evidence requires committed producer source: "
            + ", ".join(sorted(dirty_paths))
        )
    hashes = {path: _sha256_file(root / path) for path in files}
    digest = sha256()
    for path, value in hashes.items():
        digest.update(path.encode() + b"\0" + value.encode() + b"\0")
    revision = _run(["git", "rev-parse", "HEAD"], cwd=root).stdout.strip()
    provenance = {
        "schema": 1,
        "revision": revision,
        "selected_source_clean": True,
        "python_isolated": bool(sys.flags.isolated),
        "python_no_user_site": bool(sys.flags.no_user_site),
        "source_tree_sha256": digest.hexdigest(),
        "files": hashes,
    }
    return provenance


def _record_source_provenance(output_dir: Path) -> dict[str, Any]:
    provenance = _source_provenance_snapshot()
    _write_json(output_dir / "source-provenance.json", provenance)
    return provenance


def _verify_source_provenance(expected: Mapping[str, Any]) -> None:
    if _source_provenance_snapshot() != expected:
        raise DemoError("producer source changed after provenance capture")


def _materialize_runtime_source(
    private_dir: Path,
    provenance: Mapping[str, Any],
) -> Path:
    repository = Path(__file__).resolve().parents[1]
    archive = private_dir / "runtime-source.tar"
    checkout = private_dir / "source-checkout"
    checkout.mkdir(mode=0o700)
    completed = subprocess.run(
        [
            "git",
            "archive",
            "--format=tar",
            f"--output={archive}",
            str(provenance["revision"]),
            "runtime",
        ],
        cwd=repository,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if completed.returncode != 0:
        raise DemoError(f"cannot materialize committed runtime source: {completed.stdout}")
    with tarfile.open(archive, mode="r:") as bundle:
        for member in bundle.getmembers():
            parts = Path(member.name).parts
            if (
                not parts
                or parts[0] != "runtime"
                or ".." in parts
                or member.issym()
                or member.islnk()
                or not (member.isdir() or member.isfile())
            ):
                raise DemoError("committed runtime archive contains an unsafe member")
        bundle.extractall(checkout, filter="data")
    archive.unlink()
    runtime_dir = checkout / "runtime"
    for path, expected_hash in provenance["files"].items():
        if not str(path).startswith("runtime/"):
            continue
        materialized = checkout / str(path)
        if not materialized.is_file() or _sha256_file(materialized) != expected_hash:
            raise DemoError(f"committed runtime snapshot differs at {path}")
    return runtime_dir


def _runtime_image_bindings(
    image: str,
    containers: Sequence[str],
    *,
    project: str,
    revision: str,
    source_tree_sha256: str,
) -> dict[str, Any]:
    inspection = json.loads(_run(["docker", "image", "inspect", image]).stdout)
    if not isinstance(inspection, list) or len(inspection) != 1:
        raise DemoError("runtime image inspection is malformed")
    image_document = inspection[0]
    if not isinstance(image_document, Mapping):
        raise DemoError("runtime image inspection is not an object")
    image_id = image_document.get("Id")
    if not isinstance(image_id, str) or not re.fullmatch(
        r"sha256:[0-9a-f]{64}", image_id
    ):
        raise DemoError("runtime image has no immutable local image identity")
    config = image_document.get("Config")
    labels = config.get("Labels") if isinstance(config, Mapping) else None
    fixed_labels = {
        "com.docker.compose.project": project,
        "com.docker.compose.service": "control",
        "io.safe-change.source-tree.sha256": source_tree_sha256,
        "org.opencontainers.image.revision": revision,
    }
    compose_version = (
        labels.get("com.docker.compose.version")
        if isinstance(labels, Mapping)
        else None
    )
    expected_labels = {
        **fixed_labels,
        "com.docker.compose.version": compose_version,
    }
    if (
        labels != expected_labels
        or not isinstance(compose_version, str)
        or re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?", compose_version)
        is None
    ):
        raise DemoError("runtime image is not bound to the producer source")
    bindings: dict[str, str] = {}
    for container in containers:
        observed = _run(
            ["docker", "inspect", "-f", "{{.Image}}", container]
        ).stdout.strip()
        if observed != image_id:
            raise DemoError(f"container {container} did not use the built runtime image")
        bindings[container] = observed
    return {
        "schema": 1,
        "tag": image,
        "image_id": image_id,
        "labels": expected_labels,
        "container_images": bindings,
    }


def _project_name() -> str:
    return f"safe-change-integrated-{os.getpid()}-{secrets.token_hex(4)}"


def _operation_id(domain: str, call_id: str) -> str:
    digest = sha256()
    digest.update(b"operation-id-v1\x00")
    digest.update(domain.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(call_id.encode("utf-8"))
    return "op-" + digest.hexdigest()


def _sandbox_operation_id(domain: str, sandbox_id: str, call_id: str) -> str:
    digest = sha256()
    digest.update(b"sandbox-operation-id-v2\x00")
    digest.update(domain.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(sandbox_id.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(call_id.encode("utf-8"))
    return "op-" + digest.hexdigest()


def _write_private(path: Path, contents: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(contents)
        stream.flush()
        os.fsync(stream.fileno())


def _new_token(path: Path) -> str:
    token = secrets.token_hex(32)
    _write_private(path, token + "\n")
    return token


def _write_release(path: Path, version: str, kind: str, target: str) -> None:
    temporary = path.with_suffix(".json.next")
    _write_json(
        temporary,
        {"version": version, "kind": kind, "target": target},
    )
    temporary.chmod(0o600)
    temporary.replace(path)


@dataclass
class IntegratedDeployment:
    compose_file: Path
    state_dir: Path
    output_dir: Path
    project: str
    image: str
    source_revision: str
    source_tree_sha256: str
    control_port: int
    order_port: int

    def __post_init__(self) -> None:
        environment = os.environ.copy()
        environment.update(
            {
                "COMPOSE_PROJECT_NAME": self.project,
                "CONTROL_PORT": str(self.control_port),
                "ORDER_PORT": str(self.order_port),
                "DEMO_STATE_DIR": str(self.state_dir),
                "RUNTIME_IMAGE": self.image,
                "SOURCE_REVISION": self.source_revision,
                "SOURCE_TREE_SHA256": self.source_tree_sha256,
                "DEMO_UID": str(os.getuid()),
                "DEMO_GID": str(os.getgid()),
            }
        )
        self.environment = environment
        self.command = ["docker", "compose", "-f", str(self.compose_file)]
        self.started = False

    @property
    def agent_network(self) -> str:
        return self.project + "_agent"

    @property
    def application_network(self) -> str:
        return self.project + "_application"

    @property
    def effects_network(self) -> str:
        return self.project + "_effects"

    @property
    def control_url(self) -> str:
        return f"http://127.0.0.1:{self.control_port}"

    @property
    def order_url(self) -> str:
        return f"http://127.0.0.1:{self.order_port}"

    def compose(
        self, *arguments: str, timeout: float = 120.0, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        return _run(
            [*self.command, *arguments],
            env=self.environment,
            timeout=timeout,
            check=check,
        )

    def start(self) -> None:
        self.compose("build", "control", timeout=240.0)
        self.started = True
        self.compose(
            "up",
            "-d",
            "--wait",
            "--wait-timeout",
            "60",
            timeout=180.0,
        )
        _wait_health(self.control_url + "/healthz")
        _wait_health(self.order_url + "/healthz")

    def service_container(self, service: str) -> str:
        identifier = self.compose("ps", "-q", service).stdout.strip()
        if not identifier:
            raise DemoError(f"Compose service has no container: {service}")
        return identifier

    def restart_control(self, sandbox_socket: Path) -> tuple[int, int, dict[str, Any]]:
        container = self.service_container("control")
        before = int(
            _run(["docker", "inspect", "-f", "{{.State.Pid}}", container])
            .stdout.strip()
        )
        command = ["docker", "kill", "--signal", "KILL", container]
        started = time.time_ns()
        killed = _run(command, timeout=30.0, check=False)
        finished = time.time_ns()
        if killed.returncode != 0:
            raise DemoError(f"control SIGKILL failed: {killed.stdout}")
        inspected = json.loads(
            _run(["docker", "inspect", container], timeout=30.0).stdout
        )
        if not isinstance(inspected, list) or len(inspected) != 1:
            raise DemoError("control crash inspection is malformed")
        state = inspected[0].get("State")
        if (
            not isinstance(state, Mapping)
            or state.get("Running") is not False
            or state.get("Pid") != 0
            or state.get("ExitCode") != 137
            or state.get("OOMKilled") is not False
        ):
            raise DemoError(f"control did not retain a SIGKILL state: {state}")
        _write_json(
            self.output_dir / "control-crash.json",
            {
                "command": command,
                "container_id": container,
                "pid_before": before,
                "started_time_ns": started,
                "finished_time_ns": finished,
                "returncode": killed.returncode,
                "state": {
                    "ExitCode": state.get("ExitCode"),
                    "FinishedAt": state.get("FinishedAt"),
                    "OOMKilled": state.get("OOMKilled"),
                    "Pid": state.get("Pid"),
                    "Running": state.get("Running"),
                },
            },
        )
        stale_socket = _observe_stale_sandbox_socket(
            sandbox_socket,
            generation=2,
        )
        self.compose("start", "control", timeout=60.0)
        _wait_health(self.control_url + "/healthz")
        after = int(
            _run(["docker", "inspect", "-f", "{{.State.Pid}}", container])
            .stdout.strip()
        )
        if before <= 0 or after <= 0 or before == after:
            raise DemoError("control container did not replace its process")
        return before, after, stale_socket

    def replace_order(self) -> tuple[str, str]:
        before = self.service_container("order")
        self.compose(
            "up",
            "-d",
            "--force-recreate",
            "--no-deps",
            "order",
            timeout=90.0,
        )
        _wait_health(self.order_url + "/healthz")
        after = self.service_container("order")
        if before == after:
            raise DemoError("order release did not replace the container")
        return before, after

    def effect_stats(self, service: str) -> dict[str, Any]:
        control = self.service_container("control")
        completed = _run(
            [
                "docker",
                "exec",
                control,
                "wget",
                "-qO-",
                f"http://{service}:8081/v1/stats",
            ],
            timeout=15.0,
        )
        try:
            value = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise DemoError(f"{service} stats are not JSON") from error
        if not isinstance(value, dict):
            raise DemoError(f"{service} stats are not an object")
        return value

    def close(self) -> None:
        if not self.started:
            return
        logs = self.compose("logs", "--no-color", timeout=30.0, check=False)
        (self.output_dir / "logs/services.log").write_text(
            logs.stdout, encoding="utf-8"
        )
        down = self.compose(
            "down", "--remove-orphans", timeout=90.0, check=False
        )
        (self.output_dir / "logs/compose-down.log").write_text(
            down.stdout.rstrip() + "\n", encoding="utf-8"
        )
        image = _run(
            ["docker", "image", "rm", self.image],
            timeout=60.0,
            check=False,
        )
        (self.output_dir / "logs/image-cleanup.log").write_text(
            image.stdout.rstrip() + "\n", encoding="utf-8"
        )
        _write_json(
            self.output_dir / "teardown.json",
            {
                "compose_down_returncode": down.returncode,
                "image_remove_returncode": image.returncode,
            },
        )
        self.started = False
        if down.returncode != 0 or image.returncode != 0:
            raise DemoError("integrated deployment cleanup failed")


class VMProcess:
    def __init__(
        self,
        *,
        binary: Path,
        backend: str,
        accel: str,
        guest_binary: Path | None,
        host_instance_ids: Mapping[int, str] | None,
        sandbox_socket: Path,
        request_path: Path,
        direct_probe: str,
        evidence_dir: Path,
        stderr_path: Path,
        expected_binary_sha256: str,
        process_evidence_path: Path,
    ) -> None:
        command = _vm_runner_command(
            binary=binary,
            backend=backend,
            accel=accel,
            guest_binary=guest_binary,
            host_instance_ids=host_instance_ids,
            sandbox_socket=sandbox_socket,
            request_path=request_path,
            direct_probe=direct_probe,
            evidence_dir=evidence_dir,
        )
        self._stderr = stderr_path.open("w", encoding="utf-8")
        expected_descriptor = os.open(binary, os.O_RDONLY | os.O_CLOEXEC)
        try:
            expected_stat = os.fstat(expected_descriptor)
            if _sha256_fd(expected_descriptor) != expected_binary_sha256:
                raise DemoError("built VM runner changed before launch")
            self.process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self._stderr,
                text=True,
                bufsize=1,
            )
            try:
                process_descriptor = os.open(
                    f"/proc/{self.process.pid}/exe",
                    os.O_RDONLY | os.O_CLOEXEC,
                )
                try:
                    process_stat = os.fstat(process_descriptor)
                    if (
                        process_stat.st_dev != expected_stat.st_dev
                        or process_stat.st_ino != expected_stat.st_ino
                    ):
                        raise DemoError(
                            "running VM runner inode differs from the built binary"
                        )
                    process_sha256 = _sha256_fd(process_descriptor)
                finally:
                    os.close(process_descriptor)
                if process_sha256 != expected_binary_sha256:
                    raise DemoError(
                        "running VM runner bytes differ from its build digest"
                    )
                process_evidence: dict[str, Any] = {
                    "schema": 1,
                    "source": "linux-proc-exe-fd",
                    "pid": self.process.pid,
                    "executable": (
                        "vm-demo" if backend == "qemu" else "firecracker-demo"
                    ),
                    "executable_sha256": process_sha256,
                }
                if backend == "firecracker":
                    process_evidence["backend"] = "firecracker"
                _write_json(process_evidence_path, process_evidence)
            except Exception:
                self.process.kill()
                self.process.wait(timeout=5.0)
                raise
        except Exception:
            self._stderr.close()
            raise
        finally:
            os.close(expected_descriptor)
        if self.process.stdin is None or self.process.stdout is None:
            raise DemoError("VM runner pipes were not created")
        self._selector = selectors.DefaultSelector()
        self._selector.register(self.process.stdout, selectors.EVENT_READ)
        self.events: list[dict[str, Any]] = []

    @property
    def pid(self) -> int:
        return self.process.pid

    def wait_event(self, expected: str, timeout: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise DemoError(f"timed out waiting for VM event {expected!r}")
            ready = self._selector.select(remaining)
            if not ready:
                raise DemoError(f"timed out waiting for VM event {expected!r}")
            line = self.process.stdout.readline()
            if line == "":
                raise DemoError(
                    f"VM runner exited {self.process.poll()} before {expected!r}"
                )
            try:
                event = json.loads(line)
            except json.JSONDecodeError as error:
                raise DemoError(f"VM runner emitted non-JSON: {line!r}") from error
            if not isinstance(event, dict) or not isinstance(event.get("event"), str):
                raise DemoError(f"VM runner emitted malformed event: {event!r}")
            event["observed_time_ns"] = time.time_ns()
            self.events.append(event)
            if event["event"] != expected:
                raise DemoError(
                    f"VM runner emitted {event['event']!r}, expected {expected!r}"
                )
            return event

    def send(self, command: str) -> None:
        if command not in {"start", "pause", "restore", "resume"}:
            raise ValueError(f"unsupported VM command {command!r}")
        self.process.stdin.write(command + "\n")
        self.process.stdin.flush()

    def wait(self, timeout: float = 120.0) -> None:
        try:
            returncode = self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as error:
            raise DemoError("VM runner did not exit") from error
        if returncode != 0:
            raise DemoError(f"VM runner exited with status {returncode}")

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5.0)
        self._selector.close()
        self._stderr.close()

    def __enter__(self) -> VMProcess:
        return self

    def __exit__(self, *unused: object) -> None:
        self.close()


def _vm_runner_command(
    *,
    binary: Path,
    backend: str,
    accel: str,
    guest_binary: Path | None,
    host_instance_ids: Mapping[int, str] | None,
    sandbox_socket: Path,
    request_path: Path,
    direct_probe: str,
    evidence_dir: Path,
) -> list[str]:
    if backend not in {"qemu", "firecracker"}:
        raise ValueError(f"unsupported VM backend {backend!r}")
    if backend == "firecracker" and guest_binary is None:
        raise ValueError("Firecracker VM runner requires a static guest binary")
    if backend == "firecracker":
        if (
            host_instance_ids is None
            or set(host_instance_ids) != {1, 3}
            or any(
                not isinstance(host_instance_ids[generation], str)
                or not host_instance_ids[generation]
                for generation in (1, 3)
            )
            or host_instance_ids[1] == host_instance_ids[3]
        ):
            raise ValueError(
                "Firecracker VM runner requires distinct generation 1 and 3 "
                "HostInstanceIDs"
            )
    elif host_instance_ids is not None:
        raise ValueError("QEMU VM runner does not accept Firecracker HostInstanceIDs")
    command = [
        str(binary),
        "-accel",
        accel,
        "-timeout",
        "18m",
        "-external-sandbox-socket",
        str(sandbox_socket),
        "-external-request",
        str(request_path),
        "-external-direct-probe",
        direct_probe,
        "-external-evidence-dir",
        str(evidence_dir),
    ]
    if backend == "firecracker":
        # firecracker-demo verifies its pinned Firecracker/kernel defaults; the
        # runtime-specific input supplied by this orchestrator is the static
        # guest to package into its initramfs.
        assert host_instance_ids is not None
        command.extend(
            [
                "-guest",
                str(guest_binary),
                "-host-instance-id-g1",
                host_instance_ids[1],
                "-host-instance-id-g3",
                host_instance_ids[3],
            ]
        )
    return command


def _vm_result_summary(
    *,
    backend: str,
    runner_pid: int,
    accel: str,
    completed: Mapping[str, Any],
) -> dict[str, Any]:
    if backend not in {"qemu", "firecracker"}:
        raise ValueError(f"unsupported VM backend {backend!r}")
    first_reused = completed.get("first_operation_reused")
    restored_reused = completed.get("restored_operation_reused")
    if type(first_reused) is not bool or restored_reused is not True:
        raise DemoError("VM runner did not report exact Operation reuse outcomes")
    summary: dict[str, Any] = {
        "runner_pid": runner_pid,
        "accelerator": accel,
        "snapshot": "before_purchase",
        "first_reused": first_reused,
        "restored_reused": restored_reused,
        "credential_free": True,
        "sandbox_generation": 3,
        "transport": "host-unix-socket",
    }
    if backend == "qemu":
        if first_reused is not False:
            raise DemoError("QEMU first Operation unexpectedly reused an earlier outcome")
        qemu_pid = completed.get("qemu_pid")
        if not isinstance(qemu_pid, int) or qemu_pid <= 0:
            raise DemoError("QEMU runner did not report its process PID")
        summary["qemu_pid"] = qemu_pid
        return summary
    firecracker_pids = completed.get("firecracker_pids")
    if (
        not isinstance(firecracker_pids, list)
        or len(firecracker_pids) != 2
        or any(not isinstance(pid, int) or pid <= 0 for pid in firecracker_pids)
        or firecracker_pids[0] == firecracker_pids[1]
    ):
        raise DemoError("Firecracker runner did not report two distinct VMM PIDs")
    summary["backend"] = "firecracker"
    summary["firecracker_pids"] = firecracker_pids
    return summary


def _kind(
    *, target: str, resource: str, result: str
) -> dict[str, Any]:
    return {
        "costs": {resource: 1},
        "produces": {result: 1},
        "retry_safe": True,
        "queryable": False,
        "target": target,
        "method": "POST",
        "response_classifier": "operation-receipt-v1",
    }


def _requirements(run_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    payment = "http://payment:8081/v1/charge"
    inventory_v1 = "http://inventory:8081/v1/charge"
    inventory_v2 = "http://inventory:8081/v2/charge"
    ledger = "http://ledger:8081/v1/charge"
    common = {
        "results": {"paid": 1, "reserved": 1, "audited": 1},
        "capacities": {
            "payment-slot": 1,
            "inventory-slot": 1,
            "audit-slot": 1,
        },
    }
    version_one = {
        "id": f"purchase-v1/{run_id}",
        **common,
        "kinds": {
            CHARGE_KIND: _kind(
                target=payment, resource="payment-slot", result="paid"
            ),
            RESERVE_V1_KIND: _kind(
                target=inventory_v1,
                resource="inventory-slot",
                result="reserved",
            ),
            AUDIT_KIND: _kind(
                target=ledger, resource="audit-slot", result="audited"
            ),
        },
    }
    version_two = {
        "id": f"purchase-v2/{run_id}",
        **common,
        "kinds": {
            CHARGE_KIND: _kind(
                target=payment, resource="payment-slot", result="paid"
            ),
            RESERVE_V2_KIND: _kind(
                target=inventory_v2,
                resource="inventory-slot",
                result="reserved",
            ),
            AUDIT_KIND: _kind(
                target=ledger, resource="audit-slot", result="audited"
            ),
        },
    }
    return version_one, version_two


def _compile_and_activate(
    *,
    deployment: IntegratedDeployment,
    runtime_dir: Path,
    output_dir: Path,
    admin_token: str,
    requirement: Mapping[str, Any],
    label: str,
    bindings: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    _write_json(output_dir / f"requirement-{label}.json", requirement)
    certificate = _http_json(
        deployment.control_url + "/v1/compile",
        method="POST",
        token=admin_token,
        payload=requirement,
    ).body
    if certificate.get("decision") != "activate" or not isinstance(
        certificate.get("rule"), dict
    ):
        raise DemoError(f"{label} did not compile to an activating Rule")
    _write_json(output_dir / f"certificate-{label}.json", certificate)
    state = _http_json(
        deployment.control_url + "/v1/certificate-state",
        method="POST",
        token=admin_token,
        payload=certificate,
    ).body
    _write_json(output_dir / f"certificate-state-{label}.json", state)
    checker = _run(
        [
            "go",
            "run",
            "./cmd/check-certificate",
            "-state",
            str(output_dir / f"certificate-state-{label}.json"),
            "-certificate",
            str(output_dir / f"certificate-{label}.json"),
        ],
        cwd=runtime_dir,
        timeout=120.0,
    )
    try:
        verdict = json.loads(checker.stdout)
    except json.JSONDecodeError as error:
        raise DemoError(f"{label} checker verdict is not JSON") from error
    if not isinstance(verdict, dict) or verdict.get("valid") is not True:
        raise DemoError(f"{label} Certificate was independently rejected")
    _write_json(output_dir / f"checker-verdict-{label}.json", verdict)
    if bindings is None:
        active = _http_json(
            deployment.control_url + "/v1/activate",
            method="POST",
            token=admin_token,
            payload=certificate,
        ).body
    else:
        cutover = _http_json(
            deployment.control_url + "/v1/cutover",
            method="POST",
            token=admin_token,
            payload={"certificate": certificate, "bindings": list(bindings)},
        ).body
        active = cutover.get("state")
        if not isinstance(active, dict) or cutover.get("bindings") != list(bindings):
            raise DemoError(f"{label} did not publish its sandbox binding")
        _write_json(output_dir / f"cutover-{label}.json", cutover)
    _write_json(output_dir / f"active-state-{label}.json", active)
    return certificate, active


def _vm_binding(
    project: str, generation: int, backend: str = "qemu"
) -> dict[str, Any]:
    if backend not in {"qemu", "firecracker"}:
        raise ValueError(f"unsupported VM backend {backend!r}")
    return {
        "sandbox_id": VM_SANDBOX_ID,
        "generation": generation,
        "host_instance_id": f"{backend}-{project}-g{generation}",
        "domain": VM_DOMAIN,
        "allowed_kinds": [AUDIT_KIND],
    }


def _sandbox_socket_path(state_dir: Path) -> Path:
    digest = sha256(VM_SANDBOX_ID.encode()).hexdigest()[:32]
    return state_dir / "sandbox-endpoints" / f"sandbox-{digest}.sock"


def _wait_sandbox_socket(
    path: Path,
    *,
    generation: int,
    record_device: bool = False,
    timeout: float = 10.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_error: OSError | None = None
    while time.monotonic() < deadline:
        try:
            socket_info = path.lstat()
            parent_info = path.parent.lstat()
            mode = socket_info.st_mode
            if not stat.S_ISSOCK(mode) or stat.S_IMODE(mode) != 0o600:
                raise DemoError(f"sandbox endpoint has unsafe mode {oct(mode)}")
            if (
                not stat.S_ISDIR(parent_info.st_mode)
                or stat.S_IMODE(parent_info.st_mode) != 0o700
                or socket_info.st_uid != os.geteuid()
                or parent_info.st_uid != os.geteuid()
            ):
                raise DemoError("sandbox endpoint has an unsafe owner or parent")
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(2.0)
                connection.connect(str(path))
                connection.sendall(
                    b"GET /healthz HTTP/1.1\r\nHost: sandbox\r\nConnection: close\r\n\r\n"
                )
                response = connection.recv(4096)
            if response.startswith(b"HTTP/1.1 200"):
                evidence = {
                    "event": "published",
                    "generation": generation,
                    "observed_time_ns": time.time_ns(),
                    "path_basename": path.name,
                    "parent_mode": "0700",
                    "socket_mode": "0600",
                    "owner_uid": os.geteuid(),
                    "inode": socket_info.st_ino,
                    "health_status": 200,
                }
                if record_device:
                    evidence["device"] = socket_info.st_dev
                return evidence
            raise DemoError(f"sandbox health response is {response[:80]!r}")
        except OSError as error:
            last_error = error
            time.sleep(0.05)
    raise DemoError(f"sandbox endpoint did not become healthy: {last_error}")


def _observe_stale_sandbox_socket(
    path: Path,
    *,
    generation: int,
) -> dict[str, Any]:
    socket_info = path.lstat()
    if (
        not stat.S_ISSOCK(socket_info.st_mode)
        or stat.S_IMODE(socket_info.st_mode) != 0o600
        or socket_info.st_uid != os.geteuid()
    ):
        raise DemoError("SIGKILL did not leave the expected private socket inode")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(2.0)
        try:
            connection.connect(str(path))
        except OSError as error:
            connect_errno = error.errno
        else:
            raise DemoError("stale sandbox endpoint accepted a connection after SIGKILL")
    if connect_errno != errno.ECONNREFUSED:
        raise DemoError(
            f"stale sandbox endpoint connect errno is {connect_errno}, want ECONNREFUSED"
        )
    return {
        "event": "stale-after-control-sigkill",
        "generation": generation,
        "observed_time_ns": time.time_ns(),
        "path_basename": path.name,
        "socket_mode": "0600",
        "owner_uid": os.geteuid(),
        "inode": socket_info.st_ino,
        "connect_errno": connect_errno,
    }


def _observe_sandbox_absence(path: Path, *, prior_generation: int) -> dict[str, Any]:
    try:
        path.lstat()
    except FileNotFoundError as error:
        lstat_errno = error.errno
    else:
        raise DemoError("reopened control retained the stale sandbox inode")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(2.0)
        try:
            connection.connect(str(path))
        except OSError as error:
            connect_errno = error.errno
        else:
            raise DemoError("reopened control automatically attached a sandbox endpoint")
    if lstat_errno != errno.ENOENT or connect_errno != errno.ENOENT:
        raise DemoError("reopened sandbox path did not fail with ENOENT")
    return {
        "event": "absent-after-control-reopen",
        "prior_generation": prior_generation,
        "observed_time_ns": time.time_ns(),
        "path_basename": path.name,
        "lstat_errno": lstat_errno,
        "connect_errno": connect_errno,
    }


def _expect_unknown(value: Mapping[str, Any], label: str) -> None:
    outcome = value.get("outcome")
    if not isinstance(outcome, Mapping) or outcome.get("phase") != "unknown":
        raise DemoError(f"{label} did not become unknown: {value}")


def _expect_succeeded(
    value: Mapping[str, Any], label: str, *, reused: bool
) -> dict[str, Any]:
    if value.get("phase") != "succeeded" or value.get("reused") is not reused:
        raise DemoError(f"{label} did not succeed with reused={reused}: {value}")
    return _decode_receipt(value)


def _submit_order(
    deployment: IntegratedDeployment,
    purchase_id: str,
    *,
    expected: frozenset[int],
) -> dict[str, Any]:
    result = _http_json(
        deployment.order_url + "/v1/orders",
        method="POST",
        payload={"order_id": purchase_id, "amount": AMOUNT},
        expected=expected,
        timeout=45.0,
    ).body
    if not isinstance(result, dict):
        raise DemoError("order response is not an object")
    return result


def _validate_networks(
    deployment: IntegratedDeployment,
    codex_container: str,
    *,
    vm_backend: str = "qemu",
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, str]]:
    services = ["ingress", "order", "control", "payment", "inventory", "ledger"]
    containers = {
        service: deployment.service_container(service) for service in services
    }
    networks = {
        "codex": _container_networks(codex_container),
        **{
            service: _container_networks(container)
            for service, container in containers.items()
        },
    }
    expected = {
        "codex": [deployment.agent_network],
        "ingress": [deployment.agent_network, deployment.application_network],
        "order": [deployment.application_network],
        "control": [deployment.application_network, deployment.effects_network],
        "payment": [deployment.effects_network],
        "inventory": [deployment.effects_network],
        "ledger": [deployment.effects_network],
    }
    normalized = {name: sorted(value) for name, value in networks.items()}
    if normalized != {name: sorted(value) for name, value in expected.items()}:
        raise DemoError(f"integrated Docker network cut differs: {normalized}")

    effect_ips = {
        service: _network_ip(containers[service], deployment.effects_network)
        for service in ("payment", "inventory", "ledger")
    }
    observations: list[dict[str, Any]] = []
    positive = (
        (codex_container, "http://ingress:8080/healthz", "codex-ingress"),
        (containers["order"], "http://control:8787/healthz", "order-control"),
    )
    for container, url, label in positive:
        probe = _network_probe(container, url, label)
        if probe["returncode"] != 0:
            raise DemoError(f"positive integrated network probe failed: {label}")
        observations.append(probe)
    for actor_name, actor in (("codex", codex_container), ("order", containers["order"])):
        for effect, address in effect_ips.items():
            for suffix, url in (
                ("name", f"http://{effect}:8081/v1/stats"),
                ("ip", f"http://{address}:8081/v1/stats"),
            ):
                probe = _network_probe(
                    actor,
                    url,
                    f"{actor_name}-{effect}-{suffix}",
                )
                if probe["returncode"] == 0:
                    raise DemoError(
                        f"{actor_name} reached {effect} directly by {suffix}"
                    )
                observations.append(probe)
    if vm_backend == "qemu":
        vm_path = "qemu-guestfwd->host-sandbox-socket"
    elif vm_backend == "firecracker":
        vm_path = "firecracker-vsock->host-sandbox-socket"
    else:
        raise ValueError(f"unsupported VM backend {vm_backend!r}")
    topology = {
        "networks": normalized,
        "agent_to_effect_shared_networks": [],
        "order_to_effect_shared_networks": [],
        "fixed_actor_paths": {
            "codex": "ingress->control",
            "order": "control",
            "vm": vm_path,
        },
    }
    return topology, observations, effect_ips


_FIRECRACKER_API_PATH_KEYS = frozenset(
    {
        "backend_path",
        "initrd_path",
        "kernel_image_path",
        "mem_file_path",
        "snapshot_path",
        "uds_path",
    }
)


def _canonicalize_firecracker_api_value(
    value: Any,
    *,
    source_root: Path,
    private_root: Path,
    field: str | None = None,
) -> Any:
    if isinstance(value, dict):
        return {
            key: _canonicalize_firecracker_api_value(
                nested,
                source_root=source_root,
                private_root=private_root,
                field=key,
            )
            for key, nested in value.items()
        }
    if isinstance(value, list):
        return [
            _canonicalize_firecracker_api_value(
                nested,
                source_root=source_root,
                private_root=private_root,
                field=field,
            )
            for nested in value
        ]
    if field not in _FIRECRACKER_API_PATH_KEYS or not isinstance(value, str):
        return value
    for root, label in (
        (source_root.resolve(), "<vm-evidence>"),
        (private_root.resolve(), "<private>"),
    ):
        prefix = os.fspath(root)
        if value == prefix:
            return label
        if value.startswith(prefix + os.sep):
            return label + value[len(prefix) :]
    return value


def _copy_firecracker_api_trace(
    source_path: Path,
    destination_path: Path,
    *,
    source_root: Path,
    private_root: Path,
) -> None:
    try:
        raw = source_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise DemoError(f"cannot read Firecracker API trace {source_path.name}") from error
    if not raw or not raw.endswith("\n"):
        raise DemoError(f"Firecracker API trace {source_path.name} is incomplete")
    canonical_records: list[str] = []
    for index, line in enumerate(raw.splitlines(), 1):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise DemoError(
                f"Firecracker API trace {source_path.name} line {index} is invalid"
            ) from error
        if not isinstance(record, dict):
            raise DemoError(
                f"Firecracker API trace {source_path.name} line {index} is not an object"
            )
        canonical = _canonicalize_firecracker_api_value(
            record,
            source_root=source_root,
            private_root=private_root,
        )
        canonical_records.append(
            json.dumps(canonical, sort_keys=True, separators=(",", ":")) + "\n"
        )
    retained = "".join(canonical_records)
    if os.fspath(private_root.resolve()) in retained:
        raise DemoError(
            f"Firecracker API trace {source_path.name} retained a private path"
        )
    _write_private(destination_path, retained)


def _copy_vm_evidence(
    source: Path,
    destination: Path,
    private_root: Path,
    *,
    backend: str = "qemu",
) -> None:
    destination.mkdir(mode=0o700)
    if backend == "qemu":
        names = (
            "result.json", "base-image-provenance.json", "guest.serial.log",
            "guest-request.json", "guest-script.sh", "host-tools.json",
            "snapshots.txt", "qemu-command.json", "qemu-process-command.json",
            "qmp-protocol.jsonl",
        )
        log_name = "qemu.log"
    elif backend == "firecracker":
        names = (
            "result.json", "assets.json", "guest-request.json",
            "guest-results.json", "snapshot-provenance.json",
            "firecracker-processes.json", "firecracker-supervisor.jsonl",
            "timeline.json", "firecracker-api-g1.jsonl", "firecracker-api-g3.jsonl",
            "firecracker-gate-g1.jsonl", "firecracker-gate-g3.jsonl",
            "firecracker-relay-g1.jsonl", "firecracker-relay-g3.jsonl",
            "snapshot.state", "snapshot.memory", "guest-initramfs.cpio",
        )
        log_name = "firecracker-g1.log"
    else:
        raise ValueError(f"unsupported VM backend {backend!r}")
    firecracker_api_names = {
        "firecracker-api-g1.jsonl",
        "firecracker-api-g3.jsonl",
    }
    for name in names:
        if backend == "firecracker" and name in firecracker_api_names:
            _copy_firecracker_api_trace(
                source / name,
                destination / name,
                source_root=source,
                private_root=private_root,
            )
        else:
            shutil.copy2(source / name, destination / name)
    log_names = (
        (log_name,)
        if backend == "qemu"
        else ("firecracker-g1.log", "firecracker-g3.log")
    )
    for name in log_names:
        log = (source / name).read_text(encoding="utf-8", errors="replace")
        log = log.replace(str(Path.home()), "<redacted-home>")
        log = log.replace(str(private_root), "<redacted-private>")
        (destination / name).write_text(log, encoding="utf-8")


def _configure_private_state(state_dir: Path) -> dict[str, str]:
    for name in (
        "payment",
        "inventory",
        "ledger",
        "control",
        "anchor",
        "credentials",
        "control-config",
        "order-config",
        "sandbox-endpoints",
    ):
        (state_dir / name).mkdir(mode=0o700)
    tokens = {
        "admin": _new_token(state_dir / "credentials/admin-token"),
        "codex": _new_token(state_dir / "credentials/codex-token"),
        "order": _new_token(state_dir / "credentials/order-token"),
    }
    _write_json(
        state_dir / "control-config/adapters.json",
        {
            "schema": 1,
            "adapters": [
                {
                    "domain": CODEX_DOMAIN,
                    "token_file": "/credentials/codex-token",
                    "kinds": [CHARGE_KIND],
                },
                {
                    "domain": ORDER_DOMAIN,
                    "token_file": "/credentials/order-token",
                    "kinds": [RESERVE_V1_KIND, RESERVE_V2_KIND],
                },
            ],
        },
    )
    (state_dir / "control-config/adapters.json").chmod(0o600)
    return tokens


def run_demo(
    *,
    output_dir: Path,
    codex_auth: Path,
    vendor_bundle: Path | None,
    model: str | None,
    vm_accel: str,
    vm_backend: str = "qemu",
) -> dict[str, Any]:
    if not sys.flags.isolated or not sys.flags.no_user_site:
        raise DemoError("integrated evidence must run under isolated Python")
    if vm_accel not in {"tcg", "kvm"}:
        raise DemoError("VM accelerator must be tcg or kvm")
    if vm_backend not in {"qemu", "firecracker"}:
        raise DemoError("VM backend must be qemu or firecracker")
    if vm_backend == "firecracker" and vm_accel != "kvm":
        raise DemoError("Firecracker requires --vm-accel kvm")
    if vm_accel == "kvm":
        try:
            kvm_descriptor = os.open(
                "/dev/kvm", os.O_RDWR | os.O_CLOEXEC
            )
        except OSError as error:
            raise DemoError(
                "KVM acceleration requires read/write access to /dev/kvm; "
                "run this target in the kvm group"
            ) from error
        try:
            if not stat.S_ISCHR(os.fstat(kvm_descriptor).st_mode):
                raise DemoError("/dev/kvm is not a character device")
        finally:
            os.close(kvm_descriptor)
    repository = Path(__file__).resolve().parents[1]
    output_dir = output_dir.resolve()
    required_commands = ("docker",)
    if vm_backend == "qemu":
        required_commands += ("qemu-system-x86_64", "qemu-img", "nc")
    for command in required_commands:
        if shutil.which(command) is None:
            raise DemoError(f"required integrated-system command is absent: {command}")
    vendor = _find_vendor_bundle(vendor_bundle)
    native_codex = vendor / "bin/codex"
    source_auth = codex_auth.resolve(strict=True)
    source_auth_digest = _sha256_file(source_auth)
    source_auth_stat = source_auth.stat()

    output_dir.mkdir(parents=True, exist_ok=False)
    output_dir.chmod(0o700)
    (output_dir / "logs").mkdir(mode=0o700)
    source_provenance = _record_source_provenance(output_dir)
    raw_protocol = output_dir / "app-server.jsonl"
    result: dict[str, Any] | None = None

    with tempfile.TemporaryDirectory(
        prefix="scr-int-"
    ) as private:
        private_dir = Path(private)
        private_dir.chmod(0o700)
        runtime_dir = _materialize_runtime_source(
            private_dir,
            source_provenance,
        )
        compose_file = runtime_dir / "deploy/integrated/compose.yaml"
        state_dir = private_dir / "state"
        workspace = private_dir / "agent-workspace"
        account_home = private_dir / "codex-home"
        wrapper_dir = private_dir / "wrapper"
        vm_work = private_dir / "vm-work"
        vm_stderr = private_dir / "vm-runner.stderr"
        binary_dir = private_dir / "bin"
        for directory in (
            state_dir,
            workspace,
            wrapper_dir,
            vm_work,
            binary_dir,
        ):
            directory.mkdir(mode=0o700)
        tokens = _configure_private_state(state_dir)
        _prepare_account_home(source_auth, account_home)

        project = _project_name()
        purchase_id = f"{PURCHASE_STEM}-{project.rsplit('-', 1)[-1]}"
        image = "safe-change-runtime:" + project
        requirement_v1, requirement_v2 = _requirements(project)
        vm_bindings = {
            generation: _vm_binding(project, generation, vm_backend)
            for generation in (1, 2, 3)
        }
        _write_release(
            state_dir / "order-config/order.json",
            "v1",
            RESERVE_V1_KIND,
            "http://inventory:8081/v1/charge",
        )
        vm_binary = binary_dir / (
            "vm-demo" if vm_backend == "qemu" else "firecracker-demo"
        )
        vm_guest_binary: Path | None = None
        if vm_backend == "qemu":
            _run(
                ["go", "build", "-trimpath", "-o", str(vm_binary), "./cmd/vm-demo"],
                cwd=runtime_dir,
                timeout=120.0,
            )
        else:
            vm_guest_binary = binary_dir / "firecracker-guest"
            static_environment = os.environ.copy()
            static_environment["CGO_ENABLED"] = "0"
            _run(
                [
                    "go",
                    "build",
                    "-trimpath",
                    "-o",
                    str(vm_guest_binary),
                    "./cmd/firecracker-guest",
                ],
                cwd=runtime_dir,
                env=static_environment,
                timeout=120.0,
            )
            _run(
                ["go", "build", "-trimpath", "-o", str(vm_binary), "./cmd/firecracker-demo"],
                cwd=runtime_dir,
                timeout=120.0,
            )
        _verify_source_provenance(source_provenance)
        vm_binary_sha256 = _sha256_file(vm_binary)
        build_provenance: dict[str, Any] = {
                "schema": 1,
                "build_input": "git-archive",
                "revision": source_provenance["revision"],
                "source_tree_sha256": source_provenance["source_tree_sha256"],
        }
        if vm_backend == "qemu":
            build_provenance["vm_demo_sha256"] = vm_binary_sha256
        else:
            build_provenance["vm_backend"] = "firecracker"
            build_provenance["firecracker_demo_sha256"] = vm_binary_sha256
            build_provenance["firecracker_guest_sha256"] = _sha256_file(vm_guest_binary)
        _write_json(output_dir / "runtime-build-provenance.json", build_provenance)
        control_port = _free_port()
        order_port = _free_port()
        while order_port == control_port:
            order_port = _free_port()
        deployment = IntegratedDeployment(
            compose_file=compose_file,
            state_dir=state_dir,
            output_dir=output_dir,
            project=project,
            image=image,
            source_revision=source_provenance["revision"],
            source_tree_sha256=source_provenance["source_tree_sha256"],
            control_port=control_port,
            order_port=order_port,
        )

        timeline: dict[str, int] = {"run_start_ns": time.time_ns()}
        sandbox_lifecycle: list[dict[str, Any]] = []
        try:
            deployment.start()
            _verify_source_provenance(source_provenance)
            _compile_and_activate(
                deployment=deployment,
                runtime_dir=runtime_dir,
                output_dir=output_dir,
                admin_token=tokens["admin"],
                requirement=requirement_v1,
                label="v1",
                bindings=[vm_bindings[1]],
            )
            timeline["rule_v1_activated_ns"] = time.time_ns()
            sandbox_socket = _sandbox_socket_path(state_dir)
            sandbox_lifecycle.append(
                _wait_sandbox_socket(
                    sandbox_socket,
                    generation=1,
                    record_device=vm_backend == "firecracker",
                )
            )

            vm_call_id = f"purchase/{purchase_id}/audit"
            vm_body = _canonical_json(
                {"purchase_id": purchase_id, "run_id": project}
            )
            vm_request_path = private_dir / "vm-request.json"
            _write_json(
                vm_request_path,
                {
                    "call_id": vm_call_id,
                    "kind": AUDIT_KIND,
                    "body": base64.b64encode(vm_body).decode("ascii"),
                },
            )
            vm_request_path.chmod(0o600)
            ledger_container = deployment.service_container("ledger")
            ledger_ip = _network_ip(ledger_container, deployment.effects_network)
            with VMProcess(
                binary=vm_binary,
                backend=vm_backend,
                accel=vm_accel,
                guest_binary=vm_guest_binary,
                host_instance_ids=(
                    {
                        generation: str(
                            vm_bindings[generation]["host_instance_id"]
                        )
                        for generation in (1, 3)
                    }
                    if vm_backend == "firecracker"
                    else None
                ),
                sandbox_socket=sandbox_socket,
                request_path=vm_request_path,
                direct_probe=f"http://{ledger_ip}:8081/v1/stats",
                evidence_dir=vm_work,
                stderr_path=vm_stderr,
                expected_binary_sha256=vm_binary_sha256,
                process_evidence_path=output_dir / "vm-runner-process.json",
            ) as vm:
                snapshot_event = vm.wait_event("snapshot-ready", 7 * 60.0)
                timeline["vm_snapshot_ready_ns"] = snapshot_event["observed_time_ns"]

                codex_call_id = f"purchase/{purchase_id}/payment"
                codex_operation_id = _operation_id(CODEX_DOMAIN, codex_call_id)
                order_call_id = f"order/{purchase_id}/payment"
                order_operation_id = _operation_id(ORDER_DOMAIN, order_call_id)
                vm_operation_id = _sandbox_operation_id(
                    VM_DOMAIN,
                    VM_SANDBOX_ID,
                    vm_call_id,
                )
                payment_body = _canonical_json(
                    {
                        "amount": AMOUNT,
                        "purchase_id": purchase_id,
                        "run_id": project,
                    }
                )
                payment_execute = {
                    "call_id": codex_call_id,
                    "kind": CHARGE_KIND,
                    "method": "POST",
                    "url": "http://payment:8081/v1/charge",
                    "headers": {"Content-Type": "application/json"},
                    "body": base64.b64encode(payment_body).decode("ascii"),
                }

                with create_docker_codex(
                    vendor_bundle=vendor,
                    workspace=workspace,
                    codex_home=account_home,
                    network=deployment.agent_network,
                    runtime_image=image,
                    temp_parent=wrapper_dir,
                ) as docker_codex:
                    login_status = _login_status(str(docker_codex.executable))
                    version = _run(
                        [str(docker_codex.executable), "--version"], timeout=30.0
                    ).stdout.strip()
                    client = CodexAppServer(
                        model_base_url=None,
                        use_logged_in_account=True,
                        model=model,
                        workspace=workspace,
                        raw_jsonl_path=raw_protocol,
                        codex_binary=str(docker_codex.executable),
                        rpc_timeout=30.0,
                        turn_timeout=LIVE_TIMEOUT_SECONDS,
                    )
                    with client:
                        thread = client.create_account_thread(
                            tool_name=TOOL_NAME,
                            tool_description=(
                                "Complete the one approved purchase through the "
                                "protected runtime. Call exactly once."
                            ),
                            input_schema={
                                "type": "object",
                                "required": ["purchase_id"],
                                "properties": {
                                    "purchase_id": {
                                        "type": "string",
                                        "enum": [purchase_id],
                                    }
                                },
                                "additionalProperties": False,
                            },
                            developer_instructions=(
                                "Only complete_purchase is available. Do not inspect "
                                "files, run commands, or request another tool."
                            ),
                        )
                        thread_id = str(thread["id"])
                        pending = client.start_protected_turn(
                            thread_id,
                            (
                                f"Experiment {project}: call {TOOL_NAME} exactly once "
                                f"with purchase_id {purchase_id}. After it returns, "
                                "reply exactly DONE."
                            ),
                            expected_tool=TOOL_NAME,
                            expected_arguments={"purchase_id": purchase_id},
                            timeout=LIVE_TIMEOUT_SECONDS,
                        )
                        timeline["codex_tool_call_ns"] = time.time_ns()
                        ephemeral_auth = account_home / "auth.json"
                        if not ephemeral_auth.is_file():
                            raise DemoError(
                                "temporary Codex authentication vanished before tool call"
                            )
                        ephemeral_auth.unlink()
                        if ephemeral_auth.exists():
                            raise DemoError(
                                "temporary Codex authentication remained after tool call"
                            )

                        initial_containers = [
                            docker_codex.container_name,
                            *(
                                deployment.service_container(service)
                                for service in (
                                    "ingress",
                                    "order",
                                    "control",
                                    "payment",
                                    "inventory",
                                    "ledger",
                                )
                            ),
                        ]
                        _capture_docker_inspect(
                            initial_containers,
                            output_dir / "docker-inspect.json",
                            extra_label_names=PROVENANCE_LABEL_NAMES,
                            include_image_identity=True,
                        )
                        image_provenance = _runtime_image_bindings(
                            image,
                            initial_containers,
                            project=project,
                            revision=source_provenance["revision"],
                            source_tree_sha256=source_provenance[
                                "source_tree_sha256"
                            ],
                        )
                        _write_json(
                            output_dir / "image-provenance.json",
                            image_provenance,
                        )
                        _capture_docker_network_inspect(
                            [
                                deployment.agent_network,
                                deployment.application_network,
                                deployment.effects_network,
                            ],
                            output_dir / "docker-network-inspect.json",
                        )
                        topology, probes, effect_ips = _validate_networks(
                            deployment,
                            docker_codex.container_name,
                            vm_backend=vm_backend,
                        )
                        _write_json(output_dir / "network-topology.json", topology)
                        _write_json(output_dir / "network-probes.json", probes)
                        timeline["network_checks_finished_ns"] = time.time_ns()

                        first_payment = _http_json(
                            deployment.control_url + "/v1/execute",
                            method="POST",
                            token=tokens["codex"],
                            payload=payment_execute,
                            expected=frozenset({409}),
                            timeout=45.0,
                        ).body
                        _expect_unknown(first_payment, "Codex payment")
                        _write_json(
                            output_dir / "codex-payment-unknown.json",
                            first_payment,
                        )
                        timeline["codex_payment_unknown_ns"] = time.time_ns()

                        first_order = _submit_order(
                            deployment,
                            purchase_id,
                            expected=frozenset({409}),
                        )
                        if (
                            first_order.get("release_version") != "v1"
                            or first_order.get("requested_kind") != RESERVE_V1_KIND
                        ):
                            raise DemoError(
                                f"old order process did not request v1: {first_order}"
                            )
                        runtime_unknown = first_order.get("runtime")
                        if not isinstance(runtime_unknown, Mapping):
                            raise DemoError("old order response omitted runtime outcome")
                        _expect_unknown(runtime_unknown, "inventory reservation")
                        _write_json(
                            output_dir / "inventory-unknown.json", first_order
                        )
                        timeline["inventory_unknown_ns"] = time.time_ns()

                        vm.send("start")
                        vm_first = vm.wait_event("first-succeeded", 150.0)
                        timeline["vm_first_succeeded_ns"] = vm_first[
                            "observed_time_ns"
                        ]
                        vm.send("pause")
                        vm_paused = vm.wait_event("paused-after-first", 30.0)
                        timeline["vm_paused_ns"] = vm_paused["observed_time_ns"]

                        _compile_and_activate(
                            deployment=deployment,
                            runtime_dir=runtime_dir,
                            output_dir=output_dir,
                            admin_token=tokens["admin"],
                            requirement=requirement_v2,
                            label="v2",
                            bindings=[vm_bindings[2]],
                        )
                        timeline["rule_v2_activated_ns"] = time.time_ns()
                        sandbox_lifecycle.append(
                            _wait_sandbox_socket(
                                sandbox_socket,
                                generation=2,
                                record_device=vm_backend == "firecracker",
                            )
                        )
                        _write_release(
                            state_dir / "order-config/order.json",
                            "v2",
                            RESERVE_V2_KIND,
                            "http://inventory:8081/v2/charge",
                        )
                        old_order_container, new_order_container = (
                            deployment.replace_order()
                        )
                        replacement_image = _runtime_image_bindings(
                            image,
                            [new_order_container],
                            project=project,
                            revision=source_provenance["revision"],
                            source_tree_sha256=source_provenance[
                                "source_tree_sha256"
                            ],
                        )
                        if replacement_image["image_id"] != image_provenance["image_id"]:
                            raise DemoError("replacement order used another runtime image")
                        image_provenance["container_images"].update(
                            replacement_image["container_images"]
                        )
                        _write_json(
                            output_dir / "image-provenance.json",
                            image_provenance,
                        )
                        timeline["order_replaced_ns"] = time.time_ns()
                        health = _http_json(deployment.order_url + "/healthz").body
                        if health.get("version") != "v2" or health.get("kind") != RESERVE_V2_KIND:
                            raise DemoError(f"new order release is not v2: {health}")

                        control_container = deployment.service_container("control")
                        control_pid_before, control_pid_after, stale_socket = (
                            deployment.restart_control(sandbox_socket)
                        )
                        sandbox_lifecycle.append(stale_socket)
                        timeline["control_restarted_ns"] = time.time_ns()
                        sandbox_lifecycle.append(
                            _observe_sandbox_absence(
                                sandbox_socket,
                                prior_generation=2,
                            )
                        )
                        _capture_docker_inspect(
                            [control_container],
                            output_dir / "control-after-restart-inspect.json",
                            extra_label_names=PROVENANCE_LABEL_NAMES,
                            include_image_identity=True,
                        )
                        _capture_docker_inspect(
                            [new_order_container],
                            output_dir / "order-after-replacement-inspect.json",
                            extra_label_names=PROVENANCE_LABEL_NAMES,
                            include_image_identity=True,
                        )

                        vm.send("restore")
                        vm_loaded = vm.wait_event("restore-loaded-paused", 60.0)
                        timeline["vm_restore_loaded_ns"] = vm_loaded[
                            "observed_time_ns"
                        ]
                        _compile_and_activate(
                            deployment=deployment,
                            runtime_dir=runtime_dir,
                            output_dir=output_dir,
                            admin_token=tokens["admin"],
                            requirement=requirement_v2,
                            label="v2-reopen",
                            bindings=[vm_bindings[3]],
                        )
                        generation_3 = _wait_sandbox_socket(
                            sandbox_socket,
                            generation=3,
                            record_device=vm_backend == "firecracker",
                        )
                        sandbox_lifecycle.append(generation_3)
                        timeline["sandbox_generation_3_ns"] = generation_3[
                            "observed_time_ns"
                        ]
                        vm.send("resume")
                        vm_completed = vm.wait_event("completed", 180.0)
                        vm.wait(timeout=30.0)
                        timeline["vm_restore_completed_ns"] = vm_completed[
                            "observed_time_ns"
                        ]
                        _write_json(output_dir / "vm-events.json", vm.events)
                        _copy_vm_evidence(
                            vm_work,
                            output_dir / "vm",
                            private_dir,
                            backend=vm_backend,
                        )

                        recovered_payment = _http_json(
                            deployment.control_url + "/v1/execute",
                            method="POST",
                            token=tokens["codex"],
                            payload=payment_execute,
                            timeout=45.0,
                        ).body
                        payment_receipt = _expect_succeeded(
                            recovered_payment,
                            "recovered Codex payment",
                            reused=False,
                        )
                        _write_json(
                            output_dir / "codex-payment-recovered.json",
                            recovered_payment,
                        )

                        recovered_order = _submit_order(
                            deployment,
                            purchase_id,
                            expected=frozenset({200}),
                        )
                        order_runtime = recovered_order.get("runtime")
                        if (
                            recovered_order.get("release_version") != "v2"
                            or recovered_order.get("requested_kind")
                            != RESERVE_V2_KIND
                            or recovered_order.get("requested_target")
                            != "http://inventory:8081/v2/charge"
                            or not isinstance(order_runtime, Mapping)
                        ):
                            raise DemoError(
                                f"new order process did not request v2: {recovered_order}"
                            )
                        inventory_receipt = _expect_succeeded(
                            order_runtime,
                            "recovered inventory reservation",
                            reused=False,
                        )
                        _write_json(
                            output_dir / "inventory-recovered.json",
                            recovered_order,
                        )

                        reused_payment = _http_json(
                            deployment.control_url + "/v1/execute",
                            method="POST",
                            token=tokens["codex"],
                            payload=payment_execute,
                        ).body
                        _expect_succeeded(
                            reused_payment,
                            "settled Codex payment",
                            reused=True,
                        )
                        reused_order = _submit_order(
                            deployment,
                            purchase_id,
                            expected=frozenset({200}),
                        )
                        reused_order_runtime = reused_order.get("runtime")
                        if not isinstance(reused_order_runtime, Mapping):
                            raise DemoError("settled order retry omitted runtime result")
                        _expect_succeeded(
                            reused_order_runtime,
                            "settled inventory reservation",
                            reused=True,
                        )
                        _write_json(
                            output_dir / "settled-retries.json",
                            {
                                "codex": reused_payment,
                                "order": reused_order,
                            },
                        )

                        stats = {
                            service: deployment.effect_stats(service)
                            for service in ("payment", "inventory", "ledger")
                        }
                        expected_stats = {
                            "payment": (2, 1, 2, 0),
                            "inventory": (2, 1, 2, 0),
                            "ledger": (1, 1, 1, 0),
                        }
                        for service, (
                            deliveries,
                            commits,
                            path_v1,
                            path_v2,
                        ) in expected_stats.items():
                            observed = stats[service]
                            paths = observed.get("paths", {})
                            if (
                                observed.get("deliveries") != deliveries
                                or observed.get("commits") != commits
                                or paths.get("/v1/charge", 0) != path_v1
                                or paths.get("/v2/charge", 0) != path_v2
                            ):
                                raise DemoError(
                                    f"{service} external facts differ: {observed}"
                                )
                        _write_json(output_dir / "effect-stats.json", stats)

                        state = _http_json(
                            deployment.control_url + "/v1/state",
                            token=tokens["admin"],
                        ).body
                        history = _http_json(
                            deployment.control_url + "/v1/history",
                            token=tokens["admin"],
                            require_object=False,
                        ).body
                        operation_ids = {
                            "codex": codex_operation_id,
                            "order": order_operation_id,
                            "vm": vm_operation_id,
                        }
                        operations = state.get("operations")
                        if not isinstance(operations, Mapping) or set(
                            operations
                        ) != set(operation_ids.values()):
                            raise DemoError(
                                f"shared History does not contain exactly three Operations: {state}"
                            )
                        expected_operations = {
                            codex_operation_id: (
                                CODEX_DOMAIN,
                                CHARGE_KIND,
                                "http://payment:8081/v1/charge",
                                2,
                                "",
                            ),
                            order_operation_id: (
                                ORDER_DOMAIN,
                                RESERVE_V1_KIND,
                                "http://inventory:8081/v1/charge",
                                2,
                                "",
                            ),
                            vm_operation_id: (
                                VM_DOMAIN,
                                AUDIT_KIND,
                                "http://ledger:8081/v1/charge",
                                1,
                                VM_SANDBOX_ID,
                            ),
                        }
                        for (
                            operation_id,
                            expected_operation,
                        ) in expected_operations.items():
                            operation = operations.get(operation_id)
                            if not isinstance(operation, Mapping):
                                raise DemoError(f"Operation {operation_id} is absent")
                            observed = (
                                operation.get("domain"),
                                operation.get("kind"),
                                operation.get("target"),
                                operation.get("dispatch_generation"),
                                operation.get("sandbox_id", ""),
                            )
                            if (
                                operation.get("phase") != "succeeded"
                                or observed != expected_operation
                            ):
                                raise DemoError(
                                    f"Operation {operation_id} differs: {operation}"
                                )
                        history_point = state.get("history")
                        requirement = state.get("requirement")
                        if (
                            not isinstance(history_point, Mapping)
                            or history_point.get("sequence") != 16
                            or not isinstance(requirement, Mapping)
                            or requirement.get("id") != requirement_v2["id"]
                            or not isinstance(history, list)
                            or len(history) != 16
                        ):
                            raise DemoError(
                                f"shared History did not end at the exact v2 state: {state}"
                            )
                        _write_json(output_dir / "final-state.json", state)
                        _write_json(output_dir / "history.json", history)

                        if ephemeral_auth.exists():
                            raise DemoError(
                                "Codex recreated temporary authentication before callback"
                            )
                        pending.respond_text(
                            json.dumps(
                                {
                                    "operations": operation_ids,
                                    "purchase_id": purchase_id,
                                    "remote_references": {
                                        "payment": payment_receipt[
                                            "remote_reference"
                                        ],
                                        "inventory": inventory_receipt[
                                            "remote_reference"
                                        ],
                                        "audit": operations[vm_operation_id][
                                            "remote_reference"
                                        ],
                                    },
                                    "status": "succeeded",
                                },
                                sort_keys=True,
                                separators=(",", ":"),
                            )
                        )
                        pending.wait_turn_completed(timeout=LIVE_TIMEOUT_SECONDS)
                        timeline["codex_turn_completed_ns"] = time.time_ns()
                        if ephemeral_auth.exists():
                            raise DemoError(
                                "Codex recreated temporary authentication during completion"
                            )
                        client.assert_hermetic_runtime()

                    _redact_protocol(raw_protocol)
                    protocol = _protocol_evidence(
                        raw_protocol,
                        thread_id=thread_id,
                        turn_id=pending.turn_id,
                        provider_call_id=pending.call_id,
                        callback_request_id=pending.request_id,
                        expected_tool=TOOL_NAME,
                        expected_arguments={"purchase_id": purchase_id},
                    )

                source_after = source_auth.stat()
                source_unchanged = (
                    _sha256_file(source_auth) == source_auth_digest
                    and source_after.st_mtime_ns == source_auth_stat.st_mtime_ns
                    and source_after.st_mode == source_auth_stat.st_mode
                )
                if not source_unchanged:
                    raise DemoError("host Codex authentication source changed")
                _write_json(
                    output_dir / "credential-lifecycle.json",
                    {
                        "actor_tokens_distinct": len(set(tokens.values())) == 3,
                        "host_source_modified": False,
                        "temporary_auth_removed_before_effect": True,
                        "vm_credential_free": True,
                    },
                )

                for source, name in (
                    (state_dir / "control/runtime.history", "runtime.history"),
                    (state_dir / "anchor/runtime.head", "runtime.head"),
                    (state_dir / "payment/payment.history", "payment.history"),
                    (
                        state_dir / "inventory/inventory.history",
                        "inventory.history",
                    ),
                    (state_dir / "ledger/ledger.history", "ledger.history"),
                ):
                    if not source.is_file():
                        raise DemoError(f"missing durable evidence: {source.name}")
                    shutil.copy2(source, output_dir / name)

                timeline["run_facts_complete_ns"] = time.time_ns()
                _write_json(output_dir / "timeline.json", timeline)
                _write_json(
                    output_dir / "sandbox-lifecycle.json",
                    sandbox_lifecycle,
                )
                vm_summary = _vm_result_summary(
                    backend=vm_backend,
                    runner_pid=vm.pid,
                    accel=vm_accel,
                    completed=vm_completed,
                )
                vm_provenance: dict[str, Any] = {}
                if vm_backend == "qemu":
                    vm_provenance["vm_demo_sha256"] = vm_binary_sha256
                else:
                    vm_provenance["vm_backend"] = "firecracker"
                    vm_provenance["firecracker_demo_sha256"] = vm_binary_sha256
                    vm_provenance["firecracker_guest_sha256"] = _sha256_file(vm_guest_binary)
                result = {
                    "run_id": project,
                    "purchase_id": purchase_id,
                    "codex": {
                        "version": version,
                        "login_status": login_status,
                        "model": protocol["model"],
                        "model_provider": protocol["model_provider"],
                        "native_binary_sha256": _sha256_file(native_codex),
                        "real_app_server": True,
                    },
                    "history": {
                        "sequence": 16,
                        "hash": state["history"]["hash"],
                        "operations": operation_ids,
                        "active_requirement": requirement_v2["id"],
                    },
                    "faults": {
                        "order_container_before": old_order_container,
                        "order_container_after": new_order_container,
                        "order_process_replaced": True,
                        "control_pid_before": control_pid_before,
                        "control_pid_after": control_pid_after,
                        "control_process_restarted": True,
                        "control_restart_mode": "sigkill",
                        "whole_vm_restored": True,
                    },
                    "effects": stats,
                    "network": topology,
                    "effect_ips": effect_ips,
                    "vm": vm_summary,
                    "protocol": protocol,
                    "provenance": {
                        "revision": source_provenance["revision"],
                        "source_tree_sha256": source_provenance[
                            "source_tree_sha256"
                        ],
                        "runtime_image_id": image_provenance["image_id"],
                        **vm_provenance,
                    },
                    "evidence_directory": output_dir.name,
                }
        finally:
            try:
                deployment.close()
            finally:
                if vm_stderr.is_file():
                    vm_error = vm_stderr.read_text(
                        encoding="utf-8", errors="replace"
                    )
                    if vm_error:
                        vm_error = vm_error.replace(
                            str(private_dir), "<redacted-private>"
                        ).replace(str(Path.home()), "<redacted-home>")
                        (output_dir / "logs/vm-runner.stderr").write_text(
                            vm_error,
                            encoding="utf-8",
                        )

    if result is None:
        raise DemoError("integrated experiment ended without a result")
    _write_json(output_dir / "result.json", result)
    return result


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--codex-auth",
        type=Path,
        default=Path.home() / ".codex/auth.json",
        help="private logged-in Codex auth.json; copied only into temporary state",
    )
    parser.add_argument("--vendor-bundle", type=Path)
    parser.add_argument("--model")
    parser.add_argument(
        "--vm-backend", choices=("qemu", "firecracker"), default="qemu"
    )
    parser.add_argument("--vm-accel", choices=("tcg", "kvm"), default="tcg")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_args(argv)
    output = arguments.output_dir
    if output is None:
        output = Path("docs/tmp/bootstrap") / time.strftime(
            "step-0018-%Y%m%dT%H%M%SZ", time.gmtime()
        )
    result = run_demo(
        output_dir=output,
        codex_auth=arguments.codex_auth,
        vendor_bundle=arguments.vendor_bundle,
        model=arguments.model,
        vm_accel=arguments.vm_accel,
        vm_backend=arguments.vm_backend,
    )
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
