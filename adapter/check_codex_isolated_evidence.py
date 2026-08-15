"""Independently verify the retained isolated-Codex experiment evidence.

The live runner is not imported here.  This checker derives the stable
Operation identity, replays the binary History hash chain, validates the
external head anchor and payment record, and joins those records with the raw
Codex App Server protocol.  A saved summary is never accepted as evidence for
itself.
"""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
import struct
import subprocess
from typing import Any, Mapping, Sequence


EFFECT_ID = "codex-order-A-17"
TOOL_NAME = "protected_payment"
CALL_ID = f"{TOOL_NAME}/v1/{EFFECT_ID}"
OPERATION_DOMAIN = "codex-app-server"
OPERATION_KIND = "charge-invoice"
PAYMENT_TARGET = "http://payment:8081/v1/charge"
ZERO_HASH = "0" * 64
MAX_JSON_BYTES = 2 << 20
MAX_HISTORY_BYTES = 32 << 20
MAX_HISTORY_FRAME_BYTES = 16 << 20
RUN_ID = re.compile(r"safe-change-codex-[1-9][0-9]*-[0-9a-f]{8}\Z")


class EvidenceError(ValueError):
    """The retained evidence is malformed, inconsistent, or incomplete."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceError(message)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceError(f"JSON object contains duplicate key {key!r}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise EvidenceError(f"JSON contains non-finite number {value}")


def _loads(data: bytes, label: str) -> Any:
    try:
        return json.loads(
            data,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, EvidenceError) as error:
        if isinstance(error, EvidenceError):
            raise
        raise EvidenceError(f"{label} is not strict JSON") from error


def _read(path: Path, *, limit: int = MAX_JSON_BYTES) -> bytes:
    try:
        info = path.lstat()
    except FileNotFoundError as error:
        raise EvidenceError(f"required evidence file is absent: {path.name}") from error
    _require(stat.S_ISREG(info.st_mode), f"evidence is not a regular file: {path.name}")
    _require(
        not stat.S_ISLNK(info.st_mode), f"evidence cannot be a symlink: {path.name}"
    )
    _require(info.st_size <= limit, f"evidence file is too large: {path.name}")
    data = path.read_bytes()
    _require(
        len(data) == info.st_size, f"evidence file changed while read: {path.name}"
    )
    return data


def _json_file(directory: Path, name: str) -> Any:
    return _loads(_read(directory / name), name)


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EvidenceError(f"{label} must be an object")
    return value


def _list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise EvidenceError(f"{label} must be a list")
    return value


def _hash(value: Any, label: str) -> str:
    _require(
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value),
        f"{label} must be a lowercase SHA-256 digest",
    )
    return value


def _operation_id() -> str:
    digest = sha256()
    digest.update(b"operation-id-v1\x00")
    digest.update(OPERATION_DOMAIN.encode())
    digest.update(b"\x00")
    digest.update(CALL_ID.encode())
    return "op-" + digest.hexdigest()


def _skip_space(data: bytes, position: int) -> int:
    while position < len(data) and data[position] in b" \t\r\n":
        position += 1
    return position


def _string_end(data: bytes, position: int) -> int:
    _require(
        position < len(data) and data[position] == ord('"'), "expected JSON string"
    )
    position += 1
    while position < len(data):
        byte = data[position]
        if byte == ord('"'):
            return position + 1
        if byte == ord("\\"):
            position += 2
        else:
            position += 1
    raise EvidenceError("unterminated JSON string")


def _value_end(data: bytes, position: int) -> int:
    position = _skip_space(data, position)
    _require(position < len(data), "missing JSON value")
    if data[position] == ord('"'):
        return _string_end(data, position)
    if data[position] in (ord("{"), ord("[")):
        stack = [data[position]]
        position += 1
        while position < len(data) and stack:
            byte = data[position]
            if byte == ord('"'):
                position = _string_end(data, position)
                continue
            if byte in (ord("{"), ord("[")):
                stack.append(byte)
            elif byte in (ord("}"), ord("]")):
                expected = ord("}") if stack[-1] == ord("{") else ord("]")
                _require(byte == expected, "mismatched JSON delimiters")
                stack.pop()
            position += 1
        _require(not stack, "unterminated JSON composite value")
        return position
    while position < len(data) and data[position] not in b",}] \t\r\n":
        position += 1
    return position


def _raw_object_member(data: bytes, wanted: str) -> bytes:
    """Return one top-level object's exact encoded member value."""

    position = _skip_space(data, 0)
    _require(
        position < len(data) and data[position] == ord("{"), "frame is not an object"
    )
    position += 1
    found: bytes | None = None
    while True:
        position = _skip_space(data, position)
        _require(position < len(data), "unterminated JSON object")
        if data[position] == ord("}"):
            break
        key_start = position
        key_end = _string_end(data, key_start)
        key = _loads(data[key_start:key_end], "frame member name")
        position = _skip_space(data, key_end)
        _require(
            position < len(data) and data[position] == ord(":"), "missing member colon"
        )
        value_start = _skip_space(data, position + 1)
        value_end = _value_end(data, value_start)
        if key == wanted:
            _require(found is None, f"duplicate frame member {wanted!r}")
            found = data[value_start:value_end]
        position = _skip_space(data, value_end)
        _require(position < len(data), "unterminated JSON object")
        if data[position] == ord(","):
            position += 1
            continue
        _require(data[position] == ord("}"), "invalid object member separator")
        break
    _require(found is not None, f"frame omitted member {wanted!r}")
    return found


def _hash_part(value: bytes) -> bytes:
    return struct.pack(">Q", len(value)) + value


def _event_hash(sequence: int, previous: str, operation: str, data: bytes) -> str:
    digest = sha256()
    digest.update(b"history-event-v1\x00")
    digest.update(struct.pack(">Q", sequence))
    digest.update(_hash_part(previous.encode()))
    digest.update(_hash_part(operation.encode()))
    digest.update(_hash_part(data))
    return digest.hexdigest()


