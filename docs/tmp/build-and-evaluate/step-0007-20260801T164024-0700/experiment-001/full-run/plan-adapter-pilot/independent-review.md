# Independent adversarial review of the runtime plan pilot

Date: 2026-08-01 (America/Vancouver)

## Verdict

**REVISE.**

The core SQLite enforcement mechanism is substantially better than the
evaluation currently supporting it:

- Under a trusted bootstrap and trusted SQLite-file boundary, the controller
  computes the token ledger, enforces the same current/binding fiber invariant
  as `PlanTokenLinearity.lean`, rejects the zero-demand one-token/two-claim
  split on the real transition path, and atomically combines Prepare's head
  consumption, ticket mint, token reclassification, event append, and durable
  state-head update.
- The claimed independent replay and “exact re-solve” control are not yet
  adequate paper evidence. Replay checks hashes, selected deltas, and target
  invariants, but does not recompute the complete transition or rejected
  decision. The exact baseline directly delegates to, or duplicates, the
  semantic predicate and omits a controller admission condition.
- The real Codex preflight in the 44-test regression does not execute this
  plan-aware controller. It is compatibility/regression evidence for the old
  App Server path, not runtime correspondence evidence for the new plan path.

Therefore the mechanism can support a carefully scoped prototype claim, but
the current report's independent-replay and exact-control claims require
revision before being used as evaluation evidence.

## Review scope and reproducibility

Reviewed without modifying adapter implementation:

- `adapter/plan_pilot.py`
- `adapter/plan_pilot_runner.py`
- `adapter/plan_replay.py`
- `adapter/test_plan_pilot.py`
- retained `plan-adapter-pilot/report.md`, `aggregate.json`, hashes, and logs

The four source hashes and aggregate hash exactly match `final-sha256.txt`.
No adapter source file was edited during this review.

Validation performed:

```text
python -W always::ResourceWarning -m unittest -v adapter.test_plan_pilot
```

Result: **11/11 passed**.

```text
python -W always::ResourceWarning -m unittest discover -v adapter
```

Result: **44/44 passed**, including the real Codex stdio preflight.

```text
python -W always::ResourceWarning -m unittest -v \
  docs/tmp/build-and-evaluate/step-0007-20260801T164024-0700/experiment-001/full-run/plan-adapter-pilot/review/independent_adversarial_tests.py
```

Result: **8/8 passed**. These tests are evidence probes: several pass by
demonstrating that the current replay/control accepts an adversarial object
that a complete checker should reject. The independent test source is retained
at `review/independent_adversarial_tests.py`, with the run summary in
`review/independent-adversarial-tests.log`.

`py_compile` passed for all four reviewed adapter files. AST inspection also
confirms that `plan_replay.py` does not import `plan_pilot.py`; the problem is
semantic incompleteness, not a direct implementation import.

## Findings, ordered by severity

### [P1] Replay is not an exact transition checker

`replay_events` independently recomputes the hash chain and calls
`_check_transition`, but `_check_transition` validates only selected fields
before applying the generic target invariant checker.
The relevant implementation spans `adapter/plan_replay.py:489-625`; rejected
events return after only the kind/stutter check at lines 499-504.

Concrete counterexample: the independent test constructs a valid genesis and
a correctly rehashed accepted `crash` event whose successor also changes
`grant_epochs["g"]` from `open` to `closed`. Actual controller `crash` changes
only inflight ticket phases and `global_version`. Nevertheless,
`replay_events` accepts the forged transition because the crash case checks
only token-ledger stutter, and `validate_semantic_state` does not constrain the
grant-epoch delta.

The gap is broader:

- Merge, Revoke, and Restrict do not have exact successor-delta checks.
- Refine checks one child and origin extension but not the complete computed
  lifecycle/plan successor.
- Dispatch/Retry check an inflight ticket plus plan/token stutter, but do not
  prove that all unrelated lifecycle fields stutter.
- Crash and Settle do not replay their exact ticket/receipt transformations.
- Disjoint mutation checks the new claim and plan/token stutter, but does not
  whitelist every other state delta.

