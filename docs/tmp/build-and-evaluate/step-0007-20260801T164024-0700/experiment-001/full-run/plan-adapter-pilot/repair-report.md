# Plan-aware pilot repair after independent review

Date: 2026-08-01 (America/Vancouver)

## Outcome

The independent review's replay, comparison-control, rejection-audit, durable
head, and Codex-boundary findings were repaired in the executable pilot.  The
old `independent-review.md` and prior logs remain unchanged as the historical
record; this report describes the post-review implementation.

The strongest new property is executable and narrow: for every logged
non-genesis operation, `adapter.plan_replay` independently computes admission
and the complete successor state, then requires exact equality with the logged
decision, event kind, and successor.  A hash-consistent but semantically forged
Crash, an arbitrary stuttering rejection of a valid Prepare, and an accepted
successor with one unrelated field changed all fail replay.

## Independent pure transition oracle

`adapter.plan_replay` still does not import `adapter.plan_pilot`.  It now has a
separately written pure transition relation for all ten pilot operations:
Prepare, disjoint mutation, Refine, Merge, Revoke, Restrict, Dispatch, Retry,
Crash, and Settle.  Each case:

1. checks the loaded source invariant before operation admission;
2. checks the operation's exact field schema;
3. recomputes source/grant/branch epoch checks, CAS, target freshness,
   assignment coverage, and all operation-specific guards;
4. constructs every field of the candidate successor from the source and
   operation;
5. validates the complete candidate invariant; and
6. returns either that exact successor or a rejected source-state stutter.

Replay compares the logged Boolean decision with this independently recomputed
decision.  It therefore rejects both a forged acceptance and a forged
rejection.  For an accepted event, it compares the entire logged successor to
the pure successor, not a selected delta.  For a rejected event, it first
establishes that independent admission also rejects and only then accepts an
exact source-state stutter.

The former `exact_re_solve` label was removed from retained results.  It was
not an independent re-solver.  The replacement `transition_oracle` constructs
and validates the full target.  `exact_transport_safe` remains only as a
compatibility alias for external review scripts and delegates to this new
oracle.

## Controlled transition matrix

The retained aggregate is now schema `plan-adapter-pilot.aggregate.v2`.  Its
seven public synthetic cases include safe disjoint transport, 1-to-1 Refine,
same-root fresh-target Merge, unsafe existing-target Merge, unsafe cross-slot
Merge, Revoke, and Restrict.  The exact aggregate is:

```json
{"baselines":{"global_version":{"false_invalidation":5,"safe_replan":2,"safe_reuse":0,"unsafe_reuse":0},"per_object":{"false_invalidation":3,"safe_replan":0,"safe_reuse":2,"unsafe_reuse":2},"semantic_transport":{"false_invalidation":0,"safe_replan":2,"safe_reuse":5,"unsafe_reuse":0}},"cases":7,"oracle_safe_semantic_reuse_cases":5,"schema":"plan-adapter-pilot.aggregate.v2"}
```

These are fixture classifications, not workload frequencies, latency results,
or solver-performance measurements.  The matrix now exposes both topology
blindness (cross-slot Merge) and target-freshness blindness (reusing a source
owner as the Merge target) in the deliberately coarse per-object baseline.
The production-shaped semantic predicate agrees with the separately written
full-transition oracle on these fixtures.  A separate operation-schema test
checks every field of every one of the ten operations by removing required
fields and injecting an unexpected target-validity field; source epochs,
target freshness, and stale plan versions have explicit negative probes.

## Reject versus corruption boundary

`PlanPilotController.apply()` validates the loaded source before constructing a
candidate.  A malformed loaded source remains a hard `PlanPilotError` and does
not append an event.  Once the source has passed validation, an invalid
controller-computed candidate is converted to a rejected event whose state
hash is the source hash.  The prior Refine batch-root-alias counterexample now
returns a `PlanDecision`, appends one reject event, and independently replays.

This separation prevents caller-triggerable target invalidity from creating an
audit gap without relabeling durable-source corruption as an ordinary request
failure.

## Reopen verification and trusted anchor

Every controller open now independently replays the complete event chain and
requires equality with `controller_meta.sequence`, `head_hash`, materialized
state, and state hash.  Rewriting only `controller_meta.state_json`, including
the prior valid-looking token-ledger substitution, therefore fails on open.

The constructor also accepts `expected_head_hash`.  A caller can retain that
value outside the SQLite database and pin reopen to it; a stale or different
head fails.  The trust boundary is explicit:

- without `expected_head_hash`, the SQLite file and trusted bootstrap are the
  integrity root, and reopen detects torn or incoherent local rewrites;
- with it, the caller is responsible for storing/authenticating the anchor;
- unkeyed event hashes do not stop an attacker who can coherently rewrite the
  entire database and its in-database head; and
- logical token names are not cryptographic or OS capabilities.

No hostile-database-tamper-resistance claim is made.

## Real Codex callback path

The targeted suite now launches the installed real `codex app-server --stdio`
boundary with the repository's deterministic loopback model fixture.  The App
Server creates a native fork and emits a real client-owned `item/tool/call`.
While that request is pending, its handler calls `service_protected_callback`:
ticket Dispatch is admitted first, the callback receives only the stable
effect/claim binding, the pending request is answered, and the ticket is
settled to a receipt.  The final controller history independently replays.

This is genuine coverage of the plan controller on the client-owned Codex tool
callback path.  It is not a full topology integration: Codex still does not
emit this pilot's plan, token, root, or batch metadata, and native fork
activation is not atomically coupled to Prepare.

## Final checks

- targeted plan suite: 19/19 passed (`repair-invocation-01-targeted.log`),
  including zero-demand identity, old/new crash boundaries, two concurrent
  Prepare writers, deterministic aggregates, and the real Codex callback;
- complete adapter regression: 52/52 passed
  (`repair-invocation-02-full-adapter.log`), including the frozen C01--C20
  controller and the pre-existing real App Server preflight;
- post-review adversarial probes: 5/5 passed
  (`repair-invocation-03-adversarial.log`); and
- byte-identical runner output, stdlib-only replay imports, `py_compile`,
  privacy/schema checks, and whitespace checks passed
  (`repair-invocation-04-static.log`).

## Remaining boundaries

- SQLite `BEGIN IMMEDIATE` and the two-writer test provide concrete sequential
  CAS evidence, not a formal concurrent-linearizability or power-loss proof.
- The external callback and settlement are not one atomic transaction.  A
  response can succeed before settlement, so physical exactly-once behavior
  still needs sink idempotency or reconciliation.
- Replay authenticates hashes only relative to its supplied/trusted anchor.
  It independently checks admission and state semantics, but the diagnostic
  rejection-reason string is only hash-covered, not semantically recomputed.
- The pure transition oracle is an independently written executable model, not
  a proof that the Python controller implements the Lean semantics.
- Refine remains 1-to-1 and token preserving; this pilot does not implement the
  full Lean `rho` grammar or token minting for one-to-many decomposition.
- The seven-case matrix is a mechanism regression, not empirical evidence
  about real-agent mutation prevalence.

No commit was created by the repair task.
