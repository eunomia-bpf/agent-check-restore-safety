"""Tests for the typed history-admission compiler and independent verifier."""

from __future__ import annotations

from copy import deepcopy
from itertools import combinations
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from history_admission.compiler import compile_request
from history_admission.schema import SchemaError, loads_json
from history_admission.verifier import verify_result


HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "history_admission" / "inherit_choice.json"


def base_request() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def compile_base(request: dict | None = None) -> dict:
    return compile_request(base_request() if request is None else request)


def make_two_atom_choice(request: dict) -> None:
    """Give the right branch a different atom under exclusive authority."""

    authority = request["authority"]
    authority["atoms"].append("grant:G:2")
    authority["allowed_maxima"] = [
        ["grant:G:0", "grant:G:1"],
        ["grant:G:0", "grant:G:2"],
    ]
    request["source"]["cells"][1]["atom"] = "grant:G:2"
    request["operation"]["right"]["cells"][0]["atom"] = "grant:G:2"
    request["operation"]["right"]["cells"][0]["parent"] = "old-right"
    request["operation"]["right"]["cells"][0]["lease"] = None


def higher_order_request() -> dict:
    """A U(2,3) future: every pair is allowed, but the triple is not."""

    atoms = ["grant:H:0", "grant:H:1", "grant:H:2", "grant:H:3"]
    source_cells = [
        {
            "id": f"old-{name}",
            "atom": f"grant:H:{index}",
            "cell_anchor": f"old-cell:{name}",
        }
        for index, name in enumerate(("a", "b", "c"), start=1)
    ]
    target_cells = [
        {
            "local_id": name,
            "atom": f"grant:H:{index}",
            "commitment_key": f"effect:{name}",
            "effect_binding_digest": f"sha256:target-effect-{name}",
            "cell_anchor": f"target-cell:{name}",
            "parent": f"old-{name}",
            "lease": None,
        }
        for index, name in enumerate(("a", "b", "c"), start=1)
    ]
    pair_maxima = [["a", "b"], ["a", "c"], ["b", "c"]]
    target_refs = {
        name: {"role": "checkpoint", "local_id": name}
        for name in ("a", "b", "c")
    }
    return {
        "schema": "history-admission.request.v2",
        "request_id": "fixture:higher-order-u23",
        "authority": {
            "id": "grant:H",
            "atoms": atoms,
            "allowed_maxima": [
                ["grant:H:0", "grant:H:1", "grant:H:2"],
                ["grant:H:0", "grant:H:1", "grant:H:3"],
                ["grant:H:0", "grant:H:2", "grant:H:3"],
            ],
        },
        "source": {
            "version": 1,
            "cells": source_cells,
            "future_maxima": [
                ["old-a", "old-b"],
                ["old-a", "old-c"],
                ["old-b", "old-c"],
            ],
            "receipt_frontier": [
                {
                    "receipt": "receipt:h0",
                    "authority": "grant:H",
                    "atom": "grant:H:0",
                    "cell_anchor": "receipt-cell:h0",
                    "epoch": "epoch:h0",
                    "operation": "send:h0",
                    "effect_digest": "sha256:effect-h0",
                    "phase": "prepared",
                }
            ],
            "leases": [],
        },
        "ledger": [
            {
                "receipt": "receipt:h0",
                "authority": "grant:H",
                "atom": "grant:H:0",
                "cell_anchor": "receipt-cell:h0",
                "epoch": "epoch:h0",
                "operation": "send:h0",
                "effect_digest": "sha256:effect-h0",
                "phase": "prepared",
            }
        ],
        "operation": {
            "kind": "RestoreReplace",
            "target_version": 2,
            "aliases": [],
            "checkpoint": {
                "coverage": "exact",
                "cells": target_cells,
                "may_maxima": pair_maxima,
                "required_maxima": pair_maxima,
            },
            "gate_uses": [
                {
                    "id": f"gate-use:{name}",
                    "gate_origin": f"gate-origin:{name}",
                    "controller_anchor": f"controller:{name}",
                    "controller_version": 1,
                    "members": [target_refs[name]],
                    "local_maxima": [[target_refs[name]]],
                }
                for name in ("a", "b", "c")
            ],
            "controller_future_maxima": [
                ["controller:a", "controller:b", "controller:c"]
            ],
            "controller_future_coverage": "exact",
        },
    }


