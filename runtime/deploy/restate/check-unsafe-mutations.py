#!/usr/bin/env python3
"""Mutation-test the independent Restate unsafe-edit evidence checker."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Callable


Mutation = Callable[[Path], None]


def read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")


def mutate_json(name: str, change: Callable[[Any], None]) -> Mutation:
    def apply(root: Path) -> None:
        path = root / name
        value = read_json(path)
        change(value)
        write_json(path, value)
    return apply


def semantic_feasible(target: dict[str, Any], *, old_payment: bool) -> bool:
    capacity = target["capacities"]["approval"]
    used = target["kinds"]["charge-v1"]["costs"].get("approval", 0) if old_payment else 0
    results = {"paid": 1} if old_payment else {}
    needed = {key for key, amount in target["results"].items() if results.get(key, 0) < amount}
    executable = {
        kind: spec for kind, spec in target["kinds"].items()
        if spec.get("target") and spec.get("method") and spec.get("response_classifier")
    }
    # This frozen target has two independent unit Results, so enumerate all
    # subsets instead of importing the production compiler.
    choices = list(executable.items())
    for mask in range(1 << len(choices)):
        produced = set()
        cost = used
        for index, (_, spec) in enumerate(choices):
            if mask & (1 << index):
                produced.update(key for key, amount in spec["produces"].items() if amount > 0)
                cost += spec["costs"].get("approval", 0)
        if needed <= produced and cost <= capacity:
            return True
    return not needed and used <= capacity


def delete_first_line(name: str) -> Mutation:
    def apply(root: Path) -> None:
        path = root / name
        lines = path.read_bytes().splitlines(keepends=True)
        path.write_bytes(b"".join(lines[1:]))
    return apply


def replace_bytes(name: str, old: bytes, new: bytes) -> Mutation:
    def apply(root: Path) -> None:
        path = root / name
        data = path.read_bytes()
        if old not in data:
            raise RuntimeError(f"{old!r} absent from {name}")
        path.write_bytes(data.replace(old, new, 1))
    return apply


def checker_command(checker: Path, evidence: Path, runtime_root: Path) -> list[str]:
    return [sys.executable, str(checker), "--evidence", str(evidence), "--runtime-root", str(runtime_root)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--checker", type=Path, default=Path(__file__).with_name("check-unsafe.py"))
    parser.add_argument("--runtime-root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    evidence = args.evidence.resolve(strict=True)
    if (evidence / "results").is_dir() and not (evidence / "run-metadata.json").exists():
        evidence = (evidence / "results").resolve(strict=True)
    checker = args.checker.resolve(strict=True)
    runtime_root = args.runtime_root.resolve(strict=True)

    baseline = subprocess.run(checker_command(checker, evidence, runtime_root), capture_output=True, text=True, timeout=180)
    if baseline.returncode != 0:
        print(f"baseline checker failed: {baseline.stderr.strip()}", file=sys.stderr)
        return 1
    baseline_verdict = json.loads(baseline.stdout)
    method = baseline_verdict["method"]

    target = read_json(evidence / "clean-requirement-target.json")
    if semantic_feasible(target, old_payment=True):
        print("baseline target unexpectedly feasible after old payment", file=sys.stderr)
        return 1
    semantic_flips: dict[str, bool] = {}
    no_payment = copy.deepcopy(target)
    semantic_flips["delete-old-payment"] = semantic_feasible(no_payment, old_payment=False)
    zero_cost = copy.deepcopy(target)
    zero_cost["kinds"]["charge-v1"]["costs"] = {}
    semantic_flips["old-cost-to-zero"] = semantic_feasible(zero_cost, old_payment=True)
    capacity_two = copy.deepcopy(target)
    capacity_two["capacities"]["approval"] = 2
    semantic_flips["capacity-to-two"] = semantic_feasible(capacity_two, old_payment=True)
    finish_zero = copy.deepcopy(target)
    finish_zero["kinds"]["finish-v2"]["costs"] = {}
    semantic_flips["finish-v2-cost-to-zero"] = semantic_feasible(finish_zero, old_payment=True)
    if semantic_flips != {
        "delete-old-payment": True, "old-cost-to-zero": True,
        "capacity-to-two": True, "finish-v2-cost-to-zero": True,
    }:
        print(f"semantic flip controls failed: {semantic_flips}", file=sys.stderr)
        return 1

    mutations: list[tuple[str, Mutation, bool]] = [
        ("observed-is-untrusted", mutate_json("observed.json", lambda value: value.update({"clean_target_completed": False})), True),
        ("delete-old-payment", delete_first_line("main-payment.history"), False),
        ("old-cost-to-zero", mutate_json("clean-requirement-target.json", lambda value: value["kinds"]["charge-v1"].update({"costs": {}})), False),
        ("finish-v2-cost-to-zero", mutate_json("clean-requirement-target.json", lambda value: value["kinds"]["finish-v2"].update({"costs": {}})), False),
        ("capacity-to-two", mutate_json("clean-requirement-target.json", lambda value: value["capacities"].update({"approval": 2})), False),
        ("target-payment-path", mutate_json("clean-final-payment-stats.json", lambda value: value.update({"paths": {"/v1/charge": 1}})), False),
        ("completion-marker-hash", mutate_json("main-expected-completion.json", lambda value: value.update({"provider_request_hash": "0" * 64})), False),
        ("provider-completion-hash", replace_bytes("main-completion.history", b'"request_hash":"', b'"request_hash":"0'), False),
        ("target-patch", replace_bytes("unsafe-target.patch", b"unsafe-v2", b"unsafe-x2"), False),
        ("build-context", replace_bytes("build.env", b"UNSAFE_V2_CONTEXT_SHA256=", b"UNSAFE_V2_CONTEXT_SHA256=0") if method == "proposed" else replace_bytes("build.env", b"NATIVE_UNSAFE_V2_CONTEXT_SHA256=", b"NATIVE_UNSAFE_V2_CONTEXT_SHA256=0"), False),
        ("metadata-image", mutate_json("run-metadata.json", lambda value: value.update({"target_image": "sha256:" + "0" * 64})), False),
        ("compose-target-kind", replace_bytes("main-compose-config.yaml", b"SAFE_CHANGE_FINISH_KIND: finish-v2", b"SAFE_CHANGE_FINISH_KIND: finish-v1") if method == "proposed" else replace_bytes("main-compose-config.yaml", b"PAYMENT_ENDPOINT: http://payment:8081/v2/charge", b"PAYMENT_ENDPOINT: http://payment:8081/v1/charge"), False),
        ("cut-journal-delete-payment", mutate_json("main-cut-journal.json", lambda value: value["rows"].pop(3)), False),
        ("final-business-state", replace_bytes("main-final-workflow-state.json", b'\\"DELIVERED\\"', b'\\"SCHEDULED\\"'), False),
        ("final-invocation-status", mutate_json("main-final-status.json", lambda value: value["rows"][0].update({"status": "failed"})), False),
    ]
    if method == "proposed":
        mutations.extend([
            ("witness", mutate_json("main-certificate-unsafe.json", lambda value: value["witness"].update({"reason": "tampered"})), False),
            ("certificate-head", mutate_json("main-certificate-unsafe-state.json", lambda value: value["history"].update({"hash": "0" * 64})), False),
            ("active-rule", mutate_json("main-control-after-refusal.json", lambda value: value["rule"].update({"allow": ["charge-v2"]})), False),
        ])
    else:
        mutations.extend([
            ("target-deployment", mutate_json("main-deployment-target.json", lambda value: value.update({"id": "dp_tampered"})), False),
            ("source-removal", replace_bytes("main-source-after-removal.exit-status.txt", b"1\n", b"0\n"), False),
            ("target-container-image", mutate_json("main-final-target-container.json", lambda value: value[0].update({"Image": "sha256:" + "0" * 64})), False),
        ])

    verdicts: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="unsafe-check-mutations-") as temporary:
        base = Path(temporary)
        for index, (name, mutation, should_accept) in enumerate(mutations):
            candidate = base / f"{index:02d}-{name}"
            shutil.copytree(evidence, candidate, ignore=shutil.ignore_patterns("compose.log", "*-observation-*.json", "build.stdout", "build.stderr"))
            mutation(candidate)
            completed = subprocess.run(checker_command(checker, candidate, runtime_root), capture_output=True, text=True, timeout=180)
            accepted = completed.returncode == 0
            if accepted != should_accept:
                print(f"mutation {name} accepted={accepted}, expected={should_accept}: {completed.stderr.strip()}", file=sys.stderr)
                return 1
            if should_accept:
                changed = json.loads(completed.stdout)
                if changed.get("evidence_digest") != baseline_verdict.get("evidence_digest"):
                    print("observed.json changed the evidence digest", file=sys.stderr)
                    return 1
            verdicts.append({"name": name, "accepted": accepted, "expected_accept": should_accept})

    output = {
        "schema": 1, "valid": True, "method": method,
        "baseline_evidence_digest": baseline_verdict["evidence_digest"],
        "semantic_flips": semantic_flips, "mutation_count": len(verdicts),
        "rejected_count": sum(not item["accepted"] for item in verdicts), "mutations": verdicts,
    }
    print(json.dumps(output, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
