# Experiment Plan: Transportable authority plans across agent history changes

**Revision 2 status:** revised after the independent round-1 `REVISE` verdict.
No Lean experiment is authorized until an independent reviewer accepts this
revision.  Revision 2 chooses the honest narrow effect design: before Prepare,
the theorem preserves claim/grant/slot/batch authority, not a nonexistent
effect assignment; the stable logical operation binding is created by the
actual atomic Prepare transition.

## Frozen Research Question

- **RQ2': When may a history-transforming agent runtime transport an already
  checked promotion plan across Fork, Restore, Merge, and partial Prepare,
  rather than globally re-solve the plan or atomically seal the whole batch?**
- This replaces the attempted Step 0006 headline that arbitrary-order safety
  itself was the main novelty.  Static deadline compilation, backward peeling,
  obstruction cores, and final sealing remain useful supporting algorithms,
  but the closest-work audit found their abstract scheduling and pruning
  structure in prior work.
- The uncertainty tested here is whether one can prove a genuinely
  lifecycle-level continuity theorem over the repository's real
  `LifecycleState`, checked `Transfer`, canonical Fork/Restore operations,
  explicit Merge, exact `PrepareOK`/`prepareState`, and ticket subrelation.  A
  disconnected list-scheduling theorem is not enough.

## Frozen Hypothesis

For a fixed, valid claim batch reserving authority for future effects in an
initially `LWF`/`AC` lifecycle state, a
checked safe owner order can be represented by ordered lineage slots with
separate residual envelopes for all tentative demand and for the promoted
batch.  The following plan grammar preserves the unconsumed plan tail:

1. restriction, Select, Abort, and Revoke delete claims or slots;
2. canonical Fork/Restore and checked same-slot Merge refine one source slot
   into a contiguous target fiber while separately conserving tentative and
   promoted demand;
3. current-slot owner-group Prepare atomically checks the live epoch, grant,
   claim, fresh operation assignment, capacity, and authoritative plan version;
   consumes the plan head; applies
   the repository's exact `prepareState`; and installs durable prepared
   tickets; and
4. Dispatch, crash, retry, and settle operate only on the durable ticket and
   stutter on the remaining plan.

Under those rules, every finite admitted plan trace preserves lifecycle
well-formedness, authority continuity, terminal/epoch monotonicity, stable
bindings, safety of the residual plan, construction of actual `PrepareOK` for
the next nonempty group and any accepted fresh assignment, and
durable-before-attempt.  In particular, a successful planned
Prepare linearizes authority consumption: later Revoke, Restore, or plan-version
change cannot invalidate the already minted ticket, and Dispatch must not
re-check the consumed plan.

The ticket denotes one non-rebindable **logical operation identity**.  The LTS
allows retry from `inflight` or `uncertain`, so neither this hypothesis nor the
paper may infer one physical attempt or exactly-once external execution.
Concrete safety continues to require mediation and the aggregate sink-outcome
bound already explicit in `Trace.lean`.

The theorem is deliberately one-sided.  Cross-slot Merge/coarsening,
cross-slot interleaving, copied promotion budget, unmatched durable-load
increase or capacity decrease, fresh Reserve into a planned owner, batch
growth, and owner/claim epoch or post-Prepare effect rebinding are **not generally
preservative**.  Each needs a concrete counterexample and must cause rejection,
replanning, or an atomic seal.  This experiment does not claim that the listed
positive rules are the weakest possible conditions.

## Paper-Value Admission

- Planned role: decisive theory evidence plus a small systems feasibility
  check.
- Largest credible paper story unlocked: a checked promotion plan is a
  **linear capability over future Prepare transitions**.  Fork refines it
  rather than copying it; Restore can transport only a lineage-preserving
  residual fragment; cross-slot Merge loses the proof; Prepare consumes the
  head and yields a durable, non-rebindable logical-operation ticket that
  authorizes Dispatch and retry.
  This connects agent history transformation to capability continuity without
  reducing the problem to generic workspace rollback.
