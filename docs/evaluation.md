# Evaluation Contract

**Status:** theory-first CSF 2027 evidence plan and repository truth as of 2026-08-01. A number is a result only when a checked-in command reproduces it.

## 1. Evidence hierarchy

This is not a throughput paper. Evidence is ranked as follows:

1. precise definitions and proofs with explicit assumptions;
2. mechanized proofs of the finite core;
3. exhaustive executable checks and minimal counterexamples for nearby wrong rules;
4. deterministic instantiation of the lifecycle in real runtime interfaces;
5. microbenchmarks only for a mechanism that actually enforces complete mediation.

The intended scientific allocation is roughly 70--80% model, theorem, and proof; 10--15% mechanization/exhaustive validation; and 10--15% runtime correspondence and enforcement. Prompt benchmarks cannot validate the safety theorem and are out of scope.

## 2. Research questions

### RQ1: What authorization state is a checkpoint missing?

For a declared class of future actions, what summary is necessary and sufficient for exact admission after fork, restore, or merge?

Evidence:

- prove that minimum future headroom exactly characterizes one fresh Reserve on one supported branch;
- exhibit choice and parallel states with the same headroom but different successor headroom;
- prove that the correlated residual downset exactly characterizes arbitrary reservation batches and supports the derivative update;
- prove the exact rectangularity criterion for when the correlated residual can be implemented as independent branch-local capability budgets, and the resulting coordination/splitting/topology trilemma;
- prove that intersection over an observation fiber is the pointwise-greatest sound memoryless one-step checker, including structural admissibility such as open epochs, while explicitly excluding generic nonblocking supervisory control.

Success criteria:

- every characterization has both directions and an explicit proposal language;
- “fully abstract” is always scoped to that action class and structural status;
- the artifact enumerates the same decisions and derivative law on bounded states;
- factorization is checked without a fixed-box truncation gap, with explicit rectangular choice and nonrectangular parallel witnesses;
- the paper does not claim generic residuation, resource composition, or partial-observation synthesis as novel.

### RQ2: What changes when a conditional effect becomes durable?

Can exact promotion remain inside the natural choice/parallel policy language, and when does algebraic repair correspond to an executable ordering of effects?

Evidence:

- the \(b\Box(x\parallel y\parallel z)\) witness in which all pairs but not the triple remain safe;
- proof that neither unique-leaf choice/parallel syntax nor a pairwise conflict graph represents that family;
- proof that one frozen nonnegative threshold row gives the exact largest safe subfamily;
- a withdrawal counterexample showing why reading live claim weights from an old guard is unsound;
- lineage-OR transport through live restore;
- the iff final-owner-support theorem for universal owner-group serialization, plus an enabled and disabled ordering when support fails;
- a validated serial order, coordinated cleanup, or atomic batch Prepare before dispatch when universal owner-order support fails.

Success criteria:

- the theorem concludes denotational contract equality, not equality of guard syntax;
- unsupported owners and removed maximal configurations/correlation obligations are returned explicitly;
- every effect in a sealed batch has a stable binding and durable claim before dispatch;
- the finite artifact reproduces every separating example.

### RQ3: Does the abstract invariant refine a real agent lifecycle?

Which facts must a concrete runtime expose so checkpoint, exclusive/parallel fork, selection, abort, replace/live restore, merge, revocation, uncertain dispatch, and settlement preserve authority continuity?

Evidence:

- a concrete/abstract state relation separating reconstructable values from durable controller state;
- a closed least-generated transition relation with sound simulation, admission, and sealing proof objects;
- fragment-conserving structural certificates \((\pi,\rho)\) that dominate every target configuration by a solvent source configuration;
- claim partition, open-epoch, binding, and support well-formedness;
- complete effect coverage: one matching claim per stable protected operation, accounting before every attempt, and aggregate actual demand bounded by declared demand;
- forward-simulation proof yielding trace-prefix authority solvency;
- a documented mapping to Claude Code and Codex lifecycle/pre-tool interfaces, labeled as correspondence rather than enforcement.

Success criteria:

