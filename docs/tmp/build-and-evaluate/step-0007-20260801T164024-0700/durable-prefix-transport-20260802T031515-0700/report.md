# Durable-prefix transport and fixed-family synthesis

**Date:** 2026-08-02

## Question

When an Agent runtime applies a history transformation after some authority
has already crossed a rollback boundary, which prospective fresh commitments
may remain enabled without reusing an old policy certificate unsafely?

This step is deliberately narrower than a full typed Fork/Restore/Merge
compiler.  It assumes a finite source family, a fixed candidate future family,
a lineage map, and an already reconstructed durable prefix.  It proves the
exact decision procedure in that scope and records what the future typed
generator must establish.

## Model

- `source : Finset (Finset U)` is the source authority contract.
- `durable : Finset U` names indivisible authority units already committed in
  rollback-independent history.
- `candidate : Finset (Finset D)` is a fixed, fully observed family of future
  cells that may create *fresh* commitments.
- `ell : D -> U` maps future semantic cells to source authority units.
- `PrefixTargetSafe` charges both the actual durable prefix and each future
  configuration.  The sums are not deduplicated, so resurrecting a committed
  unit is visible as a second occurrence.
- `PrefixConfigMorphism` requires local injectivity, disjointness from the
  prefix, and source admission of `durable ∪ image(C)` for every future `C`.

Retries and replays resolved by an existing receipt are not elements of `D`;
they are durable stutters in the commitment LTS.  Treating a retry as a fresh
future cell would correctly fail this fresh-authorization judgment but would
be the wrong runtime abstraction.

## Checked results

1. `UniversalPrefixTransport` for every natural-number additive source policy
   is equivalent to `PrefixConfigMorphism`, assuming a well-formed source and
   an empty target configuration.  Thus the semantic test is not merely a
   sufficient heuristic.
2. `safeFuture` executably filters a fixed candidate family by local
   injectivity, prefix disjointness, and source-family membership.
3. `safeFuture` is sound and is the greatest prefix-safe subfamily of that
   candidate under set inclusion.
4. If source and candidate are rooted downsets, `safeFuture` is also a rooted
   downset.
5. A supplied `required` family fits in some admitted pruning exactly when it
   is contained in `safeFuture`.  This prevents silent pruning relative to the
   supplied requirements; meaningful non-vacuity still depends on the typed
   operator generator producing a complete and nontrivial requirement family.
6. Applying the previously checked minimal-nonface theorem to `safeFuture`
   yields the least common-coordination equivalence under maximal asynchronous
   `localProduct` recombination and its finest exact block partition.
7. Immutable ledger growth makes the extracted set of committed atoms
   monotone.
8. If a prospective fresh cell maps to an atom already in the durable prefix,
   a capacity-one point policy proves that universal certificate reuse is
   impossible.  Because the past is outside `D`, quotienting future cells
   alone cannot erase this obstruction.

## Separating fixtures

- A restored future looks safe when checked against the snapshot alone.
- Adding the prepared durable ledger binding rejects the restored fresh
  commitment for the same unit.
- A future for a distinct atom remains structurally transportable.  This
  demonstrates only that the invariant itself does not require blanket epoch
  invalidation; it is not a lease/version/refinement theorem.

## Receipt-to-prefix gate

`committedAtoms` is a finite set and therefore deduplicates repeated atoms.  It
is a faithful durable unit prefix only when all of the following are checked:

1. the ledger is authoritative and outside the rollback domain;
2. `RedemptionCommitment.Safe` establishes receipt-per-unit uniqueness;
3. atom identity includes an indivisible unit identifier together with root,
   issuer, scope, and version/nonce where relevant; and
4. the adapter separately proves `committedAtoms S ∈ source`.

The fourth fact is the `hDurable` premise in the synthesis theorem.  It is a
cross-model consistency obligation and does not follow from the commitment
LTS's `Safe S` predicate.

## Validation

The following checks passed on the final source:

```text
lake env lean AuthorityContinuity/DurablePrefixTransport.lean
lake build AuthorityContinuity.Main
lake env lean AuthorityContinuity/Audit.lean
lake env leanchecker --fresh AuthorityContinuity.Main
```

The integrated build completed 8,501 jobs.  The theorem audit reports only
Lean/Mathlib foundations `propext`, `Classical.choice`, and `Quot.sound`; no
project axiom, `sorry`, or `admit` is present.  An independent hostile review
approved the mathematics after requiring the receipt-prefix gate and the
renaming of the distinct-atom fixture so it no longer claimed lease
refinement.

## Scope and novelty consequence

This step establishes exact policy-oblivious inheritance for all additive
policies in a fixed candidate/control scope.  It does **not** establish:

- the most permissive behavior for one fixed current policy;
- a global optimum over alias, reissue, reauthorize, fence, and reject repairs;
- exact concrete-runtime reachability;
- physical co-location (a coordination component may be a durable distributed
  service);
- remote exactly-once execution, receipt truthfulness, or lease validity; or
- correctness/completeness of the typed operation that generates `candidate`
  and `required`.

The fixed-family filter and static factorization are supporting results, not
the paper's mathematical novelty.  The remaining contribution must derive the
families and lineage from typed Fork/Restore/Merge semantics, bind outstanding
lease/version state, check the cross-model history gate, and lower either a
witness-carrying repair or a minimal counterexample to a real runtime.

## Next step

Build the small compiler around these checked kernels.  Its first version will
consume an explicit typed request and emit:

- admitted and rejected future configurations with local witnesses;
- required-behavior preservation or a failing required configuration;
- common coordination components under the declared runtime independence
  model;
- lineage/prefix collision diagnostics; and
- `Inherit`, `ReadmitOK`, `NeedsMechanism`, or `Reject`, without claiming a
  unique globally most-permissive repair.