- Strongest reviewer rejection addressed: “versioned schedule certificates”
  may otherwise be only proof-carrying plans plus cache invalidation/OCC, while
  the slot theorem may be only compositional scheduling under new names.  To
  survive, the result must connect checked claim transfer to both demand
  envelopes, actual cleanup/Prepare semantics, and the Prepare-to-ticket
  boundary over arbitrary finite lifecycle traces.
- Independent evidence beyond prior runs: Step 0006 failed to compile its
  attempted serialization proof and changed no paper claim.  This experiment
  freezes a materially different theorem, adds computed promoted-batch lineage
  accounting, proves a trace-level plan-transport result over actual
  lifecycle rules, mechanizes invalidation counterexamples, and—only after the
  proof succeeds—tests the checker in the existing dispatch-owning adapter.
- Novelty gate: the positive result is decisive only if it also proves the
  frozen observation lower bound below.  Fiber/slot preservation without that
  lower bound is supporting authority-LTS refinement, not enough by itself to
  center RQ2.
- Why this is not already settled by the static audit: the known peeling and
  AND/OR results decide one immutable batch.  They do not say whether an
  unconsumed authority proof survives agent Fork/Restore/Merge, how a plan is
  consumed without duplication, or when the plan ceases to matter because a
  durable ticket has been minted.
- Paper decision if positive: center RQ2 on lifecycle transport of a linear
  authority plan; present static scheduling/core/seal results as compiled
  machinery and credited supporting structure; make Prepare-to-ticket the
  operational linearization point.
- Paper decision if negative: if the actual `Transfer` and `Prepare` semantics
  do not support the induction, remove plan transport as a contribution and
  retain only recompute-or-seal; if a primary theorem subsumes the whole
  lifecycle result under a faithful translation, cite and demote it; if a
  positive grammar is too narrow to cover canonical runtime histories, do not
  claim practical certificate reuse.
- Best alternative and why this has higher decision value: minimum-cost final
  sealing has verified useful special cases but a high closest-work ceiling;
  another large trace scan cannot recover missing authority ground truth.  The
  present experiment directly tests the surviving agent-specific novelty.

## Published Precedent And Novelty Baselines

- Proof-carrying code, proof-carrying authorization/file systems, and
  proof-carrying plans own the generic idea that a certificate gates execution.
- Proof-Carrying Agent Actions and “No Certificate, No Execution” own current
  agent-action certificate architectures.
- Optimistic concurrency control, authorization-cache invalidation, Zanzibar,
  escrow, reservation protocols, and two-phase Prepare own generic versions,
  leases, reservations, and atomic validation.
- Commit-Time Authorization owns rechecking a witness at the durable-effect
  boundary.  The proposed result differs only if it proves semantic transport
  of the unconsumed plan and then makes the consumed plan irrelevant: actual
  Dispatch relies on the durable ticket, not on freshness of the old witness.
- Iris authoritative resource algebras, linear/resource-aware session types,
  and component/interface refinement own generic linear splitting,
  phase/resource discipline, and schedulability-preserving refinement.
- Dynamic event structures and dynamic causality own changing event relations;
  configuration structures, partial-order reduction, AND/OR precedence,
  antimatroid pruning, generalized deadlock repair, and scheduling with
  rejection own the static order/core substrate.
- Crab and ACRFence own the broad 2026 observation that agent checkpoint,
  restore, fork, and replay interact with external effects and authority.  The
  proposed claim must therefore remain the co-durable authority-plan transport
  theorem and its checked runtime boundary, not “rollback is unsafe.”

The source-by-source separation table is frozen in
`certificate-closest/report.md`; the plan may not fill a missing operator in a
baseline silently.  A definition-preserving prior theorem that derives the
same actual lifecycle result counts as a baseline win.

## Formal Object And Invariants

