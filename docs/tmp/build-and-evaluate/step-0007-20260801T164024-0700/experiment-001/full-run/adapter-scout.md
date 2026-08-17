# Adapter scout: transportable plan pilot on the existing Codex boundary

Date: 2026-08-01 (America/Vancouver)  
Mode: read-only runtime scout; no runtime implementation and no Lean invocation  
Approved experiment: Step 0007, Experiment 001, Revision 2

## Bottom line

The repository already has the narrow runtime asset required by the accepted
plan.  `adapter/` launches a pinned real Codex App Server, grounds logical
histories in real `thread/fork` IDs, owns the client-side
`item/tool/call` callback, holds that callback while a controller worker is
hard-killed/restarted, and dispatches only after consulting a durable
SQLite-backed controller.  The model and external sink are deterministic local
fixtures, so this is a dispatch-boundary correspondence experiment rather than
a model-behaviour benchmark.

The smallest honest pilot does **not** modify Codex, replace the existing
adapter, or extend the old P0--P3 claim into a product-wide monitor.  It adds the
plan as authoritative semantic state in the existing controller and uses the
existing `DurableController.apply()` transaction as the implementation
linearization point.  In particular, plan-head comparison, current-slot and
assignment checks, tentative-to-durable promotion, ticket creation, ledger
advance, version advance, event append, and state-head update must all occur in
one `BEGIN IMMEDIATE` transaction.

The fixed C01--C20 suite and its frozen oracle should remain untouched and run
as a regression.  Plan-specific controlled histories should live in a separate
small runner/checker so that the old scientific contract is not silently
reinterpreted.

## Existing dispatch-owning path

The concrete path is:

```text
real Codex App Server
  thread/start + native thread/fork
    -> real item/tool/call request remains pending
      -> adapter.worker child opens controller.sqlite3
        -> DurableController.apply(dispatch)
          -> authenticated sink.sqlite3 attempt
            -> controller settlement / receipt
              -> item/tool/call response
```

Exact files and responsibilities:

| File | Existing responsibility | Pilot relevance |
|---|---|---|
| `adapter/app_server.py:488` | creates a persistent seed thread with the single dynamic tool `protected_commit` | real agent-runtime boundary |
| `adapter/app_server.py:551` | invokes native `thread/fork` and checks `forkedFromId` | real history identity and fork evidence |
| `adapter/app_server.py:576` | waits for the real `item/tool/call` and leaves it pending until the adapter responds | protected dispatch seam |
| `adapter/codex_litmus.py:108` | `NativeTopology` maps logical epochs to real Codex history IDs | controlled Fork/Restore/Merge materialization evidence |
| `adapter/codex_litmus.py:181` | creates one controller DB and sink DB per policy/case and routes operations | current end-to-end orchestration pattern |
| `adapter/controller.py:81` | creates the authoritative semantic state | smallest home for plan metadata |
| `adapter/controller.py:124` | durable controller and SQLite schema | authoritative state outside the agent checkpoint domain |
| `adapter/controller.py:333` | computes an accepted successor on a private candidate copy | smallest semantic extension point |
| `adapter/controller.py:618` | `BEGIN IMMEDIATE`, load, check/transition, append event, update head, commit | required atomic plan-head and Prepare-to-ticket point |
| `adapter/worker.py:658` | applies one ordinary operation in a fresh worker process | topology/plan operations and crash-independent reopen |
| `adapter/worker.py:501` | owns hard-crash dispatch/recovery around the prepared ticket | crash-after-Prepare and ticket-use histories |
| `adapter/worker.py:713` | runner-facing dispatch wrapper | no plan should be consulted here after Prepare |
| `adapter/sink.py:81` | durable authenticated idempotent sink keyed by stable logical effect ID | physical outcome/attempt oracle |
| `adapter/replay.py:93` | independent semantic state reconstructed from deltas | must independently reconstruct the new plan fields |
| `adapter/replay.py:525` | independent operation-delta semantics | must reject malformed or inconsistent plan deltas |
| `adapter/litmus.yaml` | frozen C01--C20 streams for the previous runtime question | regression only; do not repurpose |
| `adapter/runtime-lock.json` | pins Codex 0.146.0, binary hash, experimental API, and scope | retain unchanged unless the binary actually changes |

## Durable storage boundary

For a normal retained run the files are:

```text
adapter/results/raw/runs/<policy>/<case>/controller.sqlite3
adapter/results/raw/runs/<policy>/<case>/sink.sqlite3
```

A fresh runner places the same pair below its caller-selected `--raw-dir`.
`controller.sqlite3` uses WAL mode and `synchronous=FULL`.  Its durable schema
has:

