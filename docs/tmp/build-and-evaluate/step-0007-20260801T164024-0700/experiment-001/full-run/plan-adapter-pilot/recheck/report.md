# Independent adversarial recheck of the repaired runtime pilot

Date: 2026-08-01 (America/Vancouver)

## Verdict

**ACCEPT, for the explicitly scoped prototype claims below.**

The five minimum gates in the earlier `independent-review.md` are now met at
prototype level.  For every non-genesis operation in the pilot grammar, replay
uses a separately implemented pure transition to recompute admission and the
entire successor.  It rejects forged acceptances, forged rejections of valid
operations, and invariant-valid successors containing an unrelated field
change.  The transition oracle no longer delegates to the compact semantic
predicate.  Invalid computed candidates become auditable reject stutters,
whereas an invalid loaded source is a hard error.  Reopen checks the chain,
head, materialized state, and optional external head anchor.  Finally, the real
installed Codex App Server callback test now traverses the plan controller's
Dispatch and Settle path.

This is not an unqualified runtime-security acceptance.  The trusted genesis,
trusted SQLite store when no external anchor is supplied, diagnostic reason
strings, physical external effects, native Codex topology, and correspondence
to the Lean model remain outside the established property.  Those boundaries
are both executable and paper-visible; none requires another pilot repair if
the paper preserves the claim language below.

## Recheck scope and reproducibility

The recheck read, but did not edit:

- `adapter/plan_pilot.py`;
- `adapter/plan_replay.py`;
- `adapter/plan_pilot_runner.py`;
- `adapter/test_plan_pilot.py`;
- `plan-adapter-pilot/independent-review.md`; and
- `plan-adapter-pilot/repair-report.md`.

All seven entries in `repair-sha256.txt` match the reviewed bytes.  Independent
test source is retained at `recheck/adversarial_recheck_tests.py`; its SHA-256
is recorded in `invocation-04-static.log`.

Validation results:

- independent adversarial recheck: **12/12 passed**;
- targeted plan pilot: **19/19 passed**;
- complete adapter discovery: **52/52 passed**;
- `py_compile`, hash-manifest verification, runner determinism, aggregate
  schema/arithmetic/privacy checks, AST import/call separation, and whitespace
  checks: **passed**.

The four invocation records are retained in this directory.  No adapter source
or earlier review record was modified, and no commit was created.

## Adversarial findings

### Exact non-genesis decision and successor replay: PASS

The recheck differentially executed all ten operations---Prepare, disjoint
mutation, Refine, Merge, Revoke, Restrict, Dispatch, Retry, Crash, and
Settle---through `PlanPilotController.apply()` and
`plan_replay.reference_transition()`.  For each operation, the independently
computed Boolean decision and complete successor equalled the controller's
durable result, and the resulting event history replayed.

Four hash-consistent attacks then replaced an otherwise valid Prepare, Refine,
Revoke, or Crash successor with a still-invariant-valid state whose unrelated
`global_version` was changed.  Replay rejected all four on complete successor
inequality.  A valid Prepare logged as a state-stuttering rejection was also
rejected because independent admission accepted it.  These probes exercise
more than generic invariant validation: the forged targets remain valid
states, but are not the unique operation successor.

The exact claim begins after trusted genesis.  Replay validates the genesis
state and marker but does not derive trusted bootstrap inputs from an earlier
event.

### Diagnostic rejection reason: committed, not recomputed

One deliberate adversarial probe remains accepted: for an operation that both
controller semantics and the oracle reject, a reviewer can replace the reason
with an arbitrary string, recompute the hashes, and replay still accepts.  A
reason changed without recomputing its body hash is detected.

This does not let an attacker change accepted/rejected status, operation kind,
or successor state.  It does mean the paper must not call the logged reason an
independently justified rejection category, and must not use reason-frequency
statistics as oracle-checked evidence.  The safe wording is that reasons are
hash-covered diagnostics; Boolean admission and complete successors are
semantically recomputed.

### Reopen, materialized state, and external anchor: PASS with stated TCB

An isolated rewrite of `controller_meta.state_json` to another valid-looking
state fails reopen because it disagrees with the replayed final state and state
hash.  A stale expected external head also fails.

