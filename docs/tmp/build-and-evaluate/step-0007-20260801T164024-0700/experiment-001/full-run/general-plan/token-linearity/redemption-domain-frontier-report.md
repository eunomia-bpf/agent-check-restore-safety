# Sanitized redemption-domain frontier report

## Status

The new Lean module is a supporting theory extension. It does not modify the
paper and does not claim a refinement of an unmodified agent runtime. All
examples are closed synthetic fixtures and contain no private trace data,
credentials, hostnames, or user content.

## Reviewer attack addressed

The old condition `|cur(t)| <= 1` treats every current history occurrence as
an independently redeemable copy. That is sufficient, but it is not generally
necessary. Several history aliases can safely refer to one shared atomic
one-shot cell. Conversely, matching a textual domain label does not make two
cloned controller databases one cell.

The first draft of this extension overclaimed that the maximum number of
accepted occurrences always equals the size of the domain image. That equality
is false when lifecycle choices make different cells mutually exclusive, and
an occurrence set also loses repeated attempts created after rollback. The
frozen module therefore uses a stricter separation:

- the event parameter identifies one potential freshly minted authorization
  receipt/commitment, not every API response;
- `Occurrence` is a history/workspace occurrence and need not identify an
  event;
- `Domain` is the semantic identity of one shared, durable, linearizable
  one-shot cell, not a caller-provided string;
- `committed` retains known accepted event IDs, while `consumed` and the
  operational `spent` set represent authoritative durable prior acceptance;
  `consumed` may also cover pruned event history and existing bindings;
- `LifecycleFeasible` is independent of per-cell one-shot safety.

The model also separates a caller operation key `e` from a linearizer-minted
authorization receipt `r = (cell, local sequence)`. A retry may return the same
receipt multiple times, while using the same operation key at two independent
cells creates two distinct receipts and therefore two authority commitments.
The closed theorems
`ResponseIdentity.retry_successes_share_one_commitment` and
`ResponseIdentity.same_operation_two_cells_create_two_commitments` freeze both
cases.

## General operational results

`OneShotRun cellOf spent commitments final` is an inductive finite execution
of newly linearized commitments. Every commit requires its cell to be absent
from `spent`, then atomically inserts it before continuing. The trace is a
list of fresh receipt identities, so two distinct commitments produced from
one restored occurrence are counted twice. Successful API retries that return
an existing receipt are intentionally outside this list.

The frozen operational results are:

1. `OneShotRun.spent_mono`: the initial spent-cell set is a subset of the
   final set.
2. `OneShotRun.final_card_eq_initial_add_commitment_length`:
   `|final| = |spent| + commitments.length`. Fresh commitment count is
   exactly durable spent-state growth.
3. `OneShotRun.initial_card_add_commitment_length_le_reachable_card`: for a
   finite offered horizon, old spent cells plus successful event count is at
   most the size of `spent union image(cellOf, offered)`.

These theorems do not use lifecycle availability and do not claim the upper
bound is reachable.

## General fixed-horizon upper bounds

For a fixed horizon, an `AdmissibleExtension` requires newly minted commitment
event identities to:

- come from the offered set;
- be fresh relative to committed event identities;
- use pairwise distinct semantic cells;
- avoid cells already consumed by committed durable history; and
- satisfy the separately supplied lifecycle-feasibility predicate.

`singlePerCell` and `avoidsConsumed` are explicit CAS/refinement premises.
Accordingly, the unconditional cardinality theorem below is a supporting
lemma once those premises have been established; it is not itself a proof
that a runtime implements linearizable admission.

The general theorem
`admissible_card_le_unusedActiveCells_card` proves only

```text
|new accepted event IDs| <= |image(cellOf, offered) - consumedCells|.
```

With a valid committed history,
`committed_add_accepted_card_le_reachableCells_card` additionally proves

```text
|committed event IDs| + |new accepted event IDs|
  <= |consumedCells union image(cellOf, offered)|.
```

This incorporates existing durable bindings/accepted history instead of
looking only at a transient active image.

## Conditional tightness and exactness

Tightness is intentionally conditional on two workload assumptions:

- `SoloAvailable`: every unused active cell has an offered attempt that is
  lifecycle-feasible by itself.
- `ProductIndependent`: singleton-feasible attempts on distinct unconsumed
  cells compose into a jointly lifecycle-feasible set.