- singleton `controller_meta(policy, state_json, policy_json, sequence,
  head_hash)`;
- append-only `events(seq, previous_hash, event_hash, state_hash, kind,
  body_hash, body_json)`; and
- triggers rejecting event updates and deletion.

`state_json` is the correct home for the plan because it is part of the
semantic controller state and therefore covered by `state_hash` and the event
hash chain.  `policy_json` currently stores implementation-specific local
budgets/escrow and is the wrong home: putting the plan there would omit it from
independent semantic replay.  The controller DB is separate from Codex's
workspace/thread checkpoint material, exactly matching the accepted model's
authoritative `ControllerState = (lifecycle, plan)`.

The sink DB is separately durable.  It contains immutable aggregate outcomes,
append-only attempts, and a monotone revision.  Its `effect_id`/stable-key
uniqueness supplies the existing physical duplicate detector; it does not turn
the theorem's logical ticket claim into a general physical exactly-once claim.

## Current lifecycle hooks and their precise limits

| Operation | Controller semantics now | Native Codex hook now | Important limit |
|---|---|---|---|
| Checkpoint | stores `checkpoint -> logical branch` in controller state | none | not a workspace/process checkpoint; plan is correctly outside it |
| Fork | changes logical frontier/epochs/delegation and records choice or parallel kind | after controller acceptance, creates fresh ephemeral children with native `thread/fork` | every child currently forks the persistent seed boundary, not the logical source; logical ancestry is adapter metadata |
| Replacing Restore | replaces source with fresh target and closes source logically | creates a fresh native fork and labels it Restore | Codex does not supply native semantic Restore; controller commit and native activation are sequential |
| Live Restore | retains source and adds target in parallel logically | creates a fresh native fork | same limitation; replace/live meaning is adapter-owned |
| Merge | certified/direct logical merge in controller | creates a fresh native fork labelled `adapter_merge_target` | Codex has no native Merge; projection and meaning are adapter-owned |
| Prepare | changes one tentative claim to durable, creates a prepared ticket, and restricts insolvent frontiers | ordinary controller operation | no plan version/current slot/root/batch check yet |
| Dispatch | requires a prepared ticket, sets it inflight, then worker calls the protected sink | real pending `item/tool/call` | already uses ticket rather than current grant freshness |

`NativeTopology.accepted()` is called only after the controller accepts an
operation.  That leaves a topology-commit/native-materialization crash window
already documented by the project.  The approved adapter pilot need not claim
to close this window.  Closing it would require a larger activation protocol
(pre-create an inert native history, atomically register it with the controller,
then activate it) and is not the smallest supporting experiment.

## Smallest implementation surface

### 1. Add one semantic `plan` object to controller state

Extend `_semantic_state()` and the state validator with a nullable/current plan
whose scalar-demand runtime representation contains at least:

```text
plan_id
version
ordered_slots
current_slot
source_durable_baseline                  # per grant/resource coordinate
R[slot][grant]
P[slot][grant]
E[slot][grant]
W[slot][grant]
root_slot[current_claim]                 # computed Option slot
batch_root[current_batch_leaf]           # immutable source-batch identity
leaf_disposition[root] = remaining | prepared | withdrawn leaves
remaining_batch[slot]
```

Claim and grant epochs already exist in lifecycle state.  Do not accept a
caller-proposed target `root_slot`, target batch, `E/W` delta, target validity,
or `PrepareOK` flag.  On an admitted structural transfer, derive target roots
and target batch only from the current plan plus the checked source-to-target
claim map; compute withdrawal deltas after checking monotone demand loss.

The state is JSON for this pilot, but use canonical sorted encodings because it
is hashed.  The new plan belongs in `ReplayState.semantic_dict()` and in the
independent replay transition implementation, not merely in controller logs.

### 2. Put transport checks beside the existing lifecycle transition

The narrow code site is `DurableController._apply_candidate()`:

- Checkpoint and ticket phase steps stutter the unconsumed plan.
- Fork/Restore and certified same-slot Merge compare the offered head/version,
  run the existing lifecycle admission, then compute slot/root/batch transport
  from the current plan and operation's checked lineage relation.
- Cross-slot owner mixtures, copied batch/slot data, stale versions, later-slot
  Prepare, unplanned Reserve into a scheduled slot, and unmatched durable-load
  growth reject transport and request exact re-solving.
- Revoke/restriction computes withdrawn leaves and `W`; it never drops them by
  a caller-supplied Boolean.

