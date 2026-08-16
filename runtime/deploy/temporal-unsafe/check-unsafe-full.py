#!/usr/bin/env python3
"""Aggregate and independently recheck a full Temporal unsafe-edit run."""

from __future__ import annotations

import argparse
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import re
import sys


SCRIPT_DIR = Path(__file__).resolve().parent


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CHECK = load("temporal_unsafe_check", SCRIPT_DIR / "check-unsafe.py")
PAIR = load("temporal_unsafe_pair", SCRIPT_DIR / "check-unsafe-pair.py")


COMMON_MUTATIONS = [
    "observed-is-not-oracle", "target-capacity", "target-finish-cost",
    "source-requirement", "frozen-source-image", "same-target-image",
    "target-patch", "control-profile", "control-source", "control-dockerfile",
    "source-adapter-config", "target-image-inspect",
    "metadata-operation", "invocation-token", "payment-token-contract",
    "workflow-restaurant", "cut-activity-type", "unstable-cut", "clean-version-marker",
    "clean-change-version-upsert", "sdk-language-flag", "completion-closure",
    "prepare-receipt", "delivery-request", "driver-assignment-signal",
    "preparation-timer", "final-stage-list",
    "provider-operation", "provider-request", "clean-payment-path",
    "provider-count", "final-worker-build", "resolved-compose-egress",
    "actual-network-egress", "foreign-network-endpoint", "extra-container",
    "poller-build", "deployment-current", "missing-end-sentinel",
    "base-worker-event", "create-before-begin", "create-after-end",
    "sentinel-id-collision", "sentinel-destroy-id",
    "missing-sentinel-destroy", "duplicate-sentinel-destroy",
]
METHOD_MUTATIONS = {
    "proposed": [
        "clean-control-not-target", "clean-control-operation",
        "unsafe-certificate", "unsafe-witness", "refusal-mutates-state",
        "refusal-mutates-history", "target-started",
        "target-absence-record", "source-finish-kind",
    ],
    "native": [
        "source-not-removed", "native-source-destroy-after-target-create",
        "target-container-image",
        "native-added-control", "native-new-charge",
        "native-target-event-missing",
    ],
}

TOP_HASH_FILES = {
    "wrapper.sha256": "run-unsafe-full.sh",
    "case-runner.sha256": "run-unsafe-case.sh",
    "case-checker.sha256": "check-unsafe.py",
    "pair-checker.sha256": "check-unsafe-pair.py",
    "mutation-checker.sha256": "check-unsafe-mutations.py",
    "full-checker.sha256": "check-unsafe-full.py",
}


def json_file(root: Path, name: str) -> object:
    return CHECK.loads(CHECK.read(root, name), name)


def require_regular(path: Path, label: str) -> None:
    info = path.lstat()
    CHECK.require(path.is_file() and not path.is_symlink(), f"{label} is not a regular file")
    CHECK.require(info.st_size <= CHECK.MAX_FILE_BYTES, f"{label} exceeds its size limit")


def require_directory(path: Path, label: str) -> None:
    path.lstat()
    CHECK.require(path.is_dir() and not path.is_symlink(), f"{label} is not a safe directory")


def full_regular_files(root: Path) -> set[str]:
    names: set[str] = set()
    total = 0
    for path in root.rglob("*"):
        info = path.lstat()
        relative = path.relative_to(root).as_posix()
        CHECK.safe_relative_name(relative)
        CHECK.require(not path.is_symlink(), f"full evidence contains a symlink: {relative}")
        if path.is_dir():
            continue
        CHECK.require(path.is_file(), f"full evidence contains a special file: {relative}")
        CHECK.require(info.st_size <= (4 << 30), f"full artifact exceeds 4 GiB: {relative}")
        names.add(relative)
        total += info.st_size
    CHECK.require(total <= (64 << 30), "full evidence exceeds 64 GiB")
    return names