Only with both assumptions does
`exists_tight_admissible_of_soloAvailable_productIndependent` construct one
accepted representative per unused cell. Consequently,
`all_admissible_card_le_iff_unusedActiveCells_card_le_of_independent` gives the
budget equivalence

```text
(all admissible accepted sets have size <= k)
  iff |unusedActiveCells| <= k.
```

The `k = 1` specialization uses an at-most-one statement. The empty horizon
has zero unused active cells and therefore satisfies it without a nonempty
side condition.

Occurrence linearity is recovered only under further explicit premises:

- one offered event identity per active occurrence;
- `cellOf` is injective on offered events;
- no offered cell is already consumed; and
- the solo-availability/product-independence premises above hold.

Under exactly these premises,
`independentOccurrences_single_redemption_iff_current_card_le_one` reduces the
cell frontier to `|activeOccurrences| <= 1`.

## Separating fixtures

### Shared cell aliases

`SharedCellAliases.shared_cell_aliases_safe_but_not_occurrence_linear` has two
distinct current occurrences and one actual `Unit` cell. Every admissible set
has at most one accepted event although occurrence cardinality is two. This is
the strict counterexample showing that occurrence linearity is sufficient but
not universally necessary.

### Mutually exclusive choice

`ExclusiveChoice.two_cells_but_choice_accepts_at_most_one` has two unused
semantic cells, while lifecycle feasibility permits at most one choice. Each
cell is solo-available, but
`ExclusiveChoice.choice_is_not_productIndependent` proves the missing product
assumption. Thus a domain-image cardinality of two is only an upper bound, not
an unconditional maximum.

### Pruned event history with a durable spent record

`DurableConsumedHistory.restored_attempt_blocked_by_pruned_consumed_history`
starts with no retained committed event ID but one durable consumed cell. A
restored attempt naming that cell cannot be accepted. This fixture prevents a
garbage-collected event log from being confused with an unspent cell.

### Rollback with cloned cells

`RollbackClonedCells.rollback_clone_double_accept_counterexample` contains two
distinct fresh receipt/event IDs mapped to one restored history occurrence,
one textual label, and one caller operation key, but to two independent
semantic cells. Both can commit. This demonstrates all required distinctions:

- event identity must be counted rather than occurrence identity; and
- equal labels do not establish a shared CAS/linearization domain; and
- caller operation-key deduplication cannot replace receipt/cell accounting.

## Trust and non-claims

The module treats the `Domain` value as the identity of an actual shared,
unit-capacity one-shot linearization object. A deployment must resolve that identity from trusted
controller state. Two services are one domain only when they coordinate
through the same durable one-shot cell (or equivalent linearization point);
two cloned stores are different domains even if their serialized labels match.

The event-cardinality results are about fresh one-shot authority commitments.
They do not directly model a capacity-greater-than-one cell or a quantitative
zero-weight event. A quantitative theorem would need an explicit positive
weight premise and capacity accounting; citing this unit-cell theorem for such
a setting would be invalid.

The module does not prove complete tool mediation, truthful external receipts,
durability of a particular database, ABA-safe generation management, dynamic
horizon discovery, liveness, or lifecycle feasibility for a real runtime.
Additional cross-cell constraints may make the general upper bound strict.
The tightness theorem must not be cited without its availability and product-
independence assumptions.

The `consumed` set is modeled as an authoritative global receipt/spent log. It
must not be reconstructed by unioning only locally visible workspace logs at
Merge or Restore; unseen durable receipts remain consumed.

## Frozen integration and validation

The theory is implemented in
`AuthorityContinuity/RedemptionDomainFrontier.lean`, imported by
`AuthorityContinuity/Main.lean`, printed by `AuthorityContinuity/Audit.lean`,
and protected by frozen theorem-name checks in `scripts/audit.sh`.

Validation commands:

```sh
lake env lean AuthorityContinuity/RedemptionDomainFrontier.lean
lake build AuthorityContinuity
./scripts/audit.sh
```

The standalone module and full library build passed under the pinned Lean and
Mathlib environment. The final timed audit also passed, including source
placeholder and declared-axiom scans, frozen theorem presence, kernel
dependency output against the existing whitelist, and a fresh replay of
`AuthorityContinuity.Main` (`real 838.16 s`, `user 834.65 s`, `sys 5.99 s`).
