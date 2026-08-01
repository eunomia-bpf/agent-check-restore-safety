# Evaluation Contract

**Status:** pre-registration for a theory-first CSF paper. Values marked TBD are not results.

The first finite artifact is complete: 2,816 AC/need states, 3,428 safe-source single-claim promotions, 27,142 safe restrictions for maximality, and 13,680 ordered disjoint batches for confluence were exhaustively checked. These bounded counts support debugging and counterexample validation; they do not replace the planned proofs or runtime study.

## 1. Evidence priorities

The project is not evaluated like a throughput paper. Its evidence hierarchy is:

1. checked definitions and proofs;
2. automatically generated counterexamples for nearby unsound designs;
3. deterministic instantiations of the formal executions;
4. limited evidence that real agent runtimes expose the modeled lifecycle operations;
5. microbenchmarks only for explicit deployability claims.

Approximate paper allocation: 70--80% semantics/theorems/proofs, 10--15% mechanization and model exploration, and 10--15% runtime instantiation and overhead.

## 2. Research questions

### RQ1: Necessary lifecycle information

What durable information beyond restored workspace/context is necessary and sufficient to make sound, maximally permissive admission decisions across checkpoint, replace/live restore, abort, revocation, escape, and merge?

Evidence:

- one small-step semantics;
- the replace/live indistinguishable-snapshot pair;
- conditional-bundle and over-approximated-frontier counterexamples;
- implication/separation table against snapshot-local authorization, flat first-commit-wins, transaction validity, and commit-time freshness.

Success criterion: each distinction is witnessed by a minimal history, and independent reviewers can classify it from the formal definitions without relying on agent prose.

### RQ2: Most-permissive escape promotion

When a branch-conditional claim becomes irreversible, what is the largest existing future family that can safely remain possible without new authority or cancellation of other claims? Can concurrent promotions be admitted without order-dependent policy?

Evidence:

- proof of the exact plain-escape capacity condition;
- proof that the safe-frontier filter is downward closed and uniquely inclusion-maximal;
- proof that witnessed branch conditioning is a conservative subset;
- proof that batched promotion repairs commute;
- proof that recursive max/sum evaluation equals explicit maximal-frontier enumeration for structured trees;
- randomized property tests comparing algorithms on small generated instances.

Metrics:

- theorem/proof status and artifact location;
- agreement rate between recursive and exhaustive need (must be 100% for tested structured instances);
- smallest counterexample for each mutated rule;
- checker time by topology nodes, grant types, and graph density, only to support the tractability discussion.

### RQ3: Reality of the lifecycle boundary

Do real agent execution systems expose operations that alter co-durability, and can the formal litmus histories be instantiated without relying on a probabilistic model failure?

Evidence from at most two systems:

- one conversation/checkpoint runtime already represented by the repository's Claude Code session experiment;
- one structured fork/commit or multi-agent runtime with explicit branch selection or merge.

Required observations:

- whether the old continuation remains live after restore;
- whether losing branches can issue external calls before selection;
- whether a merge can retain outputs or effects from more than one child;
- which lifecycle decisions and effect receipts are durable;
- whether authority is copied, transferred, delayed in escrow, or rechecked.

The test workload must be deterministic. LLM-generated UUID drift may be included as motivation but is not required for the core violation.

### RQ4: Enforceability and cost

Can a small reference monitor reject authority-invalid histories while preserving useful pure exploration and safely admitted effects?

Baselines:

- **snapshot-local clone:** authorization state is copied with the checkpoint;
- **split-all:** authority is partitioned at every fork;
- **flat ledger / delayed escrow:** one global consumption ledger, with authority transferred only after selection;
- **transaction-only:** effects stage and settle correctly but bounded authority is not checked across descendants;
- **structured topology-aware:** the proposed monitor.

Metrics:

- invalid durable histories admitted (primary safety metric; target 0 for the proposed monitor);
- safe histories rejected;
- exact deficit and maximal retained frontier family returned;
- pure candidates allowed before selection;
- reserve, restore, merge, and escape latency;
- durable ledger writes and contention under parallel commits.

No overhead percentage will be claimed until a stable implementation and repeated measurement exist.

## 3. Fixed litmus suite

| ID | History | Expected classification |
|---|---|---|
| L1 | reserve one claim; escape; restore old local view; reserve/escape again | unsafe unless the first durable use remains charged |
| L2 | reserve one unit in each of two choose-one branches; select one | safe with one unit |
| L3 | start from L2; merge and retain both branch effects | unsafe; exact scalar deficit 1 |
| L4 | replace leaf \(b\) by restored epoch \(b'\) after durable tombstone | preserve surrounding context and need when binding-preserving claims transfer once |
| L5 | live-restore leaf \(b\) inside context \(E[b]\) | install \(E[b\parallel b']\), not \(E[b]\parallel b'\) |
| L6 | losing branch performs an issue-time disclosure, then aborts | disclosure remains durable/charged |
| L7 | reserve under epoch 0; revoke; restore epoch-0 snapshot; attempt escape | rejected as stale; earlier durable use remains accounted |
| L8 | two pure choice branches compute; parent transfers one claim after selection | safe under flat delayed escrow and proposed monitor; prevents a strawman comparison |
| L9 | two transaction-valid branches settle under a one-unit grant | transaction-valid but authority-invalid |

## 4. Mutation study

The explorer should delete or weaken one premise at a time:

- place durable claims inside the checkpoint;
- let abort delete escaped claims;
- make restore-live use choice rather than parallel topology;
- insert the restored clone outside its original lifecycle context;
- allow merge without re-admission;
- refresh stale epochs on restore;
- reuse a claim ID for a fresh effect;
- treat alternative claims inside one branch as a conjunctive bundle;
- dispatch before durable uncertain/escaped accounting;
- approximate general topology by pairwise data when the representation is not pairwise-complete.

For each mutation, report the shortest violating schedule found and map it to the theorem premise it demonstrates. This is stronger evidence than a collection of prompt anecdotes because it tests the logical necessity of the design.

## 5. Mechanization target

Lean 4 is the preferred target because the surrounding research program already uses it and CSF 2027 has strong mechanization expertise. The minimum useful artifact proves:

- unique-claim accounting and epoch well-formedness;
- terminal-ID non-reuse and claim-level promotion refinement;
- snapshot-local impossibility;
- plain-escape load split and exact capacity condition;
- maximal safe promotion support, witnessed promotion, and batch confluence;
- preservation for the explicitly modeled small transition core;
- correctness of structured need recursion.

The graph complexity proof may remain on paper if encoding it would displace higher-value mechanization. Proof size, trusted axioms, Lean version, build command, and build time are TBD.

## 6. Stop rules

The main claim must be narrowed or abandoned if:

- prior work already states an equivalent changing-co-durability authority theorem;
- the formal semantics cannot distinguish the proposed property from ordinary transaction validity;
- the snapshot-local theorem is already subsumed by equivalent prior lifecycle work or the maximal-support result has no enforceable consequence;
- a real lifecycle API cannot expose or enforce the topology witness assumed by the monitor;
- mechanization reveals that the transition rules silently assume the desired invariant.