def retag_binary_operator(
    request: dict,
    kind: str,
    left_role: str,
    right_role: str,
) -> None:
    operation = request["operation"]
    operation["kind"] = kind
    operation[left_role] = operation.pop("left")
    operation[right_role] = operation.pop("right")
    role_map = {"left": left_role, "right": right_role}
    for gate_use in operation["gate_uses"]:
        for field in ("members", "local_maxima"):
            for item in gate_use[field]:
                refs = item if field == "local_maxima" else [item]
                for ref in refs:
                    ref["role"] = role_map[ref["role"]]


def finite_downsets(names: tuple[str, ...]) -> list[frozenset[frozenset[str]]]:
    configs = [
        frozenset(config)
        for size in range(len(names) + 1)
        for config in combinations(names, size)
    ]
    families: list[frozenset[frozenset[str]]] = []
    for bits in range(1 << len(configs)):
        family = frozenset(
            configs[index]
            for index in range(len(configs))
            if bits & (1 << index)
        )
        if frozenset() not in family:
            continue
        if all(
            frozenset(subset) in family
            for config in family
            for size in range(len(config) + 1)
            for subset in combinations(config, size)
        ):
            families.append(family)
    return families


def family_maxima(family: frozenset[frozenset[str]]) -> list[list[str]]:
    maxima = [
        config
        for config in family
        if not any(config < other for other in family)
    ]
    return [
        sorted(config)
        for config in sorted(maxima, key=lambda item: (len(item), sorted(item)))
    ]


def refinement_oracle_request(
    candidate: frozenset[frozenset[str]],
    required: frozenset[frozenset[str]],
    physical: frozenset[frozenset[str]],
) -> dict:
    names = ("a", "b", "c")
    refs = {
        name: {"role": "checkpoint", "local_id": name} for name in names
    }
    physical_support = sorted(set().union(*(set(config) for config in physical)))
    gate_uses = []
    controller_future = [[]]
    if physical_support:
        gate_uses = [
            {
                "id": "gate-use:oracle",
                "gate_origin": "gate-origin:oracle",
                "controller_anchor": "controller:oracle",
                "controller_version": 1,
                "members": [refs[name] for name in physical_support],
                "local_maxima": [
                    [refs[name] for name in config]
                    for config in family_maxima(physical)
                ],
            }
        ]
        controller_future = [["controller:oracle"]]
    return {
        "schema": "history-admission.request.v2",
        "request_id": "oracle:refinement",
        "authority": {
            "id": "grant:oracle",
            "atoms": [f"grant:oracle:{name}" for name in names],
            "allowed_maxima": [[f"grant:oracle:{name}" for name in names]],
        },
        "source": {
            "version": 1,
            "cells": [
                {
                    "id": f"old-{name}",
                    "atom": f"grant:oracle:{name}",
                    "cell_anchor": f"old-cell:{name}",
                }
                for name in names
            ],
            "future_maxima": [
                [f"old-{name}" for name in config]
                for config in family_maxima(candidate)
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
                "cells": [
                    {
                        "local_id": name,
                        "atom": f"grant:oracle:{name}",
                        "commitment_key": f"effect:{name}",
                        "effect_binding_digest": f"sha256:effect-{name}",
                        "cell_anchor": f"target-cell:{name}",
                        "parent": f"old-{name}",
                        "lease": None,
                    }
                    for name in names
                ],
                "may_maxima": family_maxima(candidate),
                "required_maxima": family_maxima(required),
            },
            "gate_uses": gate_uses,
            "controller_future_maxima": controller_future,
            "controller_future_coverage": "exact",
        },
    }


