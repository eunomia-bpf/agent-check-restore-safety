"""Run one purchase across real Codex, containers, and a restored QEMU VM.

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
from hashlib import sha256
import json
import os
from pathlib import Path
import selectors
import secrets
import shutil
import subprocess
import sys
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
CHARGE_KIND = "charge-invoice"
RESERVE_V1_KIND = "reserve-v1"
RESERVE_V2_KIND = "reserve-v2"
AUDIT_KIND = "append-audit"
LIVE_TIMEOUT_SECONDS = 20 * 60.0


def _project_name() -> str:
    return f"safe-change-integrated-{os.getpid()}-{secrets.token_hex(4)}"


def _operation_id(domain: str, call_id: str) -> str:
    digest = sha256()
    digest.update(b"operation-id-v1\x00")
    digest.update(domain.encode("utf-8"))
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

    def restart_control(self) -> tuple[int, int]:
        container = self.service_container("control")
        before = int(
            _run(["docker", "inspect", "-f", "{{.State.Pid}}", container])
            .stdout.strip()
        )
        self.compose("restart", "control", timeout=60.0)
        _wait_health(self.control_url + "/healthz")
        after = int(
            _run(["docker", "inspect", "-f", "{{.State.Pid}}", container])
            .stdout.strip()
        )
        if before <= 0 or after <= 0 or before == after:
            raise DemoError("control container did not replace its process")
        return before, after

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
        accel: str,
        control_port: int,
        token_path: Path,
        request_path: Path,
        direct_probe: str,
        evidence_dir: Path,
        stderr_path: Path,
    ) -> None:
        command = [
            str(binary),
            "-accel",
            accel,
            "-timeout",
            "18m",
            "-external-control-port",
            str(control_port),
            "-external-token-file",
            str(token_path),
            "-external-request",
            str(request_path),
            "-external-direct-probe",
            direct_probe,
            "-external-evidence-dir",
            str(evidence_dir),
        ]
        self._stderr = stderr_path.open("w", encoding="utf-8")
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._stderr,
            text=True,
            bufsize=1,
        )
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
        if command not in {"start", "restore"}:
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
    active = _http_json(
        deployment.control_url + "/v1/activate",
        method="POST",
        token=admin_token,
        payload=certificate,
    ).body
    _write_json(output_dir / f"active-state-{label}.json", active)
    return certificate, active


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
    topology = {
        "networks": normalized,
        "agent_to_effect_shared_networks": [],
        "order_to_effect_shared_networks": [],
        "fixed_actor_paths": {
            "codex": "ingress->control",
            "order": "control",
            "vm": "qemu-guestfwd->ingress->control",
        },
    }
    return topology, observations, effect_ips


def _copy_vm_evidence(source: Path, destination: Path, private_root: Path) -> None:
    destination.mkdir(mode=0o700)
    for name in (
        "result.json",
        "guest.serial.log",
        "snapshots.txt",
        "qemu-command.json",
        "qmp-protocol.jsonl",
    ):
        shutil.copy2(source / name, destination / name)
    log = (source / "qemu.log").read_text(encoding="utf-8", errors="replace")
    log = log.replace(str(Path.home()), "<redacted-home>")
    log = log.replace(str(private_root), "<redacted-private>")
    (destination / "qemu.log").write_text(log, encoding="utf-8")


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
    ):
        (state_dir / name).mkdir(mode=0o700)
    tokens = {
        "admin": _new_token(state_dir / "credentials/admin-token"),
        "codex": _new_token(state_dir / "credentials/codex-token"),
        "order": _new_token(state_dir / "credentials/order-token"),
        "vm": _new_token(state_dir / "credentials/vm-token"),
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
                {
                    "domain": VM_DOMAIN,
                    "token_file": "/credentials/vm-token",
                    "kinds": [AUDIT_KIND],
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
) -> dict[str, Any]:
    if vm_accel not in {"tcg", "kvm"}:
        raise DemoError("VM accelerator must be tcg or kvm")
    repository = Path(__file__).resolve().parents[1]
    runtime_dir = repository / "runtime"
    compose_file = runtime_dir / "deploy/integrated/compose.yaml"
    output_dir = output_dir.resolve()
    for command in ("docker", "qemu-system-x86_64", "qemu-img", "nc"):
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
    raw_protocol = output_dir / "app-server.jsonl"
    result: dict[str, Any] | None = None

    with tempfile.TemporaryDirectory(
        prefix="safe-change-integrated-private-"
    ) as private:
        private_dir = Path(private)
        private_dir.chmod(0o700)
        state_dir = private_dir / "state"
        workspace = private_dir / "agent-workspace"
        account_home = private_dir / "codex-home"
        wrapper_dir = private_dir / "wrapper"
        vm_work = private_dir / "vm-work"
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
        _write_release(
            state_dir / "order-config/order.json",
            "v1",
            RESERVE_V1_KIND,
            "http://inventory:8081/v1/charge",
        )
        vm_binary = binary_dir / "vm-demo"
        _run(
            ["go", "build", "-trimpath", "-o", str(vm_binary), "./cmd/vm-demo"],
            cwd=runtime_dir,
            timeout=120.0,
        )
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
            control_port=control_port,
            order_port=order_port,
        )

        timeline: dict[str, int] = {"run_start_ns": time.time_ns()}
        try:
            deployment.start()
            _compile_and_activate(
                deployment=deployment,
                runtime_dir=runtime_dir,
                output_dir=output_dir,
                admin_token=tokens["admin"],
                requirement=requirement_v1,
                label="v1",
            )
            timeline["rule_v1_activated_ns"] = time.time_ns()

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
                    "method": "POST",
                    "url": "http://ledger:8081/v1/charge",
                    "headers": {"Content-Type": "application/json"},
                    "body": base64.b64encode(vm_body).decode("ascii"),
                },
            )
            vm_request_path.chmod(0o600)
            ledger_container = deployment.service_container("ledger")
            ledger_ip = _network_ip(ledger_container, deployment.effects_network)
            vm_stderr = private_dir / "vm-runner.stderr"

            with VMProcess(
                binary=vm_binary,
                accel=vm_accel,
                control_port=deployment.control_port,
                token_path=state_dir / "credentials/vm-token",
                request_path=vm_request_path,
                direct_probe=f"http://{ledger_ip}:8081/v1/stats",
                evidence_dir=vm_work,
                stderr_path=vm_stderr,
            ) as vm:
                snapshot_event = vm.wait_event("snapshot-ready", 7 * 60.0)
                timeline["vm_snapshot_ready_ns"] = snapshot_event["observed_time_ns"]

                codex_call_id = f"purchase/{purchase_id}/payment"
                codex_operation_id = _operation_id(CODEX_DOMAIN, codex_call_id)
                order_call_id = f"order/{purchase_id}/payment"
                order_operation_id = _operation_id(ORDER_DOMAIN, order_call_id)
                vm_operation_id = _operation_id(VM_DOMAIN, vm_call_id)
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
                            deployment, docker_codex.container_name
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

                        _compile_and_activate(
                            deployment=deployment,
                            runtime_dir=runtime_dir,
                            output_dir=output_dir,
                            admin_token=tokens["admin"],
                            requirement=requirement_v2,
                            label="v2",
                        )
                        timeline["rule_v2_activated_ns"] = time.time_ns()
                        _write_release(
                            state_dir / "order-config/order.json",
                            "v2",
                            RESERVE_V2_KIND,
                            "http://inventory:8081/v2/charge",
                        )
                        old_order_container, new_order_container = (
                            deployment.replace_order()
                        )
                        timeline["order_replaced_ns"] = time.time_ns()
                        health = _http_json(deployment.order_url + "/healthz").body
                        if health.get("version") != "v2" or health.get("kind") != RESERVE_V2_KIND:
                            raise DemoError(f"new order release is not v2: {health}")

                        control_container = deployment.service_container("control")
                        control_pid_before, control_pid_after = (
                            deployment.restart_control()
                        )
                        timeline["control_restarted_ns"] = time.time_ns()
                        _capture_docker_inspect(
                            [control_container],
                            output_dir / "control-after-restart-inspect.json",
                        )
                        _capture_docker_inspect(
                            [new_order_container],
                            output_dir / "order-after-replacement-inspect.json",
                        )

                        vm.send("restore")
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
                            ),
                            order_operation_id: (
                                ORDER_DOMAIN,
                                RESERVE_V1_KIND,
                                "http://inventory:8081/v1/charge",
                                2,
                            ),
                            vm_operation_id: (
                                VM_DOMAIN,
                                AUDIT_KIND,
                                "http://ledger:8081/v1/charge",
                                1,
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
                            or history_point.get("sequence") != 15
                            or not isinstance(requirement, Mapping)
                            or requirement.get("id") != requirement_v2["id"]
                            or not isinstance(history, list)
                            or len(history) != 15
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
                        "actor_tokens_distinct": len(set(tokens.values())) == 4,
                        "host_source_modified": False,
                        "temporary_auth_removed_before_effect": True,
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
                        "sequence": 15,
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
                        "whole_vm_restored": True,
                    },
                    "effects": stats,
                    "network": topology,
                    "effect_ips": effect_ips,
                    "vm": {
                        "runner_pid": vm.pid,
                        "accelerator": vm_accel,
                        "snapshot": "before_purchase",
                        "first_reused": False,
                        "restored_reused": True,
                    },
                    "protocol": protocol,
                    "evidence_directory": output_dir.name,
                }
        finally:
            deployment.close()

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
    parser.add_argument("--vm-accel", choices=("tcg", "kvm"), default="tcg")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_args(argv)
    output = arguments.output_dir
    if output is None:
        output = Path("docs/tmp/bootstrap") / time.strftime(
            "step-0014-%Y%m%dT%H%M%SZ", time.gmtime()
        )
    result = run_demo(
        output_dir=output,
        codex_auth=arguments.codex_auth,
        vendor_bundle=arguments.vendor_bundle,
        model=arguments.model,
        vm_accel=arguments.vm_accel,
    )
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
