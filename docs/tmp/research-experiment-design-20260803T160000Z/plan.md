# Experiment Plan: Kernel-check the Agent security-state characterization

## Research Question

- RQ exactly as written in the paper: “When does an Agent history rewrite
  have a policy-safe, history-faithful, completion-nonblocking realization
  preserving every structurally promised outcome, and how can a reference
  monitor realize exactly that boundary while effects race the rewrite?”
- Specific uncertainty tested here: whether the paper's finite registered-slice
  semantics supports a non-circular, kernel-checked characterization joining
  exact compilation, information lower bounds on P/I/E/C and two incidence
  relations, closure from one natural genesis, and bidirectional durable
  refinement.
- Why the answer matters: all four fresh CSF reviews judged the central insight
  promising but the headline theorem insufficiently auditable because its
  records, answer function, reachability argument, event relation, and
  bisimulation bridge remain partly prose.

## Paper-Value Admission

- Planned role: decisive.
- Largest credible paper story this experiment could unlock: Agent History
  Admission is a mechanically checked characterization that derives an
  edit-specific security state, constructs its greatest safe monitor or proves
  impossibility, and remains correct across reachable Fork/Restore/Merge
  histories and effect/edit races.
- Strongest reviewer reject argument or load-bearing uncertainty addressed:
  the main theorem currently depends on prose inventories for its four evidence
  factors, a partly implicit projection model, arbitrary bootstrapped
  separation states, and a prose-level durable LTS.
- Independent evidence added beyond existing runs and published results: the
  existing Lean development checks an earlier authority-continuity model, and
  the Python artifact checks bounded examples. Neither defines or proves the
  current paper's joined Agent-history characterization.
- Why the result is not tautological, already settled, or dominated:
  generalized nonblocking supplies only a synthesis backend after a plant and
  outcome markings are given. The new proof checks the Agent-specific
  derivation, occurrence/cell/receipt distinctions, reachable edit histories,
  and cut refinement that the backend assumes.
- Paper decision if positive: retain and substantiate the unified
  characterization thesis; replace the current auxiliary-mechanization claim
  with an exact theorem-coverage map.
- Paper decision if contradictory, mixed, or inconclusive: preserve the
  counterexample and repair the scientific model before revising the paper.
  Partial compilation or infrastructure progress is not paper evidence.
- Best alternative experiment and why this one has higher decision value:
  another runtime integration could ground deployment, but the repository
  already has a bounded Codex adapter and all four reviewers prioritized
  formal auditability over performance or another interface demo.

## Frozen Formal Contract

The experiment has four new modules in dependency order. The theorem names
below are frozen completion obligations, not examples that may be renamed or
dropped during execution.

### 1. `AuthorityContinuity/AgentHistoryAdmission/FiniteCore.lean`

Paper-matched definitions:

- `Frontier` with leaf, choice, parallel, join-barrier, and sequence cases;
- `Edit` with exactly `forkChoice`, `forkParallel`, `restoreReplace`,
  `restoreLive`, `mergeSelect`, and `mergeJoin`;
- explicitly enumerated `PromiseFactor`, `IdentityFactor`, `EffectFactor`,
  `CutFactor`, `FullView`, `ValidView`, and `DerivedCut`;
- P rows for frontier/provenance/checkpoints/schemas/lifts/retirement;
- I rows with separate occurrence/cell marginals, `occCell`, gate, handle,
  lineage, scope, invocation, digest, and label;
- E rows with separate receipt marginals, `receiptCell`, `receiptCreator`,
  `cursorReceipt`, cursor, result future, outbox, and residual policy;
- C rows for domain, policy/schema/view versions, epoch phase/freshness, gate
  ownership, active epoch, certificate metadata, and checkpoint coordinates;
- `deriveEdit`, `Resolved`, `resolve`, `IndexedCompletion`, `b0`, `compat`,
  `phi`, declarative `Realization`/`GreatestRealization`, executable
  `greatestPostfixed`, `PruningCertificate`, `CanonicalProgram`, and `Query`;
