"""Run the deterministic Codex preflight through one Firecracker restore.

This is an explicit real-KVM entry point.  It keeps the ordinary Codex
App Server boundary: :func:`adapter.test_app_server.run_preflight` sees only a
temporary ``codex`` executable, while that executable fixes the host-owned VM
artifacts and delegates to ``firecracker-codex-shim``.

Stdout is reserved for one compact, non-secret result locator.  The App Server
JSONL stream and all Firecracker evidence remain in caller-supplied private
directories.
"""

from __future__ import annotations

import argparse
import base64
from hashlib import sha256
import http.client
import json
import os
from pathlib import Path
import secrets
import socket
import stat
import sys
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from adapter.app_server import MCPStdioServer
from adapter.firecracker_codex import create_firecracker_codex
from adapter.test_app_server import PreflightResult, run_preflight


RESULT_SCHEMA = 1
_MAX_RUNTIME_RESULT_BYTES = 8 << 20
_MAX_CONTROL_RESPONSE_BYTES = 4 << 20
_MAX_WORKSPACE_PATCH_BYTES = 1 << 20
_MAX_WORKSPACE_VALIDATION_COMMAND_BYTES = 64 << 10
_WORKSPACE_VALIDATION_SHELL = "/opt/codex/bin/sh"
_GUEST_MCP_RELAY = "/opt/codex/bin/mcp-operation-relay"
_GUEST_MCP_PORT = 7002
_CONTROL_CHARACTERS = frozenset(chr(value) for value in range(32)) | {chr(127)}


class DemoError(RuntimeError):
    """The opt-in Firecracker preflight failed a local contract check."""


def _digest(value: str, label: str) -> str:
    if (
        len(value) != 64
        or value != value.lower()
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise DemoError(f"{label} must be one lowercase SHA-256 digest")
    return value


def _canonical_existing(value: Path, label: str) -> tuple[Path, os.stat_result]:
    raw = os.fspath(value)
    if (
        not raw
        or not os.path.isabs(raw)
        or os.path.normpath(raw) != raw
        or any(character in _CONTROL_CHARACTERS for character in raw)
    ):
        raise DemoError(f"{label} must be an absolute canonical path")
    try:
        info = value.lstat()
        resolved = value.resolve(strict=True)
    except OSError as error:
        raise DemoError(f"cannot inspect {label}: {value}") from error
    if stat.S_ISLNK(info.st_mode) or resolved != value:
        raise DemoError(f"{label} must not be or traverse a symlink")
    return resolved, info


def _directory(
    value: Path,
    label: str,
    *,
    private: bool,
    empty: bool,
) -> Path:
    path, info = _canonical_existing(value, label)
    if not stat.S_ISDIR(info.st_mode):
        raise DemoError(f"{label} must be a real directory")
    if private:
        if stat.S_IMODE(info.st_mode) != 0o700:
            raise DemoError(f"{label} must have mode 0700")
        if info.st_uid != os.geteuid():
            raise DemoError(f"{label} must be owned by the current user")
    if empty:
        with os.scandir(path) as entries:
            if next(entries, None) is not None:
                raise DemoError(f"{label} must be empty")
    return path


def _verified_artifact(
    value: Path,
    expected_sha256: str,
    label: str,
    *,
    executable: bool,
) -> tuple[Path, dict[str, Any]]:
    path, initial = _canonical_existing(value, label)
    if not stat.S_ISREG(initial.st_mode) or initial.st_size <= 0:
        raise DemoError(f"{label} must be a nonempty regular file")
    if executable and initial.st_mode & 0o111 == 0:
        raise DemoError(f"{label} must be executable")
    expected = _digest(expected_sha256, f"{label}_sha256")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise DemoError(f"cannot open {label}: {path}") from error
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or (
            opened.st_dev,
            opened.st_ino,
        ) != (initial.st_dev, initial.st_ino):
            raise DemoError(f"{label} changed while it was opened")
        digest = sha256()
        size = 0
        while block := os.read(descriptor, 1 << 20):
            digest.update(block)
            size += len(block)
    finally:
        os.close(descriptor)
    current = path.lstat()
    if (current.st_dev, current.st_ino, current.st_size) != (
        initial.st_dev,
        initial.st_ino,
        initial.st_size,
    ):
        raise DemoError(f"{label} changed while it was hashed")
    actual = digest.hexdigest()
    if actual != expected:
        raise DemoError(f"{label} SHA-256 is {actual}, require {expected}")
    return path, {"path": os.fspath(path), "sha256": actual, "size": size}


def _paths_overlap(first: Path, second: Path) -> bool:
    return first == second or first in second.parents or second in first.parents


def _require_pairwise_disjoint(paths: Mapping[str, Path]) -> None:
    items = list(paths.items())
    for index, (first_label, first) in enumerate(items):
        for second_label, second in items[index + 1 :]:
            if _paths_overlap(first, second):
                raise DemoError(
                    f"{first_label} and {second_label} paths must not overlap"
                )


def _fingerprint_private_file(path: Path, label: str) -> dict[str, Any]:
    resolved, info = _canonical_existing(path, label)
    if not stat.S_ISREG(info.st_mode) or info.st_size <= 0:
        raise DemoError(f"{label} must be a nonempty regular file")
    if stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != os.geteuid():
        raise DemoError(f"{label} must be a current-user file with mode 0600")
    digest = sha256()
    with resolved.open("rb") as source:
        while block := source.read(1 << 20):
            digest.update(block)
    return {
        "path": os.fspath(resolved),
        "sha256": digest.hexdigest(),
        "size": info.st_size,
    }


def _read_private_token(path: Path, label: str) -> str:
    resolved, info = _canonical_existing(path, label)
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_uid != os.geteuid()
        or info.st_size < 32
        or info.st_size > 4096
    ):
        raise DemoError(f"{label} must be a private current-user token file")
    try:
        value = resolved.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as error:
        raise DemoError(f"cannot read {label}") from error
    if len(value) < 32 or any(character.isspace() for character in value):
        raise DemoError(f"{label} contains an invalid token")
    return value