def _replay_history(path: Path) -> list[dict[str, Any]]:
    raw = _read(path, limit=MAX_HISTORY_BYTES)
    offset = 0
    previous = ZERO_HASH
    events: list[dict[str, Any]] = []
    while offset < len(raw):
        _require(len(raw) - offset >= 12, "History has an incomplete frame header")
        _require(raw[offset : offset + 4] == b"HST1", "History frame marker is invalid")
        length = struct.unpack(">Q", raw[offset + 4 : offset + 12])[0]
        _require(
            0 < length <= MAX_HISTORY_FRAME_BYTES, "History frame length is invalid"
        )
        start = offset + 12
        end = start + length
        _require(end <= len(raw), "History has an incomplete final frame")
        payload = raw[start:end]
        stored = _object(
            _loads(payload, f"History frame {len(events) + 1}"), "History frame"
        )
        _require(
            set(stored)
            == {"version", "sequence", "operation", "data", "previous_hash", "hash"},
            "History frame fields differ from format version 1",
        )
        sequence = stored["sequence"]
        operation = stored["operation"]
        _require(stored["version"] == 1, "History frame version is unsupported")
        _require(
            type(sequence) is int and sequence == len(events) + 1,
            "History sequence is not contiguous",
        )
        _require(isinstance(operation, str) and operation, "History operation is empty")
        _require(
            stored["previous_hash"] == previous, "History previous hash is inconsistent"
        )
        current = _hash(stored["hash"], "History event hash")
        data_raw = _raw_object_member(payload, "data")
        _require(
            current == _event_hash(sequence, previous, operation, data_raw),
            "History event hash does not match the retained frame bytes",
        )
        events.append(
            {
                "sequence": sequence,
                "operation": operation,
                "data": stored["data"],
                "previous_hash": previous,
                "hash": current,
            }
        )
        previous = current
        offset = end
    _require(events, "History is empty")
    return events


def _check_anchor(directory: Path, sequence: int, history_hash: str) -> None:
    raw = _read(directory / "runtime.head")
    anchor = _object(_loads(raw, "runtime.head"), "runtime.head")
    _require(
        set(anchor) == {"version", "sequence", "hash", "checksum"},
        "runtime.head fields differ from format version 1",
    )
    _require(anchor["version"] == 1, "runtime.head version is unsupported")
    _require(
        anchor["sequence"] == sequence and anchor["hash"] == history_hash,
        "external head does not match History",
    )
    checksum = sha256(
        b"history-head-anchor-v1\x00"
        + struct.pack(">Q", sequence)
        + history_hash.encode()
    ).hexdigest()
    _require(anchor["checksum"] == checksum, "external head checksum is invalid")
    canonical_value = {
        "version": 1,
        "sequence": sequence,
        "hash": history_hash,
        "checksum": checksum,
    }
    canonical = (
        json.dumps(canonical_value, separators=(",", ":"), ensure_ascii=True).encode()
        + b"\n"
    )
    _require(raw == canonical, "external head is not canonically encoded")


def _one(values: list[Any], label: str) -> Any:
    _require(len(values) == 1, f"expected one {label}, observed {len(values)}")
    return values[0]


def _rfc3339_nanoseconds(value: Any, label: str) -> int:
    _require(isinstance(value, str), f"{label} must be an RFC3339 timestamp")
    matched = re.fullmatch(
        r"([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2})"
        r"(?:\.([0-9]{1,9}))?Z",
        value,
    )
    _require(matched is not None, f"{label} must be an RFC3339 UTC timestamp")
    assert matched is not None
    try:
        seconds = int(
            datetime.strptime(matched.group(1), "%Y-%m-%dT%H:%M:%S")
            .replace(tzinfo=timezone.utc)
            .timestamp()
        )
    except ValueError as error:
        raise EvidenceError(f"{label} is not a real timestamp") from error
    fraction = (matched.group(2) or "").ljust(9, "0")
    return seconds * 1_000_000_000 + int(fraction or "0")


def _inspect_object(value: Any, label: str) -> dict[str, Any]:
    item = _object(value, label)
    _require(
        set(item)
        == {"Config", "HostConfig", "Id", "Mounts", "Name", "NetworkSettings", "State"},
        f"{label} is not the privacy-minimal Docker projection",
    )
    _require(isinstance(item.get("Id"), str) and item.get("Id"), f"{label} has no ID")
    _require(
        isinstance(item.get("Name"), str) and item.get("Name", "").startswith("/"),
        f"{label} has no Docker name",
    )
    return item


def _docker_networks(item: Mapping[str, Any], label: str) -> dict[str, Any]:
    network_settings = _object(item.get("NetworkSettings"), f"{label} networks")
    _require(
        set(network_settings) == {"Networks"},
        f"{label} retained unnecessary Docker network fields",
    )
    networks = _object(network_settings.get("Networks"), f"{label} network map")
    for attachment_value in networks.values():
        attachment = _object(attachment_value, f"{label} network attachment")
        _require(
            set(attachment) == {"IPAddress"},
            f"{label} retained unnecessary Docker attachment fields",
        )
    return networks


def _docker_service(item: Mapping[str, Any]) -> str | None:
    config = item.get("Config")
    labels = config.get("Labels") if isinstance(config, dict) else None
    if not isinstance(labels, dict):
        return None
    _require(
        set(labels)
        <= {
            "com.docker.compose.container-number",
            "com.docker.compose.project",
            "com.docker.compose.service",
        },
        "Docker projection retained an unnecessary Compose label",
    )
    if "com.docker.compose.container-number" not in labels:
        return None
    value = labels.get("com.docker.compose.service")
    return value if isinstance(value, str) else None


def _check_container_hardening(item: Mapping[str, Any], label: str) -> None:
    host = _object(item.get("HostConfig"), f"{label} host configuration")
    _require(
        set(host)
        == {
            "CapDrop",
            "NetworkMode",
            "Privileged",
            "ReadonlyRootfs",
            "SecurityOpt",
            "Tmpfs",
        },
        f"{label} retained unnecessary Docker host fields",
    )
    _require(host.get("ReadonlyRootfs") is True, f"{label} root filesystem is writable")
    _require(host.get("Privileged") is False, f"{label} is a privileged container")
    _require(host.get("CapDrop") == ["ALL"], f"{label} did not drop all capabilities")
    security = host.get("SecurityOpt")
    _require(
        isinstance(security, list)
        and any(
            option in {"no-new-privileges=true", "no-new-privileges:true"}
            for option in security
        ),
        f"{label} did not set no-new-privileges",
    )
    state = _object(item.get("State"), f"{label} state")
    _require(
        set(state) == {"Pid", "Running", "StartedAt"},
        f"{label} retained unnecessary Docker state fields",
    )
    _require(
        state.get("Running") is True
        and type(state.get("Pid")) is int
        and state.get("Pid") > 0,
        f"{label} was not a running container when inspected",
    )
    mounts = _list(item.get("Mounts"), f"{label} mounts")
    for mount_value in mounts:
        mount = _object(mount_value, f"{label} mount")
        _require(
            set(mount) == {"Destination", "RW", "Type"},
            f"{label} retained a Docker mount source",
        )
        destination = str(mount.get("Destination", ""))
        _require(
            destination != "/var/run/docker.sock",
            f"{label} received the host Docker socket",
        )


