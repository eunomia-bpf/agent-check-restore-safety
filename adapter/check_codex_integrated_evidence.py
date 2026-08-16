"""Independently verify the Codex + service + restored-VM evidence bundle.

The live runner is deliberately not imported.  This checker replays the exact
binary History frames, validates all three Certificates, derives three Operation
identities and requests, joins three independently durable effect records, and
checks raw Docker, App Server, and QEMU or Firecracker evidence.
"""

from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any, Mapping, Sequence

from adapter.check_codex_isolated_evidence import (
    EvidenceError,
    _check_anchor,
    _check_container_hardening,
    _docker_networks,
    _hash,
    _inspect_object,
    _json_file,
    _list,
    _loads,
    _object,
    _read,
    _replay_history,
    _require,
    _rfc3339_nanoseconds,
)


RUN_ID = re.compile(r"safe-change-integrated-[1-9][0-9]*-[0-9a-f]{8}\Z")
PURCHASE_ID = re.compile(r"A-17-([0-9a-f]{8})\Z")
TOOL_NAME = "complete_purchase"
CODEX_DOMAIN = "codex-app-server"
ORDER_DOMAIN = "orders"
VM_DOMAIN = "full-linux-vm"
VM_SANDBOX_ID = "integrated-vm"
CHARGE_KIND = "charge-invoice"
RESERVE_V1_KIND = "reserve-v1"
RESERVE_V2_KIND = "reserve-v2"
AUDIT_KIND = "append-audit"
BASE_IMAGE_SHA = "d1940f7d69d343355e183dff1e08a59852d32e7309baa7a4bad8365b11b005ac"
NATIVE_CODEX_SHA = "cb0a15567e9a60a5820d54b0f6ae86d504dc3805c1eab21a47f70e3eb7b73a40"
QEMU_SYSTEM_SHA = "8a35ccba41582fc6c38b9df85fc9e35fa1d42f414d2d7d8090ee9b2f5e7c0854"
QEMU_IMAGE_SHA = "634320b91165669917123e8e79cce1c4d00cee0a4aa4d662d7c0a8186479b3fb"
NETCAT_SHA = "2a6fac3d98e090468962ef18003cb8b89fbffa7219917ca12567d5e42b156948"


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


def _operation_id(domain: str, call_id: str) -> str:
    digest = sha256()
    digest.update(b"operation-id-v1\x00")
    digest.update(domain.encode())
    digest.update(b"\x00")
    digest.update(call_id.encode())
    return "op-" + digest.hexdigest()


def _sandbox_operation_id(domain: str, sandbox_id: str, call_id: str) -> str:
    digest = sha256()
    digest.update(b"sandbox-operation-id-v2\x00")
    digest.update(domain.encode())
    digest.update(b"\x00")
    digest.update(sandbox_id.encode())
    digest.update(b"\x00")
    digest.update(call_id.encode())
    return "op-" + digest.hexdigest()


def _git_bytes(repository: Path, arguments: Sequence[str]) -> bytes:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    _require(
        completed.returncode == 0,
        "source revision cannot be read from the local Git object database",
    )
    return completed.stdout


def _check_provenance(
    directory: Path,
    run_id: str,
    repository: Path,
) -> dict[str, Any]:
    source = _object(
        _json_file(directory, "source-provenance.json"),
        "source provenance",
    )
    _require(
        set(source)
        == {
            "files",
            "python_isolated",
            "python_no_user_site",
            "revision",
            "schema",
            "selected_source_clean",
            "source_tree_sha256",
        }
        and source.get("schema") == 1
        and source.get("selected_source_clean") is True
        and source.get("python_isolated") is True
        and source.get("python_no_user_site") is True,
        "source provenance envelope differs",
    )
    revision = source.get("revision")
    tree_hash = source.get("source_tree_sha256")
    _require(
        isinstance(revision, str)
        and re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", revision) is not None
        and isinstance(tree_hash, str)
        and re.fullmatch(r"[0-9a-f]{64}", tree_hash) is not None,
        "source provenance contains an invalid revision or tree digest",
    )
    _git_bytes(repository, ["cat-file", "-e", revision + "^{commit}"])
    listed = _git_bytes(
        repository,
        ["ls-tree", "-r", "--name-only", "-z", revision],
    ).decode("utf-8").split("\0")
    expected_files = sorted(
        path for path in listed if path and _selected_source_path(path)
    )
    required = {
        "adapter/__init__.py",
        "adapter/app_server.py",
        "adapter/codex_integrated_runtime_demo.py",
        "adapter/codex_isolated_runtime_demo.py",
        "adapter/codex_runtime_demo.py",
        "adapter/docker_codex.py",
        "adapter/mock_responses.py",
    }
    _require(
        required <= set(expected_files),
        "source revision omits an integrated producer dependency",
    )
    recorded_files = _object(source.get("files"), "source file hashes")
    _require(
        list(sorted(recorded_files)) == expected_files,
        "source provenance selects another implementation file set",
    )
    recomputed: dict[str, str] = {}
    for path in expected_files:
        value = recorded_files.get(path)
        _require(
            isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None,
            f"source digest is malformed for {path}",
        )
        content = _git_bytes(repository, ["show", f"{revision}:{path}"])
        recomputed[path] = sha256(content).hexdigest()
    _require(
        recorded_files == recomputed,
        "recorded producer files differ from the committed source revision",
    )
    digest = sha256()
    for path in expected_files:
        digest.update(path.encode() + b"\x00" + recomputed[path].encode() + b"\x00")
    _require(
        digest.hexdigest() == tree_hash,
        "producer source-tree digest does not match its committed files",
    )

    build = _object(
        _json_file(directory, "runtime-build-provenance.json"),
        "runtime build provenance",
    )
    backend = build.get("vm_backend", "qemu")
    if backend == "qemu":
        vm_demo_sha256 = build.get("vm_demo_sha256")
        expected_build = {
            "schema": 1,
            "build_input": "git-archive",
            "revision": revision,
            "source_tree_sha256": tree_hash,
            "vm_demo_sha256": vm_demo_sha256,
        }
    else:
        vm_demo_sha256 = build.get("firecracker_demo_sha256")
        guest_sha256 = build.get("firecracker_guest_sha256")
        expected_build = {
            "schema": 1,
            "build_input": "git-archive",
            "revision": revision,
            "source_tree_sha256": tree_hash,
            "vm_backend": "firecracker",
            "firecracker_demo_sha256": vm_demo_sha256,
            "firecracker_guest_sha256": guest_sha256,
        }
    _require(
        backend in {"qemu", "firecracker"}
        and build == expected_build
        and isinstance(vm_demo_sha256, str)
        and re.fullmatch(r"[0-9a-f]{64}", vm_demo_sha256) is not None
        and (
            backend == "qemu"
            or (
                isinstance(guest_sha256, str)
                and re.fullmatch(r"[0-9a-f]{64}", guest_sha256) is not None
            )
        ),
        "runtime build is not tied to the committed Git archive",
    )

    image = _object(
        _json_file(directory, "image-provenance.json"),
        "runtime image provenance",
    )
    source_labels = {
        "io.safe-change.source-tree.sha256": tree_hash,
        "org.opencontainers.image.revision": revision,
    }
    fixed_image_labels = {
        "com.docker.compose.project": run_id,
        "com.docker.compose.service": "control",
        **source_labels,
    }
    image_labels = _object(image.get("labels"), "runtime image labels")
    compose_version = image_labels.get("com.docker.compose.version")
    expected_labels = {
        **fixed_image_labels,
        "com.docker.compose.version": compose_version,
    }
    image_id = image.get("image_id")
    container_images = _object(
        image.get("container_images"), "runtime container image bindings"
    )
    _require(
        set(image)
        == {"container_images", "image_id", "labels", "schema", "tag"}
        and image.get("schema") == 1
        and image.get("tag") == "safe-change-runtime:" + run_id
        and isinstance(image_id, str)
        and re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is not None
        and image_labels == expected_labels
        and isinstance(compose_version, str)
        and re.fullmatch(
            r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?",
            compose_version,
        )
        is not None
        and len(container_images) == 8
        and all(value == image_id for value in container_images.values()),
        "runtime image is not immutably bound to the producer source",
    )
    return {
        "revision": revision,
        "source_tree_sha256": tree_hash,
        "image_id": image_id,
        "image_labels": expected_labels,
        "source_labels": source_labels,
        "compose_version": compose_version,
        "container_images": container_images,
        "vm_demo_sha256": vm_demo_sha256,
        "vm_backend": backend,
        "firecracker_guest_sha256": build.get("firecracker_guest_sha256"),
        "source_files": recorded_files,
    }


@contextmanager
def _recorded_runtime_source(
    repository: Path, provenance: Mapping[str, Any]
) -> Any:
    """Materialize the exact recorded Go verifier source into a private tree."""

    revision = provenance.get("revision")
    source_files = _object(provenance.get("source_files"), "source file hashes")
    _require(isinstance(revision, str), "recorded source revision is absent")
    with tempfile.TemporaryDirectory(
        prefix="safe-change-recorded-runtime-"
    ) as temporary:
        root = Path(temporary)
        runtime = root / "runtime"
        runtime.mkdir(mode=0o700)
        materialized: set[str] = set()
        for path in sorted(source_files):
            if not path.startswith("runtime/") or not (
                path.endswith(".go") or path in {"runtime/go.mod", "runtime/go.sum"}
            ):
                continue
            parts = Path(path).parts
            _require(
                parts
                and parts[0] == "runtime"
                and ".." not in parts
                and not Path(path).is_absolute(),
                "recorded runtime source contains an unsafe path",
            )
            content = _git_bytes(repository, ["show", f"{revision}:{path}"])
            expected = source_files[path]
            _require(
                sha256(content).hexdigest() == expected,
                f"recorded runtime source digest changed for {path}",
            )
            destination = root.joinpath(*parts)
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            destination.write_bytes(content)
            materialized.add(path)
        required = {
            "runtime/go.mod",
            "runtime/go.sum",
            "runtime/cmd/check-certificate/main.go",
        }
        if provenance.get("vm_backend") == "firecracker":
            required.add("runtime/cmd/check-firecracker-evidence/main.go")
        _require(
            required <= materialized,
            "recorded runtime source omits an independent verifier",
        )
        yield runtime


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode()


def _kind(target: str, resource: str, result: str) -> dict[str, Any]:
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
    common = {
        "results": {"paid": 1, "reserved": 1, "audited": 1},
        "capacities": {
            "payment-slot": 1,
            "inventory-slot": 1,
            "audit-slot": 1,
        },
    }
    first = {
        "id": f"purchase-v1/{run_id}",
        **common,
        "kinds": {
            CHARGE_KIND: _kind(
                "http://payment:8081/v1/charge", "payment-slot", "paid"
            ),
            RESERVE_V1_KIND: _kind(
                "http://inventory:8081/v1/charge",
                "inventory-slot",
                "reserved",
            ),
            AUDIT_KIND: _kind(
                "http://ledger:8081/v1/charge", "audit-slot", "audited"
            ),
        },
    }
    second = {
        "id": f"purchase-v2/{run_id}",
        **common,
        "kinds": {
            CHARGE_KIND: _kind(
                "http://payment:8081/v1/charge", "payment-slot", "paid"
            ),
            RESERVE_V2_KIND: _kind(
                "http://inventory:8081/v2/charge",
                "inventory-slot",
                "reserved",
            ),
            AUDIT_KIND: _kind(
                "http://ledger:8081/v1/charge", "audit-slot", "audited"
            ),
        },
    }
    return first, second


def _vm_binding(run_id: str, generation: int, backend: str = "qemu") -> dict[str, Any]:
    prefix = "firecracker" if backend == "firecracker" else "qemu"
    return {
        "sandbox_id": VM_SANDBOX_ID,
        "generation": generation,
        "host_instance_id": f"{prefix}-{run_id}-g{generation}",
        "domain": VM_DOMAIN,
        "allowed_kinds": [AUDIT_KIND],
    }


def _gateway_request_hash(
    url: str, body: bytes, operation_id: str, *, content_type: bool = True
) -> str:
    headers = {
        "accept-encoding": "identity",
        "idempotency-key": operation_id,
        "user-agent": "safe-change-runtime/1",
        "x-operation-id": operation_id,
    }
    if content_type:
        headers["content-type"] = "application/json"
    digest = sha256()
    digest.update(b"POST\x00" + url.encode() + b"\x00")
    for name, value in sorted(headers.items()):
        digest.update(name.encode() + b":" + value.encode() + b"\x00")
    digest.update(body)
    return digest.hexdigest()


def _effect_request_hash(body: bytes) -> str:
    return sha256(b"POST\x00/v1/charge\x00" + body).hexdigest()


def _expected_vm_guest_script(request_data: bytes, direct_probe: str) -> str:
    encoded_request = base64.b64encode(request_data).decode()
    encoded_probe = base64.b64encode(direct_probe.encode()).decode()
    template = r'''#!/usr/bin/env bash
set -uo pipefail
log_marker() { printf '%s\n' "$1" > /dev/ttyS0; }
log_marker "SAFE_CHANGE_VM_EXTERNAL_READY kernel=$(uname -r)"
until curl -fsS --connect-timeout 2 --max-time 3 http://10.0.2.100:8000/go >/dev/null; do sleep 1; done
direct_url=$(printf '%s' '<DIRECT_PROBE>' | base64 -d)
if curl -fsS --connect-timeout 2 --max-time 3 "$direct_url" >/dev/null; then
  log_marker SAFE_CHANGE_VM_DIRECT_EFFECT_REACHABLE
  /sbin/poweroff -f
  exit 1
fi
log_marker SAFE_CHANGE_VM_DIRECT_EFFECT_BLOCKED
printf '%s' '<REQUEST_DATA>' | base64 -d > /run/safe-change-execute.json
status=$(curl -sS --max-time 45 -o /run/safe-change-response.json -w '%{http_code}' \
  -X POST -H 'Content-Type: application/json' \
  --data-binary @/run/safe-change-execute.json http://10.0.2.100:8787/v1/execute) || status=transport-error
read -r phase reused < <(python3 -c 'import json; d=json.load(open("/run/safe-change-response.json")); print(d.get("phase", ""), str(bool(d.get("reused", False))).lower())' 2>/dev/null || true)
if [[ "$status" == 200 && "$phase" == succeeded && "$reused" == false ]]; then
  log_marker "SAFE_CHANGE_VM_FIRST_SUCCEEDED reused=false"
  sync
  while true; do sleep 60; done
fi
if [[ "$status" == 200 && "$phase" == succeeded && "$reused" == true ]]; then
  log_marker "SAFE_CHANGE_VM_RESTORED_SUCCEEDED reused=true"
  sync
  /sbin/poweroff -f
  exit 0
fi
log_marker "SAFE_CHANGE_VM_EXTERNAL_UNEXPECTED status=$status phase=$phase reused=$reused"
/sbin/poweroff -f
exit 1
'''
    return template.replace("<DIRECT_PROBE>", encoded_probe).replace(
        "<REQUEST_DATA>", encoded_request
    )


def _receipt(operation_id: str) -> tuple[bytes, str, str, str]:
    external_result = sha256(b"charged\x00" + operation_id.encode()).hexdigest()
    remote = "payment/" + operation_id
    body = _canonical(
        {
            "schema": 1,
            "operation_id": operation_id,
            "outcome": "succeeded",
            "result_hash": external_result,
            "remote_reference": remote,
        }
    ) + b"\n"
    gateway_result = external_result
    return body, external_result, gateway_result, remote


def _single_line_record(directory: Path, name: str) -> dict[str, Any]:
    raw = _read(directory / name)
    lines = raw.splitlines()
    _require(len(lines) == 1 and raw.endswith(b"\n"), f"{name} is not one durable record")
    return _object(_loads(lines[0], name), name)


def _one(values: list[Any], label: str) -> Any:
    _require(len(values) == 1, f"expected one {label}, observed {len(values)}")
    return values[0]