def _sandbox_socket_path(value: Path) -> Path:
    raw = os.fspath(value)
    if (
        not raw
        or not os.path.isabs(raw)
        or os.path.normpath(raw) != raw
        or len(os.fsencode(raw)) >= 108
        or any(character in _CONTROL_CHARACTERS for character in raw)
    ):
        raise DemoError("sandbox_socket must be an absolute canonical Unix socket path")
    parent = value.parent
    try:
        parent_info = parent.lstat()
        resolved_parent = parent.resolve(strict=True)
    except OSError as error:
        raise DemoError("cannot inspect sandbox_socket parent") from error
    if (
        not stat.S_ISDIR(parent_info.st_mode)
        or stat.S_ISLNK(parent_info.st_mode)
        or resolved_parent != parent
        or stat.S_IMODE(parent_info.st_mode) != 0o700
        or parent_info.st_uid != os.geteuid()
    ):
        raise DemoError("sandbox_socket parent must be a private current-user directory")
    return value


def _verify_sandbox_socket(path: Path) -> None:
    try:
        info = path.lstat()
    except OSError as error:
        raise DemoError("sandbox endpoint was not published") from error
    if (
        not stat.S_ISSOCK(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_uid != os.geteuid()
    ):
        raise DemoError("sandbox endpoint is not a private current-user Unix socket")


class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: Path) -> None:
        super().__init__("localhost", timeout=45.0)
        self._socket_path = os.fspath(socket_path)

    def connect(self) -> None:
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.settimeout(self.timeout)
        try:
            connection.connect(self._socket_path)
        except BaseException:
            connection.close()
            raise
        self.sock = connection


