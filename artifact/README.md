# Executable authority-continuity validation

This directory contains a dependency-free Python model of the paper's finite
authority-continuity state and frozen threshold-guard lifecycle contracts.  It
is executable validation, not a mechanized proof.  In particular, passing
bounded enumeration does not establish the paper's unbounded theorems.

The model computes per-branch headroom as the componentwise minimum slack over
configurations containing that branch.  A reservation batch is a canonical
branch-indexed demand vector.  The enumerated residual profile contains exactly
the batches in a finite component box that keep every configuration solvent.
The unbounded membership predicate remains separate from this enumeration.

A frozen guard has nonnegative vector coefficients and a residual budget.  Its
terms refer to stable lineage predicates: retaining any current descendant of a
lineage charges the frozen coefficient once.  Coefficients do not track later
changes to `Q`; changing them would silently change a durable lifecycle
decision.  Live restore transports a lineage predicate with OR semantics rather
than copying its charge to both continuations.

The model also includes selected rules of a crash-persistent lifecycle state with grant epochs,
prepared/inflight/uncertain tickets, settled receipts, and explicit terminal
claims.  Its rules cover atomic Prepare, Dispatch and same-ID Retry attempts,
crash recovery, Settle, Revoke, and certified fork/restore transformations.
The monotone tombstone set is the artifact's finite representation of closed
branch epochs: a tombstoned branch may not retain a tentative claim or Prepare
one, re-enter contract support, or be reused as a supposedly fresh descendant.
The artifact does not implement lifecycle Reserve, Select/Abort, generic
Merge certificates, or the complete paper LTS.

The `history_admission/` package is a second, small artifact driven by the
new typed-history theory.  An untrusted compiler derives normalized semantic
cells, typed Fork/Restore/Merge futures, the greatest durable-prefix-safe
admitted future, and controller-realization witnesses.  A separate bit-mask verifier
reconstructs the result without importing the compiler.  It checks the more
general implementation relation `Required <= RawPhysical <= Admitted`, so an
implementation may safely omit optional behavior without being confused with
a GateClone over-approximation.  Its seal certifies structural history
admission only; it deliberately does not authorize an external effect.

`exact_history_realization.py` is a bounded executable model of the paper's
unified Agent-history contract.  It enumerates indexed causal completions,
performs length-preserving fresh/alias resolution, and computes the finite
prefix-robust greatest fixed point.  The result retains indexed completion
ghosts, the full descending chain, a ranked cause for every removal, and
survivor witnesses for every prefix/still-compatible-outcome obligation.
Installation re-derives admission instead of trusting a positive certificate.
The shared-prefix regression `X tensor (Y choice Z)` under
`Pref({yx, xz})` has one individually safe completion per outcome but is
correctly rejected by the chain of sizes 2, 1, 0.  A second regression keeps
two outcome identities even when their resolved traces coincide.

The same file also retains an earlier bounded interface for all six
Fork/Restore/Merge shapes.  Its operation objects name registered leaf
contracts or checkpoints, derive per-source controller generations, and
cannot carry a plan, outcome family, source set, controller anchors, or receipt
frontier.  This is structural regression evidence only: it does not implement
the paper's immutable edit-schema refinement checker, authorized retirement,
or single global policy-domain epoch.  Its cut seal compares both the fresh
receipt trace and the ordered, append-only logical-occurrence frontier,
including an order-sensitive digest.  The 19 focused litmus tests also include
completion-observability rejection, same-cell aliases, structural Merge
fixtures, and both orderings of fresh/alias-versus-install races.

The executable model deliberately uses a flat frontier and finite caps of
128 outcomes, eight occurrences per outcome, and 50,000 linearizations.  These
bounds make exhaustive checking auditable; passing them is not a proof of the
paper's unbounded exact-realization or weak-bisimulation theorems.