def _check_certificate(
    directory: Path,
    label: str,
    runtime_dir: Path | None,
) -> dict[str, Any]:
    verdict = _object(
        _json_file(directory, f"checker-verdict-{label}.json"),
        f"{label} checker verdict",
    )
    _require(verdict.get("valid") is True, f"saved {label} Certificate was rejected")
    if runtime_dir is None:
        return verdict
    completed = subprocess.run(
        [
            "go",
            "run",
            "./cmd/check-certificate",
            "-state",
            str(directory / f"certificate-state-{label}.json"),
            "-certificate",
            str(directory / f"certificate-{label}.json"),
        ],
        cwd=runtime_dir,
        text=True,
        capture_output=True,
        timeout=120.0,
        check=False,
    )
    _require(completed.returncode == 0, f"fresh {label} Certificate check failed")
    fresh = _object(
        _loads(completed.stdout.encode(), f"fresh {label} Certificate verdict"),
        f"fresh {label} Certificate verdict",
    )
    _require(fresh == verdict, f"fresh {label} Certificate verdict changed")
    return verdict


def _prepared(
    event: Mapping[str, Any], expected: Mapping[str, Any], label: str
) -> dict[str, Any]:
    _require(event.get("operation") == "operation.prepared", f"{label} was not prepared")
    data = _object(event.get("data"), f"{label} prepare data")
    _require(
        set(data) == {"operation", "semantic_version"}
        and data.get("semantic_version") == 1,
        f"{label} prepare envelope changed",
    )
    operation = _object(data.get("operation"), f"{label} prepared Operation")
    _require(operation == expected, f"{label} prepared Operation differs")
    return operation


def _phase(
    event: Mapping[str, Any],
    operation_id: str,
    expected: Mapping[str, Any],
    label: str,
) -> dict[str, Any]:
    _require(event.get("operation") == "operation.phase", f"{label} is not a phase event")
    data = _object(event.get("data"), f"{label} data")
    _require(
        set(data) == {"id", "semantic_version", "update"}
        and data.get("id") == operation_id
        and data.get("semantic_version") == 1
        and data.get("update") == expected,
        f"{label} differs",
    )
    return _object(data.get("update"), f"{label} update")


def _check_history_and_effects(
    directory: Path,
    run_id: str,
    purchase_id: str,
    runtime_dir: Path | None,
    vm_backend: str = "qemu",
) -> dict[str, Any]:
    requirement_v1, requirement_v2 = _requirements(run_id)
    _require(
        _json_file(directory, "requirement-v1.json") == requirement_v1
        and _json_file(directory, "requirement-v2.json") == requirement_v2
        and _json_file(directory, "requirement-v2-reopen.json") == requirement_v2,
        "retained Requirements differ from the run identity",
    )
    certificate_v1 = _object(
        _json_file(directory, "certificate-v1.json"), "v1 Certificate"
    )
    certificate_v2 = _object(
        _json_file(directory, "certificate-v2.json"), "v2 Certificate"
    )
    certificate_v2_reopen = _object(
        _json_file(directory, "certificate-v2-reopen.json"),
        "v2 reopen Certificate",
    )
    certificate_verdicts = {
        "v1": _check_certificate(directory, "v1", runtime_dir),
        "v2": _check_certificate(directory, "v2", runtime_dir),
        "v2-reopen": _check_certificate(directory, "v2-reopen", runtime_dir),
    }

    events = _replay_history(directory / "runtime.history")
    _require(len(events) == 16, "shared History does not contain exactly 16 events")
    _check_anchor(directory, 16, events[-1]["hash"])
    _require(
        _json_file(directory, "history.json") == events,
        "History API view differs from binary replay",
    )
    _require(
        [event["operation"] for event in events]
        == [
            "rule.bindings.cutover",
            "operation.prepared",
            "operation.phase",
            "operation.phase",
            "operation.prepared",
            "operation.phase",
            "operation.phase",
            "operation.prepared",
            "operation.phase",
            "operation.phase",
            "rule.bindings.cutover",
            "rule.bindings.cutover",
            "operation.phase",
            "operation.phase",
            "operation.phase",
            "operation.phase",
        ],
        "shared History event shape changed",
    )
    first_rule = _object(events[0]["data"], "v1 cutover")
    second_rule = _object(events[10]["data"], "v2 cutover")
    third_rule = _object(events[11]["data"], "v2 reopen cutover")
    _require(
        first_rule
        == {
            "certificate": certificate_v1,
            "bindings": [_vm_binding(run_id, 1, vm_backend)],
            "semantic_version": 1,
        }
        and second_rule
        == {
            "certificate": certificate_v2,
            "bindings": [_vm_binding(run_id, 2, vm_backend)],
            "semantic_version": 1,
        }
        and third_rule
        == {
            "certificate": certificate_v2_reopen,
            "bindings": [_vm_binding(run_id, 3, vm_backend)],
            "semantic_version": 1,
        },
        "Rule-and-sandbox cutover events differ from retained evidence",
    )
    vm_host_instance_ids: dict[int, str] = {}
    for generation, rule in (
        (1, first_rule),
        (2, second_rule),
        (3, third_rule),
    ):
        bindings = _list(
            rule.get("bindings"), f"generation {generation} History bindings"
        )
        _require(
            len(bindings) == 1,
            f"generation {generation} History binding count differs",
        )
        binding = _object(
            bindings[0], f"generation {generation} History binding"
        )
        host_instance_id = binding.get("host_instance_id")
        _require(
            isinstance(host_instance_id, str) and bool(host_instance_id),
            f"generation {generation} History HostInstanceID is absent",
        )
        vm_host_instance_ids[generation] = host_instance_id
    _require(
        certificate_v1.get("history")
        == {"sequence": 0, "hash": "0" * 64}
        and certificate_v1.get("from_rule") == 0
        and certificate_v1.get("decision") == "activate"
        and certificate_v1.get("schema") == 1
        and certificate_v1.get("requirement") == requirement_v1
        and certificate_v1.get("rule")
        == {
            "allow": [AUDIT_KIND, CHARGE_KIND, RESERVE_V1_KIND],
            "requirement_hash": certificate_v1.get("rule", {}).get(
                "requirement_hash"
            ),
            "version": 1,
        }
        and isinstance(certificate_v1.get("digest"), str),
        "v1 Certificate binding differs",
    )
    _require(
        certificate_v2.get("history")
        == {"sequence": 10, "hash": events[9]["hash"]}
        and certificate_v2.get("from_rule") == 1
        and certificate_v2.get("decision") == "activate"
        and certificate_v2.get("schema") == 1
        and certificate_v2.get("requirement") == requirement_v2
        and certificate_v2.get("rule", {}).get("version") == 2
        and certificate_v2.get("rule", {}).get("allow") == [],
        "v2 Certificate did not close new work while preserving old Operations",
    )
    _require(
        certificate_v2_reopen.get("history")
        == {"sequence": 11, "hash": events[10]["hash"]}
        and certificate_v2_reopen.get("from_rule") == 2
        and certificate_v2_reopen.get("decision") == "activate"
        and certificate_v2_reopen.get("schema") == 1
        and certificate_v2_reopen.get("requirement") == requirement_v2
        and certificate_v2_reopen.get("rule", {}).get("version") == 3
        and certificate_v2_reopen.get("rule", {}).get("allow") == [],
        "reopen Certificate is not bound to the post-cutover History head",
    )
    _hash(certificate_v1.get("digest"), "v1 Certificate digest")
    _hash(certificate_v2.get("digest"), "v2 Certificate digest")
    _hash(certificate_v2_reopen.get("digest"), "v2 reopen Certificate digest")
    for label, sequence, history_hash, rule_version in (
        ("v1", 0, "0" * 64, 1),
        ("v2", 10, events[9]["hash"], 2),
        ("v2-reopen", 11, events[10]["hash"], 3),
    ):
        _require(
            certificate_verdicts[label]
            == {
                "decision": "activate",
                "history_hash": history_hash,
                "history_sequence": sequence,
                "rule_version": rule_version,
                "valid": True,
            },
            f"{label} Certificate verdict differs from its checked binding",
        )

    calls = {
        "codex": (CODEX_DOMAIN, f"purchase/{purchase_id}/payment"),
        "order": (ORDER_DOMAIN, f"order/{purchase_id}/payment"),
        "vm": (VM_DOMAIN, f"purchase/{purchase_id}/audit"),
    }
    operation_ids = {
        name: (
            _sandbox_operation_id(domain, VM_SANDBOX_ID, call_id)
            if name == "vm"
            else _operation_id(domain, call_id)
        )
        for name, (domain, call_id) in calls.items()
    }
    bodies = {
        "codex": _canonical(
            {"amount": 42, "purchase_id": purchase_id, "run_id": run_id}
        ),
        "order": json.dumps(
            {"order_id": purchase_id, "amount": 42},
            separators=(",", ":"),
        ).encode(),
        "vm": _canonical({"purchase_id": purchase_id, "run_id": run_id}),
    }
    contracts = {
        "codex": (
            CHARGE_KIND,
            CODEX_DOMAIN,
            "http://payment:8081/v1/charge",
            {"payment-slot": 1},
            {"paid": 1},
        ),
        "order": (
            RESERVE_V1_KIND,
            ORDER_DOMAIN,
            "http://inventory:8081/v1/charge",
            {"inventory-slot": 1},
            {"reserved": 1},
        ),
        "vm": (
            AUDIT_KIND,
            VM_DOMAIN,
            "http://ledger:8081/v1/charge",
            {"audit-slot": 1},
            {"audited": 1},
        ),
    }
    prepare_indices = {"codex": 1, "order": 4, "vm": 7}
    prepared: dict[str, dict[str, Any]] = {}
    for name, index in prepare_indices.items():
        kind, domain, target, costs, produces = contracts[name]
        operation_id = operation_ids[name]
        expected = {
            "id": operation_id,
            "domain": domain,
            "kind": kind,
            "request_hash": _gateway_request_hash(
                target,
                bodies[name],
                operation_id,
                content_type=name == "codex",
            ),
            "rule_version": 1,
            "costs": costs,
            "produces": produces,
            "retry_safe": True,
            "queryable": False,
            "target": target,
            "method": "POST",
            "response_classifier": "operation-receipt-v1",
            "request_stored": True,
            "request_body": base64.b64encode(bodies[name]).decode(),
            "phase": "prepared",
        }
        if name == "codex":
            expected["request_headers"] = {"Content-Type": "application/json"}
        if name == "vm":
            expected["sandbox_id"] = VM_SANDBOX_ID
        prepared[name] = _prepared(events[index], expected, name)

    first_owner = (
        _object(events[2]["data"], "first dispatch")
        .get("update", {})
        .get("dispatch_owner")
    )
    _require(
        isinstance(first_owner, str)
        and re.fullmatch(r"[0-9a-f]{32}", first_owner) is not None,
        "first control boot identity is absent",
    )
    _phase(
        events[2], operation_ids["codex"],
        {"phase": "dispatched", "dispatch_owner": first_owner, "dispatch_generation": 1},
        "Codex dispatch generation 1",
    )
    _phase(events[3], operation_ids["codex"], {"phase": "unknown"}, "Codex unknown")
    _phase(
        events[5], operation_ids["order"],
        {"phase": "dispatched", "dispatch_owner": first_owner, "dispatch_generation": 1},
        "order dispatch generation 1",
    )
    _phase(events[6], operation_ids["order"], {"phase": "unknown"}, "order unknown")
    _phase(
        events[8], operation_ids["vm"],
        {"phase": "dispatched", "dispatch_owner": first_owner, "dispatch_generation": 1},
        "VM dispatch generation 1",
    )

    external: dict[str, dict[str, Any]] = {}
    settled_updates: dict[str, dict[str, Any]] = {}
    record_files = {
        "codex": "payment.history",
        "order": "inventory.history",
        "vm": "ledger.history",
    }
    success_indices = {"codex": 13, "order": 15, "vm": 9}
    for name, record_file in record_files.items():
        operation_id = operation_ids[name]
        record = _single_line_record(directory, record_file)
        receipt_body, external_hash, gateway_hash, remote = _receipt(operation_id)
        _require(
            record
            == {
                "operation_id": operation_id,
                "request_hash": _effect_request_hash(bodies[name]),
                "result_hash": external_hash,
                "remote_reference": remote,
                "path": "/v1/charge",
            },
            f"{name} durable external record differs",
        )
        expected_update = {
            "phase": "succeeded",
            "result_hash": gateway_hash,
            "status_code": 200,
            "result_body": base64.b64encode(receipt_body).decode(),
            "remote_reference": remote,
        }
        settled_updates[name] = _phase(
            events[success_indices[name]],
            operation_id,
            expected_update,
            f"{name} success",
        )
        external[name] = {
            "record": record,
            "receipt_body": receipt_body,
            "gateway_result_hash": gateway_hash,
            "remote_reference": remote,
        }

    second_owner = (
        _object(events[12]["data"], "second dispatch")
        .get("update", {})
        .get("dispatch_owner")
    )
    _require(
        isinstance(second_owner, str)
        and re.fullmatch(r"[0-9a-f]{32}", second_owner) is not None
        and second_owner != first_owner,
        "control replacement did not change dispatch ownership",
    )
    _phase(
        events[12], operation_ids["codex"],
        {"phase": "dispatched", "dispatch_owner": second_owner, "dispatch_generation": 2},
        "Codex dispatch generation 2",
    )
    _phase(
        events[14], operation_ids["order"],
        {"phase": "dispatched", "dispatch_owner": second_owner, "dispatch_generation": 2},
        "order dispatch generation 2",
    )

    stats = _object(_json_file(directory, "effect-stats.json"), "effect stats")
    expected_stats = {
        "payment": {"deliveries": 2, "commits": 1, "paths": {"/v1/charge": 2}},
        "inventory": {"deliveries": 2, "commits": 1, "paths": {"/v1/charge": 2}},
        "ledger": {"deliveries": 1, "commits": 1, "paths": {"/v1/charge": 1}},
    }
    _require(stats == expected_stats, "three external services have unexpected facts")

    state = _object(_json_file(directory, "final-state.json"), "final state")
    final_rule = _object(state.get("rule"), "final Rule")
    certificate_rule = _object(
        certificate_v2_reopen.get("rule"), "reopen Certificate Rule"
    )
    _require(
        state.get("history") == {"sequence": 16, "hash": events[-1]["hash"]}
        and state.get("requirement") == requirement_v2
        and final_rule == certificate_rule,
        "final State does not match replayed v2 History",
    )
    operations = _object(state.get("operations"), "final Operations")
    _require(
        set(operations) == set(operation_ids.values()),
        "final State has another Operation set",
    )
    for name, operation_id in operation_ids.items():
        operation = _object(operations.get(operation_id), f"final {name} Operation")
        generation = 1 if name == "vm" else 2
        owner = first_owner if name == "vm" else second_owner
        expected_operation = dict(prepared[name])
        expected_operation.update(
            {
                "dispatch_generation": generation,
                "dispatch_owner": owner,
                **settled_updates[name],
            }
        )
        _require(
            operation == expected_operation,
            f"final {name} Operation differs from History or external record",
        )

    certificate_state_v1 = _object(
        _json_file(directory, "certificate-state-v1.json"),
        "v1 Certificate state",
    )
    _require(
        certificate_state_v1
        == {
            "from_rule": 0,
            "history": {"hash": "0" * 64, "sequence": 0},
            "open_operations": {},
            "schema": 1,
            "settled": {"results": {}, "used": {}},
        },
        "v1 Certificate input state differs from an empty History",
    )
    certificate_state_v2 = _object(
        _json_file(directory, "certificate-state-v2.json"),
        "v2 Certificate state",
    )
    expected_open = {
        operation_ids[name]: {
            "costs": contracts[name][3],
            "id": operation_ids[name],
            "produces": contracts[name][4],
            "retry_safe": True,
        }
        for name in ("codex", "order")
    }
    _require(
        certificate_state_v2
        == {
            "from_rule": 1,
            "history": {"hash": events[9]["hash"], "sequence": 10},
            "open_operations": expected_open,
            "schema": 1,
            "settled": {
                "results": {"audited": 1},
                "used": {"audit-slot": 1},
            },
        },
        "v2 Certificate input was not the replayed two-open/one-settled state",
    )
    certificate_state_v2_reopen = _object(
        _json_file(directory, "certificate-state-v2-reopen.json"),
        "v2 reopen Certificate state",
    )
    _require(
        certificate_state_v2_reopen
        == {
            "from_rule": 2,
            "history": {"hash": events[10]["hash"], "sequence": 11},
            "open_operations": expected_open,
            "schema": 1,
            "settled": {
                "results": {"audited": 1},
                "used": {"audit-slot": 1},
            },
        },
        "reopen Certificate input was not the durable post-cutover state",
    )

    active_v1 = _object(_json_file(directory, "active-state-v1.json"), "v1 State")
    _require(
        active_v1
        == {
            "history": {"hash": events[0]["hash"], "sequence": 1},
            "operations": {},
            "requirement": requirement_v1,
            "rule": certificate_v1["rule"],
        },
        "v1 activation State differs from the first History event",
    )
    active_v2 = _object(_json_file(directory, "active-state-v2.json"), "v2 State")
    active_v2_rule = _object(active_v2.get("rule"), "active v2 Rule")
    _require(
        active_v2.get("history")
        == {"hash": events[10]["hash"], "sequence": 11}
        and active_v2.get("requirement") == requirement_v2
        and active_v2_rule == certificate_v2["rule"],
        "v2 activation State differs from the eleventh History event",
    )
    active_operations = _object(active_v2.get("operations"), "active v2 Operations")
    expected_active_phases = {"codex": "unknown", "order": "unknown", "vm": "succeeded"}
    expected_active_operations: dict[str, dict[str, Any]] = {}
    for name, operation_id in operation_ids.items():
        operation = dict(prepared[name])
        operation.update(
            {
                "phase": expected_active_phases[name],
                "dispatch_generation": 1,
                "dispatch_owner": first_owner,
            }
        )
        if name == "vm":
            operation.update(settled_updates[name])
        expected_active_operations[operation_id] = operation
    _require(
        active_operations == expected_active_operations,
        "v2 activation Operations differ from exact replay through sequence 10",
    )
    active_v2_reopen = _object(
        _json_file(directory, "active-state-v2-reopen.json"),
        "active v2 reopen State",
    )
    active_v2_reopen_rule = _object(
        active_v2_reopen.get("rule"), "active v2 reopen Rule"
    )
    _require(
        active_v2_reopen.get("history")
        == {"hash": events[11]["hash"], "sequence": 12}
        and active_v2_reopen.get("requirement") == requirement_v2
        and active_v2_reopen_rule == certificate_v2_reopen["rule"]
        and active_v2_reopen.get("operations") == active_operations,
        "reopen activation State differs from the twelfth History event",
    )
    for label, active, generation in (
        ("v1", active_v1, 1),
        ("v2", active_v2, 2),
        ("v2-reopen", active_v2_reopen, 3),
    ):
        _require(
            _json_file(directory, f"cutover-{label}.json")
            == {
                "state": active,
                "bindings": [_vm_binding(run_id, generation, vm_backend)],
            },
            f"{label} cutover response differs from its committed State and binding",
        )
    return {
        "events": events,
        "history_hash": events[-1]["hash"],
        "requirements": (requirement_v1, requirement_v2),
        "operation_ids": operation_ids,
        "bodies": bodies,
        "external": external,
        "stats": stats,
        "state": state,
        "first_owner": first_owner,
        "second_owner": second_owner,
        "vm_host_instance_ids": vm_host_instance_ids,
        "certificates": (certificate_v1, certificate_v2, certificate_v2_reopen),
    }


