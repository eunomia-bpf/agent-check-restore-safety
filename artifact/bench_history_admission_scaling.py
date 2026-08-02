#!/usr/bin/env python3
"""Reproducible bounded scaling sweep for the history-admission artifact.

The benchmark uses the documented compiler and verifier CLI paths in fresh
Python processes.  Request generation and file creation happen outside the
timed interval.  It is a small-contract characterization, not a throughput or
cross-machine performance claim.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
from itertools import combinations
import json
from math import comb
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterable, Sequence

from history_admission.schema import (
    MAX_CONTROLLERS,
    MAX_EXPANDED_CONFIGURATIONS,
    MAX_PRODUCT_STATES,
    MAX_SOURCE_CELLS,
    MAX_TARGET_CELLS,
)


HERE = Path(__file__).resolve().parent
REPO = HERE.parent
DEFAULT_OUTPUT = HERE / "results" / "history_admission_scaling.json"
REPETITIONS = 5
CELL_COUNTS = (4, 6, 8, 10, 12)
OVERLAP_CELLS = 6
CONTROLLER_COUNTS = (1, 2, 3, 4)
CELL_CAP_FAILURE = 13
CONTROLLER_CAP_FAILURE = 5


def _configs_of_size(names: Sequence[str], size: int) -> list[list[str]]:
    return [list(items) for items in combinations(names, size)]


def _cell_names(count: int) -> list[str]:
    return [f"cell:{index:02d}" for index in range(count)]


def _atom(name: str) -> str:
    return f"grant:scale:{name}"


def _old(name: str) -> str:
    return f"old:{name}"


def _refs(names: Iterable[str]) -> list[dict[str, str]]:
    return [
        {"role": "checkpoint", "local_id": name}
        for name in names
    ]


def _request(
    *,
    request_id: str,
    names: list[str],
    family_maxima: list[list[str]],
    controller_count: int,
    local_maxima: list[list[str]],
) -> dict[str, Any]:
    atoms = [_atom(name) for name in names]
    source_cells = [
        {
            "id": _old(name),
            "atom": _atom(name),
            "cell_anchor": f"old-anchor:{name}",
        }
        for name in names
    ]
    target_cells = [
        {
            "local_id": name,
            "atom": _atom(name),
            "commitment_key": f"effect:{name}",
            "effect_binding_digest": f"sha256:scale-effect-{name}",
            "cell_anchor": f"target-anchor:{name}",
            "parent": _old(name),
            "lease": None,
        }
        for name in names
    ]
    controller_anchors = [
        f"controller:{index:02d}" for index in range(controller_count)
    ]
    gate_uses = []
    for index, anchor in enumerate(controller_anchors):
        gate_uses.append(
            {
                "id": f"gate-use:{index:02d}",
                "gate_origin": f"gate-origin:{index:02d}",
                "controller_anchor": anchor,
                "controller_version": 1,
                "members": _refs(names),
                "local_maxima": [_refs(config) for config in local_maxima],
            }
        )
    return {
        "schema": "history-admission.request.v1",
        "request_id": request_id,
        "authority": {
            "id": "grant:scale",
            "atoms": atoms,
            "allowed_maxima": [
                [_atom(name) for name in config]
                for config in family_maxima
            ],
        },
        "source": {
            "version": 1,
            "cells": source_cells,
            "future_maxima": [
                [_old(name) for name in config]
                for config in family_maxima
            ],
            "receipt_frontier": [],
            "leases": [],
        },
        "ledger": [],
        "operation": {
            "kind": "RestoreReplace",
            "target_version": 2,
            "aliases": [],
            "checkpoint": {
                "coverage": "exact",
                "cells": target_cells,
                "may_maxima": family_maxima,
                "required_maxima": family_maxima,
            },
            "gate_uses": gate_uses,
            "controller_future_maxima": [controller_anchors],
        },
    }


def threshold_request(cell_count: int) -> tuple[dict[str, Any], dict[str, int]]:
    names = _cell_names(cell_count)
    rank = cell_count // 2
    maxima = _configs_of_size(names, rank)
    family_size = sum(comb(cell_count, size) for size in range(rank + 1))
    minimal_nonfaces = comb(cell_count, rank + 1)
    return (
        _request(
            request_id=f"scaling:cells:{cell_count}",
            names=names,
            family_maxima=maxima,
            controller_count=1,
            local_maxima=maxima,
        ),
        {
            "semantic_cells": cell_count,
            "controllers": 1,
            "expanded_family_configurations": family_size,
            "minimal_nonfaces": minimal_nonfaces,
            "physical_configurations": family_size,
            "analytically_reconstructed_full_pair_expansion_iterations": (
                family_size
            ),
        },
    )


def overlap_request(
    controller_count: int,
) -> tuple[dict[str, Any], dict[str, int]]:
    names = _cell_names(OVERLAP_CELLS)
    maxima = [names]
    local_family_size = 1 << OVERLAP_CELLS
    # The co-live maxima expands to every controller subset.  For each
    # nonempty subset, the first controller visits L pair-expansion iterations
    # and every later controller visits L^2.  All controllers expose the same
    # full powerset, so union deduplication leaves L partial configurations.
    pair_expansion_iterations = (
        ((1 << controller_count) - 1) * local_family_size
        + (
            controller_count * (1 << (controller_count - 1))
            - ((1 << controller_count) - 1)
        )
        * local_family_size
        * local_family_size
    )
    return (
        _request(
            request_id=f"scaling:controllers:{controller_count}",
            names=names,
            family_maxima=maxima,
            controller_count=controller_count,
            local_maxima=maxima,
        ),
        {
            "semantic_cells": OVERLAP_CELLS,
            "controllers": controller_count,
            "expanded_family_configurations": local_family_size,
            "minimal_nonfaces": 0,
            "physical_configurations": local_family_size,
            "analytically_reconstructed_full_pair_expansion_iterations": (
                pair_expansion_iterations
            ),
        },
    )


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _run(command: list[str], *, expected_code: int) -> dict[str, Any]:
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = "0"
    started = time.perf_counter_ns()
    completed = subprocess.run(
        command,
        cwd=HERE,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
    if completed.returncode != expected_code:
        raise RuntimeError(
            f"unexpected exit {completed.returncode} (wanted {expected_code}): "
            f"{' '.join(command)}\nstdout={completed.stdout}\nstderr={completed.stderr}"
        )
    return {
        "wall_ms": round(elapsed_ms, 6),
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _summary(samples: list[float]) -> dict[str, Any]:
    ordered = sorted(samples)
    quartiles = statistics.quantiles(ordered, n=4, method="inclusive")
    return {
        "repetitions": len(ordered),
        "raw_wall_ms": samples,
        "min_wall_ms": round(ordered[0], 6),
        "p25_wall_ms": round(quartiles[0], 6),
        "median_wall_ms": round(statistics.median(ordered), 6),
        "p75_wall_ms": round(quartiles[2], 6),
        "max_wall_ms": round(ordered[-1], 6),
    }


def _run_passing_case(
    root: Path,
    label: str,
    request: dict[str, Any],
    dimensions: dict[str, int],
) -> dict[str, Any]:
    case_root = root / label
    case_root.mkdir()
    request_path = case_root / "request.json"
    _write_json(request_path, request)
    compile_times: list[float] = []
    verify_times: list[float] = []
    result_hashes: list[str] = []
    seal_hashes: list[str] = []
    observed_nonfaces: list[int] = []
    result_sizes: list[int] = []
    for repetition in range(REPETITIONS):
        result_path = case_root / f"result-{repetition}.json"
        seal_path = case_root / f"seal-{repetition}.json"
        compiled = _run(
            [
                sys.executable,
                "-m",
                "history_admission.compiler",
                str(request_path),
                "--output",
                str(result_path),
            ],
            expected_code=0,
        )
        compile_times.append(compiled["wall_ms"])
        result_bytes = result_path.read_bytes()
        result_hashes.append(sha256(result_bytes).hexdigest())
        result_sizes.append(len(result_bytes))
        result = json.loads(result_bytes)
        observed_nonfaces.append(
            len(result["coordination"]["minimal_nonfaces"])
        )
        if result["coordination"]["status"] != "exact":
            raise RuntimeError(f"{label}: expected exact coordination")
        verified = _run(
            [
                sys.executable,
                "-m",
                "history_admission.verifier",
                str(request_path),
                str(result_path),
                "--output",
                str(seal_path),
            ],
            expected_code=0,
        )
        verify_times.append(verified["wall_ms"])
        seal_bytes = seal_path.read_bytes()
        seal_hashes.append(sha256(seal_bytes).hexdigest())
        seal = json.loads(seal_bytes)
        if not seal["valid"]:
            raise RuntimeError(f"{label}: verifier did not accept compiler result")
    if len(set(result_hashes)) != 1 or len(set(seal_hashes)) != 1:
        raise RuntimeError(f"{label}: output changed across identical repetitions")
    if set(observed_nonfaces) != {dimensions["minimal_nonfaces"]}:
        raise RuntimeError(
            f"{label}: minimal-nonface oracle mismatch: {observed_nonfaces}"
        )
    return {
        "label": label,
        "status": "completed",
        **dimensions,
        "request_bytes": request_path.stat().st_size,
        "result_bytes": result_sizes[0],
        "result_sha256": result_hashes[0],
        "seal_sha256": seal_hashes[0],
        "observed_minimal_nonfaces": observed_nonfaces[0],
        "compiler": _summary(compile_times),
        "verifier": _summary(verify_times),
    }


def _run_failure_case(
    root: Path,
    label: str,
    request: dict[str, Any],
    dimensions: dict[str, int],
    diagnostic: str,
) -> dict[str, Any]:
    case_root = root / label
    case_root.mkdir()
    request_path = case_root / "request.json"
    result_path = case_root / "result.json"
    seal_path = case_root / "seal.json"
    _write_json(request_path, request)
    _write_json(result_path, {})
    compiled = _run(
        [
            sys.executable,
            "-m",
            "history_admission.compiler",
            str(request_path),
            "--output",
            str(case_root / "compiler-output.json"),
        ],
        expected_code=2,
    )
    verified = _run(
        [
            sys.executable,
            "-m",
            "history_admission.verifier",
            str(request_path),
            str(result_path),
            "--output",
            str(seal_path),
        ],
        expected_code=2,
    )
    if diagnostic not in compiled["stderr"] or diagnostic not in verified["stderr"]:
        raise RuntimeError(
            f"{label}: expected diagnostic {diagnostic!r}\n"
            f"compiler={compiled['stderr']}\nverifier={verified['stderr']}"
        )
    return {
        "label": label,
        "status": "rejected_as_planned",
        **dimensions,
        "request_bytes": request_path.stat().st_size,
        "expected_diagnostic": diagnostic,
        "compiler": compiled,
        "verifier": verified,
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


def run_experiment() -> dict[str, Any]:
    if REPETITIONS != 5:
        raise RuntimeError("the approved experiment fixes five repetitions")
    with tempfile.TemporaryDirectory(prefix="history-admission-scaling-") as temp:
        root = Path(temp)
        cell_rows = []
        for count in CELL_COUNTS:
            request, dimensions = threshold_request(count)
            cell_rows.append(
                _run_passing_case(root, f"cells-{count}", request, dimensions)
            )
        controller_rows = []
        for count in CONTROLLER_COUNTS:
            request, dimensions = overlap_request(count)
            controller_rows.append(
                _run_passing_case(
                    root, f"controllers-{count}", request, dimensions
                )
            )
        cell_request, cell_dimensions = threshold_request(CELL_CAP_FAILURE)
        cell_failure = _run_failure_case(
            root,
            f"cells-{CELL_CAP_FAILURE}-cap",
            cell_request,
            cell_dimensions,
            f"source must declare between 1 and {MAX_SOURCE_CELLS} cells",
        )
        product_request, product_dimensions = overlap_request(
            CONTROLLER_CAP_FAILURE
        )
        if (
            product_dimensions[
                "analytically_reconstructed_full_pair_expansion_iterations"
            ]
            <= MAX_PRODUCT_STATES
        ):
            raise RuntimeError("product-cap control does not exceed the cap")
        product_failure = _run_failure_case(
            root,
            f"controllers-{CONTROLLER_CAP_FAILURE}-pair-expansion-cap",
            product_request,
            product_dimensions,
            f"controller product exceeds {MAX_PRODUCT_STATES} states",
        )
        product_failure["actual_pair_expansion_iterations_before_rejection"] = (
            MAX_PRODUCT_STATES + 1
        )
        product_failure["full_pair_expansion_iteration_count_executed"] = False
    return {
        "experiment": "history-admission-scaling-v1",
        "role": "supporting",
        "timing_scope": (
            "fresh-process end-to-end CLI wall time; deterministic request "
            "generation and file creation excluded"
        ),
        "repetitions": REPETITIONS,
        "environment": {
            "python": sys.version,
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "logical_cpus": os.cpu_count(),
            "repository_commit": _git_value(["rev-parse", "HEAD"]),
            "repository_dirty": bool(_git_value(["status", "--porcelain"])),
            "pythonhashseed": "0 for timed child processes",
            "source_sha256": {
                "benchmark_runner": _file_sha256(Path(__file__).resolve()),
                "compiler": _file_sha256(
                    HERE / "history_admission" / "compiler.py"
                ),
                "verifier": _file_sha256(
                    HERE / "history_admission" / "verifier.py"
                ),
                "schema": _file_sha256(
                    HERE / "history_admission" / "schema.py"
                ),
            },
        },
        "caps": {
            "source_cells": MAX_SOURCE_CELLS,
            "target_cells": MAX_TARGET_CELLS,
            "controllers": MAX_CONTROLLERS,
            "expanded_configurations": MAX_EXPANDED_CONFIGURATIONS,
            "controller_product_pair_expansion_iteration_limit": (
                MAX_PRODUCT_STATES
            ),
        },
        "cell_sweep": cell_rows,
        "controller_sweep": controller_rows,
        "expected_failures": [cell_failure, product_failure],
        "correctness": {
            "all_passing_outputs_deterministic": True,
            "all_passing_results_independently_verified": True,
            "minimal_nonface_oracles_matched": True,
            "exercised_source_cell_cap_failed_closed": True,
            "exercised_controller_product_iteration_cap_failed_closed": True,
        },
        "limitations": [
            "Synthetic manifests characterize the finite algorithm, not real-agent prevalence.",
            "Wall time includes Python startup and JSON I/O and is machine-specific.",
            "Pair-expansion iteration counts are analytically derived from the deterministic workload and source loop, not exported production telemetry.",
            "Only the source-cell and controller-product iteration limits are exercised; target-cell, controller-count, and expanded-configuration limits are not tested.",
            "Per-case requests, results, and seals use a temporary directory and are not archived; a clean pinned rerun is required to audit historical timings independently.",
            "The sweep does not justify extrapolation past the declared caps.",
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"raw JSON output (default: {DEFAULT_OUTPUT})",
    )
    args = parser.parse_args(argv)
    result = run_experiment()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    _write_json(args.output, result)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