- two independent answers: `SemanticAns` is defined only through the
  declarative realization/specification relation; `CompilerAns` is defined
  only through derivation, the executable fixed point, certificate checking,
  and compilation. Neither is defined in terms of the other.

Seals and digests are pure recomputed functions of enumerated base fields, not
extra information stores. Frozen theorems:

- `deriveEdit_deterministic`
- `deriveEdit_preserves_valid`
- `resolve_prefix`
- `phi_monotone`
- `greatestPostfixed_fixed`
- `greatestPostfixed_is_realization_iff_nonempty`
- `realization_subset_greatestPostfixed`
- `declarativeSpec_unique`
- `verifyPruningCertificate_eq_greatest`
- `compilerAns_eq_semanticAns`
- `canonicalProgram_generated_marked`
- `residual_greatestPostfixed_coherent`

Together these must prove the paper's exact-compilation clause against an
independently defined realization—not merely show that one executable checker
agrees with another.

### 2. `AuthorityContinuity/AgentHistoryAdmission/OperationalSemantics.lean`

Definitions:

- one literal empty `genesis`;
- a constrained `RegisteredSlice` input containing contracts, schemas, policy,
  and authenticated identity rows, but no receipts, cursor, outbox, epoch,
  certificate, result future, or monitor state;
- deterministic initial installation that constructs those runtime fields;
- `AgentSec` with the paper's five named coherence clauses;
- independent inductive `IdealStep` and `KernelStep` relations, with separate
  guards and updates. `KernelStep` must not be defined as `IdealStep` plus
  metadata.

The exhaustive kernel event relation contains registration, initial
installation, successful edit/installation for each of the six edits,
`freshUse`, `aliasUse`, denied use, `save`, `preload`, stale/failed install,
retry, result-bundle retrieval, result delivery, dispatch, settlement, and
crash/recovery. Request arrival and scheduling are explicit silent events if
they are retained in the paper model. Ideal steps contain the semantic
counterparts; preload and failed installation are kernel-only silent steps.

Frozen theorems:

- `initialize_agentSec`
- `kernelStep_preserves_agentSec`
- `kernelTrace_preserves_agentSec`
- `fresh_before_install_stale`
- `alias_before_install_stale`
- `install_before_old_use_denied`
- `six_edits_closed`

`kernelTrace_preserves_agentSec` quantifies over the reflexive-transitive
closure of the exhaustive event relation, establishing closure at every finite
prefix rather than testing a bounded list of traces.

### 3. `AuthorityContinuity/AgentHistoryAdmission/ReachableEvidence.lean`

Definitions:

- `Factor`, `FactorMask`, typed `MaskedView`, explicit `eraseOccCell` and
  `eraseReceiptCell`, and private-name isomorphism after dependent-field
  deletion;
- `Exact` over `SemanticAns`, answer equivalence, and the canonical
  `DecisionQuotient`;
- concrete finite P/I/E/C and occurrence--cell/receipt--cell separating worlds;
- `Reachable S := Relation.ReflTransGen (fun a b => exists e, KernelStep a e b)
  genesis S`.

Every world has a displayed constructor trace from the same empty genesis
through constrained registration, checked initial installation, and actual
Save/use/edit/install transitions. In particular, E receipts are created only
by `freshUse`; C version differences arise only by real history/version
transitions; no state with a receipt, cursor, epoch, certificate, or installed
program can be injected as an initial state.

Frozen theorems:

- `decisionQuotient_exact`
- `every_exact_abstraction_refines_decisionQuotient`
- `fullEvidence_exact`
- `p0_reachable`, `p1_reachable`, `i0_reachable`, `i1_reachable`,
  `e0_reachable`, `e1_reachable`, `c0_reachable`, `c1_reachable`
- `p_projection_collision`, `i_projection_collision`,
  `e_projection_collision`, `c_projection_collision`
- `p_answers_differ`, `i_answers_differ`, `e_answers_differ`,
  `c_answers_differ`
- `occCell_projection_collision`, `occCell_answers_differ`
- `receiptCell_projection_collision`, `receiptCell_answers_differ`
- `properFactorProjection_not_exact`
- `eraseOccCell_not_exact`
- `eraseReceiptCell_not_exact`
- `all_separation_worlds_reachable`