Rejected decisions are not recomputed at all. Any operation, including an
actually valid Prepare, is accepted by replay as a rejected event if the event
kind is `reject` and the successor equals the predecessor. This proves state
stuttering, not correctness of the admission decision or rejection reason.

This invalidates phrases such as “independently replays every exact
transition” or “the event log proves that each controller decision followed
the operation semantics.” The safe description is: **independent hash-chain,
selected-delta, and invariant validation**.

Required revision: implement an independently written pure successor/admission
function for every operation, or an exhaustive per-field frame/delta checker;
then require exact equality with the logged successor. Rejected operations
must also have their failed admission independently recomputed if rejection
correctness is claimed.

### [P1] The finite “exact re-solve” control is not independent of semantic transport

For every non-Merge structural operation, `exact_transport_safe` returns
`semantic_transport_safe` directly after checking that the source has a serial
order. For Merge it repeats essentially the same affected-claim and
root/batch-fiber predicate. On valid pilot states, the live-load invariant
already makes at least one slot-consistent serial order available, so this
precondition does not create an independent oracle for the six fixtures.
See `adapter/plan_replay.py:375-409`, compared with the semantic Merge predicate
at lines 343-368.

The independent test confirms that `semantic_transport == exact_re_solve` on
all six public records. Agreement is therefore largely by construction, not
an independent experimental result.

There is also a concrete shared omission. The controller requires the Merge
target owner to be fresh, but both `semantic_transport_safe` and
`exact_transport_safe` ignore `target_owner`. On a valid same-root state, an
operation targeting an existing source owner is classified safe by both
baselines while the real controller correctly rejects it as `invalid merge
owners`.

Consequences:

- `semantic_transport.unsafe_reuse = 0` is a result for the hand-selected
  matrix under a non-independent labeler, not evidence of sound reuse in
  general.
- `global_re_solves_avoided = 5` is a deterministic statistic of these six
  synthetic predicates, not a solver-backed performance or workload result.
- “exact control” should be renamed until it is replaced by an independently
  specified transition solver including branch epochs, target freshness, and
  every operation field.

### [P1/P2] Hash chaining does not establish ledger provenance without a trusted anchor/store

The normal operation API cannot submit `initial`, `origin`, `disposition`, or
other target-plan fields. Genesis generates one `token:<claim>` token per
input claim, and every controller transition preserves `initial`; this is a
real API property.

It is not a tamper-resistant provenance property:

- bootstrap claims, roots, batch roots, capacities, slots, and the database
  path are trusted constructor inputs;
- token identifiers are logical names, not unforgeable credentials;
- reopening a database validates only `controller_meta.state_json`; it does
  not replay the event chain or compare the state with the chain head; and
- hashes are unkeyed and there is no external signed/MACed anchor.

The independent test directly rewrites `controller_meta.state_json` to replace
the complete initial/origin/disposition ledger with a different but internally
valid ledger. `PlanPilotController(path)` reopens it successfully. A separately
invoked `replay_events` call with the final state hash as an expected anchor
detects the mismatch, but the controller does not perform that check itself.
The reopen path is `adapter/plan_pilot.py:493-516`; controller-generated genesis
tokens are at lines 353-429.

This is acceptable only with an explicit **trusted bootstrap + trusted SQLite
file** threat boundary. If hostile local processes or workspace restore can
write the controller database, token provenance is not enforced. For a
stronger claim, verify replay on open against an external authenticated anchor
or protect state/head with an external key/service.

### [P2] Some adversarial operations roll back by exception rather than produce reject stutters

`apply` catches `_Reject`, but a controller-computed invalid target detected by
`validate_state(candidate)` raises `PlanPilotError`, escapes, and rolls back
the entire transaction without appending a reject event.
This exception boundary is visible at `adapter/plan_pilot.py:929-958`.

The independent test exercises a same-slot alias missed by Refine's precheck:

- source claim: slot `s`, batch root `ra`, owner `oa`;
- existing peer: slot `s`, batch root `rb`, owner `ob`; and
- requested one-to-one child under existing owner `ob`.

Refine checks only the existing owner's `root_slot`, so construction proceeds.
The target validator then detects that `ob` mixes immutable batch roots and
raises `PlanPilotError`. State remains old—so safety fails closed—but the API
returns no `PlanDecision`, and no rejected event is recorded.

