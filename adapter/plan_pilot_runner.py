"""Deterministic count-only transition-matrix runner for the plan pilot.

The cases are synthetic public fixtures.  Their individual states and
operations are never emitted; the output contains only aggregate decision
counts.  The pure complete-successor oracle remains independently implemented in
``adapter.plan_replay`` and is not imported by the controller.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Mapping

from adapter.plan_pilot import initial_state
from adapter.plan_replay import aggregate_json, decision_baselines


def _state(
    *,
    capacity: int,
    slots: list[str],
    claims: list[Mapping[str, Any]],
) -> dict[str, Any]:
    return initial_state(grants={"g": capacity}, ordered_slots=slots, claims=claims)


def controlled_decisions() -> list[dict[str, bool]]:
    """Return a fixed public transition matrix without case trajectories."""

    two_slot = [
        {"claim": "c1", "grant": "g", "demand": 1, "owner": "o1", "slot": "s1"},
        {"claim": "c2", "grant": "g", "demand": 1, "owner": "o2", "slot": "s2"},
    ]
    disjoint_state = _state(capacity=3, slots=["s1", "s2"], claims=two_slot)
    cross_state = _state(capacity=2, slots=["s1", "s2"], claims=two_slot)
    same_root_state = _state(
        capacity=3,
        slots=["s1"],
        claims=[
            {
                "claim": "source",
                "grant": "g",
                "demand": 2,
                "owner": "o1",
                "slot": "s1",
                "batch_root": "root",
            },
            {
                "claim": "peer",
                "grant": "g",
                "demand": 1,
                "owner": "o2",
                "slot": "s1",
                "batch_root": "root",
            },
        ],
    )

    cases = [
        (
            disjoint_state,
            {
                "op": "disjoint_mutation",
                "claim": "outside",
                "grant": "g",
                "demand": 1,
                "owner": "outside-owner",
            },
        ),
        (
            same_root_state,
            {
                "op": "refine",
                "plan_version": 0,
                "source_claim": "source",
                "children": [
                    {"claim": "replacement", "owner": "o1", "demand": 2},
                ],
            },
        ),
        (
            same_root_state,
            {
                "op": "merge",
                "plan_version": 0,
                "source_owners": ["o1", "o2"],
                "target_owner": "o1",
            },
        ),
        (
            same_root_state,
            {
                "op": "merge",
                "plan_version": 0,
                "source_owners": ["o1", "o2"],
                "target_owner": "same-root-join",
            },
        ),
        (
            cross_state,
            {
                "op": "merge",
                "plan_version": 0,
                "source_owners": ["o1", "o2"],
                "target_owner": "cross-root-join",
            },
        ),
        (cross_state, {"op": "revoke", "plan_version": 0, "grant": "g"}),
        (
            cross_state,
            {"op": "restrict", "plan_version": 0, "keep_owners": ["o1"]},
        ),
    ]
    return [decision_baselines(state, operation) for state, operation in cases]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = aggregate_json(controlled_decisions()) + "\n"
    if args.output is None:
        print(payload, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