The new Lean development must extend the existing model, not replace it.
Runtime hashes are representation details; Lean uses record equality and
finite maps.

### Authoritative extended state

The formal transition system is over one durable controller state
`ControllerState = (lifecycle, plan)`.  The `lifecycle` projection is the
existing `LifecycleState`; `plan` is unique authoritative controller data, not
an agent-supplied proof object and not part of the reconstructable workspace
snapshot.  It contains:

- immutable source capacity and durable-load baseline, a finite source batch,
  and a finite ordered set of root slots;
- source slot envelopes `R_i` (the complete tentative bundle of a scheduled
  source owner) and `P_i` (the selected batch demand), with `P_i <= R_i`
  componentwise;
- a monotonically advancing head/version and the current slot cursor;
- a computed partial `rootSlot : Claim -> Option Slot` over every current
  tentative claim (and `none` elsewhere), plus a computed batch-root lineage
  for current batch fragments;
- a discrete per-root lineage-leaf ledger partitioning every extant batch leaf
  into `remaining`, `prepared`, or `withdrawn`, so zero-demand claims cannot
  disappear merely because vector accounting cannot see them;
- componentwise per-slot ledgers `E_i` for batch demand already Prepared and
  `W_i` for batch demand explicitly/computably withdrawn; and
- the current remaining batch, plus optional final-seal root slots under an
  explicit valid-full-atomic-batch premise.

Every tentative claim of a scheduled source owner receives that owner's root
slot, including non-batch claims charged by `R_i`; claims of unrelated owners
receive `none`.  A structural transfer does not accept a target slot map.  It
computes

```text
rootSlot'(c') = rootSlot(c)  when Transfer.rho(c') = some c,
rootSlot'(c') = none         otherwise.
```

Composition therefore preserves the immutable root through arbitrary depth.
An executable owner-purity checker rejects a target owner whose tentative
claims come from two root slots or mix a planned `some i` lineage with an
unplanned `none` lineage.  “Same-slot Merge” is a theorem about this computed
map, not a trusted operation label or caller proposition.

Checkpoint does not copy `plan` into the workspace.  Fork/Restore/Merge submit
an operation against the current controller head and receive a newly computed
head; they cannot install a historical plan value.  `PreparePlanned` compares
an offered version with the authoritative head, constructs and projects to the
actual `CoreStep.prepare`, moves demand to `E`, and advances the head in one
abstract transition.  Ticket steps stutter on the unconsumed plan.  This proves
a sequential atomic specification; concurrent linearizability remains an
implementation obligation tested against the controller's SQLite transaction,
not something inferred from a natural-number version.

### Computed batch-lineage accounting

The existing `Transfer.CoreValid.fiber_demand` proves conservation of all
tentative demand.  It does not identify the selected promoted batch.  The child
batch is therefore computed, never proposed:

```text
U' = { c' | exists c in U, Transfer.rho(c') = some c }.
```

Every leaf of every source batch-root lineage is accounted for discretely as a
current remaining fragment, an actually Prepared claim, or an explicitly
withdrawn/terminal leaf.  A root may have leaves in more than one category
after fragmentation and partial Prepare, but no leaf is in two categories and
no root silently loses its last leaf.  This identity ledger is authoritative
even for zero-demand claims.  The vector ledgers separately account for demand
in current fragments, already in `E`, or in `W`.  A topology transfer computes any
conservative demand loss only after deriving `B'_i <= B_i`, using the
componentwise definition `delta_i = B_i - B'_i` and
`W'_i = W_i + delta_i`; restriction/Revoke uses an explicit drop transition
and the same computed update.  Neither `delta` nor `W'` is caller supplied.  It is not
legal to pick `U' = empty` while leaving disappearance unexplained.  Batch
copying or substitution is rejected because target membership and batch-root
lineage derive solely from the current batch and checked `rho`.  Terminal-ID
monotonicity and the authoritative head prevent an old source fragment from
being replayed after consumption or withdrawal.

