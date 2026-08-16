"""Run the real Codex payment recovery with an enforced Docker network cut.

This explicit live-account experiment strengthens ``codex_runtime_demo``: the
Codex App Server runs in a locked-down container on the agent network, payment
runs only on a separate internal effects network, and control is the sole
container attached to both.  The model callback remains pending while the
control container restarts after a lost payment response.
"""

from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Mapping, Sequence
from urllib.error import URLError

from adapter.app_server import CodexAppServer
from adapter.codex_runtime_demo import (
    CALL_ID,
    EFFECT_ID,
    LIVE_TIMEOUT_SECONDS,
    OPERATION_DOMAIN,
    OPERATION_KIND,
    TOOL_NAME,
    DemoError,
    _canonical_json,
    _decode_receipt,
    _http_json,
    _login_status,
    _operation_id,
    _protocol_evidence,
    _read_private_token,
    _sha256_file,
    _write_json,
)
from adapter.docker_codex import create_docker_codex


def _run(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float = 120.0,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        [str(value) for value in command],
        cwd=cwd,
        env=None if env is None else dict(env),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
        check=False,
    )
    if check and completed.returncode != 0:
        rendered = " ".join(str(value) for value in command)
        raise DemoError(
            f"command failed with {completed.returncode}: {rendered}\n"
            f"{completed.stdout[-6000:]}"
        )
    return completed