For this pilot, the real Codex IDs remain evidence in `NativeTopology.events`;
the semantic plan is keyed by adapter logical epochs and immutable claim/slot
lineage.  Do not claim that Codex itself emits slot or authority metadata.

### 3. Extend the existing Prepare transaction, not the worker dispatch path

The current `prepare` arm already promotes the claim and mints a ticket on the
candidate state, and `apply()` commits that state and its event in one SQLite
transaction.  Extend this arm to:

1. compare the offered plan version with the durable current version;
2. select the nonempty group in the current slot;
3. validate fresh injective operation assignment and current
   claim/grant/owner epochs;
4. derive the capacity bound from `P`, current durable load, and live state;
5. promote the selected claims and install stable prepared tickets;
6. move their identity leaves from remaining to prepared, add demand to `E`,
   advance the cursor/version, and install the tail head; and
7. append the delta and update `controller_meta` in the same commit.

No plan data is passed to `dispatch_with_recovery()`.  After this commit,
Dispatch, Retry, Crash, Settle, and post-Prepare Revoke continue to operate on
the durable ticket and stable logical operation identity.  This is the runtime
counterpart of the accepted Prepare-to-ticket principle.

### 4. Keep plan-controlled histories separate from C01--C20

Do not edit the frozen `litmus.yaml`, `oracle.yaml`, or retained results.  Add a
small plan-pilot stream and runner/checker beside them, reusing
`CodexAppServer`, `NativeTopology`, `apply_in_worker`,
`dispatch_with_recovery`, and `AuthenticatedSink`.  The stream contains typed
operations and no expected labels.  A checker-only exact exhaustive solver
must independently recompute fresh serial orders/final-seal feasibility from
each raw pre-state; runtime modules must not import it.

This is the minimum extra experimental code.  The old P0--P3 policies are
regressions for the earlier authority experiment, not valid main baselines for
the new plan-transport RQ.

## Controlled history matrix

Use a small matrix that directly engages the accepted mechanism:

| History | Purpose | Required observation |
|---|---|---|
| positive disjoint mutation | mutation touches an unplanned `none`-slot owner | semantic transport reuses; global-version baseline re-solves; exact oracle agrees reuse is safe |
| two-depth same-slot refinement | native Fork then replacing/live Restore fragments one slot with computed lineage | semantic transport reuses at both depths; no caller-supplied child slot/batch |
| same-slot coarsening | Merge descendants that inherit one immutable root slot | transport accepts; exact oracle agrees |
| partial Prepare then refinement | Prepare one current-slot group, refine/coarsen the remaining same-slot fragment, then Prepare tail | version/cursor, `E/W`, identity disposition, and next-group order all advance correctly |
| stale restored head | present a checkpoint-era plan version after current head advanced | reject stale CAS; no ticket or sink attempt |
| later-slot Prepare | request Prepare from a later slot while an earlier nonempty group remains | reject; zero later-slot tickets/attempts |
| cross-slot Merge | instantiate the accepted `K=4` witness (`a:(1,1), b:(1,2), c:(1,2), d:(1,1)`; merge `a,c` and `b,d`) | base authority remains admissible but plan transport rejects; per-object observation incorrectly reuses; exact serial re-solve finds no order, while full atomic seal remains feasible |
| copied batch or unmatched durable growth | try to reuse caller-copied `P`/batch or create a durable increase outside planned Prepare | reject/invalidate and no dispatch |
| crash before Prepare commit | kill before the atomic plan/ticket commit | old head and no ticket survive; zero sink outcomes |
| crash after Prepare, before dispatch | commit new head/ticket, kill worker, then recover | new head and prepared ticket survive; exactly one eventual outcome |
| post-Prepare Revoke | Prepare, revoke the old grant epoch, then Dispatch/retry/settle | dispatch uses the stable ticket and original binding; one outcome/receipt; fresh tentative use rejects |

One real native Fork plus the protected dynamic-tool call is enough to establish
the Codex integration boundary.  The remaining finite histories may reuse the
same runner/controller path; do not present synthetic case count as workload
prevalence.

## Comparisons

The comparison roles from the accepted plan should be implemented exactly:

1. **Proposed semantic transport:** computed slot/root/batch dependency,
   current-head CAS, and atomic Prepare-to-ticket.
2. **Global-version baseline (current-practice conservative baseline):** any
   durable lifecycle version change invalidates the plan and invokes exact
   re-solving before the next planned Prepare.
3. **Per-object dependency baseline (strongest local-cache alternative):**
   reuse when named claim/grant IDs, demand, phase, and epochs are unchanged;
   intentionally does not observe owner/co-durability topology.  The cross-slot
   indistinguishability history determines whether it is unsound.