Before Prepare there is deliberately no claimed effect assignment: the current
base LTS has none.  `PreparePlanned` accepts a proposed operation assignment and
runs a finite assignment checker against the current group and actual
`A.opClaim`; soundness derives `assigned_mem`, `covered`,
`assignment_injective`, and `fresh`.  Plan validity plus actual `LWF` derives
the tentative/open/grant premises, and schedule arithmetic derives `base`.
The operation-to-claim binding becomes authoritative and non-rebindable only
when the actual `prepareState` installs the prepared ticket.

### Complete residual invariant

All equations below are componentwise for every resource coordinate.  Let
`d_0` be the source durable load, `d_t` the current durable load, `L_i` all
current tentative demand owned by descendants of slot `i` (batch and
non-batch), and `B_i` the remaining fixed-batch fragments in that slot.  A
valid controller plan requires:

```text
d_t = d_0 + sum_i E_i
L_i + E_i <= R_i
B_i + E_i + W_i = P_i
```

It also requires current batch fragments to be nonterminal tentative claims;
the discrete lineage-leaf partition above; computed slot purity; stable grant
metadata and monotone epochs; a safe source slot order; contiguous current
fibers in that order; and a cursor at the first slot whose **remaining batch
Finset is nonempty**, irrespective of its demand vector.  Within that slot the
next owner group is likewise selected by claim nonemptiness, not positive
demand.  Owners with only non-batch tentative demand remain charged in `L_i`
but are not scheduled for an empty Prepare, respecting
`PrepareOK.nonempty`.

Unplanned Prepare, fresh Reserve into a planned slot, capacity decrease, and
unmatched durable promotion have no plan-preserving constructor: they must
lose the version check or occur only after explicit invalidation/replanning.
Capacity increase and mutations proved disjoint may be added only through a
sound primitive checker.  No constructor may take target `PlanValid`, target
slot bounds, or next-Prepare readiness as an input.

## Frozen Theorem Matrix

Names may change for Lean style, but logical scope may not be weakened after a
failed proof without a new reviewed plan.

| Theorem or witness | Required connection | Success condition |
|---|---|---|
| `singleton_support_iff_deadline` | actual `State`, owner groups, exact `preparedCore` support | compiles the next-group support query to vector arithmetic under explicit WF/AC/fixed-batch premises |
| `block_expansion_safe` | arbitrary finite vector slots/fibers | any internal order inside contiguous fibers is safe when both `R` and `P` sums are conserved and each `p_x <= r_x` |
| `computed_batch_promoted_bound` | child batch/root map computed from current batch and checked `Transfer.rho` | derives target promoted-fiber load, the discrete per-root leaf disposition, and exact `E/W/remaining` demand accounting—including zero-demand claims; no caller chooses `U'` |
| `canonical_transfer_slot_bounds` | actual `checkCanonical`/`canonicalTarget`, emitted `Transfer.Valid`, and computed root-slot inheritance | derives, rather than assumes, residual slot bounds and owner purity for an admitted Fork/Restore subclass |
| `restriction_transports_plan` | actual restriction/revoke target plus computed withdrawal | deletion projects a valid plan, accounts removed batch demand in `W`, and optionally lifts a seal |
| `same_slot_merge_transports` | actual checked `MergeDescriptor` plus computed root slots/batch lineage | conservatively coarsening one computed root slot preserves the plan; ordinary simulation admission alone is insufficient |
| `assignment_check_sound` | finite checker over current group, offered assignment, and actual `opClaim` | derives exactly `assigned_mem`, `covered`, injectivity, and freshness; no pre-Prepare semantic-effect claim |
| `prepare_head_is_ok` | actual live state, current nonempty group, assignment-check output, source invariants | constructs every field of the repository's real `PrepareOK`; it may not assume `PrepareOK` as a certificate field |
| `prepare_head_advances_plan` | atomic authoritative-head check plus actual `prepareState`, exact cleanup, ticket installation | consumes one current-slot group, moves demand to `E`, preserves the tail, advances the unique head, and installs prepared tickets |
| `planned_step_preserves` | explicit extended-controller subrelation projecting to actual `Step` | each positive grammar rule computes its target plan and preserves lifecycle plus plan invariants |
| `planned_trace_preserves` | reflexive-transitive closure | arbitrary finite admitted histories preserve `LWF`, `AC`, plan validity, monotonicity, stable bindings, and next-Prepare readiness |
| `prepared_ticket_survives_plan_change` | actual ticket/revoke/topology rules | after Prepare, Dispatch/retry/crash/settle use one stable logical binding and do not require the old plan version; no physical at-most-once conclusion |
| `version_observation_lower_bound` | two pairs of finite states and a quantified decision function over a frozen observation type | global equality rejects a genuinely transport-safe mutation, while claim/grant-version-only observation cannot distinguish a safe history from a topology-only plan-invalidating history; topology/slot lineage is therefore a necessary dependency for this class |
| negative examples | executable finite instances over actual or faithfully instantiated model | cross-slot Merge, cross-slot interleaving, copied `P`, unmatched durable increase, and stale restored version each break transport or are rejected |

