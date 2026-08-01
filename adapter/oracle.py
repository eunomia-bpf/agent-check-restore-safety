"""Independent fixed-suite oracle.

Controller and worker modules must never import this module.  It is used only
after a run to compare raw decisions and independently captured sink state
against the predeclared LTS/litmus expectations.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ObservationProbe:
    name: str
    action: str
    decision: str
    abstract_label: str


@dataclass(frozen=True)
class OracleCase:
    case_id: str
    decisions: dict[str, str]
    aggregate_sink_outcomes: dict[str, int]
    settled_receipts: tuple[str, ...]
    unsafe_if_accepted: tuple[str, ...]
    observation_probe: ObservationProbe | None


def load_oracle(path: str | Path) -> dict[str, OracleCase]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("version") != 1:
        raise ValueError("oracle document must have version 1")
    provenance = document.get("provenance")
    if not isinstance(provenance, dict) or provenance.get("frozen_before_controller_run") is not True:
        raise ValueError("oracle provenance must state that it was frozen before the run")
    raw_cases = document.get("cases")
    if not isinstance(raw_cases, dict):
        raise ValueError("oracle cases must be an object keyed by case ID")

    cases: dict[str, OracleCase] = {}
    for case_id, raw in raw_cases.items():
        if not isinstance(raw, dict):
            raise ValueError(f"oracle case {case_id} must be an object")
        raw_decisions = raw.get("decisions")
        if not isinstance(raw_decisions, dict) or not raw_decisions:
            raise ValueError(f"oracle case {case_id} has no decisions")
        decisions = {str(key): str(value) for key, value in raw_decisions.items()}
        if not set(decisions.values()) <= {"accept", "reject"}:
            raise ValueError(f"oracle case {case_id} has an invalid decision")
        raw_counts = raw.get("aggregate_sink_outcomes", {})
        if not isinstance(raw_counts, dict):
            raise ValueError(f"oracle case {case_id} has invalid sink counts")
        counts = {str(key): int(value) for key, value in raw_counts.items()}
        if any(value < 0 for value in counts.values()):
            raise ValueError(f"oracle case {case_id} has a negative sink count")
        raw_probe: Any = raw.get("observation_probe")
        probe = None
        if raw_probe is not None:
            if not isinstance(raw_probe, dict):
                raise ValueError(f"oracle case {case_id} has an invalid observation probe")
            probe = ObservationProbe(
                name=str(raw_probe["name"]),
                action=str(raw_probe["action"]),
                decision=str(raw_probe["decision"]),
                abstract_label=str(raw_probe["abstract_label"]),
            )
        cases[str(case_id)] = OracleCase(
            case_id=str(case_id),
            decisions=decisions,
            aggregate_sink_outcomes=counts,
            settled_receipts=tuple(str(value) for value in raw.get("settled_receipts", ())),
            unsafe_if_accepted=tuple(str(value) for value in raw.get("unsafe_if_accepted", ())),
            observation_probe=probe,
        )
    expected = {f"C{index:02d}" for index in range(1, 21)}
    if set(cases) != expected:
        raise ValueError("oracle must cover exactly C01--C20")
    return cases


def assert_controller_oracle_separation(root: str | Path) -> None:
    """Fail if authority-critical worker modules reference oracle/checker code."""

    directory = Path(root)
    forbidden_tokens = ("adapter.oracle", "from .oracle", "check_results", "oracle.yaml")
    for relative in ("controller.py", "worker.py", "sink.py"):
        path = directory / relative
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for token in forbidden_tokens:
            if token in text:
                raise AssertionError(f"{relative} violates oracle separation with {token!r}")
