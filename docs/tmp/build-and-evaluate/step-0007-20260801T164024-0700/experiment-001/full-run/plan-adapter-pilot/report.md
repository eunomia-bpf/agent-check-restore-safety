# Plan-aware SQLite adapter pilot

Date: 2026-08-01 (America/Vancouver)

> **Historical initial-pass report.** The retained implementation and aggregate
> were subsequently strengthened after adversarial review.  The authoritative
> final results are in `repair-report.md` and `recheck/report.md`: seven
> synthetic cases, 19/19 targeted tests, 52/52 full adapter tests, and 12/12
> independent adversarial tests.  Counts and hashes below describe the earlier
> checkpoint and are retained to make the repair history auditable.

## Outcome

A thin, separate plan-aware controller now exercises the accepted runtime
mechanism without changing the frozen C01--C20 controller, streams, oracle,
retained results, or Lean sources.  The implementation is deliberately a
vertical pilot rather than a replacement for the existing Codex runner.

New implementation files:

- `adapter/plan_pilot.py`: canonical rich state, SQLite controller,
  plan/lifecycle transitions, and a protected-callback integration seam;
- `adapter/plan_replay.py`: controller-independent hash-chain replay,
  invariant checker, finite owner-order enumerator, and comparison baselines;
- `adapter/test_plan_pilot.py`: eleven controlled tests; and
- `adapter/plan_pilot_runner.py`: fixed synthetic decision matrix whose output
  contains aggregate counts only.

The controller stores lifecycle claims, grant/branch epochs, tickets,
receipts, a discrete origin-token ledger, and the complete quantitative plan
in the same canonical `state_json`.  Each accepted or rejected operation
appends a hash-chained event carrying the successor semantic state and advances
`controller_meta` in the same SQLite transaction.  Rejections are state-hash
stutters.

The token layer mirrors `PlanTokenLinearity.lean`: `initial` is a finite set of
controller-minted tokens, `origin` maps current and historical claim witnesses
to those immutable tokens, and `disposition` is recomputed as `remaining`,
`prepared`, or `withdrawn` from actual plan membership and durable
ticket/receipt bindings.  It is deliberately separate from vector demand;
zero-demand claims remain identity-bearing schedulable work.

## Atomic Prepare boundary

`PlanPilotController.apply()` executes `BEGIN IMMEDIATE`, loads the durable
head, and computes a private candidate.  Planned Prepare then performs, before
one commit:

1. exact plan-version CAS;
2. lexicographic computation of the earliest nonempty slot/owner group;
3. coverage, injectivity, fresh-effect, tentative/open-epoch, capacity, and
   planned-batch checks;
4. tentative-to-durable promotion;
5. durable prepared-ticket creation;
6. computed leaf disposition, remaining set, `E`, token disposition, cursor,
   plan version, and global version updates; and
7. event append, state hash, event hash, and durable-head update.

The crash-boundary test observes only the old head before commit and only the
complete new plan/ticket head after commit and reopen; no torn plan/ticket
state is observable.

Dispatch and Retry have no plan version, current slot, owner, root, batch, or
grant-epoch guard.  They require a durable ticket and change only ticket phase
plus the global event version.  `service_protected_callback()` is the explicit
future App Server/native dynamic-tool integration seam: its callback receives
only the stable `(effect, claim)` ticket binding, never the old plan.

## Computed transport rules

- A disjoint mutation must create a fresh outside owner.  The controller
  computes that claim's optional root as `None`, creates its open lifecycle
  branch, and leaves the selected plan byte-for-byte unchanged.  Both the
  controller validator and independent checker compute owner-root purity over
  every tentative claim, so placing root-`None` work under a scheduled owner
  is rejected.
- Refinement accepts only current remaining source leaves.  The replacement
  receives the source slot, immutable batch root, and immutable origin token;
  none is caller input.  Its natural-number demand may be at most the source
  demand, and the computed loss is added to `W`.  The compact pilot API admits
  one current replacement per source token; a one-to-many target is rejected
  independently of demand.
- Coarsening derives all tentative claims owned by the named source owners.
  Every affected claim must lie in one non-`None` `(slot, batch-root)` fiber.
  Same-slot/same-root merges pass; cross-slot, mixed-batch-root, and
  planned-plus-root-`None` mixtures reject.
- Restriction and Revoke derive the withdrawn tentative leaves from lifecycle
  state, terminalize them, remove them from `remaining`, and add their demand
  to the correct `W` row.  The caller cannot supply a target leaf set or
  withdrawal ledger.

Every operation has an exact field whitelist.  In particular, a caller cannot
supply target validity, roots, batches, remaining leaves, `E`, `W`, a target
plan, token origins/quotas, or an opaque nested request carrying such material.
The targeted suite checks direct `W` and origin injection plus a nested
target-validity injection.

## Independent control and aggregate result

`adapter.plan_replay` does not import the controller.  It independently:

- recomputes canonical JSON hashes, event predecessors, state hashes, and event
  hashes;
- checks the exact `B + E + W = P` ledger, reservation/deadline bounds,
  durable-load equation, cursor, ticket binding, immutable batch roots,
  all-tentative optional-root purity, token current/binding fiber cardinality,
  exclusivity, coverage, and exact token disposition;
- verifies rejected-event stuttering, version CAS, computed Prepare head and
  tickets, disjoint plan stuttering, and plan-independent Dispatch/Retry; and
- exhaustively enumerates all finite owner-group permutations consistent with
  slot order for the small controlled states.

The fixed comparison matrix contains six public synthetic mutations.  It
compares global-version invalidation, a local/per-object cache, semantic
transport, and the finite exact control.  The retained deterministic output is
`aggregate.json`:

