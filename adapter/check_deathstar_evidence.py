"""Independently verify the retained DeathStarBench recovery experiment.

This module deliberately does not import the live deployment script.  It
replays the binary History, invokes the standalone Certificate checker, and
joins the runtime record to the unmodified application's MongoDB facts,
adapter audits, source identities, and Docker network/removal evidence.
"""

from __future__ import annotations

import argparse
import base64
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Iterable, Mapping, Sequence

from adapter.check_codex_isolated_evidence import (
    EvidenceError,
    _check_anchor,
    _hash,
    _list,
    _loads,
    _object,
    _read,
    _replay_history,
    _require,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME = ROOT / "runtime"
ZERO_HASH = "0" * 64
V1_TAG = "hotelReservation-0.2.2"
V2_TAG = "hotelReservation-0.3.5"
V1_COMMIT = "25ccc81c1f6a1e7fe4d6b726d6a310cd2b607fa9"
V2_COMMIT = "6ecb09706140f8730b5385c08f1386c654c3c526"
V1_TREE = "9846449187fdeb286127885ab747cef24bdba3fd"
V2_TREE = "0ac0fd6d4ccfa1472d3895384d45fef5c6246b03"
IMAGE_ID = re.compile(r"(?:sha256:)?[0-9a-f]{64}\Z")
OFFICIAL_SERVICES = (
    "attractions",
    "consul",
    "frontend",
    "geo",
    "jaeger",
    "memcached-profile",
    "memcached-rate",
    "memcached-reserve",
    "memcached-review",
    "mongodb-attractions",
    "mongodb-geo",
    "mongodb-profile",
    "mongodb-rate",
    "mongodb-recommendation",
    "mongodb-reservation",
    "mongodb-review",
    "mongodb-user",
    "profile",
    "rate",
    "recommendation",
    "reservation",
    "review",
    "search",
    "user",
)
V2_BINARY_SERVICES = {
    "attractions",
    "frontend",
    "geo",
    "profile",
    "rate",
    "recommendation",
    "reservation",
    "review",
    "search",
    "user",
}


def _json(path: Path, label: str | None = None) -> Any:
    return _loads(_read(path), label or path.name)


def _operation_id(domain: str, call_id: str) -> str:
    _require(isinstance(domain, str) and domain, "Operation domain is absent")
    _require(isinstance(call_id, str) and call_id, "call identity is absent")
    digest = sha256()
    digest.update(b"operation-id-v1\x00")
    digest.update(domain.encode())
    digest.update(b"\x00")
    digest.update(call_id.encode())
    return "op-" + digest.hexdigest()


def _gateway_request_hash(url: str, body: bytes, operation_id: str) -> str:
    """Reproduce runtime/internal/gateway.requestHash for this workload."""

    headers = {
        "accept-encoding": "identity",
        "content-type": "application/json",
        "idempotency-key": operation_id,
        "user-agent": "safe-change-runtime/1",
        "x-operation-id": operation_id,
    }
    digest = sha256()
    digest.update(b"POST\x00" + url.encode() + b"\x00")
    for name, value in sorted(headers.items()):
        digest.update(name.encode() + b":" + value.encode() + b"\x00")
    digest.update(body)
    return digest.hexdigest()


def _fact(operation_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
    required = {"hotel_id", "in_date", "out_date", "rooms", "username", "password"}
    _require(set(request) == required, "reservation request fields changed")
    _require(request.get("username") == "Cornell_30", "test username changed")
    _require(request.get("password") == "0000000000", "test password changed")
    _require(request.get("rooms") == 1, "registered workload is not one room")
    return {
        "customer_name": "safe-" + operation_id,
        "hotel_id": request["hotel_id"],
        "in_date": request["in_date"],
        "out_date": request["out_date"],
        "rooms": request["rooms"],
    }


def _fact_hash(facts: Sequence[Mapping[str, Any]]) -> str:
    ordered = sorted(
        (dict(item) for item in facts),
        key=lambda item: (
            item["customer_name"],
            item["hotel_id"],
            item["in_date"],
            item["out_date"],
            item["rooms"],
        ),
    )
    # Go hashes json.Marshal([]ReservationFact), whose struct field order is
    # the insertion order below rather than lexicographic object-key order.
    encoded = json.dumps(
        [
            {
                "customer_name": item["customer_name"],
                "hotel_id": item["hotel_id"],
                "in_date": item["in_date"],
                "out_date": item["out_date"],
                "rooms": item["rooms"],
            }
            for item in ordered
        ],
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode()
    return sha256(encoded).hexdigest()


def _pick(mapping: Mapping[str, Any], names: Sequence[str], label: str) -> Any:
    present = [name for name in names if name in mapping]
    _require(len(present) == 1, f"{label} is absent or ambiguous")
    return mapping[present[0]]


def _string(mapping: Mapping[str, Any], names: Sequence[str], label: str) -> str:
    value = _pick(mapping, names, label)
    _require(isinstance(value, str) and value, f"{label} is not a nonempty string")
    return value


def _result_identity(
    upstream: Mapping[str, Any]
) -> tuple[dict[str, str], dict[str, str]]:
    upstream_identities = _object(upstream.get("identities"), "upstream identities")
    _require(
        set(upstream_identities)
        == {
            "domain",
            "raw_retry",
            "old_version_drain",
            "proposed_old",
            "proposed_new",
            "unexecuted",
            "multi_night",
        },
        "upstream identity fields changed",
    )
    domain = _string(upstream_identities, ("domain",), "Operation domain")

    aliases = {
        "raw": "raw_retry",
        "drain": "old_version_drain",
        "old": "proposed_old",
        "new": "proposed_new",
        "zero": "unexecuted",
        "multi": "multi_night",
    }
    call_ids: dict[str, str] = {}
    operation_ids: dict[str, str] = {}
    for short, name in aliases.items():
        item = _object(upstream_identities.get(name), name + " identity")
        _require(set(item) == {"call_id", "operation_id"}, name + " identity fields changed")
        call_id = _string(item, ("call_id",), name + " call identity")
        expected_id = _operation_id(domain, call_id)
        _require(item.get("operation_id") == expected_id, name + " Operation identity is not derived")
        call_ids[short] = call_id
        operation_ids[short] = expected_id
    _require(len(set(call_ids.values())) == 6, "call identities are not distinct")
    _require(len(set(operation_ids.values())) == 6, "Operation identities are not distinct")
    urls = _object(upstream.get("urls"), "upstream URLs")
    _require(
        set(urls) == {"raw_effect", "drain_effect", "effect_v1", "effect_v2", "query"},
        "upstream URL fields changed",
    )
    identity = {
        "domain": domain,
        "raw": call_ids["raw"],
        "drain": call_ids["drain"],
        "old": call_ids["old"],
        "new": call_ids["new"],
        "zero": call_ids["zero"],
        "multi": call_ids["multi"],
        "raw_effect": _string(urls, ("raw_effect",), "raw baseline effect URL"),
        "drain_effect": _string(urls, ("drain_effect",), "drain baseline effect URL"),
        "effect_v1": _string(urls, ("effect_v1",), "v1 effect URL"),
        "effect_v2": _string(urls, ("effect_v2",), "v2 effect URL"),
        "query": _string(urls, ("query",), "observer URL"),
    }
    return identity, operation_ids


def _execute_request(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    document = _object(_json(path, label), label)
    if set(document) == {"request"}:
        document = _object(document["request"], label + " request")
    body_value = document.get("body")
    _require(isinstance(body_value, str), f"{label} has no base64 body")
    try:
        body = base64.b64decode(body_value, validate=True)
    except ValueError as error:
        raise EvidenceError(f"{label} body is not canonical base64") from error
    _require(base64.b64encode(body).decode() == body_value, f"{label} body base64 changed")
    _require(
        set(document) <= {"call_id", "kind", "method", "url", "headers", "body"},
        f"{label} contains an unexpected execute field",
    )
    _require(
        document.get("method") in (None, "", "POST")
        and document.get("headers") in (None, {}, {"Content-Type": "application/json"}, {"content-type": "application/json"}),
        f"{label} changes the fixed HTTP request",
    )
    return document, body


def _check_certificate(
    directory: Path, label: str, runtime_dir: Path
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    certificate_dir = directory / "certificates"
    certificate = _object(_json(certificate_dir / f"{label}.json"), f"{label} Certificate")
    state = _object(
        _json(certificate_dir / f"state-{label}.json"), f"{label} Certificate state"
    )
    saved = _object(
        _json(certificate_dir / f"verdict-{label}.json"), f"{label} Certificate verdict"
    )
    _require(saved.get("valid") is True, f"saved {label} Certificate is invalid")
    completed = subprocess.run(
        [
            "go",
            "run",
            "./cmd/check-certificate",
            "-state",
            os.fspath((certificate_dir / f"state-{label}.json").resolve()),
            "-certificate",
            os.fspath((certificate_dir / f"{label}.json").resolve()),
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
    _require(fresh == saved, f"fresh {label} Certificate verdict changed")
    return certificate, state, saved


def _normalized_fact(value: Any, label: str) -> dict[str, Any]:
    fact = _object(value, label)
    snake = {"customer_name", "hotel_id", "in_date", "out_date", "rooms"}
    camel = {"customerName", "hotelId", "inDate", "outDate", "number"}
    _require(set(fact) in (snake, camel), f"{label} has another Mongo projection")
    if set(fact) == snake:
        normalized = dict(fact)
    else:
        normalized = {
            "customer_name": fact["customerName"],
            "hotel_id": fact["hotelId"],
            "in_date": fact["inDate"],
            "out_date": fact["outDate"],
            "rooms": fact["number"],
        }
    _require(
        all(isinstance(normalized[name], str) and normalized[name] for name in snake - {"rooms"})
        and type(normalized["rooms"]) is int
        and normalized["rooms"] > 0,
        f"{label} has invalid values",
    )
    return normalized


def _mongo(path: Path, expected: Mapping[str, Any], count: int, label: str) -> list[dict[str, Any]]:
    document = _object(_json(path, label), label)
    _require(
        set(document) == {"schema", "operation_id", "filter", "count", "facts"}
        and document.get("schema") == 1,
        f"{label} fields changed",
    )
    observed_count = _pick(document, ("count", "matching_count"), label + " count")
    facts_value = _pick(document, ("facts", "documents", "rows"), label + " facts")
    _require(type(observed_count) is int and observed_count == count, f"{label} count differs")
    facts = [
        _normalized_fact(value, f"{label} fact {index}")
        for index, value in enumerate(_list(facts_value, label + " facts"), 1)
    ]
    _require(len(facts) == count, f"{label} did not retain every matching document")
    _require(all(fact == expected for fact in facts), f"{label} contains another fact")
    expected_filter = {
        "customerName": expected["customer_name"],
        "hotelId": expected["hotel_id"],
        "inDate": expected["in_date"],
        "outDate": expected["out_date"],
        "number": expected["rooms"],
    }
    _require(document.get("filter") == expected_filter, f"{label} filter differs from its facts")
    _require(
        document.get("operation_id") == expected["customer_name"][len("safe-") :],
        f"{label} Operation identity differs from its customer",
    )
    return facts


def _audit(
    path: Path,
    operation_id: str,
    deliveries: int,
    label: str,
    *,
    first_drop: bool = True,
) -> list[dict[str, Any]]:
    raw = _read(path)
    lines = raw.splitlines()
    _require(raw.endswith(b"\n") and len(lines) == deliveries, f"{label} delivery count differs")
    records: list[dict[str, Any]] = []
    for index, line in enumerate(lines, 1):
        record = _object(_loads(line, f"{label} line {index}"), f"{label} line {index}")
        _require(
            set(record)
            == {"delivery", "operation_id", "upstream_status", "upstream_hash", "upstream_ok", "drop"},
            f"{label} line {index} fields changed",
        )
        _require(
            record.get("delivery") == index
            and record.get("operation_id") == operation_id
            and record.get("upstream_status") == 200
            and record.get("upstream_ok") is True,
            f"{label} line {index} is not a successful delivery",
        )
        _hash(record.get("upstream_hash"), f"{label} upstream hash")
        records.append(record)
    _require(records[0].get("drop") is first_drop, f"{label} first-response behavior differs")
    if deliveries > 1:
        _require(
            all(record.get("drop") is False for record in records[1:]),
            f"{label} lost more than the injected first response",
        )
    return records


def _stats(path: Path, deliveries: int, drops: int, label: str) -> dict[str, Any]:
    value = _object(_json(path, label), label)
    _require(
        value.get("mode") == "effect"
        and value.get("deliveries") == deliveries
        and value.get("upstream_successes") == deliveries
        and value.get("drops") == drops
        and value.get("facts") == [],
        f"{label} differs from the audit",
    )
    return value


def _unwrap_outcome(value: Any, label: str) -> tuple[dict[str, Any], str | None]:
    document = _object(value, label)
    error = document.get("error") if isinstance(document.get("error"), str) else None
    if isinstance(document.get("outcome"), dict):
        return _object(document["outcome"], label + " outcome"), error
    if isinstance(document.get("body"), dict):
        body = _object(document["body"], label + " body")
        nested_error = body.get("error") if isinstance(body.get("error"), str) else error
        if isinstance(body.get("outcome"), dict):
            return _object(body["outcome"], label + " outcome"), nested_error
        return body, nested_error
    return document, error


def _check_outcome(path: Path, operation_id: str, *, recovered: bool, label: str) -> dict[str, Any]:
    outcome, error = _unwrap_outcome(_json(path, label), label)
    _require(error is None, f"{label} reports an error")
    _require(
        outcome.get("operation_id") == operation_id
        and outcome.get("phase") == "succeeded"
        and outcome.get("status_code") == 200
        and outcome.get("recovered_by_query") is recovered
        and outcome.get("reused") is False,
        f"{label} has another runtime outcome",
    )
    _hash(outcome.get("result_hash"), f"{label} result hash")
    return outcome


def _prepare(event: Mapping[str, Any], operation_id: str, label: str) -> dict[str, Any]:
    _require(event.get("operation") == "operation.prepared", f"{label} was not prepared")
    data = _object(event.get("data"), f"{label} prepare data")
    _require(
        set(data) == {"semantic_version", "operation"}
        and data.get("semantic_version") == 1,
        f"{label} prepare envelope changed",
    )
    operation = _object(data.get("operation"), f"{label} prepared Operation")
    _require(operation.get("id") == operation_id, f"{label} identity differs")
    return operation


def _updates(events: Sequence[Mapping[str, Any]], operation_id: str) -> list[dict[str, Any]]:
    updates: list[dict[str, Any]] = []
    for event in events:
        if event.get("operation") != "operation.phase":
            continue
        data = _object(event.get("data"), "Operation phase data")
        if data.get("id") != operation_id:
            continue
        _require(
            set(data) == {"id", "semantic_version", "update"}
            and data.get("semantic_version") == 1,
            "Operation phase envelope changed",
        )
        updates.append(_object(data.get("update"), "Operation update"))
    return updates


def _check_upstream(directory: Path) -> dict[str, Any]:
    document = _object(_json(directory / "upstream.json"), "upstream provenance")
    _require(
        set(document)
        == {"schema", "repository", "releases", "runtime", "identities", "urls"}
        and document.get("schema") == 1
        and isinstance(document.get("repository"), str)
        and "github.com/delimitrou/DeathStarBench" in document["repository"],
        "upstream provenance schema or repository differs",
    )
    releases_value = document.get("releases", document)
    releases = _object(releases_value, "upstream releases")
    v1 = _object(_pick(releases, ("v1", "old"), "v1 upstream release"), "v1 release")
    v2 = _object(_pick(releases, ("v2", "new"), "v2 upstream release"), "v2 release")
    for label, value, tag, commit, tree in (
        ("v1", v1, V1_TAG, V1_COMMIT, V1_TREE),
        ("v2", v2, V2_TAG, V2_COMMIT, V2_TREE),
    ):
        _require(value.get("tag") == tag, f"{label} upstream tag differs")
        _require(value.get("commit") == commit, f"{label} upstream commit differs")
        _require(
            set(value)
            >= {"tag", "commit", "tree", "image", "image_id"},
            f"{label} upstream provenance fields changed",
        )
        image = _string(value, ("image_id",), f"{label} image identity")
        _require(IMAGE_ID.fullmatch(image) is not None, f"{label} image identity is invalid")
        _require(
            value.get("tree") == tree,
            f"{label} source tree identity differs",
        )
        _require(
            value.get("source_clean_before_build") is True
            and value.get("source_clean_after_build") is True
            and value.get("status_porcelain_before_build") == ""
            and value.get("status_porcelain_after_build") == "",
            f"{label} source was edited",
        )
    _require(
        _string(v1, ("image_id",), "v1 image")
        != _string(v2, ("image_id",), "v2 image"),
        "v1 and v2 resolved to the same image",
    )
    runtime = _object(document.get("runtime"), "runtime provenance")
    _hash(runtime.get("checker_sha256"), "Certificate checker binary hash")
    _require(
        isinstance(runtime.get("git_head"), str)
        and re.fullmatch(r"[0-9a-f]{40}", runtime["git_head"]) is not None
        and isinstance(runtime.get("image"), str)
        and runtime.get("image")
        and isinstance(runtime.get("image_id"), str)
        and IMAGE_ID.fullmatch(runtime["image_id"]) is not None,
        "runtime provenance is invalid",
    )
    _require(
        runtime.get("source_clean_before_build") is True
        and runtime.get("source_clean_after_build") is True
        and runtime.get("status_porcelain_before_build") == ""
        and runtime.get("status_porcelain_after_build") == "",
        "runtime source changed during its image build",
    )
    _require(
        len({v1["image_id"], v2["image_id"], runtime["image_id"]}) == 3,
        "runtime and upstream images are not distinct",
    )

    def strings(value: Any) -> Iterable[str]:
        if isinstance(value, str):
            yield value
        elif isinstance(value, list):
            for item in value:
                yield from strings(item)
        elif isinstance(value, dict):
            for item in value.values():
                yield from strings(item)

    raw_images = _json(directory / "docker/images.json", "raw Docker images")
    retained_strings = set(strings(raw_images))
    _require(
        {v1["image_id"], v2["image_id"], runtime["image_id"]} <= retained_strings,
        "upstream/runtime image identities differ from raw Docker inspection",
    )
    return document


def _check_official_graph(directory: Path, upstream: Mapping[str, Any]) -> None:
    services_raw = _read(directory / "docker/official-services.txt")
    _require(services_raw.endswith(b"\n"), "official service list is not newline terminated")
    try:
        service_names = [line.decode() for line in services_raw.splitlines()]
    except UnicodeDecodeError as error:
        raise EvidenceError("official service list is not UTF-8") from error
    _require(
        tuple(service_names) == OFFICIAL_SERVICES,
        "official service list is not the exact 24-service graph",
    )

    compose_path = directory / "docker/compose-config.yaml"
    completed = subprocess.run(
        ["docker", "compose", "-f", os.fspath(compose_path), "config", "--format", "json"],
        text=True,
        capture_output=True,
        timeout=30.0,
        check=False,
    )
    _require(completed.returncode == 0, "retained Compose configuration cannot be parsed")
    compose = _object(
        _loads(completed.stdout.encode(), "retained Compose configuration"),
        "retained Compose configuration",
    )
    services = _object(compose.get("services"), "Compose services")
    _require(set(services) == set(OFFICIAL_SERVICES), "Compose configuration omits an official service")
    v2 = _object(_object(upstream.get("releases"), "upstream releases").get("v2"), "v2 release")
    for name, value in services.items():
        service = _object(value, f"Compose service {name}")
        _require("build" not in service, f"Compose service {name} retains a build context")
        _require(service.get("ports") in (None, []), f"Compose service {name} exposes a host port")
        if name in V2_BINARY_SERVICES:
            _require(service.get("image") == v2.get("image"), f"Compose service {name} used another application image")

    state = _object(
        _json(directory / "docker/official-service-state.json"),
        "official service state",
    )
    state_items = [
        _object(value, "official service state item")
        for value in _list(state.get("services"), "official service states")
    ]
    _require(
        state.get("schema") == 1
        and len(state_items) == 24
        and {str(item.get("service")) for item in state_items} == set(OFFICIAL_SERVICES),
        "official service state is incomplete",
    )
    state_by_service = {str(item["service"]): item for item in state_items}
    _require(
        state_by_service["frontend"]
        == {"service": "frontend", "compose_scaled_to_zero": True, "running": False},
        "official Compose frontend was not the one explicitly scaled to zero",
    )

    raw_containers = [
        _object(value, "raw Docker container")
        for value in _list(
            _json(directory / "docker/containers.json", "raw Docker containers"),
            "raw Docker containers",
        )
    ]
    by_id: dict[str, dict[str, Any]] = {}
    compose_by_service: dict[str, list[dict[str, Any]]] = {}
    for item in raw_containers:
        identifier = item.get("Id")
        _require(
            isinstance(identifier, str)
            and re.fullmatch(r"[0-9a-f]{64}", identifier) is not None
            and identifier not in by_id,
            "raw Docker container identity is invalid or repeated",
        )
        by_id[identifier] = item
        config = _object(item.get("Config"), "raw Docker container configuration")
        labels = config.get("Labels")
        if not isinstance(labels, dict):
            continue
        if labels.get("com.docker.compose.project") != "safe-change-deathstar-step15":
            continue
        service = labels.get("com.docker.compose.service")
        _require(isinstance(service, str) and service, "Compose container has no service label")
        compose_by_service.setdefault(service, []).append(item)
    _require(
        set(compose_by_service) == set(OFFICIAL_SERVICES) - {"frontend"}
        and all(len(items) == 1 for items in compose_by_service.values()),
        "raw Docker inspection does not contain exactly 23 official service containers",
    )
    resolved_images: set[str] = set()
    for service, items in compose_by_service.items():
        item = items[0]
        expected_state = state_by_service[service]
        identifier = str(item["Id"])
        running = _object(item.get("State"), f"{service} container state").get("Running")
        image_id = item.get("Image")
        _require(
            expected_state
            == {
                "service": service,
                "container_id": identifier,
                "compose_scaled_to_zero": False,
                "running": True,
            }
            and running is True,
            f"official service {service} was absent or stopped",
        )
        _require(
            isinstance(image_id, str) and IMAGE_ID.fullmatch(image_id) is not None,
            f"official service {service} has no resolved image identity",
        )
        resolved_images.add(image_id)
        if service in V2_BINARY_SERVICES - {"frontend"}:
            _require(image_id == v2.get("image_id"), f"official service {service} did not run the v2 image")

    frontend_v2 = [
        item
        for item in raw_containers
        if item.get("Name") == "/safe-change-step15-frontend-v2"
    ]
    _require(len(frontend_v2) == 1, "self-run v2 frontend is absent or repeated")
    frontend = frontend_v2[0]
    frontend_config = _object(frontend.get("Config"), "v2 frontend configuration")
    _require(
        _object(frontend.get("State"), "v2 frontend state").get("Running") is True
        and frontend.get("Image") == v2.get("image_id")
        and frontend_config.get("Image") == v2.get("image"),
        "self-run v2 frontend did not use the pinned v2 image",
    )
    _require(resolved_images, "official graph has no resolved dependency images")


def _running_inspection(path: Path, label: str) -> dict[str, Any]:
    value = _json(path, label)
    if isinstance(value, list):
        value = _list(value, label)
        _require(len(value) == 1, f"{label} does not identify one container")
        value = value[0]
    item = _object(value, label)
    state = _object(item.get("State", item.get("state")), label + " state")
    _require(state.get("Running", state.get("running")) is True, f"{label} was not retained and running")
    identifier = item.get("Id", item.get("id"))
    _require(isinstance(identifier, str) and identifier, f"{label} has no container identity")
    return item


def _removal_probes(path: Path) -> dict[str, Any]:
    value = _object(_json(path, "removal probes"), "removal probes")
    for label in ("frontend_v1", "effect_v1"):
        aliases = (label, label.replace("_", "-"), label.replace("_v1", ""))
        probe = _object(_pick(value, aliases, label + " removal probe"), label + " removal probe")
        returncode = _pick(probe, ("exit_code",), label + " inspect status")
        _require(
            type(returncode) is int
            and returncode != 0
            and isinstance(probe.get("stderr"), str)
            and "no such object" in probe["stderr"].lower(),
            f"removed {label} still inspected successfully or failed for another reason",
        )
    for label in ("frontend_v2", "effect_v2"):
        probe = _object(value.get(label), label + " removal probe")
        _require(
            probe.get("exit_code") == 0 and probe.get("running") is True,
            f"{label} was not running after old component removal",
        )
    return value


def _service_name(item: Mapping[str, Any]) -> str:
    for key in ("service", "name", "Name"):
        value = item.get(key)
        if isinstance(value, str) and value:
            return value.lstrip("/")
    config = item.get("Config")
    if isinstance(config, dict):
        labels = config.get("Labels")
        if isinstance(labels, dict):
            value = labels.get("com.docker.compose.service")
            if isinstance(value, str):
                return value
    return ""


def _network_names(item: Mapping[str, Any]) -> set[str]:
    for key in ("networks", "Networks"):
        value = item.get(key)
        if isinstance(value, list) and all(isinstance(name, str) for name in value):
            return set(value)
        if isinstance(value, dict):
            return set(value)
    settings = item.get("NetworkSettings")
    if isinstance(settings, dict) and isinstance(settings.get("Networks"), dict):
        return set(settings["Networks"])
    return set()


def _check_network(directory: Path) -> dict[str, set[str]]:
    proof = _object(_json(directory / "docker/network-proof.json"), "network proof")
    _require(
        set(proof)
        == {
            "schema",
            "networks",
            "members",
            "component_networks",
            "assertions",
            "direct_probes",
            "pass",
        }
        and proof.get("schema") == 1,
        "network proof fields changed",
    )
    networks = _object(proof.get("networks"), "logical networks")
    _require(
        set(networks) == {"control", "frontdoor", "observation", "application"}
        and all(isinstance(value, str) and value for value in networks.values())
        and len(set(networks.values())) == 4,
        "logical network identities differ",
    )
    member_values = _object(proof.get("members"), "network members")
    _require(set(member_values) == set(networks), "network membership dimensions differ")
    members: dict[str, set[str]] = {}
    for network, values in member_values.items():
        items = _list(values, network + " members")
        _require(
            all(isinstance(value, str) and value for value in items)
            and len(items) == len(set(items)),
            network + " membership is invalid",
        )
        members[network] = set(items)

    def raw_network_members(path: Path, label: str) -> dict[str, set[str]]:
        raw_networks = _list(_json(path, label), label)
        result: dict[str, set[str]] = {}
        for value in raw_networks:
            network = _object(value, label + " item")
            name = network.get("Name")
            containers = _object(network.get("Containers"), label + " members")
            _require(isinstance(name, str) and name, label + " item has no name")
            names: set[str] = set()
            for attachment_value in containers.values():
                attachment = _object(attachment_value, label + " attachment")
                member_name = attachment.get("Name")
                _require(
                    isinstance(member_name, str) and member_name,
                    label + " attachment has no container name",
                )
                names.add(member_name)
            _require(name not in result, label + " identity repeats")
            result[name] = names
        return result

    raw_members = raw_network_members(
        directory / "docker/networks.json", "raw final Docker networks"
    )
    _require(
        set(raw_members) == set(networks.values())
        and all(raw_members[networks[key]] == members[key] for key in networks),
        "network proof membership differs from raw Docker inspection",
    )

    component_values = _object(proof.get("component_networks"), "component networks")
    required_components = {
        "control",
        "effect_v1",
        "effect_v2",
        "observer",
        "frontend_v1",
        "frontend_v2",
        "reservation",
        "mongo",
    }
    _require(
        required_components <= set(component_values),
        "network proof omitted a required component",
    )
    components: dict[str, set[str]] = {}
    for name, values in component_values.items():
        items = _list(values, name + " component networks")
        _require(
            all(isinstance(value, str) and value in set(networks.values()) for value in items)
            and len(items) == len(set(items)),
            name + " component networks are invalid",
        )
        components[name] = set(items)
    expected_components = {
        "control": {networks["control"]},
        "effect_v1": {networks["control"], networks["frontdoor"]},
        "effect_v2": {networks["control"], networks["frontdoor"]},
        "observer": {networks["control"], networks["observation"]},
        "frontend_v1": {networks["frontdoor"], networks["application"]},
        "frontend_v2": {networks["frontdoor"], networks["application"]},
        "reservation": {networks["application"]},
        "mongo": {networks["application"], networks["observation"]},
    }
    _require(
        all(components[name] == expected for name, expected in expected_components.items()),
        "component network cut differs",
    )
    raw_v1_members = raw_network_members(
        directory / "docker/networks-v1.json", "raw v1 Docker networks"
    )
    _require(set(raw_v1_members) == set(networks.values()), "v1 Docker network set differs")

    def networks_for(
        raw: Mapping[str, set[str]], container_name: str
    ) -> set[str]:
        return {network for network, names in raw.items() if container_name in names}

    _require(
        networks_for(raw_v1_members, "safe-change-step15-effect-v1")
        == components["effect_v1"]
        and networks_for(raw_v1_members, "safe-change-step15-frontend-v1")
        == components["frontend_v1"]
        and networks_for(raw_members, "safe-change-step15-effect-v2")
        == components["effect_v2"]
        and networks_for(raw_members, "safe-change-step15-frontend-v2")
        == components["frontend_v2"],
        "v1/v2 component networks differ from raw Docker snapshots",
    )

    def names(network: str) -> str:
        return " ".join(name.lower().replace("_", "-") for name in members[network])

    control_names = names("control")
    frontdoor_names = names("frontdoor")
    observation_names = names("observation")
    application_names = names("application")
    _require(
        "control" in control_names
        and "effect" in control_names
        and "observer" in control_names,
        "control network omitted control/effect/observer",
    )
    _require(
        "effect" in frontdoor_names and "frontend" in frontdoor_names,
        "frontdoor network omitted effect/frontend",
    )
    _require(
        "observer" in observation_names
        and ("reservation-db" in observation_names or "mongodb-reservation" in observation_names),
        "observation network omitted observer/MongoDB",
    )
    _require(
        "frontend" in application_names
        and "reservation" in application_names
        and ("reservation-db" in application_names or "mongodb-reservation" in application_names),
        "application network omitted real services",
    )
    _require(
        not any(word in control_names for word in ("frontend", "reservation-db", "mongodb-reservation", " reservation ")),
        "control network includes DeathStarBench application state",
    )
    _require(
        "observer" not in frontdoor_names
        and "reservation" not in frontdoor_names
        and "effect" not in observation_names
        and "frontend" not in observation_names,
        "effect and observer trust boundaries overlap",
    )
    assertions = _object(proof.get("assertions"), "network assertions")
    expected_assertions = {
        "effect_mongo_disjoint",
        "observer_frontend_disjoint",
        "observer_reservation_disjoint",
        "control_frontend_disjoint",
        "control_reservation_disjoint",
        "control_mongo_disjoint",
        "control_effect_shared",
        "control_observer_shared",
    }
    _require(
        set(assertions) == expected_assertions
        and all(assertions[name] is True for name in expected_assertions),
        "network isolation assertion failed",
    )
    probes = _object(proof.get("direct_probes"), "network direct probes")
    negative_probes = {
        "control_to_frontend",
        "control_to_reservation",
        "control_to_mongo",
        "effect_to_mongo",
        "observer_to_frontend",
        "observer_to_reservation",
    }
    positive_probes = {"control_to_effect", "control_to_observer"}
    _require(
        set(probes) == negative_probes | positive_probes,
        "network direct probe set differs",
    )
    for name in sorted(negative_probes):
        value = probes[name]
        probe = _object(value, f"network probe {name}")
        exit_code = _pick(probe, ("exit_code",), f"network probe {name} exit code")
        _require(type(exit_code) is int and exit_code != 0, f"network direct probe {name} succeeded")
    for name in sorted(positive_probes):
        probe = _object(probes[name], f"network probe {name}")
        response = _object(probe.get("response"), f"network probe {name} response")
        _require(
            set(probe) == {"exit_code", "response"}
            and probe.get("exit_code") == 0
            and response.get("status") == "ok"
            and response.get("mode") in ("effect", "observer"),
            f"network positive probe {name} returned another service response",
        )
    return {
        actual_name: members[logical]
        for logical, actual_name in networks.items()
    }


def _timeline(path: Path) -> list[dict[str, Any]]:
    raw = _read(path)
    _require(raw.endswith(b"\n"), "timeline is not newline terminated")
    events = [
        _object(_loads(line, f"timeline line {index}"), f"timeline line {index}")
        for index, line in enumerate(raw.splitlines(), 1)
    ]
    _require(events, "timeline is empty")
    times: list[int] = []
    labels: list[str] = []
    for index, event in enumerate(events, 1):
        _require(
            set(event) == {"schema", "seq", "at_ns", "event", "details"}
            and event.get("schema") == 1
            and event.get("seq") == index
            and isinstance(event.get("details"), dict),
            "timeline event schema or sequence changed",
        )
        timestamp = event.get("at_ns")
        label = event.get("event")
        _require(type(timestamp) is int and timestamp > 0, "timeline timestamp is invalid")
        _require(isinstance(label, str) and label, "timeline label is invalid")
        times.append(timestamp)
        labels.append(label.lower().replace("_", "-"))
    _require(times == sorted(times) and len(times) == len(set(times)), "timeline is reordered")
    _require(
        labels
        == [
            "source-clone-started",
            "source-commits-verified",
            "images-built",
            "official-service-graph-started",
            "frontend-v1-ready",
            "raw-retry-completed",
            "old-version-drain-sampled",
            "proposed-old-response-lost",
            "old-processes-removed",
            "control-restarted",
            "old-operation-recovered-by-query",
            "run-passed",
        ],
        "timeline event order differs from the fixed protocol",
    )
    return events


def _request_document(path: Path) -> tuple[dict[str, Any], bytes, dict[str, Any]]:
    request, body = _execute_request(path, path.name)
    decoded = _object(_loads(body, path.name + " body"), path.name + " body")
    return request, body, decoded


def _observation(value: Any, label: str) -> dict[str, Any]:
    item = _object(value, label)
    expected = {
        "schema",
        "operation_id",
        "request_hash",
        "outcome",
        "fact_hash",
        "remote_reference",
    }
    _require(expected <= set(item), f"{label} fields changed")
    _require(item.get("schema") == 1, f"{label} schema changed")
    _require(
        isinstance(item.get("operation_id"), str)
        and re.fullmatch(r"op-[0-9a-f]{64}", item["operation_id"]) is not None,
        f"{label} Operation identity is invalid",
    )
    _hash(item.get("request_hash"), f"{label} request hash")
    outcome = item.get("outcome")
    _require(outcome in ("succeeded", "inconclusive"), f"{label} outcome is invalid")
    if outcome == "succeeded":
        _hash(item.get("fact_hash"), f"{label} fact hash")
    else:
        _require(item.get("fact_hash") == "", f"{label} inconclusive result carries a fact hash")
    _require(
        isinstance(item.get("remote_reference"), str),
        f"{label} remote reference is invalid",
    )
    return item


def _observer_request(
    path: Path,
    operation_id: str,
    effect_url: str,
    body: bytes,
    label: str,
) -> str:
    document = _object(_json(path, label), label)
    _require(
        set(document) == {"schema", "operation_id", "effect_url", "request_hash"}
        and document.get("schema") == 1
        and document.get("operation_id") == operation_id
        and document.get("effect_url") == effect_url,
        f"{label} binding differs",
    )
    expected = _gateway_request_hash(effect_url, body, operation_id)
    _require(document.get("request_hash") == expected, f"{label} request hash differs")
    return expected


def _check_observer(
    directory: Path,
    identities: Mapping[str, str],
    request_hashes: Mapping[str, str],
    expected: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    stats = _object(
        _json(directory / "adapter/observer-facts.json"), "observer facts"
    )
    _require(
        set(stats) == {"mode", "queries", "outcomes", "facts"}
        and stats.get("mode") == "observer",
        "observer facts schema or mode changed",
    )
    facts = _list(stats.get("facts"), "observer queries")
    _require(
        stats.get("queries") == len(facts) == 5,
        "observer did not retain exactly five fixed queries",
    )
    outcomes = _object(stats.get("outcomes"), "observer outcomes")
    _require(
        outcomes == {"succeeded": 3, "inconclusive": 2}
        and
        outcomes.get("succeeded") == sum(
            isinstance(item, dict) and item.get("outcome") == "succeeded" for item in facts
        )
        and outcomes.get("inconclusive") == sum(
            isinstance(item, dict) and item.get("outcome") == "inconclusive" for item in facts
        ),
        "observer outcome counts differ from its facts",
    )
    checked = [_observation(item, f"observer query {index}") for index, item in enumerate(facts, 1)]
    by_identity: dict[str, dict[str, Any]] = {}
    for item in checked:
        operation_id = str(item.get("operation_id"))
        _require(operation_id not in by_identity, "observer queried one Operation more than once")
        by_identity[operation_id] = item
    _require(
        set(by_identity)
        == {identities[name] for name in ("raw", "drain", "old", "new", "zero")},
        "observer query identities differ from the five fixed controls",
    )
    selected = {
        name: by_identity[identities[name]]
        for name in ("raw", "drain", "old", "new", "zero")
    }
    for name in ("drain", "old", "new"):
        item = selected[name]
        _require(
            item.get("count") == 1
            and item.get("outcome") == "succeeded"
            and item.get("request_hash") == request_hashes[name]
            and item.get("remote_reference") == "reservation-db.reservation/count=1",
            f"{name} observation does not identify one exact Mongo fact",
        )
        observed_facts = [
            _normalized_fact(value, f"{name} observed fact")
            for value in _list(item.get("facts"), f"{name} observed facts")
        ]
        _require(
            observed_facts == [dict(expected[name])]
            and item.get("fact_hash") == _fact_hash(observed_facts),
            f"{name} observation fact or hash differs from Mongo",
        )
    old_item = selected["old"]
    raw_item = selected["raw"]
    _require(
        raw_item.get("count") == 2
        and raw_item.get("outcome") == "inconclusive"
        and raw_item.get("fact_hash") == ""
        and raw_item.get("facts") == []
        and raw_item.get("request_hash") == request_hashes["raw"]
        and raw_item.get("remote_reference") == "reservation-db.reservation/count=2",
        "duplicate Mongo control did not remain inconclusive",
    )
    zero_item = selected["zero"]
    _require(
        zero_item.get("operation_id") == identities["zero"]
        and zero_item.get("request_hash") == request_hashes["zero"]
        and zero_item.get("outcome") == "inconclusive"
        and zero_item.get("fact_hash") == ""
        and zero_item.get("facts") == []
        and zero_item.get("remote_reference") == "reservation-db.reservation/count=0",
        "absent Mongo control did not remain inconclusive",
    )
    raw_response = _observation(
        _json(directory / "baselines/raw-retry/observer-response.json"),
        "raw duplicate observer response",
    )
    zero_response = _observation(
        _json(directory / "adapter/unexecuted-observation.json"),
        "absent-fact observer response",
    )
    drain_response = _observation(
        _json(directory / "baselines/old-version-drain/observer-response.json"),
        "old-version-drain observer response",
    )
    new_response = _observation(
        _json(directory / "proposed/new-observer-response.json"),
        "new v2 observer response",
    )
    for response, retained, label in (
        (raw_response, raw_item, "raw duplicate"),
        (zero_response, zero_item, "absent-fact"),
        (drain_response, selected["drain"], "old-version-drain"),
        (new_response, selected["new"], "new v2"),
    ):
        _require(
            response
            == {
                key: retained[key]
                for key in (
                    "schema",
                    "operation_id",
                    "request_hash",
                    "outcome",
                    "fact_hash",
                    "remote_reference",
                )
            },
            f"{label} response differs from observer stats",
        )
    return {"stats": stats, **selected}


def _check_requirements(
    directory: Path,
    identity: Mapping[str, str],
    first_request: Mapping[str, Any],
    recover_request: Mapping[str, Any],
    new_request: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], str, str]:
    v1 = _object(_json(directory / "requirements/v1.json"), "v1 Requirement")
    v2 = _object(_json(directory / "requirements/v2.json"), "v2 Requirement")
    _require(set(v1) == {"id", "results", "capacities", "kinds"}, "v1 Requirement fields changed")
    _require(set(v2) == {"id", "results", "capacities", "kinds"}, "v2 Requirement fields changed")
    kinds_v1 = _object(v1.get("kinds"), "v1 kinds")
    kinds_v2 = _object(v2.get("kinds"), "v2 kinds")
    _require(len(kinds_v1) == 1 and len(kinds_v2) == 1, "DeathStar Requirement must have one registered kind per release")
    kind_v1, spec_v1 = next(iter(kinds_v1.items()))
    kind_v2, spec_v2 = next(iter(kinds_v2.items()))
    spec_v1 = _object(spec_v1, "v1 kind")
    spec_v2 = _object(spec_v2, "v2 kind")
    _require(
        first_request.get("kind") == kind_v1
        and first_request.get("url") == identity["effect_v1"]
        and recover_request.get("kind") == kind_v2
        and recover_request.get("url") == identity["effect_v2"]
        and new_request.get("kind") == kind_v2
        and new_request.get("url") == identity["effect_v2"],
        "execute requests do not select their stated release",
    )
    _require(
        spec_v1
        == {
            "costs": spec_v1.get("costs"),
            "produces": spec_v1.get("produces"),
            "retry_safe": False,
            "queryable": True,
            "target": identity["effect_v1"],
            "method": "POST",
            "response_classifier": "operation-receipt-v1",
            "query_target": identity["query"],
            "query_method": "POST",
            "query_classifier": "operation-observation-v1",
        },
        "v1 query contract differs",
    )
    _require(
        spec_v2
        == {
            "costs": spec_v2.get("costs"),
            "produces": spec_v2.get("produces"),
            "retry_safe": False,
            "queryable": True,
            "target": identity["effect_v2"],
            "method": "POST",
            "response_classifier": "operation-receipt-v1",
            "query_target": identity["query"],
            "query_method": "POST",
            "query_classifier": "operation-observation-v1",
        },
        "v2 query contract differs",
    )
    results1 = _object(v1.get("results"), "v1 results")
    results2 = _object(v2.get("results"), "v2 results")
    capacities1 = _object(v1.get("capacities"), "v1 capacities")
    capacities2 = _object(v2.get("capacities"), "v2 capacities")
    _require(
        len(results1) == len(results2) == len(capacities1) == len(capacities2) == 1,
        "registered workload is not one-dimensional",
    )
    result_name = next(iter(results1))
    capacity_name = next(iter(capacities1))
    _require(
        results1 == {result_name: 1}
        and results2 == {result_name: 2}
        and capacities1 == {capacity_name: 1}
        and capacities2 == {capacity_name: 2}
        and spec_v1["costs"] == {capacity_name: 1}
        and spec_v2["costs"] == {capacity_name: 1}
        and spec_v1["produces"] == {result_name: 1}
        and spec_v2["produces"] == {result_name: 1},
        "Requirement counts do not express one old plus one new reservation",
    )
    _require(kind_v1 != kind_v2, "v1 and v2 use the same Operation kind")
    return v1, v2, kind_v1, kind_v2


def _check_history(
    directory: Path,
    runtime_dir: Path,
    identity: Mapping[str, str],
    identities: Mapping[str, str],
    request_hashes: Mapping[str, str],
    request_body: bytes,
    first_request: Mapping[str, Any],
    recover_request: Mapping[str, Any],
    new_request: Mapping[str, Any],
    expected_old: Mapping[str, Any],
    observer: Mapping[str, Any],
) -> dict[str, Any]:
    v1, v2, kind_v1, kind_v2 = _check_requirements(
        directory, identity, first_request, recover_request, new_request
    )
    certificate_v1, state_v1, verdict_v1 = _check_certificate(directory, "v1", runtime_dir)
    certificate_v2, state_v2, verdict_v2 = _check_certificate(directory, "v2", runtime_dir)
    events = _replay_history(directory / "state/runtime.history")
    _require(len(events) == 9, "runtime History does not contain exactly nine events")
    _check_anchor(directory / "state", len(events), events[-1]["hash"])
    _require(
        _json(directory / "state/history.json", "History API view") == events,
        "History API view differs from binary replay",
    )
    _require(
        [event["operation"] for event in events]
        == [
            "rule.activated",
            "operation.prepared",
            "operation.phase",
            "operation.phase",
            "rule.activated",
            "operation.phase",
            "operation.prepared",
            "operation.phase",
            "operation.phase",
        ],
        "runtime History event shape changed",
    )
    _require(
        events[0]["data"] == {"semantic_version": 1, "certificate": certificate_v1}
        and events[4]["data"] == {"semantic_version": 1, "certificate": certificate_v2},
        "History Rule activations differ from retained Certificates",
    )
    _require(
        certificate_v1.get("schema") == 1
        and certificate_v1.get("decision") == "activate"
        and certificate_v1.get("history") == {"sequence": 0, "hash": ZERO_HASH}
        and certificate_v1.get("from_rule") == 0
        and certificate_v1.get("requirement") == v1,
        "v1 Certificate binding differs",
    )
    _require(
        certificate_v2.get("schema") == 1
        and certificate_v2.get("decision") == "activate"
        and certificate_v2.get("history") == {"sequence": 4, "hash": events[3]["hash"]}
        and certificate_v2.get("from_rule") == 1
        and certificate_v2.get("requirement") == v2,
        "v2 Certificate binding differs",
    )
    rule_v1 = _object(certificate_v1.get("rule"), "v1 Rule")
    rule_v2 = _object(certificate_v2.get("rule"), "v2 Rule")
    _require(rule_v1.get("version") == 1 and rule_v1.get("allow") == [kind_v1], "v1 Rule differs")
    _require(rule_v2.get("version") == 2 and rule_v2.get("allow") == [kind_v2], "v2 Rule differs")
    _hash(certificate_v1.get("digest"), "v1 Certificate digest")
    _hash(certificate_v2.get("digest"), "v2 Certificate digest")
    _require(
        verdict_v1
        == {
            "valid": True,
            "decision": "activate",
            "history_sequence": 0,
            "history_hash": ZERO_HASH,
            "rule_version": 1,
        }
        and verdict_v2
        == {
            "valid": True,
            "decision": "activate",
            "history_sequence": 4,
            "history_hash": events[3]["hash"],
            "rule_version": 2,
        },
        "Certificate verdict binding differs",
    )

    old = _prepare(events[1], identities["old"], "old Operation")
    new = _prepare(events[6], identities["new"], "new Operation")
    expected_contract = {
        "id": identities["old"],
        "domain": identity["domain"],
        "kind": kind_v1,
        "request_hash": request_hashes["old"],
        "rule_version": 1,
        "costs": next(iter(v1["kinds"].values()))["costs"],
        "produces": next(iter(v1["kinds"].values()))["produces"],
        "retry_safe": False,
        "queryable": True,
        "target": identity["effect_v1"],
        "method": "POST",
        "response_classifier": "operation-receipt-v1",
        "query_target": identity["query"],
        "query_method": "POST",
        "query_classifier": "operation-observation-v1",
        "phase": "prepared",
    }
    _require(old == expected_contract, "old Operation did not freeze the complete v1 contract")
    expected_new_contract = dict(expected_contract)
    expected_new_contract.update(
        {
            "id": identities["new"],
            "kind": kind_v2,
            "request_hash": request_hashes["new"],
            "rule_version": 2,
            "costs": next(iter(v2["kinds"].values()))["costs"],
            "produces": next(iter(v2["kinds"].values()))["produces"],
            "target": identity["effect_v2"],
        }
    )
    _require(new == expected_new_contract, "new Operation did not freeze the v2 contract")

    old_updates = _updates(events, identities["old"])
    new_updates = _updates(events, identities["new"])
    _require(
        [item.get("phase") for item in old_updates] == ["dispatched", "unknown", "succeeded"]
        and len([item for item in old_updates if item.get("phase") == "dispatched"]) == 1
        and old_updates[0].get("dispatch_generation") == 1,
        "old Operation was redispatched or skipped a recovery phase",
    )
    _require(
        [item.get("phase") for item in new_updates] == ["dispatched", "succeeded"]
        and new_updates[0].get("dispatch_generation") == 1,
        "new Operation did not execute once",
    )
    owner1 = old_updates[0].get("dispatch_owner")
    owner2 = new_updates[0].get("dispatch_owner")
    _require(
        isinstance(owner1, str)
        and re.fullmatch(r"[0-9a-f]{32}", owner1) is not None
        and isinstance(owner2, str)
        and re.fullmatch(r"[0-9a-f]{32}", owner2) is not None
        and owner1 != owner2,
        "control restart did not change dispatch ownership",
    )
    observation = _object(observer["old"], "settling observation")
    observation_body = base64.b64decode(old_updates[2].get("result_body", ""), validate=True)
    _require(
        _object(_loads(observation_body, "History observation body"), "History observation body")
        == {key: observation[key] for key in ("schema", "operation_id", "request_hash", "outcome", "fact_hash", "remote_reference")}
        and old_updates[2].get("settlement") == "query"
        and old_updates[2].get("result_hash") == observation["fact_hash"]
        and old_updates[2].get("status_code") == 200
        and old_updates[2].get("remote_reference") == "reservation-db.reservation/count=1",
        "History query settlement differs from the observer",
    )

    new_body = base64.b64decode(new_updates[1].get("result_body", ""), validate=True)
    receipt = _object(_loads(new_body, "v2 receipt"), "v2 receipt")
    _require(
        receipt.get("schema") == 1
        and receipt.get("operation_id") == identities["new"]
        and receipt.get("outcome") == "succeeded"
        and receipt.get("remote_reference") == "deathstar/reservation/" + identities["new"]
        and new_updates[1].get("result_hash") == sha256(b"200\x00" + new_body).hexdigest()
        and new_updates[1].get("settlement") in (None, ""),
        "new v2 receipt or History settlement differs",
    )
    _hash(receipt.get("result_hash"), "v2 receipt result hash")

    final_state = _object(_json(directory / "state/final-state.json"), "final State")
    final_rule = _object(final_state.get("rule"), "final Rule")
    _require(
        final_state.get("history") == {"sequence": 9, "hash": events[-1]["hash"]}
        and final_state.get("requirement") == v2
        and final_rule.get("version") == rule_v2.get("version")
        and final_rule.get("requirement_hash") == rule_v2.get("requirement_hash")
        and final_rule.get("allow") == [],
        "final State differs from replayed History",
    )
    operations = _object(final_state.get("operations"), "final Operations")
    _require(set(operations) == {identities["old"], identities["new"]}, "final State has another Operation set")
    final_old = _object(operations[identities["old"]], "final old Operation")
    final_new = _object(operations[identities["new"]], "final new Operation")
    _require(
        all(final_old.get(key) == value for key, value in old.items() if key != "phase")
        and final_old.get("phase") == "succeeded"
        and final_old.get("dispatch_generation") == 1
        and final_old.get("settlement") == "query"
        and final_old.get("result_hash") == observation["fact_hash"],
        "final old Operation differs from frozen v1 Operation and query result",
    )
    _require(
        all(final_new.get(key) == value for key, value in new.items() if key != "phase")
        and final_new.get("phase") == "succeeded"
        and final_new.get("dispatch_generation") == 1
        and final_new.get("settlement") in (None, ""),
        "final new Operation differs from frozen v2 Operation",
    )
    _require(
        _json(directory / "state/active-v1.json", "active v1 State")
        == {
            "history": {"sequence": 1, "hash": events[0]["hash"]},
            "requirement": v1,
            "rule": rule_v1,
            "operations": {},
        },
        "active v1 State differs from History",
    )
    active_v2 = _object(_json(directory / "state/active-v2.json"), "active v2 State")
    _require(
        active_v2.get("history") == {"sequence": 5, "hash": events[4]["hash"]}
        and active_v2.get("requirement") == v2
        and active_v2.get("rule") == rule_v2
        and set(_object(active_v2.get("operations"), "active v2 Operations")) == {identities["old"]},
        "active v2 State differs from replayed open old Operation",
    )

    _require(
        state_v1
        == {
            "schema": 1,
            "history": {"sequence": 0, "hash": ZERO_HASH},
            "from_rule": 0,
            "settled": {"used": {}, "results": {}},
            "open_operations": {},
        },
        "v1 Certificate input is not empty State",
    )
    open_v2 = _object(state_v2.get("open_operations"), "v2 open Operations")
    _require(
        state_v2.get("schema") == 1
        and state_v2.get("history") == {"sequence": 4, "hash": events[3]["hash"]}
        and state_v2.get("from_rule") == 1
        and state_v2.get("settled") == {"used": {}, "results": {}}
        and open_v2
        == {
            identities["old"]: {
                "id": identities["old"],
                "costs": old["costs"],
                "produces": old["produces"],
                "retry_safe": False,
                "queryable": True,
            }
        },
        "v2 Certificate input did not preserve the queryable old Operation",
    )
    return {
        "events": events,
        "old": old,
        "new": new,
        "final": final_state,
        "certificate_v1": certificate_v1,
        "certificate_v2": certificate_v2,
    }


def _transport_document(path: Path, label: str) -> dict[str, Any]:
    value = _object(_json(path, label), label)
    _require(value.get("schema") in (None, 1), f"{label} schema changed")
    return value


def _transport_failed(path: Path, label: str) -> dict[str, Any]:
    value = _transport_document(path, label)
    code = value.get("exit_code", value.get("returncode"))
    status = value.get("http_status", value.get("status"))
    _require(
        type(code) is int
        and code != 0
        and status in (None, 0, "000", "transport-error"),
        f"{label} did not retain a lost transport response",
    )
    _require(value.get("body") in (None, "", {}), f"{label} unexpectedly retained a successful body")
    return value


def _unknown_transport_wrapper(
    path: Path, transport: Mapping[str, Any], label: str
) -> None:
    value = _object(_json(path, label), label)
    _require(
        value
        == {"schema": 1, "outcome": "unknown", "transport": dict(transport)},
        f"{label} differs from the raw failed transport",
    )


def _receipt_document(path: Path, operation_id: str, label: str) -> dict[str, Any]:
    value = _transport_document(path, label)
    body: Any = value.get("body", value)
    if isinstance(body, str):
        body = _loads(body.encode(), label + " body")
    receipt = _object(body, label + " receipt")
    _require(
        receipt.get("schema") == 1
        and receipt.get("operation_id") == operation_id
        and receipt.get("outcome") == "succeeded"
        and receipt.get("remote_reference") == "deathstar/reservation/" + operation_id,
        f"{label} receipt differs",
    )
    _hash(receipt.get("result_hash"), label + " result hash")
    status = value.get("http_status", value.get("status"))
    if status is not None:
        _require(status in (200, "200"), f"{label} HTTP status differs")
    return receipt


def _check_first_unknown(path: Path, operation_id: str) -> dict[str, Any]:
    outcome, error = _unwrap_outcome(_json(path, "first unknown response"), "first unknown response")
    _require(
        outcome.get("operation_id") == operation_id
        and outcome.get("phase") == "unknown"
        and outcome.get("recovered_by_query") is False
        and isinstance(error, str)
        and "unknown" in error.lower(),
        "first runtime response was not an unknown outcome",
    )
    return outcome


def _check_multi_night(
    directory: Path,
    operation_id: str,
    body: bytes,
) -> None:
    request = _object(_loads(body, "multi-night request body"), "multi-night request body")
    _require(
        request
        == {
            "hotel_id": "1",
            "in_date": "2015-04-09",
            "out_date": "2015-04-11",
            "rooms": 1,
            "username": "Cornell_30",
            "password": "0000000000",
        },
        "multi-night control request changed",
    )
    transport = _transport_document(
        directory / "adapter/multi-night-transport.json", "multi-night transport"
    )
    _require(
        type(transport.get("exit_code")) is int
        and transport.get("exit_code") != 0
        and transport.get("http_status") in (400, "400")
        and transport.get("response_bytes", 0) > 0
        and isinstance(transport.get("stderr"), str),
        "multi-night request was not rejected at the adapter boundary",
    )
    response = _object(
        _json(directory / "adapter/multi-night-response.json"),
        "multi-night response",
    )
    _require(
        response
        == {
            "schema": 1,
            "http_status": 400,
            "outcome": "rejected-before-dispatch",
            "transport": transport,
        },
        "multi-night response summary differs from the transport",
    )
    _stats(
        directory / "adapter/multi-night-adapter-stats.json",
        0,
        0,
        "multi-night adapter stats",
    )
    expected = {
        "customer_name": "safe-" + operation_id,
        "hotel_id": "1",
        "in_date": "2015-04-09",
        "out_date": "2015-04-11",
        "rooms": 1,
    }
    _mongo(
        directory / "adapter/multi-night-mongo.json",
        expected,
        0,
        "multi-night Mongo",
    )


def _check_matrix(directory: Path, derived: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    matrix = _object(_json(directory / "baseline-matrix.json"), "baseline matrix")
    _require(set(matrix) == {"schema", "rows", "pass"} and matrix.get("schema") == 1, "baseline matrix fields changed")
    rows = [_object(value, "baseline row") for value in _list(matrix.get("rows"), "baseline rows")]
    _require(len(rows) == 3, "baseline matrix does not contain three conditions")
    by_condition = {str(row.get("condition")): row for row in rows}
    _require(len(by_condition) == 3, "baseline condition names repeat")

    def find(name: str) -> dict[str, Any]:
        matched = [row for condition, row in by_condition.items() if name in condition.lower().replace("_", "-")]
        _require(len(matched) == 1, f"baseline matrix omitted {name}")
        return matched[0]

    for name, key in (("raw", "raw"), ("drain", "drain"), ("query", "proposed")):
        row = find(name)
        facts = derived[key]
        _require(
            row.get("deliveries") == facts["deliveries"]
            and row.get("commits") == facts["commits"]
            and row.get("mongo_rows") == facts["mongo_rows"]
            and row.get("old_version_retained") is facts["old_version_retained"]
            and row.get("recovered_by_query") is facts["recovered_by_query"],
            f"{name} baseline summary differs from raw evidence",
        )
        _require(row.get("pass") is True, f"{name} baseline did not pass its fixed oracle")
    raw = find("raw")
    drain = find("drain")
    proposed = find("query")
    _require(
        raw.get("safety") in (False, "unsafe")
        and raw.get("availability") in (True, "available")
        and drain.get("safety") in (True, "safe")
        and drain.get("availability") in (False, "unavailable")
        and proposed.get("safety") in (True, "safe")
        and proposed.get("availability") in (True, "available"),
        "baseline safety/availability labels contradict the raw outcomes",
    )
    return matrix


def _check_result(
    directory: Path,
    result: Mapping[str, Any],
    upstream: Mapping[str, Any],
    matrix: Mapping[str, Any],
    history: Mapping[str, Any],
) -> None:
    _require(
        set(result)
        == {"schema", "upstream", "conditions", "history", "network_isolation", "pass"}
        and result.get("schema") == 1,
        "result summary fields changed",
    )
    _require(result.get("upstream") == upstream.get("releases"), "result upstream summary differs")
    conditions = _object(result.get("conditions"), "result conditions")
    _require(conditions == {str(row["condition"]): row for row in matrix["rows"]}, "result conditions differ from baseline matrix")
    events = history["events"]
    _require(
        result.get("history") == {"sequence": len(events), "hash": events[-1]["hash"]},
        "result History summary differs from replay",
    )
    _require(result.get("network_isolation") is True, "result does not record network isolation")
    _require(result.get("pass") is True, "result did not record a successful derived run")


def check_evidence(
    directory: Path | str,
    *,
    runtime_dir: Path | str = DEFAULT_RUNTIME,
) -> dict[str, Any]:
    """Check a complete retained run and return only independently derived facts."""

    root = Path(directory).resolve()
    runtime = Path(runtime_dir).resolve()
    _require(root.is_dir(), "DeathStar evidence directory is absent")
    _require((runtime / "go.mod").is_file(), "runtime source for fresh Certificate checks is absent")

    result = _object(_json(root / "result.json"), "result summary")
    upstream = _check_upstream(root)
    _check_official_graph(root, upstream)
    identity, identities = _result_identity(upstream)

    first_request, first_body, first_input = _request_document(root / "proposed/execute-first.json")
    recover_request, recover_body, recover_input = _request_document(root / "proposed/execute-recover.json")
    new_request, new_body, new_input = _request_document(root / "proposed/execute-new.json")
    _require(
        first_request.get("call_id") == identity["old"]
        and recover_request.get("call_id") == identity["old"]
        and new_request.get("call_id") == identity["new"],
        "execute request call identities differ",
    )
    _require(
        first_body == recover_body
        and first_input == recover_input,
        "recovery changed the old external request body",
    )
    raw_body = _read(root / "baselines/raw-retry/request-body.json")
    drain_body = _read(root / "baselines/old-version-drain/request-body.json")
    old_body = _read(root / "proposed/old-request-body.json")
    saved_new_body = _read(root / "proposed/new-request-body.json")
    zero_body = _read(root / "adapter/unexecuted-request-body.json")
    multi_body = _read(root / "adapter/multi-night-request-body.json")
    _require(
        raw_body == drain_body == old_body == saved_new_body == zero_body
        and old_body == first_body
        and saved_new_body == new_body,
        "condition request bodies are not byte-identical to the exact gateway requests",
    )
    raw_input = _object(_loads(raw_body, "raw-retry request body"), "raw-retry request body")
    drain_input = _object(_loads(drain_body, "old-version-drain request body"), "old-version-drain request body")
    zero_input = _object(_loads(zero_body, "unexecuted request body"), "unexecuted request body")
    expected = {
        "raw": _fact(identities["raw"], raw_input),
        "drain": _fact(identities["drain"], drain_input),
        "old": _fact(identities["old"], first_input),
        "new": _fact(identities["new"], new_input),
    }
    request_hashes = {
        "raw": _observer_request(
            root / "baselines/raw-retry/observer-request.json",
            identities["raw"],
            identity["raw_effect"],
            raw_body,
            "raw-retry observer request",
        ),
        "drain": _observer_request(
            root / "baselines/old-version-drain/observer-request.json",
            identities["drain"],
            identity["drain_effect"],
            drain_body,
            "old-version-drain observer request",
        ),
        "old": _gateway_request_hash(identity["effect_v1"], first_body, identities["old"]),
        "new": _gateway_request_hash(identity["effect_v2"], new_body, identities["new"]),
        "zero": _observer_request(
            root / "adapter/unexecuted-observer-request.json",
            identities["zero"],
            identity["effect_v1"],
            zero_body,
            "unexecuted observer request",
        ),
    }
    _require(
        _fact(identities["zero"], zero_input)["customer_name"]
        == "safe-" + identities["zero"],
        "unexecuted observer body or identity differs",
    )
    _check_multi_night(root, identities["multi"], multi_body)

    raw_mongo = _mongo(root / "baselines/raw-retry/mongo.json", expected["raw"], 2, "raw-retry Mongo")
    raw_audit = _audit(root / "baselines/raw-retry/adapter-audit.jsonl", identities["raw"], 2, "raw-retry audit")
    _stats(root / "baselines/raw-retry/adapter-stats.json", 2, 1, "raw-retry stats")
    raw_transport = _transport_failed(
        root / "baselines/raw-retry/first-transport.json",
        "raw-retry first transport",
    )
    _unknown_transport_wrapper(
        root / "baselines/raw-retry/first-response.json",
        raw_transport,
        "raw-retry first response",
    )
    _receipt_document(root / "baselines/raw-retry/second-response.json", identities["raw"], "raw-retry second response")

    drain_mongo = _mongo(
        root / "baselines/old-version-drain/mongo.json", expected["drain"], 1, "old-version-drain Mongo"
    )
    drain_audit = _audit(
        root / "baselines/old-version-drain/adapter-audit.jsonl",
        identities["drain"],
        1,
        "old-version-drain audit",
    )
    _stats(root / "baselines/old-version-drain/adapter-stats.json", 1, 1, "old-version-drain stats")
    drain_transport = _transport_failed(
        root / "baselines/old-version-drain/transport.json",
        "old-version-drain transport",
    )
    _unknown_transport_wrapper(
        root / "baselines/old-version-drain/response.json",
        drain_transport,
        "old-version-drain response",
    )
    drain_frontend = _running_inspection(
        root / "baselines/old-version-drain/frontend-inspect.json",
        "retained v1 frontend",
    )
    drain_effect = _running_inspection(
        root / "baselines/old-version-drain/effect-inspect.json",
        "retained v1 effect",
    )
    release_v1 = _object(_object(upstream["releases"], "upstream releases")["v1"], "v1 release")
    runtime_provenance = _object(upstream["runtime"], "runtime provenance")
    _require(
        drain_frontend.get("Image") == release_v1.get("image_id")
        and _object(drain_frontend.get("Config"), "retained v1 frontend configuration").get("Image")
        == release_v1.get("image")
        and drain_effect.get("Image") == runtime_provenance.get("image_id")
        and _object(drain_effect.get("Config"), "retained v1 effect configuration").get("Image")
        == runtime_provenance.get("image"),
        "old-version-drain retained another frontend or adapter image",
    )

    proposed_old_mongo = _mongo(root / "proposed/mongo-old.json", expected["old"], 1, "proposed old Mongo")
    proposed_new_mongo = _mongo(root / "proposed/mongo-new.json", expected["new"], 1, "proposed new Mongo")
    proposed_old_audit = _audit(root / "proposed/effect-v1-audit.jsonl", identities["old"], 1, "proposed v1 audit")
    proposed_new_audit = _audit(
        root / "proposed/effect-v2-audit.jsonl",
        identities["new"],
        1,
        "proposed v2 audit",
        first_drop=False,
    )
    _stats(root / "proposed/effect-v1-stats.json", 1, 1, "proposed v1 stats")
    _stats(root / "proposed/effect-v2-stats.json", 1, 0, "proposed v2 stats")
    proposed_v1_frontend = _running_inspection(
        root / "proposed/frontend-v1-before-removal.json",
        "proposed v1 frontend before removal",
    )
    proposed_v1_effect = _running_inspection(
        root / "proposed/effect-v1-before-removal.json",
        "proposed v1 effect before removal",
    )
    _require(
        proposed_v1_frontend.get("Image") == release_v1.get("image_id")
        and proposed_v1_effect.get("Image") == runtime_provenance.get("image_id"),
        "pre-removal inspection did not identify the v1 frontend/effect",
    )
    _check_first_unknown(root / "proposed/first-unknown.json", identities["old"])
    recovered = _check_outcome(
        root / "proposed/recovered-response.json", identities["old"], recovered=True, label="recovered response"
    )
    direct_new = _check_outcome(
        root / "proposed/new-response.json", identities["new"], recovered=False, label="new response"
    )

    observer = _check_observer(root, identities, request_hashes, expected)
    _require(recovered.get("result_hash") == observer["old"]["fact_hash"], "recovered outcome does not join the Mongo fact hash")
    history = _check_history(
        root,
        runtime,
        identity,
        identities,
        request_hashes,
        first_body,
        first_request,
        recover_request,
        new_request,
        expected["old"],
        observer,
    )
    _require(
        direct_new.get("result_hash")
        == history["final"]["operations"][identities["new"]]["result_hash"],
        "new response differs from final State",
    )
    removal = _removal_probes(root / "docker/removal-probes.json")
    networks = _check_network(root)
    timeline = _timeline(root / "timeline.jsonl")

    derived = {
        "raw": {
            "deliveries": len(raw_audit), "commits": len(raw_mongo), "mongo_rows": len(raw_mongo),
            "old_version_retained": True, "recovered_by_query": False,
        },
        "drain": {
            "deliveries": len(drain_audit), "commits": len(drain_mongo), "mongo_rows": len(drain_mongo),
            "old_version_retained": True, "recovered_by_query": False,
        },
        "proposed": {
            "deliveries": len(proposed_old_audit) + len(proposed_new_audit),
            "commits": len(proposed_old_mongo) + len(proposed_new_mongo),
            "mongo_rows": len(proposed_old_mongo) + len(proposed_new_mongo),
            "old_version_retained": False, "recovered_by_query": True,
        },
    }
    matrix = _check_matrix(root, derived)
    _check_result(root, result, upstream, matrix, history)
    return {
        "valid": True,
        "history_chain_replayed": True,
        "history_sequence": len(history["events"]),
        "history_hash": history["events"][-1]["hash"],
        "old_operation_id": identities["old"],
        "new_operation_id": identities["new"],
        "old_dispatches": 1,
        "old_mongo_rows": len(proposed_old_mongo),
        "raw_retry_mongo_rows": len(raw_mongo),
        "recovered_by_query": recovered["recovered_by_query"],
        "source_versions": [V1_COMMIT, V2_COMMIT],
        "network_count": len(networks),
        "removal_checked": bool(removal),
        "timeline_events": len(timeline),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path, help="retained step-0015 evidence directory")
    parser.add_argument("--runtime-dir", type=Path, default=DEFAULT_RUNTIME)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        verdict = check_evidence(arguments.evidence, runtime_dir=arguments.runtime_dir)
    except (EvidenceError, OSError, subprocess.SubprocessError) as error:
        print(json.dumps({"valid": False, "error": str(error)}, sort_keys=True))
        return 1
    print(json.dumps(verdict, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
