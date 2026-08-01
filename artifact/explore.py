"""Deterministic exhaustive checks over small authority-continuity states."""

from __future__ import annotations

import argparse
import json
from functools import lru_cache
from itertools import product
from pathlib import Path
from typing import Iterable, Iterator

from authority_continuity import (
    Claim,
    FrontierFamily,
    NoTopologyRepair,
    is_downward_closed,
    make_state,
    plain_escape_counterexample,
    powerset,
    snapshot_local_impossibility_litmus,
    vector_leq,
)


def all_downward_closed_families(branches: tuple[str, ...]) -> Iterator[FrontierFamily]:
    frontiers = tuple(powerset(branches))
    # Every nonempty downward-closed family contains the empty frontier.
    for mask in range(1 << len(frontiers)):
        if not (mask & 1):
            continue
        family = frozenset(
            frontier for index, frontier in enumerate(frontiers) if mask & (1 << index)
        )
        if is_downward_closed(family):
            yield family


@lru_cache(maxsize=None)
def downward_closed_subfamilies(family: FrontierFamily) -> tuple[FrontierFamily, ...]:
    frontiers = tuple(sorted(family, key=lambda item: (len(item), tuple(sorted(item)))))
    result = []
    for mask in range(1, 1 << len(frontiers)):
        candidate = frozenset(
            frontier for index, frontier in enumerate(frontiers) if mask & (1 << index)
        )
        if is_downward_closed(candidate):
            result.append(candidate)
    return tuple(result)


def proper_nonempty_subsets(items: tuple[str, ...]) -> Iterable[tuple[str, ...]]:
    for subset in powerset(items):
        if subset:
            yield tuple(sorted(subset))


def exhaustive_checks() -> dict[str, object]:
    ac_cases = 0
    maximal_cases = 0
    safe_restrictions = 0
    confluence_cases = 0

    for branch_count in range(1, 4):
        branches = tuple(f"b{index}" for index in range(branch_count))
        families = tuple(all_downward_closed_families(branches))
        for family in families:
            for weights in product((1, 2), repeat=branch_count):
                conditional = tuple(
                    Claim(f"c{index}", (weights[index],), branch)
                    for index, branch in enumerate(branches)
                )
                for durable_load in (0, 1):
                    durable = (
                        (Claim("durable", (durable_load,), None),)
                        if durable_load
                        else ()
                    )
                    for grant in range(8):
                        state = make_state(
                            (grant,),
                            durable=durable,
                            conditional=conditional,
                            frontiers=family,
                        )
                        # Independent formulations of AC: universal frontier check
                        # and componentwise supremum need.
                        ac_cases += 1
                        assert state.authority_continuous == vector_leq(state.need, state.grant)
                        if not state.authority_continuous:
                            continue

                        present_branches = frozenset().union(*family)
                        for index, branch in enumerate(branches):
                            if branch not in present_branches:
                                continue
                            claim_id = f"c{index}"
                            repaired = state.promote_maximally((claim_id,))
                            maximal_cases += 1
                            assert repaired.authority_continuous
                            assert is_downward_closed(repaired.frontiers)

                            plain_target = state.promote_plain((claim_id,))
                            for restriction in downward_closed_subfamilies(family):
                                candidate = plain_target.with_frontiers(restriction)
                                if candidate.authority_continuous:
                                    safe_restrictions += 1
                                    assert restriction <= repaired.frontiers

                        claim_ids = tuple(f"c{index}" for index in range(branch_count))
                        if branch_count < 2:
                            continue
                        for left in proper_nonempty_subsets(claim_ids):
                            remaining = tuple(item for item in claim_ids if item not in left)
                            for right in proper_nonempty_subsets(remaining):
                                union = tuple(sorted(left + right))
                                try:
                                    batch = state.promote_maximally(union)
                                except NoTopologyRepair:
                                    continue
                                left_then_right = state.promote_maximally(left).promote_maximally(right)
                                right_then_left = state.promote_maximally(right).promote_maximally(left)
                                assert batch == left_then_right == right_then_left
                                confluence_cases += 1

    source, escaped, witness = plain_escape_counterexample()
    litmus = snapshot_local_impossibility_litmus()
    assert source.authority_continuous and not escaped.authority_continuous
    assert litmus["replace"]["safe"] and not litmus["live"]["safe"]

    return {
        "schema_version": 1,
        "artifact_kind": "finite executable validation (not mechanized proof)",
        "parameters": {
            "authority_coordinates": 1,
            "branches": [1, 2, 3],
            "claim_weights": [1, 2],
            "durable_loads": [0, 1],
            "grants": list(range(8)),
            "frontier_families": "all nonempty downward-closed families",
        },
        "checks": {
            "ac_need_equivalence": {"states": ac_cases, "status": "pass"},
            "single_claim_maximal_support": {
                "safe_source_owner_cases": maximal_cases,
                "safe_downward_restrictions_checked": safe_restrictions,
                "status": "pass",
            },
            "batched_promotion_confluence": {
                "ordered_disjoint_batches": confluence_cases,
                "status": "pass",
            },
            "snapshot_local_impossibility": {"status": "pass", **litmus},
            "plain_escape_counterexample": {
                "status": "pass",
                "source_safe": source.authority_continuous,
                "target_safe": escaped.authority_continuous,
                "grant": list(escaped.grant),
                "violating_frontier": sorted(witness),
                "violating_load": list(escaped.frontier_load(witness)),
            },
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        help="also write the deterministic JSON result to this path",
    )
    args = parser.parse_args()
    result = exhaustive_checks()
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    print(encoded, end="")
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")


if __name__ == "__main__":
    main()
