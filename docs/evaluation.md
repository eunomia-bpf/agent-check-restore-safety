# Evaluation Contract

**Status:** theory-first CSF 2027 evidence plan and repository truth as of 2026-07-31. A number is a result only when a checked-in command reproduces it.

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

## 7. Active RQ3 mechanization experiment

The current BUILD_AND_EVALUATE step tests one uncertainty: whether abstract lifecycle preservation and the conditional trace theorem can be checked in Lean without `sorry`, project axioms, or target-WF/AC premises in derived transition cases. Boundary I/II are outside this RQ3 experiment and remain paper proofs until separate mechanization.

- Approved plan: `docs/tmp/build-and-evaluate/step-0001-20260801T042542-0700/experiment-001/plan.md`.
- Plan review: `docs/tmp/build-and-evaluate/step-0001-20260801T042542-0700/experiment-001/plan-review.md`.
- Toolchain: Lean 4.30.0 (`d024af0`), Lake 5.0.0, Mathlib tag `v4.30.0` (`c5ea0035`).
- Real preflight: the final Lake package built `AuthorityContinuity.Main`; `#print axioms preflight_identity` reported no axioms; `leanchecker --fresh AuthorityContinuity.Main` exited 0 after 111.34 seconds.
- Raw preflight evidence: `lean/results/preflight.log` and `lean/results/leanchecker-preflight.log`.
- Full-run status: all ten frozen theorem names build from the root module; a clean 742-job build completed in 13.46 seconds (maximum RSS 2,109,000 KiB), the source audit found no placeholders or project axioms/constants, printed dependencies were limited to `propext`, `Quot.sound`, and `Classical.choice`, and an independent fresh kernel replay exited zero in 136.89 seconds.
- Independent result review: **mixed**. The computed restriction, exact Prepare/cleanup, ticket, binding, AC-simulation, and conditional trace results are valid, but `TopologyShape` supplies the target's main structural WF facts fieldwise rather than deriving them from canonical Fork/Restore/Merge construction and a checked transfer certificate.
- Paper decision: under the frozen interpretation rule, this run remains internal finite-submodel evidence and does not enter the current paper as a mechanization claim.
- Next gate: mechanize canonical topology targets, `Mono_0(pi)`, transfer/fiber conservation and certificate-checker soundness, then repeat the clean build and fresh independent result review. A dispatch-owning adapter remains separately necessary to test complete mediation and aggregate outcome assumptions.