The history-admission request schema is version 3, while result and verifier
schemas are version 4.  The adapter labels controller co-liveness evidence as
`exact`, `sound_overapprox`, or `exact_projection_through_r`; this is an
external attestation, not a fact the parser can establish.  Both executables
derive `coordination.required_coliveness_arity` (`r*`) from `Required` and
`Admitted`.  In projection mode they reject submitted controller groups above
`r*`, enumerate only the exact lower-order projection, and use the Lean
readiness theorem to decide the hidden full family.  In contrast,
`sound_overapprox` can prove an upper safety bound but never obtains a Ready
decision or structural seal.  See `history_admission/README.md` for the
fixed-prefix semantics and boundary.

For every non-`Reject` result, the tool also filters the submitted controller
family to its greatest safe subfamily.  Under `exact`, this is a full-Gamma
repair.  Under `exact_projection_through_r`, it is explicitly a
projection-only concrete restriction, not the maxima of the hidden full
Gamma.  Under `sound_overapprox`, it is diagnostic upper-bound information and
is never marked installable.  Every proposal remains non-authorizing and must
be installed and resubmitted before it can affect a later decision.

Run the unit tests and deterministic exhaustive explorer from this directory:

```sh
python3 -m unittest -v
python3 -m unittest -v test_exact_history_realization
python3 explore.py
python3 -m history_admission.compiler \
  fixtures/history_admission/inherit_choice.json \
  --output /tmp/history-admission-result.json
python3 -m history_admission.verifier \
  fixtures/history_admission/inherit_choice.json \
  /tmp/history-admission-result.json \
  --output /tmp/history-admission-seal.json
```

To save the canonical machine-readable report:

```sh
python3 explore.py --output results/exhaustive.json
```

The explorer enumerates every nonempty downward-closed frontier family on one
to three branches, scalar claim weights 1--2, durable demand 0--1, and grants
0--7.  Its headline source-state population satisfies an explicit owner-support
well-formedness predicate: every conditional claim's owner must occur in at
least one admitted frontier.  A separate 2,816-state raw algebra scan includes
unsupported-owner states only as a transcription diagnostic; it is not
headline theorem evidence.  The well-formed scan contains 1,312 states, of
which 730 are safe source states.  It checks:

- the universal-frontier and componentwise-need formulations of AC agree;
- direct single-branch Reserve admission agrees with the headroom test;
- direct batch admission agrees with correlated residual-profile membership;
- the exact residual is the rectangular product `Box(H)` exactly when the
  all-headrooms corner satisfies every configuration-slack inequality; the
  fixed choice state is rectangular and the fixed parallel state is not;
- choice and parallel states can have equal headroom but different residual
  profiles and divergent successor headroom;
- the Reserve derivative agrees with
  `R(successor) = {y | x + y in R(parent)}` on every enumerated successor
  batch;
- the bounded knowledge-set checker equals the intersection of its states'
  residual profiles;
- maximal single-claim promotion support is nonempty, downward closed, safe,
  and contains every safe downward-closed topology restriction;
- a compact frozen guard admits a frontier exactly when the explicit maximal
  safe-support filter admits it;
- maximal repairs for adjacent disjoint claim batches are independent of
  serialization, both as explicit families and guarded contracts;
- promotion in `b choice (x parallel y parallel z)` produces the higher-order
  family `U(2,3)`: every pair is allowed but the triple is not.  No pairwise
  conflict graph, hence no cograph lifecycle contract, represents this family;
- recomputing guard coefficients from current `Q` after withdrawal incorrectly
  reopens a previously excluded triple, while a frozen guard does not;
- OR-lineage transport after live restore charges an old/restored pair once,
  whereas naively copying the guard term charges it twice;
- under final-owner support, an exact guarded batch and both serial orders
  produce the same state and the same denotational support (guard syntax need
  not agree).  When final-owner support is absent, mandatory cleanup makes the
  `s`-first order disable the `t` step, while the enabled `t`-first order reaches
  the atomic batch's cleaned state and denotational support;
- abstract exact-promotion confluence still does not justify a witnessed
  shortcut that conditions on the first owner: that shortcut can tombstone the
  next owner and terminalize the claim needed by the second escape;
- the snapshot-local litmus constructs the actual replace pre-state with empty
  `Q` and the actual live-restore pre-state with a one-unit old claim, then
  applies the same fresh `Reserve(restored, 1)` proposal to both.  The replace
  successor has need one and is accepted, whereas the live successor has need
  two and must be rejected; and