def check_build_evidence(root: Path) -> dict[str, str]:
    build_root = root / "build-evidence"
    require_directory(build_root, "full build-evidence")
    names = CHECK.regular_files(build_root)
    manifest = CHECK.read(build_root, "SHA256SUMS")
    CHECK.require(
        sha256(manifest).hexdigest() == CHECK.ACCEPTED_BUILD_EVIDENCE_MANIFEST_SHA256,
        "full build-evidence manifest differs from the accepted build",
    )
    declared = CHECK.checksum_entries(manifest, "full build-evidence/SHA256SUMS")
    CHECK.require(set(declared) == names - {"SHA256SUMS"}, "full build-evidence manifest does not cover its exact tree")
    for name, digest in declared.items():
        CHECK.require(sha256(CHECK.read(build_root, name)).hexdigest() == digest, f"full build-evidence checksum mismatch: {name}")
    build_bytes = CHECK.read(root, "build.env")
    CHECK.require(build_bytes == CHECK.read(build_root, "build.env"), "full build.env differs from build evidence")
    CHECK.require(sha256(build_bytes).hexdigest() == CHECK.ACCEPTED_BUILD_ENV_SHA256, "full build.env differs from the accepted target")
    build = CHECK.parse_env(build_bytes, "full build.env")
    CHECK.require(set(build) == CHECK.FROZEN_BUILD_KEYS, "full build.env key set differs from the accepted target")
    for key, value in CHECK.FROZEN_BUILD.items():
        CHECK.require(build.get(key) == value, f"full frozen build key differs: {key}")
    return build


def check_script_hash(root: Path, artifact: str, script: str) -> None:
    script_path = SCRIPT_DIR / script
    expected = f"{sha256(script_path.read_bytes()).hexdigest()}  {script}\n".encode()
    CHECK.require(CHECK.read(root, artifact) == expected, f"{artifact} does not bind the executed source")


def check_full_metadata(root: Path, repetitions: int, build: dict[str, str]) -> None:
    value = CHECK.obj(json_file(root, "full-metadata.json"), "full metadata")
    CHECK.exact_fields(value, {
        "schema", "recorded_at", "cell", "system", "output_root",
        "repetitions", "methods", "attempts", "input_build_env",
        "shared_build_env", "shared_build_sha256", "skip_build",
        "one_target_image", "identity_contract", "compose_profiles", "checks",
    }, "full metadata")
    CHECK.require(value.get("schema") == 1 and value.get("cell") == CHECK.CELL, "full metadata schema/cell differs")
    CHECK.require(value.get("system") == "temporal-food-ordering", "full metadata system differs")
    CHECK.parse_timestamp(value.get("recorded_at"), "full metadata recorded_at")
    CHECK.require(
        value.get("repetitions") == repetitions
        and value.get("methods") == ["proposed", "native"]
        and value.get("attempts") == 2 * repetitions,
        "full metadata matrix differs",
    )
    CHECK.require(
        value.get("shared_build_sha256") == CHECK.ACCEPTED_BUILD_ENV_SHA256
        and value.get("skip_build") is True
        and value.get("one_target_image") == build["TEMPORAL_UNSAFE_WORKER_ID"],
        "full metadata build binding differs",
    )
    CHECK.require(
        value.get("identity_contract") == "payment_token_equals_order_id"
        and value.get("compose_profiles") == []
        and value.get("checks") == ["independent-case", "mutations", "matched-pair", "independent-full"],
        "full metadata execution contract differs",
    )
    output_root = value.get("output_root")
    input_build = value.get("input_build_env")
    shared_build = value.get("shared_build_env")
    CHECK.require(
        all(isinstance(item, str) and Path(item).is_absolute() for item in (output_root, input_build, shared_build))
        and Path(output_root) == root
        and Path(shared_build) == root / "build.env",
        "full metadata recorded paths differ",
    )


def expected_mutation_names(method: str) -> list[str]:
    return COMMON_MUTATIONS + METHOD_MUTATIONS[method]