This contradicts an unqualified “every malformed/adversarial operation is an
auditable state-hash stutter” claim and exposes a caller-triggerable
availability/audit gap. Candidate-invalid errors should become reject events,
while corruption of the loaded source should remain a hard error; that likely
requires explicit source validation before transition and separate exception
types for source corruption versus invalid computed target.

### [P2] The Codex preflight does not exercise the plan-aware path

`plan_pilot.py` is imported by its unit tests, the aggregate runner imports
only `initial_state`, and no App Server/Codex module imports the new pilot.
`service_protected_callback` explicitly describes itself as a future
integration seam.
The seam is `adapter/plan_pilot.py:964-994`.

The 44-test discovery run includes both the plan pilot tests and the existing
real Codex stdio preflight, but those are separate tests of separate paths.
Thus the preflight proves that the repository's prior Codex boundary still
works; it does not prove that Codex supplies plan metadata, that a native
Fork/Restore activates only after plan admission, or that real tool callbacks
are gated by this token ledger.

Paper-safe wording: **the adapter exposes a callback-shaped integration seam
and does not regress the independently tested Codex boundary**. It is not yet
an end-to-end Codex/Claude runtime integration.

### [P2] External effects remain outside the atomic transaction

Prepare's ticket creation is atomic with the plan state. `dispatch` then
commits the ticket phase before `service_protected_callback` invokes the
external callback, and settlement is a later transaction. A crash or exception
after callback success and before settlement leaves an uncertain/inflight
ticket and can cause a retry. Exactly-once physical execution therefore
requires sink idempotency/reconciliation and is not proved by the plan token.

Also, “Dispatch is read-only” is inaccurate literally: it writes ticket phase,
global version, event, and durable head. Its **admission decision** is
ticket/receipt-local and does not explicitly inspect plan version, root, owner,
or grant epoch. The encompassing `apply` still runs the full target validator.

### [P2/P3] Runtime topology coverage is deliberately narrower than Lean

The implemented Refine is one-to-one and requires every child owner to already
exist with an open branch epoch. It cannot create a fresh Fork owner and does
not implement the general `rho`/CanonicalOp space of the Lean grammar. The
one-child target inherits source slot, batch root, grant, and token; that
restricted transport is sound.

Merge changes owners of existing tentative claims, requires a fresh target,
and correctly rejects cross-slot, mixed-batch-root, or planned/root-`None`
fibers. Restriction and Revoke compute withdrawal from actual tentative claims
and reclassify tokens. These are useful vertical paths, but not general
Fork/Restore correspondence.

### [P3] Aggregate privacy and determinism pass only at the retained-output boundary

The runner output is deterministic canonical JSON containing only six-case
confusion counts. Re-execution exactly reproduces `aggregate.json` and its
SHA-256. It contains no claim IDs, operations, successor states, workspace
paths, threads, or agent trajectories.

This does not make the controller itself trajectory-free: every SQLite event
stores the full operation and full successor semantic state. Nor does a
count-only aggregate provide privacy for arbitrary real workloads; small or
secret case sets can leak through counts. Here the cases are fixed synthetic
public fixtures, so the retained aggregate is appropriately scoped and does
not use private agent traces.

## Requested property-by-property audit