- plain escape can turn a safe exclusive choice into an unsafe state.
- the lifecycle recovery graph rejects Dispatch-before-Prepare, preserves
  prepared work across crash, maps inflight to uncertain, reuses the same
  stable operation ID and claim on Retry, retains durable accounting on
  cancellation, and permits a sealed operation to dispatch after Revoke; and
- certified replace/live restore and choice/parallel fork preserve receipts,
  prepared/uncertain tickets, lineage guards, and per-frontier load dominance.

The deterministic v5 exhaustive counts are 6,180 single-branch demands,
17,658 batch memberships, 4,067 accepted derivative prefixes and 103,785
successor memberships, and 730 headroom-box criterion checks (296 rectangular,
434 nonrectangular).  It also checks 2,060 single-claim promotions and 22,246
safe topology restrictions, 2,060 frozen-guard repairs with 11,142 frontier
memberships, and 6,312 ordered disjoint batches for each of the explicit and
guarded confluence checks.  The recovery graph contains 8 phase/epoch states
and 22 valid edges, and structural simulation checks 26 target frontiers across
four fork/restore modes.  All source-state-derived counts use the owner-support
filter.  The unit suite contains 24 tests.

For each rectangularity case, the explorer enumerates residual components
through that source's maximum headroom component.  This contains all of
`Box(H)`; moreover, every residual batch is componentwise bounded by the
single-branch headrooms.  The equality check therefore does not acquire the
fixed-box truncation artifact discussed below.

The guarded contract stores base frontiers explicitly only because this explorer
uses at most three branches.  This is not a proposed runtime representation.
Larger implementations can keep the structured contract and frozen guards in a
PB/ILP solver or compile them to a decision diagram; exact global admission is
not assumed to remain linear after threshold guards introduce higher-order
constraints.

## Bounded derivative convention

The derivative check does not compare two profiles both truncated at the same
bound.  For successor candidates `y` in `[0,M]^(B x K)` and an accepted prefix
`x`, it enumerates the parent through component bound
`M + max_component(x)`.  This larger box contains every queried `x + y`.
Version 5 uses `M = 2`, prefix components in `0..1`, and therefore parent bound
at most 3.  Treating an out-of-box `x + y` as rejected would be a truncation
artifact, not a valid derivative check.

## Anonymous supplemental package

Do not submit the repository as the artifact: repository history and research
notes are not anonymous.  From the repository root, build the supplemental
archive from the explicit file manifest:

```sh
python3 artifact/build_anonymous_supplement.py \
  --output /tmp/history-admission-supplement.tar.gz
tar -tzf /tmp/history-admission-supplement.tar.gz
```

`ANONYMOUS_MANIFEST.txt` lists every included file individually.  The builder
rejects directories, symlinks, globs, missing entries, absolute user paths,
repository commit identifiers, and repository author/committer identities.  It
normalizes file order, timestamps, ownership, modes, and the gzip header.  The
archive contains the compiler and independent verifier, private-data-free unit
and litmus tests, the bounded scaling driver, and the complete Lean sources,
pinned dependencies, and audit driver.  It intentionally excludes repository
history, `docs`, downloaded references, private-trajectory code and output,
historical scaling JSON and machine timings, Lean build output and logs, caches,
and bytecode.

To validate the extracted archive, use a fresh directory:

```sh
cd artifact
python3 -m unittest -v
python3 bench_history_admission_scaling.py --output /tmp/scaling.json

cd ../lean
lake exe cache get
lake build AuthorityContinuity
bash scripts/audit.sh
```

The scaling driver includes a theory-directed projection sweep.  On its
six-cell full contract, the submitted unary projection grows from 128 product
iterations at two controllers to 640 at ten, while reconstructing the hidden
full powerset would grow from 4,288 to 16,846,784 iterations and cross the
200,000 fail-closed cap at five controllers.  These are deterministic loop
counts for a synthetic workload; wall-clock values remain machine-specific.
