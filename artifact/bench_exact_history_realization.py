#!/usr/bin/env python3
"""Reproducible scaling sweep for the current prefix-robust admission core.

The benchmark runs ``check_admission`` in fresh Python processes.  Workload
construction is outside the timed interval.  The result characterizes the
bounded explicit constructor; it is not Agent-runtime throughput evidence.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
from itertools import permutations
import json
from math import factorial
import os
from pathlib import Path
import platform
import resource
import statistics
import subprocess
import sys
import time
from typing import Any, Sequence

from exact_history_realization import (
    MAX_LINEARIZATIONS,
    MAX_OCCURRENCES_PER_OUTCOME,
    MAX_OUTCOMES,
    MAX_SAFE_EXECUTIONS,
    Contract,
    HistoryState,
    LiveBranch,
    ModelError,
    Occurrence,
    Pomset,
    PrefixPolicy,
    check_admission,
)


HERE = Path(__file__).resolve().parent
REPO = HERE.parent
DEFAULT_OUTPUT = HERE / "results" / "exact_history_realization_scaling.json"
REPETITIONS = 5
SHARED_PREFIX_SIZES = (2, 8, 32, 64, 128)
UNORDERED_WIDTHS = (3, 4, 5, 6)
OUTCOME_CAP_FAILURE = MAX_OUTCOMES + 1
OCCURRENCE_CAP_FAILURE = MAX_OCCURRENCES_PER_OUTCOME + 1


def _shared_prefix(
    size: int,
    *,
    admitted: bool,
) -> tuple[HistoryState, Contract]:
    shared = Occurrence("x", "cell:x")
    outcomes = tuple(
        Pomset(
            (shared, Occurrence(f"y:{index}", f"cell:y:{index}")),
            frozenset({("x", f"y:{index}")}) if admitted else frozenset(),
        )
        for index in range(size)
    )
    contract = Contract(outcomes)
    if admitted:
        policy = PrefixPolicy.from_maximal(
            *(("cell:x", f"cell:y:{index}") for index in range(size))
        )
    else:
        policy = PrefixPolicy.from_maximal(
            ("cell:y:0", "cell:x"),
            *(("cell:x", f"cell:y:{index}") for index in range(1, size)),
        )
    return (
        HistoryState(
            branches=(LiveBranch("branch", contract, "generation"),),
            policy=policy,
        ),
        contract,
    )


def _unordered(width: int) -> tuple[HistoryState, Contract]:
    nodes = tuple(
        Occurrence(f"x:{index}", f"cell:{index}") for index in range(width)
    )
    contract = Contract((Pomset(nodes),))
    cell_orders = tuple(
        tuple(f"cell:{index}" for index in order)
        for order in permutations(range(width))
    )
    return (
        HistoryState(
            branches=(LiveBranch("branch", contract, "generation"),),
            policy=PrefixPolicy.from_maximal(*cell_orders),
        ),
        contract,
    )


def _peak_rss_kb() -> int:
    status = Path("/proc/self/status")
    if status.exists():
        for line in status.read_text(encoding="utf-8").splitlines():
            if line.startswith("VmHWM:"):
                return int(line.split()[1])
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


def _run_success(kind: str, size: int) -> dict[str, Any]:
    if kind == "shared_accept":
        state, contract = _shared_prefix(size, admitted=True)
    elif kind == "shared_reject":
        state, contract = _shared_prefix(size, admitted=False)
    elif kind == "unordered":
        state, contract = _unordered(size)
    else:  # pragma: no cover - guarded by the parent matrix
        raise ValueError(f"unknown success workload: {kind}")

    started = time.perf_counter_ns()
    result = check_admission(state, contract)
    elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
    row = {
        "kind": kind,
        "size": size,
        "core_elapsed_ms": round(elapsed_ms, 6),
        "peak_rss_kb": _peak_rss_kb(),
        "outcomes": len(result.outcomes),
        "candidate_completions": len(result.candidate_completions),
        "surviving_indexed_completions": len(
            result.surviving_indexed_completions
        ),
        "language_prefixes": len(result.language_w),
        "descending_chain_sizes": [
            len(step) for step in result.descending_chain
        ],
        "pruning_causes": len(result.pruning_causes),
        "survivor_witnesses": len(result.survivor_witnesses),
        "admitted": result.admitted,
    }
    if kind == "shared_accept":
        assert result.admitted
        assert len(result.candidate_completions) == size
        assert len(result.surviving_indexed_completions) == size
        assert len(result.survivor_witnesses) == size * (2 * size + 1)
    elif kind == "shared_reject":
        assert not result.admitted
        assert len(result.candidate_completions) == size
        assert [len(step) for step in result.descending_chain] == [size, 1, 0]
        assert len(result.pruning_causes) == size
    else:
        completions = factorial(size)
        assert result.admitted
        assert len(result.candidate_completions) == completions
        assert len(result.surviving_indexed_completions) == completions
        assert len(result.survivor_witnesses) == completions * (size + 1)
    return row


def _run_cap(kind: str, size: int) -> dict[str, Any]:
    expected = {
        "outcome_cap": f"contract exceeds the {MAX_OUTCOMES}-outcome cap",
        "occurrence_cap": (
            f"pomset exceeds the {MAX_OCCURRENCES_PER_OUTCOME}-occurrence cap"
        ),
    }[kind]
    started = time.perf_counter_ns()
    try:
        if kind == "outcome_cap":
            Contract(
                tuple(
                    Pomset((Occurrence(f"x:{index}", f"cell:{index}"),))
                    for index in range(size)
                )
            )
        else:
            Pomset(
                tuple(
                    Occurrence(f"x:{index}", f"cell:{index}")
                    for index in range(size)
                )
            )
    except ModelError as error:
        diagnostic = str(error)
    else:  # pragma: no cover - indicates a broken fail-closed control
        raise AssertionError(f"{kind} unexpectedly passed")
    elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
    if diagnostic != expected:
        raise AssertionError(
            f"{kind}: expected {expected!r}, observed {diagnostic!r}"
        )
    return {
        "kind": kind,
        "size": size,
        "validation_elapsed_ms": round(elapsed_ms, 6),
        "peak_rss_kb": _peak_rss_kb(),
        "status": "rejected_as_planned",
        "diagnostic": diagnostic,
    }


def _git_value(arguments: list[str]) -> str | None:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=REPO,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def _file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _cpu_model() -> str:
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        for line in cpuinfo.read_text(encoding="utf-8").splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    return platform.processor()


def _summarize_success(samples: list[dict[str, Any]]) -> dict[str, Any]:
    semantic_keys = (
        "kind",
        "size",
        "outcomes",
        "candidate_completions",
        "surviving_indexed_completions",
        "language_prefixes",
        "descending_chain_sizes",
        "pruning_causes",
        "survivor_witnesses",
        "admitted",
    )
    semantic = {key: samples[0][key] for key in semantic_keys}
    for sample in samples[1:]:
        assert all(sample[key] == value for key, value in semantic.items())
    times = [sample["core_elapsed_ms"] for sample in samples]
    rss = [sample["peak_rss_kb"] for sample in samples]
    return {
        **semantic,
        "repetitions": len(samples),
        "raw_core_elapsed_ms": times,
        "min_core_elapsed_ms": min(times),
        "median_core_elapsed_ms": round(statistics.median(times), 6),
        "max_core_elapsed_ms": max(times),
        "raw_peak_rss_kb": rss,
        "median_peak_rss_kb": statistics.median(rss),
        "max_peak_rss_kb": max(rss),
    }


def _summarize_cap(samples: list[dict[str, Any]]) -> dict[str, Any]:
    semantic_keys = ("kind", "size", "status", "diagnostic")
    semantic = {key: samples[0][key] for key in semantic_keys}
    for sample in samples[1:]:
        assert all(sample[key] == value for key, value in semantic.items())
    times = [sample["validation_elapsed_ms"] for sample in samples]
    rss = [sample["peak_rss_kb"] for sample in samples]
    return {
        **semantic,
        "repetitions": len(samples),
        "raw_validation_elapsed_ms": times,
        "median_validation_elapsed_ms": round(statistics.median(times), 6),
        "max_validation_elapsed_ms": max(times),
        "raw_peak_rss_kb": rss,
        "median_peak_rss_kb": statistics.median(rss),
        "max_peak_rss_kb": max(rss),
    }


def _run_child(kind: str, size: int) -> dict[str, Any]:
    if kind in {"shared_accept", "shared_reject", "unordered"}:
        return _run_success(kind, size)
    if kind in {"outcome_cap", "occurrence_cap"}:
        return _run_cap(kind, size)
    raise ValueError(f"unknown workload: {kind}")


def _fresh_samples(kind: str, size: int) -> list[dict[str, Any]]:
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = "0"
    samples = []
    for _ in range(REPETITIONS):
        completed = subprocess.run(
            [sys.executable, __file__, "--child", kind, str(size)],
            cwd=HERE,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        samples.append(json.loads(completed.stdout))
    return samples


def run_experiment() -> dict[str, Any]:
    if REPETITIONS != 5:
        raise RuntimeError("the experiment fixes five repetitions")
    success_rows = []
    for kind in ("shared_accept", "shared_reject"):
        for size in SHARED_PREFIX_SIZES:
            success_rows.append(
                _summarize_success(_fresh_samples(kind, size))
            )
    for width in UNORDERED_WIDTHS:
        success_rows.append(
            _summarize_success(_fresh_samples("unordered", width))
        )
    cap_rows = [
        _summarize_cap(
            _fresh_samples("outcome_cap", OUTCOME_CAP_FAILURE)
        ),
        _summarize_cap(
            _fresh_samples("occurrence_cap", OCCURRENCE_CAP_FAILURE)
        ),
    ]
    return {
        "experiment": "exact-history-realization-scaling-v1",
        "role": "supporting",
        "timing_scope": (
            "check_admission core only for success rows; deterministic workload "
            "construction excluded; every sample is a fresh Python process"
        ),
        "repetitions": REPETITIONS,
        "environment": {
            "python": sys.version,
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "cpu_model": _cpu_model(),
            "logical_cpus": os.cpu_count(),
            "repository_commit": _git_value(["rev-parse", "HEAD"]),
            "repository_dirty": bool(
                _git_value(["status", "--porcelain", "--untracked-files=all"])
            ),
            "pythonhashseed": "0 for every measured child process",
            "source_sha256": {
                "benchmark_runner": _file_sha256(Path(__file__).resolve()),
                "exact_validator": _file_sha256(
                    HERE / "exact_history_realization.py"
                ),
            },
        },
        "caps": {
            "outcomes": MAX_OUTCOMES,
            "occurrences_per_outcome": MAX_OCCURRENCES_PER_OUTCOME,
            "linearizations_per_outcome": MAX_LINEARIZATIONS,
            "indexed_safe_executions": MAX_SAFE_EXECUTIONS,
        },
        "success_rows": success_rows,
        "cap_rows": cap_rows,
        "correctness": {
            "all_semantic_counts_deterministic": True,
            "acceptance_rows_retained_all_expected_completions": True,
            "rejection_rows_produced_expected_ranked_chain": True,
            "exercised_outcome_cap_failed_closed": True,
            "exercised_occurrence_cap_failed_closed": True,
        },
        "limitations": [
            "Synthetic finite contracts characterize the constructor, not real-Agent workload prevalence.",
            "The benchmark does not include schema derivation, installation, dispatch, or protected-call mediation.",
            "Wall time and peak RSS are machine-specific.",
            "Explicit outcome and linearization enumeration remains bounded and may grow exponentially.",
            "Only the outcome and per-outcome occurrence caps are exercised.",
        ],
    }


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--child", nargs=2, metavar=("KIND", "SIZE"))
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"raw JSON output (default: {DEFAULT_OUTPUT})",
    )
    args = parser.parse_args(argv)
    if args.child:
        print(
            json.dumps(
                _run_child(args.child[0], int(args.child[1])),
                sort_keys=True,
            )
        )
        return 0
    result = run_experiment()
    _write_json(args.output, result)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