def check_mutations(root: Path, name: str, method: str, evidence_digest: str) -> dict[str, object]:
    value = CHECK.obj(json_file(root, name), name)
    CHECK.exact_fields(value, {
        "schema", "valid", "method", "baseline_evidence_digest",
        "mutation_count", "rejected_count", "positive_control_count", "mutations",
    }, name)
    expected_names = expected_mutation_names(method)
    rows = CHECK.arr(value.get("mutations"), name + " mutations")
    CHECK.require(
        value.get("schema") == 1 and value.get("valid") is True
        and value.get("method") == method
        and value.get("baseline_evidence_digest") == evidence_digest
        and value.get("mutation_count") == len(expected_names)
        and value.get("rejected_count") == len(expected_names) - 1
        and value.get("positive_control_count") == 1
        and len(rows) == len(expected_names),
        f"{name} aggregate differs",
    )
    for index, (raw, expected_name) in enumerate(zip(rows, expected_names, strict=True)):
        row = CHECK.obj(raw, f"{name} row {index}")
        CHECK.exact_fields(row, {"name", "accepted", "expected_accept"}, f"{name} row {index}")
        accept = index == 0
        CHECK.require(
            row == {"name": expected_name, "accepted": accept, "expected_accept": accept},
            f"{name} row {index} differs",
        )
    return value


def check_outer_layout(root: Path, repetitions: int) -> bool:
    core = {
        "build.env", "build-evidence", "full-metadata.json", *TOP_HASH_FILES,
        *(f"rep-{number:02d}" for number in range(1, repetitions + 1)),
    }
    entries = {path.name for path in root.iterdir()}
    finalized = "SHA256SUMS" in entries
    optional = {"full-check.json", "summary.json", "exit-status.txt", "SHA256SUMS"}
    if finalized:
        CHECK.require(entries == core | optional, "finalized full evidence entry set differs")
    else:
        CHECK.require(entries in (core, core | {"full-check.json"}), "in-progress full evidence entry set differs")
        if "full-check.json" in entries:
            CHECK.require((root / "full-check.json").read_bytes() == b"", "in-progress full-check output is not empty")
    for name in core - {"build-evidence", *(f"rep-{number:02d}" for number in range(1, repetitions + 1))}:
        require_regular(root / name, name)
    return finalized


def check_finalized(
    root: Path, verdict: dict[str, object], expected_summary: dict[str, object],
) -> None:
    CHECK.require(CHECK.read(root, "exit-status.txt") == b"0\n", "full runner exit status differs")
    CHECK.require(json_file(root, "full-check.json") == verdict, "recorded full-check verdict differs from recomputation")
    CHECK.require(json_file(root, "summary.json") == expected_summary, "full summary differs from recomputation")
    names = full_regular_files(root)
    declared = CHECK.checksum_entries(CHECK.read(root, "SHA256SUMS"), "full SHA256SUMS")
    CHECK.require(set(declared) == names - {"SHA256SUMS"}, "full SHA256SUMS does not cover its exact tree")
    for name, digest in declared.items():
        CHECK.require(sha256(CHECK.read(root, name)).hexdigest() == digest, f"full checksum mismatch: {name}")


