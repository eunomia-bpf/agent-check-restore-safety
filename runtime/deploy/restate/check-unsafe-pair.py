#!/usr/bin/env python3
"""Check that proposed/native unsafe-edit bundles are a matched pair."""

from __future__ import annotations

import argparse
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys


SCRIPT_DIR = Path(__file__).resolve().parent
CHECK_PATH = SCRIPT_DIR / "check-unsafe.py"
SPEC = importlib.util.spec_from_file_location("unsafe_check", CHECK_PATH)
assert SPEC is not None and SPEC.loader is not None
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


def root(path: Path) -> Path:
    value = path.resolve(strict=True)
    if (value / "results").is_dir() and not (value / "run-metadata.json").exists():
        value = (value / "results").resolve(strict=True)
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proposed", required=True, type=Path)
    parser.add_argument("--native", required=True, type=Path)
    parser.add_argument("--runtime-root", type=Path, default=SCRIPT_DIR.parents[1])
    parser.add_argument(
        "--allow-unmatched-workload", action="store_true",
        help="audit legacy preflights with different order IDs; full runs must not use this",
    )
    args = parser.parse_args()
    try:
        proposed_root, native_root = root(args.proposed), root(args.native)
        runtime_root = args.runtime_root.resolve(strict=True)
        proposed = CHECK.check(proposed_root, runtime_root)
        native = CHECK.check(native_root, runtime_root)
        CHECK.require(proposed["method"] == "proposed" and native["method"] == "native", "pair lanes differ")
        target_proposed = CHECK.read(proposed_root, "clean-requirement-target.json")
        target_native = CHECK.read(native_root, "clean-requirement-target.json")
        CHECK.require(target_proposed == target_native, "pair target Requirements differ")
        source_proposed = CHECK.read(proposed_root, "clean-requirement-source.json")
        source_native = CHECK.read(native_root, "clean-requirement-source.json")
        CHECK.require(source_proposed == source_native, "pair source Requirements differ")
        proposed_build_bytes = CHECK.read(proposed_root, "build.env")
        native_build_bytes = CHECK.read(native_root, "build.env")
        CHECK.require(proposed_build_bytes == native_build_bytes, "pair frozen build.env bytes differ")
        proposed_build = CHECK.parse_env(proposed_build_bytes)
        native_build = CHECK.parse_env(native_build_bytes)
        for key in (
            "UPSTREAM_ARCHIVE_SHA256", "APP_LOCK_SHA256", "V1_PROGRAM_SHA256",
            "UNSAFE_V2_WORKFLOW_SHA256", "UNSAFE_V2_COMPILED_SHA256",
            "NATIVE_UNSAFE_V2_COMPILED_SHA256",
        ):
            CHECK.require(proposed_build.get(key) == native_build.get(key), f"pair build key {key} differs")
        CHECK.require(
            proposed_build["UNSAFE_V2_COMPILED_SHA256"] == native_build["NATIVE_UNSAFE_V2_COMPILED_SHA256"],
            "proposed/native target workflow bytes differ",
        )
        certificate = CHECK.obj(CHECK.jvalue(proposed_root, "clean-certificate-target.json"), "clean target Certificate")
        CHECK.require(
            json.dumps(certificate.get("requirement"), sort_keys=True, separators=(",", ":")).encode()
            == json.dumps(json.loads(target_native), sort_keys=True, separators=(",", ":")).encode(),
            "empty-History Certificate is not bound to the native lane's exact target Requirement",
        )
        CHECK.require(proposed["clean_target_completed"] and native["clean_target_completed"], "one exact target feasibility control failed")
        CHECK.require(proposed["main_decision"] == "impossible" and not proposed["target_started"], "proposed lane did not refuse before target")
        CHECK.require(native["target_started"] and native["external_requirement_violated"], "native lane did not expose external Requirement overuse")
        proposed_metadata = CHECK.obj(CHECK.jvalue(proposed_root, "run-metadata.json"), "proposed run metadata")
        native_metadata = CHECK.obj(CHECK.jvalue(native_root, "run-metadata.json"), "native run metadata")
        matched_ids = (
            proposed_metadata.get("clean_order_id") == native_metadata.get("clean_order_id")
            and proposed_metadata.get("main_order_id") == native_metadata.get("main_order_id")
        )
        matched_orders = (
            CHECK.read(proposed_root, "clean-order.json") == CHECK.read(native_root, "clean-order.json")
            and CHECK.read(proposed_root, "main-order.json") == CHECK.read(native_root, "main-order.json")
        )
        proposed_payment = CHECK.records(proposed_root, "main-payment.history")[0]["operation_id"]
        native_payment = CHECK.records(native_root, "main-payment.history")[0]["operation_id"]
        proposed_completion = CHECK.records(proposed_root, "main-completion.history")[0]["operation_id"]
        native_completion = CHECK.records(native_root, "main-completion.history")[0]["operation_id"]
        matched_operations = (
            proposed_payment == native_payment and proposed_completion == native_completion
        )
        matched_workload = matched_ids and matched_orders and matched_operations
        if not args.allow_unmatched_workload:
            CHECK.require(matched_ids, "pair clean/main order IDs differ")
            CHECK.require(matched_orders, "pair clean/main order request bytes differ")
            CHECK.require(matched_operations, "pair main external Operation identities differ")
        pair_payload = {
            "proposed_digest": proposed["evidence_digest"], "native_digest": native["evidence_digest"],
            "target_requirement_sha256": sha256(target_proposed).hexdigest(),
            "target_workflow_sha256": proposed_build["UNSAFE_V2_COMPILED_SHA256"],
            "matched_workload": matched_workload,
        }
        pair_digest = sha256(json.dumps(pair_payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        output = {
            "schema": 1, "valid": True, "cell": "history-dependent-unsafe-edit",
            "clean_target_completed_both": True, "same_target_requirement": True,
            "same_target_workflow_bytes": True, "empty_history_allow": ["charge-v2", "finish-v2"],
            "matched_workload": matched_workload,
            "clean_order_id": proposed_metadata.get("clean_order_id") if matched_ids else None,
            "main_order_id": proposed_metadata.get("main_order_id") if matched_ids else None,
            "main_payment_operation_id": proposed_payment if matched_operations else None,
            "main_completion_operation_id": proposed_completion if matched_operations else None,
            "proposed_decision": "impossible", "proposed_target_started": False,
            "native_runtime_status": "completed", "native_approval_used": 2,
            "native_approval_capacity": 1, "pair_digest": pair_digest,
        }
    except (CHECK.EvidenceError, OSError) as error:
        print(f"check-unsafe-pair: {error}", file=sys.stderr)
        return 1
    print(json.dumps(output, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