The central claim fails if the full trace theorem ranges only over an abstract
list rewrite, if a certificate contains target `LWF`/`AC`/`PrepareOK` as an
input, if the next owner is made ready by definition, or if the proof never
touches `Transfer`, `prepareState`, and `Step`.

The observation theorem is the novelty gate, not a performance anecdote.  Its
claim is relative to a frozen observation footprint, not to all imaginable
cache schemes.  Freeze `LocalAuthObs` to the old plan ID plus current capacity,
durable load, and each scheduled claim's ID, demand, grant, coarse
tentative/durable/terminal phase, and grant epoch; it deliberately erases the
tentative owner, branch-correlation contract, transfer root, and owner-slot
grouping.  This models a dependency cache over immutable credential/resource
objects but not co-durability topology.  The safe source/current history and
the simulation-admitted cross-slot-coarsened history have equal
`LocalAuthObs`, yet only the former retains the old plan.  Therefore every
decision function solely over this observation must either accept the unsafe
history or reject its safe counterpart.  This is an information result, not a
claim that every per-object version design omits topology.

Conversely, `GlobalObs` is equality of the entire durable controller version.
It distinguishes those histories but also rejects a separate mutation confined
to an unplanned `none`-slot owner, for which plan preservation is proved.  The
proposed observation adds computed root-slot/batch lineage and the plan-relevant
topology projection, separating both pairs.  If these equalities, safety facts,
and the quantified decision-function corollary do not kernel-check, the
transport theorem is classified as supporting rather than headline evidence.

### Frozen constructor-premise audit

| Extended controller step | Permitted source evidence | Computed target; forbidden shortcuts |
|---|---|---|
| checkpoint / ticket phase | source plan validity and an actual existing `Step` | plan stutters; no target invariant premise |
| canonical transport | successful actual `checkCanonical`, successful current-head comparison, immutable current plan | lifecycle is `canonicalTarget`; root slots, child batch, `W`, cursor, and new head are functions of source plan and `rho`; no target slot map or `PlanValid` |
| restriction / Revoke drop | actual restriction/Revoke parameters and current head | lifecycle target is existing computed target; removed batch demand is computed into `W`; no Boolean “relaxing” flag |
| checked Merge transport | actual simulation/direct admission, current-head comparison, computed owner-purity and batch-accounting checkers | lifecycle is `MergeDescriptor.target`; plan transport is rejected if computed roots mix; no caller assertion of “same slot” |
| `PreparePlanned` | source `LWF`/`AC`/plan validity, successful current-head checker, successful assignment checker, current nonempty group | proves `PrepareOK`, projects to exact `prepareState`, moves demand into `E`, installs tickets, and advances head atomically; target readiness/`PrepareOK`/`PlanValid` are forbidden premises |
| invalidate/replan | explicit termination of the old head followed by the independently checked static solver | not a transport-preservation constructor and not usable inside the positive trace theorem to hide an unsupported mutation |