Each lower bound therefore requires both a proved projection
equality/isomorphism and proved opposite declarative answers. Opposite answers
alone do not count.

### 4. `AuthorityContinuity/AgentHistoryAdmission/DurableRefinement.lean`

Definitions:

- `SecurityObservation` exactly for `Edge`, `Fresh`, `Alias`, `deny`, and
  `Dispatch`, with all other events silent;
- explicit `obs`, `alphaI`, `alphaS`, relation `R`, tau closure, weak step, and
  divergence-insensitive `WeakBisimulation`;
- `TxImage(pre, post, linearized)` and `recover`, making crash-stable atomicity
  a typed premise;
- matching over every event constructor in the two exhaustive LTSs, including
  silent paths for Save, preload, failed/stale installation, retry, retrieval,
  delivery, settlement, request/scheduling when present, and crash/recovery.

Frozen theorems:

- `recover_before_eq_pre`
- `recover_after_eq_post`
- `recovered_crash_tau`
- `idealStep_matches_kernel`
- `kernelStep_matches_ideal`
- `agentHistoryAdmission_weakBisimulation`
- `agentSecurityStateCharacterization`

The assembly theorem must expose all four clauses: exact compilation against
the declarative spec, factor/incidence tightness on reachable pairs,
finite-sequence closure, and durable bidirectional weak bisimulation.

## Expected And Alternative Outcomes

- Current expected answer: all frozen obligations are consistent and
  kernel-checkable for the finite registered-slice semantics.
- Strongest competing explanation: the broad theorem currently works only
  because prose leaves incompatible identity, outcome, cut, or recovery choices
  underspecified; complete formalization either needs a new premise or
  invalidates a lower-bound, reachability, closure, or refinement clause.
- Contradictory result: any generated well-formed history for which
  `CompilerAns` differs from `SemanticAns`; any separation pair lacking either
  reachability, projection collision, or opposite answers; any kernel event
  breaking `AgentSec`; or either direction of weak simulation failing.

## Published Precedent And Real Assets

- Closest proof protocol: kernel-checked theorem statements, explicit axiom
  audits, and small separating models as used in CSF theory papers. The
  generalized-nonblocking backend is compared by citation rather than
  reimplemented as a competing system.
- Actual toolchain: Lean 4.30.0, Lake 5.0.0, and Mathlib v4.30.0 pinned in
  `lean/`. A task-local Elan 4.2.3 installation now exposes Lean and Lake at
  `/home/will/.cache/agent-history-elan/bin/`.
- Reused assets: only the pinned environment, audit/axiom-allowlist workflow,
  generic finite-set and reflexive-transitive-closure proof idioms, and the
  Python artifact as an oracle to port/check.
- Explicitly not reused as central evidence: `TypedHistoryAdmission.HistoryOp`
  (cell-set families, not indexed outcomes), `DurablePrefixTransport.safeFuture`
  (pointwise filtering, not the shared-prefix fixed point),
  `Lifecycle.Step` (the old authority lifecycle), and
  `IdentityQuotientSeparation` (only a proof pattern).

## Comparison And Controls

- Proposed method: the complete paper-matched Lean semantics and theorem
  package.
- Numerical baseline: none is scientifically meaningful. Generalized
  nonblocking, live synthesis, Shepherd, DART, and Cordon are claim/semantics
  precedents, not interchangeable executable baselines for whether this proof
  is correct.
- Controls:
  - erase each P/I/E/C factor and prove projection collision plus opposite
    answers;
  - erase occurrence--cell or receipt--cell incidence while retaining their
    marginals;
  - replace reachable traces by arbitrary initial states only as a rejected
    control;
  - omit receipt-silent alias progress from C and show the stale-cut race;
  - test both orders of old use versus edit installation.
- Conclusion if a control matches the full semantics: if an erased view remains
  exact, that necessity clause fails; if an arbitrary-state witness cannot be
  reconstructed from genesis, it is not evidence; if receipt-only fencing
  matches all cut races, the alias-race necessity claim fails.

## Workloads And Metrics