def _free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_health(url: str, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    last_error = "not attempted"
    while time.monotonic() < deadline:
        try:
            result = _http_json(url, timeout=1.0)
            if result.body.get("status") == "ok":
                return
            last_error = f"unexpected health body: {result.body}"
        except (DemoError, URLError, OSError) as error:
            last_error = str(error)
        time.sleep(0.2)
    raise DemoError(f"timed out waiting for {url}: {last_error}")


def _safe_project_name() -> str:
    return f"safe-change-codex-{os.getpid()}-{secrets.token_hex(4)}"


def _find_vendor_bundle(explicit: Path | None) -> Path:
    if explicit is not None:
        candidates = [explicit]
    else:
        roots = [
            Path.home()
            / ".local/share/codex-runtime/npm/lib/node_modules/@openai/codex/node_modules",
            Path.home() / ".npm-global/lib/node_modules/@openai/codex/node_modules",
            Path("/usr/local/lib/node_modules/@openai/codex/node_modules"),
        ]
        candidates: list[Path] = []
        for root in roots:
            candidates.extend(sorted(root.glob("@openai/codex-linux-*/vendor/*")))
    valid = [
        path.resolve()
        for path in candidates
        if (path / "bin/codex").is_file() and (path / "codex-resources").is_dir()
    ]
    if len(valid) > 1:
        digests = {_sha256_file(path / "bin/codex") for path in valid}
        if len(digests) == 1:
            valid = [sorted(valid)[0]]
    if len(valid) != 1:
        raise DemoError(
            "could not select one Codex native vendor bundle; pass --vendor-bundle "
            f"(found {len(valid)})"
        )
    return valid[0]


def _prepare_account_home(source_auth: Path, destination: Path) -> None:
    source_auth = source_auth.resolve()
    if not source_auth.is_file():
        raise DemoError(f"Codex auth file does not exist: {source_auth}")
    if source_auth.stat().st_mode & 0o077:
        raise DemoError(f"Codex auth file is not private: {source_auth}")
    destination.mkdir(mode=0o700)
    target = destination / "auth.json"
    shutil.copyfile(source_auth, target)
    target.chmod(0o600)


@dataclass
class ComposeDeployment:
    compose_file: Path
    state_dir: Path
    output_dir: Path
    project: str
    image: str
    control_port: int

    def __post_init__(self) -> None:
        environment = os.environ.copy()
        environment.update(
            {
                "COMPOSE_PROJECT_NAME": self.project,
                "CONTROL_PORT": str(self.control_port),
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
    def effects_network(self) -> str:
        return self.project + "_effects"

    @property
    def control_url(self) -> str:
        return f"http://127.0.0.1:{self.control_port}"

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
        self.compose(
            "up",
            "-d",
            "--wait",
            "--wait-timeout",
            "60",
            "payment",
            "control",
            timeout=120.0,
        )
        self.started = True
        _wait_health(self.control_url + "/healthz")

    def service_container(self, service: str) -> str:
        identifier = self.compose("ps", "-q", service).stdout.strip()
        if not identifier:
            raise DemoError(f"Compose service has no container: {service}")
        return identifier

    def container_pid(self, service: str) -> int:
        identifier = self.service_container(service)
        result = _run(
            ["docker", "inspect", "-f", "{{.State.Pid}}", identifier]
        ).stdout.strip()
        try:
            pid = int(result)
        except ValueError as error:
            raise DemoError(f"invalid container PID for {service}: {result}") from error
        if pid <= 0:
            raise DemoError(f"container for {service} is not running")
        return pid

    def restart_control(self) -> tuple[int, int]:
        before = self.container_pid("control")
        self.compose("restart", "control", timeout=60.0)
        _wait_health(self.control_url + "/healthz")
        after = self.container_pid("control")
        if after == before:
            raise DemoError("control restart did not replace its process")
        return before, after

    def payment_stats(self) -> dict[str, Any]:
        completed = self.compose(
            "exec",
            "-T",
            "control",
            "wget",
            "-qO-",
            "http://payment:8081/v1/stats",
        )
        try:
            value = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise DemoError(
                "payment stats from the effects network are not JSON"
            ) from error
        if not isinstance(value, dict):
            raise DemoError("payment stats are not an object")
        return value

    def logs(self) -> None:
        completed = self.compose("logs", "--no-color", check=False)
        path = self.output_dir / "logs" / "services.log"
        path.write_text(completed.stdout, encoding="utf-8")

    def close(self) -> None:
        if self.started:
            self.logs()
        compose_down = self.compose(
            "down", "--remove-orphans", timeout=90.0, check=False
        )
        (self.output_dir / "logs" / "compose-down.log").write_text(
            compose_down.stdout, encoding="utf-8"
        )
        image_cleanup = _run(
            ["docker", "image", "rm", self.image],
            timeout=60.0,
            check=False,
        )
        (self.output_dir / "logs" / "image-cleanup.log").write_text(
            image_cleanup.stdout, encoding="utf-8"
        )
        self.started = False
        _write_json(
            self.output_dir / "teardown.json",
            {
                "compose_down_returncode": compose_down.returncode,
                "image_remove_returncode": image_cleanup.returncode,
            },
        )
        if compose_down.returncode != 0 or image_cleanup.returncode != 0:
            raise DemoError(
                "isolated deployment teardown did not remove its project and image"
            )


def _container_networks(container: str) -> list[str]:
    completed = _run(
        [
            "docker",
            "inspect",
            "-f",
            "{{json .NetworkSettings.Networks}}",
            container,
        ]
    )
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise DemoError(f"invalid Docker network inspection for {container}") from error
    if not isinstance(value, dict):
        raise DemoError(f"Docker network inspection is not an object for {container}")
    return sorted(str(name) for name in value)


def _network_ip(container: str, network: str) -> str:
    template = '{{(index .NetworkSettings.Networks "' + network + '").IPAddress}}'
    address = _run(["docker", "inspect", "-f", template, container]).stdout.strip()
    parts = address.split(".")
    if len(parts) != 4 or any(
        not part.isdigit() or not 0 <= int(part) <= 255 for part in parts
    ):
        raise DemoError(f"invalid container address on {network}: {address}")
    return address


def _redact_host_home(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _redact_host_home(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_host_home(item) for item in value]
    if isinstance(value, str):
        return value.replace(str(Path.home()), "<redacted-home>")
    return value


def _docker_inspect_projection(
    value: Any,
    *,
    extra_label_names: Sequence[str] = (),
    include_image_identity: bool = False,
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise DemoError("Docker inspection is not a list")
    projected: list[dict[str, Any]] = []
    label_names = {
        "com.docker.compose.container-number",
        "com.docker.compose.project",
        "com.docker.compose.service",
    } | set(extra_label_names)
    for raw in value:
        if not isinstance(raw, dict):
            raise DemoError("Docker inspection contains a non-object")
        config = raw.get("Config")
        state = raw.get("State")
        host = raw.get("HostConfig")
        network_settings = raw.get("NetworkSettings")
        if not all(
            isinstance(item, dict) for item in (config, state, host, network_settings)
        ):
            raise DemoError("Docker inspection omitted a required object")
        labels = config.get("Labels")
        networks = network_settings.get("Networks")
        mounts = raw.get("Mounts")
        if not isinstance(labels, dict) or not isinstance(networks, dict):
            raise DemoError("Docker inspection omitted labels or networks")
        if not isinstance(mounts, list):
            raise DemoError("Docker inspection omitted mounts")
        document = {
                "Id": raw.get("Id"),
                "Name": raw.get("Name"),
                "Config": {
                    "Cmd": config.get("Cmd"),
                    "Entrypoint": config.get("Entrypoint"),
                    "Hostname": config.get("Hostname"),
                    "Image": config.get("Image"),
                    "Labels": {
                        key: labels[key] for key in label_names if key in labels
                    },
                    "User": config.get("User"),
                    "WorkingDir": config.get("WorkingDir"),
                },
                "State": {
                    "Pid": state.get("Pid"),
                    "Running": state.get("Running"),
                    "StartedAt": state.get("StartedAt"),
                },
                "HostConfig": {
                    "CapDrop": host.get("CapDrop"),
                    "NetworkMode": host.get("NetworkMode"),
                    "Privileged": host.get("Privileged"),
                    "ReadonlyRootfs": host.get("ReadonlyRootfs"),
                    "SecurityOpt": host.get("SecurityOpt"),
                    "Tmpfs": host.get("Tmpfs"),
                },
                "Mounts": [
                    {
                        "Destination": mount.get("Destination"),
                        "RW": mount.get("RW"),
                        "Type": mount.get("Type"),
                    }
                    for mount in mounts
                    if isinstance(mount, dict)
                ],
                "NetworkSettings": {
                    "Networks": {
                        name: {
                            "IPAddress": (
                                attachment.get("IPAddress")
                                if isinstance(attachment, dict)
                                else None
                            )
                        }
                        for name, attachment in networks.items()
                    }
                },
            }
        if include_image_identity:
            document["Image"] = raw.get("Image")
        projected.append(document)
    return projected


def _capture_docker_inspect(
    containers: Sequence[str],
    path: Path,
    *,
    extra_label_names: Sequence[str] = (),
    include_image_identity: bool = False,
) -> list[Any]:
    completed = _run(["docker", "inspect", *containers])
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise DemoError("raw Docker inspection is not JSON") from error
    if (
        not isinstance(value, list)
        or len(value) != len(containers)
        or not all(isinstance(item, dict) for item in value)
    ):
        raise DemoError("raw Docker inspection does not match requested containers")
    filtered = _docker_inspect_projection(
        _redact_host_home(value),
        extra_label_names=extra_label_names,
        include_image_identity=include_image_identity,
    )
    _write_json(path, filtered)
    return filtered


def _capture_docker_network_inspect(
    networks: Sequence[str], path: Path
) -> list[dict[str, Any]]:
    completed = _run(["docker", "network", "inspect", *networks])
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise DemoError("Docker network inspection is not JSON") from error
    if not isinstance(value, list) or len(value) != len(networks):
        raise DemoError("Docker network inspection differs from the request")
    projected: list[dict[str, Any]] = []
    for raw in value:
        if not isinstance(raw, dict) or not isinstance(raw.get("Containers"), dict):
            raise DemoError("Docker network inspection omitted container membership")
        projected.append(
            {
                "Containers": {
                    identifier: {
                        "IPv4Address": attachment.get("IPv4Address"),
                        "Name": attachment.get("Name"),
                    }
                    for identifier, attachment in raw["Containers"].items()
                    if isinstance(attachment, dict)
                },
                "Id": raw.get("Id"),
                "Internal": raw.get("Internal"),
                "Name": raw.get("Name"),
            }
        )
    _write_json(path, projected)
    return projected


def _redact_protocol(path: Path) -> None:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise DemoError(
                    f"cannot privacy-filter App Server line {line_number}"
                ) from error
            if not isinstance(record, dict):
                raise DemoError(
                    f"cannot privacy-filter non-object App Server line {line_number}"
                )
            payload = record.get("payload")
            if isinstance(payload, dict):
                method = payload.get("method")
                params = payload.get("params")
                if method == "remoteControl/status/changed" and isinstance(
                    params, dict
                ):
                    params["installationId"] = "<redacted>"
                if method == "account/rateLimits/updated" and isinstance(params, dict):
                    params["rateLimits"] = {"redacted": True}
            records.append(record)
    temporary = path.with_name(path.name + ".privacy-filtered")
    with temporary.open("w", encoding="utf-8") as destination:
        for record in records:
            destination.write(
                json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
            )
        destination.flush()
        os.fsync(destination.fileno())
    os.replace(temporary, path)


def _network_probe(container: str, url: str, label: str) -> dict[str, Any]:
    command = [
        "docker",
        "exec",
        container,
        "wget",
        "-T",
        "2",
        "-qO-",
        url,
    ]
    started = time.time_ns()
    completed = _run(
        command,
        timeout=10.0,
        check=False,
    )
    finished = time.time_ns()
    return {
        "label": label,
        "command": command,
        "returncode": completed.returncode,
        "output": completed.stdout,
        "started_time_ns": started,
        "finished_time_ns": finished,
    }


def _require_payment_blocked(container: str, payment_ip: str) -> list[dict[str, Any]]:
    positive = _network_probe(
        container, "http://control:8787/healthz", "control-health"
    )
    observations = [positive]
    if positive["returncode"] != 0:
        raise DemoError(
            "Codex network probe could not reach the control health endpoint"
        )
    try:
        health = json.loads(positive["output"])
    except json.JSONDecodeError as error:
        raise DemoError(
            "Codex network probe returned invalid control health"
        ) from error
    if health != {"status": "ok"}:
        raise DemoError(f"Codex network probe returned unexpected health: {health}")

    for label, description, url in (
        ("payment-name", "service name", "http://payment:8081/v1/stats"),
        (
            "payment-ip",
            "effects-network IP",
            f"http://{payment_ip}:8081/v1/stats",
        ),
    ):
        probe = _network_probe(container, url, label)
        observations.append(probe)
        if probe["returncode"] == 0:
            raise DemoError(
                f"Codex container reached payment directly by {description}"
            )
    return observations


def _validate_network_cut(
    deployment: ComposeDeployment, codex_container: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    control_container = deployment.service_container("control")
    payment_container = deployment.service_container("payment")
    networks = {
        "codex": _container_networks(codex_container),
        "control": _container_networks(control_container),
        "payment": _container_networks(payment_container),
    }
    expected = {
        "codex": [deployment.agent_network],
        "control": sorted([deployment.agent_network, deployment.effects_network]),
        "payment": [deployment.effects_network],
    }
    if networks != expected:
        raise DemoError(
            f"Docker network topology differs from the enforced cut: {networks}"
        )
    payment_ip = _network_ip(payment_container, deployment.effects_network)
    observations = _require_payment_blocked(codex_container, payment_ip)
    return (
        {
            "networks": networks,
            "codex_payment_shared_networks": [],
            "control_is_only_bridge": True,
            "control_health_from_codex": "reachable",
            "direct_payment_by_name_from_codex": "blocked",
            "direct_payment_by_ip_from_codex": "blocked",
        },
        observations,
    )


def run_demo(
    *,
    output_dir: Path,
    codex_auth: Path,
    vendor_bundle: Path | None,
    model: str | None,
) -> dict[str, Any]:
    repository = Path(__file__).resolve().parents[1]
    runtime_dir = repository / "runtime"
    compose_file = repository / "runtime/deploy/codex-isolated/compose.yaml"
    if shutil.which("docker") is None:
        raise DemoError("Docker is required for the isolated Codex experiment")
    vendor = _find_vendor_bundle(vendor_bundle)
    native_codex = vendor / "bin/codex"

    output_dir.mkdir(parents=True, exist_ok=False)
    output_dir.chmod(0o700)
    (output_dir / "logs").mkdir(mode=0o700)
    raw_protocol = output_dir / "app-server.jsonl"

    result: dict[str, Any] | None = None
    with tempfile.TemporaryDirectory(
        prefix="safe-change-codex-isolated-private-"
    ) as private:
        private_dir = Path(private)
        private_dir.chmod(0o700)
        state_dir = private_dir / "state"
        workspace = private_dir / "agent-workspace"
        account_home = private_dir / "codex-home"
        wrapper_dir = private_dir / "wrapper"
        for directory in (
            state_dir,
            state_dir / "payment",
            state_dir / "control",
            state_dir / "anchor",
            workspace,
            wrapper_dir,
        ):
            directory.mkdir(mode=0o700)
        _prepare_account_home(codex_auth, account_home)

        project = _safe_project_name()
        image = "safe-change-runtime:" + project
        deployment = ComposeDeployment(
            compose_file=compose_file,
            state_dir=state_dir,
            output_dir=output_dir,
            project=project,
            image=image,
            control_port=_free_port(),
        )
        try:
            deployment.start()
            admin_token = _read_private_token(state_dir / "control" / "admin-token")
            operation_token = _read_private_token(
                state_dir / "control" / "operation-token"
            )
            target = "http://payment:8081/v1/charge"
            requirement = {
                "id": "codex-payment-isolated-v1/" + project,
                "results": {"paid": 1},
                "capacities": {"charge": 1},
                "kinds": {
                    OPERATION_KIND: {
                        "costs": {"charge": 1},
                        "produces": {"paid": 1},
                        "retry_safe": True,
                        "queryable": False,
                        "target": target,
                        "method": "POST",
                        "response_classifier": "operation-receipt-v1",
                    }
                },
            }
            _write_json(output_dir / "requirement.json", requirement)
            certificate = _http_json(
                deployment.control_url + "/v1/compile",
                method="POST",
                token=admin_token,
                payload=requirement,
            ).body
            if certificate.get("decision") != "activate" or not isinstance(
                certificate.get("rule"), dict
            ):
                raise DemoError(f"Requirement did not compile to a Rule: {certificate}")
            _write_json(output_dir / "certificate.json", certificate)
            certificate_state = _http_json(
                deployment.control_url + "/v1/certificate-state",
                method="POST",
                token=admin_token,
                payload=certificate,
            ).body
            _write_json(output_dir / "certificate-state.json", certificate_state)
            checker = _run(
                [
                    "go",
                    "run",
                    "./cmd/check-certificate",
                    "-state",
                    str(output_dir / "certificate-state.json"),
                    "-certificate",
                    str(output_dir / "certificate.json"),
                ],
                cwd=runtime_dir,
                timeout=120.0,
            )
            try:
                checker_verdict = json.loads(checker.stdout)
            except json.JSONDecodeError as error:
                raise DemoError("standalone Certificate verdict is not JSON") from error
            if (
                not isinstance(checker_verdict, dict)
                or checker_verdict.get("valid") is not True
            ):
                raise DemoError(
                    f"standalone Certificate checker rejected: {checker_verdict}"
                )
            _write_json(output_dir / "checker-verdict.json", checker_verdict)
            active = _http_json(
                deployment.control_url + "/v1/activate",
                method="POST",
                token=admin_token,
                payload=certificate,
            ).body
            _write_json(output_dir / "active-state.json", active)

            payment_body = _canonical_json(
                {
                    "amount": 42,
                    "experiment_id": project,
                    "order_id": EFFECT_ID,
                }
            )
            execute_payload = {
                "call_id": CALL_ID,
                "kind": OPERATION_KIND,
                "method": "POST",
                "url": target,
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
                            "Submit the one application-approved payment identity. "
                            "Call exactly once and do not alter the identity."
                        ),
                        input_schema={
                            "type": "object",
                            "required": ["effect_id"],
                            "properties": {
                                "effect_id": {
                                    "type": "string",
                                    "enum": [EFFECT_ID],
                                }
                            },
                            "additionalProperties": False,
                        },
                        developer_instructions=(
                            "Only protected_payment is available. Do not inspect "
                            "files, run commands, or request another tool."
                        ),
                    )
                    thread_id = str(thread["id"])
                    pending = client.start_protected_turn(
                        thread_id,
                        (
                            f"Experiment {project}: call {TOOL_NAME} exactly once "
                            f"with effect_id {EFFECT_ID}. After it returns, reply "
                            "exactly DONE."
                        ),
                        expected_tool=TOOL_NAME,
                        expected_arguments={"effect_id": EFFECT_ID},
                        timeout=LIVE_TIMEOUT_SECONDS,
                    )
                    ephemeral_auth = account_home / "auth.json"
                    if not ephemeral_auth.is_file():
                        raise DemoError(
                            "temporary Codex authentication disappeared before the tool call"
                        )
                    ephemeral_auth.unlink()
                    if ephemeral_auth.exists():
                        raise DemoError(
                            "temporary Codex authentication remained after tool-call start"
                        )
                    _write_json(
                        output_dir / "credential-lifecycle.json",
                        {
                            "host_source_modified": False,
                            "temporary_auth_removed_before_effect": True,
                        },
                    )

                    control_container = deployment.service_container("control")
                    payment_container = deployment.service_container("payment")
                    _capture_docker_inspect(
                        [
                            docker_codex.container_name,
                            control_container,
                            payment_container,
                        ],
                        output_dir / "docker-inspect.json",
                    )
                    _capture_docker_network_inspect(
                        [deployment.agent_network, deployment.effects_network],
                        output_dir / "docker-network-inspect.json",
                    )
                    topology, network_probes = _validate_network_cut(
                        deployment, docker_codex.container_name
                    )
                    _write_json(output_dir / "network-topology.json", topology)
                    _write_json(output_dir / "network-probes.json", network_probes)

                    first = _http_json(
                        deployment.control_url + "/v1/execute",
                        method="POST",
                        token=operation_token,
                        payload=execute_payload,
                        expected=frozenset({409}),
                        timeout=40.0,
                    ).body
                    first_outcome = first.get("outcome")
                    if (
                        not isinstance(first_outcome, dict)
                        or first_outcome.get("phase") != "unknown"
                    ):
                        raise DemoError(
                            f"lost response did not produce unknown: {first}"
                        )
                    _write_json(output_dir / "first-outcome.json", first)

                    before_pid, after_pid = deployment.restart_control()
                    _capture_docker_inspect(
                        [control_container],
                        output_dir / "control-after-restart-inspect.json",
                    )
                    recovered = _http_json(
                        deployment.control_url + "/v1/execute",
                        method="POST",
                        token=operation_token,
                        payload=execute_payload,
                        timeout=40.0,
                    ).body
                    if (
                        recovered.get("phase") != "succeeded"
                        or recovered.get("reused") is not False
                    ):
                        raise DemoError(
                            f"Operation did not recover through payment: {recovered}"
                        )
                    receipt = _decode_receipt(recovered)
                    expected_operation_id = _operation_id()
                    if (
                        recovered.get("operation_id") != expected_operation_id
                        or receipt.get("operation_id") != expected_operation_id
                        or receipt.get("outcome") != "succeeded"
                    ):
                        raise DemoError("receipt did not bind the expected Operation")
                    _write_json(output_dir / "recovered-outcome.json", recovered)

                    reused = _http_json(
                        deployment.control_url + "/v1/execute",
                        method="POST",
                        token=operation_token,
                        payload=execute_payload,
                    ).body
                    if (
                        reused.get("phase") != "succeeded"
                        or reused.get("reused") is not True
                    ):
                        raise DemoError(f"settled Operation was not reused: {reused}")
                    _write_json(output_dir / "reused-outcome.json", reused)

                    if ephemeral_auth.exists():
                        raise DemoError(
                            "Codex rewrote temporary authentication before callback response"
                        )
                    pending.respond_text(
                        json.dumps(
                            {
                                "effect_id": EFFECT_ID,
                                "remote_reference": receipt["remote_reference"],
                                "status": "succeeded",
                            },
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                    )
                    pending.wait_turn_completed(timeout=LIVE_TIMEOUT_SECONDS)
                    if ephemeral_auth.exists():
                        raise DemoError(
                            "Codex rewrote temporary authentication during completion"
                        )
                    client.assert_hermetic_runtime()

                _redact_protocol(raw_protocol)
                protocol = _protocol_evidence(
                    raw_protocol,
                    thread_id=thread_id,
                    turn_id=pending.turn_id,
                    provider_call_id=pending.call_id,
                    callback_request_id=pending.request_id,
                )

            stats = deployment.payment_stats()
            if (
                stats.get("deliveries") != 2
                or stats.get("commits") != 1
                or stats.get("paths", {}).get("/v1/charge") != 2
            ):
                raise DemoError(f"payment was not exactly-once: {stats}")
            state = _http_json(
                deployment.control_url + "/v1/state", token=admin_token
            ).body
            history = _http_json(
                deployment.control_url + "/v1/history",
                token=admin_token,
                require_object=False,
            ).body
            operation = state.get("operations", {}).get(_operation_id())
            if (
                not isinstance(operation, dict)
                or operation.get("phase") != "succeeded"
                or operation.get("target") != target
            ):
                raise DemoError(f"final control state is inconsistent: {state}")
            _write_json(output_dir / "payment-stats.json", stats)
            _write_json(output_dir / "final-state.json", state)
            _write_json(output_dir / "history.json", history)

            for source, name in (
                (state_dir / "control" / "runtime.history", "runtime.history"),
                (state_dir / "anchor" / "runtime.head", "runtime.head"),
                (state_dir / "payment" / "payment.history", "payment.history"),
            ):
                if source.is_file():
                    shutil.copy2(source, output_dir / name)

            result = {
                "run_id": project,
                "codex": {
                    "version": version,
                    "login_status": login_status,
                    "model": protocol["model"],
                    "model_provider": protocol["model_provider"],
                    "native_binary_sha256": _sha256_file(native_codex),
                    "real_app_server": True,
                },
                "operation": {
                    "operation_id": _operation_id(),
                    "first_result": "unknown",
                    "recovered_result": "succeeded",
                    "settled_retry_reused": True,
                },
                "fault": {
                    "control_pid_before": before_pid,
                    "control_pid_after": after_pid,
                    "control_restarted_while_callback_pending": True,
                },
                "payment": {"deliveries": 2, "durable_commits": 1},
                "network": topology,
                "protocol": protocol,
                "evidence_directory": output_dir.name,
            }
        finally:
            deployment.close()

    if result is None:
        raise DemoError("isolated Codex experiment ended without a result")
    _write_json(output_dir / "result.json", result)
    evidence_check = _run(
        [
            sys.executable,
            "-m",
            "adapter.check_codex_isolated_evidence",
            str(output_dir),
            "--runtime-dir",
            str(runtime_dir),
            "--output",
            str(output_dir / "independent-verdict.json"),
        ],
        cwd=repository,
        timeout=120.0,
    )
    try:
        independent_verdict = json.loads(evidence_check.stdout)
    except json.JSONDecodeError as error:
        raise DemoError("independent evidence verdict is not JSON") from error
    if (
        not isinstance(independent_verdict, dict)
        or independent_verdict.get("valid") is not True
    ):
        raise DemoError(f"independent evidence checker rejected: {independent_verdict}")
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
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_args(argv)
    output = arguments.output_dir
    if output is None:
        output = Path(tempfile.mkdtemp(prefix="safe-change-codex-isolated-evidence-"))
        output.rmdir()
    try:
        result = run_demo(
            output_dir=output.resolve(),
            codex_auth=arguments.codex_auth,
            vendor_bundle=arguments.vendor_bundle,
            model=arguments.model,
        )
    except BaseException as error:
        if output.exists():
            _write_json(
                output / "failure.json",
                {"error_type": type(error).__name__, "error": str(error)},
            )
        raise
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["ComposeDeployment", "run_demo"]