The result audit rejects any theorem whose constructor or record contains target
`LWF`, target `AC`, target `ActiveExact`, target `PrepareOK`, target
`PlanValid`, residual schedule safety, an independently chosen target slot or
batch, equality of an offered/current head asserted rather than checked, or a
pre-Prepare effect binding self-authenticated by certificate fields.

## Comparison And Controls

- **Proposed method:** semantic slot transport with plan-head CAS and
  Prepare-to-ticket conversion.
- **Global-version baseline:** invalidate and globally re-solve after every
  lifecycle mutation.  It is safe but may reject reuse after a disjoint or
  conservative same-slot change.
- **Per-object dependency baseline:** reuse when named claim/credential objects
  and their versions are unchanged.  A topology-only change can alter
  co-durability while leaving those versions untouched; a frozen finite
  witness must demonstrate the unsoundness.
- **Recompute oracle:** reconstruct the current owner deadlines and run exact
  peeling/final-seal verification from scratch.  Every transported positive
  certificate must agree with it.
- **Full atomic-seal baseline:** coordinate the entire remaining batch.  It is
  safe when the valid-full-batch premise holds but buys no serial reuse.
- **Commit-time recheck baseline:** revalidate the original authorization
  witness at Dispatch.  The proposed lifecycle instead validates at atomic
  Prepare and dispatches/retries from the durable non-rebindable ticket; a
  post-Prepare Revoke history distinguishes them.
- **Ablations:** remove tentative-demand conservation, promoted-batch
  conservation, `p<=r`, fiber contiguity, slot purity, version CAS, stable
  epochs/bindings, full-batch validity, or durable ticket installation.  Each
  removed load-bearing premise needs a counterexample or a derivation from the
  remaining assumptions.

No performance or prevalence claim is admitted from synthetic controls.  The
comparisons test semantic agreement, reuse, and invalidation behavior.

## Real Trace Evidence And Its Limit

The completed Trace Commons audit at pinned commit
`112ebd4d03ce852b00e935d523107c3d0c9a65bf` found 30 sessions, 18,012 events,
4,264 tool calls, 4,262 tool results, 269 explicit errors, and 953 file-history
snapshots.  The commands include Git push, network, process/service, database,
package, and deployment shapes.  TraceLab independently supplies scale (8,058
sessions and 743,819 tool calls).

These data justify the heterogeneous external-effect workload and the need for
runtime metadata.  They do **not** contain trusted Fork/Restore events,
authority/grant lineage, conditional-versus-durable phase, receipts,
compensation, or idempotence.  Consequently:

- use the public traces for workload/schema and observability-gap evidence;
- do not label individual histories unsafe or estimate unsafe-rollback
  prevalence; and
- use controlled adapter histories for theorem-premise and runtime-checker
  evaluation.

## Workloads And Metrics

### Mechanization workloads

1. an arbitrary finite source order and arbitrary finite same-slot fibers;
2. a real canonical Fork/Restore transfer with batch refinement;
3. restriction/Revoke and a checked same-slot Merge;
4. a multi-round history with two refinements, partial current-slot Prepare,
   further same-slot refinement/coarsening, then remaining Prepare;
5. crash before Prepare, crash after Prepare, and post-Prepare Revoke followed
   by ticket Dispatch/retry/settle; and
6. smallest negative instances for every invalidation boundary.

### Formal primary metrics

- kernel acceptance with no `sorry`, `admit`, project axiom, or synthetic
  desired-result field;