The recheck additionally replaced an entire temporary controller database with
a different, internally coherent controller database.  Unanchored reopen
accepted the replacement history; reopen using the victim's externally retained
old head rejected it.  This is the intended boundary, not tamper resistance:

- without `expected_head_hash`, the complete SQLite database and bootstrap are
  the integrity root;
- with the argument, the caller must protect and update the exact external
  anchor; and
- unkeyed hashes cannot resist a process that can coherently replace the
  database and its in-database head.

The anchor checks one durable history head.  It is not a cryptographic key, an
OS capability, a transparency log, or a promise that authorized writers cannot
advance the database after the check.

### Transition oracle and aggregate label: PASS as differential executable evidence

AST inspection confirms that `plan_replay.py` does not import the controller.
The compact `semantic_transport_safe` function does not call
`reference_transition`, `transition_oracle_safe`, or the compatibility alias.
The `transition_oracle` label is instead obtained from complete successor
construction and target validation.

Positive and negative probes cover plan CAS, existing-target Merge, unknown or
closed source owner, missing operation fields, and injected target-validity
fields.  The full targeted suite separately removes every required field and
injects an unexpected field for every operation.  On the seven fixed fixtures,
the compact semantic predicate and transition oracle agree; the aggregate uses
the oracle as its label and no longer labels one function with itself.

This remains two manually implemented Python semantics, not an independent
theorem prover or a proof of correspondence to Lean.  The runner also uses the
controller's trusted `initial_state` constructor to build public source
fixtures.  Thus agreement is useful differential regression evidence, not a
soundness theorem or statistical validation.

### Invalid candidate versus corrupted source: PASS

The earlier mixed-batch Refine alias was rerun.  Starting from a valid source,
the controller-computed invalid target returns a `PlanDecision`, appends one
`reject` event, preserves the state hash, and independently replays.  After the
materialized source is changed so that its stored cursor violates the source
invariant, `apply()` raises `PlanPilotError` and appends no event.

The exact distinction is **valid loaded source plus rejected or invalid
computed target** versus **loaded source that already fails validation**.  A
strict-valid but coherently substituted store remains in the trusted-store
boundary described above.

### Real Codex callback: PASS at the client-owned tool seam

The independent test launches the installed `codex app-server --stdio` binary
against the deterministic loopback Responses fixture, creates the native fork,
and observes a real pending `item/tool/call`.  Its client handler sees the
prepared ticket, invokes `service_protected_callback`, verifies that Dispatch
has changed the ticket to `inflight` before sending the App Server callback
response, and verifies that Settle creates the receipt after that response.
The final controller chain independently replays.

The precise supported integration is therefore:

`real Codex pending dynamic-tool request -> client handler -> plan-controller
Dispatch -> client response -> plan-controller Settle`.

Codex does not emit the pilot's plan, token, root, slot, batch, or epoch
metadata.  Native Fork/Restore/Merge activation is not mediated by the plan
controller, and Prepare is not atomically coupled to the native Codex fork.
The model responses are deterministic loopback fixtures, although the Codex
binary and stdio protocol path are real.

### Prepare concurrency, crash boundaries, and token lifecycle: PASS with physical-effect limit

Two independent SQLite connections submitting the same plan version produce
one admitted Prepare and one stale-version reject.  Reopen observes one ticket
and a replayable serial history.  Injected failure before SQLite commit leaves
genesis; injected failure after commit leaves the complete prepared state.
This is concrete `BEGIN IMMEDIATE`/CAS evidence, not a power-loss or formal
linearizability proof.

On the actual controller path, a zero-demand one-token/two-child Refine is
rejected, while a zero-demand one-to-one replacement can be prepared.  The
same ticket then traverses Dispatch, Crash to `uncertain`, Retry to `inflight`,
and Settle to one durable receipt, with the full history replaying.

The callback response occurs before settlement.  A process failure in that
interval can require retry or reconciliation and may duplicate a physical
effect unless the sink is idempotent.  Logical one-token/one-binding safety
does not establish exactly-once external execution.

### Determinism and privacy: PASS only for the fixed retained aggregate