def _docker_service(item: Mapping[str, Any]) -> str | None:
    config = _object(item.get("Config"), "Docker configuration")
    labels = _object(config.get("Labels"), "Docker labels")
    allowed = {
        "com.docker.compose.container-number",
        "com.docker.compose.project",
        "com.docker.compose.service",
        "com.docker.compose.version",
        "io.safe-change.source-tree.sha256",
        "org.opencontainers.image.revision",
    }
    _require(set(labels) <= allowed, "Docker projection retained another label")
    if "com.docker.compose.container-number" not in labels:
        return None
    service = labels.get("com.docker.compose.service")
    return service if isinstance(service, str) else None


def _integrated_inspect_object(value: Any, label: str) -> dict[str, Any]:
    item = _object(value, label)
    base = dict(item)
    image_id = base.pop("Image", None)
    _inspect_object(base, label)
    _require(
        isinstance(image_id, str)
        and re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is not None,
        f"{label} omits its immutable Docker image identity",
    )
    return item


def _mount_map(item: Mapping[str, Any], label: str) -> dict[str, tuple[bool, str]]:
    result: dict[str, tuple[bool, str]] = {}
    for value in _list(item.get("Mounts"), f"{label} mounts"):
        mount = _object(value, f"{label} mount")
        _require(
            set(mount) == {"Destination", "RW", "Type"}
            and isinstance(mount.get("Destination"), str)
            and type(mount.get("RW")) is bool
            and mount.get("Type") == "bind",
            f"{label} retained a malformed or unnecessary mount field",
        )
        destination = str(mount["Destination"])
        _require(destination not in result, f"{label} repeats a mount destination")
        result[destination] = (bool(mount["RW"]), str(mount["Type"]))
    return result


def _config(item: Mapping[str, Any], label: str) -> dict[str, Any]:
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
        f"{label} is not the privacy-minimal Docker configuration",
    )
    return config


def _check_docker(
    directory: Path,
    run_id: str,
    provenance: Mapping[str, Any],
) -> dict[str, Any]:
    raw = _list(_json_file(directory, "docker-inspect.json"), "Docker inspection")
    _require(len(raw) == 7, "Docker inspection must contain exactly seven actors")
    inspected = [
        _integrated_inspect_object(value, f"Docker container {index}")
        for index, value in enumerate(raw, 1)
    ]
    _require(
        len({str(item["Id"]) for item in inspected}) == 7,
        "Docker inspection repeats a container identity",
    )
    by_service = {
        service: item
        for item in inspected
        if (service := _docker_service(item)) is not None
    }
    services = {"ingress", "order", "control", "payment", "inventory", "ledger"}
    _require(set(by_service) == services, "Docker inspection omitted a service")
    codex_values = [item for item in inspected if _docker_service(item) is None]
    codex = _integrated_inspect_object(
        _one(codex_values, "Codex container"), "Codex container"
    )
    _require(
        re.fullmatch(r"/safe-change-codex-[0-9a-f]{16}", str(codex["Name"]))
        is not None,
        "unmanaged container is not the isolated Codex process",
    )

    expected_image = "safe-change-runtime:" + run_id
    users: list[str] = []
    for label, item in [("Codex", codex), *sorted(by_service.items())]:
        _check_container_hardening(item, label)
        config = _config(item, label)
        _require(config.get("Image") == expected_image, f"{label} used another image")
        image_key = str(item["Name"])[1:] if label == "Codex" else str(item["Id"])
        _require(
            item.get("Image") == provenance["image_id"]
            and provenance["container_images"].get(image_key)
            == provenance["image_id"],
            f"{label} container is not joined to the immutable runtime image",
        )
        labels = _object(config.get("Labels"), f"{label} labels")
        _require(
            all(
                labels.get(key) == value
                for key, value in provenance["source_labels"].items()
            ),
            f"{label} image labels do not bind the producer source",
        )
        user = config.get("User")
        _require(
            isinstance(user, str)
            and re.fullmatch(r"[1-9][0-9]*:[1-9][0-9]*", user) is not None,
            f"{label} did not use a non-root numeric UID/GID",
        )
        users.append(user)
        _require(
            config.get("Hostname") == str(item["Id"])[:12],
            f"{label} hostname does not bind its container ID",
        )
    _require(len(set(users)) == 1, "Docker actors did not share the configured UID/GID")

    for service, item in by_service.items():
        labels = _object(_config(item, service).get("Labels"), f"{service} labels")
        _require(
            labels
            == {
                **provenance["source_labels"],
                "com.docker.compose.version": provenance["compose_version"],
                "com.docker.compose.container-number": "1",
                "com.docker.compose.project": run_id,
                "com.docker.compose.service": service,
            },
            f"{service} belongs to another Compose deployment",
        )
    codex_labels = _object(_config(codex, "Codex").get("Labels"), "Codex labels")
    _require(
        codex_labels == provenance["image_labels"],
        "Codex image label does not bind the deployment",
    )

    agent = run_id + "_agent"
    application = run_id + "_application"
    effects = run_id + "_effects"
    expected_networks = {
        "codex": [agent],
        "ingress": [agent, application],
        "order": [application],
        "control": [application, effects],
        "payment": [effects],
        "inventory": [effects],
        "ledger": [effects],
    }
    actors = {"codex": codex, **by_service}
    observed_networks = {
        name: sorted(_docker_networks(item, name)) for name, item in actors.items()
    }
    _require(
        observed_networks == expected_networks,
        "raw Docker inspection does not contain the exact three-domain cut",
    )
    primary_networks = {
        "codex": agent,
        "ingress": agent,
        "order": application,
        "control": application,
        "payment": effects,
        "inventory": effects,
        "ledger": effects,
    }
    for name, item in actors.items():
        host = _object(item.get("HostConfig"), f"{name} host configuration")
        _require(
            host.get("NetworkMode") == primary_networks[name],
            f"{name} primary Docker network differs",
        )

    expected_commands = {
        "ingress": [
            "/usr/local/bin/ingress",
            "-control-listen=0.0.0.0:8787",
            "-order-listen=0.0.0.0:8080",
            "-control-upstream=http://control:8787",
            "-order-upstream=http://order:8080",
        ],
        "order": [
            "/usr/local/bin/order",
            "-listen=0.0.0.0:8080",
            "-release=/config/order.json",
            "-control=http://control:8787",
            "-operation-token-file=/credentials/order-token",
        ],
        "control": [
            "/usr/local/bin/control",
            "-listen=0.0.0.0:8787",
            "-allow-nonloopback=true",
            "-history=/state/runtime.history",
            "-head-anchor=/anchor/runtime.head",
            "-admin-token-file=/credentials/admin-token",
            "-adapter-config=/config/adapters.json",
            "-sandbox-socket-dir=/sandbox-endpoints",
        ],
        "payment": [
            "/usr/local/bin/payment",
            "-listen=0.0.0.0:8081",
            "-state=/state/payment.history",
            "-drop-first-response=true",
        ],
        "inventory": [
            "/usr/local/bin/payment",
            "-listen=0.0.0.0:8081",
            "-state=/state/inventory.history",
            "-drop-first-response=true",
        ],
        "ledger": [
            "/usr/local/bin/payment",
            "-listen=0.0.0.0:8081",
            "-state=/state/ledger.history",
        ],
    }
    expected_mounts = {
        "ingress": {},
        "order": {
            "/config": (False, "bind"),
            "/credentials/order-token": (False, "bind"),
        },
        "control": {
            "/anchor": (True, "bind"),
            "/credentials": (False, "bind"),
            "/config": (False, "bind"),
            "/sandbox-endpoints": (True, "bind"),
            "/state": (True, "bind"),
        },
        "payment": {"/state": (True, "bind")},
        "inventory": {"/state": (True, "bind")},
        "ledger": {"/state": (True, "bind")},
    }
    for service, item in by_service.items():
        config = _config(item, service)
        _require(
            config.get("Entrypoint") is None
            and config.get("Cmd") == expected_commands[service]
            and config.get("WorkingDir") == "/",
            f"{service} executed another service command",
        )
        _require(
            _mount_map(item, service) == expected_mounts[service],
            f"{service} received another host mount or mount mode",
        )

    codex_config = _config(codex, "Codex")
    entrypoint = _list(codex_config.get("Entrypoint"), "Codex entrypoint")
    arguments = _list(codex_config.get("Cmd"), "Codex command")
    _require(
        len(entrypoint) == 1 and str(entrypoint[0]).endswith("/bin/codex"),
        "Codex container did not execute the native vendor binary",
    )
    _require(
        arguments
        == [
            "app-server",
            "--stdio",
            "-c",
            "analytics.enabled=false",
            "-c",
            "features.responses_websockets=false",
            "-c",
            "features.apps=false",
            "-c",
            "features.enable_mcp_apps=false",
            "-c",
            "features.plugins=false",
            "-c",
            "mcp_servers={}",
        ],
        "Codex App Server command enabled another integration",
    )
    codex_mounts = _mount_map(codex, "Codex")
    home = codex_mounts.get("/var/lib/safe-change/codex-home")
    working = codex_config.get("WorkingDir")
    _require(
        len(codex_mounts) == 3
        and home == (True, "bind")
        and isinstance(working, str)
        and codex_mounts.get(working) == (False, "bind")
        and len([value for value in codex_mounts.values() if value[0] is False]) == 2,
        "Codex workspace, account home, or vendor mounts differ",
    )

    network_values = _list(
        _json_file(directory, "docker-network-inspect.json"),
        "Docker network inspection",
    )
    _require(len(network_values) == 3, "Docker network inspection is incomplete")
    documents: dict[str, dict[str, Any]] = {}
    for value in network_values:
        document = _object(value, "Docker network")
        _require(
            set(document) == {"Containers", "Id", "Internal", "Name"}
            and isinstance(document.get("Name"), str)
            and isinstance(document.get("Id"), str)
            and document.get("Id"),
            "Docker network projection contains another field or lacks identity",
        )
        documents[str(document["Name"])] = document
    _require(
        set(documents) == {agent, application, effects},
        "Docker network inspection names another deployment",
    )
    _require(
        documents[agent].get("Internal") is False
        and documents[application].get("Internal") is True
        and documents[effects].get("Internal") is True,
        "Docker network internal flag differs from the three-domain cut",
    )
    expected_members = {
        agent: {"codex", "ingress"},
        application: {"ingress", "order", "control"},
        effects: {"control", "payment", "inventory", "ledger"},
    }
    for network_name, names in expected_members.items():
        attachments = _object(
            documents[network_name].get("Containers"),
            f"{network_name} memberships",
        )
        identifiers = {str(actors[name]["Id"]): name for name in names}
        _require(
            set(attachments) == set(identifiers),
            f"{network_name} has an unrecorded or missing member",
        )
        for identifier, name in identifiers.items():
            attachment = _object(
                attachments[identifier], f"{network_name} {name} attachment"
            )
            inspected_ip = _object(
                _docker_networks(actors[name], name).get(network_name),
                f"{network_name} {name} inspected address",
            ).get("IPAddress")
            _require(
                set(attachment) == {"IPv4Address", "Name"}
                and attachment.get("Name") == str(actors[name]["Name"])[1:]
                and isinstance(attachment.get("IPv4Address"), str)
                and str(attachment["IPv4Address"]).split("/", 1)[0] == inspected_ip,
                f"{network_name} {name} identity or address differs",
            )

    topology = _object(_json_file(directory, "network-topology.json"), "network topology")
    _require(
        topology
        == {
            "networks": expected_networks,
            "agent_to_effect_shared_networks": [],
            "order_to_effect_shared_networks": [],
            "fixed_actor_paths": {
                "codex": "ingress->control",
                "order": "control",
                "vm": (
                    "firecracker-vsock->host-sandbox-socket"
                    if provenance.get("vm_backend") == "firecracker"
                    else "qemu-guestfwd->host-sandbox-socket"
                ),
            },
        },
        "network summary differs from raw Docker inspection",
    )

    effect_ips = {
        name: _object(
            _docker_networks(actors[name], name).get(effects), f"{name} effects IP"
        ).get("IPAddress")
        for name in ("payment", "inventory", "ledger")
    }
    for name, address in effect_ips.items():
        _require(
            isinstance(address, str)
            and re.fullmatch(r"(?:[0-9]{1,3}\.){3}[0-9]{1,3}", address) is not None,
            f"{name} inspection omitted an IPv4 address",
        )
    probes = _list(_json_file(directory, "network-probes.json"), "network probes")
    labels = ["codex-ingress", "order-control"]
    urls = ["http://ingress:8080/healthz", "http://control:8787/healthz"]
    executors = [str(codex["Name"])[1:], str(actors["order"]["Id"])]
    for actor_name in ("codex", "order"):
        executor = (
            str(codex["Name"])[1:]
            if actor_name == "codex"
            else str(actors["order"]["Id"])
        )
        for effect_name in ("payment", "inventory", "ledger"):
            for suffix, url in (
                ("name", f"http://{effect_name}:8081/v1/stats"),
                ("ip", f"http://{effect_ips[effect_name]}:8081/v1/stats"),
            ):
                labels.append(f"{actor_name}-{effect_name}-{suffix}")
                urls.append(url)
                executors.append(executor)
    _require(
        len(probes) == 14
        and [value.get("label") if isinstance(value, dict) else None for value in probes]
        == labels,
        "network probes are incomplete or reordered",
    )
    prior_finish: int | None = None
    for index, value in enumerate(probes):
        probe = _object(value, f"network probe {index + 1}")
        _require(
            probe.get("command")
            == [
                "docker",
                "exec",
                executors[index],
                "wget",
                "-T",
                "2",
                "-qO-",
                urls[index],
            ],
            f"network probe {labels[index]} command differs",
        )
        started = probe.get("started_time_ns")
        finished = probe.get("finished_time_ns")
        _require(
            type(started) is int and type(finished) is int and 0 < started <= finished,
            f"network probe {labels[index]} has invalid timing",
        )
        if prior_finish is not None:
            _require(started >= prior_finish, "network probes overlap or are reordered")
        prior_finish = finished
        if index == 0:
            _require(
                probe.get("returncode") == 0
                and _loads(str(probe.get("output", "")).encode(), "ingress health")
                == {"kind": RESERVE_V1_KIND, "status": "ok", "version": "v1"},
                "positive Codex-to-ingress probe failed",
            )
        elif index == 1:
            _require(
                probe.get("returncode") == 0
                and _loads(str(probe.get("output", "")).encode(), "control health")
                == {"status": "ok"},
                "positive order-to-control probe failed",
            )
        else:
            _require(
                type(probe.get("returncode")) is int
                and probe.get("returncode") != 0,
                f"direct effect probe {labels[index]} unexpectedly succeeded",
            )

    control_values = _list(
        _json_file(directory, "control-after-restart-inspect.json"),
        "post-restart control inspection",
    )
    control_post = _integrated_inspect_object(
        _one(control_values, "post-restart control"), "post-restart control"
    )
    control = actors["control"]
    _check_container_hardening(control_post, "post-restart control")
    _require(
        control_post.get("Id") == control.get("Id")
        and control_post.get("Image") == provenance["image_id"]
        and _config(control_post, "post-restart control")
        == _config(control, "initial control")
        and _docker_networks(control_post, "post-restart control")
        == _docker_networks(control, "initial control")
        and _mount_map(control_post, "post-restart control")
        == _mount_map(control, "initial control"),
        "control restart changed container identity or confinement",
    )
    control_initial_state = _object(control.get("State"), "initial control State")
    control_post_state = _object(control_post.get("State"), "restarted control State")
    control_initial_start = _rfc3339_nanoseconds(
        control_initial_state.get("StartedAt"), "initial control start"
    )
    control_post_start = _rfc3339_nanoseconds(
        control_post_state.get("StartedAt"), "restarted control start"
    )
    _require(
        control_initial_state.get("Running") is True
        and control_post_state.get("Running") is True
        and type(control_initial_state.get("Pid")) is int
        and type(control_post_state.get("Pid")) is int
        and control_initial_state["Pid"] > 0
        and control_post_state["Pid"] > 0
        and control_initial_state.get("Pid") != control_post_state.get("Pid")
        and control_post_start > control_initial_start,
        "control restart did not replace its process",
    )
    crash = _object(_json_file(directory, "control-crash.json"), "control crash")
    crash_state = _object(crash.get("state"), "control crash State")
    crash_started = crash.get("started_time_ns")
    crash_finished = crash.get("finished_time_ns")
    docker_finished = _rfc3339_nanoseconds(
        crash_state.get("FinishedAt"), "SIGKILL finish time"
    )
    _require(
        crash
        == {
            "command": ["docker", "kill", "--signal", "KILL", str(control["Id"])],
            "container_id": str(control["Id"]),
            "pid_before": control_initial_state["Pid"],
            "started_time_ns": crash_started,
            "finished_time_ns": crash_finished,
            "returncode": 0,
            "state": {
                "ExitCode": 137,
                "FinishedAt": crash_state.get("FinishedAt"),
                "OOMKilled": False,
                "Pid": 0,
                "Running": False,
            },
        }
        and type(crash_started) is int
        and type(crash_finished) is int
        and control_initial_start < crash_started <= docker_finished <= crash_finished
        and crash_finished < control_post_start,
        "retained control fault is not an observed SIGKILL between two processes",
    )

    order_values = _list(
        _json_file(directory, "order-after-replacement-inspect.json"),
        "replacement order inspection",
    )
    order_post = _integrated_inspect_object(
        _one(order_values, "replacement order"), "replacement order"
    )
    order = actors["order"]
    _check_container_hardening(order_post, "replacement order")
    initial_order_config = _config(order, "initial order")
    replacement_order_config = _config(order_post, "replacement order")
    _require(
        order_post.get("Id") != order.get("Id")
        and order_post.get("Image") == provenance["image_id"]
        and provenance["container_images"].get(str(order_post["Id"]))
        == provenance["image_id"]
        and order_post.get("Name") == order.get("Name")
        and {
            key: value
            for key, value in replacement_order_config.items()
            if key != "Hostname"
        }
        == {key: value for key, value in initial_order_config.items() if key != "Hostname"}
        and replacement_order_config.get("Hostname") == str(order_post["Id"])[:12]
        and _docker_networks(order_post, "replacement order")
        == _docker_networks(order, "initial order")
        and _mount_map(order_post, "replacement order")
        == expected_mounts["order"],
        "order replacement changed release confinement or did not replace the container",
    )
    initial_order_start = _rfc3339_nanoseconds(
        _object(order.get("State"), "initial order State").get("StartedAt"),
        "initial order start",
    )
    replacement_order_start = _rfc3339_nanoseconds(
        _object(order_post.get("State"), "replacement order State").get("StartedAt"),
        "replacement order start",
    )
    _require(
        replacement_order_start > initial_order_start,
        "replacement order start time did not advance",
    )
    image_actor_keys = {
        str(codex["Name"])[1:],
        *(str(item["Id"]) for item in by_service.values()),
        str(order_post["Id"]),
    }
    _require(
        set(provenance["container_images"]) == image_actor_keys,
        "runtime image provenance does not cover the exact executed containers",
    )

    return {
        "codex_id": str(codex["Id"]),
        "codex_arguments": arguments,
        "control_pid_before": control_initial_state["Pid"],
        "control_pid_after": control_post_state["Pid"],
        "control_restart_start_ns": control_post_start,
        "control_crash_started_ns": int(crash_started),
        "control_crash_finished_ns": int(crash_finished),
        "order_id_before": str(order["Id"]),
        "order_id_after": str(order_post["Id"]),
        "order_replacement_start_ns": replacement_order_start,
        "probe_start_ns": probes[0]["started_time_ns"],
        "probe_finish_ns": probes[-1]["finished_time_ns"],
        "topology": topology,
        "effect_ips": effect_ips,
        "runtime_uid": int(users[0].split(":", 1)[0]),
    }