- Workloads: all six typed edits; the shared-prefix fixed-point witness; every
  factor/incidence pair; and the complete event constructors enumerated above.
- Primary metric: every frozen theorem elaborates, appears in the audit root,
  has only allowed foundational dependencies, and survives fresh kernel replay.
- Correctness ground truth: the independent declarative definitions, Lean
  kernel, theorem dependency output, and fresh `leanchecker` replay.
- Repetitions/seeds: deterministic; one clean build, one complete axiom audit,
  and one fresh replay. Build time is provenance, not a scientific result.

## Planned Runs

| Run group | Role | Frozen completion |
|---|---|---|
| real preflight | dependency | compile one independent `SemanticAns`/`CompilerAns` shared-prefix witness and prove one pruning step plus their answer equality |
| finite core | decisive | all `FiniteCore` definitions and twelve frozen theorems |
| operational closure | decisive | exhaustive `KernelStep`, five-clause `AgentSec`, and all seven frozen preservation/race theorems |
| reachable separation | decisive | explicit genesis traces, every projection collision, every opposite answer, and all exactness theorems |
| durable refinement | decisive | independent ideal/kernel LTS matching in both directions and the assembly theorem |
| audit | correctness | clean build, placeholder/axiom scan, `#print axioms`, and fresh root replay |

## Execution

All commands run from `lean/` with the installed pinned toolchain:

```sh
ELAN_HOME=/home/will/.cache/agent-history-elan \
PATH=/home/will/.cache/agent-history-elan/bin:/usr/local/bin:/usr/bin:/bin \
lake clean
ELAN_HOME=/home/will/.cache/agent-history-elan \
PATH=/home/will/.cache/agent-history-elan/bin:/usr/local/bin:/usr/bin:/bin \
lake exe cache get
ELAN_HOME=/home/will/.cache/agent-history-elan \
PATH=/home/will/.cache/agent-history-elan/bin:/usr/local/bin:/usr/bin:/bin \
lake build AuthorityContinuity
ELAN_HOME=/home/will/.cache/agent-history-elan \
PATH=/home/will/.cache/agent-history-elan/bin:/usr/local/bin:/usr/bin:/bin \
./scripts/audit.sh
ELAN_HOME=/home/will/.cache/agent-history-elan \
PATH=/home/will/.cache/agent-history-elan/bin:/usr/local/bin:/usr/bin:/bin \
lake env leanchecker --fresh AuthorityContinuity.Main
```

- Real preflight: define the actual shared-prefix outcome fixture in
  `FiniteCore.lean`, compute its executable pruning round, state the
  declarative realizability answer independently, and prove equality.
- Full completion rule: every frozen theorem is imported by
  `AuthorityContinuity.Main`, listed in `Audit.lean` and the audit allowlist,
  builds without placeholders or project axioms, and survives fresh replay.
  Every negative control remains a proved counterexample.
- Raw results:
  `docs/tmp/research-experiment-design-20260803T160000Z/raw/` and generated
  audit logs under `lean/results/`.
- Recovery rule: preserve failed logs and repair only elaboration or theorem
  defects. Do not change the RQ, oracle, expected answer, theorem names, event
  coverage, genesis, or completion rule without a new plan review.

## Interpretation

- Positive: the full registered-slice characterization is mechanically
  supported, including reachable lower bounds, arbitrary finite-prefix
  closure, and durable bidirectional refinement.
- Negative: preserve the counterexample and repair the scientific model; do
  not weaken the headline through prose.
- Mixed/inconclusive: report exactly which central frozen theorem remains
  unproved. Auxiliary compilation does not validate the whole theorem.
- Paper target: a compact theorem-to-mechanization coverage table, not a new
  performance result.

## Reproducibility Notes

- Software: `leanprover/lean4:v4.30.0`, Mathlib `v4.30.0`, Lake 5.0.0, Elan
  4.2.3; repository-pinned manifest.
- Config/seeds: deterministic finite definitions; no seeds.
- Declared theorem premises: finite registered protected-call slices, trusted
  schemas and policy, complete mediation, and crash-stable atomic domain
  transactions. These are explicit theorem premises, not empirical claims
  about arbitrary Agent runtimes.