- the proof states exactly what it cannot infer from files, natural-language intent, remote receipts, or optional hooks;
- no runtime hook is described as complete mediation unless an adapter owns every dispatch path;
- RL is described only as a prospective adapter mapping: the calculus does not establish reward, policy-update, privacy, licensing, or provenance correctness.

### RQ4: Is there a deployable algorithmic boundary?

Can an industrial runtime obtain useful fast paths while failing closed on the general guarded case?

Evidence:

- linear cotree evaluation for unguarded choice/parallel contracts;
- linear construction of the exact promotion guard;
- linearly checkable concrete configuration certificates;
- an honest coNP boundary for universal safety with compact threshold guards;
- one minimal dispatch-owning adapter or mandatory tool proxy after the proof and mechanization stabilize.

Baselines for any later adapter:

- snapshot-local clone;
- always split authority;
- parent escrow with transfer after durable selection;
- transaction-only staging;
- residual/guarded authority controller.

Primary safety metrics are violating histories admitted (target zero) and safe useful histories rejected. Latency is secondary and must not be reported before enforcement is complete.

## 3. Fixed litmus suite

| ID | History | Expected result |
|---|---|---|
| L1 | reserve, dispatch, restore old values, repeat with a fresh operation ID | old durable demand remains charged; duplicate authority is rejected |
| L2 | two exclusive empty branches each request one unit under \(G=1\) | individual headroom is one; joint batch is rejected |
| L3 | the same two branches in parallel | individual headroom is one; joint batch is rejected, and reserving one drives the other's successor headroom to zero |
| L4 | compare L2 choice with L3 parallel before any claim | same headroom, different residual regions and successor summaries |
| L5 | promote \(b\) in \(b\Box(x\parallel y\parallel z)\), all unit claims, \(G=3\) | retain every subset of \(\{x,y,z\}\) of size at most two; no pairwise graph representation |
| L6 | withdraw a claim after L5 | frozen guard still forbids the triple; dynamic recomputation would silently change a durable policy, so reopening requires explicit re-admission |
| L7 | live-restore one guarded lineage | substitute old membership by the OR of old/restored descendants and charge it once |
| L8 | restore-replace versus restore-live with identical reconstructed values | a Reserve can be safe in one and unsafe in the other |
| L9 | sequentially promote owners without final support | one order can tombstone the next owner; arbitrary order is not guaranteed, so validate an order, coordinate cleanup, or seal the batch |
| L10 | two transaction-valid branch effects under one one-use grant | transaction-valid but authority-invalid when both become durable |
| L11 | two pure candidates with empty bundles; transfer one claim after selection | safe under parent escrow and the proposed controller |
| L12 | adapter declares a protected query in a rollout and later retains several rollout artifacts | local reset does not erase the supplied claim; applying the theory to learning still depends on a trusted provenance projection and finite demands |
| L13 | Prepare operation \(e\); revoke its epoch; Dispatch \(e\); retry/settle | sealed operation may finish once because already charged; no new Prepare is allowed, and retry is the same stable operation rather than fresh authority |

## 4. Mutation study

Delete or weaken one premise at a time:

