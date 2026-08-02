"""Untrusted witness synthesizer for typed history admission."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from itertools import combinations, product
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
    SchemaError,
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


Config = frozenset[str]
Family = frozenset[Config]
OccurrenceRef = tuple[str, str]


OPERATOR_ROLES: dict[str, tuple[str, ...]] = {
    "ForkChoice": ("left", "right"),
    "ForkParallel": ("left", "right"),
    "RestoreReplace": ("checkpoint",),
    "RestoreLive": ("current", "checkpoint"),
    "MergeSelect": ("left", "right"),
    "MergeJoin": ("left", "right"),
}

CHOICE_OPERATORS = {"ForkChoice", "MergeSelect"}
TENSOR_OPERATORS = {"ForkParallel", "RestoreLive", "MergeJoin"}
PHASE_RANK = {"prepared": 0, "settled": 1}


@dataclass(frozen=True)
class Receipt:
    receipt: str
    authority: str
    atom: str
    cell_anchor: str
    epoch: str
    operation: str
    effect_digest: str
    phase: str

    @property
    def immutable_binding(self) -> tuple[str, ...]:
        return (
            self.authority,
            self.atom,
            self.cell_anchor,
            self.epoch,
            self.operation,
            self.effect_digest,
        )


@dataclass(frozen=True)
class SourceCell:
    cell_id: str
    atom: str
    cell_anchor: str


@dataclass(frozen=True)
class LeaseBinding:
    lease_id: str
    issued_version: int
    cell: str
    atom: str


@dataclass(frozen=True)
class Occurrence:
    role: str
    local_id: str
    atom: str
    commitment_key: str
    effect_binding_digest: str
    cell_anchor: str
    parent: str | None
    lease: str | None

    @property
    def ref(self) -> OccurrenceRef:
        return (self.role, self.local_id)


@dataclass(frozen=True)
class NormalizedCell:
    cell_id: str
    atom: str
    commitment_key: str
    effect_binding_digest: str
    cell_anchor: str
    parent: str | None
    parent_candidates: tuple[str, ...]
    has_unparented_occurrence: bool
    lease: str | None
    lease_candidates: tuple[str, ...]
    has_unleased_occurrence: bool
    occurrences: tuple[OccurrenceRef, ...]


@dataclass(frozen=True)
class Controller:
    anchor: str
    gate_origin: str
    version: int
    local_family: Family
    gate_use_ids: tuple[str, ...]


@dataclass(frozen=True)
class ParsedRequest:
    raw: dict[str, Any]
    request_id: str
    authority_id: str
    atoms: tuple[str, ...]
    authority: Family
    source_version: int
    source_cells: dict[str, SourceCell]
    source_future: Family
    source_receipts: dict[str, Receipt]
    current_receipts: dict[str, Receipt]
    source_durable: Config
    current_durable: Config
    source_leases: dict[str, LeaseBinding]
    operator: str
    target_version: int
    role_coverage: dict[str, str]
    role_may: dict[str, Family]
    role_required: dict[str, Family]
    normalized_cells: dict[str, NormalizedCell]
    occurrence_to_cell: dict[OccurrenceRef, str]
    alias_groups: tuple[dict[str, Any], ...]
    controllers: dict[str, Controller]
    controller_future: Family
    controller_future_coverage: str


def _powerset(items: Sequence[str]) -> Iterator[Config]:
    ordered = tuple(sorted(items))
    for size in range(len(ordered) + 1):
        for members in combinations(ordered, size):
            yield frozenset(members)


def _sorted_configs(family: Iterable[Config]) -> list[Config]:
    return sorted(family, key=lambda config: (len(config), tuple(sorted(config))))


def _maxima(family: Family) -> list[list[str]]:
    maximal = [
        config
        for config in family
        if not any(config < other for other in family)
    ]
    return [sorted(config) for config in _sorted_configs(maximal)]


def _family_digest(family: Family) -> str:
    return digest_json(_maxima(family))


def _downward_closure(maxima: Iterable[Config], path: str) -> Family:
    result: set[Config] = set()
    for maximal in maxima:
        result.update(_powerset(tuple(maximal)))
        if len(result) > MAX_EXPANDED_CONFIGURATIONS:
            raise SchemaError(
                f"{path} expands past {MAX_EXPANDED_CONFIGURATIONS} configurations"
            )
    if not result:
        raise SchemaError(f"{path} must contain at least one maximal configuration")
    return frozenset(result)


def _parse_maxima(
    value: Any,
    universe: set[str],
    path: str,
) -> Family:
    raw_maxima = expect_list(value, path)
    maxima: list[Config] = []
    for index, raw_config in enumerate(raw_maxima):
        members = unique_strings(raw_config, f"{path}[{index}]")
        unknown = sorted(set(members) - universe)
        if unknown:
            raise SchemaError(
                f"{path}[{index}] references undeclared values: {', '.join(unknown)}"
            )
        maxima.append(frozenset(members))
    return _downward_closure(maxima, path)


def _family_choice(left: Family, right: Family) -> Family:
    return frozenset(set(left) | set(right))


def _family_tensor(left: Family, right: Family, path: str) -> Family:
    result: set[Config] = set()
    for left_config in left:
        for right_config in right:
            result.add(left_config | right_config)
            if len(result) > MAX_EXPANDED_CONFIGURATIONS:
                raise SchemaError(
                    f"{path} expands past {MAX_EXPANDED_CONFIGURATIONS} configurations"
                )
    return frozenset(result)


def _support(family: Family) -> Config:
    support: set[str] = set()
    for config in family:
        support.update(config)
    return frozenset(support)


def _parse_receipt(raw: Any, path: str) -> Receipt:
    obj = expect_object(raw, path)
    expect_exact_keys(
        obj,
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
    phase = expect_string(obj["phase"], f"{path}.phase")
    if phase not in PHASE_RANK:
        raise SchemaError(f"{path}.phase must be prepared or settled")
    return Receipt(
        receipt=expect_string(obj["receipt"], f"{path}.receipt"),
        authority=expect_string(obj["authority"], f"{path}.authority"),
        atom=expect_string(obj["atom"], f"{path}.atom"),
        cell_anchor=expect_string(obj["cell_anchor"], f"{path}.cell_anchor"),
        epoch=expect_string(obj["epoch"], f"{path}.epoch"),
        operation=expect_string(obj["operation"], f"{path}.operation"),
        effect_digest=expect_string(
            obj["effect_digest"], f"{path}.effect_digest"
        ),
        phase=phase,
    )


def _parse_receipts(
    raw: Any,
    authority_id: str,
    atoms: set[str],
    path: str,
) -> dict[str, Receipt]:
    result: dict[str, Receipt] = {}
    atom_owner: dict[str, str] = {}
    for index, item in enumerate(expect_list(raw, path)):
        receipt = _parse_receipt(item, f"{path}[{index}]")
        if receipt.receipt in result:
            raise SchemaError(f"{path} repeats receipt ID {receipt.receipt!r}")
        if receipt.authority != authority_id:
            raise SchemaError(
                f"{path}[{index}] belongs to {receipt.authority!r}, not {authority_id!r}"
            )
        if receipt.atom not in atoms:
            raise SchemaError(f"{path}[{index}] names undeclared atom {receipt.atom!r}")
        previous = atom_owner.get(receipt.atom)
        if previous is not None:
            raise SchemaError(
                f"{path} binds atom {receipt.atom!r} to two receipts: "
                f"{previous!r} and {receipt.receipt!r}"
            )
        result[receipt.receipt] = receipt
        atom_owner[receipt.atom] = receipt.receipt
    return result


def _parse_occurrence_ref(
    raw: Any,
    roles: tuple[str, ...],
    path: str,
) -> OccurrenceRef:
    obj = expect_object(raw, path)
    expect_exact_keys(obj, ("role", "local_id"), (), path)
    role = expect_string(obj["role"], f"{path}.role")
    local_id = expect_string(obj["local_id"], f"{path}.local_id")
    if role not in roles:
        raise SchemaError(f"{path}.role is not valid for this operator: {role!r}")
    return (role, local_id)


def _occurrence_key(ref: OccurrenceRef) -> str:
    return f"{ref[0]}/{quote(ref[1], safe='')}"


def _independent_cell_id(ref: OccurrenceRef) -> str:
    return f"occ:{ref[0]}:{quote(ref[1], safe='')}"


def _normalize_occurrences(
    occurrences: dict[OccurrenceRef, Occurrence],
    aliases_raw: Any,
    roles: tuple[str, ...],
) -> tuple[
    dict[OccurrenceRef, str],
    dict[str, NormalizedCell],
    tuple[dict[str, Any], ...],
]:
    alias_objects = expect_list(aliases_raw, "$.operation.aliases")
    occurrence_group: dict[OccurrenceRef, str] = {}
    parsed_groups: list[tuple[str, tuple[OccurrenceRef, ...], str]] = []
    alias_ids: set[str] = set()

    for index, raw_group in enumerate(alias_objects):
        path = f"$.operation.aliases[{index}]"
        group = expect_object(raw_group, path)
        expect_exact_keys(group, ("id", "members", "evidence"), (), path)
        alias_id = expect_string(group["id"], f"{path}.id")
        if alias_id in alias_ids:
            raise SchemaError(f"duplicate alias ID: {alias_id!r}")
        alias_ids.add(alias_id)
        refs = tuple(
            _parse_occurrence_ref(item, roles, f"{path}.members[{member_index}]")
            for member_index, item in enumerate(
                expect_list(group["members"], f"{path}.members")
            )
        )
        if len(refs) < 2 or len(set(refs)) != len(refs):
            raise SchemaError(f"{path}.members must contain at least two unique occurrences")
        for ref in refs:
            if ref not in occurrences:
                raise SchemaError(f"{path} references unknown occurrence {_occurrence_key(ref)!r}")
            if ref in occurrence_group:
                raise SchemaError(
                    f"occurrence {_occurrence_key(ref)!r} belongs to multiple aliases"
                )
            occurrence_group[ref] = alias_id

        evidence = expect_object(group["evidence"], f"{path}.evidence")
        expect_exact_keys(evidence, ("kind", "value"), (), f"{path}.evidence")
        kind = expect_string(evidence["kind"], f"{path}.evidence.kind")
        value = expect_string(evidence["value"], f"{path}.evidence.value")
        if kind != "stable_cell_anchor":
            raise SchemaError(f"{path}.evidence.kind must be stable_cell_anchor")

        members = [occurrences[ref] for ref in refs]
        identity_rows = {
            (
                member.atom,
                member.commitment_key,
                member.effect_binding_digest,
                member.cell_anchor,
            )
            for member in members
        }
        if len(identity_rows) != 1:
            raise SchemaError(
                f"{path} aliases occurrences with different atom, commitment key, "
                "effect binding, or cell anchor"
            )
        if members[0].cell_anchor != value:
            raise SchemaError(f"{path}.evidence.value does not match the stable cell anchor")
        parsed_groups.append((alias_id, tuple(sorted(refs)), value))

    by_anchor: dict[str, set[OccurrenceRef]] = {}
    for ref, occurrence in occurrences.items():
        by_anchor.setdefault(occurrence.cell_anchor, set()).add(ref)
    for anchor, refs in by_anchor.items():
        if len(refs) <= 1:
            continue
        groups = {occurrence_group.get(ref) for ref in refs}
        if None in groups or len(groups) != 1:
            rendered = ", ".join(sorted(_occurrence_key(ref) for ref in refs))
            raise SchemaError(
                f"stable cell anchor {anchor!r} is reused without one complete alias: {rendered}"
            )
        group_id = next(iter(groups))
        declared = {
            ref
            for alias_id, members, _ in parsed_groups
            if alias_id == group_id
            for ref in members
        }
        if declared != refs:
            raise SchemaError(f"alias {group_id!r} does not cover its entire stable cell anchor")

    occurrence_to_cell: dict[OccurrenceRef, str] = {}
    alias_output: list[dict[str, Any]] = []
    for alias_id, refs, anchor in sorted(parsed_groups):
        member = occurrences[refs[0]]
        binding = {
            "members": [_occurrence_key(ref) for ref in refs],
            "atom": member.atom,
            "commitment_key": member.commitment_key,
            "effect_binding_digest": member.effect_binding_digest,
            "cell_anchor": anchor,
        }
        cell_id = "alias:" + digest_json(binding).split(":", 1)[1]
        for ref in refs:
            occurrence_to_cell[ref] = cell_id
        alias_output.append(
            {
                "id": alias_id,
                "normalized_cell": cell_id,
                **binding,
            }
        )

    for ref in sorted(occurrences):
        occurrence_to_cell.setdefault(ref, _independent_cell_id(ref))

    grouped: dict[str, list[Occurrence]] = {}
    for ref, cell_id in occurrence_to_cell.items():
        grouped.setdefault(cell_id, []).append(occurrences[ref])

    normalized: dict[str, NormalizedCell] = {}
    for cell_id, members in grouped.items():
        first = members[0]
        parent_candidates = tuple(
            sorted({member.parent for member in members if member.parent is not None})
        )
        has_unparented = any(member.parent is None for member in members)
        lease_candidates = tuple(
            sorted({member.lease for member in members if member.lease is not None})
        )
        has_unleased = any(member.lease is None for member in members)
        normalized[cell_id] = NormalizedCell(
            cell_id=cell_id,
            atom=first.atom,
            commitment_key=first.commitment_key,
            effect_binding_digest=first.effect_binding_digest,
            cell_anchor=first.cell_anchor,
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


def _remap_family(family: Family, mapping: Mapping[str, str]) -> Family:
    return frozenset(
        frozenset(mapping[member] for member in config)
        for config in family
    )


def _parse_request(document: Any) -> ParsedRequest:
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

    authority_obj = expect_object(raw["authority"], "$.authority")
    expect_exact_keys(authority_obj, ("id", "atoms", "allowed_maxima"), (), "$.authority")
    authority_id = expect_string(authority_obj["id"], "$.authority.id")
    atoms = unique_strings(authority_obj["atoms"], "$.authority.atoms", allow_empty=False)
    if len(atoms) > MAX_ATOMS:
        raise SchemaError(f"authority has more than {MAX_ATOMS} atoms")
    atom_set = set(atoms)
    authority = _parse_maxima(
        authority_obj["allowed_maxima"], atom_set, "$.authority.allowed_maxima"
    )

    source_obj = expect_object(raw["source"], "$.source")
    expect_exact_keys(
        source_obj,
        ("version", "cells", "future_maxima", "receipt_frontier", "leases"),
        (),
        "$.source",
    )
    source_version = expect_nonnegative_int(source_obj["version"], "$.source.version")
    source_cells: dict[str, SourceCell] = {}
    source_anchors: set[str] = set()
    for index, raw_cell in enumerate(expect_list(source_obj["cells"], "$.source.cells")):
        path = f"$.source.cells[{index}]"
        cell = expect_object(raw_cell, path)
        expect_exact_keys(cell, ("id", "atom", "cell_anchor"), (), path)
        cell_id = expect_string(cell["id"], f"{path}.id")
        atom = expect_string(cell["atom"], f"{path}.atom")
        anchor = expect_string(cell["cell_anchor"], f"{path}.cell_anchor")
        if cell_id in source_cells:
            raise SchemaError(f"duplicate source cell ID {cell_id!r}")
        if anchor in source_anchors:
            raise SchemaError(f"source repeats stable semantic cell anchor {anchor!r}")
        if atom not in atom_set:
            raise SchemaError(f"{path}.atom is undeclared: {atom!r}")
        source_cells[cell_id] = SourceCell(cell_id, atom, anchor)
        source_anchors.add(anchor)
    if not source_cells or len(source_cells) > MAX_SOURCE_CELLS:
        raise SchemaError(
            f"source must declare between 1 and {MAX_SOURCE_CELLS} cells"
        )
    source_future = _parse_maxima(
        source_obj["future_maxima"],
        set(source_cells),
        "$.source.future_maxima",
    )
    if _support(source_future) != frozenset(source_cells):
        raise SchemaError("$.source.cells must exactly equal the active future support")

    source_receipts = _parse_receipts(
        source_obj["receipt_frontier"],
        authority_id,
        atom_set,
        "$.source.receipt_frontier",
    )
    current_receipts = _parse_receipts(
        raw["ledger"], authority_id, atom_set, "$.ledger"
    )
    for receipt_id, old in source_receipts.items():
        current = current_receipts.get(receipt_id)
        if current is None:
            raise SchemaError(f"current ledger dropped source receipt {receipt_id!r}")
        if current.immutable_binding != old.immutable_binding:
            raise SchemaError(f"current ledger rebound source receipt {receipt_id!r}")
        if PHASE_RANK[current.phase] < PHASE_RANK[old.phase]:
            raise SchemaError(f"current ledger regressed source receipt {receipt_id!r}")
    source_durable = frozenset(receipt.atom for receipt in source_receipts.values())
    current_durable = frozenset(receipt.atom for receipt in current_receipts.values())
    if source_durable not in authority:
        raise SchemaError("source durable receipt prefix is outside the authority family")
    if current_durable not in authority:
        raise SchemaError("current durable receipt prefix is outside the authority family")

    source_leases: dict[str, LeaseBinding] = {}
    for index, raw_lease in enumerate(expect_list(source_obj["leases"], "$.source.leases")):
        path = f"$.source.leases[{index}]"
        lease = expect_object(raw_lease, path)
        expect_exact_keys(lease, ("id", "issued_version", "cell", "atom"), (), path)
        lease_id = expect_string(lease["id"], f"{path}.id")
        issued_version = expect_nonnegative_int(
            lease["issued_version"], f"{path}.issued_version"
        )
        cell_id = expect_string(lease["cell"], f"{path}.cell")
        atom = expect_string(lease["atom"], f"{path}.atom")
        if lease_id in source_leases:
            raise SchemaError(f"duplicate source lease ID {lease_id!r}")
        if cell_id not in source_cells:
            raise SchemaError(f"{path}.cell is undeclared: {cell_id!r}")
        if atom != source_cells[cell_id].atom:
            raise SchemaError(f"{path}.atom does not match source cell lineage")
        if issued_version > source_version:
            raise SchemaError(f"{path}.issued_version is newer than the source envelope")
        source_leases[lease_id] = LeaseBinding(
            lease_id, issued_version, cell_id, atom
        )

    source_lineage = {cell_id: cell.atom for cell_id, cell in source_cells.items()}
    for config in source_future:
        reasons = _config_obstructions(
            authority, source_durable, config, source_lineage
        )
        if reasons:
            raise SchemaError(
                "source envelope is not admitted: "
                + _render_obstruction(config, reasons)
            )

    operation_obj = expect_object(raw["operation"], "$.operation")
    kind = expect_string(operation_obj.get("kind"), "$.operation.kind")
    roles = OPERATOR_ROLES.get(kind)
    if roles is None:
        raise SchemaError(f"unknown operation kind: {kind!r}")
    operation_required = {
        "kind",
        "target_version",
        "aliases",
        "gate_uses",
        "controller_future_maxima",
        "controller_future_coverage",
        *roles,
    }
    expect_exact_keys(operation_obj, operation_required, (), "$.operation")
    target_version = expect_nonnegative_int(
        operation_obj["target_version"], "$.operation.target_version"
    )
    controller_future_coverage = expect_string(
        operation_obj["controller_future_coverage"],
        "$.operation.controller_future_coverage",
    )
    if controller_future_coverage not in {"exact", "sound_overapprox"}:
        raise SchemaError(
            "$.operation.controller_future_coverage must be exact or "
            "sound_overapprox"
        )

    occurrences: dict[OccurrenceRef, Occurrence] = {}
    role_coverage: dict[str, str] = {}
    raw_role_may: dict[str, Family] = {}
    raw_role_required: dict[str, Family] = {}
    for role in roles:
        path = f"$.operation.{role}"
        arm = expect_object(operation_obj[role], path)
        expect_exact_keys(
            arm,
            ("coverage", "cells", "may_maxima", "required_maxima"),
            (),
            path,
        )
        coverage = expect_string(arm["coverage"], f"{path}.coverage")
        if coverage not in {"exact", "sound_overapprox"}:
            raise SchemaError(f"{path}.coverage must be exact or sound_overapprox")
        role_coverage[role] = coverage
        local_cells: set[str] = set()
        for index, raw_cell in enumerate(expect_list(arm["cells"], f"{path}.cells")):
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
            if atom not in atom_set:
                raise SchemaError(f"{cell_path}.atom is undeclared: {atom!r}")
            parent = expect_optional_string(cell["parent"], f"{cell_path}.parent")
            lease = expect_optional_string(cell["lease"], f"{cell_path}.lease")
            if parent is not None and parent not in source_cells:
                raise SchemaError(f"{cell_path}.parent is undeclared: {parent!r}")
            if lease is not None and lease not in source_leases:
                raise SchemaError(f"{cell_path}.lease is undeclared: {lease!r}")
            occurrence = Occurrence(
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
                cell_anchor=expect_string(
                    cell["cell_anchor"], f"{cell_path}.cell_anchor"
                ),
                parent=parent,
                lease=lease,
            )
            occurrences[occurrence.ref] = occurrence
            local_cells.add(local_id)
            if len(occurrences) > MAX_OCCURRENCES:
                raise SchemaError(
                    f"operation has more than {MAX_OCCURRENCES} arm-tagged occurrences"
                )
        if not local_cells:
            raise SchemaError(f"{path}.cells must be nonempty")
        may = _parse_maxima(arm["may_maxima"], local_cells, f"{path}.may_maxima")
        required = _parse_maxima(
            arm["required_maxima"], local_cells, f"{path}.required_maxima"
        )
        if _support(may) != frozenset(local_cells):
            raise SchemaError(f"{path}.cells must exactly equal may-family support")
        if not required <= may:
            raise SchemaError(f"{path}.required family is not a subset of may")
        raw_role_may[role] = may
        raw_role_required[role] = required

    occurrence_to_cell, normalized_cells, alias_groups = _normalize_occurrences(
        occurrences, operation_obj["aliases"], roles
    )
    role_may: dict[str, Family] = {}
    role_required: dict[str, Family] = {}
    for role in roles:
        role_mapping = {
            local_id: occurrence_to_cell[(role, local_id)]
            for candidate_role, local_id in occurrences
            if candidate_role == role
        }
        role_may[role] = _remap_family(raw_role_may[role], role_mapping)
        role_required[role] = _remap_family(
            raw_role_required[role], role_mapping
        )

    controllers = _parse_controllers(
        operation_obj["gate_uses"],
        operation_obj["controller_future_maxima"],
        roles,
        occurrences,
        occurrence_to_cell,
    )
    controller_future = controllers[1]

    return ParsedRequest(
        raw=raw,
        request_id=request_id,
        authority_id=authority_id,
        atoms=atoms,
        authority=authority,
        source_version=source_version,
        source_cells=source_cells,
        source_future=source_future,
        source_receipts=source_receipts,
        current_receipts=current_receipts,
        source_durable=source_durable,
        current_durable=current_durable,
        source_leases=source_leases,
        operator=kind,
        target_version=target_version,
        role_coverage=role_coverage,
        role_may=role_may,
        role_required=role_required,
        normalized_cells=normalized_cells,
        occurrence_to_cell=occurrence_to_cell,
        alias_groups=alias_groups,
        controllers=controllers[0],
        controller_future=controller_future,
        controller_future_coverage=controller_future_coverage,
    )


def _parse_ref_family(
    raw: Any,
    roles: tuple[str, ...],
    occurrences: Mapping[OccurrenceRef, Occurrence],
    occurrence_to_cell: Mapping[OccurrenceRef, str],
    path: str,
) -> Family:
    raw_maxima = expect_list(raw, path)
    maxima: list[Config] = []
    for index, raw_config in enumerate(raw_maxima):
        refs = [
            _parse_occurrence_ref(item, roles, f"{path}[{index}][{member_index}]")
            for member_index, item in enumerate(
                expect_list(raw_config, f"{path}[{index}]")
            )
        ]
        if len(set(refs)) != len(refs):
            raise SchemaError(f"{path}[{index}] repeats an occurrence")
        for ref in refs:
            if ref not in occurrences:
                raise SchemaError(
                    f"{path}[{index}] references unknown occurrence {_occurrence_key(ref)!r}"
                )
        maxima.append(frozenset(occurrence_to_cell[ref] for ref in refs))
    return _downward_closure(maxima, path)


def _parse_controllers(
    gate_uses_raw: Any,
    future_raw: Any,
    roles: tuple[str, ...],
    occurrences: Mapping[OccurrenceRef, Occurrence],
    occurrence_to_cell: Mapping[OccurrenceRef, str],
) -> tuple[dict[str, Controller], Family]:
    controllers: dict[str, Controller] = {}
    gate_use_ids: set[str] = set()
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
        if use_id in gate_use_ids:
            raise SchemaError(f"duplicate gate-use ID: {use_id!r}")
        gate_use_ids.add(use_id)
        origin = expect_string(use["gate_origin"], f"{path}.gate_origin")
        anchor = expect_string(use["controller_anchor"], f"{path}.controller_anchor")
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
        for ref in members:
            if ref not in occurrences:
                raise SchemaError(f"{path} references unknown occurrence {_occurrence_key(ref)!r}")
        local_family = _parse_ref_family(
            use["local_maxima"],
            roles,
            occurrences,
            occurrence_to_cell,
            f"{path}.local_maxima",
        )
        member_cells = frozenset(occurrence_to_cell[ref] for ref in members)
        if _support(local_family) != member_cells:
            raise SchemaError(f"{path}.members must exactly equal local-family support")
        candidate = Controller(anchor, origin, version, local_family, (use_id,))
        previous = controllers.get(anchor)
        if previous is None:
            controllers[anchor] = candidate
        else:
            if (
                previous.gate_origin != origin
                or previous.version != version
                or previous.local_family != local_family
            ):
                raise SchemaError(
                    f"gate uses sharing controller anchor {anchor!r} disagree on origin, "
                    "version, or normalized local family"
                )
            controllers[anchor] = Controller(
                anchor,
                origin,
                version,
                local_family,
                tuple(sorted((*previous.gate_use_ids, use_id))),
            )
    if len(controllers) > MAX_CONTROLLERS:
        raise SchemaError(f"operation has more than {MAX_CONTROLLERS} controllers")
    future = _parse_maxima(
        future_raw,
        set(controllers),
        "$.operation.controller_future_maxima",
    )
    if _support(future) != frozenset(controllers):
        raise SchemaError(
            "$.operation.controller_future_maxima must cover every declared "
            "controller anchor"
        )
    return controllers, future


def _derive_operator_family(parsed: ParsedRequest, required: bool) -> Family:
    families = parsed.role_required if required else parsed.role_may
    roles = OPERATOR_ROLES[parsed.operator]
    if parsed.operator == "RestoreReplace":
        return families["checkpoint"]
    left = families[roles[0]]
    right = families[roles[1]]
    if parsed.operator in CHOICE_OPERATORS:
        return _family_choice(left, right)
    if parsed.operator in TENSOR_OPERATORS:
        return _family_tensor(left, right, f"$.operation.{parsed.operator}")
    raise AssertionError(parsed.operator)


def _config_obstructions(
    authority: Family,
    durable: Config,
    config: Config,
    lineage: Mapping[str, str],
) -> list[dict[str, Any]]:
    by_atom: dict[str, list[str]] = {}
    for cell in config:
        by_atom.setdefault(lineage[cell], []).append(cell)
    reasons: list[dict[str, Any]] = []
    replayed = sorted(atom for atom in by_atom if atom in durable)
    for atom in replayed:
        reasons.append({"kind": "PrefixReplay", "atom": atom})
    for atom, cells in sorted(by_atom.items()):
        if len(cells) > 1:
            reasons.append(
                {
                    "kind": "LineageCollision",
                    "atom": atom,
                    "cells": sorted(cells),
                }
            )
    image = frozenset(by_atom)
    combined = durable | image
    if combined not in authority:
        reasons.append(
            {
                "kind": "ForbiddenUnion",
                "durable_atoms": sorted(durable),
                "future_atoms": sorted(image),
                "combined_atoms": sorted(combined),
            }
        )
    return reasons


def _render_obstruction(config: Config, reasons: list[dict[str, Any]]) -> str:
    kinds = ", ".join(reason["kind"] for reason in reasons)
    return f"configuration {sorted(config)!r}: {kinds}"


def _safe_future(
    authority: Family,
    durable: Config,
    candidate: Family,
    lineage: Mapping[str, str],
) -> tuple[Family, dict[Config, list[dict[str, Any]]]]:
    safe: set[Config] = set()
    obstructions: dict[Config, list[dict[str, Any]]] = {}
    for config in candidate:
        reasons = _config_obstructions(authority, durable, config, lineage)
        if reasons:
            obstructions[config] = reasons
        else:
            safe.add(config)
    return frozenset(safe), obstructions


def _inheritance(
    parsed: ParsedRequest,
    candidate: Family,
) -> tuple[bool, dict[str, Any]]:
    if parsed.current_durable != parsed.source_durable:
        return False, {
            "status": "unavailable",
            "reason": {
                "kind": "PrefixGrew",
                "source": sorted(parsed.source_durable),
                "current": sorted(parsed.current_durable),
            },
        }
    if parsed.target_version < parsed.source_version:
        return False, {
            "status": "unavailable",
            "reason": {
                "kind": "VersionNotMonotone",
                "source": parsed.source_version,
                "target": parsed.target_version,
            },
        }
    parent_map: dict[str, str] = {}
    for cell_id, cell in sorted(parsed.normalized_cells.items()):
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
        source_atom = parsed.source_cells[cell.parent].atom
        if source_atom != cell.atom:
            return False, {
                "status": "unavailable",
                "reason": {
                    "kind": "LineageDoesNotCommute",
                    "cell": cell_id,
                    "target_atom": cell.atom,
                    "parent": cell.parent,
                    "parent_atom": source_atom,
                },
            }
    for config in _sorted_configs(candidate):
        parents = [parent_map[cell] for cell in config]
        if len(set(parents)) != len(parents):
            return False, {
                "status": "unavailable",
                "reason": {
                    "kind": "ParentCollision",
                    "configuration": sorted(config),
                    "parents": sorted(parents),
                },
            }
        image = frozenset(parents)
        if image not in parsed.source_future:
            return False, {
                "status": "unavailable",
                "reason": {
                    "kind": "ParentImageForbidden",
                    "configuration": sorted(config),
                    "parent_image": sorted(image),
                },
            }
    return True, {
        "status": "available",
        "source_version": parsed.source_version,
        "target_version": parsed.target_version,
        "durable_atoms": sorted(parsed.current_durable),
        "parent_map": dict(sorted(parent_map.items())),
    }


def _minimal_nonfaces(family: Family) -> list[Config]:
    support = tuple(sorted(_support(family)))
    result: list[Config] = []
    for candidate in _powerset(support):
        if len(candidate) < 2 or candidate in family:
            continue
        if all(candidate - {cell} in family for cell in candidate):
            result.append(candidate)
    return _sorted_configs(result)


def _required_coliveness_arity(
    required: Family, admitted: Family, universe: Iterable[str]
) -> int:
    """Compute the contract-only co-liveness observation upper bound."""

    required_arity = max((len(config) for config in required), default=0)
    obstruction_arity = max(
        (len(config) for config in _minimal_nonfaces(admitted)), default=0
    )
    outside_arity = 1 if set(universe) - _support(admitted) else 0
    return max(required_arity, obstruction_arity, outside_arity)


def _coordination_components(family: Family) -> list[list[str]]:
    support = sorted(_support(family))
    parent = {cell: cell for cell in support}

    def find(cell: str) -> str:
        while parent[cell] != cell:
            parent[cell] = parent[parent[cell]]
            cell = parent[cell]
        return cell

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    for nonface in _minimal_nonfaces(family):
        ordered = sorted(nonface)
        for cell in ordered[1:]:
            union(ordered[0], cell)
    groups: dict[str, list[str]] = {}
    for cell in support:
        groups.setdefault(find(cell), []).append(cell)
    return sorted((sorted(group) for group in groups.values()), key=lambda g: (g[0], len(g)))


def _controller_product_analysis(
    controllers: Mapping[str, Controller],
    controller_future: Family,
    admitted: Family,
) -> tuple[Family, dict[Config, dict[str, Any]], Family, Family]:
    """Enumerate the declared product and its greatest safe co-live filter once."""

    physical: set[Config] = set()
    witnesses: dict[Config, dict[str, Any]] = {}
    safe_controller_future: set[Config] = set()
    safe_physical: set[Config] = set()
    product_states = 0
    for controller_config in _sorted_configs(controller_future):
        partial: dict[Config, dict[str, Config]] = {frozenset(): {}}
        for anchor in sorted(controller_config):
            next_partial: dict[Config, dict[str, Config]] = {}
            controller = controllers[anchor]
            for accumulated, choices in sorted(
                partial.items(), key=lambda item: (len(item[0]), tuple(sorted(item[0])))
            ):
                for local in _sorted_configs(controller.local_family):
                    product_states += 1
                    if product_states > MAX_PRODUCT_STATES:
                        raise SchemaError(
                            f"controller product exceeds {MAX_PRODUCT_STATES} states"
                        )
                    combined = accumulated | local
                    next_partial.setdefault(combined, {**choices, anchor: local})
            partial = next_partial
        controller_product = frozenset(partial)
        controller_safe = controller_product <= admitted
        if controller_safe:
            safe_controller_future.add(controller_config)
            safe_physical.update(controller_product)
        for config, choices in partial.items():
            physical.add(config)
            witnesses.setdefault(
                config,
                {
                    "co_live_controllers": sorted(controller_config),
                    "local_choices": {
                        anchor: sorted(local)
                        for anchor, local in sorted(choices.items())
                    },
                },
            )
            if len(physical) > MAX_EXPANDED_CONFIGURATIONS:
                raise SchemaError(
                    "physical controller family exceeds finite configuration cap"
                )
    return (
        frozenset(physical),
        witnesses,
        frozenset(safe_controller_future),
        frozenset(safe_physical),
    )


def _coliveness_repair(
    parsed: ParsedRequest,
    required: Family,
    repaired_future: Family,
    repaired_physical: Family,
) -> dict[str, Any]:
    """Return the canonical co-liveness-only repair proposal.

    For every declared co-live controller configuration C, its independent
    local product is checked against Admitted.  Parsed local families are
    nonempty and contain the empty configuration.  Thus, for H contained in C,
    Product(H) is contained in Product(C) by assigning empty choices to the
    removed controllers.  The safe configurations therefore form the unique
    greatest downward-closed subset of declared Gamma whose physical product
    respects Admitted.  This is a proposal only: it neither mutates the
    submitted manifest nor changes deployment readiness.
    """

    if frozenset() not in repaired_future:
        raise SchemaError(
            "internal error: empty controller configuration is not repair-safe"
        )
    if any(
        subset not in repaired_future
        for config in repaired_future
        for subset in _powerset(tuple(config))
    ):
        raise SchemaError(
            "internal error: canonical co-liveness repair is not downward closed"
        )

    covered_required = required & repaired_physical
    missing_required = required - repaired_physical
    changes_coliveness = repaired_future != parsed.controller_future
    if missing_required:
        status = "infeasible"
    elif changes_coliveness:
        status = "feasible"
    else:
        status = "not_needed"

    return {
        "kind": "co_liveness_only",
        "status": status,
        "restriction_maxima": _maxima(repaired_future),
        "declared_coverage": parsed.controller_future_coverage,
        "required_coverage": {
            "scope": "declared_controller_product",
            "covered": not missing_required,
            "covered_maxima": _maxima(frozenset(covered_required)),
            "missing_required": [
                sorted(config) for config in _sorted_configs(missing_required)
            ],
        },
        "installation_required": status == "feasible",
        "effect_authorizes": False,
    }


def _minimal_covering_controllers(
    target: Config,
    local_choices: Mapping[str, list[str]],
) -> list[str]:
    """Return a deterministic inclusion-minimal controller cover of target."""

    chosen = sorted(
        anchor for anchor, local in local_choices.items() if set(local) & target
    )
    for anchor in reversed(chosen.copy()):
        without = [candidate for candidate in chosen if candidate != anchor]
        covered = set().union(
            *(set(local_choices[candidate]) & target for candidate in without)
        ) if without else set()
        if target <= covered:
            chosen.remove(anchor)
    return chosen


def _coordination_result(
    parsed: ParsedRequest,
    admitted: Family | None,
    required: Family,
    physical: Family | None,
    product_witnesses: Mapping[Config, dict[str, Any]] | None,
) -> dict[str, Any]:
    if admitted is None:
        return {
            "status": "not_applicable",
            "required_covered": None,
            "admitted_respected": None,
            "exact_fidelity": None,
            "target_maxima": None,
            "physical_maxima": _maxima(frozenset({frozenset()})),
            "minimal_nonfaces": [],
            "components": [],
            "witness": None,
        }
    if physical is None or product_witnesses is None:
        raise SchemaError("internal error: missing controller product analysis")
    nonfaces = _minimal_nonfaces(admitted)
    components = _coordination_components(admitted)
    extra = physical - admitted
    missing = admitted - physical
    missing_required = required - physical
    if not extra and not missing:
        return {
            "status": "exact",
            "required_covered": True,
            "admitted_respected": True,
            "exact_fidelity": True,
            "target_maxima": _maxima(admitted),
            "physical_maxima": _maxima(physical),
            "minimal_nonfaces": [sorted(config) for config in nonfaces],
            "components": components,
            "witness": None,
        }

    if not extra and not missing_required:
        configuration = _sorted_configs(missing)[0]
        return {
            "status": "safe_restriction",
            "required_covered": True,
            "admitted_respected": True,
            "exact_fidelity": False,
            "target_maxima": _maxima(admitted),
            "physical_maxima": _maxima(physical),
            "minimal_nonfaces": [sorted(config) for config in nonfaces],
            "components": components,
            "witness": {
                "kind": "OptionalBehaviorRestricted",
                "missing_configuration": sorted(configuration),
            },
        }

    witness: dict[str, Any]
    if extra:
        configuration = _sorted_configs(extra)[0]
        product_witness = product_witnesses[configuration]
        outside = configuration - _support(admitted)
        if outside:
            cell = sorted(outside)[0]
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
                "gate_origins": {
                    anchor: parsed.controllers[anchor].gate_origin
                },
            }
        else:
            contained = [
                nonface for nonface in nonfaces if nonface <= configuration
            ]
            if not contained:
                raise SchemaError(
                    "internal error: unsupported controller configuration has "
                    "neither an outside-support cell nor a minimal nonface"
                )
            minimal = _sorted_configs(contained)[0]
            local_choices = product_witness["local_choices"]
            locally_unsafe = [
                anchor
                for anchor, local in sorted(local_choices.items())
                if frozenset(local) not in admitted
            ]
            if locally_unsafe:
                anchor = locally_unsafe[0]
                local = frozenset(local_choices[anchor])
                local_nonfaces = [
                    nonface for nonface in nonfaces if nonface <= local
                ]
                if not local_nonfaces:
                    raise SchemaError(
                        "internal error: locally unsafe controller choice has "
                        "no minimal nonface"
                    )
                local_minimal = _sorted_configs(local_nonfaces)[0]
                witness = {
                    "kind": "ControllerOverpermit",
                    "failure_class": "LocalOverpermission",
                    "forbidden_configuration": sorted(local_minimal),
                    "minimal_nonface": sorted(local_minimal),
                    "offending_controller": anchor,
                    "co_live_controllers": [anchor],
                    "local_choices": {anchor: sorted(local_minimal)},
                    "gate_origins": {
                        anchor: parsed.controllers[anchor].gate_origin
                    },
                }
            else:
                used = _minimal_covering_controllers(minimal, local_choices)
                origins = {
                    parsed.controllers[anchor].gate_origin for anchor in used
                }
                if len(used) < 2:
                    raise SchemaError(
                        "internal error: a locally sound product minimal "
                        "nonface is not split across controllers"
                    )
                kind = "GateClone" if len(origins) == 1 else "GateCut"
                witness = {
                    "kind": kind,
                    "failure_class": "CorrelationCut",
                    "forbidden_configuration": sorted(minimal),
                    "minimal_nonface": sorted(minimal),
                    "co_live_controllers": used,
                    "local_choices": {
                        anchor: sorted(set(local_choices[anchor]) & minimal)
                        for anchor in used
                    },
                    "gate_origins": {
                        anchor: parsed.controllers[anchor].gate_origin
                        for anchor in used
                    },
                }
    else:
        configuration = _sorted_configs(missing_required)[0]
        witness = {
            "kind": "MissingRequiredBehavior",
            "required_configuration": sorted(configuration),
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
        "target_maxima": _maxima(admitted),
        "physical_maxima": _maxima(physical),
        "minimal_nonfaces": [sorted(config) for config in nonfaces],
        "components": components,
        "witness": witness,
    }


def _lease_results(parsed: ParsedRequest, semantic_class: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for lease_id, lease in sorted(parsed.source_leases.items()):
        targets = sorted(
            cell_id
            for cell_id, cell in parsed.normalized_cells.items()
            if cell.lease == lease_id
            and cell.parent == lease.cell
            and cell.atom == lease.atom
        )
        decision = "inherited" if semantic_class == "Inherit" and targets else "revalidate"
        results.append(
            {
                "lease": lease_id,
                "issued_version": lease.issued_version,
                "source_cell": lease.cell,
                "atom": lease.atom,
                "decision": decision,
                "target_cells": targets,
            }
        )
    return results


def compile_request(document: Any) -> dict[str, Any]:
    parsed = _parse_request(document)
    candidate = _derive_operator_family(parsed, required=False)
    required = _derive_operator_family(parsed, required=True)
    if not required <= candidate:
        raise SchemaError("generated required family is not a subset of candidate")
    lineage = {
        cell_id: cell.atom for cell_id, cell in parsed.normalized_cells.items()
    }
    safe, obstructions = _safe_future(
        parsed.authority, parsed.current_durable, candidate, lineage
    )
    can_inherit, inheritance = _inheritance(parsed, candidate)

    rejection_witness: dict[str, Any] | None = None
    pruning_witness: dict[str, Any] | None = None
    if can_inherit:
        semantic_class = "Inherit"
        admitted = candidate
        family_name = "candidate"
    elif safe == candidate:
        semantic_class = "ReadmitOK"
        admitted = candidate
        family_name = "candidate"
    elif required <= safe:
        semantic_class = "NeedsMechanism"
        admitted = safe
        family_name = "safeFuture"
        pruned = _sorted_configs(candidate - safe)[0]
        pruning_witness = {
            "kind": "OptionalConfigurationPruned",
            "configuration": sorted(pruned),
            "reasons": obstructions[pruned],
        }
    else:
        semantic_class = "Reject"
        admitted = None
        family_name = None
        rejected_required = _sorted_configs(required - safe)[0]
        rejection_witness = {
            "kind": "RequiredConfigurationRejected",
            "configuration": sorted(rejected_required),
            "reasons": obstructions[rejected_required],
        }

    if admitted is None:
        coordination = _coordination_result(
            parsed, admitted, required, None, None
        )
        coliveness_repair = None
    else:
        (
            physical,
            product_witnesses,
            repaired_future,
            repaired_physical,
        ) = _controller_product_analysis(
            parsed.controllers, parsed.controller_future, admitted
        )
        coordination = _coordination_result(
            parsed,
            admitted,
            required,
            physical,
            product_witnesses,
        )
        coliveness_repair = _coliveness_repair(
            parsed, required, repaired_future, repaired_physical
        )
    coordination["required_coliveness_arity"] = (
        None
        if admitted is None
        else _required_coliveness_arity(
            required, admitted, parsed.normalized_cells
        )
    )
    restriction_required = semantic_class == "NeedsMechanism"
    coordination_ready = coordination["status"] in {"exact", "safe_restriction"}
    if semantic_class == "Reject":
        readiness = "NotApplicable"
    elif restriction_required and coordination_ready:
        readiness = "ReadyWithRestriction"
    elif restriction_required:
        readiness = "NeedsRestrictionAndCoordination"
    elif coordination_ready:
        readiness = "Ready"
    else:
        readiness = "NeedsCoordination"
    structurally_eligible = semantic_class != "Reject" and coordination_ready
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
            "cell_anchor": cell.cell_anchor,
            "parent": cell.parent,
            "parent_candidates": list(cell.parent_candidates),
            "has_unparented_occurrence": cell.has_unparented_occurrence,
            "lease": cell.lease,
            "lease_candidates": list(cell.lease_candidates),
            "has_unleased_occurrence": cell.has_unleased_occurrence,
            "occurrences": [_occurrence_key(ref) for ref in cell.occurrences],
        }
        for cell_id, cell in sorted(parsed.normalized_cells.items())
    }
    controller_output = {
        anchor: {
            "gate_origin": controller.gate_origin,
            "version": controller.version,
            "local_maxima": _maxima(controller.local_family),
            "gate_uses": list(controller.gate_use_ids),
        }
        for anchor, controller in sorted(parsed.controllers.items())
    }
    lease_results = _lease_results(parsed, semantic_class)
    if any(item["decision"] == "revalidate" for item in lease_results):
        external_obligations.append("lease_revalidation")
    result = {
        "schema": RESULT_SCHEMA,
        "request_id": parsed.request_id,
        "request_digest": digest_json(parsed.raw),
        "normalization": {
            "occurrence_to_cell": {
                _occurrence_key(ref): cell_id
                for ref, cell_id in sorted(parsed.occurrence_to_cell.items())
            },
            "cells": normalized_cells_output,
            "alias_groups": list(parsed.alias_groups),
        },
        "frontier": {
            "authority": parsed.authority_id,
            "authority_maxima": _maxima(parsed.authority),
            "source_durable_atoms": sorted(parsed.source_durable),
            "current_durable_atoms": sorted(parsed.current_durable),
            "source_receipt_digest": digest_json(
                [receipt.__dict__ for receipt in parsed.source_receipts.values()]
            ),
            "current_ledger_digest": digest_json(
                [receipt.__dict__ for receipt in parsed.current_receipts.values()]
            ),
        },
        "operator": {
            "kind": parsed.operator,
            "coverage_by_role": dict(sorted(parsed.role_coverage.items())),
            "analysis_precision": (
                "exact"
                if all(value == "exact" for value in parsed.role_coverage.values())
                else "conservative_overapprox"
            ),
            "candidate_maxima": _maxima(candidate),
            "candidate_digest": _family_digest(candidate),
            "required_maxima": _maxima(required),
            "required_digest": _family_digest(required),
            "safe_maxima": _maxima(safe),
            "safe_digest": _family_digest(safe),
        },
        "semantic_admission": {
            "class": semantic_class,
            "family": family_name,
            "admitted_maxima": None if admitted is None else _maxima(admitted),
            "admitted_digest": None if admitted is None else _family_digest(admitted),
            "inheritance": inheritance,
            "pruning_witness": pruning_witness,
            "rejection_witness": rejection_witness,
        },
        "controllers": {
            "normalized": controller_output,
            "co_live_maxima": _maxima(parsed.controller_future),
            "co_live_coverage": parsed.controller_future_coverage,
        },
        "coordination": coordination,
        "co_liveness_repair": coliveness_repair,
        "deployment": {
            "restriction": (
                "manifest_supplied"
                if restriction_required and coordination_ready
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
    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compile a typed history-admission request into witnesses."
    )
    parser.add_argument("request", help="path to history-admission request JSON")
    parser.add_argument("--output", required=True, help="path for result JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        result = compile_request(load_json(args.request))
        write_json(args.output, result)
    except SchemaError as exc:
        print(f"history-admission compiler: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
