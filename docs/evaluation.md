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

### Completed Trace Commons schema audit

A second read-only audit used the public
[Trace Commons Agent Traces](https://huggingface.co/datasets/trace-commons/agent-traces)
at pinned main revision
`112ebd4d03ce852b00e935d523107c3d0c9a65bf` and Viewer parquet revision
`72c58f6a93393d75b1cbff4369430deda2f19c48`. All 30 donated sessions were
read through the Dataset Viewer API; no raw donated trace was copied into the
repository. The sample is small and heavily Claude-Code-skewed, so these are
schema and workload-shape observations rather than population estimates.

The rows contain 18,012 trace events, 4,264 tool calls, 4,262 matching tool
results, 269 explicitly marked result errors, and 953 file-history snapshot
events. The snapshot records name tracked file versions, while the same
sessions contain shell syntax for Git pushes, network or remote operations,
process/service management, package installation, databases, and deployment.
The descriptive command classes overlap and must not be reported as
prevalence. Two PowerShell calls have no matching result; one starts a build
and one stops processes before building. A missing result establishes
uncertainty, not that the call had no effect and not that a rollback was unsafe.

This audit makes the three-state-plane distinction concrete:

1. reconstructable state, exemplified by tracked file versions;
2. monotone lifecycle and authority state, such as closed branch/grant epochs,
   consumed claims, and stable operation bindings; and
3. external reality, which requires an effect-specific receipt or a
   conservative uncertainty marker rather than inference from local rewind.

Trace `uuid`/`parentUuid`, call IDs, result/error fields, working directory,
and Git branch support ordinary lineage and correlation. They do not expose a
trusted semantic Fork/Restore cut, grant/claim provenance, protected-effect
phase, durable receipt, or compensation/idempotence contract. Consequently,
the corpus cannot reconstruct an authority-continuity decision or support an
unsafe-history rate. It instead motivates the minimum industrial telemetry
contract and confirms that a workspace snapshot and the security state needed
for safe restore are different objects. The complete reproducible audit is
`docs/tmp/build-and-evaluate/step-0006-20260801T153740-0700/trace-commons-audit.md`.

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

## 11. Step 0006 formal gate and evidence disposition

Step 0006 froze the following RQ2 experiment without changing the paper-facing
question:

> RQ2: What changes when a conditional effect becomes durable? Can exact
> promotion remain inside the natural choice/parallel policy language, and
> when does algebraic repair correspond to an executable ordering of effects?

The admitted experiment targeted the actual `PrepareOK`/`CoreStep.prepare`
semantics, source-fixed owner groups, exact prefix repair, immediate cleanup,
and equality of final authorization state with atomic sealing. Its independent
plan review accepted the design while imposing a novelty ceiling: universal
order existence is the established conditional-independence/asynchronous-cube
target; only an authority-derived final-support certificate and atomic
refinement could be claimed as new.

The Lean preflight exhausted its frozen three-attempt budget without compiling
the proposed theorem module. Attempt 1 lacked the pinned `lake` on `PATH`;
attempt 2 exposed namespace/type shadowing; attempt 3 reached the intended
module but left 15 proof-elaboration obligations, including quantified
downward closure, open-claim, active-exactness, and `PrepareOK` membership
facts. The generated declarations depended on synthetic `sorryAx`; therefore
the draft is not proof evidence. Independent result review classifies the
experiment as **inconclusive**, not as a counterexample to Boundary II, and
forbids any paper-claim update from this run.

The failed source is retained byte-for-byte at SHA-256
`bb25e8fa5f47576da00511a734c55b2c5db241b1115f4f0ff404f9884b535faa`
under `experiment-001/preflight/Serialization.failed.lean.txt`, outside Lake's
source glob. A post-disposition regression build of the unchanged authoritative
library completed 755 jobs successfully; this is repository hygiene, not a
fourth preflight or evidence for RQ2. The plan, three logs, result review, and
regression log are retained under
`docs/tmp/build-and-evaluate/step-0006-20260801T153740-0700/experiment-001/`.

The closest-work result is nevertheless decisive for framing. Generic
enabledness preservation plus commutation, state-conditional independence,
full asynchronous cubes, and disruption/remainder cleanup are established.
No inspected source states the authority-specific closed form
`K_O = AND_{b in O} Supp_b(F_O)` or its equality-with-atomic-seal refinement.
Boundary II may survive only in that specialized form and only after a fresh,
materially revised mechanization.

The separate selected-order audit corrects an earlier exponential-search
intuition. In the current nonnegative downward-closed model, the singleton
configuration is the cheapest witness of an owner's support. Writing `p_b` for
the promoted vector and `h_b = G - d - r_b`, owner `b` remains enabled after
predecessors `S` exactly when `sum_{a in S} p_a <= h_b`. A backward algorithm
can therefore peel any owner that is safe as the last remaining owner. It uses
`O(n^2 k)` direct arithmetic, returns a safe forward order when it empties the
batch, and otherwise returns a choice-independent dead core with one overloaded
coordinate per owner as a compact no-order certificate. Boundary II is the
special case in which every owner is peelable initially.

This static result cannot become the new headline. Möhring--Skutella--Stork's
AND/OR precedence feasibility gives the same abstract peeling algorithm and
obstruction; conflict-free Dual Event Structure traces express the same
reversed bundle condition; and antimatroid pruning gives arbitrary-choice
completeness and the unique core. The authority vectors provide a compact
domain derivation without enumerating exponentially many minimal killers, but
not a new scheduling theory.

The next materially revised question is *serial or seal*. A runtime should
return a version-bound safe order, a dead-core obstruction, or an explicitly
costed final atomic seal, then prove which Fork/Restore/Merge/Abort/Revoke
transitions preserve or invalidate that certificate before Dispatch. The
Step 0006 report contains an exact final-seal criterion and candidate hardness
reductions, but these remain internal until independently reviewed and
mechanized. Static peeling is useful machinery; the versioned lifecycle theorem
and crash-stable real-runtime enforcement must carry any new agent-specific
claim. The complete theorem/prior-art audit is
`docs/tmp/build-and-evaluate/step-0006-20260801T153740-0700/killer-hypergraph/report.md`.

## 12. RQ3 dynamic-redemption-topology experiment

Step 0007 experiment 002 reopens one RQ3 premise after a hostile review found
that current-occurrence linearity is sufficient but not necessary.  Several
history handles can safely race through one durable linearization cell, while
one restored occurrence can redeem twice if its local admission state was
cloned.  Equal labels, process IDs, worktrees, or endpoint names do not decide
which case holds.

The accepted revision-2 hypothesis uses two maps:

```text
history handles --resolve--> semantic redemption cells
                --lineage--> source authority atoms.
```

For every lifecycle-derived co-redeemability configuration, aliases are first
quotiented by `resolve`; `lineage` must then be locally injective and its image
must be a permitted source configuration after durable commitments are
retained.  The planned finite theorem characterizes this condition as
preservation of every nonnegative additive bounded-authority policy.  The
condition is classical configuration-morphism machinery; the proposed
paper-level delta is the semantic-cell quotient and typed refinement of agent
Fork/Restore/Merge/Prepare.  Global
`charged + sum(unspent rights) <= capacity` is explicitly only the detached,
product-independent escrow corollary.

Paper-value role: **decisive theory experiment**.  It repairs a false universal
necessity claim and tests the strongest surviving operator-level novelty.
Positive, contradictory, and mixed paper decisions are fixed in the approved
plan.  The plan and two-round independent review are in
`docs/tmp/build-and-evaluate/step-0007-20260801T164024-0700/experiment-002-domain-conservation/`.

Current run status: **partially complete; central operator theorem still
blocked**.  `ConfigurationCellQuotient.lean` now kernel-checks the exact finite
additive iff without a target-safety premise, including explicit
capacity-one collision and forbidden-image indicator witnesses.  This closes
item 1 below but remains classical supporting machinery.  A first operational
commitment LTS also compiled and proved real single-step/RTC preservation, but
independent review returned **REVISE**: its aggregate ledger obscured the
cell-local implementation boundary, external phases lacked well-formedness,
retry identity was weaker than Replay, and label-erased RTC could not count
fresh commitment events.  It is not accepted evidence until those issues are
repaired.

The revision repairs all four findings: Fresh now updates explicit
cell/epoch-local spent state; ledger and external phase have a preserved
well-formed domain and monotone phase order; Retry resolves
`(cell, operation, digest)` to the existing receipt; and retained labeled
traces satisfy exact committed-cardinality growth by fresh-event count.  A
read-only follow-up returned **PASS for the scoped commitment core**.  The
result still does not establish the source `Safe` invariant for any
topology-changing operator and is not the central agent lifecycle theorem.

The quotient module passed standalone elaboration, the integrated library
build, the frozen axiom/declaration checks, and a fresh kernel replay of
`AuthorityContinuity.Main` on 2026-08-02.  Its source SHA-256 is
`6d29f8f3c6c6eb21365d34e93448ad27e75691af9901dda912853788b09d6c81`;
the regenerated identical axiom-log hashes are
`e72bd514020f16dffb1a14d1a97ae9f157e510b1d82f589a7c4cb919f3d0e518`.

The supporting seven-case in-memory semantic oracle separates event,
occurrence, cell, operation-key, commitment, and sink identities.  Its latest
59-test adapter regression passed in 13.063 seconds.  This is dependency
evidence for the detached/escrow profile, not execution of the decisive typed
operator theorem.  It does not prove storage durability, native product
lifecycle refinement, or external exactly-once.

A separate traditional-model audit also rejects dynamic graph growth,
different control/effect histories, rollback-resistant output state, and
configuration local injectivity as novelty.  The future graph will be modeled
intensionally by a versioned co-durability contract.  The scoped lower bound
applies only when the runtime immediately materializes independently
redeemable authority; delayed delegation and shared ratification remain valid
escape mechanisms.

Completion requires, before any central paper rewrite:

1. a kernel-checked cell-quotient characterization with collision and
   forbidden-image counterexamples;
2. operational balance-to-commitment conservation with Fresh/Replay Prepare;
3. typed operator preservation and arbitrary checked-history induction;
4. clone and sequential-restore necessity plus strict shared/cloned/Merge
   witnesses; and
5. durable-commitment-before-mediated-Dispatch, leaving physical exactly-once
   conditional on the sink.

The real Codex callback remains one effect-boundary correspondence seam.  The
self-hosted paper-formation trajectory may test whether required fields occur
and remain private after aggregation; it cannot validate the theorem or imply
product-wide mediation.

## 13. RQ4 bounded history-admission scaling characterization

Paper-value role: **supporting internal artifact evidence**. The admitted
question was whether the compiler and independent verifier complete a selected
nontrivial small contract and engage finite bounds, not whether an industrial
runtime is deployable or fast.

The deterministic cell sweep reaches 2,510 configurations and 792 minimal
nonfaces at 12 cells. The controller sweep fixes 6 cells and 64 final physical
configurations while source-grounded pair-expansion counts grow from 64 to
70,592 for one through four overlapping controllers. Both implementations
accept every planned row, produce stable hashes over five repetitions, and
agree exactly. They reject 13 source cells at the 12-cell limit and reject five
overlapping controllers at pair-expansion iteration 200,001; 202,688 is only
the hypothetical uncapped total. Target-cell, raw controller-count, and
expanded-configuration limits were not tested.

Independent review verdict: **valid and matrix-complete, but provenance-
incomplete as a historical archive**. A 103-check recomputation found no
arithmetic or summary errors, and a fresh temporary rerun reproduced every
non-timing field. The historical run used a dirty tree and deleted temporary
requests/results/seals, so a clean pinned rerun remains necessary for a fully
auditable timing archive.

Paper decision: retain bounded family/certificate counts and fail-closed
engagement of the two exercised limits. Detailed wall times stay in the
internal report because this evaluation contract forbids paper-facing latency
before complete runtime enforcement. No throughput, prevalence, fast-path, or
deployability claim follows.

- Plan and reviews: `docs/tmp/history-admission-scaling-20260802/`.
- Runner: `artifact/bench_history_admission_scaling.py`.
- Raw result: `artifact/results/history_admission_scaling.json`.

## 14. RQ4 central Agent security-state mechanization

Paper-value role: **decisive formal experiment**. Four fresh CSF reviews agreed
that the outcome-indexed history-admission idea is promising but that the
paper's central characterization is not independently auditable from its
current prose inventories, auxiliary Lean modules, and bounded Python tests.
The new experiment therefore targets the complete current theorem rather than
another runtime benchmark.

The approved plan freezes four paper-matched Lean modules:

1. `FiniteCore.lean` independently defines the declarative realization
   semantics and the executable indexed greatest fixed point, then proves
   `compilerAns_eq_semanticAns` and greatest-monitor/certificate obligations.
2. `OperationalSemantics.lean` defines a single empty genesis, constrained
   registration and initial installation, the five-clause `AgentSec`
   invariant, all six history edits, the complete modeled event relation, and
   arbitrary finite-prefix closure.
3. `ReachableEvidence.lean` constructs every P/I/E/C and incidence-separation
   world by an explicit trace from genesis and proves both erased-view
   isomorphism and opposite declarative answers.
4. `DurableRefinement.lean` defines independent ideal and kernel LTSs and proves
   both directions of divergence-insensitive weak simulation before assembling
   the full characterization.

The non-circularity contract is load-bearing. `SemanticAns` may refer only to
the declarative realization relation, while `CompilerAns` uses derivation and
the executable fixed point. Kernel transitions have their own guards and
updates rather than being ideal transitions with metadata. Lower bounds require
both a reachable projection collision and opposite semantic answers.

This plan deliberately diagnoses, rather than inherits, one defect in the
frozen PDF: the appendix currently declares every `BootOK` post-installation
state initial and therefore calls each lower-bound world length-zero reachable.
The experiment instead requires one literal empty genesis followed by actual
registration, installation, Save, use, and edit steps. A positive result would
support a later minimal paper repair from bootstrap membership to natural
reachability; it must not be described as directly proving the current
length-zero wording.

The real toolchain is installed and pinned at Lean 4.30.0, Lake 5.0.0, Mathlib
v4.30.0, and Elan 4.2.3. An initial fresh read-only review approved the
four-module structure. A subsequent reverse map against every clause of the
frozen PDF found additional load-bearing obligations: the independent atomic
realization, three-way semantic answer including stale installation,
representative-independent event derivatives, typed natural-join
normalization, target-only lower bound, generalized-nonblocking
correspondence, and the precise common abstraction for bisimulation. These are
now binding in the revised plan. A second formal-scope audit additionally
forced an explicit root-cut origin, a total edit-answer type for empty fixed
points, simultaneous state/event/trace nominal quotients, alpha-equivalent
observable labels, state-indexed atomic-swap premises, and a precise
query-fixing construction for the C pair. Two narrower audits then strengthened
that repair further: declarative history derivation is now independent of the
executable derivation; semantic installation handles arbitrary stale or corrupt
artifacts; public answers erase diagnostics only after verification; factor
exactness is typed over the joint `(view,query)` orbit; and weak bisimulation
carries one persistent renaming witness so Fresh/Alias identity is preserved
across the entire observation trace. Bootstrap keeps deterministic allocation
by choosing a private namespace seed before initial installation. The resulting
contract passed three independent final checks: a whole-plan/paper-contract
review, a nominal-semantics review, and an atomic-answer/installation review,
all with verdict **APPROVE**. The last correction makes C-erasure use one
static unary dependency schema: I-owned gate/handle rows whose mandatory
foreign-key closure reaches erased seed/epoch ownership are removed uniformly,
never according to which two worlds are being compared.

Completion requires every frozen theorem to appear in the audit root, pass the
placeholder/project-axiom scan, build from a clean state, and survive
`lake env leanchecker --fresh AuthorityContinuity.Main`. The first execution
gate remains a real shared-prefix preflight reproducing the paper's two-outcome
`[2,1,0]` pruning chain with independently computed semantic and compiler
answers. It cannot begin until the revised contract is approved.

- Approved plan:
  `docs/tmp/research-experiment-design-20260803T160000Z/plan.md`.
- Planned raw evidence:
  `docs/tmp/research-experiment-design-20260803T160000Z/raw/`.
- Current status: **final contract approved; real preflight PASS as
  dependency-only evidence after one semantic FAIL and repair; the general
  registered finite admission core now PASSes after a separate nonvacuity FAIL,
  repair, `--trust=0` replay, and adversarial finite probes**.
- Preflight result:
  `docs/tmp/research-experiment-design-20260803T160000Z/preflight-result.md`.
- General finite-core result:
  `docs/tmp/research-experiment-design-20260803T160000Z/general-finite-core-result.md`.

The general finite result connects a total inductive receipt-threaded resolver
to constructional candidate generation, derives receipt state and durable
authority prefix from one ordered ledger, keeps `Realization` independent of
the compiler, and proves that `CompilerAns` and `SemanticAns` both admit
exactly the valid declarative realizations. It also proves monotonicity,
bounded stabilization, equality with the greatest postfixed family, and
componentwise language/family greatestness for every registered finite input.
The literal paper fixture remains `[2,1,0]`.

This is the first theorem-bearing submilestone, not completion of the central
experiment. `OperationalSemantics.lean`, `ReachableEvidence.lean`, and
`DurableRefinement.lean` remain required before the paper may call the
six-edit closure, state lower bounds, or weak bisimulation mechanized. The
ranked deletion-cause certificate is likewise deferred rather than weakened.

## 15. RQ4 real program replacement after external operations

Paper-value role: **decisive systems experiment**. The selected repository RQ
remains “RQ4: Is there a deployable algorithmic boundary?” The experiment asks
whether the runtime can replace a live official Restate `food-ordering` program
after an unresolved payment attempt, without an old-version state branch or
per-instance migration.

The fixed comparison uses one target v2 that removes the old payment step and
two executions at the same Restate-visible cut. In H1 the external payment is
durably committed but its response has not returned from the `ctx.run`
closure; in H0 no payment is committed. The Requirement still requires one
payment in both cases and v2 contains no executable payment producer. A
disabled historical kind remains only to interpret the old Operation. The expected runtime
answer is therefore H1 `activate` and H0 `impossible`. The comparison is valid
only if the retained Restate journals are equal at the cut. Native Restate and
the matched Temporal Worker Deployment path are measured through their
official version mechanisms rather than assigned expected outcomes from prose
documentation.

Independent value beyond the DeathStar run comes from the maintained
long-running workflow, real durable journal, immutable deployments, official
pause/resume lifecycle, and the opposite-answer H0/H1 pair. Merely recovering
another lost HTTP response is dependency work. The no-query ablation must fail
closed; a compatible edit must still work; an unsafe edit must never complete;
the provider must be intentionally non-idempotent; and deliveries, durable
commits, old-code retention, terminal workflow state,
and independent Rule checking are all retained.

Current status: **core experiment PASS and frozen after independent result
review**. In five matched Restate pairs, H0 and H1 have the same retained
journal and workflow state but different durable payment facts. The proposed
runtime rejects H0 before target start and activates H1 after querying the
existing payment; H1 then reaches `DELIVERED` with one payment and one
completion commit, without v1. Native Restate replacement backs off on code
mismatch. Retaining v1 preserves availability, but the real old-version control
duplicates H1 payment in all five repetitions and therefore is not a safe
substitute.

The matched Temporal application now preserves the full food-ordering business
chain rather than the earlier simplified path. Its final package contains 55
real lanes: 30 H0/H1 lanes across manual branch, AutoUpgrade, and Pinned; five
compatible lanes; ten old-version lanes; and ten proposed/native unsafe lanes.
All lanes completed their expected checker outcome. The package exited zero,
all 5,680 recursive checksums match, and all 28 post-command resource checks
are clean. AutoUpgrade exposes nondeterministic replay failures, Pinned and
old-version execution retain v1, manual branching requires explicit developer
logic, and the native unsafe path completes after consuming approval 2 against
capacity 1 while the proposed path refuses before target start.

The result is scoped to registered, queryable HTTP Operations and this
food-ordering workload. It does not establish generic exactly-once behavior or
production VM cutover. Two early failed-attempt records have incomplete exact
provenance; they are not used in the accepted matrix and are documented in the
result review rather than reconstructed.

- Plan: `docs/tmp/bootstrap/step-0016-20260815T153407Z/experiment-restate-food-ordering/plan.md`.
- Plan audit: `docs/tmp/bootstrap/step-0016-20260815T153407Z/experiment-restate-food-ordering/plan-review.md`.
- Result review: `docs/tmp/bootstrap/step-0016-20260815T153407Z/experiment-restate-food-ordering/result-review.md`.
- Raw evidence: `docs/tmp/bootstrap/step-0016-20260815T153407Z/experiment-restate-food-ordering/raw/`.
- Portable raw archive: `docs/tmp/bootstrap/step-0016-20260815T153407Z/experiment-restate-food-ordering/artifacts/raw-evidence-20260816.tar.zst`.

## 16. Native Codex whole-VM continuity smoke

Paper-value role: **systems dependency evidence, not yet a paper result**. The
question is whether an unmodified App Server client can retain one real Codex
execution across destruction of the original VMM, rather than whether
Firecracker snapshotting itself is novel.

The current source passed one credential-free KVM execution with native Codex
0.147.0, Firecracker 1.16.1, and Linux 6.1.155. The runtime held one protected
tool callback, drained the model connection, paused and snapshotted G1, sent
`SIGKILL` to the exact child and reaped it, started G3, loaded the full snapshot
paused, installed both host endpoints before resume, reattached the retained
stream, and only then delivered the callback. The matching successful callback
response entered the retained stream and the same turn completion reached the
client before the runtime accepted client EOF. Both recorded VMM PIDs were
absent after cleanup.

The retained run contains 22 ordered lifecycle events, 16 artifact hashes, 80
canonical bridge commitments, and 352 App Server records. A standalone checker
returned `{"schema":1,"valid":true}` after joining those records with VMM API
calls, relay lifetimes, process identities, snapshot inputs, and the immutable
Codex payload. Unit mutation tests reject reordered lifecycle events, rebound
hashes, missing delivery records, premature completion, process mismatches, and
cross-generation substitutions.

This is a one-run functional smoke with a 1 GiB memory snapshot and a fixed
local model endpoint. It is not performance evidence, a production sandbox, a
portable attestation, product-wide mediation, or a refinement of the abstract
safe-change theorem. The decisive next experiment must combine this substrate
with a real repository and the durable Operation gateway, then change a Rule
at the same VM boundary and compare useful continuation against the strongest
update and isolation baselines. The exact implementation boundary is in
`docs/firecracker-codex-runtime.md`.