def _jsonl(path: Path, label: str) -> list[dict[str, Any]]:
    raw = _read(path, limit=32 << 20)
    lines = raw.splitlines()
    _require(lines and raw.endswith(b"\n"), f"{label} is empty or unterminated")
    records = [
        _object(_loads(line, f"{label} line {index}"), f"{label} record")
        for index, line in enumerate(lines, 1)
    ]
    _require(
        [record.get("sequence") for record in records]
        == list(range(1, len(records) + 1)),
        f"{label} sequence is not contiguous",
    )
    prior = 0
    for record in records:
        _require(
            set(record) == {"direction", "payload", "sequence", "time_ns"}
            and record.get("direction") in {
                "client_to_server",
                "server_to_client",
                "server_stderr",
                "meta",
            }
            and type(record.get("time_ns")) is int
            and record["time_ns"] > prior,
            f"{label} has an invalid record envelope or clock",
        )
        prior = int(record["time_ns"])
    return records


def _firecracker_supervisor_jsonl(
    path: Path,
    expected_instance_ids: Mapping[int, str] | None = None,
) -> list[dict[str, Any]]:
    """Read the durable Firecracker supervisor trace without QMP assumptions."""

    if expected_instance_ids is not None:
        _require(
            set(expected_instance_ids) == {1, 3}
            and all(
                isinstance(expected_instance_ids[generation], str)
                and bool(expected_instance_ids[generation])
                for generation in (1, 3)
            )
            and expected_instance_ids[1] != expected_instance_ids[3],
            "History does not contain two distinct Firecracker HostInstanceIDs",
        )
    label = "Firecracker supervisor"
    raw = _read(path, limit=1 << 20)
    lines = raw.splitlines()
    _require(lines and raw.endswith(b"\n"), f"{label} is empty or unterminated")
    records = [
        _object(_loads(line, f"{label} line {index}"), f"{label} record")
        for index, line in enumerate(lines, 1)
    ]
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
    _require(
        len(records) == len(expected),
        "Firecracker supervisor event count differs",
    )
    prior_time = 0
    prior_elapsed = 0
    base_keys = {"schema", "sequence", "event", "time_ns", "elapsed_ns"}
    process_keys = {"generation", "instance_id", "pid", "start_time_ticks"}
    for index, (record, (event, generation)) in enumerate(
        zip(records, expected), 1
    ):
        allowed_keys = base_keys | process_keys | {"details"}
        _require(
            set(record) <= allowed_keys
            and base_keys <= set(record)
            and record.get("schema") == 1
            and record.get("sequence") == index
            and record.get("event") == event
            and type(record.get("time_ns")) is int
            and record["time_ns"] > prior_time
            and type(record.get("elapsed_ns")) is int
            and record["elapsed_ns"] > prior_elapsed,
            "Firecracker supervisor sequence or clock differs",
        )
        if generation == 0:
            _require(
                not (process_keys & set(record)),
                "global Firecracker supervisor event is process-bound",
            )
        else:
            _require(
                process_keys <= set(record)
                and record.get("generation") == generation
                and isinstance(record.get("instance_id"), str)
                and bool(record["instance_id"])
                and (
                    expected_instance_ids is None
                    or record["instance_id"]
                    == expected_instance_ids[generation]
                )
                and type(record.get("pid")) is int
                and record["pid"] > 0
                and type(record.get("start_time_ticks")) is int
                and record["start_time_ticks"] > 0,
                "Firecracker supervisor process binding differs",
            )
        if "details" in record:
            _object(record["details"], "Firecracker supervisor details")
        if event == "process-stopped":
            details = _object(
                record.get("details"),
                f"Firecracker generation {generation} stop details",
            )
            _require(
                details
                == {
                    "exit_confirmed": True,
                    "termination": "supervisor",
                },
                f"Firecracker generation {generation} was not stopped by the supervisor",
            )
        prior_time = int(record["time_ns"])
        prior_elapsed = int(record["elapsed_ns"])
    return records


def _firecracker_api_jsonl(
    path: Path,
    *,
    generation: int,
    expected_instance_id: str,
) -> list[dict[str, Any]]:
    label = f"Firecracker API generation {generation}"
    raw = _read(path, limit=4 << 20)
    lines = raw.splitlines()
    _require(lines and raw.endswith(b"\n"), f"{label} trace is empty or unterminated")
    records = [
        _object(_loads(line, f"{label} line {index}"), f"{label} record")
        for index, line in enumerate(lines, 1)
    ]
    prior_time = 0
    allowed = {
        "sequence",
        "time_ns",
        "method",
        "path",
        "request",
        "status",
        "response",
    }
    for index, record in enumerate(records, 1):
        _require(
            set(record) <= allowed
            and {"sequence", "time_ns", "method", "path", "status"}
            <= set(record)
            and record.get("sequence") == index
            and type(record.get("time_ns")) is int
            and record["time_ns"] > prior_time
            and isinstance(record.get("method"), str)
            and isinstance(record.get("path"), str)
            and type(record.get("status")) is int
            and record["status"] in {200, 204},
            f"{label} envelope or clock differs",
        )
        prior_time = int(record["time_ns"])

    states = [
        _object(record.get("response"), f"{label} instance response")
        for record in records
        if record.get("method") == "GET" and record.get("path") == "/"
    ]
    _require(
        bool(states)
        and all(state.get("id") == expected_instance_id for state in states),
        f"{label} instance ID differs from the committed HostInstanceID",
    )

    def request(method: str, api_path: str) -> dict[str, Any]:
        matches = [
            record
            for record in records
            if record.get("method") == method and record.get("path") == api_path
        ]
        _require(
            len(matches) == 1,
            f"{label} does not contain exactly one {method} {api_path}",
        )
        return _object(matches[0].get("request"), f"{label} {api_path} request")

    if generation == 1:
        vsock = request("PUT", "/vsock")
        snapshot = request("PUT", "/snapshot/create")
        _require(
            vsock.get("uds_path") == "<vm-evidence>/vsock-g1"
            and snapshot.get("snapshot_path")
            == "<vm-evidence>/snapshot.state"
            and snapshot.get("mem_file_path")
            == "<vm-evidence>/snapshot.memory",
            "generation 1 Firecracker API trace retained non-canonical private paths",
        )
    elif generation == 3:
        load = request("PUT", "/snapshot/load")
        override = _object(
            load.get("vsock_override"), "generation 3 Firecracker vsock override"
        )
        _require(
            override.get("uds_path") == "<vm-evidence>/vsock-g3",
            "generation 3 Firecracker API trace retained a non-canonical private path",
        )
    else:
        raise EvidenceError(f"unsupported Firecracker generation {generation}")
    return records


