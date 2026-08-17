# Step 0007 full run: general authority-plan kernel

Date: 2026-08-01 (America/Vancouver)

Scope: `lean/AuthorityContinuity/Plan.lean` only.  This run did not edit the
paper, canonical story/design/evaluation documents, user-instruction log, or
any pre-existing Lean module.  It did not run the whole-library build because
other full-run modules were being developed concurrently.

## Terminal result

The sixth retained single-file invocation succeeded.  Invocation 5 first
kernel-checked the four theorem gates; invocation 6 rechecked the final source
after adding the required current-head comparison to canonical transport:

```text
PATH=/home/yunwei37/.elan/toolchains/leanprover--lean4---v4.30.0/bin:$PATH \
  lake env lean AuthorityContinuity/Plan.lean
exit code: 0
```

Source SHA-256:
`7893871864e400f4c0306dcf65d869dd2bfceaf56cfc65d15d45c2b05e38fc08`.

The retained logs are `invocation-001.log` through `invocation-006.log`.
Invocations 1--4 failed during ordinary proof engineering; every diagnostic
was retained.  Invocations 5 and 6 printed no `sorryAx` for any audited theorem.  The
reported dependencies are only the standard Mathlib/Lean dependencies
`propext`, `Classical.choice`, and `Quot.sound`.

## Proved gates

### 1. Arbitrary-batch transfer and computed roots

- `computed_batch_load_le` ranges over an arbitrary finite source batch `U`.
  Its target is exactly `childBatch tr U`, computed from the actual
  `Transfer.rho`; `Transfer.CoreValid.fiber_demand` supplies every fiber bound.
- `childBatch_root_inherited` proves that every computed child has an actual
  source member and inherits its immutable root through `childRootSlot`.
- `computed_root_batch_load_le` reindexes the arbitrary batch by immutable
  root and proves conservation independently for every slot and coordinate.
- No target batch or target root map is a theorem or constructor argument.

### 2. Exact `B/E/W` accounting and zero-demand visibility

- `AuthorityPlan.ExactAccounting` is the componentwise equality
  `B + E + W = P`, where `B` is recomputed from the lifecycle's actual demand,
  the plan's current `remaining` leaves, and their roots.
- `AuthorityPlan.afterTransfer` computes the new remaining set and roots from
  `rho`, proves `B' <= B`, then computes
  `W' = W + (B - B')`.  `AuthorityPlan.afterTransfer_exact` proves the exact
  equality after this update; `W'` is not supplied by an adapter.
- The leaf ledger is a partial function
  `Claim -> Option LeafDisposition`, so `remaining`, `prepared`, and
  `withdrawn` are mutually exclusive by construction rather than by a
  caller-provided partition proof.
- `zero_demand_child_visible` proves that every computed child remains an
  explicit discrete leaf independently of its demand vector.
- `empty_fiber_leaf_withdrawn` proves that an old current leaf with an empty
  actual fiber is explicitly withdrawn, again independently of demand.
- `AuthorityPlan.afterPrepare_exact` proves that removing the complete current
  root group from `B` and adding its actual load to `E` preserves the exact
  equation for every slot and coordinate.

### 3. Noncircular atomic Prepare

- `checkHead` compares the offered natural-number head with the unique
  controller plan.
- `checkAssignment` is executable and
  `checkAssignment_sound` derives actual membership, coverage, injectivity,
  and freshness.
- `prepare_head_is_ok` constructs every field of the repository's actual
  `LifecycleState.PrepareOK` from source `LWF`, successful head and assignment
  checks, a nonempty computed head group, actual tentativeness, and source
  schedule arithmetic.
- `PreparePlanned` has no `PrepareOK`, target `LWF`, target `AC`, target plan
  validity, target batch, or target root premise.
- `PreparePlanned.actual_step` projects the atomic controller transition to
  the exact existing `Step.core (CoreStep.prepare ...)` and therefore to
  `prepareState`.  `PreparePlanned.accounting` proves the simultaneous plan
  update.

### 4. Positive grammar, actual projection, and arbitrary finite traces

- `PlannedStep` contains checkpoint, current-head-checked canonical transfer,
  the atomic `PreparePlanned` transition, and actual ticket steps.
- `PlannedStep.actual_step` projects every constructor to the repository's
  sole `Step` relation.
- `PlannedStep.preserves_accounting` proves the plan equality from the source
  equality and the computed transition.  No constructor accepts target
  accounting.
- `planned_trace_preserves` ranges over the reflexive-transitive closure of
  that positive grammar and preserves actual lifecycle `LWF`, `AC`,
  `ActiveExact`, and exact plan accounting.
- `planned_trace_projects` erases every arbitrary finite planned trace to an
  arbitrary finite actual lifecycle trace.

## Constructor-premise audit

A static scan found no `sorry`, `admit`, project `axiom`, target
`LWF`/`AC`/`PrepareOK`/`ExactAccounting` premise, or caller-selected target
batch/root.  The only occurrences of `axioms` are the seven explicit
`#print axioms` audit commands.

## Explicitly deferred gates

This module is positive kernel evidence for the four priority gates, not the
entire frozen theorem matrix.

- It does not prove the abstract block-expansion/deadline scheduler, the
  residual `L + E <= R` envelope, or the global durable-load equation
  `d_t = d_0 + sum E`.  `R` is retained as plan data but is not yet connected
  to a proved invariant.
- It models one authoritative `currentSlot`; Prepare consumes its whole
  computed root group but does not compute the next cursor.  Consequently the
  trace theorem covers arbitrary finite histories in the stated grammar, not
  the reviewed multi-slot/multi-Prepare workload.
- Restriction/Revoke plan transport, checked same-slot Merge, cross-slot Merge
  counterexamples, and owner-purity checking are not constructors here.
- The function-valued disposition makes categories exclusive and keeps the
  two required zero-demand cases visible, but this run does not yet prove the
  complete per-root historical leaf-partition theorem across arbitrary-depth
  transfer plus multiple partial Prepare rounds.
- Ticket steps stutter on the plan and project to the actual LTS, but the
  separate post-Prepare Revoke/Dispatch witness remains in `PlanPreflight`;
  stable binding and durable-before-attempt are inherited from the existing
  `Step`/`Trace` theory rather than restated here.
- Same-slot Merge, the observation lower bound, negative suite, complete
  project build/audit/fresh replay, and adapter pilot are separate full-run
  obligations.

These omissions mean this result supports the semantic transport story, but
by itself does not satisfy the experiment plan's complete positive-support
rule or justify the full multi-round schedule-continuity headline.