def check_full(path: Path, runtime_root: Path, repetitions: int) -> dict[str, object]:
    root = path.resolve(strict=True)
    CHECK.require(root.is_dir(), "full evidence root is not a directory")
    CHECK.require(repetitions > 0, "repetition count must be positive")
    finalized = check_outer_layout(root, repetitions)
    build = check_build_evidence(root)
    for artifact, script in TOP_HASH_FILES.items():
        check_script_hash(root, artifact, script)
    check_full_metadata(root, repetitions, build)

    case_digests: set[str] = set()
    pair_digests: set[str] = set()
    run_ids: set[str] = set()
    target_images: set[str] = set()
    project_ids: set[str] = set()
    payment_ids: set[str] = set()
    completion_ids: set[str] = set()
    mutation_count = 0
    rejected_count = 0
    positive_control_count = 0
    pairs: list[dict[str, object]] = []
    repetition_summaries: list[dict[str, object]] = []
    for repetition in range(1, repetitions + 1):
        rep = root / f"rep-{repetition:02d}"
        require_directory(rep, f"rep-{repetition:02d}")
        expected_rep_entries = {
            "proposed", "native", "proposed-runner.stdout", "proposed-runner.stderr",
            "proposed-runner.exit-status.txt", "proposed-check.json",
            "proposed-mutations.json", "native-runner.stdout", "native-runner.stderr",
            "native-runner.exit-status.txt", "native-check.json",
            "native-mutations.json", "pair-check.json", "summary.json",
        }
        CHECK.require({item.name for item in rep.iterdir()} == expected_rep_entries, f"rep-{repetition:02d} entry set differs")
        for method in ("proposed", "native"):
            require_directory(rep / method, f"rep-{repetition:02d} {method} case")
            for suffix in ("runner.stdout", "runner.stderr", "runner.exit-status.txt", "check.json", "mutations.json"):
                require_regular(rep / f"{method}-{suffix}", f"rep-{repetition:02d} {method}-{suffix}")
            CHECK.require(CHECK.read(rep, f"{method}-runner.exit-status.txt") == b"0\n", f"rep-{repetition:02d} {method} runner failed")
        for name in ("pair-check.json", "summary.json"):
            require_regular(rep / name, f"rep-{repetition:02d} {name}")

        proposed_path, native_path = rep / "proposed", rep / "native"
        proposed = CHECK.check(proposed_path, runtime_root)
        native = CHECK.check(native_path, runtime_root)
        pair = PAIR.check_pair(proposed_path, native_path, runtime_root)
        CHECK.require(json_file(rep, "proposed-check.json") == proposed, f"rep-{repetition:02d} recorded proposed verdict differs")
        CHECK.require(json_file(rep, "native-check.json") == native, f"rep-{repetition:02d} recorded native verdict differs")
        CHECK.require(json_file(rep, "pair-check.json") == pair, f"rep-{repetition:02d} recorded pair verdict differs")
        CHECK.require(
            CHECK.read(root, "build.env") == CHECK.read(CHECK.evidence_root(proposed_path), "build.env")
            == CHECK.read(CHECK.evidence_root(native_path), "build.env"),
            f"rep-{repetition:02d} did not use the shared full build",
        )
        proposed_mutations = check_mutations(
            rep, "proposed-mutations.json", "proposed", str(proposed["evidence_digest"]),
        )
        native_mutations = check_mutations(
            rep, "native-mutations.json", "native", str(native["evidence_digest"]),
        )
        mutation_count += int(proposed_mutations["mutation_count"]) + int(native_mutations["mutation_count"])
        rejected_count += int(proposed_mutations["rejected_count"]) + int(native_mutations["rejected_count"])
        positive_control_count += int(proposed_mutations["positive_control_count"]) + int(native_mutations["positive_control_count"])
        case_digests.update((str(proposed["evidence_digest"]), str(native["evidence_digest"])))
        pair_digests.add(str(pair["pair_digest"]))
        for lane_path in (proposed_path, native_path):
            lane_root = CHECK.evidence_root(lane_path)
            run_ids.add(CHECK.read(lane_root, "clean-run-id.txt").decode().strip())
            run_ids.add(CHECK.read(lane_root, "main-run-id.txt").decode().strip())
            target_images.add(CHECK.parse_env(CHECK.read(lane_root, "build.env"), "build.env")["TEMPORAL_UNSAFE_WORKER_ID"])
            metadata = CHECK.jobject(lane_root, "run-metadata.json")
            project_ids.update((str(metadata["clean_project"]), str(metadata["main_project"])))
        payment_ids.add(str(pair["main_payment_operation_id"]))
        completion_ids.add(str(pair["main_completion_operation_id"]))
        aggregate_pair = {
            "repetition": repetition, "proposed_digest": proposed["evidence_digest"],
            "native_digest": native["evidence_digest"], "pair_digest": pair["pair_digest"],
        }
        pairs.append(aggregate_pair)
        summary = {
            "schema": 1, "valid": True, "repetition": f"rep-{repetition:02d}",
            "attempts": 2,
            "proposed_evidence_digest": proposed["evidence_digest"],
            "native_evidence_digest": native["evidence_digest"],
            "pair_digest": pair["pair_digest"],
            "mutation_count": int(proposed_mutations["mutation_count"]) + int(native_mutations["mutation_count"]),
            "rejected_count": int(proposed_mutations["rejected_count"]) + int(native_mutations["rejected_count"]),
            "positive_control_count": int(proposed_mutations["positive_control_count"]) + int(native_mutations["positive_control_count"]),
            "main_payment_operation_id": pair["main_payment_operation_id"],
            "main_completion_operation_id": pair["main_completion_operation_id"],
        }
        CHECK.require(json_file(rep, "summary.json") == summary, f"rep-{repetition:02d} summary differs")
        repetition_summaries.append(summary)
    CHECK.require(len(case_digests) == repetitions * 2, "case evidence was reused across repetitions")
    CHECK.require(len(pair_digests) == repetitions, "pair evidence was reused across repetitions")
    CHECK.require(len(run_ids) == repetitions * 4, "Temporal run IDs were reused")
    CHECK.require(len(project_ids) == repetitions * 4, "Compose project identities were reused")
    CHECK.require(len(payment_ids) == repetitions, "payment Operation identities were reused")
    CHECK.require(len(completion_ids) == repetitions, "completion Operation identities were reused")
    CHECK.require(len(target_images) == 1, "full run did not use one exact target image")
    CHECK.require(next(iter(target_images)) == build["TEMPORAL_UNSAFE_WORKER_ID"], "full target image differs from the shared build")
    verdict: dict[str, object] = {
        "schema": 1, "valid": True, "cell": CHECK.CELL, "repetitions": repetitions,
        "case_count": repetitions * 2, "pair_count": repetitions,
        "unique_case_evidence_digests": len(case_digests),
        "unique_pair_digests": len(pair_digests), "unique_run_ids": len(run_ids),
        "one_target_image": next(iter(target_images)), "pairs": pairs,
    }
    full_summary: dict[str, object] = {
        "schema": 1, "valid": True, "cell": CHECK.CELL,
        "system": "temporal-food-ordering", "repetitions": repetitions,
        "attempts": 2 * repetitions,
        "clean_target_completed_both": True,
        "proposed_refused_before_target": True,
        "native_completed_without_requirement_enforcement": True,
        "mutation_count": mutation_count, "rejected_count": rejected_count,
        "positive_control_count": positive_control_count,
        "unique_case_evidence_digests": len(case_digests),
        "unique_pair_digests": len(pair_digests),
        "unique_payment_operation_ids": len(payment_ids),
        "unique_completion_operation_ids": len(completion_ids),
        "one_target_image": next(iter(target_images)), "pairs": repetition_summaries,
    }
    CHECK.require(
        rejected_count == mutation_count - positive_control_count
        and positive_control_count == 2 * repetitions,
        "full mutation totals differ",
    )
    if finalized:
        check_finalized(root, verdict, full_summary)
    return verdict


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--runtime-root", type=Path, default=CHECK.RUNTIME_ROOT)
    parser.add_argument("--repetitions", type=int, default=5)
    args = parser.parse_args()
    try:
        verdict = check_full(args.evidence, args.runtime_root.resolve(strict=True), args.repetitions)
    except (CHECK.EvidenceError, OSError, CHECK.subprocess.SubprocessError) as error:
        print(f"check-unsafe-full: {error}", file=sys.stderr)
        return 1
    print(json.dumps(verdict, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