def _check_docker_evidence(directory: Path, run_id: str) -> dict[str, Any]:
    raw_initial = _list(
        _json_file(directory, "docker-inspect.json"), "Docker inspection"
    )
    _require(len(raw_initial) == 3, "Docker inspection must contain three containers")
    initial = [
        _inspect_object(item, f"Docker container {index}")
        for index, item in enumerate(raw_initial, 1)
    ]
    by_service = {
        service: item
        for item in initial
        if (service := _docker_service(item)) in {"control", "payment"}
    }
    _require(
        set(by_service) == {"control", "payment"},
        "Compose services are absent from Docker inspection",
    )
    codex_candidates = [item for item in initial if _docker_service(item) is None]
    codex = _inspect_object(
        _one(codex_candidates, "Codex container"), "Codex container"
    )
    control = by_service["control"]
    payment = by_service["payment"]
    _require(
        len({str(item["Id"]) for item in initial}) == 3,
        "Docker inspection repeats a container",
    )

    expected_image = "safe-change-runtime:" + run_id
    container_users: list[Any] = []
    for label, item in (("Codex", codex), ("control", control), ("payment", payment)):
        _check_container_hardening(item, label)
        config = _object(item.get("Config"), f"{label} configuration")
        _require(
            set(config)
            == {
                "Cmd",
                "Entrypoint",
                "Hostname",
                "Image",
                "Labels",
                "User",
                "WorkingDir",
            },
            f"{label} retained unnecessary Docker configuration fields",
        )
        _require(
            config.get("Image") == expected_image, f"{label} used another runtime image"
        )
        container_users.append(config.get("User"))
    _require(
        len(set(container_users)) == 1
        and isinstance(container_users[0], str)
        and re.fullmatch(r"[1-9][0-9]*:[1-9][0-9]*", container_users[0]) is not None,
        "containers did not share one non-root numeric UID/GID",
    )

    for service, item in (("control", control), ("payment", payment)):
        config = _object(item.get("Config"), f"{service} configuration")
        labels = _object(config.get("Labels"), f"{service} labels")
        _require(
            set(labels)
            == {
                "com.docker.compose.container-number",
                "com.docker.compose.project",
                "com.docker.compose.service",
            }
            and labels.get("com.docker.compose.project") == run_id
            and labels.get("com.docker.compose.service") == service,
            f"{service} belongs to another Compose project",
        )

    agent_network = run_id + "_agent"
    effects_network = run_id + "_effects"
    networks = {
        "codex": sorted(_docker_networks(codex, "Codex")),
        "control": sorted(_docker_networks(control, "control")),
        "payment": sorted(_docker_networks(payment, "payment")),
    }
    _require(
        networks
        == {
            "codex": [agent_network],
            "control": [agent_network, effects_network],
            "payment": [effects_network],
        },
        "raw Docker inspection does not contain the exact network cut",
    )
    network_values = _list(
        _json_file(directory, "docker-network-inspect.json"),
        "Docker network inspection",
    )
    _require(
        len(network_values) == 2, "Docker network inspection must contain two networks"
    )
    network_documents = {
        str(document["Name"]): document
        for value in network_values
        if isinstance(value, dict)
        and (document := _object(value, "Docker network"))
        and set(document) == {"Containers", "Id", "Internal", "Name"}
    }
    _require(
        set(network_documents) == {agent_network, effects_network},
        "Docker network inspection names another deployment",
    )
    expected_members = {
        agent_network: {str(codex["Id"]): codex, str(control["Id"]): control},
        effects_network: {
            str(control["Id"]): control,
            str(payment["Id"]): payment,
        },
    }
    for network_name, members in expected_members.items():
        network_document = network_documents[network_name]
        _require(
            isinstance(network_document.get("Id"), str) and network_document.get("Id"),
            "Docker network inspection omitted its identity",
        )
        _require(
            network_document.get("Internal") is (network_name == effects_network),
            "Docker effects network internal flag is inconsistent",
        )
        attachments = _object(
            network_document.get("Containers"),
            f"{network_name} container membership",
        )
        _require(
            set(attachments) == set(members),
            f"{network_name} has an unrecorded or missing container",
        )
        for identifier, container in members.items():
            attachment = _object(attachments[identifier], f"{network_name} attachment")
            _require(
                set(attachment) == {"IPv4Address", "Name"}
                and attachment.get("Name") == str(container["Name"])[1:],
                f"{network_name} attachment identity is inconsistent",
            )
            inspected_ip = _object(
                _docker_networks(container, str(container["Name"])).get(network_name),
                f"{network_name} inspected address",
            ).get("IPAddress")
            _require(
                isinstance(attachment.get("IPv4Address"), str)
                and attachment.get("IPv4Address", "").split("/", 1)[0] == inspected_ip,
                f"{network_name} attachment address is inconsistent",
            )
    topology = _object(
        _json_file(directory, "network-topology.json"), "network topology"
    )
    _require(
        topology.get("networks") == networks,
        "network summary differs from raw Docker inspection",
    )
    _require(
        topology.get("control_is_only_bridge") is True
        and topology.get("codex_payment_shared_networks") == []
        and topology.get("control_health_from_codex") == "reachable"
        and topology.get("direct_payment_by_name_from_codex") == "blocked"
        and topology.get("direct_payment_by_ip_from_codex") == "blocked",
        "network summary does not state the checked cut",
    )

    codex_config = _object(codex.get("Config"), "Codex configuration")
    codex_arguments = _list(codex_config.get("Cmd"), "Codex command arguments")
    entrypoint = _list(codex_config.get("Entrypoint"), "Codex entrypoint")
    _require(
        len(entrypoint) == 1 and str(entrypoint[0]).endswith("/bin/codex"),
        "Codex container did not execute the native vendor binary",
    )
    _require(
        isinstance(codex_config.get("User"), str)
        and re.fullmatch(r"[0-9]+:[0-9]+", codex_config.get("User", "")) is not None,
        "Codex container did not use a numeric UID/GID",
    )
    _require(
        codex_config.get("Hostname") == str(codex["Id"])[:12],
        "Codex hostname does not bind its inspected container ID",
    )
    codex_host = _object(codex.get("HostConfig"), "Codex host configuration")
    _require(
        codex_host.get("NetworkMode") == agent_network
        and codex_host.get("Tmpfs") == {"/tmp": "rw,nosuid,nodev,mode=1777"},
        "Codex primary network or temporary filesystem differs from the boundary",
    )
    codex_mounts = [
        _object(value, "Codex mount")
        for value in _list(codex.get("Mounts"), "Codex mounts")
    ]
    _require(len(codex_mounts) == 3, "Codex container has an unexpected mount")
    home_mounts = [
        mount
        for mount in codex_mounts
        if mount.get("Destination") == "/var/lib/safe-change/codex-home"
    ]
    _require(
        len(home_mounts) == 1 and home_mounts[0].get("RW") is True,
        "Codex home mount is absent or read-only",
    )
    readonly_mounts = [mount for mount in codex_mounts if mount.get("RW") is False]
    _require(len(readonly_mounts) == 2, "Codex workspace or vendor mount is writable")
    _require(
        codex_config.get("WorkingDir")
        in [mount.get("Destination") for mount in readonly_mounts],
        "Codex working directory is not a read-only mount",
    )

    post_values = _list(
        _json_file(directory, "control-after-restart-inspect.json"),
        "post-restart Docker inspection",
    )
    post = _inspect_object(
        _one(post_values, "post-restart control container"),
        "post-restart control container",
    )
    _require(
        post.get("Id") == control.get("Id"),
        "control restart inspected another container",
    )
    _check_container_hardening(post, "post-restart control")
    initial_state = _object(control.get("State"), "initial control state")
    post_state = _object(post.get("State"), "post-restart control state")
    _require(
        initial_state.get("Pid") != post_state.get("Pid"),
        "control process PID did not change",
    )
    initial_started = _rfc3339_nanoseconds(
        initial_state.get("StartedAt"), "initial control start"
    )
    post_started = _rfc3339_nanoseconds(
        post_state.get("StartedAt"), "post-restart control start"
    )
    _require(
        post_started > initial_started, "control Docker start time did not advance"
    )

    payment_network = _object(
        _docker_networks(payment, "payment").get(effects_network),
        "payment effects network",
    )
    payment_ip = payment_network.get("IPAddress")
    _require(
        isinstance(payment_ip, str)
        and re.fullmatch(r"(?:[0-9]{1,3}\.){3}[0-9]{1,3}", payment_ip) is not None,
        "Docker inspection omitted the payment IP",
    )
    codex_name = str(codex["Name"])[1:]
    probes = _list(_json_file(directory, "network-probes.json"), "network probes")
    _require(
        [probe.get("label") if isinstance(probe, dict) else None for probe in probes]
        == ["control-health", "payment-name", "payment-ip"],
        "network probes are incomplete or reordered",
    )
    urls = [
        "http://control:8787/healthz",
        "http://payment:8081/v1/stats",
        f"http://{payment_ip}:8081/v1/stats",
    ]
    prior_finish: int | None = None
    for index, (probe_value, url) in enumerate(zip(probes, urls, strict=True)):
        probe = _object(probe_value, f"network probe {index + 1}")
        expected_command = [
            "docker",
            "exec",
            codex_name,
            "wget",
            "-T",
            "2",
            "-qO-",
            url,
        ]
        _require(
            probe.get("command") == expected_command,
            "network probe command differs from the inspected Codex container",
        )
        started = probe.get("started_time_ns")
        finished = probe.get("finished_time_ns")
        _require(
            type(started) is int and type(finished) is int and 0 < started <= finished,
            "network probe timing is invalid",
        )
        if prior_finish is not None:
            _require(started >= prior_finish, "network probes overlap or are reordered")
        prior_finish = finished
        if index == 0:
            _require(
                probe.get("returncode") == 0, "positive control-health probe failed"
            )
            _require(
                _loads(str(probe.get("output", "")).encode(), "control probe output")
                == {"status": "ok"},
                "positive control-health probe returned another response",
            )
        else:
            _require(
                type(probe.get("returncode")) is int and probe.get("returncode") != 0,
                "direct payment probe unexpectedly succeeded",
            )

    teardown = _object(_json_file(directory, "teardown.json"), "teardown verdict")
    _require(
        teardown == {"compose_down_returncode": 0, "image_remove_returncode": 0},
        "deployment teardown did not remove the Compose project and image",
    )
    credential = _object(
        _json_file(directory, "credential-lifecycle.json"),
        "credential lifecycle",
    )
    _require(
        credential
        == {
            "host_source_modified": False,
            "temporary_auth_removed_before_effect": True,
        },
        "temporary Codex credential lifecycle is inconsistent",
    )
    return {
        "codex_id": str(codex["Id"]),
        "codex_arguments": codex_arguments,
        "codex_readonly_mounts": [
            str(mount.get("Destination")) for mount in readonly_mounts
        ],
        "control_pid_before": initial_state["Pid"],
        "control_pid_after": post_state["Pid"],
        "control_restart_time_ns": post_started,
        "network_probe_start_ns": probes[0]["started_time_ns"],
        "network_probe_finish_ns": probes[-1]["finished_time_ns"],
        "network_topology": topology,
    }