def _check_firecracker_vm(
    directory: Path,
    runtime_dir: Path | None,
    provenance: Mapping[str, Any],
    run_id: str,
    purchase_id: str,
    host_instance_ids: Mapping[int, str],
    operation_id: str,
    external: Mapping[str, Any],
    ledger_ip: str,
) -> dict[str, Any]:
    """Delegate byte-level Firecracker evidence checks to the Go checker.

    The retained directory is checked with source-provenance-selected runtime
    source, rather than trusting the VM result summary.  Python still binds
    that result and the two VMM PIDs to the top-level runner result below.
    """
    _require(runtime_dir is not None, "Firecracker checker source is unavailable")
    _require(
        set(host_instance_ids) == {1, 2, 3}
        and all(
            isinstance(host_instance_ids[generation], str)
            and bool(host_instance_ids[generation])
            for generation in (1, 2, 3)
        )
        and len(set(host_instance_ids.values())) == 3,
        "History does not contain three distinct sandbox HostInstanceIDs",
    )
    expected_instance_ids = {
        generation: host_instance_ids[generation] for generation in (1, 3)
    }
    checker_path = "runtime/cmd/check-firecracker-evidence/main.go"
    source_files = _object(provenance.get("source_files"), "source file hashes")
    expected_digest = source_files.get(checker_path)
    _require(
        isinstance(expected_digest, str)
        and re.fullmatch(r"[0-9a-f]{64}", expected_digest) is not None,
        "source provenance does not bind the Firecracker checker",
    )
    checker_source = _read(
        runtime_dir / "cmd" / "check-firecracker-evidence" / "main.go",
        limit=4 << 20,
    )
    _require(
        sha256(checker_source).hexdigest() == expected_digest,
        "committed Firecracker checker differs from source provenance",
    )
    vm_dir = directory / "vm"
    try:
        completed = subprocess.run(
            [
                "go",
                "run",
                "./cmd/check-firecracker-evidence",
                "-evidence",
                str(vm_dir),
            ],
            cwd=runtime_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            text=True,
            timeout=180.0,
        )
    except subprocess.TimeoutExpired:
        raise EvidenceError("Firecracker evidence checker timed out") from None
    _require(
        completed.returncode == 0,
        "Firecracker evidence checker rejected retained VM evidence: "
        + completed.stderr[-1000:].strip(),
    )
    result = _object(_json_file(vm_dir, "result.json"), "Firecracker VM result")
    assets = _object(_json_file(vm_dir, "assets.json"), "Firecracker VM assets")
    pids = result.get("firecracker_pids")
    first_reused = result.get("first_operation_reused")
    _require(
        result.get("backend") == "firecracker"
        and result.get("accelerator") == "kvm"
        and isinstance(pids, list) and len(pids) == 2
        and all(type(pid) is int and pid > 0 for pid in pids) and pids[0] != pids[1]
        and result.get("operation_call_id") == f"purchase/{purchase_id}/audit"
        and result.get("operation_id") == operation_id
        and result.get("direct_probe_host") == f"{ledger_ip}:8081"
        and result.get("successor_termination") == "host-after-final-result"
        and _object(assets.get("guest"), "Firecracker guest artifact").get("sha256")
        == provenance.get("firecracker_guest_sha256")
        and type(first_reused) is bool
        and result.get("restored_operation_reused") is True,
        "Firecracker VM summary is incomplete",
    )
    process_envelope = _object(
        _json_file(vm_dir, "firecracker-processes.json"),
        "Firecracker process identities",
    )
    processes = _list(
        process_envelope.get("processes"), "Firecracker process identity list"
    )
    process_by_generation: dict[int, dict[str, Any]] = {}
    for value in processes:
        process = _object(value, "Firecracker process identity")
        generation = process.get("generation")
        _require(
            type(generation) is int
            and generation in {1, 3}
            and generation not in process_by_generation,
            "Firecracker process generations are incomplete or duplicated",
        )
        process_by_generation[generation] = process
    _require(
        process_envelope.get("schema") == 1
        and set(process_envelope) == {"schema", "processes"}
        and set(process_by_generation) == {1, 3}
        and all(
            process_by_generation[generation].get("id")
            == expected_instance_ids[generation]
            and process_by_generation[generation].get("pid")
            == pids[index]
            and process_by_generation[generation].get("termination")
            == "supervisor"
            for index, generation in enumerate((1, 3))
        ),
        "Firecracker process identity or supervisor termination differs",
    )
    supervisor = _firecracker_supervisor_jsonl(
        vm_dir / "firecracker-supervisor.jsonl",
        expected_instance_ids,
    )
    operation_results = {
        record.get("generation"): _object(
            record.get("details"),
            f"Firecracker generation {record.get('generation')} operation result",
        )
        for record in supervisor
        if record.get("event") == "operation-result"
    }
    _require(
        operation_results
        == {
            1: {"operation_id": operation_id, "reused": first_reused},
            3: {"operation_id": operation_id, "reused": True},
        },
        "Firecracker supervisor Operation reuse differs from the VM summary",
    )
    for generation in (1, 3):
        _firecracker_api_jsonl(
            vm_dir / f"firecracker-api-g{generation}.jsonl",
            generation=generation,
            expected_instance_id=expected_instance_ids[generation],
        )
    request = _object(
        _json_file(vm_dir, "guest-request.json"), "Firecracker guest request"
    )
    expected_call = f"purchase/{purchase_id}/audit"
    _require(
        set(request) == {"call_id", "kind", "body"}
        and request.get("call_id") == expected_call
        and request.get("kind") == AUDIT_KIND
        and isinstance(request.get("body"), str),
        "Firecracker guest request is not bound to this integrated run",
    )
    try:
        body = json.loads(base64.b64decode(request["body"], validate=True))
    except (ValueError, json.JSONDecodeError):
        raise EvidenceError(
            "Firecracker guest request body is not valid base64 JSON"
        ) from None
    _require(
        body == {"purchase_id": purchase_id, "run_id": run_id},
        "Firecracker guest request body belongs to another run",
    )
    expected_outcome = {
        "operation_id": operation_id,
        "phase": "succeeded",
        "status_code": 200,
        "body": base64.b64encode(external["receipt_body"]).decode(),
        "result_hash": external["gateway_result_hash"],
        "recovered_by_query": False,
    }
    guest_results = _object(
        _json_file(vm_dir, "guest-results.json"), "Firecracker guest results"
    )
    _require(
        guest_results
        == {
            "schema": 1,
            "first": {
                "event": "RESULT",
                "status": 200,
                "body": {**expected_outcome, "reused": first_reused},
            },
            "restored": {
                "event": "RESULT",
                "status": 200,
                "body": {**expected_outcome, "reused": True},
            },
        },
        "Firecracker guest results differ from the durable History outcome",
    )
    # Relay evidence identifies the pinned control-socket target and independently
    # observes its peer PID. Do not infer peer device/inode from either value;
    # future peer identity fields must likewise be observed and retained.
    sandbox_identities: dict[int, dict[str, int]] = {}
    for generation in (1, 3):
        path = vm_dir / f"firecracker-relay-g{generation}.jsonl"
        raw = _read(path, limit=1 << 20)
        lines = raw.splitlines()
        _require(
            len(lines) >= 2 and len(lines) % 2 == 0 and raw.endswith(b"\n"),
            f"Firecracker relay generation {generation} trace is incomplete",
        )
        identities = set()
        sandbox_peer_pids = set()
        byte_records: list[dict[str, Any]] = []
        for index, line in enumerate(lines, 1):
            record = _object(
                _loads(line, f"Firecracker relay g{generation} line {index}"),
                f"Firecracker relay g{generation} record",
            )
            device = record.get("sandbox_device")
            inode = record.get("sandbox_inode")
            _require(
                type(device) is int
                and device > 0
                and type(inode) is int
                and inode > 0,
                f"Firecracker relay generation {generation} lacks sandbox identity",
            )
            identities.add((int(device), int(inode)))
            event = record.get("event")
            expected_event = "accept" if index % 2 == 1 else "bytes"
            _require(
                event == expected_event,
                f"Firecracker relay generation {generation} attempts are reordered",
            )
            sandbox_peer_pid = record.get("sandbox_peer_pid")
            if event == "bytes":
                guest_to_host = record.get("guest_to_host_bytes")
                host_to_guest = record.get("host_to_guest_bytes")
                _require(
                    type(sandbox_peer_pid) is int
                    and sandbox_peer_pid > 0
                    and type(guest_to_host) is int
                    and guest_to_host > 0
                    and type(host_to_guest) is int
                    and host_to_guest >= 0
                    and (index != len(lines) or host_to_guest > 0),
                    f"Firecracker relay generation {generation} lacks an observed "
                    "sandbox peer PID or complete byte counts",
                )
                sandbox_peer_pids.add(int(sandbox_peer_pid))
                byte_records.append(record)
            else:
                _require(
                    "sandbox_peer_pid" not in record,
                    f"Firecracker relay generation {generation} attached a peer PID "
                    "to a non-bytes event",
                )
        _require(
            len(identities) == 1,
            f"Firecracker relay generation {generation} changed sandbox identity",
        )
        _require(
            len(sandbox_peer_pids) == 1,
            f"Firecracker relay generation {generation} changed sandbox peer PID",
        )
        if generation == 1 and first_reused:
            _require(
                len(byte_records) >= 2
                and any(
                    record.get("host_to_guest_bytes") == 0
                    for record in byte_records[:-1]
                ),
                "Firecracker first-generation reuse lacks a prior lost response",
            )
        device, inode = identities.pop()
        sandbox_identities[generation] = {
            "device": device,
            "inode": inode,
            "sandbox_peer_pid": sandbox_peer_pids.pop(),
        }
    return {
        "backend": "firecracker",
        "result": result,
        "firecracker_pids": pids,
        "host_instance_ids": expected_instance_ids,
        "sandbox_identities": sandbox_identities,
    }


def _check_vm(
    directory: Path,
    run_id: str,
    purchase_id: str,
    ledger_ip: str,
) -> dict[str, Any]:
    vm_dir = directory / "vm"
    host_tools = _object(_json_file(vm_dir, "host-tools.json"), "VM host tools")
    _require(
        host_tools
        == {
            "schema": 1,
            "tools": {
                "qemu-system-x86_64": {
                    "path": "/usr/bin/qemu-system-x86_64",
                    "sha256": QEMU_SYSTEM_SHA,
                    "version": "QEMU emulator version 8.2.2 (Debian 1:8.2.2+ds-0ubuntu1.18)",
                },
                "qemu-img": {
                    "path": "/usr/bin/qemu-img",
                    "sha256": QEMU_IMAGE_SHA,
                    "version": "qemu-img version 8.2.2 (Debian 1:8.2.2+ds-0ubuntu1.18)",
                },
                "nc": {
                    "path": "/usr/bin/nc.openbsd",
                    "sha256": NETCAT_SHA,
                    "version": "OpenBSD netcat (Debian patchlevel 1.226-1ubuntu2)",
                },
            },
        },
        "VM host tools differ from the pinned executable set",
    )
    _require(
        _json_file(vm_dir, "base-image-provenance.json")
        == {
            "schema": 1,
            "bytes": 624105472,
            "sha256": BASE_IMAGE_SHA,
            "private_backing_copy": True,
            "file_mode": "0600",
        },
        "QEMU did not use a run-private post-copy-verified base image",
    )
    call_id = f"purchase/{purchase_id}/audit"
    request_value = {
        "call_id": call_id,
        "kind": AUDIT_KIND,
        "body": base64.b64encode(
            _canonical({"purchase_id": purchase_id, "run_id": run_id})
        ).decode(),
    }
    request_data = (
        json.dumps(request_value, sort_keys=True, indent=2) + "\n"
    ).encode()
    _require(
        _read(vm_dir / "guest-request.json") == request_data,
        "VM guest request contains routing, credentials, or another field set",
    )
    guest_script = _read(vm_dir / "guest-script.sh").decode("utf-8", errors="strict")
    _require(
        guest_script
        == _expected_vm_guest_script(
            request_data,
            f"http://{ledger_ip}:8081/v1/stats",
        )
        and "Authorization" not in guest_script
        and "Bearer" not in guest_script
        and "/v1/charge" not in guest_script,
        "VM guest script differs from the credential-free host-bound boundary",
    )
    result = _object(_json_file(vm_dir, "result.json"), "VM result")
    expected_result = {
        "accelerator": result.get("accelerator"),
        "base_image_sha256": BASE_IMAGE_SHA,
        "cpus": 2,
        "direct_effect": "blocked_before_and_after_restore",
        "first_operation_reused": False,
        "full_linux_guest": True,
        "guest_forwards": ["metadata-gate", "host-bound-sandbox"],
        "guest_credential_free": True,
        "guest_kernel": result.get("guest_kernel"),
        "guest_request_fields": ["call_id", "kind", "body"],
        "implicit_nics_disabled": True,
        "machine": "q35",
        "memory_mib": 1024,
        "network_backend": "qemu-user-restrict-on",
        "operation_call_id": call_id,
        "operation_kind": AUDIT_KIND,
        "qemu_pid": result.get("qemu_pid"),
        "restored_operation_reused": True,
        "sandbox_transport": "host-unix-socket",
        "schema": 1,
        "snapshot": "before_purchase",
        "cutover_while_paused": True,
        "restore_loaded_before_resume": True,
        "whole_vm_restored": True,
    }
    _require(
        result.get("accelerator") in {"tcg", "kvm"}
        and isinstance(result.get("guest_kernel"), str)
        and type(result.get("qemu_pid")) is int
        and result["qemu_pid"] > 0
        and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+-[0-9]+-generic", result["guest_kernel"])
        is not None
        and result == expected_result,
        "VM result does not identify the expected full Linux restore",
    )

    qemu = _object(_json_file(vm_dir, "qemu-command.json"), "QEMU command")
    arguments = _list(qemu.get("arguments"), "QEMU arguments")
    _require(
        set(qemu) == {"arguments", "executable", "schema"}
        and qemu.get("schema") == 1
        and qemu.get("executable") == "qemu-system-x86_64",
        "QEMU command envelope differs",
    )
    netdev_indices = [index for index, value in enumerate(arguments) if value == "-netdev"]
    _require(len(netdev_indices) == 1, "QEMU did not use exactly one explicit netdev")
    netdev_index = netdev_indices[0]
    _require(netdev_index + 1 < len(arguments), "QEMU netdev argument is absent")
    netdev = arguments[netdev_index + 1]
    _require(isinstance(netdev, str), "QEMU netdev is not text")
    matched = re.fullmatch(
        r"user,id=opnet,restrict=on,"
        r"guestfwd=tcp:10\.0\.2\.100:8000-cmd:/usr/bin/nc\.openbsd 127\.0\.0\.1 ([0-9]+),"
        r"guestfwd=tcp:10\.0\.2\.100:8787-cmd:/usr/bin/nc\.openbsd -U <host-sandbox-socket>",
        netdev,
    )
    _require(matched is not None, "QEMU user network has another forwarding boundary")
    assert matched is not None
    forwarded_port = int(matched.group(1))
    _require(
        1024 <= forwarded_port <= 65535,
        "QEMU metadata forward does not use an unprivileged host port",
    )
    expected_arguments = [
        "-name",
        "safe-change-shared-history-vm",
        "-machine",
        "q35",
        "-m",
        "1024",
        "-smp",
        "2",
        "-drive",
        "file=<vm-evidence>/guest.qcow2,if=virtio,format=qcow2,cache=none",
        "-display",
        "none",
        "-serial",
        "file:<vm-evidence>/guest.serial.log",
        "-monitor",
        "none",
        "-qmp",
        "unix:<vm-evidence>/qmp.sock,server=on,wait=off",
        "-no-reboot",
        "-nic",
        "none",
        "-netdev",
        netdev,
        "-device",
        "virtio-net-pci,netdev=opnet",
        "-smbios",
        "type=1,serial=ds=nocloud;s=http://10.0.2.100:8000/",
        "-accel",
        "tcg,thread=multi" if result["accelerator"] == "tcg" else "kvm",
    ]
    _require(
        arguments == expected_arguments
        and "hostfwd=" not in netdev
        and "Bearer" not in json.dumps(arguments)
        and "token" not in json.dumps(arguments).lower()
        and arguments.count("-nic") == 1,
        "QEMU command enabled another device, mount, or host forward",
    )
    process_command = _object(
        _json_file(vm_dir, "qemu-process-command.json"),
        "live QEMU process command",
    )
    _require(
        process_command
        == {
            "arguments": arguments,
            "executable": "qemu-system-x86_64",
            "executable_path": "/usr/bin/qemu-system-x86_64",
            "executable_sha256": QEMU_SYSTEM_SHA,
            "pid": result["qemu_pid"],
            "schema": 1,
            "source": "linux-proc-cmdline-and-exe-fd",
        },
        "retained /proc QEMU command differs from the planned launch boundary",
    )

    qmp_records = _jsonl(vm_dir / "qmp-protocol.jsonl", "QMP protocol")
    greeting = _object(qmp_records[0].get("payload"), "QMP greeting")
    greeting_body = _object(greeting.get("QMP"), "QMP greeting body")
    version = _object(greeting_body.get("version"), "QMP version")
    qmp_version = _object(
        version.get("qemu"),
        "QEMU version",
    )
    _require(
        qmp_records[0].get("direction") == "server_to_client"
        and all(type(qmp_version.get(part)) is int for part in ("major", "minor", "micro")),
        "QMP greeting is absent or malformed",
    )
    _require(
        qmp_version == {"major": 8, "minor": 2, "micro": 2},
        "QMP server version differs from the pinned QEMU executable",
    )
    client_records = [
        record
        for record in qmp_records
        if record.get("direction") == "client_to_server"
    ]
    expected_commands = [
        {"execute": "qmp_capabilities", "id": "command-1"},
        {"execute": "stop", "id": "command-2"},
        {"execute": "query-status", "id": "command-3"},
        {
            "arguments": {"command-line": "savevm before_purchase"},
            "execute": "human-monitor-command",
            "id": "command-4",
        },
        {"execute": "cont", "id": "command-5"},
        {"execute": "stop", "id": "command-6"},
        {"execute": "query-status", "id": "command-7"},
        {
            "arguments": {"command-line": "loadvm before_purchase"},
            "execute": "human-monitor-command",
            "id": "command-8",
        },
        {"execute": "query-status", "id": "command-9"},
        {"execute": "cont", "id": "command-10"},
    ]
    _require(
        [record.get("payload") for record in client_records] == expected_commands,
        "QMP did not perform the exact stop/save/continue/stop/load/continue sequence",
    )
    response_times: dict[str, int] = {}
    response_returns: dict[str, Any] = {}
    for command in expected_commands:
        command_id = str(command["id"])
        values = [
            record
            for record in qmp_records
            if record.get("direction") == "server_to_client"
            and isinstance(record.get("payload"), dict)
            and record["payload"].get("id") == command_id
        ]
        response = _object(_one(values, f"QMP response {command_id}"), "QMP response")
        payload = _object(response.get("payload"), f"QMP response {command_id} payload")
        _require(
            "return" in payload and "error" not in payload,
            f"QMP command {command_id} failed",
        )
        response_times[command_id] = int(response["time_ns"])
        response_returns[command_id] = payload["return"]
    client_times = {
        str(record["payload"]["id"]): int(record["time_ns"])
        for record in client_records
    }
    _require(
        all(
            client_times[f"command-{index}"] < response_times[f"command-{index}"]
            for index in range(1, 11)
        )
        and all(
            response_times[f"command-{index}"]
            < client_times[f"command-{index + 1}"]
            for index in range(1, 10)
        ),
        "QMP response clock precedes its command",
    )
    _require(
        response_returns["command-4"] == ""
        and response_returns["command-8"] == "",
        "QMP save or load command returned an unexpected warning",
    )
    for command_id in ("command-3", "command-7", "command-9"):
        response_values = [
            record["payload"]["return"]
            for record in qmp_records
            if record.get("direction") == "server_to_client"
            and isinstance(record.get("payload"), dict)
            and record["payload"].get("id") == command_id
        ]
        status = _object(
            _one(response_values, f"QMP paused status {command_id}"),
            f"QMP paused status {command_id}",
        )
        _require(
            status.get("status") == "paused" and status.get("running") is False,
            f"QEMU was not confirmed paused at {command_id}",
        )

    snapshots = _read(vm_dir / "snapshots.txt").decode("utf-8", errors="strict")
    _require(
        len(re.findall(r"(?m)^\s*[0-9]+\s+before_purchase\s+", snapshots)) == 1,
        "QEMU snapshot listing does not contain exactly before_purchase",
    )
    serial = _read(vm_dir / "guest.serial.log", limit=4 << 20).decode(
        "utf-8", errors="replace"
    )
    markers = [
        f"SAFE_CHANGE_VM_EXTERNAL_READY kernel={result['guest_kernel']}",
        "SAFE_CHANGE_VM_DIRECT_EFFECT_BLOCKED",
        "SAFE_CHANGE_VM_FIRST_SUCCEEDED reused=false",
        "SAFE_CHANGE_VM_DIRECT_EFFECT_BLOCKED",
        "SAFE_CHANGE_VM_RESTORED_SUCCEEDED reused=true",
    ]
    positions: list[int] = []
    offset = 0
    for marker in markers:
        position = serial.find(marker, offset)
        _require(position >= 0, f"VM serial log omitted marker {marker}")
        positions.append(position)
        offset = position + len(marker)
    _require(
        serial.count("SAFE_CHANGE_VM_EXTERNAL_READY") == 1
        and serial.count("SAFE_CHANGE_VM_DIRECT_EFFECT_BLOCKED") == 2
        and serial.count("SAFE_CHANGE_VM_FIRST_SUCCEEDED reused=false") == 1
        and serial.count("SAFE_CHANGE_VM_RESTORED_SUCCEEDED reused=true") == 1
        and "SAFE_CHANGE_VM_DIRECT_EFFECT_REACHABLE" not in serial
        and "SAFE_CHANGE_VM_EXTERNAL_UNEXPECTED" not in serial,
        "VM serial evidence contains a bypass, unexpected result, or duplicate marker",
    )
    _require(_read(vm_dir / "qemu.log") == b"", "QEMU emitted an unexpected error log")

    vm_events = _list(_json_file(directory, "vm-events.json"), "VM runner events")
    _require(
        len(vm_events) == 5
        and [value.get("event") if isinstance(value, dict) else None for value in vm_events]
        == [
            "snapshot-ready",
            "first-succeeded",
            "paused-after-first",
            "restore-loaded-paused",
            "completed",
        ],
        "VM runner events are incomplete or reordered",
    )
    snapshot_event = _object(vm_events[0], "snapshot-ready event")
    first_event = _object(vm_events[1], "first-succeeded event")
    paused_event = _object(vm_events[2], "paused VM event")
    loaded_event = _object(vm_events[3], "loaded-paused VM event")
    completed_event = _object(vm_events[4], "completed VM event")
    _require(
        snapshot_event
        == {
            "event": "snapshot-ready",
            "guest_kernel": result["guest_kernel"],
            "observed_time_ns": snapshot_event.get("observed_time_ns"),
        }
        and first_event
        == {
            "event": "first-succeeded",
            "observed_time_ns": first_event.get("observed_time_ns"),
            "operation_call_id": call_id,
        }
        and paused_event
        == {
            "event": "paused-after-first",
            "observed_time_ns": paused_event.get("observed_time_ns"),
            "operation_call_id": call_id,
        }
        and loaded_event
        == {
            "event": "restore-loaded-paused",
            "observed_time_ns": loaded_event.get("observed_time_ns"),
            "operation_call_id": call_id,
        }
        and {
            key: value
            for key, value in completed_event.items()
            if key not in {"event", "observed_time_ns"}
        }
        == result,
        "VM event payloads differ from the guest operation and final VM result",
    )
    times = [
        snapshot_event.get("observed_time_ns"),
        first_event.get("observed_time_ns"),
        paused_event.get("observed_time_ns"),
        loaded_event.get("observed_time_ns"),
        completed_event.get("observed_time_ns"),
    ]
    _require(
        all(type(value) is int for value in times)
        and response_times["command-4"] <= times[0]
        and times[0] < client_times["command-5"]
        and response_times["command-5"] < times[1]
        and times[1] < client_times["command-6"]
        and response_times["command-7"] <= times[2]
        and times[2] < client_times["command-8"]
        and response_times["command-9"] <= times[3]
        and times[3] < client_times["command-10"]
        and response_times["command-10"] < times[4],
        "VM events do not correlate with the raw QMP save/load clocks",
    )
    return {
        "result": result,
        "snapshot_time_ns": int(times[0]),
        "first_success_time_ns": int(times[1]),
        "paused_time_ns": int(times[2]),
        "loaded_paused_time_ns": int(times[3]),
        "completion_time_ns": int(times[4]),
        "qmp_greeting_time_ns": int(qmp_records[0]["time_ns"]),
        "save_command_time_ns": client_times["command-4"],
        "save_response_time_ns": response_times["command-4"],
        "pause_command_time_ns": client_times["command-6"],
        "pause_status_response_time_ns": response_times["command-7"],
        "load_command_time_ns": client_times["command-8"],
        "load_status_response_time_ns": response_times["command-9"],
        "resume_command_time_ns": client_times["command-10"],
        "resume_response_time_ns": response_times["command-10"],
        "qmp_records": len(qmp_records),
    }