4. **Exact re-solve oracle/control:** enumerate all current owner orders (or
   exact peeling) from the live state after every relevant mutation.  Every
   proposed positive transport must agree with it.
5. **Full atomic-seal baseline:** validate and Prepare the entire remaining
   batch atomically when feasible.  Record coordination/seal size; it buys no
   serial certificate reuse.
6. **Commit-time authorization recheck:** targeted lifecycle control, not a
   broad performance baseline.  Rechecking the old grant at Dispatch should
   reject after Revoke, whereas a correctly prepared durable ticket dispatches.

Do not promote the old P0, P1, or P2 policies, workspace-only rollback, or an
always-accept policy as new baselines: they do not answer the frozen RQ.

## Metrics and exact counting rules

Primary supporting metrics:

- **decision agreement with exact re-solving:** confusion table over each
  attempted transport (`safe reuse`, `replan required`) plus named mismatch;
- **transport reuse rate:** accepted transports divided by all structural
  mutations for which the exact oracle says the old residual plan remains
  executable; also report the raw numerator/denominator;
- **global re-solves avoided:** `global_version_resolves -
  semantic_transport_resolves`, as an exact count on the same histories;
- **unsafe reuse / false invalidation counts:** especially per-object
  cross-slot acceptance and global-version disjoint-mutation rejection;
- **stale-version and cross-slot rejection counts:** raw counts, with zero
  tickets and sink attempts on each rejected path;
- **serial progress:** number of admitted head groups, forbidden later-slot
  Prepare count, residual groups, and final-seal size;
- **ticket outcomes:** plan version before/after Prepare, stable
  `(effect_id, claim_id)` binding, ticket phase, sink attempt count, aggregate
  outcome count, and controller receipt across each crash/Revoke history; and
- **descriptive local cost:** certificate-check and exact re-solve elapsed time
  on identical frozen prestates.  Use repeated local trials and report raw
  samples plus median and interquartile range; make no general performance or
  prevalence claim.

Correctness vetoes any apparent reuse/latency win if the exact solver disagrees,
the proposed checker did not engage, the native tool callback was bypassed, a
rejected operation produced a ticket/sink attempt, replay does not reconstruct
the same semantic head, or compared methods receive different prestates.

## Minimal real test command after implementation

The thinnest end-to-end test should be one test method, not the full matrix:

```bash
cd /home/yunwei37/workspace/my-paper-work/agent-check-restore-safety
python -W always::ResourceWarning -m unittest -v \
  adapter.test_plan_pilot.RealPlanPilotTests.test_native_fork_prepare_revoke_dispatch
```

That test must launch the pinned real App Server, obtain a native fork ID,
transport one computed child batch/root slot against the current head, perform
one atomic planned Prepare, reopen or crash/restart the controller, Revoke, and
Dispatch once through the pending dynamic-tool callback.  Passing this command
is only an implementation preflight.  The full pilot must then run every
controlled history and comparison, retain raw JSONL/SQLite/timing samples, run
the independent exact checker/replay, and finally rerun the existing regression:

```bash
python -W always::ResourceWarning -m unittest discover -v adapter
```

The proposed test module does not yet exist; this report does not implement it.

## Scope and nonclaims

- The adapter owns choice/parallel, replacing/live Restore, Merge, slot, and
  authority meanings.  Codex supplies thread IDs, native fork boundaries, and
  the dynamic-tool callback only.
- The pilot can test sequential SQLite atomicity and crash recovery.  It does
  not prove concurrent linearizability, power-loss durability, or atomicity
  between controller topology commit and native history activation.
- It mediates only the isolated `protected_commit` tool/sink.  Built-in shell,
  MCP, web, network, frontend/App Server death, and direct database access
  remain outside scope.
- Exact solver agreement on controlled histories is supporting feasibility
  evidence.  The formal theorem and observation lower bound carry the main
  claim; the adapter cannot rescue a missing formal bridge.
- Public traces motivate heterogeneous effects and missing metadata but cannot
  label rollback unsafety or supply trusted slot/authority ground truth.

## Read-only SQLite audit note

During this scout, querying the retained P3/C01 schemas through SQLite created
four untracked WAL/SHM sidecars despite the connection being opened for a
read-only inspection.  The query process exited, `lsof` showed no open handles,
and the files were an empty WAL plus transient SHM pages.  After explicit
authorization, only these four exact untracked sidecars were removed.  Neither
`controller.sqlite3` nor `sink.sqlite3` was deleted or modified; Git reports no
tracked adapter-result change.

