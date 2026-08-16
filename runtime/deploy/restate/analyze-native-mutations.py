#!/usr/bin/env python3
"""Require the native-Restate analyzer to reject evidence inconsistencies."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
from typing import Any, Callable


ANALYZER_PATH = Path(__file__).with_name("analyze-native.py")
SPEC = importlib.util.spec_from_file_location("restate_native_analyzer", ANALYZER_PATH)
assert SPEC is not None and SPEC.loader is not None
ANALYZER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ANALYZER)


def load(path: Path) -> Any:
    return json.loads(path.read_text())


def write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, separators=(",", ":")) + "\n")


def order_changed(_: Path, h1: Path) -> None:
    value = load(h1 / "order.json")
    value["totalCost"] = 43
    write(h1 / "order.json", value)


def cut_journal_changed(_: Path, h1: Path) -> None:
    value = load(h1 / "cut-journal.json")
    value["rows"][-1]["name"] = "other"
    write(h1 / "cut-journal.json", value)


def durable_fact_removed(_: Path, h1: Path) -> None:
    (h1 / "payment-at-cut.history").write_bytes(b"")


def commands_changed(_: Path, h1: Path) -> None:
    with (h1 / "post-cut-command.log").open("ab") as output:
        output.write(b"conditional-fallback\n")


def proposed_control_added(h0: Path, _: Path) -> None:
    value = load(h0 / "containers.raw.json")
    value.append({
        "Image": "sha256:" + "1" * 64,
        "Config": {"Image": "sha256:" + "1" * 64, "Labels": {"com.docker.compose.service": "control"}},
        "State": {"Running": True}, "NetworkSettings": {"Networks": {}},
    })
    write(h0 / "containers.raw.json", value)


def source_image_changed(h0: Path, _: Path) -> None:
    value = load(h0 / "source-container-retained.json")
    value[0]["Image"] = "sha256:" + "a" * 64
    write(h0 / "source-container-retained.json", value)


def invocation_replaced(h0: Path, _: Path) -> None:
    value = load(h0 / "final-status.json")
    value["rows"][0]["id"] = "inv_replacement"
    write(h0 / "final-status.json", value)


def provider_counts_changed(h0: Path, _: Path) -> None:
    value = load(h0 / "final-payment-stats.json")
    value["commits"] = 1
    write(h0 / "final-payment-stats.json", value)


MUTATIONS: dict[str, Callable[[Path, Path], None]] = {
    "workload changed": order_changed,
    "cut journal changed": cut_journal_changed,
    "durable fact removed": durable_fact_removed,
    "conditional command added": commands_changed,
    "proposed control added": proposed_control_added,
    "source image changed": source_image_changed,
    "invocation replaced": invocation_replaced,
    "provider counts changed": provider_counts_changed,
}


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--h0", required=True, type=Path)
    value.add_argument("--h1", required=True, type=Path)
    return value


def main() -> int:
    args = parser().parse_args()
    good = ANALYZER.analyze(args.h0, args.h1)
    if good.get("valid") is not True:
        raise SystemExit("unmodified evidence did not pass")
    rejected: list[str] = []
    with tempfile.TemporaryDirectory(prefix="safe-change-native-mutations.") as temporary:
        base = Path(temporary)
        for index, (name, mutate) in enumerate(MUTATIONS.items(), 1):
            candidate = base / f"mutation-{index:02d}"
            h0, h1 = candidate / "h0", candidate / "h1"
            shutil.copytree(args.h0, h0)
            shutil.copytree(args.h1, h1)
            mutate(h0, h1)
            try:
                ANALYZER.analyze(h0, h1)
            except (ANALYZER.EvidenceError, ANALYZER.BASE.EvidenceError, OSError):
                rejected.append(name)
            else:
                raise SystemExit(f"analyzer accepted mutation: {name}")

        # Runtime-authored observed.json is deliberately not an oracle.
        ignored_root = base / "self-report"
        h0, h1 = ignored_root / "h0", ignored_root / "h1"
        shutil.copytree(args.h0, h0)
        shutil.copytree(args.h1, h1)
        observed = load(h0 / "observed.json")
        observed["execution"] = {"status": "completed", "order_status": "DELIVERED"}
        write(h0 / "observed.json", observed)
        if ANALYZER.analyze(h0, h1).get("valid") is not True:
            raise SystemExit("analyzer incorrectly trusted runtime self-report")

    print(json.dumps({
        "schema": 1, "valid": True, "mutations": len(MUTATIONS),
        "rejected": rejected, "runtime_self_report_ignored": True,
    }, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