def _check_protocol(
    directory: Path,
    operation_id: str,
    remote_reference: str,
    run_id: str,
    codex_id: str,
    codex_arguments: list[Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    raw = _read(directory / "app-server.jsonl", limit=MAX_HISTORY_BYTES)
    lines = raw.splitlines()
    _require(
        lines and raw.endswith(b"\n"), "App Server protocol is empty or unterminated"
    )
    records = [
        _object(_loads(line, f"App Server line {index}"), "App Server record")
        for index, line in enumerate(lines, 1)
    ]
    _require(
        [record.get("sequence") for record in records]
        == list(range(1, len(records) + 1)),
        "App Server record sequence is not contiguous",
    )
    payloads = [(record.get("direction"), record.get("payload")) for record in records]
    starts = [
        payload
        for direction, payload in payloads
        if direction == "meta"
        and isinstance(payload, dict)
        and payload.get("event") == "process_start"
    ]
    start = _object(_one(starts, "App Server process start"), "process start")
    command = start.get("command")
    _require(
        isinstance(command, list) and "app-server" in command and "--stdio" in command,
        "process start is not a Codex App Server command",
    )
    _require(
        command[1:] == codex_arguments,
        "App Server process arguments differ from Docker inspection",
    )
    command_text = json.dumps(command, sort_keys=True)
    _require(
        "model_providers" not in command_text
        and "authority_continuity_mock" not in command_text,
        "App Server installed the deterministic test provider",
    )
    remote_status = [
        payload
        for direction, payload in payloads
        if direction == "server_to_client"
        and isinstance(payload, dict)
        and payload.get("method") == "remoteControl/status/changed"
    ]
    remote_params = _object(
        _one(remote_status, "remote-control status").get("params"),
        "remote-control status",
    )
    _require(
        remote_params.get("installationId") == "<redacted>"
        and remote_params.get("serverName") == codex_id[:12],
        "privacy-filtered App Server identity does not bind the Codex container",
    )
    rate_limits = [
        payload
        for direction, payload in payloads
        if direction == "server_to_client"
        and isinstance(payload, dict)
        and payload.get("method") == "account/rateLimits/updated"
    ]
    _require(len(rate_limits) >= 1, "App Server protocol omitted rate-limit notices")
    for notice in rate_limits:
        notice_params = _object(notice.get("params"), "rate-limit notice")
        _require(
            notice_params.get("rateLimits") == {"redacted": True},
            "App Server account telemetry was not privacy-filtered",
        )
    stops = [
        payload
        for direction, payload in payloads
        if direction == "meta"
        and isinstance(payload, dict)
        and payload.get("event") == "process_stop"
    ]
    stop = _object(_one(stops, "App Server process stop"), "process stop")
    _require(
        stop.get("returncode") == 0, "App Server process did not exit successfully"
    )

    thread_requests = [
        payload
        for direction, payload in payloads
        if direction == "client_to_server"
        and isinstance(payload, dict)
        and payload.get("method") == "thread/start"
    ]
    thread_request = _object(
        _one(thread_requests, "thread/start request"), "thread/start"
    )
    thread_params = _object(thread_request.get("params"), "thread/start params")
    tools = _list(thread_params.get("dynamicTools"), "dynamic tools")
    _require(
        len(tools) == 1 and _object(tools[0], "dynamic tool").get("name") == TOOL_NAME,
        "thread exposed a tool other than protected_payment",
    )
    dynamic_tool = _object(tools[0], "dynamic tool")
    _require(
        dynamic_tool.get("inputSchema")
        == {
            "additionalProperties": False,
            "properties": {"effect_id": {"enum": [EFFECT_ID], "type": "string"}},
            "required": ["effect_id"],
            "type": "object",
        },
        "protected_payment schema does not freeze the application identity",
    )
    _require(
        thread_params.get("approvalPolicy") == "never"
        and thread_params.get("sandbox") == "read-only",
        "thread request weakened its local boundary",
    )
    thread_responses = [
        payload
        for direction, payload in payloads
        if direction == "server_to_client"
        and isinstance(payload, dict)
        and payload.get("id") == thread_request.get("id")
        and isinstance(payload.get("result"), dict)
    ]
    thread_result = _object(
        _one(thread_responses, "thread/start response").get("result"), "thread result"
    )
    thread = _object(thread_result.get("thread"), "thread")
    thread_id = thread.get("id")
    sandbox = _object(thread_result.get("sandbox"), "thread sandbox")
    _require(
        isinstance(thread_id, str) and thread_id, "thread response omitted its identity"
    )
    _require(
        thread_result.get("approvalPolicy") == "never",
        "thread response changed approval policy",
    )
    _require(
        sandbox == {"networkAccess": False, "type": "readOnly"},
        "thread response changed sandbox boundary",
    )
    model = thread_result.get("model")
    provider = thread_result.get("modelProvider")
    _require(isinstance(model, str) and model, "thread response omitted model")
    _require(
        isinstance(provider, str)
        and provider
        and provider != "authority_continuity_mock",
        "thread response used a mock model provider",
    )

    turn_requests = [
        payload
        for direction, payload in payloads
        if direction == "client_to_server"
        and isinstance(payload, dict)
        and payload.get("method") == "turn/start"
    ]
    turn_request = _object(_one(turn_requests, "turn/start request"), "turn/start")
    turn_params = _object(turn_request.get("params"), "turn/start params")
    _require(turn_params.get("threadId") == thread_id, "turn belongs to another thread")
    expected_prompt = (
        f"Experiment {run_id}: call {TOOL_NAME} exactly once with effect_id "
        f"{EFFECT_ID}. After it returns, reply exactly DONE."
    )
    _require(
        turn_params.get("input") == [{"text": expected_prompt, "type": "text"}],
        "turn prompt is not bound to the retained experiment",
    )
    turn_responses = [
        payload
        for direction, payload in payloads
        if direction == "server_to_client"
        and isinstance(payload, dict)
        and payload.get("id") == turn_request.get("id")
        and isinstance(payload.get("result"), dict)
    ]
    turn_result = _object(
        _one(turn_responses, "turn/start response").get("result"), "turn result"
    )
    turn_id = _object(turn_result.get("turn"), "turn").get("id")
    _require(isinstance(turn_id, str) and turn_id, "turn response omitted its identity")

    allowed_item_types = {
        "agentMessage",
        "dynamicToolCall",
        "reasoning",
        "userMessage",
    }
    for direction, payload in payloads:
        if direction != "server_to_client" or not isinstance(payload, dict):
            continue
        if payload.get("method") not in {"item/started", "item/completed"}:
            continue
        params_value = payload.get("params")
        item = params_value.get("item") if isinstance(params_value, dict) else None
        if isinstance(item, dict):
            _require(
                item.get("type") in allowed_item_types,
                f"App Server used an undeclared built-in item {item.get('type')!r}",
            )

    tool_calls = [
        payload
        for direction, payload in payloads
        if direction == "server_to_client"
        and isinstance(payload, dict)
        and payload.get("method") == "item/tool/call"
    ]
    tool_call = _object(_one(tool_calls, "tool callback"), "tool callback")
    tool_records = [
        record
        for record in records
        if record.get("direction") == "server_to_client"
        and isinstance(record.get("payload"), dict)
        and record.get("payload", {}).get("method") == "item/tool/call"
    ]
    tool_record = _object(_one(tool_records, "tool callback record"), "tool record")
    params = _object(tool_call.get("params"), "tool callback params")
    provider_call_id = params.get("callId")
    _require(
        params.get("threadId") == thread_id
        and params.get("turnId") == turn_id
        and params.get("tool") == TOOL_NAME
        and params.get("arguments") == {"effect_id": EFFECT_ID}
        and isinstance(provider_call_id, str),
        "Codex tool callback identity or arguments are inconsistent",
    )
    callbacks = [
        payload
        for direction, payload in payloads
        if direction == "client_to_server"
        and isinstance(payload, dict)
        and payload.get("id") == tool_call.get("id")
        and isinstance(payload.get("result"), dict)
    ]
    callback = _object(
        _one(callbacks, "tool callback response").get("result"), "tool callback result"
    )
    callback_records = [
        record
        for record in records
        if record.get("direction") == "client_to_server"
        and isinstance(record.get("payload"), dict)
        and record.get("payload", {}).get("id") == tool_call.get("id")
        and isinstance(record.get("payload", {}).get("result"), dict)
    ]
    callback_record = _object(
        _one(callback_records, "tool callback response record"), "callback record"
    )
    items = _list(callback.get("contentItems"), "tool callback content")
    _require(
        callback.get("success") is True and len(items) == 1,
        "tool callback was not one success result",
    )
    callback_text = _object(items[0], "tool callback item").get("text")
    _require(isinstance(callback_text, str), "tool callback omitted text")
    callback_value = _object(
        _loads(callback_text.encode(), "tool callback text"), "tool callback text"
    )
    _require(
        callback_value
        == {
            "effect_id": EFFECT_ID,
            "remote_reference": remote_reference,
            "status": "succeeded",
        },
        "tool callback was not bound to the durable payment receipt",
    )

    completed_items = [
        payload.get("params", {}).get("item")
        for direction, payload in payloads
        if direction == "server_to_client"
        and isinstance(payload, dict)
        and payload.get("method") == "item/completed"
        and isinstance(payload.get("params"), dict)
        and payload.get("params", {}).get("threadId") == thread_id
        and payload.get("params", {}).get("turnId") == turn_id
    ]
    completed_tools = [
        item
        for item in completed_items
        if isinstance(item, dict) and item.get("type") == "dynamicToolCall"
    ]
    completed_tool = _object(
        _one(completed_tools, "completed dynamic tool"), "completed dynamic tool"
    )
    _require(
        completed_tool.get("id") == provider_call_id
        and completed_tool.get("success") is True
        and completed_tool.get("status") == "completed",
        "dynamic tool completion is inconsistent",
    )
    final_messages = [
        item
        for item in completed_items
        if isinstance(item, dict)
        and item.get("type") == "agentMessage"
        and item.get("phase") == "final_answer"
    ]
    final_message = _object(
        _one(final_messages, "final agent message"), "final agent message"
    )
    _require(
        final_message.get("text") == "DONE", "Codex final answer differs from DONE"
    )
    completions = [
        payload
        for direction, payload in payloads
        if direction == "server_to_client"
        and isinstance(payload, dict)
        and payload.get("method") == "turn/completed"
        and payload.get("params", {}).get("threadId") == thread_id
        and payload.get("params", {}).get("turn", {}).get("id") == turn_id
    ]
    completed_turn = _object(
        _one(completions, "turn completion").get("params", {}).get("turn"),
        "completed turn",
    )
    _require(
        completed_turn.get("status") == "completed"
        and completed_turn.get("error") is None,
        "Codex turn did not complete successfully",
    )
    summary = {
        "raw_records": len(records),
        "real_app_server_process": True,
        "custom_model_provider_installed": False,
        "model": model,
        "model_provider": provider,
        "sandbox_network_access": False,
        "sandbox_type": "readOnly",
        "approval_policy": "never",
        "dynamic_tool_calls": 1,
        "callback_responses": 1,
        "completed_turns": 1,
        "final_agent_message": "DONE",
        "thread_id": thread_id,
        "turn_id": turn_id,
        "provider_call_id": provider_call_id,
    }
    timing = {
        "tool_call_time_ns": tool_record.get("time_ns"),
        "callback_response_time_ns": callback_record.get("time_ns"),
        "thread_cwd": thread_result.get("cwd"),
        "process_command": command,
    }
    _require(
        type(timing["tool_call_time_ns"]) is int
        and type(timing["callback_response_time_ns"]) is int
        and timing["tool_call_time_ns"] < timing["callback_response_time_ns"],
        "App Server callback timing is invalid",
    )
    return summary, timing


def _check_certificate(directory: Path, runtime_dir: Path | None) -> dict[str, Any]:
    saved = _object(
        _json_file(directory, "checker-verdict.json"), "saved Certificate verdict"
    )
    if runtime_dir is None:
        return saved
    completed = subprocess.run(
        [
            "go",
            "run",
            "./cmd/check-certificate",
            "-state",
            os.fspath((directory / "certificate-state.json").resolve()),
            "-certificate",
            os.fspath((directory / "certificate.json").resolve()),
        ],
        cwd=runtime_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=120.0,
        check=False,
    )
    _require(
        completed.returncode == 0,
        "standalone Certificate checker rejected retained inputs",
    )
    fresh = _object(
        _loads(completed.stdout, "fresh Certificate verdict"),
        "fresh Certificate verdict",
    )
    _require(
        fresh == saved, "fresh Certificate verdict differs from the retained verdict"
    )
    return fresh


def check_evidence(
    directory: Path, *, runtime_dir: Path | None = None
) -> dict[str, Any]:
    """Verify one evidence directory and return a newly derived verdict."""

    directory = directory.resolve(strict=True)
    _require(directory.is_dir(), "evidence path is not a directory")
    operation_id = _operation_id()
    remote_reference = "payment/" + operation_id

    requirement = _object(_json_file(directory, "requirement.json"), "Requirement")
    requirement_id = requirement.get("id")
    requirement_prefix = "codex-payment-isolated-v1/"
    _require(
        isinstance(requirement_id, str)
        and requirement_id.startswith(requirement_prefix),
        "Requirement identity does not contain an experiment identity",
    )
    run_id = str(requirement_id)[len(requirement_prefix) :]
    _require(RUN_ID.fullmatch(run_id) is not None, "experiment identity is invalid")
    expected_kind = {
        "costs": {"charge": 1},
        "method": "POST",
        "produces": {"paid": 1},
        "queryable": False,
        "response_classifier": "operation-receipt-v1",
        "retry_safe": True,
        "target": PAYMENT_TARGET,
    }
    _require(
        requirement
        == {
            "capacities": {"charge": 1},
            "id": requirement_prefix + run_id,
            "kinds": {OPERATION_KIND: expected_kind},
            "results": {"paid": 1},
        },
        "Requirement differs from the isolated payment contract",
    )
    certificate = _object(_json_file(directory, "certificate.json"), "Certificate")
    certificate_state = _object(
        _json_file(directory, "certificate-state.json"), "Certificate state"
    )
    _require(
        certificate.get("decision") == "activate"
        and certificate.get("requirement") == requirement,
        "Certificate does not activate the retained Requirement",
    )
    _require(
        certificate.get("history") == {"hash": ZERO_HASH, "sequence": 0},
        "Certificate is not bound to the empty History",
    )
    rule = _object(certificate.get("rule"), "Certificate Rule")
    _require(
        rule.get("version") == 1 and rule.get("allow") == [OPERATION_KIND],
        "Certificate Rule differs from version 1",
    )
    _require(
        certificate_state
        == {
            "from_rule": 0,
            "history": {"hash": ZERO_HASH, "sequence": 0},
            "open_operations": {},
            "schema": 1,
            "settled": {"results": {}, "used": {}},
        },
        "Certificate state is not the claimed pre-activation state",
    )
    certificate_verdict = _check_certificate(directory, runtime_dir)
    _require(
        certificate_verdict.get("valid") is True
        and certificate_verdict.get("decision") == "activate"
        and certificate_verdict.get("history_sequence") == 0
        and certificate_verdict.get("history_hash") == ZERO_HASH
        and certificate_verdict.get("rule_version") == 1,
        "standalone Certificate verdict does not validate activation",
    )

    docker = _check_docker_evidence(directory, run_id)

    events = _replay_history(directory / "runtime.history")
    retained_events = _list(_json_file(directory, "history.json"), "History endpoint")
    _require(
        retained_events == events, "History endpoint differs from binary History replay"
    )
    _require(
        [event["operation"] for event in events]
        == [
            "rule.activated",
            "operation.prepared",
            "operation.phase",
            "operation.phase",
            "operation.phase",
            "operation.phase",
        ],
        "History does not contain the required six-event recovery",
    )
    _require(
        events[0]["data"] == {"certificate": certificate, "semantic_version": 1},
        "activation event differs from the checked Certificate",
    )
    prepared = _object(events[1]["data"].get("operation"), "prepared Operation")
    _require(
        prepared.get("id") == operation_id
        and prepared.get("domain") == OPERATION_DOMAIN
        and prepared.get("kind") == OPERATION_KIND
        and prepared.get("phase") == "prepared"
        and prepared.get("target") == PAYMENT_TARGET,
        "prepared Operation identity or contract is inconsistent",
    )
    updates = [
        _object(event["data"].get("update"), "Operation update") for event in events[2:]
    ]
    _require(
        [update.get("phase") for update in updates]
        == ["dispatched", "unknown", "dispatched", "succeeded"],
        "History phase recovery is inconsistent",
    )
    _require(
        updates[0].get("dispatch_generation") == 1
        and updates[2].get("dispatch_generation") == 2,
        "dispatch generations do not prove a restarted recovery",
    )
    first_owner = updates[0].get("dispatch_owner")
    second_owner = updates[2].get("dispatch_owner")
    _require(
        isinstance(first_owner, str)
        and isinstance(second_owner, str)
        and first_owner != second_owner,
        "control restart did not change dispatch ownership",
    )
    head = events[-1]
    _check_anchor(directory, head["sequence"], head["hash"])

    payment_body = json.dumps(
        {
            "amount": 42,
            "experiment_id": run_id,
            "order_id": EFFECT_ID,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    payment_lines = _read(directory / "payment.history").splitlines()
    payment = _object(
        _loads(_one(payment_lines, "durable payment record"), "payment record"),
        "payment record",
    )
    payment_result_hash = sha256(b"charged\x00" + operation_id.encode()).hexdigest()
    payment_request_hash = sha256(b"POST\x00/v1/charge\x00" + payment_body).hexdigest()
    _require(
        payment
        == {
            "operation_id": operation_id,
            "request_hash": payment_request_hash,
            "result_hash": payment_result_hash,
            "remote_reference": remote_reference,
            "path": "/v1/charge",
        },
        "durable payment record is not bound to the stable Operation",
    )
    stats = _object(_json_file(directory, "payment-stats.json"), "payment stats")
    _require(
        stats == {"commits": 1, "deliveries": 2, "paths": {"/v1/charge": 2}},
        "payment did not record two deliveries and one commit",
    )

    first = _object(_json_file(directory, "first-outcome.json"), "first outcome")
    first_outcome = _object(first.get("outcome"), "first outcome body")
    _require(
        first_outcome
        == {
            "operation_id": operation_id,
            "phase": "unknown",
            "result_hash": "",
            "reused": False,
        },
        "lost response did not leave exactly one unknown Operation",
    )
    recovered = _object(
        _json_file(directory, "recovered-outcome.json"), "recovered outcome"
    )
    reused = _object(_json_file(directory, "reused-outcome.json"), "reused outcome")
    _require(
        recovered.get("operation_id") == operation_id
        and recovered.get("phase") == "succeeded"
        and recovered.get("reused") is False
        and recovered.get("status_code") == 200,
        "recovered outcome is inconsistent",
    )
    expected_reused = dict(recovered)
    expected_reused["reused"] = True
    _require(
        reused == expected_reused,
        "settled retry did not reuse the exact recovered bytes",
    )
    encoded_body = recovered.get("body")
    _require(isinstance(encoded_body, str), "recovered outcome omitted body")
    try:
        receipt_bytes = base64.b64decode(encoded_body, validate=True)
    except ValueError as error:
        raise EvidenceError("recovered receipt is not canonical base64") from error
    receipt = _object(_loads(receipt_bytes, "payment receipt"), "payment receipt")
    _require(
        receipt
        == {
            "operation_id": operation_id,
            "outcome": "succeeded",
            "remote_reference": remote_reference,
            "result_hash": payment_result_hash,
            "schema": 1,
        },
        "payment receipt is not bound to the durable record",
    )
    gateway_result_hash = sha256(b"200\x00" + receipt_bytes).hexdigest()
    _require(
        recovered.get("result_hash") == gateway_result_hash,
        "gateway result hash does not cover the retained receipt bytes",
    )

    headers = {
        "accept-encoding": "identity",
        "content-type": "application/json",
        "idempotency-key": operation_id,
        "user-agent": "safe-change-runtime/1",
        "x-operation-id": operation_id,
    }
    request_digest = sha256()
    request_digest.update(b"POST\x00" + PAYMENT_TARGET.encode() + b"\x00")
    for name, value in sorted(headers.items()):
        request_digest.update(name.encode() + b":" + value.encode() + b"\x00")
    request_digest.update(payment_body)
    _require(
        prepared.get("request_hash") == request_digest.hexdigest(),
        "prepared request hash does not cover the protected HTTP request",
    )

    state = _object(_json_file(directory, "final-state.json"), "final state")
    _require(
        state.get("history") == {"hash": head["hash"], "sequence": head["sequence"]},
        "final state is not at the replayed History head",
    )
    operation = _object(
        _object(state.get("operations"), "final Operations").get(operation_id),
        "final Operation",
    )
    _require(
        operation.get("phase") == "succeeded"
        and operation.get("dispatch_generation") == 2
        and operation.get("dispatch_owner") == second_owner
        and operation.get("domain") == OPERATION_DOMAIN
        and operation.get("kind") == OPERATION_KIND
        and operation.get("request_hash") == prepared.get("request_hash")
        and operation.get("result_hash") == gateway_result_hash
        and operation.get("result_body") == encoded_body
        and operation.get("remote_reference") == remote_reference,
        "final Operation differs from History, request, or payment receipt",
    )
    succeeded_update = updates[-1]
    _require(
        succeeded_update.get("result_hash") == gateway_result_hash
        and succeeded_update.get("result_body") == encoded_body
        and succeeded_update.get("remote_reference") == remote_reference,
        "settled History event differs from the recovered outcome",
    )
    active = _object(_json_file(directory, "active-state.json"), "active state")
    _require(
        active.get("history") == {"hash": events[0]["hash"], "sequence": 1}
        and active.get("operations") == {},
        "active state was not captured immediately after Rule activation",
    )

    topology = docker["network_topology"]
    protocol, protocol_timing = _check_protocol(
        directory,
        operation_id,
        remote_reference,
        run_id,
        docker["codex_id"],
        docker["codex_arguments"],
    )
    _require(
        protocol_timing["thread_cwd"] in docker["codex_readonly_mounts"],
        "App Server workspace is not one of the inspected read-only mounts",
    )
    _require(
        protocol_timing["tool_call_time_ns"]
        <= docker["network_probe_start_ns"]
        <= docker["network_probe_finish_ns"]
        < docker["control_restart_time_ns"]
        < protocol_timing["callback_response_time_ns"],
        "raw clocks do not place network checks and control restart inside the pending callback",
    )
    result = _object(_json_file(directory, "result.json"), "runner result")
    evidence_name = result.get("evidence_directory")
    _require(
        result.get("run_id") == run_id
        and isinstance(evidence_name, str)
        and evidence_name not in {"", ".", ".."}
        and "/" not in evidence_name,
        "runner result belongs to another experiment or exposes a host path",
    )
    _require(
        result.get("protocol") == protocol,
        "runner protocol summary differs from raw App Server records",
    )
    _require(
        result.get("network") == topology,
        "runner network summary differs from retained topology",
    )
    _require(
        result.get("operation")
        == {
            "first_result": "unknown",
            "operation_id": operation_id,
            "recovered_result": "succeeded",
            "settled_retry_reused": True,
        },
        "runner Operation summary is inconsistent",
    )
    _require(
        result.get("payment") == {"deliveries": 2, "durable_commits": 1},
        "runner payment summary is inconsistent",
    )
    fault = _object(result.get("fault"), "runner fault summary")
    _require(
        fault.get("control_pid_before") == docker["control_pid_before"]
        and fault.get("control_pid_after") == docker["control_pid_after"]
        and fault.get("control_restarted_while_callback_pending") is True,
        "runner fault summary differs from raw Docker process replacement",
    )
    codex = _object(result.get("codex"), "runner Codex summary")
    _require(
        codex.get("real_app_server") is True
        and codex.get("model") == protocol["model"]
        and codex.get("model_provider") == protocol["model_provider"]
        and isinstance(codex.get("login_status"), str)
        and codex.get("login_status", "").startswith("Logged in")
        and isinstance(codex.get("version"), str)
        and codex.get("version", "").startswith("codex-cli "),
        "runner Codex summary does not identify a logged-in real App Server",
    )
    _hash(codex.get("native_binary_sha256"), "Codex native binary hash")

    return {
        "valid": True,
        "operation_id": operation_id,
        "certificate_valid": True,
        "history_sequence": head["sequence"],
        "history_hash": head["hash"],
        "history_chain_replayed": True,
        "external_head_valid": True,
        "payment_deliveries": 2,
        "payment_commits": 1,
        "codex_protocol_records": protocol["raw_records"],
        "codex_tool_calls": 1,
        "control_process_replaced": True,
        "callback_restart_order_valid": True,
        "network_cut_attested": True,
        "run_id": run_id,
    }


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".next")
    temporary.write_text(
        json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--runtime-dir", type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_args(argv)
    runtime_dir = arguments.runtime_dir
    if runtime_dir is not None:
        runtime_dir = runtime_dir.resolve(strict=True)
    verdict = check_evidence(arguments.evidence, runtime_dir=runtime_dir)
    if arguments.output is not None:
        _write_json(arguments.output, verdict)
    print(json.dumps(verdict, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["EvidenceError", "check_evidence"]