Two fresh executions produce byte-identical aggregate v2 JSON, equal to the
retained `aggregate.json`.  Each baseline's four confusion counts sum to all
seven cases.  The top-level and nested keys are allowlisted, and the output
contains no fixture claim/owner names, operations, state, plan version,
successor, path, or trajectory.

This privacy statement does not extend to SQLite events, which contain full
operations and successor states, or to arbitrary count releases over secret or
small workloads.  The seven fixtures are fixed, synthetic, and public; the
aggregate is not a measurement of real-agent prevalence.

## Requested property-by-property disposition

| Requested property | Recheck result | Exact boundary |
|---|---|---|
| Independently recomputed accept/reject | **PASS** | Every non-genesis Boolean decision is recomputed; diagnostic reason text is not. |
| Complete successor equality | **PASS** | Hash-consistent, invariant-valid forged Prepare/Refine/Revoke/Crash targets fail. |
| Reopen chain/head/state | **PASS** | Torn/incoherent rewrites fail; coherent whole-store replacement is in the unanchored TCB. |
| Expected external anchor | **PASS** | Detects a different exact head if the caller protects the anchor; it is not keyed authentication by itself. |
| Oracle independence and dependencies | **PASS as executable differential evidence** | Separate controller import/call graph; CAS, epochs, freshness, and schemas covered; no Lean correspondence proof. |
| Invalid target versus corrupt source | **PASS** | Valid-source target failure logs reject; invariant-invalid loaded source raises and adds no event. |
| Real Codex callback path | **PASS narrowly** | Real App Server dynamic-tool callback traverses Dispatch/Settle; native topology and plan production remain outside. |
| Two-writer Prepare and crash injection | **PASS experimentally** | One CAS winner and old-or-new injected commit boundaries; no power-loss/formal concurrency proof. |
| Zero-demand, Retry, Settle | **PASS** | Real transition path enforces logical token binding; physical exactly-once is not implied. |
| Deterministic count-only output | **PASS for fixed fixtures** | Aggregate only; raw event databases are neither trajectory-free nor privacy preserving. |

## Paper-safe claims

The repaired artifact supports the following statements:

1. Under trusted bootstrap inputs, every logged non-genesis operation has its
   Boolean admission and complete successor recomputed by a separately
   implemented pure Python transition checker.
2. Replay rejects hash-consistent forged transitions, including valid-state
   unrelated deltas, and rejects a valid operation falsely logged as rejected.
3. Reopen validates the full event chain against the in-database head and
   materialized state; an optional externally protected exact head detects a
   different coherent history.
4. On the implemented one-to-one Refine, same-lineage Merge, Revoke,
   Restrict, Prepare, and ticket paths, the controller and transition oracle
   agree on exact successors and preserve the checked runtime invariant.
5. SQLite serialized writers yield one matching-version Prepare winner in the
   tested race, and injected pre/post-commit failures expose only old or new
   durable states.
6. The actual Refine path rejects the zero-demand one-origin/two-current-witness
   split; one-to-one zero-demand transport remains executable.
7. One real installed Codex App Server dynamic-tool callback is gated by
   controller Dispatch and followed by controller Settle at the client-owned
   callback seam.
8. The seven-case retained result is deterministic, count-only, synthetic,
   and free of individual trajectories at the aggregate-output boundary.

## Claims still not supported

- Rejection reason strings are independently justified or safe to aggregate as
  semantic categories.
- Hash chaining alone resists a process that can coherently rewrite the SQLite
  database, or the external anchor is authenticated without caller protection.
- Genesis/bootstrap facts are derived or independently reconstructed.
- The Python oracle proves correspondence to the Lean semantics or makes the
  runtime formally verified.
- The full Lean `rho` grammar, one-to-many token minting, or general native
  Codex/Claude Fork, Restore, and Merge are implemented.
- Native topology activation and Prepare share one atomic linearization point.
- Ticket linearity or the tested callback provides exactly-once physical
  external effects.
- Exception injection is a power-loss test or the two-writer run is a formal
  concurrent-linearizability proof.
- Raw controller events are private, count-only, or suitable for release.
- Seven synthetic cases establish workload frequencies, performance, or
  avoided replanning on real agent traces.

Subject to these boundaries, the repaired runtime pilot is suitable as a small
feasibility and executable-correspondence component of the theory-heavy paper.