- exact theorem assumptions and `#print axioms` output;
- fresh `leanchecker --fresh AuthorityContinuity.Main` replay;
- agreement of finite examples with direct `native_decide`/exhaustive
  recomputation; and
- whether the full theorem imports and uses the actual lifecycle modules.

### Runtime feasibility metrics, only after formal success

- decision agreement with exact global re-solving;
- transported-certificate reuse rate on controlled positive histories;
- exact number of global re-solves avoided;
- stale-version and cross-slot rejection counts;
- admitted serial batches and final-seal size/cost;
- certificate-check and re-solve latency, reported descriptively with repeated
  local trials; and
- dispatch result for crash-before/after-Prepare and post-Prepare Revoke.

## Planned Runs And Attempt Budget

| Run group | Role | Real asset | Frozen decision consequence |
|---|---|---|---|
| formal preflight | dependency and early falsification | pinned Lean/Mathlib project and one existing/minimal actual lifecycle fixture | within at most three retained attempts, compile one thin vertical path: actual canonical transfer, one computed slot/batch bound, authoritative-head `PreparePlanned`, one plan-stuttering Revoke/topology step, then ticket Dispatch; otherwise stop as inconclusive |
| general fiber/slot proof | main theory | new module importing actual `Transfer`/`Step` | prove the frozen theorem matrix without circular certificate fields |
| lifecycle trace proof | main theory | actual `Step`, `prepareState`, ticket rules | arbitrary finite planned traces preserve both base safety and residual plan validity |
| negative suite | boundary controls | finite executable instances | every excluded rule is either rejected by a checker or has a smallest plan-invalidating witness |
| adapter pilot | feasibility evidence | existing dispatch-owning Codex adapter | only after mechanization succeeds, compare semantic transport with global version, per-object reuse, exact re-solve, and full seal |
| regression/audit | integrity | repository scripts and clean build | all prior authoritative results remain valid; no failed source remains under the Lean source glob |

There are at most **three real preflight attempts**.  Every command, source
snapshot, diagnostic, and exit code is retained.  A fourth attempt is
forbidden without a new user-visible research decision and new independently
reviewed plan.  A proof-engineering failure is inconclusive, not theorem
counterevidence.  No paper claim changes until an independent result review.
One attempt means one retained invocation of the approved end-to-end Lean
command against one frozen source snapshot.  Additional hidden `lake env lean`
or editor elaboration invocations count as attempts; read-only source inspection
does not.

## Real Preflight Case

The admitted preflight is intentionally a thin vertical path:

1. reuse an existing checked fixture where possible, or construct one minimal
   finite `LWF`/`AC` source with a nonempty fixed batch and authoritative plan;
2. run one actual admitted canonical Fork/Restore transfer and derive one
   target `R` bound plus one computed child-batch `P` bound from `rho`;
3. run the finite assignment and current-head checkers, construct every field
   of actual `PrepareOK`, project `PreparePlanned` to `prepareState`, advance the
   authoritative head, and inspect the prepared ticket; and
4. apply one actual plan-stuttering Revoke or topology step, then an actual
   ticket Dispatch, proving that the consumed old plan is not consulted.

The general block theorem, second refinement, same-slot Merge, observation
lower bound, and simulation-admitted cross-slot counterexample belong to the
full run.  A small negative Boolean check may be included only if it reuses the
same fixture and proof path.  A generic `List` theorem alone does not pass.

## Run Completion And Positive-Support Rule

The **run** is complete when the plan was independently accepted before source
creation; the allowed attempts and full commands reached a recorded terminal
result; failed sources were retained outside the Lake glob; regression and
axiom evidence were captured when executable; and an independent result review
classified every frozen row as proved, refuted, failed, or unattempted.  Run
completion is not positive evidence.

A **positive result** requires all of the following, without reviewer waiver:

1. preflight succeeds within the three-attempt budget;
2. computed root-slot and exact remaining/`E`/`W` batch-accounting bridges
   kernel-check over actual checked transfer;