class HistoryAdmissionCompilerTests(unittest.TestCase):
    def test_choice_inherits_with_shared_logical_gate(self) -> None:
        request = base_request()
        second_use = deepcopy(request["operation"]["gate_uses"][0])
        second_use["id"] = "gate-use:choice-alias"
        request["operation"]["gate_uses"].append(second_use)
        result = compile_base(request)
        self.assertEqual("Inherit", result["semantic_admission"]["class"])
        self.assertEqual("Ready", result["deployment"]["readiness"])
        self.assertTrue(result["history_admission"]["structurally_eligible"])
        self.assertFalse(result["history_admission"]["effect_authorizes"])
        self.assertEqual("exact", result["controllers"]["co_live_coverage"])
        self.assertEqual(2, result["coordination"]["required_coliveness_arity"])
        self.assertEqual(
            ["gate-use:choice", "gate-use:choice-alias"],
            result["controllers"]["normalized"]["controller:choice"]["gate_uses"],
        )
        self.assertEqual(
            ["occ:left:left-effect", "occ:right:right-effect"],
            result["leases"][0]["target_cells"],
        )

    def test_same_arms_parallel_are_rejected_for_shared_lineage(self) -> None:
        request = base_request()
        request["operation"]["kind"] = "ForkParallel"
        result = compile_base(request)
        self.assertEqual("Reject", result["semantic_admission"]["class"])
        witness = result["semantic_admission"]["rejection_witness"]
        self.assertEqual("RequiredConfigurationRejected", witness["kind"])
        self.assertIn(
            "LineageCollision", {reason["kind"] for reason in witness["reasons"]}
        )
        self.assertFalse(result["history_admission"]["structurally_eligible"])

    def test_full_safe_without_parent_is_readmitted(self) -> None:
        request = base_request()
        for role in ("left", "right"):
            request["operation"][role]["cells"][0]["parent"] = None
            request["operation"][role]["cells"][0]["lease"] = None
        result = compile_base(request)
        self.assertEqual("ReadmitOK", result["semantic_admission"]["class"])
        self.assertEqual(
            "ParentMissing",
            result["semantic_admission"]["inheritance"]["reason"]["kind"],
        )
        self.assertEqual("Ready", result["deployment"]["readiness"])

    def test_sound_overapprox_is_reported_as_conservative(self) -> None:
        request = base_request()
        request["operation"]["left"]["coverage"] = "sound_overapprox"
        request["operation"]["controller_future_coverage"] = "sound_overapprox"
        result = compile_base(request)
        self.assertEqual("Inherit", result["semantic_admission"]["class"])
        self.assertEqual(
            "conservative_overapprox", result["operator"]["analysis_precision"]
        )
        self.assertEqual(
            {"left": "sound_overapprox", "right": "exact"},
            result["operator"]["coverage_by_role"],
        )
        self.assertEqual(
            "sound_overapprox", result["controllers"]["co_live_coverage"]
        )
        self.assertIn(
            "controller_coliveness_coverage_attestation",
            result["history_admission"]["external_obligations"],
        )

    def test_optional_unsafe_parallel_future_accepts_manifest_restriction(self) -> None:
        request = base_request()
        make_two_atom_choice(request)
        request["operation"]["kind"] = "ForkParallel"
        request["operation"]["right"]["required_maxima"] = [[]]
        result = compile_base(request)
        self.assertEqual("NeedsMechanism", result["semantic_admission"]["class"])
        self.assertEqual("ReadyWithRestriction", result["deployment"]["readiness"])
        self.assertEqual("manifest_supplied", result["deployment"]["restriction"])
        self.assertTrue(result["history_admission"]["structurally_eligible"])
        self.assertTrue(verify_result(request, result)["structurally_admits"])
        self.assertIn(
            "fresh_authority_issuance",
            result["history_admission"]["external_obligations"],
        )
        self.assertEqual(
            "OptionalConfigurationPruned",
            result["semantic_admission"]["pruning_witness"]["kind"],
        )

    def test_required_unsafe_parallel_future_is_rejected(self) -> None:
        request = base_request()
        make_two_atom_choice(request)
        request["operation"]["kind"] = "ForkParallel"
        result = compile_base(request)
        self.assertEqual("Reject", result["semantic_admission"]["class"])
        self.assertIsNone(result["coordination"]["required_coliveness_arity"])
        reasons = result["semantic_admission"]["rejection_witness"]["reasons"]
        self.assertIn("ForbiddenUnion", {reason["kind"] for reason in reasons})

    def test_new_durable_receipt_for_future_atom_is_prefix_replay(self) -> None:
        request = base_request()
        request["ledger"].append(
            {
                "receipt": "receipt:1",
                "authority": "grant:G",
                "atom": "grant:G:1",
                "cell_anchor": "receipt-cell:1",
                "epoch": "epoch:1",
                "operation": "send:1",
                "effect_digest": "sha256:effect-1",
                "phase": "prepared",
            }
        )
        result = compile_base(request)
        self.assertEqual("Reject", result["semantic_admission"]["class"])
        reasons = result["semantic_admission"]["rejection_witness"]["reasons"]
        self.assertEqual("PrefixReplay", reasons[0]["kind"])
        self.assertEqual(
            "PrefixGrew",
            result["semantic_admission"]["inheritance"]["reason"]["kind"],
        )

    def test_parallel_same_cell_requires_explicit_alias_then_inherits(self) -> None:
        request = base_request()
        request["operation"]["kind"] = "ForkParallel"
        right = request["operation"]["right"]["cells"][0]
        left = request["operation"]["left"]["cells"][0]
        right["atom"] = left["atom"]
        right["cell_anchor"] = left["cell_anchor"]
        right["commitment_key"] = left["commitment_key"]
        right["effect_binding_digest"] = left["effect_binding_digest"]
        right["parent"] = left["parent"]
        right["lease"] = left["lease"]
        request["operation"]["aliases"] = [
            {
                "id": "alias:shared-cell",
                "members": [
                    {"role": "left", "local_id": "left-effect"},
                    {"role": "right", "local_id": "right-effect"},
                ],
                "evidence": {
                    "kind": "stable_cell_anchor",
                    "value": left["cell_anchor"],
                },
            }
        ]
        result = compile_base(request)
        self.assertEqual("Inherit", result["semantic_admission"]["class"])
        self.assertEqual(1, len(result["normalization"]["cells"]))
        self.assertEqual("Ready", result["deployment"]["readiness"])

    def test_undeclared_shared_cell_anchor_fails_closed(self) -> None:
        request = base_request()
        request["operation"]["right"]["cells"][0]["cell_anchor"] = (
            request["operation"]["left"]["cells"][0]["cell_anchor"]
        )
        with self.assertRaisesRegex(SchemaError, "reused without one complete alias"):
            compile_base(request)

    def test_alias_cannot_hide_different_commitment_key(self) -> None:
        request = base_request()
        left = request["operation"]["left"]["cells"][0]
        right = request["operation"]["right"]["cells"][0]
        right["cell_anchor"] = left["cell_anchor"]
        request["operation"]["aliases"] = [
            {
                "id": "bad-alias",
                "members": [
                    {"role": "left", "local_id": "left-effect"},
                    {"role": "right", "local_id": "right-effect"},
                ],
                "evidence": {
                    "kind": "stable_cell_anchor",
                    "value": left["cell_anchor"],
                },
            }
        ]
        with self.assertRaisesRegex(SchemaError, "different atom, commitment key"):
            compile_base(request)

    def test_alias_cannot_hide_different_effect_binding(self) -> None:
        request = base_request()
        left = request["operation"]["left"]["cells"][0]
        right = request["operation"]["right"]["cells"][0]
        right["atom"] = left["atom"]
        right["cell_anchor"] = left["cell_anchor"]
        right["commitment_key"] = left["commitment_key"]
        request["operation"]["aliases"] = [
            {
                "id": "bad-effect-alias",
                "members": [
                    {"role": "left", "local_id": "left-effect"},
                    {"role": "right", "local_id": "right-effect"},
                ],
                "evidence": {
                    "kind": "stable_cell_anchor",
                    "value": left["cell_anchor"],
                },
            }
        ]
        with self.assertRaisesRegex(SchemaError, "effect binding"):
            compile_base(request)

    def test_alias_identity_is_independent_of_parent_and_lease_transport(self) -> None:
        request = base_request()
        request["operation"]["kind"] = "ForkParallel"
        left = request["operation"]["left"]["cells"][0]
        right = request["operation"]["right"]["cells"][0]
        right["atom"] = left["atom"]
        right["cell_anchor"] = left["cell_anchor"]
        right["commitment_key"] = left["commitment_key"]
        right["effect_binding_digest"] = left["effect_binding_digest"]
        right["parent"] = "old-right"
        right["lease"] = None
        request["operation"]["aliases"] = [
            {
                "id": "alias:identity-only",
                "members": [
                    {"role": "left", "local_id": "left-effect"},
                    {"role": "right", "local_id": "right-effect"},
                ],
                "evidence": {
                    "kind": "stable_cell_anchor",
                    "value": left["cell_anchor"],
                },
            }
        ]
        result = compile_base(request)
        self.assertEqual("ReadmitOK", result["semantic_admission"]["class"])
        self.assertEqual(
            "ParentAmbiguous",
            result["semantic_admission"]["inheritance"]["reason"]["kind"],
        )
        normalized = next(iter(result["normalization"]["cells"].values()))
        self.assertEqual(["old-left", "old-right"], normalized["parent_candidates"])
        self.assertIsNone(normalized["lease"])

    def test_cloned_choice_gates_product_expand_same_cells(self) -> None:
        request = base_request()
        base_use = request["operation"]["gate_uses"][0]
        first = deepcopy(base_use)
        first["id"] = "gate-use:clone-1"
        first["controller_anchor"] = "controller:clone-1"
        second = deepcopy(base_use)
        second["id"] = "gate-use:clone-2"
        second["controller_anchor"] = "controller:clone-2"
        request["operation"]["gate_uses"] = [first, second]
        request["operation"]["controller_future_maxima"] = [
            ["controller:clone-1", "controller:clone-2"]
        ]
        result = compile_base(request)
        self.assertEqual("Inherit", result["semantic_admission"]["class"])
        self.assertEqual("NeedsCoordination", result["deployment"]["readiness"])
        self.assertEqual("GateClone", result["coordination"]["witness"]["kind"])
        self.assertEqual(
            "CorrelationCut",
            result["coordination"]["witness"]["failure_class"],
        )
        self.assertFalse(result["history_admission"]["structurally_eligible"])

    def test_cloned_controllers_over_one_aliased_cell_need_atomic_redemption(self) -> None:
        request = base_request()
        request["operation"]["kind"] = "ForkParallel"
        left = request["operation"]["left"]["cells"][0]
        right = request["operation"]["right"]["cells"][0]
        for field in (
            "atom",
            "cell_anchor",
            "commitment_key",
            "effect_binding_digest",
            "parent",
            "lease",
        ):
            right[field] = left[field]
        request["operation"]["aliases"] = [
            {
                "id": "alias:one-redemption-cell",
                "members": [
                    {"role": "left", "local_id": "left-effect"},
                    {"role": "right", "local_id": "right-effect"},
                ],
                "evidence": {
                    "kind": "stable_cell_anchor",
                    "value": left["cell_anchor"],
                },
            }
        ]
        base_use = request["operation"]["gate_uses"][0]
        first = deepcopy(base_use)
        first["id"] = "gate-use:alias-clone-1"
        first["controller_anchor"] = "controller:alias-clone-1"
        second = deepcopy(base_use)
        second["id"] = "gate-use:alias-clone-2"
        second["controller_anchor"] = "controller:alias-clone-2"
        request["operation"]["gate_uses"] = [first, second]
        request["operation"]["controller_future_maxima"] = [
            ["controller:alias-clone-1", "controller:alias-clone-2"]
        ]
        result = compile_base(request)
        self.assertEqual("Inherit", result["semantic_admission"]["class"])
        self.assertEqual("Ready", result["deployment"]["readiness"])
        self.assertIn(
            "atomic_redemption",
            result["history_admission"]["external_obligations"],
        )
        self.assertFalse(result["history_admission"]["effect_authorizes"])

    def test_exclusive_gate_instances_do_not_product_expand(self) -> None:
        request = base_request()
        base_use = request["operation"]["gate_uses"][0]
        first = deepcopy(base_use)
        first["id"] = "gate-use:clone-1"
        first["controller_anchor"] = "controller:clone-1"
        second = deepcopy(base_use)
        second["id"] = "gate-use:clone-2"
        second["controller_anchor"] = "controller:clone-2"
        request["operation"]["gate_uses"] = [first, second]
        request["operation"]["controller_future_maxima"] = [
            ["controller:clone-1"],
            ["controller:clone-2"],
        ]
        result = compile_base(request)
        self.assertEqual("Ready", result["deployment"]["readiness"])

    def test_every_declared_controller_must_be_reachable(self) -> None:
        request = base_request()
        base_use = request["operation"]["gate_uses"][0]
        hidden = deepcopy(base_use)
        hidden["id"] = "gate-use:hidden-clone"
        hidden["controller_anchor"] = "controller:hidden-clone"
        request["operation"]["gate_uses"].append(hidden)
        with self.assertRaisesRegex(SchemaError, "cover every declared controller"):
            compile_base(request)

    def test_optional_physical_restriction_is_safe_refinement(self) -> None:
        request = base_request()
        request["operation"]["right"]["required_maxima"] = [[]]
        left_ref = {"role": "left", "local_id": "left-effect"}
        request["operation"]["gate_uses"] = [
            {
                "id": "gate-use:left-only",
                "gate_origin": "gate-origin:left-only",
                "controller_anchor": "controller:left-only",
                "controller_version": 1,
                "members": [left_ref],
                "local_maxima": [[left_ref]],
            }
        ]
        request["operation"]["controller_future_maxima"] = [
            ["controller:left-only"]
        ]
        result = compile_base(request)
        self.assertEqual("Inherit", result["semantic_admission"]["class"])
        self.assertEqual("safe_restriction", result["coordination"]["status"])
        self.assertTrue(result["coordination"]["required_covered"])
        self.assertTrue(result["coordination"]["admitted_respected"])
        self.assertFalse(result["coordination"]["exact_fidelity"])
        self.assertEqual(
            "OptionalBehaviorRestricted",
            result["coordination"]["witness"]["kind"],
        )
        self.assertEqual("Ready", result["deployment"]["readiness"])
        self.assertTrue(result["history_admission"]["structurally_eligible"])

    def test_split_gate_emits_gate_cut_not_gate_clone(self) -> None:
        request = base_request()
        left_ref = {"role": "left", "local_id": "left-effect"}
        right_ref = {"role": "right", "local_id": "right-effect"}
        request["operation"]["gate_uses"] = [
            {
                "id": "gate-use:left",
                "gate_origin": "gate-origin:left",
                "controller_anchor": "controller:left",
                "controller_version": 1,
                "members": [left_ref],
                "local_maxima": [[left_ref]],
            },
            {
                "id": "gate-use:right",
                "gate_origin": "gate-origin:right",
                "controller_anchor": "controller:right",
                "controller_version": 1,
                "members": [right_ref],
                "local_maxima": [[right_ref]],
            },
        ]
        request["operation"]["controller_future_maxima"] = [
            ["controller:left", "controller:right"]
        ]
        result = compile_base(request)
        self.assertEqual("GateCut", result["coordination"]["witness"]["kind"])
        self.assertEqual(
            "CorrelationCut",
            result["coordination"]["witness"]["failure_class"],
        )

    def test_one_locally_unsafe_controller_is_not_called_a_gate_cut(self) -> None:
        request = higher_order_request()
        refs = [
            {"role": "checkpoint", "local_id": name}
            for name in ("a", "b", "c")
        ]
        request["operation"]["gate_uses"] = [
            {
                "id": "gate-use:overpermit",
                "gate_origin": "gate-origin:overpermit",
                "controller_anchor": "controller:overpermit",
                "controller_version": 1,
                "members": refs,
                "local_maxima": [refs],
            }
        ]
        request["operation"]["controller_future_maxima"] = [
            ["controller:overpermit"]
        ]
        result = compile_request(request)
        witness = result["coordination"]["witness"]
        self.assertEqual("ControllerOverpermit", witness["kind"])
        self.assertEqual("LocalOverpermission", witness["failure_class"])
        self.assertEqual(
            ["occ:checkpoint:a", "occ:checkpoint:b", "occ:checkpoint:c"],
            witness["minimal_nonface"],
        )

    def test_pruned_cell_is_reported_outside_admitted_support(self) -> None:
        request = base_request()
        right = request["operation"]["right"]
        right["cells"][0]["atom"] = "grant:G:0"
        right["cells"][0]["parent"] = None
        right["cells"][0]["lease"] = None
        right["required_maxima"] = [[]]
        result = compile_base(request)
        self.assertEqual("NeedsMechanism", result["semantic_admission"]["class"])
        witness = result["coordination"]["witness"]
        self.assertEqual("OutsideSupport", witness["kind"])
        self.assertEqual("OutsideSupport", witness["failure_class"])
        self.assertNotIn("minimal_nonface", witness)
        self.assertEqual(1, result["coordination"]["required_coliveness_arity"])
        self.assertEqual(
            ["occ:right:right-effect"], witness["outside_support_cells"]
        )

    def test_higher_order_constraint_requires_joint_coordination(self) -> None:
        request = higher_order_request()
        result = compile_request(request)
        self.assertEqual("Inherit", result["semantic_admission"]["class"])
        self.assertEqual("NeedsCoordination", result["deployment"]["readiness"])
        self.assertEqual("exact", result["controllers"]["co_live_coverage"])
        self.assertEqual(3, result["coordination"]["required_coliveness_arity"])
        self.assertEqual(
            [["occ:checkpoint:a", "occ:checkpoint:b", "occ:checkpoint:c"]],
            result["coordination"]["minimal_nonfaces"],
        )
        self.assertEqual(
            [["occ:checkpoint:a", "occ:checkpoint:b", "occ:checkpoint:c"]],
            result["coordination"]["components"],
        )
        self.assertEqual("GateCut", result["coordination"]["witness"]["kind"])

        pairwise_only = higher_order_request()
        pairwise_only["operation"]["controller_future_maxima"] = [
            ["controller:a", "controller:b"],
            ["controller:a", "controller:c"],
            ["controller:b", "controller:c"],
        ]
        pairwise_result = compile_request(pairwise_only)
        self.assertEqual("Ready", pairwise_result["deployment"]["readiness"])
        self.assertEqual("exact", pairwise_result["coordination"]["status"])
        self.assertEqual(
            3, pairwise_result["coordination"]["required_coliveness_arity"]
        )

    def test_all_six_typed_operators_follow_choice_tensor_semantics(self) -> None:
        expected = {
            "ForkChoice": "Inherit",
            "ForkParallel": "Reject",
            "MergeSelect": "Inherit",
            "MergeJoin": "Reject",
            "RestoreLive": "Reject",
        }
        for kind, semantic_class in expected.items():
            with self.subTest(kind=kind):
                request = base_request()
                if kind == "RestoreLive":
                    retag_binary_operator(
                        request, kind, "current", "checkpoint"
                    )
                else:
                    request["operation"]["kind"] = kind
                result = compile_base(request)
                self.assertEqual(kind, result["operator"]["kind"])
                self.assertEqual(
                    semantic_class, result["semantic_admission"]["class"]
                )

        replace = base_request()
        operation = replace["operation"]
        operation["kind"] = "RestoreReplace"
        operation["checkpoint"] = operation.pop("left")
        operation.pop("right")
        checkpoint_ref = {"role": "checkpoint", "local_id": "left-effect"}
        operation["gate_uses"] = [
            {
                "id": "gate-use:replace",
                "gate_origin": "gate-origin:replace",
                "controller_anchor": "controller:replace",
                "controller_version": 1,
                "members": [checkpoint_ref],
                "local_maxima": [[checkpoint_ref]],
            }
        ]
        operation["controller_future_maxima"] = [["controller:replace"]]
        result = compile_base(replace)
        self.assertEqual("RestoreReplace", result["operator"]["kind"])
        self.assertEqual("Inherit", result["semantic_admission"]["class"])

    def test_receipt_binding_regression_is_invalid_evidence_not_semantic_reject(self) -> None:
        request = base_request()
        request["ledger"][0]["effect_digest"] = "sha256:rebound"
        with self.assertRaisesRegex(SchemaError, "rebound source receipt"):
            compile_base(request)

    def test_request_v2_and_strict_json_fail_closed(self) -> None:
        with self.assertRaisesRegex(SchemaError, "duplicate JSON object key"):
            loads_json('{"schema":"a","schema":"b"}')
        with self.assertRaisesRegex(SchemaError, "floating-point"):
            loads_json('{"value":1.0}')

        request = base_request()
        request["schema"] = "history-admission.request.v1"
        with self.assertRaisesRegex(SchemaError, "history-admission.request.v2"):
            compile_base(request)

        request = base_request()
        del request["operation"]["controller_future_coverage"]
        with self.assertRaisesRegex(SchemaError, "controller_future_coverage"):
            compile_base(request)

        request = base_request()
        request["operation"]["controller_future_coverage"] = "pairwise"
        with self.assertRaisesRegex(SchemaError, "exact or sound_overapprox"):
            compile_base(request)

    def test_raw_manifest_caps_fail_closed(self) -> None:
        request = base_request()
        request["request_id"] = "x" * 4097
        with self.assertRaisesRegex(SchemaError, "Unicode code points"):
            compile_base(request)

        request = base_request()
        base_use = request["operation"]["gate_uses"][0]
        request["operation"]["gate_uses"] = []
        for index in range(25):
            gate_use = deepcopy(base_use)
            gate_use["id"] = f"gate-use:{index}"
            request["operation"]["gate_uses"].append(gate_use)
        with self.assertRaisesRegex(SchemaError, "more than 24 gate uses"):
            compile_base(request)

    def test_compilation_is_deterministic(self) -> None:
        self.assertEqual(compile_base(), compile_base())

    def test_exhaustive_three_cell_refinement_oracle(self) -> None:
        names = ("a", "b", "c")
        families = finite_downsets(names)
        candidates = [
            family
            for family in families
            if set().union(*(set(config) for config in family)) == set(names)
        ]
        checked = 0
        for candidate in candidates:
            for required in (family for family in families if family <= candidate):
                for physical in families:
                    request = refinement_oracle_request(
                        candidate, required, physical
                    )
                    result = compile_request(request)
                    extra = physical - candidate
                    missing_required = required - physical
                    missing_optional = candidate - physical
                    if not extra and not missing_optional:
                        expected = "exact"
                    elif not extra and not missing_required:
                        expected = "safe_restriction"
                    elif extra and missing_required:
                        expected = "unsafe_and_incomplete"
                    elif extra:
                        expected = "unsafe_overapprox"
                    else:
                        expected = "missing_required"
                    self.assertEqual(expected, result["coordination"]["status"])
                    seal = verify_result(request, result)
                    self.assertTrue(seal["valid"])
                    self.assertEqual(
                        expected in {"exact", "safe_restriction"},
                        seal["structurally_admits"],
                    )
                    checked += 1
        self.assertEqual(2166, checked)


