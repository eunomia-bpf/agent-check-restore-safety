#!/usr/bin/env python3
"""Require the compatible checker to reject independent decisive mutations."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, Callable


CHECK_PATH = Path(__file__).with_name("check-compatible.py")
SPEC = importlib.util.spec_from_file_location("restate_compatible_check", CHECK_PATH)
assert SPEC is not None and SPEC.loader is not None
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, separators=(",", ":")) + "\n")


def mutate_cut_lineage(root: Path) -> None:
    value = load_json(root / "cut-status.json")
    value["rows"][0]["created_at"] = "2020-01-01T00:00:00.000Z"
    write_json(root / "cut-status.json", value)


def mutate_sleep_notification(root: Path) -> None:
    value = load_json(root / "cut-journal-after-window.json")
    lite = json.loads(value["rows"][-1]["entry_lite_json"])
    lite["Notification"]["result"] = "Failure"
    value["rows"][-1]["entry_lite_json"] = json.dumps(lite, separators=(",", ":"))
    write_json(root / "cut-journal-after-window.json", value)


def mutate_sleep_notification_raw(root: Path) -> None:
    value = load_json(root / "cut-journal-after-window.json")
    value["rows"][-1]["raw"] = "08022201"
    write_json(root / "cut-journal-after-window.json", value)


def mutate_run_metadata_cli(root: Path) -> None:
    value = load_json(root / "run-metadata.json")
    value["restate_cli_image"] = (
        "docker.io/restatedev/restate-cli:1.7.3@sha256:" + "2" * 64
    )
    write_json(root / "run-metadata.json", value)


def mutate_post_window_history(root: Path) -> None:
    path = root / "payment-after-cut-window.history"
    path.write_bytes(path.read_bytes() + path.read_bytes())


def mutate_build_provenance(root: Path) -> None:
    path = root / "build.env"
    lines = path.read_text().splitlines()
    for index, line in enumerate(lines):
        if line.startswith("COMPATIBLE_V2_COMPILED_SHA256="):
            lines[index] = "COMPATIBLE_V2_COMPILED_SHA256=" + "0" * 64
            break
    else:
        raise RuntimeError("compatible compiled provenance is absent")
    path.write_text("\n".join(lines) + "\n")


def mutate_final_repin(root: Path) -> None:
    source = load_json(root / "deployment-v1.json")["id"]
    value = load_json(root / "final-status.json")
    value["rows"][0]["pinned_deployment_id"] = source
    write_json(root / "final-status.json", value)


def mutate_final_business_state(root: Path) -> None:
    value = load_json(root / "final-workflow-state.json")
    value["rows"][0]["value_utf8"] = '"SCHEDULED"'
    write_json(root / "final-workflow-state.json", value)


def mutate_duplicate_payment(root: Path) -> None:
    path = root / "payment.history"
    path.write_bytes(path.read_bytes() + path.read_bytes())


def mutate_completion_request(root: Path) -> None:
    path = root / "completion.history"
    record = json.loads(path.read_text())
    record["request_hash"] = "f" * 64
    path.write_text(json.dumps(record, separators=(",", ":")) + "\n")


def mutate_resubmission(root: Path) -> None:
    value = load_json(root / "final-invocations.json")
    duplicate = dict(value["rows"][0])
    duplicate["id"] = "inv_resubmitted"
    value["rows"].append(duplicate)
    write_json(root / "final-invocations.json", value)


def mutate_source_removal(root: Path) -> None:
    (root / "source-container-after-removal.exit-status.txt").write_text("0\n")


def mutate_resume(root: Path) -> None:
    (root / "resume-exit-status.txt").write_text("1\n")


def mutate_target_image(root: Path) -> None:
    value = load_json(root / "containers.raw.json")
    for item in value:
        if item.get("Config", {}).get("Labels", {}).get("com.docker.compose.service") == "order-v2":
            item["Image"] = "sha256:" + "1" * 64
            break
    else:
        raise RuntimeError("target container is absent")
    write_json(root / "containers.raw.json", value)


def mutate_final_output(root: Path) -> None:
    value = load_json(root / "final-journal.json")
    lite = json.loads(value["rows"][-1]["entry_lite_json"])
    lite["Command"]["Output"]["result"] = "Failure"
    value["rows"][-1]["entry_lite_json"] = json.dumps(lite, separators=(",", ":"))
    write_json(root / "final-journal.json", value)


def mutate_proposed_certificate(root: Path) -> None:
    value = load_json(root / "certificate-compatible.json")
    value["rule"]["allow"] = ["charge-v1", "finish"]
    write_json(root / "certificate-compatible.json", value)


def mutate_proposed_control_completion(root: Path) -> None:
    value = load_json(root / "final-control-state.json")
    finish = next(operation for operation in value["operations"].values() if operation.get("kind") == "finish")
    finish["phase"] = "prepared"
    write_json(root / "final-control-state.json", value)


def mutate_native_control_absence(root: Path) -> None:
    write_json(root / "control-at-cut.json", {"invented": True})


COMMON_MUTATIONS: dict[str, Callable[[Path], None]] = {
    "cut lineage changed": mutate_cut_lineage,
    "Sleep notification changed": mutate_sleep_notification,
    "Sleep notification raw bytes changed": mutate_sleep_notification_raw,
    "effective Restate CLI changed": mutate_run_metadata_cli,
    "post-wake durable payment History changed": mutate_post_window_history,
    "compatible build provenance changed": mutate_build_provenance,
    "final target repin removed": mutate_final_repin,
    "DELIVERED state removed": mutate_final_business_state,
    "payment provider fact duplicated": mutate_duplicate_payment,
    "completion request hash changed": mutate_completion_request,
    "second workflow invocation added": mutate_resubmission,
    "source removal failed": mutate_source_removal,
    "official resume failed": mutate_resume,
    "target image changed": mutate_target_image,
    "final workflow Output failed": mutate_final_output,
}


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--evidence", required=True, type=Path, help="compatible attempt or results directory")
    value.add_argument("--method", choices=("proposed", "native"), help="optional expected lane")
    value.add_argument(
        "--runtime-root", type=Path, default=Path(__file__).resolve().parents[2],
        help="runtime source root containing cmd/check-certificate",
    )
    return value


def main() -> int:
    args = parser().parse_args()
    source = CHECK.evidence_root(args.evidence)
    good = CHECK.check_evidence(source, args.runtime_root, args.method)
    method = good["method"]
    mutations = dict(COMMON_MUTATIONS)
    if method == "proposed":
        mutations["compatible Certificate widened"] = mutate_proposed_certificate
        mutations["control completion unsettled"] = mutate_proposed_control_completion
    else:
        mutations["proposed control inserted into native lane"] = mutate_native_control_absence

    rejected: list[str] = []
    with tempfile.TemporaryDirectory(prefix=f"safe-change-compatible-{method}-mutations.") as temporary:
        base = Path(temporary)
        for index, (name, mutate) in enumerate(mutations.items(), 1):
            candidate = base / f"mutation-{index:02d}"
            shutil.copytree(source, candidate)
            mutate(candidate)
            try:
                CHECK.check_evidence(candidate, args.runtime_root, method)
            except (
                CHECK.EvidenceError,
                CHECK.BASE.EvidenceError,
                OSError,
                subprocess.SubprocessError,
            ):
                rejected.append(name)
            else:
                raise SystemExit(f"checker accepted decisive mutation: {name}")

        # This is not a decisive evidence mutation: it proves the runner's
        # self-reported summary cannot affect the independently recomputed
        # verdict or digest.
        ignored = base / "ignored-observed-json"
        shutil.copytree(source, ignored)
        write_json(ignored / "observed.json", {"valid": False, "invented": "ignored"})
        ignored_result = CHECK.check_evidence(ignored, args.runtime_root, method)
        if ignored_result != good:
            raise SystemExit("observed.json influenced the independent verdict")

    print(json.dumps({
        "schema": 1,
        "valid": True,
        "method": method,
        "mutations": len(mutations),
        "rejected": rejected,
        "observed_json_ignored": True,
    }, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
