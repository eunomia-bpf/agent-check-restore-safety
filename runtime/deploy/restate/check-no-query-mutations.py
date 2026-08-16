#!/usr/bin/env python3
"""Require the no-query checker to reject independent evidence mutations."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
from typing import Any, Callable


CHECK_PATH = Path(__file__).with_name("check-no-query.py")
SPEC = importlib.util.spec_from_file_location("restate_no_query_check", CHECK_PATH)
assert SPEC is not None and SPEC.loader is not None
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, separators=(",", ":")) + "\n")


def mutate_recovery(root: Path) -> None:
    value = load_json(root / "no-query-recovery.json")
    value["code"] = "ok"
    write_json(root / "no-query-recovery.json", value)


def mutate_history(root: Path) -> None:
    path = root / "no-query-runtime.history"
    data = bytearray(path.read_bytes())
    data[-1] ^= 1
    path.write_bytes(data)


def mutate_payment_truth(root: Path) -> None:
    value = load_json(root / "no-query-payment-stats.json")
    value["commits"] = 0
    write_json(root / "no-query-payment-stats.json", value)


def mutate_target_started(root: Path) -> None:
    value = load_json(root / "no-query-summary.json")
    value["target_started"] = True
    write_json(root / "no-query-summary.json", value)


def mutate_certificate(root: Path) -> None:
    value = load_json(root / "no-query-certificate-v2.json")
    value["decision"] = "activate"
    write_json(root / "no-query-certificate-v2.json", value)


def mutate_control_state(root: Path) -> None:
    value = load_json(root / "control-after-no-query.json")
    value["operations"] = {}
    write_json(root / "control-after-no-query.json", value)


def mutate_provider_record(root: Path) -> None:
    (root / "no-query-payment.history").write_bytes(b"")


def mutate_target_container(root: Path) -> None:
    value = load_json(root / "no-query-containers.raw.json")
    value.append({
        "Image": "sha256:" + "2" * 64,
        "Config": {"Image": "sha256:" + "2" * 64, "Labels": {"com.docker.compose.service": "order-v2"}},
    })
    write_json(root / "no-query-containers.raw.json", value)


MUTATIONS: dict[str, Callable[[Path], None]] = {
    "recovery accepted": mutate_recovery,
    "History bit flip": mutate_history,
    "payment commit removed": mutate_payment_truth,
    "target marked started": mutate_target_started,
    "Certificate decision changed": mutate_certificate,
    "post-query state changed": mutate_control_state,
    "provider fact removed": mutate_provider_record,
    "target container added": mutate_target_container,
}


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--evidence", required=True, type=Path)
    value.add_argument("--runtime-root", type=Path, default=Path(__file__).resolve().parents[2])
    return value


def main() -> int:
    args = parser().parse_args()
    good = CHECK.check_evidence(args.evidence, args.runtime_root)
    if good.get("valid") is not True:
        raise SystemExit("unmodified evidence did not pass")
    rejected: list[str] = []
    with tempfile.TemporaryDirectory(prefix="safe-change-no-query-mutations.") as temporary:
        base = Path(temporary)
        for index, (name, mutate) in enumerate(MUTATIONS.items(), 1):
            candidate = base / f"mutation-{index:02d}"
            shutil.copytree(args.evidence, candidate)
            mutate(candidate)
            try:
                CHECK.check_evidence(candidate, args.runtime_root)
            except (CHECK.EvidenceError, CHECK.CHECK.EvidenceError, OSError):
                rejected.append(name)
            else:
                raise SystemExit(f"checker accepted mutation: {name}")
    print(json.dumps({"schema": 1, "valid": True, "mutations": len(MUTATIONS), "rejected": rejected}, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