def _check_protocol(
    directory: Path,
    run_id: str,
    purchase_id: str,
    operation_ids: Mapping[str, str],
    remotes: Mapping[str, str],
    codex_id: str,
    codex_arguments: list[Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    records = _jsonl(directory / "app-server.jsonl", "App Server protocol")
    payloads = [
        (record.get("direction"), record.get("payload"), record)
        for record in records
    ]
    starts = [
        payload
        for direction, payload, _ in payloads
        if direction == "meta"
        and isinstance(payload, dict)
        and payload.get("event") == "process_start"
    ]
    start = _object(_one(starts, "App Server process start"), "process start")
    command = _list(start.get("command"), "App Server process command")
    _require(
        len(command) >= 3
        and str(command[0]).endswith("/codex")
        and command[1:] == codex_arguments,
        "App Server process differs from raw Docker inspection",
    )
    command_text = json.dumps(command, sort_keys=True)
    _require(
        "model_providers" not in command_text
        and "authority_continuity_mock" not in command_text,
        "App Server installed a deterministic test provider",
    )
    stops = [
        payload
        for direction, payload, _ in payloads
        if direction == "meta"
        and isinstance(payload, dict)
        and payload.get("event") == "process_stop"
    ]
    _require(
        _object(_one(stops, "App Server process stop"), "process stop")
        == {"event": "process_stop", "returncode": 0},
        "App Server process did not exit successfully",
    )

    remote_notices = [
        payload
        for direction, payload, _ in payloads
        if direction == "server_to_client"
        and isinstance(payload, dict)
        and payload.get("method") == "remoteControl/status/changed"
    ]
    remote_params = _object(
        _object(_one(remote_notices, "remote-control status"), "remote status").get(
            "params"
        ),
        "remote-control params",
    )
    _require(
        remote_params.get("installationId") == "<redacted>"
        and remote_params.get("serverName") == codex_id[:12]
        and remote_params.get("status") == "disabled",
        "privacy-filtered App Server identity does not bind the Codex container",
    )
    rate_notices = [
        payload
        for direction, payload, _ in payloads
        if direction == "server_to_client"
        and isinstance(payload, dict)
        and payload.get("method") == "account/rateLimits/updated"
    ]
    _require(rate_notices, "App Server protocol omitted account rate notices")
    for value in rate_notices:
        params = _object(value.get("params"), "rate-limit params")
        _require(
            params.get("rateLimits") == {"redacted": True},
            "App Server account telemetry was not privacy-filtered",
        )

    thread_requests = [
        payload
        for direction, payload, _ in payloads
        if direction == "client_to_server"
        and isinstance(payload, dict)
        and payload.get("method") == "thread/start"
    ]
    thread_request = _object(_one(thread_requests, "thread/start request"), "thread/start")
    thread_params = _object(thread_request.get("params"), "thread/start params")
    requested_model = thread_params.get("model")
    cwd = thread_params.get("cwd")
    dynamic_tool = {
        "description": (
            "Complete the one approved purchase through the protected runtime. "
            "Call exactly once."
        ),
        "inputSchema": {
            "additionalProperties": False,
            "properties": {
                "purchase_id": {"enum": [purchase_id], "type": "string"}
            },
            "required": ["purchase_id"],
            "type": "object",
        },
        "name": TOOL_NAME,
        "type": "function",
    }
    expected_thread_params = {
            "approvalPolicy": "never",
            "cwd": cwd,
            "developerInstructions": (
                "Only complete_purchase is available. Do not inspect files, "
                "run commands, or request another tool."
            ),
            "dynamicTools": [dynamic_tool],
            "environments": [],
            "ephemeral": True,
            "sandbox": "read-only",
            "serviceName": "safe_change_runtime",
        }
    if "model" in thread_params:
        expected_thread_params["model"] = requested_model
    _require(
        (requested_model is None or isinstance(requested_model, str))
        and isinstance(cwd, str)
        and cwd
        and thread_params == expected_thread_params,
        "thread/start did not expose exactly one purchase tool and read-only sandbox",
    )
    thread_responses = [
        payload
        for direction, payload, _ in payloads
        if direction == "server_to_client"
        and isinstance(payload, dict)
        and payload.get("id") == thread_request.get("id")
        and isinstance(payload.get("result"), dict)
    ]
    thread_result = _object(
        _object(_one(thread_responses, "thread/start response"), "thread response").get(
            "result"
        ),
        "thread result",
    )
    thread = _object(thread_result.get("thread"), "Codex thread")
    thread_id = thread.get("id")
    sandbox = _object(thread_result.get("sandbox"), "thread sandbox")
    model = thread_result.get("model")
    _require(
        isinstance(thread_id, str)
        and thread_id
        and isinstance(model, str)
        and model
        and (requested_model is None or requested_model == model)
        and thread_result.get("cwd") == cwd
        and thread_result.get("modelProvider") == "openai"
        and thread_result.get("approvalPolicy") == "never"
        and sandbox == {"networkAccess": False, "type": "readOnly"},
        "real thread response changed model provider or sandbox boundary",
    )

    turn_requests = [
        payload
        for direction, payload, _ in payloads
        if direction == "client_to_server"
        and isinstance(payload, dict)
        and payload.get("method") == "turn/start"
    ]
    turn_request = _object(_one(turn_requests, "turn/start request"), "turn/start")
    prompt = (
        f"Experiment {run_id}: call {TOOL_NAME} exactly once with purchase_id "
        f"{purchase_id}. After it returns, reply exactly DONE."
    )
    _require(
        turn_request.get("params")
        == {"input": [{"text": prompt, "type": "text"}], "threadId": thread_id},
        "turn prompt is not bound to the retained run and purchase",
    )
    turn_responses = [
        payload
        for direction, payload, _ in payloads
        if direction == "server_to_client"
        and isinstance(payload, dict)
        and payload.get("id") == turn_request.get("id")
        and isinstance(payload.get("result"), dict)
    ]
    turn_result = _object(
        _object(_one(turn_responses, "turn/start response"), "turn response").get(
            "result"
        ),
        "turn result",
    )
    turn_id = _object(turn_result.get("turn"), "turn").get("id")
    _require(isinstance(turn_id, str) and turn_id, "turn response omitted its identity")

    allowed_types = {"agentMessage", "dynamicToolCall", "reasoning", "userMessage"}
    for direction, payload, _ in payloads:
        if (
            direction != "server_to_client"
            or not isinstance(payload, dict)
            or payload.get("method") not in {"item/started", "item/completed"}
        ):
            continue
        params = payload.get("params")
        item = params.get("item") if isinstance(params, dict) else None
        if isinstance(item, dict):
            _require(
                item.get("type") in allowed_types,
                f"Codex used undeclared item type {item.get('type')!r}",
            )

    tool_values = [
        (payload, record)
        for direction, payload, record in payloads
        if direction == "server_to_client"
        and isinstance(payload, dict)
        and payload.get("method") == "item/tool/call"
    ]
    tool_call, tool_record = _one(tool_values, "Codex dynamic tool call")
    tool_call = _object(tool_call, "tool call")
    tool_record = _object(tool_record, "tool record")
    tool_params = _object(tool_call.get("params"), "tool call params")
    provider_call_id = tool_params.get("callId")
    _require(
        tool_params
        == {
            "arguments": {"purchase_id": purchase_id},
            "callId": provider_call_id,
            "namespace": None,
            "threadId": thread_id,
            "tool": TOOL_NAME,
            "turnId": turn_id,
        }
        and isinstance(provider_call_id, str)
        and provider_call_id,
        "Codex tool identity or arguments differ",
    )
    callback_values = [
        (payload, record)
        for direction, payload, record in payloads
        if direction == "client_to_server"
        and isinstance(payload, dict)
        and payload.get("id") == tool_call.get("id")
        and isinstance(payload.get("result"), dict)
    ]
    callback_payload, callback_record = _one(callback_values, "tool callback response")
    callback_payload = _object(callback_payload, "callback payload")
    callback_record = _object(callback_record, "callback record")
    callback = _object(callback_payload.get("result"), "callback result")
    content = _list(callback.get("contentItems"), "callback content")
    _require(
        callback.get("success") is True and len(content) == 1,
        "tool callback was not one successful response",
    )
    callback_item = _object(content[0], "callback item")
    callback_text = callback_item.get("text")
    _require(
        callback_item.get("type") == "inputText" and isinstance(callback_text, str),
        "tool callback omitted its JSON text",
    )
    callback_value = _object(
        _loads(callback_text.encode(), "tool callback text"), "callback value"
    )
    _require(
        callback_value
        == {
            "operations": dict(operation_ids),
            "purchase_id": purchase_id,
            "remote_references": {
                "audit": remotes["vm"],
                "inventory": remotes["order"],
                "payment": remotes["codex"],
            },
            "status": "succeeded",
        },
        "Codex callback differs from the three durable external receipts",
    )

    completed_items = [
        payload.get("params", {}).get("item")
        for direction, payload, _ in payloads
        if direction == "server_to_client"
        and isinstance(payload, dict)
        and payload.get("method") == "item/completed"
        and isinstance(payload.get("params"), dict)
        and payload["params"].get("threadId") == thread_id
        and payload["params"].get("turnId") == turn_id
    ]
    completed_tools = [
        item
        for item in completed_items
        if isinstance(item, dict) and item.get("type") == "dynamicToolCall"
    ]
    completed_tool = _object(
        _one(completed_tools, "completed dynamic tool"), "completed tool"
    )
    _require(
        completed_tool.get("id") == provider_call_id
        and completed_tool.get("tool") == TOOL_NAME
        and completed_tool.get("arguments") == {"purchase_id": purchase_id}
        and completed_tool.get("status") == "completed"
        and completed_tool.get("success") is True,
        "completed Codex tool differs from the callback",
    )
    final_values = [
        item
        for item in completed_items
        if isinstance(item, dict)
        and item.get("type") == "agentMessage"
        and item.get("phase") == "final_answer"
    ]
    final_message = _object(_one(final_values, "final agent message"), "final message")
    _require(final_message.get("text") == "DONE", "Codex final answer differs from DONE")
    completion_values = [
        (payload, record)
        for direction, payload, record in payloads
        if direction == "server_to_client"
        and isinstance(payload, dict)
        and payload.get("method") == "turn/completed"
        and isinstance(payload.get("params"), dict)
        and payload["params"].get("threadId") == thread_id
        and payload["params"].get("turn", {}).get("id") == turn_id
    ]
    completion, completion_record = _one(completion_values, "turn completion")
    completion = _object(completion, "turn completion")
    completion_record = _object(completion_record, "turn completion record")
    completed_turn = _object(completion.get("params", {}).get("turn"), "completed turn")
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
        "model_provider": "openai",
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
        "process_start_ns": records[0]["time_ns"],
        "tool_call_ns": tool_record["time_ns"],
        "callback_ns": callback_record["time_ns"],
        "turn_completed_ns": completion_record["time_ns"],
        "process_stop_ns": records[-1]["time_ns"],
    }
    _require(
        timing["process_start_ns"]
        < timing["tool_call_ns"]
        < timing["callback_ns"]
        < timing["turn_completed_ns"]
        < timing["process_stop_ns"],
        "App Server raw clocks are inconsistent",
    )
    return summary, timing


def _expected_runtime_outcome(
    operation_id: str,
    external: Mapping[str, Any],
    *,
    reused: bool,
) -> dict[str, Any]:
    return {
        "body": base64.b64encode(external["receipt_body"]).decode(),
        "operation_id": operation_id,
        "phase": "succeeded",
        "recovered_by_query": False,
        "result_hash": external["gateway_result_hash"],
        "reused": reused,
        "status_code": 200,
    }


def _check_outcomes(
    directory: Path,
    operation_ids: Mapping[str, str],
    external: Mapping[str, Mapping[str, Any]],
) -> None:
    codex_unknown = _object(
        _json_file(directory, "codex-payment-unknown.json"), "Codex unknown result"
    )
    _require(
        codex_unknown
        == {
            "code": "outcome_unknown",
            "error": (
                "external operation outcome is unknown: Post "
                '"http://payment:8081/v1/charge": EOF'
            ),
            "outcome": {
                "operation_id": operation_ids["codex"],
                "phase": "unknown",
                "recovered_by_query": False,
                "result_hash": "",
                "reused": False,
            },
        },
        "Codex first payment did not retain the expected unknown outcome",
    )
    recovered_codex = _object(
        _json_file(directory, "codex-payment-recovered.json"),
        "recovered Codex payment",
    )
    _require(
        recovered_codex
        == _expected_runtime_outcome(
            operation_ids["codex"], external["codex"], reused=False
        ),
        "recovered Codex payment differs from the durable receipt",
    )

    inventory_unknown = _object(
        _json_file(directory, "inventory-unknown.json"), "inventory unknown result"
    )
    _require(
        inventory_unknown
        == {
            "release_version": "v1",
            "requested_kind": RESERVE_V1_KIND,
            "requested_target": "http://inventory:8081/v1/charge",
            "runtime": {
                "code": "outcome_unknown",
                "error": (
                    "external operation outcome is unknown: Post "
                    '"http://inventory:8081/v1/charge": EOF'
                ),
                "outcome": {
                    "operation_id": operation_ids["order"],
                    "phase": "unknown",
                    "recovered_by_query": False,
                    "result_hash": "",
                    "reused": False,
                },
            },
        },
        "v1 inventory request did not retain the expected unknown outcome",
    )
    inventory_recovered = _object(
        _json_file(directory, "inventory-recovered.json"),
        "recovered inventory result",
    )
    expected_recovered_order = {
        "release_version": "v2",
        "requested_kind": RESERVE_V2_KIND,
        "requested_target": "http://inventory:8081/v2/charge",
        "runtime": _expected_runtime_outcome(
            operation_ids["order"], external["order"], reused=False
        ),
    }
    _require(
        inventory_recovered == expected_recovered_order,
        "v2 order process did not recover the frozen v1 Operation",
    )

    retries = _object(_json_file(directory, "settled-retries.json"), "settled retries")
    _require(
        retries
        == {
            "codex": _expected_runtime_outcome(
                operation_ids["codex"], external["codex"], reused=True
            ),
            "order": {
                **{
                    key: value
                    for key, value in expected_recovered_order.items()
                    if key != "runtime"
                },
                "runtime": _expected_runtime_outcome(
                    operation_ids["order"], external["order"], reused=True
                ),
            },
        },
        "settled payment or inventory retry was not reused",
    )


def _check_timeline(
    directory: Path,
    docker: Mapping[str, Any],
    vm: Mapping[str, Any],
    protocol: Mapping[str, Any],
) -> dict[str, int]:
    timeline = _object(_json_file(directory, "timeline.json"), "run timeline")
    names = {
        "run_start_ns",
        "rule_v1_activated_ns",
        "vm_snapshot_ready_ns",
        "codex_tool_call_ns",
        "network_checks_finished_ns",
        "codex_payment_unknown_ns",
        "inventory_unknown_ns",
        "vm_first_succeeded_ns",
        "vm_paused_ns",
        "rule_v2_activated_ns",
        "order_replaced_ns",
        "control_restarted_ns",
        "vm_restore_loaded_ns",
        "sandbox_generation_3_ns",
        "vm_restore_completed_ns",
        "codex_turn_completed_ns",
        "run_facts_complete_ns",
    }
    _require(
        set(timeline) == names
        and all(type(timeline.get(name)) is int and timeline[name] > 0 for name in names),
        "run timeline fields or clocks are invalid",
    )
    ordered = [
        "run_start_ns",
        "rule_v1_activated_ns",
        "vm_snapshot_ready_ns",
        "codex_tool_call_ns",
        "network_checks_finished_ns",
        "codex_payment_unknown_ns",
        "inventory_unknown_ns",
        "vm_first_succeeded_ns",
        "vm_paused_ns",
        "rule_v2_activated_ns",
        "order_replaced_ns",
        "control_restarted_ns",
        "vm_restore_loaded_ns",
        "sandbox_generation_3_ns",
        "vm_restore_completed_ns",
        "codex_turn_completed_ns",
        "run_facts_complete_ns",
    ]
    _require(
        [timeline[name] for name in ordered]
        == sorted(timeline[name] for name in ordered)
        and len({timeline[name] for name in ordered}) == len(ordered),
        "run timeline does not preserve the claimed fault order",
    )
    one_second = 1_000_000_000
    _require(
        timeline["rule_v1_activated_ns"] < vm["qmp_greeting_time_ns"]
        and vm["save_response_time_ns"] <= timeline["vm_snapshot_ready_ns"]
        == vm["snapshot_time_ns"]
        and timeline["vm_snapshot_ready_ns"] < protocol["process_start_ns"]
        and protocol["tool_call_ns"] <= timeline["codex_tool_call_ns"]
        <= protocol["tool_call_ns"] + one_second
        and timeline["codex_tool_call_ns"] <= docker["probe_start_ns"]
        and docker["probe_finish_ns"] <= timeline["network_checks_finished_ns"]
        <= docker["probe_finish_ns"] + one_second
        and timeline["vm_first_succeeded_ns"] == vm["first_success_time_ns"]
        and timeline["vm_paused_ns"] == vm["paused_time_ns"]
        and vm["pause_status_response_time_ns"] <= timeline["vm_paused_ns"]
        and timeline["vm_paused_ns"] < timeline["rule_v2_activated_ns"]
        and docker["order_replacement_start_ns"] <= timeline["order_replaced_ns"]
        and timeline["order_replaced_ns"] < docker["control_crash_started_ns"]
        and docker["control_crash_finished_ns"]
        < docker["control_restart_start_ns"]
        <= timeline["control_restarted_ns"]
        and timeline["control_restarted_ns"] < vm["load_command_time_ns"]
        and vm["load_status_response_time_ns"]
        <= timeline["vm_restore_loaded_ns"]
        == vm["loaded_paused_time_ns"]
        and timeline["vm_restore_loaded_ns"]
        < timeline["sandbox_generation_3_ns"]
        < vm["resume_command_time_ns"]
        and vm["resume_response_time_ns"] < timeline["vm_restore_completed_ns"]
        == vm["completion_time_ns"]
        and timeline["vm_restore_completed_ns"] < protocol["callback_ns"]
        and protocol["turn_completed_ns"] <= timeline["codex_turn_completed_ns"]
        <= protocol["turn_completed_ns"] + one_second
        and protocol["process_stop_ns"] <= timeline["run_facts_complete_ns"],
        "raw Docker, App Server, VM, and runner clocks do not correlate",
    )
    return {name: int(timeline[name]) for name in names}


def _check_firecracker_timeline(
    directory: Path,
    docker: Mapping[str, Any],
    vm: Mapping[str, Any],
    protocol: Mapping[str, Any],
) -> dict[str, int]:
    """Bind outer runner observations to the Firecracker supervisor clock."""
    timeline = _object(_json_file(directory, "timeline.json"), "run timeline")
    ordered = [
        "run_start_ns",
        "rule_v1_activated_ns",
        "vm_snapshot_ready_ns",
        "codex_tool_call_ns",
        "network_checks_finished_ns",
        "codex_payment_unknown_ns",
        "inventory_unknown_ns",
        "vm_first_succeeded_ns",
        "vm_paused_ns",
        "rule_v2_activated_ns",
        "order_replaced_ns",
        "control_restarted_ns",
        "vm_restore_loaded_ns",
        "sandbox_generation_3_ns",
        "vm_restore_completed_ns",
        "codex_turn_completed_ns",
        "run_facts_complete_ns",
    ]
    _require(
        set(timeline) == set(ordered)
        and all(type(timeline.get(name)) is int and timeline[name] > 0 for name in ordered)
        and [timeline[name] for name in ordered] == sorted(timeline[name] for name in ordered)
        and len({timeline[name] for name in ordered}) == len(ordered),
        "Firecracker run timeline fields or fault order are invalid",
    )
    call_id = vm["result"].get("operation_call_id")
    events = _list(_json_file(directory, "vm-events.json"), "VM runner events")
    expected_events = [
        "snapshot-ready",
        "first-succeeded",
        "paused-after-first",
        "restore-loaded-paused",
        "completed",
    ]
    _require(
        len(events) == 5
        and [value.get("event") if isinstance(value, dict) else None for value in events]
        == expected_events,
        "Firecracker VM events are incomplete or reordered",
    )
    event_values = [
        _object(value, f"Firecracker VM event {index}")
        for index, value in enumerate(events)
    ]
    snapshot, first, paused, loaded, completed = event_values
    _require(
        snapshot == {
            "event": "snapshot-ready",
            "guest_kernel": "6.1.155",
            "firecracker_version": "1.16.1",
            "observed_time_ns": snapshot.get("observed_time_ns"),
        }
        and first
        == {
            "event": "first-succeeded",
            "operation_call_id": call_id,
            "observed_time_ns": first.get("observed_time_ns"),
        }
        and paused
        == {
            "event": "paused-after-first",
            "operation_call_id": call_id,
            "observed_time_ns": paused.get("observed_time_ns"),
        }
        and loaded
        == {
            "event": "restore-loaded-paused",
            "operation_call_id": call_id,
            "observed_time_ns": loaded.get("observed_time_ns"),
        }
        and {
            key: value
            for key, value in completed.items()
            if key not in {"event", "observed_time_ns"}
        }
        == vm["result"],
        "Firecracker VM events do not bind the guest result",
    )
    observed = [value.get("observed_time_ns") for value in event_values]
    _require(
        all(type(value) is int and value > 0 for value in observed)
        and observed == [
            timeline["vm_snapshot_ready_ns"],
            timeline["vm_first_succeeded_ns"],
            timeline["vm_paused_ns"],
            timeline["vm_restore_loaded_ns"],
            timeline["vm_restore_completed_ns"],
        ],
        "Firecracker VM event clocks differ from top-level timeline",
    )
    supervisor = _firecracker_supervisor_jsonl(
        directory / "vm" / "firecracker-supervisor.jsonl"
    )
    by_event_generation = {
        (record.get("event"), record.get("generation")): record
        for record in supervisor
        if isinstance(record, dict)
    }
    required = [
        ("run-started", None),
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
        ("run-completed", None),
    ]
    _require(
        all(
            key in by_event_generation
            and type(by_event_generation[key].get("time_ns")) is int
            for key in required
        ),
        "Firecracker supervisor omits restored causal events",
    )
    supervisor_time = {
        key: int(by_event_generation[key]["time_ns"]) for key in required
    }
    one_second = 1_000_000_000
    _require(
        timeline["rule_v1_activated_ns"]
        < supervisor_time[("run-started", None)]
        < supervisor_time[("snapshot-created-paused", 1)]
        < supervisor_time[("relay-armed-paused", 1)]
        < timeline["vm_snapshot_ready_ns"]
        < protocol["process_start_ns"]
        and protocol["tool_call_ns"]
        <= timeline["codex_tool_call_ns"]
        <= protocol["tool_call_ns"] + one_second
        and timeline["codex_tool_call_ns"] <= docker["probe_start_ns"]
        and docker["probe_finish_ns"]
        <= timeline["network_checks_finished_ns"]
        <= docker["probe_finish_ns"] + one_second
        and supervisor_time[("relay-armed-paused", 1)]
        < supervisor_time[("vm-resumed", 1)]
        and timeline["inventory_unknown_ns"]
        < supervisor_time[("vm-resumed", 1)]
        < supervisor_time[("operation-result", 1)]
        < timeline["vm_first_succeeded_ns"]
        < supervisor_time[("vm-paused", 1)]
        < supervisor_time[("process-stopped", 1)]
        < timeline["vm_paused_ns"]
        < timeline["rule_v2_activated_ns"]
        and docker["order_replacement_start_ns"]
        <= timeline["order_replaced_ns"]
        < docker["control_crash_started_ns"]
        and docker["control_crash_finished_ns"]
        < docker["control_restart_start_ns"]
        <= timeline["control_restarted_ns"]
        < supervisor_time[("process-started", 3)]
        < supervisor_time[("snapshot-loaded-paused", 3)]
        < timeline["vm_restore_loaded_ns"]
        < timeline["sandbox_generation_3_ns"]
        < supervisor_time[("relay-armed-paused", 3)]
        < supervisor_time[("vm-resumed", 3)]
        < supervisor_time[("operation-result", 3)]
        < supervisor_time[("process-stopped", 3)]
        < supervisor_time[("run-completed", None)]
        < timeline["vm_restore_completed_ns"]
        < protocol["callback_ns"]
        and protocol["turn_completed_ns"]
        <= timeline["codex_turn_completed_ns"]
        <= protocol["turn_completed_ns"] + one_second
        and protocol["process_stop_ns"] <= timeline["run_facts_complete_ns"],
        "raw Docker, App Server, Firecracker, and runner clocks do not correlate",
    )
    return {name: int(timeline[name]) for name in ordered}


def _check_sandbox_lifecycle(
    directory: Path,
    docker: Mapping[str, Any],
    timeline: Mapping[str, int],
    *,
    vm_backend: str = "qemu",
    vm: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    records = _list(
        _json_file(directory, "sandbox-lifecycle.json"),
        "sandbox endpoint lifecycle",
    )
    _require(len(records) == 5, "sandbox endpoint lifecycle is incomplete")
    values = [
        _object(record, f"sandbox lifecycle record {index}")
        for index, record in enumerate(records, 1)
    ]
    basename = "sandbox-" + sha256(VM_SANDBOX_ID.encode()).hexdigest()[:32] + ".sock"
    published: dict[int, int] = {}
    published_inodes: dict[int, int] = {}
    published_devices: dict[int, int] = {}
    for value, generation in zip((values[0], values[1], values[4]), (1, 2, 3)):
        observed = value.get("observed_time_ns")
        inode = value.get("inode")
        device = value.get("device")
        expected_publication = {
            "event": "published",
            "generation": generation,
            "observed_time_ns": observed,
            "path_basename": basename,
            "parent_mode": "0700",
            "socket_mode": "0600",
            "owner_uid": docker["runtime_uid"],
            "inode": inode,
            "health_status": 200,
        }
        if vm_backend == "firecracker":
            expected_publication["device"] = device
        _require(
            value == expected_publication
            and type(observed) is int
            and type(inode) is int
            and observed > 0
            and inode > 0,
            f"sandbox generation {generation} was not observed as a private healthy socket",
        )
        published[generation] = int(observed)
        published_inodes[generation] = int(inode)
        if vm_backend == "firecracker":
            _require(
                type(device) is int and device > 0,
                f"sandbox generation {generation} lacks a device identity",
            )
            published_devices[generation] = int(device)
    stale = values[2]
    stale_time = stale.get("observed_time_ns")
    _require(
        stale
        == {
            "event": "stale-after-control-sigkill",
            "generation": 2,
            "observed_time_ns": stale_time,
            "path_basename": basename,
            "socket_mode": "0600",
            "owner_uid": docker["runtime_uid"],
            "inode": published_inodes[2],
            "connect_errno": 111,
        }
        and type(stale_time) is int
        and stale_time > 0,
        "SIGKILL did not leave the exact non-accepting sandbox socket inode",
    )
    absent = values[3]
    absent_time = absent.get("observed_time_ns")
    _require(
        absent
        == {
            "event": "absent-after-control-reopen",
            "prior_generation": 2,
            "observed_time_ns": absent_time,
            "path_basename": basename,
            "lstat_errno": 2,
            "connect_errno": 2,
        }
        and type(absent_time) is int
        and absent_time > 0,
        "replayed sandbox endpoint was not observed absent after control restart",
    )
    _require(
        timeline["rule_v1_activated_ns"] <= published[1]
        < timeline["vm_snapshot_ready_ns"]
        and timeline["rule_v2_activated_ns"] <= published[2]
        < timeline["order_replaced_ns"]
        and docker["control_crash_finished_ns"] <= int(stale_time)
        < docker["control_restart_start_ns"]
        and timeline["control_restarted_ns"] <= int(absent_time)
        < timeline["vm_restore_loaded_ns"]
        < published[3]
        and published[3] == timeline["sandbox_generation_3_ns"],
        "sandbox socket observations do not match the cutover and restart order",
    )
    if vm_backend == "firecracker":
        _require(vm is not None, "Firecracker sandbox identity evidence is absent")
        relay_identities = _object(
            vm.get("sandbox_identities"), "Firecracker relay sandbox identities"
        )
        _require(
            relay_identities
            == {
                generation: {
                    "device": published_devices[generation],
                    "inode": published_inodes[generation],
                    "sandbox_peer_pid": (
                        docker["control_pid_before"]
                        if generation == 1
                        else docker["control_pid_after"]
                    ),
                }
                for generation in (1, 3)
            },
            "Firecracker relays did not use the published control sockets",
        )
    return {
        "credential_free": True,
        "sigkill_stale_inode_observed": True,
        "generations": [1, 2, 3],
        "replay_auto_attach_blocked": True,
        "transport": "host-unix-socket",
    }


def _check_runner_result(
    directory: Path,
    run_id: str,
    purchase_id: str,
    history: Mapping[str, Any],
    docker: Mapping[str, Any],
    vm: Mapping[str, Any],
    protocol: Mapping[str, Any],
    provenance: Mapping[str, Any],
) -> None:
    result = _object(_json_file(directory, "result.json"), "runner result")
    _require(
        set(result)
        == {
            "codex",
            "effect_ips",
            "effects",
            "evidence_directory",
            "faults",
            "history",
            "network",
            "provenance",
            "protocol",
            "purchase_id",
            "run_id",
            "vm",
        }
        and result.get("run_id") == run_id
        and result.get("purchase_id") == purchase_id,
        "runner result belongs to another integrated run",
    )
    evidence_name = result.get("evidence_directory")
    _require(
        isinstance(evidence_name, str)
        and evidence_name not in {"", ".", ".."}
        and "/" not in evidence_name,
        "runner result exposes a host evidence path",
    )
    operation_ids = history["operation_ids"]
    _require(
        result.get("history")
        == {
            "active_requirement": f"purchase-v2/{run_id}",
            "hash": history["history_hash"],
            "operations": operation_ids,
            "sequence": 16,
        },
        "runner History summary differs from binary replay",
    )
    _require(result.get("effects") == history["stats"], "runner effect summary differs")
    _require(
        result.get("effect_ips") == docker["effect_ips"],
        "runner effect IP summary differs from Docker inspection",
    )
    _require(
        result.get("network") == docker["topology"],
        "runner network summary differs from Docker inspection",
    )
    _require(
        result.get("protocol") == protocol,
        "runner protocol summary differs from App Server records",
    )
    _require(
        result.get("faults")
        == {
            "control_pid_after": docker["control_pid_after"],
            "control_pid_before": docker["control_pid_before"],
            "control_process_restarted": True,
            "control_restart_mode": "sigkill",
            "order_container_after": docker["order_id_after"],
            "order_container_before": docker["order_id_before"],
            "order_process_replaced": True,
            "whole_vm_restored": True,
        },
        "runner fault summary differs from Docker and VM evidence",
    )
    codex = _object(result.get("codex"), "runner Codex summary")
    _require(
        codex
        == {
            "login_status": "Logged in using ChatGPT",
            "model": protocol["model"],
            "model_provider": "openai",
            "native_binary_sha256": NATIVE_CODEX_SHA,
            "real_app_server": True,
            "version": "codex-cli 0.147.0",
        },
        "runner Codex summary does not identify the pinned logged-in App Server",
    )
    if provenance.get("vm_backend") == "firecracker":
        _check_firecracker_runner_result(
            directory, result, run_id, purchase_id, vm, provenance
        )
        return
    _require(
        result.get("provenance")
        == {
            "revision": provenance["revision"],
            "runtime_image_id": provenance["image_id"],
            "source_tree_sha256": provenance["source_tree_sha256"],
            "vm_demo_sha256": provenance["vm_demo_sha256"],
        },
        "runner provenance summary differs from committed source and image evidence",
    )
    _require(
        result.get("faults")
        == {
            "control_pid_after": docker["control_pid_after"],
            "control_pid_before": docker["control_pid_before"],
            "control_process_restarted": True,
            "control_restart_mode": "sigkill",
            "order_container_after": docker["order_id_after"],
            "order_container_before": docker["order_id_before"],
            "order_process_replaced": True,
            "whole_vm_restored": True,
        },
        "runner fault summary differs from Docker and VM evidence",
    )
    vm_summary = _object(result.get("vm"), "runner VM summary")
    _require(
        vm_summary.get("accelerator") == vm["result"]["accelerator"]
        and vm_summary.get("snapshot") == vm["result"]["snapshot"]
        and vm_summary.get("first_reused")
        == vm["result"]["first_operation_reused"]
        and vm_summary.get("restored_reused")
        == vm["result"]["restored_operation_reused"]
        and vm_summary.get("credential_free") is True
        and vm_summary.get("sandbox_generation") == 3
        and vm_summary.get("transport") == "host-unix-socket"
        and vm_summary.get("qemu_pid") == vm["result"]["qemu_pid"]
        and type(vm_summary.get("runner_pid")) is int
        and vm_summary["runner_pid"] > 0
        and vm_summary["runner_pid"] != vm_summary["qemu_pid"]
        and set(vm_summary)
        == {
            "accelerator",
            "credential_free",
            "first_reused",
            "restored_reused",
            "qemu_pid",
            "runner_pid",
            "sandbox_generation",
            "snapshot",
            "transport",
        },
        "runner VM summary differs from QEMU guest evidence",
    )
    runner_process = _object(
        _json_file(directory, "vm-runner-process.json"),
        "live VM runner process",
    )
    _require(
        runner_process
        == {
            "schema": 1,
            "source": "linux-proc-exe-fd",
            "pid": vm_summary["runner_pid"],
            "executable": "vm-demo",
            "executable_sha256": provenance["vm_demo_sha256"],
        },
        "running VM runner is not the binary tied to committed source",
    )
    codex = _object(result.get("codex"), "runner Codex summary")
    _require(
        codex
        == {
            "login_status": "Logged in using ChatGPT",
            "model": protocol["model"],
            "model_provider": "openai",
            "native_binary_sha256": NATIVE_CODEX_SHA,
            "real_app_server": True,
            "version": "codex-cli 0.147.0",
        },
        "runner Codex summary does not identify the pinned logged-in App Server",
    )


def _check_firecracker_runner_result(
    directory: Path,
    result: Mapping[str, Any],
    run_id: str,
    purchase_id: str,
    vm: Mapping[str, Any],
    provenance: Mapping[str, Any],
) -> None:
    _require(
        set(result)
        == {
            "codex",
            "effect_ips",
            "effects",
            "evidence_directory",
            "faults",
            "history",
            "network",
            "provenance",
            "protocol",
            "purchase_id",
            "run_id",
            "vm",
        }
        and result.get("run_id") == run_id
        and result.get("purchase_id") == purchase_id
        and isinstance(result.get("evidence_directory"), str)
        and "/" not in result["evidence_directory"],
        "Firecracker runner result belongs to another run",
    )
    summary = _object(result.get("vm"), "Firecracker runner VM summary")
    first_reused = vm["result"].get("first_operation_reused")
    _require(
        summary
        == {
            "backend": "firecracker",
            "runner_pid": summary.get("runner_pid"),
            "accelerator": "kvm",
            "snapshot": "before_purchase",
            "first_reused": first_reused,
            "restored_reused": True,
            "credential_free": True,
            "sandbox_generation": 3,
            "transport": "host-unix-socket",
            "firecracker_pids": vm["firecracker_pids"],
        }
        and type(first_reused) is bool
        and vm["result"].get("restored_operation_reused") is True
        and type(summary.get("runner_pid")) is int
        and summary["runner_pid"] > 0
        and summary["runner_pid"] not in vm["firecracker_pids"],
        "runner Firecracker VM summary differs from retained evidence",
    )
    expected_provenance = {
        "revision": provenance["revision"],
        "source_tree_sha256": provenance["source_tree_sha256"],
        "runtime_image_id": provenance["image_id"],
        "vm_backend": "firecracker",
        "firecracker_demo_sha256": provenance["vm_demo_sha256"],
        "firecracker_guest_sha256": provenance["firecracker_guest_sha256"],
    }
    _require(
        result.get("provenance") == expected_provenance,
        "runner Firecracker build provenance differs",
    )
    runner = _object(
        _json_file(directory, "vm-runner-process.json"),
        "Firecracker runner process",
    )
    _require(
        runner
        == {
            "schema": 1,
            "source": "linux-proc-exe-fd",
            "pid": summary["runner_pid"],
            "executable": "firecracker-demo",
            "executable_sha256": provenance["vm_demo_sha256"],
            "backend": "firecracker",
        },
        "Firecracker runner process is not tied to the retained build",
    )


def check_evidence(
    directory: Path, *, runtime_dir: Path | None = None
) -> dict[str, Any]:
    """Replay one retained bundle and return facts derived from raw evidence."""

    directory = directory.resolve(strict=True)
    _require(directory.is_dir(), "evidence path is not a directory")
    requirement_v1 = _object(
        _json_file(directory, "requirement-v1.json"), "v1 Requirement"
    )
    requirement_id = requirement_v1.get("id")
    prefix = "purchase-v1/"
    _require(
        isinstance(requirement_id, str) and requirement_id.startswith(prefix),
        "v1 Requirement does not contain a run identity",
    )
    run_id = str(requirement_id)[len(prefix) :]
    matched = RUN_ID.fullmatch(run_id)
    _require(matched is not None, "integrated run identity is invalid")
    assert matched is not None
    suffix = run_id.rsplit("-", 1)[-1]
    purchase_id = f"A-17-{suffix}"
    _require(PURCHASE_ID.fullmatch(purchase_id) is not None, "purchase identity is invalid")

    if runtime_dir is None:
        candidate = Path(__file__).resolve().parents[1] / "runtime"
        if (candidate / "cmd/check-certificate").is_dir():
            runtime_dir = candidate
    elif runtime_dir is not None:
        runtime_dir = runtime_dir.resolve(strict=True)

    repository = (
        runtime_dir.parent
        if runtime_dir is not None
        else Path(__file__).resolve().parents[1]
    )
    provenance = _check_provenance(directory, run_id, repository)
    with _recorded_runtime_source(repository, provenance) as verifier_runtime:
        history = _check_history_and_effects(
            directory,
            run_id,
            purchase_id,
            verifier_runtime,
            provenance["vm_backend"],
        )
        docker = _check_docker(directory, run_id, provenance)
        if provenance["vm_backend"] == "qemu":
            vm = _check_vm(
                directory,
                run_id,
                purchase_id,
                str(docker["effect_ips"]["ledger"]),
            )
        else:
            vm = _check_firecracker_vm(
                directory,
                verifier_runtime,
                provenance,
                run_id,
                purchase_id,
                history["vm_host_instance_ids"],
                history["operation_ids"]["vm"],
                history["external"]["vm"],
                str(docker["effect_ips"]["ledger"]),
            )
    remotes = {
        name: str(history["external"][name]["remote_reference"])
        for name in ("codex", "order", "vm")
    }
    protocol_summary, protocol_timing = _check_protocol(
        directory,
        run_id,
        purchase_id,
        history["operation_ids"],
        remotes,
        docker["codex_id"],
        docker["codex_arguments"],
    )
    _check_outcomes(
        directory, history["operation_ids"], history["external"]
    )
    if provenance["vm_backend"] == "qemu":
        timeline = _check_timeline(directory, docker, vm, protocol_timing)
        sandbox_boundary = _check_sandbox_lifecycle(directory, docker, timeline)
    else:
        timeline = _check_firecracker_timeline(
            directory, docker, vm, protocol_timing
        )
        sandbox_boundary = _check_sandbox_lifecycle(
            directory,
            docker,
            timeline,
            vm_backend="firecracker",
            vm=vm,
        )

    credential = _object(
        _json_file(directory, "credential-lifecycle.json"), "credential lifecycle"
    )
    _require(
        credential
        == {
            "actor_tokens_distinct": True,
            "host_source_modified": False,
            "temporary_auth_removed_before_effect": True,
            "vm_credential_free": True,
        },
        "credential lifecycle does not isolate three credentials and the credential-free VM",
    )
    teardown = _object(_json_file(directory, "teardown.json"), "teardown")
    _require(
        teardown == {"compose_down_returncode": 0, "image_remove_returncode": 0},
        "deployment teardown did not remove the Compose project and image",
    )
    _check_runner_result(
        directory,
        run_id,
        purchase_id,
        history,
        docker,
        vm,
        protocol_summary,
        provenance,
    )

    deliveries = sum(int(value["deliveries"]) for value in history["stats"].values())
    commits = sum(int(value["commits"]) for value in history["stats"].values())
    _require(deliveries == 5 and commits == 3, "derived external totals differ")
    if provenance["vm_backend"] == "qemu":
        _require(vm["load_command_time_ns"] > docker["control_restart_start_ns"] and vm["load_status_response_time_ns"] <= timeline["vm_restore_loaded_ns"] < timeline["sandbox_generation_3_ns"] < vm["resume_command_time_ns"] and protocol_timing["callback_ns"] > vm["completion_time_ns"], "restored VM or Codex callback did not cross the replaced control process")
    else:
        _require(
            timeline["vm_restore_completed_ns"] < protocol_timing["callback_ns"],
            "Firecracker callback did not follow the restored VM completion",
        )
    return {
        "valid": True,
        "run_id": run_id,
        "purchase_id": purchase_id,
        "certificates_valid": 3,
        "history_chain_replayed": True,
        "history_sequence": 16,
        "history_hash": history["history_hash"],
        "operation_ids": history["operation_ids"],
        "rule_transition": {
            "from_version": 1,
            "to_version": 3,
            "v2_new_work_allow_count": 0,
        },
        "sandbox_boundary": sandbox_boundary,
        "external_effects": {
            "deliveries": deliveries,
            "commits": commits,
            "by_service": history["stats"],
        },
        "fault_correlations": {
            "control_process_restarted": True,
            "control_process_sigkilled": True,
            "dispatch_owner_changed": True,
            "order_process_replaced": True,
            "v2_process_recovered_v1_operation": True,
            "whole_vm_restored": True,
            "vm_cutover_while_paused": True,
            "restored_vm_operation_reused": True,
            "raw_clock_order_valid": bool(timeline),
        },
        "network_isolation": {
            "attested": True,
            "direct_agent_effect_paths": 0,
            "direct_order_effect_paths": 0,
            "negative_probes": 12,
        },
        "codex_protocol": {
            "real_app_server_process": True,
            "model_provider": protocol_summary["model_provider"],
            "model": protocol_summary["model"],
            "records": protocol_summary["raw_records"],
            "dynamic_tool_calls": 1,
            "callback_responses": 1,
            "completed_turns": 1,
            "final_agent_message": "DONE",
        },
        "vm": (
            {
                "accelerator": vm["result"]["accelerator"],
                "base_image_sha256": BASE_IMAGE_SHA,
                "qmp_records": vm["qmp_records"],
                "snapshot": "before_purchase",
            }
            if provenance["vm_backend"] == "qemu"
            else {
                "accelerator": vm["result"]["accelerator"],
                "backend": "firecracker",
                "firecracker_pids": vm["firecracker_pids"],
                "snapshot": "before_purchase",
            }
        ),
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
    verdict = check_evidence(arguments.evidence, runtime_dir=arguments.runtime_dir)
    output = arguments.output
    if output is None:
        output = arguments.evidence / "independent-verdict.json"
    _write_json(output, verdict)
    print(json.dumps(verdict, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["EvidenceError", "check_evidence"]