- store the authoritative ledger inside the checkpoint;
- duplicate a claim during fork or live restore;
- use current \(Q\) rather than frozen coefficients in an installed guard;
- copy a lineage coefficient to every descendant instead of substituting OR;
- let abort or reset delete a dispatched/uncertain claim;
- accept merge from a workspace diff without \((T',\pi,\rho)\);
- refresh a closed epoch on restore;
- reuse one claim for distinct operation IDs;
- dispatch before atomic Prepare;
- let Retry change the stable operation ID or claim binding, or let a closed epoch create a new Prepare;
- treat algebraic filter commutation as operational serializability without owner support;
- infer exclusivity or effect equivalence from untrusted model text.

For each mutation, report the shortest violating schedule and the theorem premise it witnesses. This is stronger evidence for principle necessity than a collection of stochastic prompt failures.

## 5. Mechanization target

Lean 4 is preferred. The minimum paper-value development proves:

- claim partition, terminal non-reuse, and epoch monotonicity;
- authority-continuity preservation for the small transition core;
- headroom exactness and the non-updateability witness;
- residual batch exactness and the derivative law;
- exact guarded promotion closure and frozen semantics;
- final-owner-support serializability modulo contract denotation;
- one-shot ticket phases, abstract preservation, effect coverage, and the conditional concrete-refinement corollary.

Report Lean version, build command, proof size, trusted axioms, and build time. Until that directory builds from a clean command, the paper must call all formal arguments paper proofs and the Python artifact bounded executable validation.

## 6. Stop and narrowing rules

Narrow or abandon the lead claim if:

- closest prior work already gives the same co-durable conditional-authority residual and lifecycle transformation;
- conditional commitments have no enforceable meaning beyond an intention;
- the guarded promotion theorem collapses to a claimed novelty in generic threshold predicates or supervisory control;
- a complete-mediation path cannot expose trustworthy branch epochs, effect bindings, and dispatch outcomes;
- every useful agent workload safely delays all authority transfer until final selection;
- mechanization reveals a transition rule that assumes the invariant it purports to preserve.

If only runtime integration is missing, retain the theory result but state deployment as future work. If a theorem is classical under renamed notation, cite the classical result and move novelty to the lifecycle-specific instantiation or remove the claim.

## 7. Completed RQ3 canonical-topology mechanization

BUILD_AND_EVALUATE Step 0002 tested the exact uncertainty left by the first mixed run: whether canonical Fork/Restore targets and fragment-conserving transfer can derive target lifecycle invariants rather than accepting a fieldwise target certificate. Boundary I/II remain paper proofs and were not silently added to this experiment.

- Approved plan: `docs/tmp/build-and-evaluate/step-0002-20260801T061001-0700/experiment-001/plan.md`.
- Plan review: `docs/tmp/build-and-evaluate/step-0002-20260801T061001-0700/experiment-001/plan-review.md`.
- Toolchain: Lean 4.30.0 (`d024af0`), Lake 5.0.0, Mathlib tag `v4.30.0` (`c5ea0035`).
- Real preflight: the named fresh-fragment split reaches the final parallel-Fork preservation theorem; 750 jobs completed in 1.60 seconds and its printed dependencies are limited to `propext`, `Quot.sound`, and `Classical.choice`.
- Full-run status: exact choice/parallel Fork and replacing/live Restore builders, checked transfer/fiber conservation, distinct simulation/direct Merge, and the authoritative full Step/Trace theorem all build. A clean 755-job build completed in 10.02 seconds (maximum RSS 2,099,376 KiB); source scans found no placeholder, project axiom/constant, or retired fieldwise topology interface; a fresh kernel replay exited zero.
- Controls: named positive and negative witnesses cover all four canonical forms, fresh fragmentation, copied demand, retained/fresh mixing, terminal-ID reuse, invalid `rho`, closed-epoch reopening, Merge-mode separation, unsafe co-durability, history preservation, and replacing Restore.
- Independent result review: **positive**. Canonical target WF, active-support exactness, load simulation, and AC are derived from builders, source invariants, and source-local checked transfer. The AC proof invokes the fiber-conservation theorem rather than a target check.
- Paper decision: report a finite abstract-lifecycle mechanization. Explicitly limit fragments to preallocated source-`unissued` IDs and exclude Boundary I/II, complete mediation, natural-language binding, aggregate sink truthfulness, and deployed-runtime refinement.
- Raw evidence: `lean/results/topology-preflight.log`, `lean/results/topology-build.log`, `lean/results/topology-axioms.log`, and the independent review under the step directory.
- Next gate: a dispatch-owning adapter plus fixed crash/retry/fork/restore histories must test the concrete refinement hypotheses. Public agent traces should guide workload selection and expose telemetry gaps, not stand in for this gate.

## 8. Real-trajectory study before the adapter

The trace study has two sharply separated objectives:

1. **Workload:** measure how often observable agent histories contain
   checkpoint/continuation, subagent or fork-like execution, Git topology
   change, retry/failure, and commands that may escape the workspace.
2. **Observability:** audit which fields required by the refinement theorem can
   be reconstructed from ordinary trace schemas. This is a schema result, not
   a claim that every outward-looking command caused a real external effect.

### Corpus and access

- Primary public real-runtime corpus: UW TraceLab v0.0.2. Its complete
  100,939,722-byte JSONL release was hash-verified as
  `11ce51ec0a25e3d1d95b025bca2f7d1647e47571eb7cc968acd5fc64d4b4fb65`
  and mechanically scanned in full. SWE-chat remains the richer natural
  checkpoint-to-Git corpus if its gated access conditions are explicitly
  accepted; until then, use only its public card/schema and published counts.
- Public fallbacks and schema controls: the 1,781 Agent LLM OpenTelemetry traces
  and Microsoft Orchard's 107,185 SWE trajectories plus 3,070 GUI prefixes.
  Orchard is public/ungated at pinned revision
  `70c05ec1f20f823ae6adc60374922e9271bb74e2`; one SWE row/schema was inspected,
  not the full 9.72 GB corpus. General AgentBench is an additional gated
  cross-domain corpus, not a substitute for in-the-wild data.
- Failure taxonomy: AgentRx and coding-agent-misalignment guide manual labels;
  they are not counted as complete lifecycle trajectories.
- External-state comparator: WebArena and WebArena-Verified expose selected
  Playwright/network/HAR and task-state evidence, but not lifecycle or
  capability lineage and not a crash-relative protected-effect receipt.
- No gated corpus may be reported as analyzed until access is actually granted
  and the exact files/checksums are retained. The current environment has no
  Hugging Face authentication.
- Treat the released sessions as human-derived data even when public and
  redacted: follow dataset terms, do not resolve or join user identities, avoid
  publishing raw prompt/code excerpts, aggregate command statistics, and seek
  institutional ethics/IRB guidance before the full study when applicable.

### Completed fixed TraceLab audit

The v0.0.2 scan found 665,453 rounds, 8,058 sessions from 52 deduplicated
users, and 743,819 tool records. Every released tool call has a call ID and no
call ID repeats within a session. The corpus contains 35,453 tools marked as
errors (4.77%) across 4,228 sessions, 75,488 process-continuation records, and
423,280 calls with sanitized command structure. A narrow, predeclared
subagent-tool vocabulary occurs in 923 sessions. These are workload and
observability counts only: a tool error is not a crash-after-effect, a process
continuation is not Restore, and a tool name is not a semantic Fork.

The union of public fields has event order, tool IDs, timestamps, error/result
status, process continuation, and sanitized command structure. It has no
trusted lifecycle parent/Fork/Restore event, grant/capability/claim lineage,
durable-support record, stable protected-effect phase/receipt, or boundary
locating a crash relative to remote durability. Public normalized traces
therefore cannot reconstruct the exact admission decision or yield an unsafe-
history rate. The durable report is
`docs/tmp/writing/step-0005-20260801T150830-0700/trace-dataset-scout/trace-dataset-audit.md`;
the downloaded corpus remains ephemeral and is reproducible from the pinned
release/hash.

Decision: do not add a broad dataset benchmark to the 12-page paper. Public
traces support workload relevance and the joint observability gap; the formal
model and an instrumented adapter/runtime remain the evidence for safety.

### Deterministic detectors and audit

Parse structured tool fields first. For shell commands, use a versioned parser
to identify `checkout`, `reset`, `revert`, `stash`, `rebase`, `merge`,
`worktree`, `push`, deployment/package commands, database clients, and common
network/API clients. Treat these as candidate operations, not semantic ground
truth. Deduplicate tool-use/result pairs by the dataset's call ID and retain
unmatched calls, errors, and repeated argument hashes as uncertainty/retry
signals. Agent LLM Traces stores calls/results inside cumulative message JSON,
so deduplicate by call ID before counting and do not interpret LLM-span status
as normalized tool-dispatch truth.

Before a full census, manually label a stratified sample containing detector
positives, errors/retries, checkpoints, and random negatives. Report detector
precision/recall with Wilson intervals and publish the annotation rubric.
Never use an LLM-only label as the source of a safety result.

### Primary outputs

- session and call counts for each observable lifecycle/effect-candidate class;
- distributions of subagent fan-out, checkpoints, repeated calls, and the
  distance from error or missing result to retry;
- a field-coverage matrix for `history_parent`, `source_boundary`, branch epoch
  and liveness, Merge projection, grant/claim identity and status, stable
  protected `effect_id`, Prepare/Dispatch/uncertain/settled phase, and external
  receipt/outcome;
- minimal real trace excerpts that select the controlled litmus workload, with
  repository/user content redacted according to dataset terms.

The target safety metric is not “number of unsafe traces,” because the missing
fields make that label unidentifiable. The honest result is workload prevalence
plus the fraction of required theorem fields that are explicit, inferable only
under an assumption, or absent.

### Instrumented complement

Run the fixed 20 deterministic histories specified in
`docs/runtime-integration.md` through a Codex App Server client whose
dynamic-tool handler owns one mock remote service. The sink must be idempotent
and queryable by stable `effect_id`, return authenticated receipts, and expose
external state to an oracle. Inject crashes before dispatch, after remote
success before durable controller commit, and after commit before reply. A
non-queryable or dishonest sink is outside the refinement claim rather than
silently treated as exactly-once.

Keep information and enforcement comparisons separate.

**Observation ablations**

- `O0`: workspace/checkpoint state only;
- `O1`: `O0` plus ordinary session/call/result telemetry;
- `O2`: `O1` plus trusted lifecycle, authority-lineage, and effect-lifecycle
  events in an anchored, self-contained replay bundle.

Admission depends on a prefix and the proposed next action. Therefore use the
key `K_i=(alpha(O_i(prefix)), normalize(next_action))`: alpha-rename run-local
IDs by first occurrence while preserving alias structure/order, remove
absolute timestamps, redact/hash canonical arguments, and normalize the action
kind, source role, demand, binding, and same/fresh-operation relation. Group
only equal keys and count fibers containing different oracle decisions; never
compare raw unique run IDs or different requested actions. The required pairs
are C13/C14 before the same Reserve (topology), C16/C18 before the same second
Reserve (authority), and C02/C04 while the same App Server request is pending
before permission for the same physical `.attempt(e1,c1)` (effect). In C02 a
prepared ticket admits Dispatch; in C04 a settled receipt denies a new attempt
and the cached reply is a zero-outcome stutter. The earlier C02/C03
`FinalizeAbort(e1)` proposal is not an existing-LTS witness because Settle
permits cancellation from `uncertain` without an authenticated-absence
premise.
Such mixed-label fibers, decoder abstentions, and wrong decisions are expected
evidence of `O0`/`O1` insufficiency, not experiment failures. `O2` must
reconstruct the genesis `LifecycleState`, each abstract label/successor and
checker decision; the corresponding concrete edges must then check as a
`SimulatedTrace`. The
formal target is not merely the existing replace/live pair: give independent
topology, forked-grant-lineage, and effect witness families for `O1`, test
componentwise necessity of the `O2` event classes, and prove replay
sufficiency under complete mediation, certificate validation, a trusted
durable head, and the sink assumptions. Without an irredundancy/lower-bound or
observation-quotient result, this remains supporting instrumentation.

**Admission-policy baselines**

- `P0 workspace/topology-local admission`: share the fixed durable effect/sink
  harness for fault fairness, but admit locally well-formed authority actions
  without correlated future accounting;
- `P1 split-all`: permanently partition remaining capacity among live children;
- `P2 parent-escrow`: retain capacity centrally and transfer once after winner
  selection, rejecting protected pre-selection dispatch;
- `P3 authority-continuity`: use the checked correlated controller and stable
  pre-dispatch tickets.

Use the exact 20 named cases, dispatch sites, and complete baseline transitions
in `docs/runtime-integration.md`. Report observation-fiber ambiguity separately
for `O0`--`O2`, then classify each `P0`--`P2` decision as a true/false
accept/reject against the oracle; baseline disagreements are expected results.
Only `P3` must match every suite decision, admit zero unsafe history, and
produce zero duplicate aggregate sink outcomes. The controller's verdict is
not its own oracle: L1/L8/L10/L13 expectations and the mock sink's before/after
snapshots determine correctness. Retain dataset/runtime locks, all 80 policy
runs, raw histories, receipts, durable heads, and JSON summaries at the paths
defined in `docs/runtime-integration.md`; only then report latency and durable
write overhead. Claude Code through a mandatory MCP proxy is a portability
check after the Codex path, not a second unfinished prototype.

## 9. Completed RQ3 Codex adapter experiment

BUILD_AND_EVALUATE Step 0004 crossed the real installed Codex App Server
boundary.  The model endpoint remained a deterministic loopback fixture, while
native `thread/fork`, `turn/start`, and client-owned `item/tool/call` were
executed by pinned `codex-cli 0.146.0`.  A separate controller worker was
hard-killed at the three named persistence boundaries and reopened two
independent SQLite durability domains while the original callback remained
pending.

An initial completed pilot was rejected by result review rather than reported:
it erased one action/grant alias, used an oracle-only C04 attempt label, and
omitted the C19 Merge projection.  Suite revision 2 did not change an oracle
decision.  It records the actual C16/C18 grants with typed alias-preserving
prefix events, executes C02/C04 admission probes, and supplies a canonical C19
projection plus injective retained-claim map to independently implemented
controller and replay checks.

Final deterministic results:

- all 80 policy/case runs terminated explicitly;
- P3 matched all 89 frozen request decisions, admitted zero unsafe request,
  and independently replayed all 20 complete delta/hash chains;
- all 44 reached effects matched raw `item/tool/call` records and produced one
  attempt, one aggregate sink outcome, and one controller receipt;
- all 33 injected `SIGKILL` faults restarted in a distinct process and
  recovered; 22 before-dispatch/after-commit paths executed the paired attempt
  admission question;
- 187 native forks matched the run actions: 80 per-run setup roots and 107
  accepted lifecycle materializations (80 fork children, 24 restore copies,
  and three merge targets); logical ancestry remained adapter metadata;
- O0 and O1 each retained the three predeclared mixed-label fibers, while O2
  retained none;
- P0 produced 11 unsafe accepts over 89 observed decisions; P1 produced four
  safe rejects over 87 observed decisions and truncated two later requests;
  P2 produced nine safe rejects over 71 observed decisions and truncated 18
  later requests.  P1/P2 produced no unsafe accept.

The supported conclusion is correspondence for one isolated queryable sink and
fixed adapter-defined lifecycle.  It is not product-wide complete mediation or
a native Codex Restore/Merge theorem: every ephemeral child is a real fork of
the persistent seed, but logical ancestry/topology is adapter state; topology
commit/activation crash windows, App Server/frontend death, shell/MCP/web
bypasses, direct same-user database access, dishonest sinks, power loss, and
natural-language binding remain outside scope.  The unbounded concrete
refinement result therefore keeps its explicit premises.

The authoritative artifacts are `adapter/results/litmus.json`,
`adapter/results/check.json`, `adapter/results/raw/`, and the plan, rejected
pilot, preflight, and result review under
`docs/tmp/build-and-evaluate/step-0004-20260801T131114-0700/`.

## 10. Step 0005 milestone verdict and next gate

A fresh blind review, primary-source attack, full reread, and artifact audit
did not accept the current paper as CSF-ready. The problem, lifecycle semantics,
fixed artifacts, and durable-support principle survived. The acceptance blocker
is now narrower: configuration structures already provide arbitrary permitted
families and higher-order conflict, while resource-sensitive event semantics,
consumable authority, and supervisory guards are closer foundations than the
paper currently distinguishes. Boundary II remains the strongest possible new
result, but its final-owner-support iff theorem has not been separated from
those models or mechanized. Boundary I and exact promotion are also outside the
current Lean development.

The next evidence gate is therefore formal rather than a broader runtime or
trajectory study:

1. encode the permitted-family, quantitative-resource, promotion, and cleanup
   semantics into the closest configuration/resource formalism;
2. prove or refute that cleanup-aware universal owner-order serializability is
   an additional lifecycle theorem;
3. mechanize Boundary I, exact promotion, and Boundary II and publish a
   theorem-to-artifact coverage map.

Complete mediation remains a major systems strengthening, not a blocker for a
clearly theory-led submission whose Codex adapter is explicitly illustrative.
If the formal delta collapses, the project must pivot openly to a
security-systems contribution with a mandatory protected boundary and a
measured availability advantage over conservative escrow/attenuation; it must
not recover novelty by adding trajectory counts or new terminology.