3. atomic authoritative-head `PreparePlanned` constructs real `PrepareOK`,
   projects to exact `prepareState`, preserves the tail, and installs tickets;
4. the positive grammar projects to actual lifecycle steps and the arbitrary
   finite `planned_trace_preserves` theorem kernel-checks;
5. the simulation-admitted cross-slot Merge witness demonstrates that base
   `LWF`/`AC` is insufficient for plan continuity;
6. the post-Prepare ticket theorem proves stable logical binding and
   durable-before-attempt without consulting the consumed plan;
7. the quantified `version_observation_lower_bound` kernel-checks; otherwise
   the formal transport result is supporting, not headline/decisive evidence;
8. clean `lake build AuthorityContinuity`, `./scripts/audit.sh`, explicit
   `#print axioms`, fresh kernel replay, and relevant artifact regressions pass;
   and
9. the independent result reviewer finds no forbidden circular premise from
   the frozen constructor audit.

The adapter pilot is supporting feasibility evidence after formal success.  It
is not required for the mathematical theorem to be true and cannot rescue a
missing formal bridge.  It runs only if slot/head/batch metadata can be added to
the existing durable controller without pretending that Codex or Claude
natively emits those fields.

## Execution And Recovery

- Worktree: `/home/yunwei37/workspace/my-paper-work/agent-check-restore-safety`.
- Authoritative Lean workflow: from `lean/`, build the pinned project with
  `lake build AuthorityContinuity`, then run `./scripts/audit.sh`; final
  validation includes a clean build/cache restore and fresh kernel replay.
- Proposed source placement after plan approval:
  `lean/AuthorityContinuity/Plan.lean` and, if needed,
  `lean/AuthorityContinuity/PlanExamples.lean`.  A failed attempt is copied as
  text into this experiment directory and removed from the Lake source glob
  before regression validation.
- Raw logs and snapshots live below this `experiment-001/` directory.
- During experiment execution, `docs/paper/`, `docs/idea-story.md`,
  `docs/design.md`, `docs/evaluation.md`, and `docs/user-instruction.md` are
  read-only.  The user's latest instruction is already recorded verbatim as
  Message 16.

## Interpretation

- **Positive:** the actual lifecycle bridge, arbitrary-trace theorem, negative
  boundaries, quantified observation lower bound, and kernel audit pass.  The
  paper may claim plan-capability transport for the explicit grammar, the
  necessity of topology/slot lineage for the frozen observation class, and a
  Prepare-to-ticket linearization principle—not globally optimal transport,
  weakest conditions, or physical exactly-once execution.
- **Negative:** a counterexample inside the positive grammar refutes the
  hypothesis; correct the model and remove the claim.  A closest primary
  theorem with a faithful actual-lifecycle translation demotes novelty even if
  Lean succeeds.
- **Mixed:** abstract fiber/slot preservation without the actual transfer and
  Prepare bridge is supporting mathematics only.  A valid theorem with
  negligible controlled reuse supports theory but not an efficiency claim.
  Missing runtime metadata makes the adapter result inconclusive, not positive.
- **Inconclusive:** exhausting the three preflight attempts, incomplete kernel
  replay, or unresolved circularity produces no new paper claim and triggers an
  independent result review.

## Target Paper Evidence

If admitted by the result review, the paper receives:

- one lifecycle diagram showing plan capability refinement, head consumption,
  and durable ticket use;
- one theorem table separating transport-preserving operations from explicit
  revalidation boundaries;
- one small evaluation table comparing semantic transport, global invalidation,
  per-object reuse, exact re-solving, and full seal on controlled histories;
- one public-trace schema table showing which required authority fields are
  absent; and
- explicit limitations: conditional theorem over complete mediation and
  checked lifecycle adapters, no unsafe-prevalence estimate, no recovery of an
  external effect already executed outside the protocol, and no claim that
  cryptographic hashes prove semantic equality.
