"""Executable oracle for copyable handles and non-amplifying redemption state.

This module is intentionally isolated from :mod:`adapter.plan_pilot`.  It is a
small semantic model, not a production controller.  More precisely, it is the
executable all-domains-independent/escrow profile of the larger theory: rights
are scalar, and every detached cell can redeem its escrow independently.  It
does not model conditional authority, choice incompatibility, or general
co-redeemability frontiers.

A ``Handle`` is a copyable reference.  A ``Cell`` is the durable, atomic
linearization object to which that reference resolves.  ``cell_id``, never the
logical label, determines that identity.  Copying handles is harmless when
they resolve to one cell; copying the cell itself duplicates independently
redeemable state.

Authority is represented by named right tokens instead of an integer alone.
``prepare`` atomically moves one token from a cell's unspent escrow into a
durable ticket.  Safe detached fork partitions tokens after fencing the source;
safe merge moves only unspent tokens and carries references to immutable spent
receipts.  ``unsafe_clone_private_cell`` is the sole deliberately unsafe
constructor.  It exists only as a negative control showing why equal logical
labels or epochs do not imply shared linearization.

The oracle records controller Prepare linearizations separately from external
sink executions.  Its crash test is an invariant of the abstract durable
controller state (right xor ticket), not evidence of physical storage
durability.  It therefore tests authority conservation in this profile, not
exactly-once behavior of an arbitrary remote sink.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import threading
from typing import Mapping, Sequence


class LifecycleRejected(ValueError):
    """A lifecycle operation failed a semantic precondition."""


class InjectedPrepareCrash(RuntimeError):
    """Test-only crash at an explicit Prepare transaction boundary."""

    def __init__(self, cut: str) -> None:
        super().__init__(f"injected Prepare crash {cut} commit")
        self.cut = cut


@dataclass(frozen=True)
class Handle:
    """Copyable reference to one durable redemption cell and epoch."""

    alias_id: str
    cell_id: str
    epoch: int


@dataclass
class _Cell:
    cell_id: str
    logical_label: str
    epoch: int
    open: bool
    unspent: set[str] = field(default_factory=set)
    receipt_refs: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class PrepareLinearization:
    sequence: int
    effect_id: str
    request_digest: str
    logical_label: str
    cell_id: str
    cell_epoch: int
    right_id: str


@dataclass
class _Ticket:
    effect_id: str
    request_digest: str
    logical_label: str
    cell_id: str
    cell_epoch: int
    right_id: str
    prepare_sequence: int
    phase: str = "prepared"


@dataclass(frozen=True)
class Receipt:
    effect_id: str
    request_digest: str
    logical_label: str
    cell_id: str
    right_id: str
    prepare_sequence: int
    outcome: str


@dataclass(frozen=True)
class ExternalSinkEffect:
    sequence: int
    effect_id: str
    request_digest: str
    logical_label: str
    right_id: str


@dataclass(frozen=True)
class PrepareDecision:
    """One caller-visible Prepare decision.

    ``linearized`` distinguishes a new controller success from an idempotent
    reply for an already prepared stable effect.
    """

    accepted: bool
    linearized: bool
    reason: str
    effect_id: str
    right_id: str | None = None
    cell_id: str | None = None


@dataclass(frozen=True)
class ConservationReport:
    logical_label: str
    minted_capacity: int
    unique_unspent: int
    unique_redeemed: int
    controller_prepare_successes: int
    external_sink_effects: int
    duplicate_unspent: tuple[str, ...]
    unspent_and_redeemed: tuple[str, ...]
    duplicate_redemptions: tuple[str, ...]
    missing_rights: tuple[str, ...]
    unknown_rights: tuple[str, ...]

    @property
    def safe(self) -> bool:
        return not (
            self.duplicate_unspent
            or self.unspent_and_redeemed
            or self.duplicate_redemptions
            or self.missing_rights
            or self.unknown_rights
            or self.unique_unspent + self.unique_redeemed != self.minted_capacity
        )


@dataclass
class _RuntimeState:
    cells: dict[str, _Cell] = field(default_factory=dict)
    tickets: dict[str, _Ticket] = field(default_factory=dict)
    receipts: dict[str, Receipt] = field(default_factory=dict)
    prepare_log: list[PrepareLinearization] = field(default_factory=list)
    sink_log: list[ExternalSinkEffect] = field(default_factory=list)
    minted_rights: dict[str, set[str]] = field(default_factory=dict)
    next_cell: int = 0
    next_event: int = 1


class RedemptionRuntime:
    """Atomic reference semantics for authority transport across histories."""

    def __init__(self) -> None:
        self._state = _RuntimeState()
        self._lock = threading.RLock()

    @staticmethod
    def _require_name(value: str, what: str) -> str:
        if not isinstance(value, str) or not value:
            raise ValueError(f"{what} must be a nonempty string")
        return value

    @staticmethod
    def _new_cell_id(state: _RuntimeState) -> str:
        cell_id = f"cell:{state.next_cell}"
        state.next_cell += 1
        return cell_id

    @staticmethod
    def _new_event_sequence(state: _RuntimeState) -> int:
        sequence = state.next_event
        state.next_event += 1
        return sequence

    @staticmethod
    def _cell_for_handle(state: _RuntimeState, handle: Handle) -> _Cell:
        cell = state.cells.get(handle.cell_id)
        if cell is None:
            raise LifecycleRejected("unknown redemption cell")
        if handle.epoch != cell.epoch:
            raise LifecycleRejected("stale cell epoch")
        if not cell.open:
            raise LifecycleRejected("redemption cell is fenced")
        return cell

    @staticmethod
    def _report(state: _RuntimeState, logical_label: str) -> ConservationReport:
        minted = set(state.minted_rights.get(logical_label, set()))
        unspent_owners: dict[str, set[str]] = {}
        for cell in state.cells.values():
            if cell.logical_label != logical_label:
                continue
            for right_id in cell.unspent:
                unspent_owners.setdefault(right_id, set()).add(cell.cell_id)
        redemptions: dict[str, list[int]] = {}
        for event in state.prepare_log:
            if event.logical_label == logical_label:
                redemptions.setdefault(event.right_id, []).append(event.sequence)

        unspent = set(unspent_owners)
        redeemed = set(redemptions)
        observed = unspent | redeemed
        duplicate_unspent = tuple(
            sorted(right for right, owners in unspent_owners.items() if len(owners) > 1)
        )
        duplicate_redemptions = tuple(
            sorted(right for right, events in redemptions.items() if len(events) > 1)
        )
        return ConservationReport(
            logical_label=logical_label,
            minted_capacity=len(minted),
            unique_unspent=len(unspent),
            unique_redeemed=len(redeemed),
            controller_prepare_successes=sum(len(events) for events in redemptions.values()),
            external_sink_effects=sum(
                effect.logical_label == logical_label for effect in state.sink_log
            ),
            duplicate_unspent=duplicate_unspent,
            unspent_and_redeemed=tuple(sorted(unspent & redeemed)),
            duplicate_redemptions=duplicate_redemptions,
            missing_rights=tuple(sorted(minted - observed)),
            unknown_rights=tuple(sorted(observed - minted)),
        )

    @classmethod
    def _require_conserved(cls, state: _RuntimeState, logical_label: str) -> None:
        report = cls._report(state, logical_label)
        if not report.safe:
            raise LifecycleRejected(
                f"logical authority {logical_label!r} is already amplified"
            )

    def mint(self, logical_label: str, capacity: int, *, alias_id: str) -> Handle:
        """Mint one logical grant into one durable redemption cell."""

        logical_label = self._require_name(logical_label, "logical label")
        alias_id = self._require_name(alias_id, "alias id")
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity <= 0:
            raise ValueError("capacity must be a positive integer")
        with self._lock:
            candidate = deepcopy(self._state)
            if logical_label in candidate.minted_rights:
                raise ValueError("logical label has already been minted")
            cell_id = self._new_cell_id(candidate)
            rights = {f"{logical_label}:right:{index}" for index in range(capacity)}
            candidate.minted_rights[logical_label] = set(rights)
            candidate.cells[cell_id] = _Cell(
                cell_id=cell_id,
                logical_label=logical_label,
                epoch=0,
                open=True,
                unspent=rights,
            )
            self._require_conserved(candidate, logical_label)
            self._state = candidate
            return Handle(alias_id=alias_id, cell_id=cell_id, epoch=0)

    def alias(self, handle: Handle, *, alias_id: str) -> Handle:
        """Copy a handle without copying its referenced redemption cell."""

        alias_id = self._require_name(alias_id, "alias id")
        with self._lock:
            if handle.cell_id not in self._state.cells:
                raise LifecycleRejected("unknown redemption cell")
            return Handle(alias_id=alias_id, cell_id=handle.cell_id, epoch=handle.epoch)

    def unsafe_clone_private_cell(self, handle: Handle, *, alias_id: str) -> Handle:
        """Negative control: clone cell-local escrow into an independent cell.

        This intentionally bypasses the global conservation precondition.  It
        models a controller database or VM snapshot copied with the workspace,
        not an operation a safe runtime may expose.
        """

        alias_id = self._require_name(alias_id, "alias id")
        with self._lock:
            candidate = deepcopy(self._state)
            source = self._cell_for_handle(candidate, handle)
            if any(ticket.cell_id == source.cell_id for ticket in candidate.tickets.values()):
                raise LifecycleRejected("negative-control clone requires no open ticket")
            cell_id = self._new_cell_id(candidate)
            candidate.cells[cell_id] = _Cell(
                cell_id=cell_id,
                logical_label=source.logical_label,
                epoch=source.epoch,
                open=True,
                unspent=set(source.unspent),
                receipt_refs=set(source.receipt_refs),
            )
            self._state = candidate
            return Handle(alias_id=alias_id, cell_id=cell_id, epoch=source.epoch)

    def prepare(
        self,
        handle: Handle,
        *,
        effect_id: str,
        request_digest: str,
        crash_at: str | None = None,
    ) -> PrepareDecision:
        """Atomically exchange one local right for one durable effect ticket."""

        effect_id = self._require_name(effect_id, "effect id")
        request_digest = self._require_name(request_digest, "request digest")
        if crash_at not in {None, "before_commit", "after_commit"}:
            raise ValueError("unknown Prepare crash cut")
        with self._lock:
            candidate = deepcopy(self._state)
            try:
                cell = self._cell_for_handle(candidate, handle)
            except LifecycleRejected as rejection:
                return PrepareDecision(False, False, str(rejection), effect_id)

            prior_ticket = candidate.tickets.get(effect_id)
            prior_receipt = candidate.receipts.get(effect_id)
            prior = prior_ticket or prior_receipt
            if prior is not None:
                if prior.request_digest != request_digest or prior.cell_id != cell.cell_id:
                    return PrepareDecision(
                        False,
                        False,
                        "stable effect id is already bound differently",
                        effect_id,
                    )
                return PrepareDecision(
                    True,
                    False,
                    "idempotent Prepare replay",
                    effect_id,
                    prior.right_id,
                    cell.cell_id,
                )
            if not cell.unspent:
                return PrepareDecision(
                    False, False, "no unspent right in redemption cell", effect_id
                )

            right_id = min(cell.unspent)
            cell.unspent.remove(right_id)
            sequence = self._new_event_sequence(candidate)
            event = PrepareLinearization(
                sequence=sequence,
                effect_id=effect_id,
                request_digest=request_digest,
                logical_label=cell.logical_label,
                cell_id=cell.cell_id,
                cell_epoch=cell.epoch,
                right_id=right_id,
            )
            candidate.prepare_log.append(event)
            candidate.tickets[effect_id] = _Ticket(
                effect_id=effect_id,
                request_digest=request_digest,
                logical_label=cell.logical_label,
                cell_id=cell.cell_id,
                cell_epoch=cell.epoch,
                right_id=right_id,
                prepare_sequence=sequence,
            )

            if crash_at == "before_commit":
                raise InjectedPrepareCrash("before")
            self._state = candidate
            if crash_at == "after_commit":
                raise InjectedPrepareCrash("after")
            return PrepareDecision(
                True,
                True,
                "Prepare linearized",
                effect_id,
                right_id,
                cell.cell_id,
            )

    def dispatch(self, effect_id: str) -> ExternalSinkEffect:
        """Record one external sink execution after a durable Prepare."""

        effect_id = self._require_name(effect_id, "effect id")
        with self._lock:
            candidate = deepcopy(self._state)
            ticket = candidate.tickets.get(effect_id)
            if ticket is None or ticket.phase != "prepared":
                raise LifecycleRejected("dispatch requires a prepared ticket")
            ticket.phase = "inflight"
            effect = ExternalSinkEffect(
                sequence=self._new_event_sequence(candidate),
                effect_id=effect_id,
                request_digest=ticket.request_digest,
                logical_label=ticket.logical_label,
                right_id=ticket.right_id,
            )
            candidate.sink_log.append(effect)
            self._state = candidate
            return effect

    def settle(self, effect_id: str, *, outcome: str) -> Receipt:
        effect_id = self._require_name(effect_id, "effect id")
        outcome = self._require_name(outcome, "outcome")
        with self._lock:
            candidate = deepcopy(self._state)
            ticket = candidate.tickets.get(effect_id)
            if ticket is None or ticket.phase != "inflight":
                raise LifecycleRejected("settlement requires an inflight ticket")
            receipt = Receipt(
                effect_id=ticket.effect_id,
                request_digest=ticket.request_digest,
                logical_label=ticket.logical_label,
                cell_id=ticket.cell_id,
                right_id=ticket.right_id,
                prepare_sequence=ticket.prepare_sequence,
                outcome=outcome,
            )
            del candidate.tickets[effect_id]
            candidate.receipts[effect_id] = receipt
            candidate.cells[ticket.cell_id].receipt_refs.add(effect_id)
            self._state = candidate
            return receipt

    def replace_restore(self, checkpoint: Handle, *, alias_id: str) -> Handle:
        """Restore values while rotating the durable cell epoch.

        The checkpoint supplies a locator, not rollbackable authority state.
        The old continuation and every copied checkpoint handle become stale.
        """

        alias_id = self._require_name(alias_id, "alias id")
        with self._lock:
            candidate = deepcopy(self._state)
            cell = self._cell_for_handle(candidate, checkpoint)
            self._require_conserved(candidate, cell.logical_label)
            cell.epoch += 1
            restored = Handle(alias_id=alias_id, cell_id=cell.cell_id, epoch=cell.epoch)
            self._require_conserved(candidate, cell.logical_label)
            self._state = candidate
            return restored

    def detached_fork(
        self, source: Handle, *, allocations: Mapping[str, int]
    ) -> dict[str, Handle]:
        """Fence a source and partition its unspent escrow among child cells."""

        if not allocations:
            raise ValueError("detached fork requires at least one child")
        normalized: dict[str, int] = {}
        for alias_id, amount in allocations.items():
            alias = self._require_name(str(alias_id), "child alias id")
            if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
                raise ValueError("child allocation must be a positive integer")
            if alias in normalized:
                raise ValueError("duplicate child alias")
            normalized[alias] = amount

        with self._lock:
            candidate = deepcopy(self._state)
            cell = self._cell_for_handle(candidate, source)
            self._require_conserved(candidate, cell.logical_label)
            if any(ticket.cell_id == cell.cell_id for ticket in candidate.tickets.values()):
                raise LifecycleRejected("detached fork requires settled source tickets")
            if sum(normalized.values()) != len(cell.unspent):
                raise LifecycleRejected("fork allocations must partition all unspent escrow")

            rights = sorted(cell.unspent)
            cell.unspent.clear()
            cell.open = False
            cell.epoch += 1
            result: dict[str, Handle] = {}
            offset = 0
            for alias_id in sorted(normalized):
                amount = normalized[alias_id]
                child_rights = set(rights[offset : offset + amount])
                offset += amount
                cell_id = self._new_cell_id(candidate)
                candidate.cells[cell_id] = _Cell(
                    cell_id=cell_id,
                    logical_label=cell.logical_label,
                    epoch=0,
                    open=True,
                    unspent=child_rights,
                    receipt_refs=set(cell.receipt_refs),
                )
                result[alias_id] = Handle(alias_id=alias_id, cell_id=cell_id, epoch=0)
            self._require_conserved(candidate, cell.logical_label)
            self._state = candidate
            return result

    def merge(self, sources: Sequence[Handle], *, alias_id: str) -> Handle:
        """Fence sources, union receipts, and move only their unspent rights."""

        alias_id = self._require_name(alias_id, "alias id")
        if len(sources) < 2 or len({handle.cell_id for handle in sources}) != len(sources):
            raise ValueError("merge requires at least two distinct source cells")
        with self._lock:
            candidate = deepcopy(self._state)
            cells = [self._cell_for_handle(candidate, handle) for handle in sources]
            labels = {cell.logical_label for cell in cells}
            if len(labels) != 1:
                raise LifecycleRejected("merge sources have different logical labels")
            logical_label = next(iter(labels))
            self._require_conserved(candidate, logical_label)
            source_ids = {cell.cell_id for cell in cells}
            if any(ticket.cell_id in source_ids for ticket in candidate.tickets.values()):
                raise LifecycleRejected("merge requires settled source tickets")

            transferred: set[str] = set()
            receipt_refs: set[str] = set()
            for cell in cells:
                if transferred & cell.unspent:
                    raise LifecycleRejected("merge sources overlap in unspent escrow")
                transferred |= cell.unspent
                receipt_refs |= cell.receipt_refs
            for cell in cells:
                cell.unspent.clear()
                cell.open = False
                cell.epoch += 1

            target_id = self._new_cell_id(candidate)
            candidate.cells[target_id] = _Cell(
                cell_id=target_id,
                logical_label=logical_label,
                epoch=0,
                open=True,
                unspent=transferred,
                receipt_refs=receipt_refs,
            )
            self._require_conserved(candidate, logical_label)
            self._state = candidate
            return Handle(alias_id=alias_id, cell_id=target_id, epoch=0)

    def conservation_report(self, logical_label: str) -> ConservationReport:
        with self._lock:
            return self._report(self._state, logical_label)

    @property
    def prepare_linearizations(self) -> tuple[PrepareLinearization, ...]:
        with self._lock:
            return tuple(self._state.prepare_log)

    @property
    def external_sink_effects(self) -> tuple[ExternalSinkEffect, ...]:
        with self._lock:
            return tuple(self._state.sink_log)

    def cell_snapshot(self, handle: Handle, *, require_current: bool = True) -> dict[str, object]:
        with self._lock:
            cell = self._state.cells.get(handle.cell_id)
            if cell is None:
                raise LifecycleRejected("unknown redemption cell")
            if require_current:
                cell = self._cell_for_handle(self._state, handle)
            return {
                "cell_id": cell.cell_id,
                "logical_label": cell.logical_label,
                "epoch": cell.epoch,
                "open": cell.open,
                "unspent": tuple(sorted(cell.unspent)),
                "receipt_refs": tuple(sorted(cell.receipt_refs)),
            }

    def ticket_snapshot(self) -> dict[str, dict[str, object]]:
        with self._lock:
            return {
                effect_id: {
                    "cell_id": ticket.cell_id,
                    "right_id": ticket.right_id,
                    "phase": ticket.phase,
                    "request_digest": ticket.request_digest,
                }
                for effect_id, ticket in sorted(self._state.tickets.items())
            }

    def receipt_snapshot(self) -> dict[str, Receipt]:
        with self._lock:
            return dict(self._state.receipts)


__all__ = [
    "ConservationReport",
    "ExternalSinkEffect",
    "Handle",
    "InjectedPrepareCrash",
    "LifecycleRejected",
    "PrepareDecision",
    "PrepareLinearization",
    "Receipt",
    "RedemptionRuntime",
]