def _post_sandbox_json(socket_path: Path, value: Mapping[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(
        dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    connection = _UnixHTTPConnection(socket_path)
    try:
        connection.request(
            "POST",
            "/v1/execute",
            body=encoded,
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        body = response.read(_MAX_CONTROL_RESPONSE_BYTES + 1)
        status = response.status
    except (OSError, http.client.HTTPException) as error:
        raise DemoError("sandbox Operation request failed") from error
    finally:
        connection.close()
    if len(body) > _MAX_CONTROL_RESPONSE_BYTES:
        raise DemoError(
            f"sandbox Operation request returned HTTP {status}: "
            + body[:1024].decode("utf-8", "replace")
        )
    try:
        result = json.loads(body)
    except json.JSONDecodeError as error:
        raise DemoError("sandbox Operation response is not valid JSON") from error
    if not isinstance(result, dict):
        raise DemoError("sandbox Operation response is not an object")
    if status == 200:
        return result
    if status == 409 and result.get("code") == "outcome_unknown":
        outcome = result.get("outcome")
        if not isinstance(outcome, dict):
            raise DemoError("unknown Operation response omitted durable progress")
        return {**outcome, "outcome_unknown": True}
    raise DemoError(
        f"sandbox Operation request returned HTTP {status}: "
        + body[:1024].decode("utf-8", "replace")
    )


def _loopback_url(value: str, label: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError as error:
        raise DemoError(f"{label} is not a URL") from error
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise DemoError(f"{label} must be one credential-free loopback HTTP origin")
    return value.rstrip("/")


def _post_json(origin: str, token: str, path: str, value: Mapping[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(
        dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    request = Request(
        origin + path,
        data=encoded,
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open(request, timeout=45.0) as response:
            body = response.read(_MAX_CONTROL_RESPONSE_BYTES + 1)
            status = response.status
    except HTTPError as error:
        detail = error.read(_MAX_CONTROL_RESPONSE_BYTES + 1)
        raise DemoError(
            f"control request {path} returned HTTP {error.code}: "
            + detail[:1024].decode("utf-8", "replace")
        ) from error
    except (OSError, URLError) as error:
        raise DemoError(f"control request {path} failed") from error
    if status != 200 or len(body) > _MAX_CONTROL_RESPONSE_BYTES:
        raise DemoError(f"control request {path} returned an invalid response")
    try:
        result = json.loads(body)
    except json.JSONDecodeError as error:
        raise DemoError(f"control request {path} returned invalid JSON") from error
    if not isinstance(result, dict):
        raise DemoError(f"control request {path} did not return an object")
    return result


def _requirement(
    identifier: str,
    payment_url: str,
    *,
    operation_count: int = 1,
    queryable: bool = False,
) -> dict[str, Any]:
    if not 1 <= operation_count <= 8:
        raise DemoError("Requirement must admit 1 to 8 protected operations")
    kind = {
        "costs": {"external-write": 1},
        "produces": {"callback-committed": 1},
        "retry_safe": not queryable,
        "queryable": queryable,
        "target": payment_url + "/v1/charge",
        "method": "POST",
        "response_classifier": "operation-receipt-v1",
    }
    if queryable:
        kind.update(
            {
                "query_target": payment_url + "/v1/query",
                "query_method": "POST",
                "query_classifier": "operation-observation-v1",
            }
        )
    return {
        "id": identifier,
        "results": {"callback-committed": operation_count},
        "capacities": {"external-write": operation_count},
        "kinds": {"protected_commit": kind},
    }


def _binding(host_instance_id: str, generation: int, repository_root: str) -> dict[str, Any]:
    return {
        "sandbox_id": "firecracker-codex",
        "generation": generation,
        "host_instance_id": host_instance_id,
        "domain": "firecracker-codex-vm",
        "allowed_kinds": ["protected_commit"],
        "repository_root": repository_root,
    }


def _read_runtime_result(
    path: Path,
    *,
    runner_sha256: str,
    codex_sha256: str,
    workspace: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    fingerprint = _fingerprint_private_file(path, "runtime result")
    if fingerprint["size"] > _MAX_RUNTIME_RESULT_BYTES:
        raise DemoError("runtime result exceeds the size limit")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as error:
        raise DemoError("runtime result is not valid JSON") from error
    if not isinstance(value, dict):
        raise DemoError("runtime result is not a JSON object")
    mapping = value.get("workspace_mapping")
    artifacts = value.get("artifacts")
    runner = artifacts.get("runner") if isinstance(artifacts, dict) else None
    if (
        value.get("schema") != 1
        or value.get("success") is not True
        or value.get("runner_sha256") != runner_sha256
        or value.get("codex_sha256") != codex_sha256
        or not isinstance(runner, dict)
        or runner.get("name") != "runner"
        or runner.get("sha256") != runner_sha256
        or not isinstance(runner.get("size"), int)
        or runner["size"] <= 0
        or runner.get("mode") != 0o600
        or not isinstance(mapping, dict)
        or mapping.get("host") != os.fspath(workspace)
        or mapping.get("guest") != "/workspace"
    ):
        raise DemoError("runtime result does not describe the requested successful run")
    session_id = value.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        raise DemoError("runtime result omitted its session identity")
    return value, fingerprint


def _write_exclusive_json(path: Path, value: Mapping[str, Any]) -> None:
    encoded = json.dumps(
        dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8") + b"\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as error:
        raise DemoError(f"cannot publish result: {path}") from error
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as destination:
            destination.write(encoded)
            destination.flush()
            os.fsync(destination.fileno())
    except BaseException:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def _preflight_record(result: PreflightResult) -> dict[str, Any]:
    if not result.ok or not result.seed_archived:
        raise DemoError("deterministic App Server preflight did not complete safely")
    record = {
        "ok": True,
        "seed_thread_id": result.seed_thread_id,
        "seed_turn_id": result.seed_turn_id,
        "fork_thread_id": result.fork_thread_id,
        "protected_turn_id": result.protected_turn_id,
        "call_id": result.call_id,
        "effect_id": result.effect_id,
        "seed_archived": result.seed_archived,
        "responses_request_count": result.responses_request_count,
        "models_request_count": result.models_request_count,
        "raw_record_count": result.raw_record_count,
    }
    if result.protected_calls:
        record["protected_calls"] = [
            {
                "request_id": item.request_id,
                "call_id": item.call_id,
                "effect_id": item.effect_id,
            }
            for item in result.protected_calls
        ]
    if result.workspace_edit_call_id is not None:
        if result.workspace_patch_sha256 is None:
            raise DemoError("workspace edit omitted its patch identity")
        record["workspace_edit_call_id"] = result.workspace_edit_call_id
        record["workspace_patch_sha256"] = _digest(
            result.workspace_patch_sha256, "workspace_patch_sha256"
        )
    if result.workspace_validation_call_id is not None:
        if result.workspace_validation_command_sha256 is None:
            raise DemoError("workspace validation omitted its command identity")
        record["workspace_validation_call_id"] = result.workspace_validation_call_id
        record["workspace_validation_command_sha256"] = _digest(
            result.workspace_validation_command_sha256,
            "workspace_validation_command_sha256",
        )
    return record


def run_demo(
    *,
    runner: Path,
    runner_sha256: str,
    firecracker: Path,
    firecracker_sha256: str,
    kernel: Path,
    kernel_sha256: str,
    guest: Path,
    guest_sha256: str,
    payload: Path,
    payload_sha256: str,
    repository: Path,
    repository_sha256: str,
    codex_sha256: str,
    runtime_evidence: Path,
    adapter_evidence: Path,
    workspace: Path,
    control_url: str | None = None,
    admin_token_file: Path | None = None,
    sandbox_socket: Path | None = None,
    payment_url: str | None = None,
    repository_tree_root: str | None = None,
    workspace_patch: str | None = None,
    workspace_validation_command: str | None = None,
    protected_effect_ids: Sequence[str] | None = None,
    recover_first_unknown: bool = False,
    mcp_relay: Path | None = None,
    mcp_relay_sha256: str | None = None,
    mcp_host_socket: Path | None = None,
    mcp_effect_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Run one deterministic preflight and publish sanitized evidence metadata."""

    effect_ids = (
        ("preflight-effect-1",)
        if protected_effect_ids is None
        else tuple(protected_effect_ids)
    )
    if not 1 <= len(effect_ids) <= 8 or len(set(effect_ids)) != len(effect_ids):
        raise DemoError("protected effect identities must contain 1 to 8 unique values")
    if any(not isinstance(effect_id, str) or not effect_id for effect_id in effect_ids):
        raise DemoError("protected effect identities must be nonempty strings")
    mcp_effects = () if mcp_effect_ids is None else tuple(mcp_effect_ids)
    mcp_inputs = (mcp_relay, mcp_relay_sha256, mcp_host_socket)
    mcp_requested = any(value is not None for value in mcp_inputs) or bool(mcp_effects)
    if mcp_requested and (not all(value is not None for value in mcp_inputs) or len(mcp_effects) != 2):
        raise DemoError(
            "MCP Firecracker mode requires relay, relay SHA-256, host socket, and two effects"
        )
    if mcp_requested and (len(effect_ids) != 1 or len(set(mcp_effects)) != 2 or any(not value for value in mcp_effects)):
        raise DemoError(
            "MCP Firecracker mode requires one checkpoint callback and two unique MCP effects"
        )

    verified: dict[str, dict[str, Any]] = {}
    artifact_paths: dict[str, Path] = {}
    for label, path, digest, executable in (
        ("runner", runner, runner_sha256, True),
        ("firecracker", firecracker, firecracker_sha256, True),
        ("kernel", kernel, kernel_sha256, False),
        ("guest", guest, guest_sha256, True),
        ("payload", payload, payload_sha256, False),
        ("repository", repository, repository_sha256, False),
    ):
        artifact_path, record = _verified_artifact(
            path, digest, label, executable=executable
        )
        artifact_paths[label] = artifact_path
        verified[label] = record
    if mcp_requested:
        assert mcp_relay is not None
        assert mcp_relay_sha256 is not None
        relay_path, relay_record = _verified_artifact(
            mcp_relay, mcp_relay_sha256, "mcp_relay", executable=True
        )
        artifact_paths["mcp_relay"] = relay_path
        verified["mcp_relay"] = relay_record

    codex_digest = _digest(codex_sha256, "codex_sha256")
    workspace_patch_digest: str | None = None
    if workspace_patch is not None:
        try:
            encoded_patch = workspace_patch.encode("utf-8")
        except UnicodeEncodeError as error:
            raise DemoError("workspace patch is not valid UTF-8") from error
        if not encoded_patch or len(encoded_patch) > _MAX_WORKSPACE_PATCH_BYTES:
            raise DemoError(
                "workspace patch must contain 1 to "
                f"{_MAX_WORKSPACE_PATCH_BYTES} UTF-8 bytes"
            )
        workspace_patch_digest = sha256(encoded_patch).hexdigest()
    workspace_validation_digest: str | None = None
    if workspace_validation_command is not None:
        if workspace_patch is None:
            raise DemoError("workspace validation requires a workspace patch")
        try:
            encoded_command = workspace_validation_command.encode("utf-8")
        except UnicodeEncodeError as error:
            raise DemoError("workspace validation command is not valid UTF-8") from error
        if (
            not encoded_command
            or len(encoded_command) > _MAX_WORKSPACE_VALIDATION_COMMAND_BYTES
            or b"\x00" in encoded_command
        ):
            raise DemoError(
                "workspace validation command must contain 1 to "
                f"{_MAX_WORKSPACE_VALIDATION_COMMAND_BYTES} NUL-free UTF-8 bytes"
            )
        workspace_validation_digest = sha256(encoded_command).hexdigest()
    runtime_dir = _directory(
        runtime_evidence, "runtime_evidence", private=True, empty=True
    )
    adapter_dir = _directory(
        adapter_evidence, "adapter_evidence", private=True, empty=True
    )
    workspace_dir = _directory(workspace, "workspace", private=False, empty=True)
    disjoint_paths = {
        **artifact_paths,
        "runtime_evidence": runtime_dir,
        "adapter_evidence": adapter_dir,
        "workspace": workspace_dir,
    }
    mcp_endpoint: Path | None = None
    if mcp_requested:
        assert mcp_host_socket is not None
        mcp_endpoint = _sandbox_socket_path(mcp_host_socket)
        _verify_sandbox_socket(mcp_endpoint)
        disjoint_paths["mcp_host_socket"] = mcp_endpoint
    join_inputs = (
        control_url,
        admin_token_file,
        sandbox_socket,
        payment_url,
        repository_tree_root,
    )
    join_requested = any(value is not None for value in join_inputs)
    if join_requested and not all(value is not None for value in join_inputs):
        raise DemoError("the five control-join options must be supplied together")
    if recover_first_unknown and not join_requested:
        raise DemoError("unknown-outcome recovery requires the control join")

    admin_token: str | None = None
    control_origin: str | None = None
    payment_origin: str | None = None
    sandbox_endpoint: Path | None = None
    source_binding: dict[str, Any] | None = None
    control_operations: list[dict[str, Any]] = []
    if join_requested:
        assert admin_token_file is not None
        assert sandbox_socket is not None
        admin_path, _ = _canonical_existing(admin_token_file, "admin_token_file")
        disjoint_paths["admin_token_file"] = admin_path
        admin_token = _read_private_token(admin_path, "admin_token_file")
        sandbox_endpoint = _sandbox_socket_path(sandbox_socket)
        disjoint_paths["sandbox_socket"] = sandbox_endpoint
        assert control_url is not None
        assert payment_url is not None
        assert repository_tree_root is not None
        control_origin = _loopback_url(control_url, "control_url")
        payment_origin = _loopback_url(payment_url, "payment_url")
        base_root = _digest(repository_tree_root, "repository_tree_root")
        source_binding = _binding(
            "host-" + secrets.token_hex(16), 1, base_root
        )
    _require_pairwise_disjoint(disjoint_paths)

    if join_requested:
        assert control_origin is not None
        assert payment_origin is not None
        assert admin_token is not None
        assert source_binding is not None
        certificate = _post_json(
            control_origin,
            admin_token,
            "/v1/compile",
            _requirement(
                "firecracker-codex-before",
                payment_origin,
                operation_count=len(effect_ids),
                queryable=recover_first_unknown,
            ),
        )
        if certificate.get("decision") != "activate" or not isinstance(
            certificate.get("rule"), dict
        ):
            raise DemoError("control refused the initial Firecracker Rule")
        initial = _post_json(
            control_origin,
            admin_token,
            "/v1/cutover",
            {"certificate": certificate, "bindings": [source_binding]},
        )
        bindings = initial.get("bindings")
        if not isinstance(bindings, list) or bindings != [source_binding]:
            raise DemoError("control returned a different initial sandbox binding")
        assert sandbox_endpoint is not None
        _verify_sandbox_socket(sandbox_endpoint)

    raw_jsonl = adapter_dir / "app-server.jsonl"
    result_path = adapter_dir / "result.json"
    mcp_server: MCPStdioServer | None = None
    if mcp_requested:
        mcp_server = MCPStdioServer(
            name="continuity",
            command=artifact_paths["mcp_relay"],
            runtime_command=_GUEST_MCP_RELAY,
            args=("-loopback-port", str(_GUEST_MCP_PORT)),
            enabled_tools=("commit_effect",),
        )
    def protected_operation(pending: Any) -> None:
        if not join_requested:
            pending.respond_text(f"receipt:{pending.arguments['effect_id']}")
            return
        assert control_origin is not None
        assert sandbox_endpoint is not None
        body = json.dumps(
            {"effect_id": pending.arguments["effect_id"]},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        outcome = _post_sandbox_json(
            sandbox_endpoint,
            {
                "call_id": pending.call_id,
                "kind": "protected_commit",
                "body": base64.b64encode(body).decode("ascii"),
            },
        )
        unknown_observed = bool(outcome.pop("outcome_unknown", False))
        if unknown_observed:
            if not recover_first_unknown or control_operations:
                raise DemoError("only the first protected Operation may require recovery")
            operation_id = outcome.get("operation_id")
            if (
                outcome.get("phase") != "unknown"
                or not isinstance(operation_id, str)
                or len(operation_id) != 67
                or not operation_id.startswith("op-")
                or any(character not in "0123456789abcdef" for character in operation_id[3:])
            ):
                raise DemoError("Operation gateway returned malformed unknown progress")
            assert admin_token is not None
            outcome = _post_json(
                control_origin,
                admin_token,
                f"/v1/operations/{operation_id}/recover",
                {},
            )
            if outcome.get("recovered_by_query") is not True:
                raise DemoError("unknown Operation did not settle by provider query")
        if (
            outcome.get("phase") != "succeeded"
            or not isinstance(outcome.get("operation_id"), str)
            or not isinstance(outcome.get("result_hash"), str)
        ):
            raise DemoError("Operation gateway did not settle the protected callback")
        control_operations.append(
            {
                "call_id": pending.call_id,
                "effect_id": pending.arguments["effect_id"],
                "operation_id": outcome["operation_id"],
                "phase": outcome["phase"],
                "result_hash": outcome["result_hash"],
                "reused": bool(outcome.get("reused", False)),
                "recovered_by_query": bool(outcome.get("recovered_by_query", False)),
                "unknown_observed": unknown_observed,
            }
        )
        pending.respond_text(f"receipt:{pending.arguments['effect_id']}")

    with create_firecracker_codex(
        runner=artifact_paths["runner"],
        runner_sha256=verified["runner"]["sha256"],
        firecracker=artifact_paths["firecracker"],
        firecracker_sha256=verified["firecracker"]["sha256"],
        kernel=artifact_paths["kernel"],
        kernel_sha256=verified["kernel"]["sha256"],
        guest=artifact_paths["guest"],
        guest_sha256=verified["guest"]["sha256"],
        payload=artifact_paths["payload"],
        payload_sha256=verified["payload"]["sha256"],
        repository=artifact_paths["repository"],
        repository_sha256=verified["repository"]["sha256"],
        codex_sha256=codex_digest,
        evidence_dir=runtime_dir,
        workspace=workspace_dir,
        mcp_host_socket=mcp_endpoint,
    ) as wrapped:
        previous_umask = os.umask(0o077)
        try:
            preflight = run_preflight(
                codex_binary=os.fspath(wrapped.executable),
                workspace=workspace_dir,
                raw_jsonl_path=raw_jsonl,
                tool_handler=protected_operation,
                workspace_patch=workspace_patch,
                workspace_validation_command=workspace_validation_command,
                workspace_validation_shell=(
                    _WORKSPACE_VALIDATION_SHELL
                    if workspace_validation_command is not None
                    else None
                ),
                protected_effect_ids=effect_ids,
                mcp_server=mcp_server,
                mcp_effect_ids=mcp_effects or None,
            )
        finally:
            os.umask(previous_umask)

    if Path(preflight.raw_jsonl_path) != raw_jsonl:
        raise DemoError("preflight reported an unexpected App Server capture path")
    preflight_record = _preflight_record(preflight)
    observed_effects = tuple(item.effect_id for item in preflight.protected_calls)
    if preflight.protected_calls and observed_effects != effect_ids:
        raise DemoError("preflight reported a different protected callback sequence")
    if join_requested and len(control_operations) != len(effect_ids):
        raise DemoError("control did not settle every protected callback")
    if recover_first_unknown and (
        not control_operations
        or control_operations[0]["unknown_observed"] is not True
        or control_operations[0]["recovered_by_query"] is not True
    ):
        raise DemoError("the first protected callback did not exercise query recovery")
    if workspace_patch_digest is not None and (
        preflight.workspace_edit_call_id is None
        or preflight.workspace_patch_sha256 != workspace_patch_digest
    ):
        raise DemoError("native Codex did not report the requested workspace edit")
    if workspace_validation_digest is not None and (
        preflight.workspace_validation_call_id is None
        or preflight.workspace_validation_command_sha256
        != workspace_validation_digest
    ):
        raise DemoError("native Codex did not report the requested workspace validation")
    runtime_value, runtime_fingerprint = _read_runtime_result(
        runtime_dir / "result.json",
        runner_sha256=verified["runner"]["sha256"],
        codex_sha256=codex_digest,
        workspace=workspace_dir,
    )
    adapter_fingerprint = _fingerprint_private_file(
        raw_jsonl, "App Server JSONL capture"
    )
    if adapter_fingerprint["size"] <= 0 or preflight.raw_record_count <= 0:
        raise DemoError("App Server JSONL capture is empty")

    if workspace_patch_digest is not None:
        repository_change = runtime_value.get("repository_change")
        if not isinstance(repository_change, dict):
            raise DemoError("runtime result omitted repository change evidence")
        base_root = _digest(str(repository_change.get("base_root", "")), "base_root")
        final_root = _digest(
            str(repository_change.get("final_root", "")), "final_root"
        )
        operation_count = repository_change.get("operation_count")
        if base_root == final_root or not isinstance(operation_count, int) or operation_count < 1:
            raise DemoError("native Codex edit did not produce a nonempty repository delta")

    control_record: dict[str, Any] | None = None
    if join_requested:
        assert control_origin is not None
        assert payment_origin is not None
        assert admin_token is not None
        assert source_binding is not None
        repository_change = runtime_value.get("repository_change")
        artifacts = runtime_value.get("artifacts")
        if not isinstance(repository_change, dict) or not isinstance(artifacts, dict):
            raise DemoError("runtime result omitted repository change evidence")
        checkpoint = artifacts.get("checkpoint")
        final_bundle = artifacts.get("repository_final")
        delta = artifacts.get("repository_delta")
        if not all(isinstance(item, dict) for item in (checkpoint, final_bundle, delta)):
            raise DemoError("runtime result omitted checkpoint or repository artifacts")
        assert isinstance(checkpoint, dict)
        assert isinstance(final_bundle, dict)
        assert isinstance(delta, dict)
        base_root = _digest(str(repository_change.get("base_root", "")), "base_root")
        final_root = _digest(str(repository_change.get("final_root", "")), "final_root")
        if base_root != source_binding["repository_root"]:
            raise DemoError("runtime repository base differs from the active binding")
        target_binding = _binding("host-" + secrets.token_hex(16), 2, final_root)
        certificate = _post_json(
            control_origin,
            admin_token,
            "/v1/compile",
            _requirement(
                "firecracker-codex-after",
                payment_origin,
                operation_count=len(effect_ids),
                queryable=recover_first_unknown,
            ),
        )
        history = certificate.get("history")
        if certificate.get("decision") != "activate" or not isinstance(history, dict):
            raise DemoError("control refused the post-execution Rule")
        repository_record = {
            "sandbox_id": source_binding["sandbox_id"],
            "source_generation": source_binding["generation"],
            "source_host_instance_id": source_binding["host_instance_id"],
            "checkpoint_sha256": _digest(
                str(checkpoint.get("sha256", "")), "checkpoint_sha256"
            ),
            "base_root": base_root,
            "final_root": final_root,
            "final_bundle_sha256": _digest(
                str(final_bundle.get("sha256", "")), "final_bundle_sha256"
            ),
            "final_bundle_size": final_bundle.get("size"),
            "delta_sha256": _digest(
                str(delta.get("sha256", "")), "delta_sha256"
            ),
            "delta_size": delta.get("size"),
        }
        committed = _post_json(
            control_origin,
            admin_token,
            "/v1/cutover",
            {
                "certificate": certificate,
                "bindings": [target_binding],
                "repositories": [repository_record],
            },
        )
        state = committed.get("state")
        bindings = committed.get("bindings")
        if (
            not isinstance(state, dict)
            or not isinstance(state.get("history"), dict)
            or bindings != [target_binding]
        ):
            raise DemoError("control returned a different repository Cutover")
        control_record = {
            "operation": control_operations[0],
            "operations": control_operations,
            "certificate_history": history,
            "committed_history": state["history"],
            "source_binding": source_binding,
            "target_binding": target_binding,
            "repository": repository_record,
        }

    record: dict[str, Any] = {
        "schema": RESULT_SCHEMA,
        "ok": True,
        "result_path": os.fspath(result_path),
        "artifacts": {**verified, "codex": {"sha256": codex_digest}},
        "workspace": {"host": os.fspath(workspace_dir), "guest": "/workspace"},
        "runtime": {
            "evidence_directory": os.fspath(runtime_dir),
            "session_id": runtime_value["session_id"],
            "result": runtime_fingerprint,
        },
        "adapter": {
            "evidence_directory": os.fspath(adapter_dir),
            "app_server_jsonl": adapter_fingerprint,
        },
        "preflight": preflight_record,
        "independent_evidence_check": "required",
    }
    if control_record is not None:
        record["control"] = control_record
    if mcp_requested:
        record["mcp"] = {
            "effect_ids": list(mcp_effects),
            "guest_relay": _GUEST_MCP_RELAY,
            "guest_port": _GUEST_MCP_PORT,
        }
    _write_exclusive_json(result_path, record)
    return record


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the deterministic App Server preflight across one real "
            "Firecracker snapshot/restore. No account credential is used."
        )
    )
    for name, help_text in (
        ("runner", "firecracker-codex-shim executable"),
        ("firecracker", "Firecracker executable"),
        ("kernel", "uncompressed guest kernel"),
        ("guest", "firecracker-agent-guest executable"),
        ("payload", "immutable native Codex SquashFS payload"),
        ("repository", "canonical read-only repository bundle"),
    ):
        parser.add_argument(f"--{name}", required=True, type=Path, help=help_text)
        parser.add_argument(
            f"--{name}-sha256", required=True, help=f"exact SHA-256 of {name}"
        )
    parser.add_argument(
        "--codex-sha256",
        required=True,
        help="exact SHA-256 of payload bin/codex",
    )
    parser.add_argument(
        "--runtime-evidence",
        required=True,
        type=Path,
        help="existing empty current-user directory with mode 0700",
    )
    parser.add_argument(
        "--adapter-evidence",
        required=True,
        type=Path,
        help="separate existing empty current-user directory with mode 0700",
    )
    parser.add_argument(
        "--workspace",
        required=True,
        type=Path,
        help="existing empty canonical host workspace",
    )
    parser.add_argument(
        "--control-url",
        help="optional loopback control API; requires all other control-join options",
    )
    parser.add_argument("--admin-token-file", type=Path)
    parser.add_argument(
        "--sandbox-socket",
        type=Path,
        help="host-owned Unix socket for the bound Firecracker instance",
    )
    parser.add_argument("--payment-url", help="loopback external-effect service origin")
    parser.add_argument(
        "--repository-tree-root",
        help="canonical input repository tree root recorded in the initial binding",
    )
    parser.add_argument(
        "--workspace-patch-file",
        type=Path,
        help=(
            "optional absolute UTF-8 apply_patch input; native Codex executes it "
            "inside the externally sandboxed Firecracker workspace"
        ),
    )
    parser.add_argument(
        "--workspace-validation-command",
        help=(
            "optional command executed after the native edit and before the "
            "protected callback, using /opt/codex/bin/sh inside Firecracker"
        ),
    )
    parser.add_argument(
        "--protected-effect-id",
        action="append",
        dest="protected_effect_ids",
        help=(
            "protected effect identity; repeat to issue multiple ordered calls "
            "in the same Codex turn"
        ),
    )
    parser.add_argument(
        "--recover-first-unknown",
        action="store_true",
        help=(
            "require the first protected Operation to become unknown and settle "
            "it through the provider query contract"
        ),
    )
    parser.add_argument(
        "--mcp-relay",
        type=Path,
        help="optional host copy of the MCP relay attested into the guest payload",
    )
    parser.add_argument("--mcp-relay-sha256")
    parser.add_argument(
        "--mcp-host-socket",
        type=Path,
        help="private trusted MCP host socket outside the microVM restore domain",
    )
    parser.add_argument(
        "--mcp-effect-id",
        action="append",
        dest="mcp_effect_ids",
        help="MCP effect identity; supply exactly twice for before/after restore",
    )
    return parser.parse_args(argv)


def _read_workspace_patch_file(value: Path | None) -> str | None:
    if value is None:
        return None
    path, info = _canonical_existing(value, "workspace_patch_file")
    if not stat.S_ISREG(info.st_mode) or info.st_size <= 0:
        raise DemoError("workspace_patch_file must be a nonempty regular file")
    if info.st_size > _MAX_WORKSPACE_PATCH_BYTES:
        raise DemoError(
            f"workspace_patch_file exceeds {_MAX_WORKSPACE_PATCH_BYTES} bytes"
        )
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise DemoError("cannot open workspace_patch_file") from error
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or (opened.st_dev, opened.st_ino, opened.st_size)
            != (info.st_dev, info.st_ino, info.st_size)
        ):
            raise DemoError("workspace_patch_file changed while it was opened")
        data = bytearray()
        while block := os.read(descriptor, 1 << 16):
            data.extend(block)
            if len(data) > _MAX_WORKSPACE_PATCH_BYTES:
                raise DemoError("workspace_patch_file grew while it was read")
    finally:
        os.close(descriptor)
    current = path.lstat()
    if (current.st_dev, current.st_ino, current.st_size) != (
        info.st_dev,
        info.st_ino,
        info.st_size,
    ):
        raise DemoError("workspace_patch_file changed while it was read")
    try:
        return bytes(data).decode("utf-8")
    except UnicodeDecodeError as error:
        raise DemoError("cannot read workspace_patch_file as UTF-8") from error


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        workspace_patch = _read_workspace_patch_file(args.workspace_patch_file)
        result = run_demo(
            runner=args.runner,
            runner_sha256=args.runner_sha256,
            firecracker=args.firecracker,
            firecracker_sha256=args.firecracker_sha256,
            kernel=args.kernel,
            kernel_sha256=args.kernel_sha256,
            guest=args.guest,
            guest_sha256=args.guest_sha256,
            payload=args.payload,
            payload_sha256=args.payload_sha256,
            repository=args.repository,
            repository_sha256=args.repository_sha256,
            codex_sha256=args.codex_sha256,
            runtime_evidence=args.runtime_evidence,
            adapter_evidence=args.adapter_evidence,
            workspace=args.workspace,
            control_url=args.control_url,
            admin_token_file=args.admin_token_file,
            sandbox_socket=args.sandbox_socket,
            payment_url=args.payment_url,
            repository_tree_root=args.repository_tree_root,
            workspace_patch=workspace_patch,
            workspace_validation_command=args.workspace_validation_command,
            protected_effect_ids=args.protected_effect_ids,
            recover_first_unknown=args.recover_first_unknown,
            mcp_relay=args.mcp_relay,
            mcp_relay_sha256=args.mcp_relay_sha256,
            mcp_host_socket=args.mcp_host_socket,
            mcp_effect_ids=args.mcp_effect_ids,
        )
    except Exception as error:
        print(f"Firecracker Codex demo failed: {error}", file=sys.stderr)
        return 1
    summary = {
        "schema": RESULT_SCHEMA,
        "ok": True,
        "result_path": result["result_path"],
        "runtime_evidence": result["runtime"]["evidence_directory"],
        "adapter_evidence": result["adapter"]["evidence_directory"],
    }
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["DemoError", "RESULT_SCHEMA", "main", "run_demo"]
