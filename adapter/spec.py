"""Load and validate the frozen runtime litmus specification.

This module intentionally knows nothing about oracle expectations.  It is safe
to import from the runner and controller side of the experiment.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable

import yaml


ALLOWED_OPERATIONS = frozenset(
    {
        "grant",
        "checkpoint",
        "fork",
        "restore",
        "delegate",
        "select",
        "reserve",
        "prepare",
        "dispatch",
        "revoke",
        "merge",
    }
)
ALLOWED_CRASH_MODES = frozenset(
    {"none", "before_dispatch", "after_remote_success", "after_controller_commit"}
)
FORBIDDEN_WORKER_KEYS = frozenset(
    {
        "expected",
        "expectation",
        "oracle",
        "decision",
        "terminal_state",
        "abstract_label",
        "unsafe_if_accepted",
    }
)


@dataclass(frozen=True)
class LitmusCase:
    case_id: str
    crash_mode: str
    dispatch_site: str | None
    operations: tuple[dict[str, Any], ...]

    @property
    def opaque_worker_id(self) -> str:
        return "case-" + sha256(self.case_id.encode("utf-8")).hexdigest()[:16]

    def worker_payload(self, policy: str) -> dict[str, Any]:
        """Return the only case material a controller worker may receive."""

        return {
            "opaque_case_id": self.opaque_worker_id,
            "policy": policy,
            "crash_mode": self.crash_mode,
            "dispatch_site": self.dispatch_site,
            "operations": [dict(operation) for operation in self.operations],
        }


def _walk_keys(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key)
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def load_litmus(path: str | Path) -> tuple[LitmusCase, ...]:
    source = Path(path)
    document = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("version") != 1:
        raise ValueError("litmus document must have version 1")
    raw_cases = document.get("cases")
    if not isinstance(raw_cases, list) or len(raw_cases) != 20:
        raise ValueError("litmus document must contain exactly 20 cases")

    cases: list[LitmusCase] = []
    seen_ids: set[str] = set()
    for raw in raw_cases:
        if not isinstance(raw, dict):
            raise ValueError("each litmus case must be an object")
        case_id = raw.get("id")
        if not isinstance(case_id, str) or not case_id:
            raise ValueError("each litmus case needs a nonempty id")
        if case_id in seen_ids:
            raise ValueError(f"duplicate case id: {case_id}")
        seen_ids.add(case_id)
        crash_mode = raw.get("crash_mode")
        if crash_mode not in ALLOWED_CRASH_MODES:
            raise ValueError(f"invalid crash mode for {case_id}: {crash_mode}")
        dispatch_site = raw.get("dispatch_site")
        if dispatch_site is not None and not isinstance(dispatch_site, str):
            raise ValueError(f"invalid dispatch site for {case_id}")
        operations = raw.get("operations")
        if not isinstance(operations, list) or not operations:
            raise ValueError(f"case {case_id} has no operation stream")
        copied: list[dict[str, Any]] = []
        for operation in operations:
            if not isinstance(operation, dict):
                raise ValueError(f"case {case_id} contains a non-object operation")
            kind = operation.get("op")
            if kind not in ALLOWED_OPERATIONS:
                raise ValueError(f"case {case_id} contains unsupported operation {kind!r}")
            forbidden = FORBIDDEN_WORKER_KEYS.intersection(_walk_keys(operation))
            if forbidden:
                raise ValueError(
                    f"case {case_id} leaks oracle keys into worker input: {sorted(forbidden)}"
                )
            copied.append(dict(operation))
        cases.append(
            LitmusCase(
                case_id=case_id,
                crash_mode=crash_mode,
                dispatch_site=dispatch_site,
                operations=tuple(copied),
            )
        )

    expected_ids = {f"C{index:02d}" for index in range(1, 21)}
    if seen_ids != expected_ids:
        raise ValueError(f"case IDs differ from C01--C20: {sorted(seen_ids)}")
    return tuple(cases)
