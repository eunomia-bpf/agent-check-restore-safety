"""Request-conditioned observation projections for the fixed runtime suite."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Iterable


TIMESTAMP_KEYS = frozenset(
    {"timestamp", "time", "created_at", "updated_at", "started_at", "completed_at", "collected_at"}
)
ID_NAMESPACES = {
    "threadId": "thread",
    "thread_id": "thread",
    "history_id": "thread",
    "parent_history_id": "thread",
    "turnId": "turn",
    "turn_id": "turn",
    "callId": "call",
    "call_id": "call",
    "effect_id": "effect",
    "attempt_id": "attempt",
    "claim_id": "claim",
    "source_claim_id": "claim",
    "grant_id": "grant",
    "branch_id": "branch",
    "source": "branch",
    "target": "branch",
    "owner_branch": "branch",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


class AlphaNormalizer:
    """Rename run-local identifiers by namespace and first occurrence."""

    def __init__(self) -> None:
        self._aliases: dict[str, dict[str, str]] = defaultdict(dict)

    def _rename(self, namespace: str, value: str) -> str:
        aliases = self._aliases[namespace]
        if value not in aliases:
            aliases[value] = f"{namespace}-{len(aliases) + 1}"
        return aliases[value]

    def normalize(self, value: Any, key: str | None = None) -> Any:
        if key in TIMESTAMP_KEYS:
            return None
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            for child_key, child in value.items():
                if child_key in TIMESTAMP_KEYS:
                    continue
                normalized = self.normalize(child, str(child_key))
                if normalized is not None:
                    result[str(child_key)] = normalized
            return result
        if isinstance(value, list):
            return [self.normalize(child, key) for child in value]
        if isinstance(value, str) and key in ID_NAMESPACES:
            return self._rename(ID_NAMESPACES[key], value)
        return value


def _redact_arguments(value: Any) -> Any:
    """Retain equality while preventing raw arguments from entering a key."""

    if value is None:
        return None
    encoded = canonical_json(value).encode("utf-8")
    return {"canonical_sha256": sha256(encoded).hexdigest()}


def normalize_action(action: dict[str, Any], normalizer: AlphaNormalizer) -> dict[str, Any]:
    allowed = {
        "kind",
        "operation",
        "effect_id",
        "claim_id",
        "grant_id",
        "branch_id",
        "source",
        "target",
        "source_role",
        "demand",
        "binding",
        "same_operation",
        "request",
    }
    selected = {key: value for key, value in action.items() if key in allowed}
    if "arguments" in action:
        selected["arguments"] = _redact_arguments(action["arguments"])
    return normalizer.normalize(selected)


@dataclass(frozen=True)
class ProbeRecord:
    case_id: str
    workspace: dict[str, Any]
    provider_events: tuple[dict[str, Any], ...]
    trusted_events: tuple[dict[str, Any], ...]
    action: dict[str, Any]
    oracle_decision: str


def observation_key(record: ProbeRecord, level: str) -> str:
    if level not in {"O0", "O1", "O2"}:
        raise ValueError(f"unknown observation level: {level}")
    normalizer = AlphaNormalizer()
    prefix: dict[str, Any] = {"workspace": normalizer.normalize(record.workspace)}
    if level in {"O1", "O2"}:
        prefix["provider_events"] = normalizer.normalize(list(record.provider_events))
    if level == "O2":
        prefix["trusted_events"] = normalizer.normalize(list(record.trusted_events))
    action = normalize_action(record.action, normalizer)
    return canonical_json({"prefix": prefix, "action": action})


def mixed_label_fibers(records: Iterable[ProbeRecord], level: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[ProbeRecord]] = defaultdict(list)
    for record in records:
        grouped[observation_key(record, level)].append(record)
    mixed: list[dict[str, Any]] = []
    for key, members in grouped.items():
        labels = {member.oracle_decision for member in members}
        if len(labels) > 1:
            mixed.append(
                {
                    "key_sha256": sha256(key.encode("utf-8")).hexdigest(),
                    "cases": sorted(member.case_id for member in members),
                    "labels": sorted(labels),
                }
            )
    return sorted(mixed, key=lambda fiber: (fiber["cases"], fiber["labels"]))