class HistoryAdmissionVerifierTests(unittest.TestCase):
    def _run_cli(self, request: dict, result: dict) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            request_path = root / "request.json"
            result_path = root / "result.json"
            seal_path = root / "seal.json"
            request_path.write_text(json.dumps(request), encoding="utf-8")
            result_path.write_text(json.dumps(result), encoding="utf-8")
            return subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "history_admission.verifier",
                    str(request_path),
                    str(result_path),
                    "--output",
                    str(seal_path),
                ],
                cwd=HERE,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

    def test_verifier_accepts_compiler_result(self) -> None:
        request = base_request()
        completed = self._run_cli(request, compile_base(request))
        self.assertEqual(0, completed.returncode, completed.stderr)
        seal = verify_result(request, compile_base(request))
        self.assertTrue(seal["valid"])
        self.assertTrue(seal["structurally_admits"])
        self.assertFalse(seal["effect_authorizes"])
        self.assertEqual("history_admission", seal["seal_kind"])

    def test_verifier_accepts_higher_order_result(self) -> None:
        request = higher_order_request()
        completed = self._run_cli(request, compile_request(request))
        self.assertEqual(0, completed.returncode, completed.stderr)

    def test_verifier_rejects_tampered_semantic_class(self) -> None:
        request = base_request()
        result = compile_base(request)
        result["semantic_admission"]["class"] = "ReadmitOK"
        completed = self._run_cli(request, result)
        self.assertEqual(3, completed.returncode)

        result = compile_base(request)
        result["controllers"]["co_live_coverage"] = "sound_overapprox"
        completed = self._run_cli(request, result)
        self.assertEqual(3, completed.returncode)

        result = compile_base(request)
        result["coordination"]["required_coliveness_arity"] = 1
        completed = self._run_cli(request, result)
        self.assertEqual(3, completed.returncode)

    def test_verifier_source_does_not_import_compiler(self) -> None:
        verifier = (HERE / "history_admission" / "verifier.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("import compiler", verifier)
        self.assertNotIn("from .compiler", verifier)


if __name__ == "__main__":
    unittest.main()