```json
{"baselines":{"global_version":{"false_invalidation":5,"safe_replan":1,"safe_reuse":0,"unsafe_reuse":0},"per_object":{"false_invalidation":3,"safe_replan":0,"safe_reuse":2,"unsafe_reuse":1},"semantic_transport":{"false_invalidation":0,"safe_replan":1,"safe_reuse":5,"unsafe_reuse":0}},"cases":6,"global_re_solves_avoided":5,"schema":"plan-adapter-pilot.aggregate.v1"}
```

This matrix is a mechanism check, not a workload sample.  The one local-cache
unsafe reuse is the cross-root Merge; global invalidation unnecessarily
re-solves five exact-safe mutations.  The semantic checker agrees with the
finite control on all six fixtures.  The JSON contains counts only: no claim,
operation, event, workspace, thread, or state trajectory is emitted.

## Controlled tests

| Test | Checked observation |
|---|---|
| stale copied plan / target injection | stale CAS and caller target fields reject as hash stutters; no tail ticket |
| disjoint mutation | existing scheduled-owner alias rejects; fresh root-`None` owner preserves the plan while global version advances |
| same-slot refinement/coarsening | one replacement inherits source root, batch, and token; same-root Merge over distinct tokens is accepted |
| cross-slot and mixed-root Merge | both reject; local baseline demonstrates the intended topology blind spot |
| two Prepare rounds | exactly one computed group advances per transaction; cursor and `E` reach the empty tail |
| post-Prepare Revoke + dispatch | tail moves to `W`; old grant closes; prepared ticket still drives one authenticated callback and receipt |
| restriction | removed owner/leaf and its token are computed as withdrawn; `W` advances |
| retry after crash | plan and token ledger stutter across Dispatch, Crash, Retry, and Settle; the stable ticket remains the only binding |
| crash boundaries | before-commit gives the complete old head; after-commit/reopen gives the complete new head and ticket |
| zero-demand token fork | a forged/two-child one-token fiber is rejected although vector arithmetic is unchanged; a 1-to-1 zero-demand replacement can still Prepare |
| deterministic aggregate | byte-identical count-only JSON; no `claims` or `successor_state` trajectory fields |

Final targeted command:

```text
python -W always::ResourceWarning -m unittest -v adapter.test_plan_pilot
```

Result: 11/11 passed.  The final targeted log is
`invocation-13-token-final-targeted.log`.

Full existing regression:

```text
python -W always::ResourceWarning -m unittest discover -v adapter
```

Final token-aware result: 44/44 passed, including the real Codex stdio/App
Server preflight and every frozen C01--C20 case.  The final log is
`invocation-14-token-full-regression.log`.

`py_compile`, the AST no-controller-import check for `plan_replay.py`, the
aggregate no-trajectory check, `git diff --check`, and a tracked diff check of
`adapter/litmus.yaml`, `adapter/oracle.yaml`, and `adapter/results` also pass.
Final SHA-256 values for the four source files and count-only aggregate are in
`final-sha256.txt`.

## Revision record

The first passing pilot used the same scheduled owner for the supposedly
disjoint claim.  That fixture passed its local implementation but did not
match the formal optional-root invariant: one owner would have carried both a
scheduled `some(slot)` claim and an unrelated `None` claim.  The original
passing logs and SHA-256 record were retained.  The first checker revision then
correctly exposed the still-stale aggregate fixture as one test failure in
`invocation-04-disjoint-root-revision.log`.  The fixture and controller were
revised to require a fresh outside owner; invocations 005 onward pass.  This
failure is retained because it is evidence that the stronger checker engaged,
not discarded as setup noise.

The next independent formal review found that vector conservation alone does
not imply linear identity: a single zero-demand leaf could be copied into two
zero-demand leaves and later mint two tickets while every `R/P/E/W` equation
remains true.  The pre-token controller, tests, logs, and SHA record were kept.
The runtime state was then extended with the discrete ledger above.  The
positive same-slot fixture is now a token-preserving 1-to-1 replacement, while
an explicit demand-zero one-token fork is a negative regression.

## Honest boundary

Within this isolated controller grammar, the pilot now enforces both
quantitative plan transport and **logical per-origin token linearity**: an
initial token has at most one current plan witness, at most one durable
ticket/receipt binding, and never both.  A zero-demand one-token fork is
therefore rejected.  Splitting one reservation into independently preparable
operations requires distinct claims/tokens at trusted plan construction; this
compact pilot does not implement token minting during topology changes.

This is a logical controller property, not a claim that a token is an OS
capability, a cryptographic credential, or one physical external execution.
The runtime correspondence covers the pilot's 1-to-1 refine and owner Merge
operations; it is not yet a general executable `rho` adapter for every
Fork/Restore shape in the Lean grammar.

Further nonclaims:

- The new path supplies a clear protected-callback integration function but
  does not add a full native Fork/Restore/Merge App Server runner.  Existing
  App Server tests are regression evidence, not evidence that Codex emits the
  plan metadata.
- SQLite `BEGIN IMMEDIATE` tests sequential transaction atomicity and reopen
  recovery.  They do not prove concurrent linearizability, filesystem
  power-loss behavior, or atomicity between controller commit and native
  history activation.
- The authenticated sink demonstrates one controlled idempotent outcome.  It
  does not prove physical exactly-once execution for arbitrary external tools.
- The exact enumerator is intentionally bounded and factorial.  It is an
  independent small-state control, not a production planner or a performance
  result.
- Six synthetic cases establish correspondence and expose baseline failure
  modes; they make no prevalence, latency, or real-agent-workload claim.

No commit was created.
