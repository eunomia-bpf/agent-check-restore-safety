#!/usr/bin/env python3
"""Require the old-drain checker to reject decisive evidence mutations."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
from typing import Any, Callable


CHECK_PATH = Path(__file__).with_name("check-old-drain.py")
SPEC = importlib.util.spec_from_file_location("restate_old_drain_check", CHECK_PATH)
assert SPEC is not None and SPEC.loader is not None
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, separators=(",", ":")) + "\n")


def mutate_runner_hash(root: Path) -> None:
    path = root / "runner.sha256"
    path.write_text("0" * 64 + path.read_text()[64:])


def mutate_cli_image(root: Path) -> None:
    value = load_json(root / "run-metadata.json")
    value["restate_cli_image"] = "docker.io/restatedev/restate-cli:1.7.3@sha256:" + "1" * 64
    write_json(root / "run-metadata.json", value)


def mutate_build_provenance(root: Path) -> None:
    path = root / "build.env"
    lines = path.read_text().splitlines()
    for index, line in enumerate(lines):
        if line.startswith("NATIVE_V1_COMPILED_SHA256="):
            lines[index] = "NATIVE_V1_COMPILED_SHA256=" + "0" * 64
            break
    else:
        raise RuntimeError("native-v1 compiled provenance is absent")
    path.write_text("\n".join(lines) + "\n")


def mutate_source_image(root: Path) -> None:
    value = load_json(root / "containers.raw.json")
    for item in value:
        if item.get("Config", {}).get("Labels", {}).get("com.docker.compose.service") == "order-v1":
            item["Image"] = "sha256:" + "2" * 64
            break
    else:
        raise RuntimeError("source container is absent")
    write_json(root / "containers.raw.json", value)


def mutate_target_container(root: Path) -> None:
    value = load_json(root / "containers.raw.json")
    target = json.loads(json.dumps(next(
        item for item in value
        if item.get("Config", {}).get("Labels", {}).get("com.docker.compose.service") == "order-v1"
    )))
    target["Config"]["Labels"]["com.docker.compose.service"] = "order-v2"
    value.append(target)
    write_json(root / "containers.raw.json", value)


def mutate_target_deployment(root: Path) -> None:
    value = load_json(root / "final-deployments.json")
    target = json.loads(json.dumps(value["deployments"][0]))
    target["id"] = "dp_inventedTarget"
    target["uri"] = "http://order-v2:9080/"
    value["deployments"].append(target)
    write_json(root / "final-deployments.json", value)


def mutate_resubmission(root: Path) -> None:
    value = load_json(root / "final-invocations.json")
    duplicate = dict(value["rows"][0])
    duplicate["id"] = "inv_inventedResubmission"
    value["rows"].append(duplicate)
    write_json(root / "final-invocations.json", value)


def mutate_final_paused(root: Path) -> None:
    value = load_json(root / "final-status.json")
    value["rows"][0]["status"] = "paused"
    write_json(root / "final-status.json", value)


def mutate_lineage(root: Path) -> None:
    value = load_json(root / "cut-status.json")
    value["rows"][0]["created_at"] = "2020-01-01T00:00:00.000Z"
    write_json(root / "cut-status.json", value)


def mutate_payment_completed(root: Path) -> None:
    value = load_json(root / "cut-journal.json")
    value["rows"][2]["completed"] = True
    write_json(root / "cut-journal.json", value)


def mutate_payment_identity(root: Path) -> None:
    value = load_json(root / "cut-journal.json")
    lite = json.loads(value["rows"][2]["entry_lite_json"])
    lite["Command"]["Run"]["name"] = "different-payment"
    value["rows"][2]["entry_lite_json"] = json.dumps(lite, separators=(",", ":"))
    write_json(root / "cut-journal.json", value)


def mutate_business_state(root: Path) -> None:
    value = load_json(root / "final-workflow-state.json")
    value["rows"][0]["value_utf8"] = '"INVENTED"'
    write_json(root / "final-workflow-state.json", value)


def mutate_payment_delivery(root: Path) -> None:
    value = load_json(root / "final-payment-stats.json")
    value["deliveries"] = 2
    value["paths"]["/v1/charge"] = 2
    write_json(root / "final-payment-stats.json", value)


def mutate_payment_history(root: Path) -> None:
    path = root / "payment.history"
    data = path.read_bytes()
    if data:
        path.write_bytes(data + data)
    else:
        path.write_text(json.dumps({"invented": True}, separators=(",", ":")) + "\n")


def mutate_completion(root: Path) -> None:
    value = load_json(root / "final-completion-stats.json")
    value["deliveries"] += 1
    value["paths"] = {"/v1/complete": value["deliveries"]}
    write_json(root / "final-completion-stats.json", value)


def mutate_source_retention(root: Path) -> None:
    value = load_json(root / "final-source-retained.json")
    value[0]["State"]["Running"] = False
    value[0]["State"]["Status"] = "exited"
    write_json(root / "final-source-retained.json", value)


def mutate_pause_cli(root: Path) -> None:
    (root / "pause.stdout").write_text("[OK]: Paused 0 invocations\n")


def mutate_resume_cli(root: Path) -> None:
    (root / "resume.stdout").write_text("[OK]: Resumed 0 invocations\n")


def mutate_recovery_flags(root: Path) -> None:
    value = load_json(root / "payment-recovered-container.json")
    command = value[0]["Config"]["Cmd"]
    command[command.index("-hold-after-commit=false")] = "-hold-after-commit=true"
    write_json(root / "payment-recovered-container.json", value)


def mutate_recovery_volume(root: Path) -> None:
    value = load_json(root / "payment-recovered-container.json")
    mount = next(item for item in value[0]["Mounts"] if item.get("Destination") == "/state")
    mount["Name"] = "invented-recovery-volume"
    write_json(root / "payment-recovered-container.json", value)


def mutate_exit_status(root: Path) -> None:
    (root / "exit-status.txt").write_text("1\n")


MUTATIONS: dict[str, Callable[[Path], None]] = {
    "runner identity changed": mutate_runner_hash,
    "effective Restate CLI changed": mutate_cli_image,
    "native-v1 build provenance changed": mutate_build_provenance,
    "retained source image changed": mutate_source_image,
    "target container inserted": mutate_target_container,
    "target deployment inserted": mutate_target_deployment,
    "second workflow invocation inserted": mutate_resubmission,
    "final invocation changed back to paused": mutate_final_paused,
    "invocation lineage changed": mutate_lineage,
    "cut payment marked completed": mutate_payment_completed,
    "payment command identity changed": mutate_payment_identity,
    "business state advanced": mutate_business_state,
    "second payment delivery inserted": mutate_payment_delivery,
    "payment durable record changed": mutate_payment_history,
    "completion delivery count changed": mutate_completion,
    "old source no longer retained": mutate_source_retention,
    "official pause result changed": mutate_pause_cli,
    "official resume result changed": mutate_resume_cli,
    "fault-release hold restored": mutate_recovery_flags,
    "fault-release durable volume changed": mutate_recovery_volume,
    "runner failure hidden": mutate_exit_status,
}


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--evidence", required=True, type=Path, help="old-drain attempt or results directory")
    value.add_argument("--case", choices=("h0", "h1"), help="optional expected history")
    return value


def main() -> int:
    args = parser().parse_args()
    source = CHECK.root_for(args.evidence)
    good = CHECK.check_evidence(source, args.case)
    case = good["case"]
    rejected: list[str] = []
    with tempfile.TemporaryDirectory(prefix=f"safe-change-old-drain-{case}-mutations.") as temporary:
        base = Path(temporary)
        for index, (name, mutate) in enumerate(MUTATIONS.items(), 1):
            candidate = base / f"mutation-{index:02d}"
            shutil.copytree(source, candidate)
            mutate(candidate)
            try:
                CHECK.check_evidence(candidate, case)
            except (CHECK.EvidenceError, CHECK.COMPAT.EvidenceError, OSError, UnicodeError):
                rejected.append(name)
            else:
                raise SystemExit(f"checker accepted decisive mutation: {name}")

        ignored = base / "ignored-observed-json"
        shutil.copytree(source, ignored)
        write_json(ignored / "observed.json", {"valid": False, "invented": "ignored"})
        ignored_result = CHECK.check_evidence(ignored, case)
        if ignored_result != good:
            raise SystemExit("observed.json influenced the independent verdict")

    print(json.dumps({
        "schema": 1,
        "valid": True,
        "case": case,
        "mutations": len(MUTATIONS),
        "rejected": rejected,
        "observed_json_ignored": True,
    }, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
