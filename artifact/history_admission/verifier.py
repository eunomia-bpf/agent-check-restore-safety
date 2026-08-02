"""Independent verifier for typed history-admission results.

The verifier treats the result producer as untrusted.  It parses the request
again, builds a separate bit-mask model of every finite family, reconstructs
the complete canonical result, and compares the supplied result byte-for-byte
at the canonical-JSON level.  Only strict JSON/schema utilities are shared.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from itertools import combinations
import sys
from typing import Any, Iterable, Iterator, Mapping, Sequence
from urllib.parse import quote

from .schema import (
    MAX_ATOMS,
    MAX_CONTROLLERS,
    MAX_EXPANDED_CONFIGURATIONS,
    MAX_GATE_USES,
    MAX_OCCURRENCES,
    MAX_PRODUCT_STATES,
    MAX_SOURCE_CELLS,
    MAX_TARGET_CELLS,
    REQUEST_SCHEMA,
    RESULT_SCHEMA,
    VERIFICATION_SCHEMA,
    SchemaError,
    canonical_json,
    digest_json,
    expect_exact_keys,
    expect_list,
    expect_nonnegative_int,
    expect_object,
    expect_optional_string,
    expect_string,
    load_json,
    unique_strings,
    write_json,
)


Mask = int
MaskFamily = frozenset[Mask]
OccurrenceRef = tuple[str, str]


_OPERATOR_ROLES: dict[str, tuple[str, ...]] = {
    "ForkChoice": ("left", "right"),
    "ForkParallel": ("left", "right"),
    "RestoreReplace": ("checkpoint",),
    "RestoreLive": ("current", "checkpoint"),
    "MergeSelect": ("left", "right"),
    "MergeJoin": ("left", "right"),
}
_CHOICE_KINDS = frozenset({"ForkChoice", "MergeSelect"})
_TENSOR_KINDS = frozenset({"ForkParallel", "RestoreLive", "MergeJoin"})
_PHASE_ORDER = {"prepared": 0, "settled": 1}


@dataclass(frozen=True)
class _ReceiptRow:
    receipt: str
    authority: str
    atom: str
    cell_anchor: str
    epoch: str
    operation: str
    effect_digest: str
    phase: str

    def binding(self) -> tuple[str, ...]:
        return (
            self.authority,
            self.atom,
            self.cell_anchor,
            self.epoch,
            self.operation,
            self.effect_digest,
        )

    def as_json(self) -> dict[str, Any]:
        return {
            "receipt": self.receipt,
            "authority": self.authority,
            "atom": self.atom,
            "cell_anchor": self.cell_anchor,
            "epoch": self.epoch,
            "operation": self.operation,
            "effect_digest": self.effect_digest,
            "phase": self.phase,
        }


@dataclass(frozen=True)
class _SourceCellRow:
    atom: str
    anchor: str


@dataclass(frozen=True)
class _LeaseRow:
    issued_version: int
    cell: str
    atom: str


@dataclass(frozen=True)
class _OccurrenceRow:
    role: str
    local_id: str
    atom: str
    commitment_key: str
    effect_binding_digest: str
    anchor: str
    parent: str | None
    lease: str | None

    @property
    def ref(self) -> OccurrenceRef:
        return (self.role, self.local_id)


@dataclass(frozen=True)
class _NormalizedCellRow:
    atom: str
    commitment_key: str
    effect_binding_digest: str
    anchor: str
    parent: str | None
    parent_candidates: tuple[str, ...]
    has_unparented_occurrence: bool
    lease: str | None
    lease_candidates: tuple[str, ...]
    has_unleased_occurrence: bool
    occurrences: tuple[OccurrenceRef, ...]


@dataclass(frozen=True)
class _ControllerRow:
    origin: str
    version: int
    local_family: MaskFamily
    use_ids: tuple[str, ...]


@dataclass(frozen=True)
class _RequestModel:
    raw: dict[str, Any]
    request_id: str
    authority_id: str
    atom_names: tuple[str, ...]
    authority: MaskFamily
    source_version: int
    source_names: tuple[str, ...]
    source_cells: dict[str, _SourceCellRow]
    source_future: MaskFamily
    source_receipts: dict[str, _ReceiptRow]
    ledger_receipts: dict[str, _ReceiptRow]
    source_durable: Mask
    current_durable: Mask
    leases: dict[str, _LeaseRow]
    operator: str
    target_version: int
    target_names: tuple[str, ...]
    role_coverage: dict[str, str]
    role_may: dict[str, MaskFamily]
    role_required: dict[str, MaskFamily]
    normalized_cells: dict[str, _NormalizedCellRow]
    occurrence_to_cell: dict[OccurrenceRef, str]
    alias_groups: tuple[dict[str, Any], ...]
    controller_names: tuple[str, ...]
    controllers: dict[str, _ControllerRow]
    controller_future: MaskFamily
    controller_future_coverage: str


def _indices(names: Sequence[str]) -> dict[str, int]:
    return {name: index for index, name in enumerate(names)}


def _mask_members(mask: Mask, names: Sequence[str]) -> list[str]:
    return [name for index, name in enumerate(names) if mask & (1 << index)]


def _mask_key(mask: Mask, names: Sequence[str]) -> tuple[int, tuple[str, ...]]:
    return (mask.bit_count(), tuple(_mask_members(mask, names)))


def _ordered_masks(family: Iterable[Mask], names: Sequence[str]) -> list[Mask]:
    return sorted(family, key=lambda mask: _mask_key(mask, names))


def _submasks(mask: Mask) -> Iterator[Mask]:
    current = mask
    while True:
        yield current
        if current == 0:
            return
        current = (current - 1) & mask


def _closure(maxima: Iterable[Mask], path: str) -> MaskFamily:
    expanded: set[Mask] = set()
    saw_maximum = False
    for maximum in maxima:
        saw_maximum = True
        expanded.update(_submasks(maximum))
        if len(expanded) > MAX_EXPANDED_CONFIGURATIONS:
            raise SchemaError(
                f"{path} expands past {MAX_EXPANDED_CONFIGURATIONS} configurations"
            )
    if not saw_maximum:
        raise SchemaError(f"{path} must contain at least one maximal configuration")
    return frozenset(expanded)


def _parse_named_family(value: Any, names: Sequence[str], path: str) -> MaskFamily:
    positions = _indices(names)
    maxima: list[Mask] = []
    for config_index, raw_config in enumerate(expect_list(value, path)):
        members = unique_strings(raw_config, f"{path}[{config_index}]")
        unknown = sorted(set(members) - set(positions))
        if unknown:
            raise SchemaError(
                f"{path}[{config_index}] references undeclared values: "
                + ", ".join(unknown)
            )
        mask = 0
        for member in members:
            mask |= 1 << positions[member]
        maxima.append(mask)
    return _closure(maxima, path)


def _maxima(family: MaskFamily, names: Sequence[str]) -> list[list[str]]:
    maximal = [
        mask
        for mask in family
        if not any(mask != other and mask & ~other == 0 for other in family)
    ]
    return [_mask_members(mask, names) for mask in _ordered_masks(maximal, names)]


def _family_digest(family: MaskFamily, names: Sequence[str]) -> str:
    return digest_json(_maxima(family, names))


def _support(family: MaskFamily) -> Mask:
    support = 0
    for mask in family:
        support |= mask
    return support


def _parse_receipt(raw: Any, path: str) -> _ReceiptRow:
    record = expect_object(raw, path)
    expect_exact_keys(
        record,
        (
            "receipt",
            "authority",
            "atom",
            "cell_anchor",
            "epoch",
            "operation",
            "effect_digest",
            "phase",
        ),
        (),
        path,
    )
    phase = expect_string(record["phase"], f"{path}.phase")
    if phase not in _PHASE_ORDER:
        raise SchemaError(f"{path}.phase must be prepared or settled")
    return _ReceiptRow(
        receipt=expect_string(record["receipt"], f"{path}.receipt"),
        authority=expect_string(record["authority"], f"{path}.authority"),
        atom=expect_string(record["atom"], f"{path}.atom"),
        cell_anchor=expect_string(record["cell_anchor"], f"{path}.cell_anchor"),
        epoch=expect_string(record["epoch"], f"{path}.epoch"),
        operation=expect_string(record["operation"], f"{path}.operation"),
        effect_digest=expect_string(
            record["effect_digest"], f"{path}.effect_digest"
        ),
        phase=phase,
    )


def _parse_receipt_set(
    raw: Any,
    authority_id: str,
    atoms: set[str],
    path: str,
) -> dict[str, _ReceiptRow]:
    receipts: dict[str, _ReceiptRow] = {}
    owner_by_atom: dict[str, str] = {}
    for index, item in enumerate(expect_list(raw, path)):
        receipt = _parse_receipt(item, f"{path}[{index}]")
        if receipt.receipt in receipts:
            raise SchemaError(f"{path} repeats receipt ID {receipt.receipt!r}")
        if receipt.authority != authority_id:
            raise SchemaError(
                f"{path}[{index}] belongs to {receipt.authority!r}, "
                f"not {authority_id!r}"
            )
        if receipt.atom not in atoms:
            raise SchemaError(
                f"{path}[{index}] names undeclared atom {receipt.atom!r}"
            )
        previous = owner_by_atom.get(receipt.atom)
        if previous is not None:
            raise SchemaError(
                f"{path} binds atom {receipt.atom!r} to two receipts: "
                f"{previous!r} and {receipt.receipt!r}"
            )
        receipts[receipt.receipt] = receipt
        owner_by_atom[receipt.atom] = receipt.receipt
    return receipts


def _parse_occurrence_ref(
    raw: Any,
    roles: tuple[str, ...],
    path: str,
) -> OccurrenceRef:
    record = expect_object(raw, path)
    expect_exact_keys(record, ("role", "local_id"), (), path)
    role = expect_string(record["role"], f"{path}.role")
    local_id = expect_string(record["local_id"], f"{path}.local_id")
    if role not in roles:
        raise SchemaError(f"{path}.role is not valid for this operator: {role!r}")
    return (role, local_id)


def _occurrence_key(ref: OccurrenceRef) -> str:
    return f"{ref[0]}/{quote(ref[1], safe='')}"


def _standalone_cell_id(ref: OccurrenceRef) -> str:
    return f"occ:{ref[0]}:{quote(ref[1], safe='')}"


def _normalize_cells(
    occurrences: Mapping[OccurrenceRef, _OccurrenceRow],
    aliases_raw: Any,
    roles: tuple[str, ...],
) -> tuple[
    dict[OccurrenceRef, str],
    dict[str, _NormalizedCellRow],
    tuple[dict[str, Any], ...],
]:
    membership: dict[OccurrenceRef, str] = {}
    groups: list[tuple[str, tuple[OccurrenceRef, ...], str]] = []
    alias_ids: set[str] = set()

    for index, raw_alias in enumerate(
        expect_list(aliases_raw, "$.operation.aliases")
    ):
        path = f"$.operation.aliases[{index}]"
        alias = expect_object(raw_alias, path)
        expect_exact_keys(alias, ("id", "members", "evidence"), (), path)
        alias_id = expect_string(alias["id"], f"{path}.id")
        if alias_id in alias_ids:
            raise SchemaError(f"duplicate alias ID: {alias_id!r}")
        alias_ids.add(alias_id)
        refs = tuple(
            _parse_occurrence_ref(item, roles, f"{path}.members[{member_index}]")
            for member_index, item in enumerate(
                expect_list(alias["members"], f"{path}.members")
            )
        )
        if len(refs) < 2 or len(set(refs)) != len(refs):
            raise SchemaError(
                f"{path}.members must contain at least two unique occurrences"
            )
        for ref in refs:
            if ref not in occurrences:
                raise SchemaError(
                    f"{path} references unknown occurrence {_occurrence_key(ref)!r}"
                )
            if ref in membership:
                raise SchemaError(
                    f"occurrence {_occurrence_key(ref)!r} belongs to multiple aliases"
                )
            membership[ref] = alias_id

        evidence = expect_object(alias["evidence"], f"{path}.evidence")
        expect_exact_keys(evidence, ("kind", "value"), (), f"{path}.evidence")
        evidence_kind = expect_string(evidence["kind"], f"{path}.evidence.kind")
        evidence_value = expect_string(
            evidence["value"], f"{path}.evidence.value"
        )
        if evidence_kind != "stable_cell_anchor":
            raise SchemaError(f"{path}.evidence.kind must be stable_cell_anchor")

        members = [occurrences[ref] for ref in refs]
        identities = {
            (
                member.atom,
                member.commitment_key,
                member.effect_binding_digest,
                member.anchor,
            )
            for member in members
        }
        if len(identities) != 1:
            raise SchemaError(
                f"{path} aliases occurrences with different atom, commitment key, "
                "effect binding, or cell anchor"
            )
        if members[0].anchor != evidence_value:
            raise SchemaError(
                f"{path}.evidence.value does not match the stable cell anchor"
            )
        groups.append((alias_id, tuple(sorted(refs)), evidence_value))

    refs_by_anchor: dict[str, set[OccurrenceRef]] = {}
    for ref, occurrence in occurrences.items():
        refs_by_anchor.setdefault(occurrence.anchor, set()).add(ref)
    for anchor, refs in refs_by_anchor.items():
        if len(refs) < 2:
            continue
        group_ids = {membership.get(ref) for ref in refs}
        if None in group_ids or len(group_ids) != 1:
            rendered = ", ".join(sorted(_occurrence_key(ref) for ref in refs))
            raise SchemaError(
                f"stable cell anchor {anchor!r} is reused without one complete alias: "
                f"{rendered}"
            )
        group_id = next(iter(group_ids))
        declared = {
            ref
            for candidate_id, candidate_refs, _ in groups
            if candidate_id == group_id
            for ref in candidate_refs
        }
        if declared != refs:
            raise SchemaError(
                f"alias {group_id!r} does not cover its entire stable cell anchor"
            )

    occurrence_to_cell: dict[OccurrenceRef, str] = {}
    alias_output: list[dict[str, Any]] = []
    for alias_id, refs, anchor in sorted(groups):
        representative = occurrences[refs[0]]
        binding = {
            "members": [_occurrence_key(ref) for ref in refs],
            "atom": representative.atom,
            "commitment_key": representative.commitment_key,
            "effect_binding_digest": representative.effect_binding_digest,
            "cell_anchor": anchor,
        }
        normalized_id = "alias:" + digest_json(binding).split(":", 1)[1]
        for ref in refs:
            occurrence_to_cell[ref] = normalized_id
        alias_output.append(
            {
                "id": alias_id,
                "normalized_cell": normalized_id,
                **binding,
            }
        )
    for ref in sorted(occurrences):
        occurrence_to_cell.setdefault(ref, _standalone_cell_id(ref))

    grouped: dict[str, list[_OccurrenceRow]] = {}
    for ref, cell_id in occurrence_to_cell.items():
        grouped.setdefault(cell_id, []).append(occurrences[ref])
    normalized: dict[str, _NormalizedCellRow] = {}
    for cell_id, members in grouped.items():
        representative = members[0]
        parent_candidates = tuple(
            sorted({member.parent for member in members if member.parent is not None})
        )
        has_unparented = any(member.parent is None for member in members)
        lease_candidates = tuple(
            sorted({member.lease for member in members if member.lease is not None})
        )
        has_unleased = any(member.lease is None for member in members)
        normalized[cell_id] = _NormalizedCellRow(
            atom=representative.atom,
            commitment_key=representative.commitment_key,
            effect_binding_digest=representative.effect_binding_digest,
            anchor=representative.anchor,
            parent=(
                parent_candidates[0]
                if len(parent_candidates) == 1 and not has_unparented
                else None
            ),
            parent_candidates=parent_candidates,
            has_unparented_occurrence=has_unparented,
            lease=(
                lease_candidates[0]
                if len(lease_candidates) == 1 and not has_unleased
                else None
            ),
            lease_candidates=lease_candidates,
            has_unleased_occurrence=has_unleased,
            occurrences=tuple(sorted(member.ref for member in members)),
        )
    if len(normalized) > MAX_TARGET_CELLS:
        raise SchemaError(f"target has more than {MAX_TARGET_CELLS} normalized cells")
    return occurrence_to_cell, normalized, tuple(alias_output)


def _remap_local_family(
    family: MaskFamily,
    local_names: Sequence[str],
    role: str,
    occurrence_to_cell: Mapping[OccurrenceRef, str],
    target_positions: Mapping[str, int],
) -> MaskFamily:
    remapped: set[Mask] = set()
    for local_mask in family:
        target_mask = 0
        for local_index, local_id in enumerate(local_names):
            if local_mask & (1 << local_index):
                cell_id = occurrence_to_cell[(role, local_id)]
                target_mask |= 1 << target_positions[cell_id]
        remapped.add(target_mask)
    return frozenset(remapped)


def _parse_reference_family(
    raw: Any,
    roles: tuple[str, ...],
    occurrences: Mapping[OccurrenceRef, _OccurrenceRow],
    occurrence_to_cell: Mapping[OccurrenceRef, str],
    target_positions: Mapping[str, int],
    path: str,
) -> MaskFamily:
    maxima: list[Mask] = []
    for config_index, raw_config in enumerate(expect_list(raw, path)):
        refs = tuple(
            _parse_occurrence_ref(
                item, roles, f"{path}[{config_index}][{member_index}]"
            )
            for member_index, item in enumerate(
                expect_list(raw_config, f"{path}[{config_index}]")
            )
        )
        if len(set(refs)) != len(refs):
            raise SchemaError(f"{path}[{config_index}] repeats an occurrence")
        mask = 0
        for ref in refs:
            if ref not in occurrences:
                raise SchemaError(
                    f"{path}[{config_index}] references unknown occurrence "
                    f"{_occurrence_key(ref)!r}"
                )
            mask |= 1 << target_positions[occurrence_to_cell[ref]]
        maxima.append(mask)
    return _closure(maxima, path)


def _parse_controllers(
    gate_uses_raw: Any,
    future_raw: Any,
    roles: tuple[str, ...],
    occurrences: Mapping[OccurrenceRef, _OccurrenceRow],
    occurrence_to_cell: Mapping[OccurrenceRef, str],
    target_positions: Mapping[str, int],
) -> tuple[tuple[str, ...], dict[str, _ControllerRow], MaskFamily]:
    controllers: dict[str, _ControllerRow] = {}
    use_ids: set[str] = set()
    gate_uses = expect_list(gate_uses_raw, "$.operation.gate_uses")
    if len(gate_uses) > MAX_GATE_USES:
        raise SchemaError(f"operation has more than {MAX_GATE_USES} gate uses")
    for index, raw_use in enumerate(gate_uses):
        path = f"$.operation.gate_uses[{index}]"
        use = expect_object(raw_use, path)
        expect_exact_keys(
            use,
            (
                "id",
                "gate_origin",
                "controller_anchor",
                "controller_version",
                "members",
                "local_maxima",
            ),
            (),
            path,
        )
        use_id = expect_string(use["id"], f"{path}.id")
        if use_id in use_ids:
            raise SchemaError(f"duplicate gate-use ID: {use_id!r}")
        use_ids.add(use_id)
        origin = expect_string(use["gate_origin"], f"{path}.gate_origin")
        anchor = expect_string(
            use["controller_anchor"], f"{path}.controller_anchor"
        )
        version = expect_nonnegative_int(
            use["controller_version"], f"{path}.controller_version"
        )
        members = tuple(
            _parse_occurrence_ref(item, roles, f"{path}.members[{member_index}]")
            for member_index, item in enumerate(
                expect_list(use["members"], f"{path}.members")
            )
        )
        if not members or len(set(members)) != len(members):
            raise SchemaError(f"{path}.members must be nonempty and unique")
        member_mask = 0
        for ref in members:
            if ref not in occurrences:
                raise SchemaError(
                    f"{path} references unknown occurrence {_occurrence_key(ref)!r}"
                )
            member_mask |= 1 << target_positions[occurrence_to_cell[ref]]
        local_family = _parse_reference_family(
            use["local_maxima"],
            roles,
            occurrences,
            occurrence_to_cell,
            target_positions,
            f"{path}.local_maxima",
        )
        if _support(local_family) != member_mask:
            raise SchemaError(
                f"{path}.members must exactly equal local-family support"
            )
        candidate = _ControllerRow(origin, version, local_family, (use_id,))
        previous = controllers.get(anchor)
        if previous is None:
            controllers[anchor] = candidate
        else:
            if (
                previous.origin != origin
                or previous.version != version
                or previous.local_family != local_family
            ):
                raise SchemaError(
                    f"gate uses sharing controller anchor {anchor!r} disagree on "
                    "origin, version, or normalized local family"
                )
            controllers[anchor] = _ControllerRow(
                origin,
                version,
                local_family,
                tuple(sorted((*previous.use_ids, use_id))),
            )
    if len(controllers) > MAX_CONTROLLERS:
        raise SchemaError(
            f"operation has more than {MAX_CONTROLLERS} controllers"
        )
    controller_names = tuple(sorted(controllers))
    controller_future = _parse_named_family(
        future_raw,
        controller_names,
        "$.operation.controller_future_maxima",
    )
    if _support(controller_future) != (1 << len(controller_names)) - 1:
        raise SchemaError(
            "$.operation.controller_future_maxima must cover every declared "
            "controller anchor"
        )
    return controller_names, controllers, controller_future


def _obstructions(
    authority: MaskFamily,
    atom_positions: Mapping[str, int],
    durable: Mask,
    config: Mask,
    cell_names: Sequence[str],
    cell_atoms: Mapping[str, str],
) -> list[dict[str, Any]]:
    cells_by_atom: dict[str, list[str]] = {}
    for cell in _mask_members(config, cell_names):
        cells_by_atom.setdefault(cell_atoms[cell], []).append(cell)
    reasons: list[dict[str, Any]] = []
    replayed = sorted(
        atom
        for atom in cells_by_atom
        if durable & (1 << atom_positions[atom])
    )
    reasons.extend({"kind": "PrefixReplay", "atom": atom} for atom in replayed)
    for atom, cells in sorted(cells_by_atom.items()):
        if len(cells) > 1:
            reasons.append(
                {
                    "kind": "LineageCollision",
                    "atom": atom,
                    "cells": sorted(cells),
                }
            )
    image = 0
    for atom in cells_by_atom:
        image |= 1 << atom_positions[atom]
    combined = durable | image
    if combined not in authority:
        atom_names = tuple(sorted(atom_positions, key=atom_positions.get))
        reasons.append(
            {
                "kind": "ForbiddenUnion",
                "durable_atoms": _mask_members(durable, atom_names),
                "future_atoms": _mask_members(image, atom_names),
                "combined_atoms": _mask_members(combined, atom_names),
            }
        )
    return reasons


def _parse_request(document: Any) -> _RequestModel:
    raw = expect_object(document, "$")
    expect_exact_keys(
        raw,
        ("schema", "request_id", "authority", "source", "ledger", "operation"),
        (),
        "$",
    )
    if expect_string(raw["schema"], "$.schema") != REQUEST_SCHEMA:
        raise SchemaError(f"$.schema must be {REQUEST_SCHEMA!r}")
    request_id = expect_string(raw["request_id"], "$.request_id")

    authority_object = expect_object(raw["authority"], "$.authority")
    expect_exact_keys(
        authority_object,
        ("id", "atoms", "allowed_maxima"),
        (),
        "$.authority",
    )
    authority_id = expect_string(authority_object["id"], "$.authority.id")
    declared_atoms = unique_strings(
        authority_object["atoms"], "$.authority.atoms", allow_empty=False
    )
    if len(declared_atoms) > MAX_ATOMS:
        raise SchemaError(f"authority has more than {MAX_ATOMS} atoms")
    atom_names = tuple(sorted(declared_atoms))
    atom_positions = _indices(atom_names)
    authority = _parse_named_family(
        authority_object["allowed_maxima"],
        atom_names,
        "$.authority.allowed_maxima",
    )

    source_object = expect_object(raw["source"], "$.source")
    expect_exact_keys(
        source_object,
        ("version", "cells", "future_maxima", "receipt_frontier", "leases"),
        (),
        "$.source",
    )
    source_version = expect_nonnegative_int(
        source_object["version"], "$.source.version"
    )
    source_cells: dict[str, _SourceCellRow] = {}
    source_anchors: set[str] = set()
    for index, raw_cell in enumerate(
        expect_list(source_object["cells"], "$.source.cells")
    ):
        path = f"$.source.cells[{index}]"
        cell = expect_object(raw_cell, path)
        expect_exact_keys(cell, ("id", "atom", "cell_anchor"), (), path)
        cell_id = expect_string(cell["id"], f"{path}.id")
        atom = expect_string(cell["atom"], f"{path}.atom")
        anchor = expect_string(cell["cell_anchor"], f"{path}.cell_anchor")
        if cell_id in source_cells:
            raise SchemaError(f"duplicate source cell ID {cell_id!r}")
        if anchor in source_anchors:
            raise SchemaError(
                f"source repeats stable semantic cell anchor {anchor!r}"
            )
        if atom not in atom_positions:
            raise SchemaError(f"{path}.atom is undeclared: {atom!r}")
        source_cells[cell_id] = _SourceCellRow(atom, anchor)
        source_anchors.add(anchor)
    if not source_cells or len(source_cells) > MAX_SOURCE_CELLS:
        raise SchemaError(
            f"source must declare between 1 and {MAX_SOURCE_CELLS} cells"
        )
    source_names = tuple(sorted(source_cells))
    source_future = _parse_named_family(
        source_object["future_maxima"],
        source_names,
        "$.source.future_maxima",
    )
    if _support(source_future) != (1 << len(source_names)) - 1:
        raise SchemaError(
            "$.source.cells must exactly equal the active future support"
        )

    source_receipts = _parse_receipt_set(
        source_object["receipt_frontier"],
        authority_id,
        set(atom_names),
        "$.source.receipt_frontier",
    )
    ledger_receipts = _parse_receipt_set(
        raw["ledger"], authority_id, set(atom_names), "$.ledger"
    )
    for receipt_id, old in source_receipts.items():
        current = ledger_receipts.get(receipt_id)
        if current is None:
            raise SchemaError(f"current ledger dropped source receipt {receipt_id!r}")
        if current.binding() != old.binding():
            raise SchemaError(f"current ledger rebound source receipt {receipt_id!r}")
        if _PHASE_ORDER[current.phase] < _PHASE_ORDER[old.phase]:
            raise SchemaError(
                f"current ledger regressed source receipt {receipt_id!r}"
            )
    source_durable = 0
    for receipt in source_receipts.values():
        source_durable |= 1 << atom_positions[receipt.atom]
    current_durable = 0
    for receipt in ledger_receipts.values():
        current_durable |= 1 << atom_positions[receipt.atom]
    if source_durable not in authority:
        raise SchemaError(
            "source durable receipt prefix is outside the authority family"
        )
    if current_durable not in authority:
        raise SchemaError(
            "current durable receipt prefix is outside the authority family"
        )

    leases: dict[str, _LeaseRow] = {}
    for index, raw_lease in enumerate(
        expect_list(source_object["leases"], "$.source.leases")
    ):
        path = f"$.source.leases[{index}]"
        lease = expect_object(raw_lease, path)
        expect_exact_keys(lease, ("id", "issued_version", "cell", "atom"), (), path)
        lease_id = expect_string(lease["id"], f"{path}.id")
        issued_version = expect_nonnegative_int(
            lease["issued_version"], f"{path}.issued_version"
        )
        source_cell = expect_string(lease["cell"], f"{path}.cell")
        atom = expect_string(lease["atom"], f"{path}.atom")
        if lease_id in leases:
            raise SchemaError(f"duplicate source lease ID {lease_id!r}")
        if source_cell not in source_cells:
            raise SchemaError(f"{path}.cell is undeclared: {source_cell!r}")
        if atom != source_cells[source_cell].atom:
            raise SchemaError(f"{path}.atom does not match source cell lineage")
        if issued_version > source_version:
            raise SchemaError(
                f"{path}.issued_version is newer than the source envelope"
            )
        leases[lease_id] = _LeaseRow(issued_version, source_cell, atom)

    source_atoms = {cell: row.atom for cell, row in source_cells.items()}
    for config in source_future:
        reasons = _obstructions(
            authority,
            atom_positions,
            source_durable,
            config,
            source_names,
            source_atoms,
        )
        if reasons:
            kinds = ", ".join(reason["kind"] for reason in reasons)
            raise SchemaError(
                f"source envelope is not admitted: configuration "
                f"{_mask_members(config, source_names)!r}: {kinds}"
            )

    operation = expect_object(raw["operation"], "$.operation")
    kind = expect_string(operation.get("kind"), "$.operation.kind")
    roles = _OPERATOR_ROLES.get(kind)
    if roles is None:
        raise SchemaError(f"unknown operation kind: {kind!r}")
    expect_exact_keys(
        operation,
        {
            "kind",
            "target_version",
            "aliases",
            "gate_uses",
            "controller_future_maxima",
            "controller_future_coverage",
            *roles,
        },
        (),
        "$.operation",
    )
    target_version = expect_nonnegative_int(
        operation["target_version"], "$.operation.target_version"
    )
    controller_future_coverage = expect_string(
        operation["controller_future_coverage"],
        "$.operation.controller_future_coverage",
    )
    if controller_future_coverage not in {"exact", "sound_overapprox"}:
        raise SchemaError(
            "$.operation.controller_future_coverage must be exact or "
            "sound_overapprox"
        )

    occurrences: dict[OccurrenceRef, _OccurrenceRow] = {}
    role_coverage: dict[str, str] = {}
    raw_role_may: dict[str, tuple[tuple[str, ...], MaskFamily]] = {}
    raw_role_required: dict[str, tuple[tuple[str, ...], MaskFamily]] = {}
    for role in roles:
        path = f"$.operation.{role}"
        arm = expect_object(operation[role], path)
        expect_exact_keys(
            arm,
            ("coverage", "cells", "may_maxima", "required_maxima"),
            (),
            path,
        )
        coverage = expect_string(arm["coverage"], f"{path}.coverage")
        if coverage not in {"exact", "sound_overapprox"}:
            raise SchemaError(
                f"{path}.coverage must be exact or sound_overapprox"
            )
        role_coverage[role] = coverage
        local_cells: dict[str, _OccurrenceRow] = {}
        for index, raw_cell in enumerate(
            expect_list(arm["cells"], f"{path}.cells")
        ):
            cell_path = f"{path}.cells[{index}]"
            cell = expect_object(raw_cell, cell_path)
            expect_exact_keys(
                cell,
                (
                    "local_id",
                    "atom",
                    "commitment_key",
                    "effect_binding_digest",
                    "cell_anchor",
                    "parent",
                    "lease",
                ),
                (),
                cell_path,
            )
            local_id = expect_string(cell["local_id"], f"{cell_path}.local_id")
            if local_id in local_cells:
                raise SchemaError(f"{path} repeats local cell ID {local_id!r}")
            atom = expect_string(cell["atom"], f"{cell_path}.atom")
            if atom not in atom_positions:
                raise SchemaError(f"{cell_path}.atom is undeclared: {atom!r}")
            parent = expect_optional_string(cell["parent"], f"{cell_path}.parent")
            lease = expect_optional_string(cell["lease"], f"{cell_path}.lease")
            if parent is not None and parent not in source_cells:
                raise SchemaError(f"{cell_path}.parent is undeclared: {parent!r}")
            if lease is not None and lease not in leases:
                raise SchemaError(f"{cell_path}.lease is undeclared: {lease!r}")
            occurrence = _OccurrenceRow(
                role=role,
                local_id=local_id,
                atom=atom,
                commitment_key=expect_string(
                    cell["commitment_key"], f"{cell_path}.commitment_key"
                ),
                effect_binding_digest=expect_string(
                    cell["effect_binding_digest"],
                    f"{cell_path}.effect_binding_digest",
                ),
                anchor=expect_string(
                    cell["cell_anchor"], f"{cell_path}.cell_anchor"
                ),
                parent=parent,
                lease=lease,
            )
            local_cells[local_id] = occurrence
            occurrences[occurrence.ref] = occurrence
            if len(occurrences) > MAX_OCCURRENCES:
                raise SchemaError(
                    f"operation has more than {MAX_OCCURRENCES} arm-tagged occurrences"
                )
        if not local_cells:
            raise SchemaError(f"{path}.cells must be nonempty")
        local_names = tuple(sorted(local_cells))
        may = _parse_named_family(
            arm["may_maxima"], local_names, f"{path}.may_maxima"
        )
        required = _parse_named_family(
            arm["required_maxima"], local_names, f"{path}.required_maxima"
        )
        if _support(may) != (1 << len(local_names)) - 1:
            raise SchemaError(f"{path}.cells must exactly equal may-family support")
        if not required <= may:
            raise SchemaError(f"{path}.required family is not a subset of may")
        raw_role_may[role] = (local_names, may)
        raw_role_required[role] = (local_names, required)

    occurrence_to_cell, normalized_cells, alias_groups = _normalize_cells(
        occurrences, operation["aliases"], roles
    )
    target_names = tuple(sorted(normalized_cells))
    target_positions = _indices(target_names)
    role_may: dict[str, MaskFamily] = {}
    role_required: dict[str, MaskFamily] = {}
    for role in roles:
        local_names, may = raw_role_may[role]
        _, required = raw_role_required[role]
        role_may[role] = _remap_local_family(
            may,
            local_names,
            role,
            occurrence_to_cell,
            target_positions,
        )
        role_required[role] = _remap_local_family(
            required,
            local_names,
            role,
            occurrence_to_cell,
            target_positions,
        )

    controller_names, controllers, controller_future = _parse_controllers(
        operation["gate_uses"],
        operation["controller_future_maxima"],
        roles,
        occurrences,
        occurrence_to_cell,
        target_positions,
    )
    return _RequestModel(
        raw=raw,
        request_id=request_id,
        authority_id=authority_id,
        atom_names=atom_names,
        authority=authority,
        source_version=source_version,
        source_names=source_names,
        source_cells=source_cells,
        source_future=source_future,
        source_receipts=source_receipts,
        ledger_receipts=ledger_receipts,
        source_durable=source_durable,
        current_durable=current_durable,
        leases=leases,
        operator=kind,
        target_version=target_version,
        target_names=target_names,
        role_coverage=role_coverage,
        role_may=role_may,
        role_required=role_required,
        normalized_cells=normalized_cells,
        occurrence_to_cell=occurrence_to_cell,
        alias_groups=alias_groups,
        controller_names=controller_names,
        controllers=controllers,
        controller_future=controller_future,
        controller_future_coverage=controller_future_coverage,
    )


def _tensor(left: MaskFamily, right: MaskFamily, path: str) -> MaskFamily:
    result: set[Mask] = set()
    for left_mask in left:
        for right_mask in right:
            result.add(left_mask | right_mask)
            if len(result) > MAX_EXPANDED_CONFIGURATIONS:
                raise SchemaError(
                    f"{path} expands past {MAX_EXPANDED_CONFIGURATIONS} configurations"
                )
    return frozenset(result)


def _operator_family(model: _RequestModel, *, required: bool) -> MaskFamily:
    arms = model.role_required if required else model.role_may
    roles = _OPERATOR_ROLES[model.operator]
    if model.operator == "RestoreReplace":
        return arms["checkpoint"]
    left, right = arms[roles[0]], arms[roles[1]]
    if model.operator in _CHOICE_KINDS:
        return left | right
    if model.operator in _TENSOR_KINDS:
        return _tensor(left, right, f"$.operation.{model.operator}")
    raise AssertionError(model.operator)


def _safe_family(
    model: _RequestModel,
    candidate: MaskFamily,
) -> tuple[MaskFamily, dict[Mask, list[dict[str, Any]]]]:
    cell_atoms = {
        cell_id: cell.atom for cell_id, cell in model.normalized_cells.items()
    }
    atom_positions = _indices(model.atom_names)
    admitted: set[Mask] = set()
    rejected: dict[Mask, list[dict[str, Any]]] = {}
    for config in candidate:
        reasons = _obstructions(
            model.authority,
            atom_positions,
            model.current_durable,
            config,
            model.target_names,
            cell_atoms,
        )
        if reasons:
            rejected[config] = reasons
        else:
            admitted.add(config)
    return frozenset(admitted), rejected


def _inheritance(
    model: _RequestModel,
    candidate: MaskFamily,
) -> tuple[bool, dict[str, Any]]:
    if model.current_durable != model.source_durable:
        return False, {
            "status": "unavailable",
            "reason": {
                "kind": "PrefixGrew",
                "source": _mask_members(model.source_durable, model.atom_names),
                "current": _mask_members(model.current_durable, model.atom_names),
            },
        }
    if model.target_version < model.source_version:
        return False, {
            "status": "unavailable",
            "reason": {
                "kind": "VersionNotMonotone",
                "source": model.source_version,
                "target": model.target_version,
            },
        }
    parent_map: dict[str, str] = {}
    for cell_id in model.target_names:
        cell = model.normalized_cells[cell_id]
        if cell.parent is None:
            if len(cell.parent_candidates) > 1:
                reason = {
                    "kind": "ParentAmbiguous",
                    "cell": cell_id,
                    "candidates": list(cell.parent_candidates),
                    "has_unparented_occurrence": cell.has_unparented_occurrence,
                }
            else:
                reason = {
                    "kind": "ParentMissing",
                    "cell": cell_id,
                    "candidates": list(cell.parent_candidates),
                }
            return False, {
                "status": "unavailable",
                "reason": reason,
            }
        parent_map[cell_id] = cell.parent
        parent_atom = model.source_cells[cell.parent].atom
        if parent_atom != cell.atom:
            return False, {
                "status": "unavailable",
                "reason": {
                    "kind": "LineageDoesNotCommute",
                    "cell": cell_id,
                    "target_atom": cell.atom,
                    "parent": cell.parent,
                    "parent_atom": parent_atom,
                },
            }

    source_positions = _indices(model.source_names)
    for config in _ordered_masks(candidate, model.target_names):
        target_cells = _mask_members(config, model.target_names)
        parents = [parent_map[cell] for cell in target_cells]
        if len(set(parents)) != len(parents):
            return False, {
                "status": "unavailable",
                "reason": {
                    "kind": "ParentCollision",
                    "configuration": target_cells,
                    "parents": sorted(parents),
                },
            }
        parent_image = 0
        for parent in parents:
            parent_image |= 1 << source_positions[parent]
        if parent_image not in model.source_future:
            return False, {
                "status": "unavailable",
                "reason": {
                    "kind": "ParentImageForbidden",
                    "configuration": target_cells,
                    "parent_image": _mask_members(
                        parent_image, model.source_names
                    ),
                },
            }
    return True, {
        "status": "available",
        "source_version": model.source_version,
        "target_version": model.target_version,
        "durable_atoms": _mask_members(model.current_durable, model.atom_names),
        "parent_map": dict(sorted(parent_map.items())),
    }


def _minimal_nonfaces(family: MaskFamily, names: Sequence[str]) -> list[Mask]:
    support = _support(family)
    support_indices = [
        index for index in range(len(names)) if support & (1 << index)
    ]
    result: list[Mask] = []
    for size in range(2, len(support_indices) + 1):
        for member_indices in combinations(support_indices, size):
            candidate = 0
            for index in member_indices:
                candidate |= 1 << index
            if candidate in family:
                continue
            if all(candidate ^ (1 << index) in family for index in member_indices):
                result.append(candidate)
    return _ordered_masks(result, names)


def _required_coliveness_arity(
    required: MaskFamily, admitted: MaskFamily, cell_count: int
) -> int:
    """Independently compute the contract-only observation upper bound."""

    required_arity = max((mask.bit_count() for mask in required), default=0)
    names = tuple(str(index) for index in range(cell_count))
    obstruction_arity = max(
        (mask.bit_count() for mask in _minimal_nonfaces(admitted, names)),
        default=0,
    )
    universe = (1 << cell_count) - 1
    outside_arity = 1 if universe & ~_support(admitted) else 0
    return max(required_arity, obstruction_arity, outside_arity)


def _components(family: MaskFamily, names: Sequence[str]) -> list[list[str]]:
    support = _support(family)
    adjacency: dict[int, set[int]] = {
        index: set()
        for index in range(len(names))
        if support & (1 << index)
    }
    for nonface in _minimal_nonfaces(family, names):
        vertices = [
            index for index in range(len(names)) if nonface & (1 << index)
        ]
        for left in vertices:
            adjacency[left].update(right for right in vertices if right != left)

    components: list[list[str]] = []
    remaining = set(adjacency)
    while remaining:
        root = min(remaining)
        pending = [root]
        reached: set[int] = set()
        while pending:
            current = pending.pop()
            if current in reached:
                continue
            reached.add(current)
            pending.extend(sorted(adjacency[current] - reached, reverse=True))
        remaining -= reached
        components.append([names[index] for index in sorted(reached)])
    return sorted(components, key=lambda component: (component[0], len(component)))


def _controller_product(
    model: _RequestModel,
) -> tuple[MaskFamily, dict[Mask, dict[str, Any]]]:
    physical: set[Mask] = set()
    witnesses: dict[Mask, dict[str, Any]] = {}
    product_states = 0
    for controller_mask in _ordered_masks(
        model.controller_future, model.controller_names
    ):
        live = _mask_members(controller_mask, model.controller_names)
        partial: dict[Mask, dict[str, Mask]] = {0: {}}
        for anchor in live:
            next_partial: dict[Mask, dict[str, Mask]] = {}
            controller = model.controllers[anchor]
            for accumulated, choices in sorted(
                partial.items(),
                key=lambda item: _mask_key(item[0], model.target_names),
            ):
                for local in _ordered_masks(
                    controller.local_family, model.target_names
                ):
                    product_states += 1
                    if product_states > MAX_PRODUCT_STATES:
                        raise SchemaError(
                            f"controller product exceeds {MAX_PRODUCT_STATES} states"
                        )
                    combined = accumulated | local
                    if combined not in next_partial:
                        next_partial[combined] = {**choices, anchor: local}
            partial = next_partial
        for config, choices in partial.items():
            physical.add(config)
            if config not in witnesses:
                witnesses[config] = {
                    "co_live_controllers": live,
                    "local_choices": {
                        anchor: _mask_members(local, model.target_names)
                        for anchor, local in sorted(choices.items())
                    },
                }
            if len(physical) > MAX_EXPANDED_CONFIGURATIONS:
                raise SchemaError(
                    "physical controller family exceeds finite configuration cap"
                )
    return frozenset(physical), witnesses


def _minimal_covering_controllers(
    target: Mask,
    local_choices: Mapping[str, list[str]],
    names: Sequence[str],
) -> list[str]:
    """Independently compute a deterministic inclusion-minimal cover."""

    positions = _indices(names)

    def choice_mask(anchor: str) -> Mask:
        mask = 0
        for name in local_choices[anchor]:
            mask |= 1 << positions[name]
        return mask

    chosen = sorted(
        anchor for anchor in local_choices if choice_mask(anchor) & target
    )
    for anchor in reversed(chosen.copy()):
        covered = 0
        for candidate in chosen:
            if candidate != anchor:
                covered |= choice_mask(candidate) & target
        if target & ~covered == 0:
            chosen.remove(anchor)
    return chosen


def _coordination(
    model: _RequestModel,
    admitted: MaskFamily | None,
    required: MaskFamily,
) -> dict[str, Any]:
    if admitted is None:
        return {
            "status": "not_applicable",
            "required_covered": None,
            "admitted_respected": None,
            "exact_fidelity": None,
            "target_maxima": None,
            "physical_maxima": [[]],
            "minimal_nonfaces": [],
            "components": [],
            "witness": None,
        }

    physical, product_witnesses = _controller_product(model)
    nonfaces = _minimal_nonfaces(admitted, model.target_names)
    components = _components(admitted, model.target_names)
    extra = physical - admitted
    missing = admitted - physical
    missing_required = required - physical
    if not extra and not missing:
        return {
            "status": "exact",
            "required_covered": True,
            "admitted_respected": True,
            "exact_fidelity": True,
            "target_maxima": _maxima(admitted, model.target_names),
            "physical_maxima": _maxima(physical, model.target_names),
            "minimal_nonfaces": [
                _mask_members(nonface, model.target_names) for nonface in nonfaces
            ],
            "components": components,
            "witness": None,
        }

    if not extra and not missing_required:
        configuration = _ordered_masks(missing, model.target_names)[0]
        return {
            "status": "safe_restriction",
            "required_covered": True,
            "admitted_respected": True,
            "exact_fidelity": False,
            "target_maxima": _maxima(admitted, model.target_names),
            "physical_maxima": _maxima(physical, model.target_names),
            "minimal_nonfaces": [
                _mask_members(nonface, model.target_names) for nonface in nonfaces
            ],
            "components": components,
            "witness": {
                "kind": "OptionalBehaviorRestricted",
                "missing_configuration": _mask_members(
                    configuration, model.target_names
                ),
            },
        }

    if extra:
        configuration = _ordered_masks(extra, model.target_names)[0]
        product_witness = product_witnesses[configuration]
        support = _support(admitted)
        outside = configuration & ~support
        if outside:
            cell_mask = outside & -outside
            cell = _mask_members(cell_mask, model.target_names)[0]
            anchor = next(
                anchor
                for anchor, local in sorted(
                    product_witness["local_choices"].items()
                )
                if cell in local
            )
            witness = {
                "kind": "OutsideSupport",
                "failure_class": "OutsideSupport",
                "forbidden_configuration": [cell],
                "outside_support_cells": [cell],
                "co_live_controllers": [anchor],
                "local_choices": {anchor: [cell]},
                "gate_origins": {anchor: model.controllers[anchor].origin},
            }
        else:
            contained = [
                nonface for nonface in nonfaces if nonface & ~configuration == 0
            ]
            if not contained:
                raise SchemaError(
                    "internal error: unsupported controller configuration has "
                    "neither an outside-support cell nor a minimal nonface"
                )
            minimal = _ordered_masks(contained, model.target_names)[0]
            positions = _indices(model.target_names)

            def local_mask(anchor: str) -> Mask:
                mask = 0
                for name in product_witness["local_choices"][anchor]:
                    mask |= 1 << positions[name]
                return mask

            locally_unsafe = [
                anchor
                for anchor in sorted(product_witness["local_choices"])
                if local_mask(anchor) not in admitted
            ]
            if locally_unsafe:
                anchor = locally_unsafe[0]
                local = local_mask(anchor)
                local_nonfaces = [
                    nonface for nonface in nonfaces if nonface & ~local == 0
                ]
                if not local_nonfaces:
                    raise SchemaError(
                        "internal error: locally unsafe controller choice has "
                        "no minimal nonface"
                    )
                local_minimal = _ordered_masks(
                    local_nonfaces, model.target_names
                )[0]
                members = _mask_members(local_minimal, model.target_names)
                witness = {
                    "kind": "ControllerOverpermit",
                    "failure_class": "LocalOverpermission",
                    "forbidden_configuration": members,
                    "minimal_nonface": members,
                    "offending_controller": anchor,
                    "co_live_controllers": [anchor],
                    "local_choices": {anchor: members},
                    "gate_origins": {
                        anchor: model.controllers[anchor].origin
                    },
                }
            else:
                used = _minimal_covering_controllers(
                    minimal,
                    product_witness["local_choices"],
                    model.target_names,
                )
                if len(used) < 2:
                    raise SchemaError(
                        "internal error: a locally sound product minimal "
                        "nonface is not split across controllers"
                    )
                origins = {model.controllers[anchor].origin for anchor in used}
                kind = "GateClone" if len(origins) == 1 else "GateCut"
                minimal_members = set(
                    _mask_members(minimal, model.target_names)
                )
                witness = {
                    "kind": kind,
                    "failure_class": "CorrelationCut",
                    "forbidden_configuration": sorted(minimal_members),
                    "minimal_nonface": sorted(minimal_members),
                    "co_live_controllers": used,
                    "local_choices": {
                        anchor: sorted(
                            set(product_witness["local_choices"][anchor])
                            & minimal_members
                        )
                        for anchor in used
                    },
                    "gate_origins": {
                        anchor: model.controllers[anchor].origin
                        for anchor in used
                    },
                }
    else:
        configuration = _ordered_masks(missing_required, model.target_names)[0]
        witness = {
            "kind": "MissingRequiredBehavior",
            "required_configuration": _mask_members(
                configuration, model.target_names
            ),
        }
    return {
        "status": (
            "unsafe_and_incomplete"
            if extra and missing_required
            else "unsafe_overapprox"
            if extra
            else "missing_required"
        ),
        "required_covered": not missing_required,
        "admitted_respected": not extra,
        "exact_fidelity": False,
        "target_maxima": _maxima(admitted, model.target_names),
        "physical_maxima": _maxima(physical, model.target_names),
        "minimal_nonfaces": [
            _mask_members(nonface, model.target_names) for nonface in nonfaces
        ],
        "components": components,
        "witness": witness,
    }


def _lease_results(model: _RequestModel, semantic_class: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for lease_id, lease in sorted(model.leases.items()):
        targets = sorted(
            cell_id
            for cell_id, cell in model.normalized_cells.items()
            if cell.lease == lease_id
            and cell.parent == lease.cell
            and cell.atom == lease.atom
        )
        results.append(
            {
                "lease": lease_id,
                "issued_version": lease.issued_version,
                "source_cell": lease.cell,
                "atom": lease.atom,
                "decision": (
                    "inherited"
                    if semantic_class == "Inherit" and targets
                    else "revalidate"
                ),
                "target_cells": targets,
            }
        )
    return results


def _expected_result(document: Any) -> dict[str, Any]:
    model = _parse_request(document)
    candidate = _operator_family(model, required=False)
    required = _operator_family(model, required=True)
    if not required <= candidate:
        raise SchemaError("generated required family is not a subset of candidate")
    safe, obstructions = _safe_family(model, candidate)
    can_inherit, inheritance = _inheritance(model, candidate)

    pruning_witness: dict[str, Any] | None = None
    rejection_witness: dict[str, Any] | None = None
    if can_inherit:
        semantic_class = "Inherit"
        admitted: MaskFamily | None = candidate
        family_name: str | None = "candidate"
    elif safe == candidate:
        semantic_class = "ReadmitOK"
        admitted = candidate
        family_name = "candidate"
    elif required <= safe:
        semantic_class = "NeedsMechanism"
        admitted = safe
        family_name = "safeFuture"
        pruned = _ordered_masks(candidate - safe, model.target_names)[0]
        pruning_witness = {
            "kind": "OptionalConfigurationPruned",
            "configuration": _mask_members(pruned, model.target_names),
            "reasons": obstructions[pruned],
        }
    else:
        semantic_class = "Reject"
        admitted = None
        family_name = None
        rejected = _ordered_masks(required - safe, model.target_names)[0]
        rejection_witness = {
            "kind": "RequiredConfigurationRejected",
            "configuration": _mask_members(rejected, model.target_names),
            "reasons": obstructions[rejected],
        }

    coordination = _coordination(model, admitted, required)
    coordination["required_coliveness_arity"] = (
        None
        if admitted is None
        else _required_coliveness_arity(
            required, admitted, len(model.target_names)
        )
    )
    restriction_required = semantic_class == "NeedsMechanism"
    controllers_exact = coordination["status"] in {"exact", "safe_restriction"}
    if semantic_class == "Reject":
        readiness = "NotApplicable"
    elif restriction_required and controllers_exact:
        readiness = "ReadyWithRestriction"
    elif restriction_required:
        readiness = "NeedsRestrictionAndCoordination"
    elif controllers_exact:
        readiness = "Ready"
    else:
        readiness = "NeedsCoordination"
    structurally_eligible = semantic_class != "Reject" and controllers_exact
    external_obligations = [
        "atomic_redemption",
        "complete_mediation",
        "controller_coliveness_coverage_attestation",
        "controller_installation_and_freshness",
        "manifest_ledger_and_receipt_authenticity",
        "runtime_required_coverage",
        "runtime_soundness_against_declared_physical_family",
    ]
    if semantic_class in {"ReadmitOK", "NeedsMechanism"}:
        external_obligations.append("fresh_authority_issuance")

    normalized_cells_output = {
        cell_id: {
            "atom": cell.atom,
            "commitment_key": cell.commitment_key,
            "effect_binding_digest": cell.effect_binding_digest,
            "cell_anchor": cell.anchor,
            "parent": cell.parent,
            "parent_candidates": list(cell.parent_candidates),
            "has_unparented_occurrence": cell.has_unparented_occurrence,
            "lease": cell.lease,
            "lease_candidates": list(cell.lease_candidates),
            "has_unleased_occurrence": cell.has_unleased_occurrence,
            "occurrences": [_occurrence_key(ref) for ref in cell.occurrences],
        }
        for cell_id, cell in sorted(model.normalized_cells.items())
    }
    controllers_output = {
        anchor: {
            "gate_origin": controller.origin,
            "version": controller.version,
            "local_maxima": _maxima(controller.local_family, model.target_names),
            "gate_uses": list(controller.use_ids),
        }
        for anchor, controller in sorted(model.controllers.items())
    }
    lease_results = _lease_results(model, semantic_class)
    if any(item["decision"] == "revalidate" for item in lease_results):
        external_obligations.append("lease_revalidation")
    return {
        "schema": RESULT_SCHEMA,
        "request_id": model.request_id,
        "request_digest": digest_json(model.raw),
        "normalization": {
            "occurrence_to_cell": {
                _occurrence_key(ref): cell_id
                for ref, cell_id in sorted(model.occurrence_to_cell.items())
            },
            "cells": normalized_cells_output,
            "alias_groups": list(model.alias_groups),
        },
        "frontier": {
            "authority": model.authority_id,
            "authority_maxima": _maxima(model.authority, model.atom_names),
            "source_durable_atoms": _mask_members(
                model.source_durable, model.atom_names
            ),
            "current_durable_atoms": _mask_members(
                model.current_durable, model.atom_names
            ),
            "source_receipt_digest": digest_json(
                [receipt.as_json() for receipt in model.source_receipts.values()]
            ),
            "current_ledger_digest": digest_json(
                [receipt.as_json() for receipt in model.ledger_receipts.values()]
            ),
        },
        "operator": {
            "kind": model.operator,
            "coverage_by_role": dict(sorted(model.role_coverage.items())),
            "analysis_precision": (
                "exact"
                if all(value == "exact" for value in model.role_coverage.values())
                else "conservative_overapprox"
            ),
            "candidate_maxima": _maxima(candidate, model.target_names),
            "candidate_digest": _family_digest(candidate, model.target_names),
            "required_maxima": _maxima(required, model.target_names),
            "required_digest": _family_digest(required, model.target_names),
            "safe_maxima": _maxima(safe, model.target_names),
            "safe_digest": _family_digest(safe, model.target_names),
        },
        "semantic_admission": {
            "class": semantic_class,
            "family": family_name,
            "admitted_maxima": (
                None if admitted is None else _maxima(admitted, model.target_names)
            ),
            "admitted_digest": (
                None
                if admitted is None
                else _family_digest(admitted, model.target_names)
            ),
            "inheritance": inheritance,
            "pruning_witness": pruning_witness,
            "rejection_witness": rejection_witness,
        },
        "controllers": {
            "normalized": controllers_output,
            "co_live_maxima": _maxima(
                model.controller_future, model.controller_names
            ),
            "co_live_coverage": model.controller_future_coverage,
        },
        "coordination": coordination,
        "deployment": {
            "restriction": (
                "manifest_supplied"
                if restriction_required and controllers_exact
                else "required"
                if restriction_required
                else "not_required"
            ),
            "coordination": coordination["status"],
            "readiness": readiness,
        },
        "leases": lease_results,
        "history_admission": {
            "structurally_eligible": structurally_eligible,
            "effect_authorizes": False,
            "external_obligations": external_obligations,
            "reason": (
                "history transformation is structurally admissible; the runtime "
                "must discharge external binding obligations"
                if structurally_eligible
                else "result is diagnostic or requires a transformed deployment"
            ),
        },
    }


def verify_result(request: Any, result: Any) -> dict[str, Any]:
    """Return a verification seal after independently reconstructing the result."""

    expected = _expected_result(request)
    valid = canonical_json(result) == canonical_json(expected)
    semantic_class = expected["semantic_admission"]["class"]
    readiness = expected["deployment"]["readiness"]
    structurally_admits = bool(
        valid
        and semantic_class in {"Inherit", "ReadmitOK", "NeedsMechanism"}
        and readiness in {"Ready", "ReadyWithRestriction"}
    )
    return {
        "schema": VERIFICATION_SCHEMA,
        "request_id": expected["request_id"],
        "request_digest": digest_json(request),
        "result_digest": digest_json(result),
        "valid": valid,
        "seal_kind": "history_admission" if structurally_admits else "diagnostic",
        "structurally_admits": structurally_admits,
        "effect_authorizes": False,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Independently verify a typed history-admission result."
    )
    parser.add_argument("request", help="path to history-admission request JSON")
    parser.add_argument("result", help="path to untrusted result JSON")
    parser.add_argument("--output", required=True, help="path for verification seal")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        request = load_json(args.request)
        expected = _expected_result(request)
    except SchemaError as exc:
        print(f"history-admission verifier: malformed request: {exc}", file=sys.stderr)
        return 2

    try:
        result = load_json(args.result)
    except SchemaError as exc:
        print(f"history-admission verifier: invalid result: {exc}", file=sys.stderr)
        return 3

    valid = canonical_json(result) == canonical_json(expected)
    semantic_class = expected["semantic_admission"]["class"]
    readiness = expected["deployment"]["readiness"]
    structurally_admits = bool(
        valid
        and semantic_class in {"Inherit", "ReadmitOK", "NeedsMechanism"}
        and readiness in {"Ready", "ReadyWithRestriction"}
    )
    seal = {
        "schema": VERIFICATION_SCHEMA,
        "request_id": expected["request_id"],
        "request_digest": digest_json(request),
        "result_digest": digest_json(result),
        "valid": valid,
        "seal_kind": "history_admission" if structurally_admits else "diagnostic",
        "structurally_admits": structurally_admits,
        "effect_authorizes": False,
    }
    try:
        write_json(args.output, seal)
    except OSError as exc:
        print(f"history-admission verifier: cannot write seal: {exc}", file=sys.stderr)
        return 2
    if not valid:
        print(
            "history-admission verifier: result does not exactly match the "
            "independently reconstructed result",
            file=sys.stderr,
        )
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