| Property | Result | Evidence and boundary |
|---|---|---|
| Controller-generated `initial/origin/disposition`; caller forgery | **PASS at operation API; trusted-boundary caveat** | Genesis computes the ledger and strict field whitelists reject token/target material. Bootstrap inputs and SQLite file are trusted; valid direct state rewrites are accepted on reopen unless offline replay is invoked with an anchor. |
| Current/binding fibers, coverage, exclusivity, exact disposition | **PASS** | Runtime current fiber is actual `plan.remaining`; binding fiber combines tickets and receipts after enforcing no overlap, equivalent to Lean `opClaim`; both fibers are covered, cardinality ≤1, mutually exclusive, and disposition is recomputed exactly. |
| Zero-demand one-token → two claims on real path | **PASS** | `_refine` rejects any two-child target before mutation, independent of demand. Both official and independent tests observe a rejected event and state stutter; the 1-to-1 zero-demand replacement remains preparable. |
| Prepare atomic head/token consumption and ticket mint | **PASS for SQLite writer atomicity** | `BEGIN IMMEDIATE` precedes load and version check; candidate construction, validation, event insert, state/head update, and commit share one transaction. Independent two-writer test yields exactly one accepted Prepare and one stale rejection. Crash injection observes old-before/new-after only. No power-loss or external-effect atomicity proof. |
| Dispatch ticket locality | **PASS with wording correction** | Admission uses durable ticket/receipt state rather than current plan/epoch data, but Dispatch mutates ticket phase/global version/event and full validation executes afterward. |
| Refine/Merge/Restrict/Revoke provenance and roots | **MIXED** | Restricted one-to-one Refine transport and controller Merge/drop rules are sound on covered cases. Fresh Refine owners/general Fork/Restore are absent; batch-root alias becomes an exception rather than rejection; baseline Merge omits target freshness. |
| Independent replay | **FAIL as exact replay** | Independent implementation/import boundary exists, and hash/invariant checks work. It accepts a forged crash with a grant-epoch mutation and accepts a valid operation logged as rejected. |
| Independent exact baseline | **FAIL** | Non-Merge exact decisions delegate to semantic transport; Merge repeats it. Both omit target freshness and disagree with the real controller on an adversarial valid state. |
| Real Codex preflight | **NOT PLAN-PATH EVIDENCE** | The real stdio test passes, but no Codex/App Server module calls `PlanPilotController` or `service_protected_callback`. |
| Trajectory-free deterministic aggregate | **PASS for fixed retained synthetic output** | Byte-reproducible count-only JSON; raw controller events remain full trajectories and no general privacy claim follows. |

## Paper-safe claims now

The current artifact supports the following scoped statements:

1. With trusted genesis inputs and a trusted SQLite file, the operation API
   computes target plan/token state and rejects caller-supplied target fields.
2. The runtime state checker enforces logical per-origin token linearity over
   actual remaining claims and durable ticket/receipt bindings, independently
   of demand values.
3. The real Refine path rejects a zero-demand one-token/two-current-claim split
   and permits a token-preserving one-to-one zero-demand replacement.
4. SQLite `BEGIN IMMEDIATE` serializes concurrent writers; in the tested
   two-writer Prepare race exactly one matching-version operation atomically
   consumes the computed head and creates its durable ticket.
5. The restricted one-to-one Refine, same-lineage owner Merge, Restriction,
   Revoke, and ticket phase paths preserve the checked runtime invariant.
6. The retained six-case aggregate is deterministic, count-only, synthetic,
   and trajectory-free as an output artifact.
7. A separately implemented replay module detects hash-chain corruption and
   many invariant/delta violations; it should not yet be called complete exact
   replay.

## Claims not supported yet

- Every logged transition or rejection is independently recomputed exactly.
- The finite control is an independent ground-truth solver, or its agreement
  establishes semantic transport soundness.
- The hash chain prevents a process able to rewrite the SQLite database from
  forging token provenance.
- Every malicious input returns an auditable reject stutter rather than an
  exception/rollback.
- The plan controller is integrated into the real Codex/Claude Fork, Restore,
  Merge, or tool-callback path.
- The runtime implements every Lean Canonical/`rho` transition.
- Ticket linearity implies exactly-once physical external effects.
- Raw runtime state/events are trajectory-free or privacy preserving.
- Six synthetic cases establish workload prevalence, performance, or avoided
  replanning on real agent trajectories.

## Minimum revision gate

Before an `ACCEPT` verdict for the paper-bearing evaluation:

1. make replay compare against a complete independently computed successor and
   independently justify rejected decisions;
2. replace the circular exact baseline with a separately specified solver or
   exhaustive state-transition oracle, including source epochs and target
   owner freshness;
3. distinguish invalid candidate targets from corrupted source state so all
   caller-caused invalid operations produce reject events;
4. either integrate `PlanPilotController` into one real Codex App Server tool
   path or explicitly present it as an unintegrated reference-monitor pilot;
5. state and enforce the trusted bootstrap/store/anchor boundary; and
6. retain the current strong token, real zero-demand negative, concurrent
   Prepare, crash-boundary, and count-only deterministic tests.
