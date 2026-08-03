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
- finite nonempty indexed pomset contracts, strict partial-order
  well-formedness, occurrence-preserving linearizations, completion
  observability, partial choice/parallel/sequence constructors, and indexed
  residuals;
- `Edit` with exactly `forkChoice`, `forkParallel`, `restoreReplace`,
  `restoreLive`, `mergeSelect`, and `mergeJoin`;
- explicitly enumerated `PromiseFactor`, `IdentityFactor`, `EffectFactor`,
  `CutFactor`, `FullView`, `ValidView`, and `DerivedCut`;
- P rows for frontier/provenance/checkpoints/schemas/lifts/retirement;
- I rows with separate occurrence/cell marginals, `occCell`, gate, handle,
  protected-call issuer, lineage, scope, invocation, digest, and label;
- E rows with separate receipt marginals, `receiptCell`, `receiptCreator`,
  `cursorReceipt`, cursor, immutable invocation, creator, authority label,
  phase, stable result future, outbox preparation/release order, and residual
  policy;
- C rows for domain, policy/schema/view versions, epoch phase/freshness, gate
  ownership, active epoch, generations, certificate metadata, and checkpoint
  coordinates;
- an explicit typed join that binds checkpoints to
  contracts/cursors/registries, occurrences to outcomes/cells, receipts to
  cells, and the cursor to the admitted cut;
- an inductive declarative `HistoryDerivation` judgment and a separately
  defined executable `deriveEdit`;
- `Resolved`, `resolve`, per-outcome `R_o` and `M_o`,
  `IndexedCompletion`, `b0`, `compat`, `phi`, the full descending chain,
  `Bdagger`, `Wdagger`, declarative `Realization`/`GreatestRealization`,
  executable `greatestPostfixed`, `PruningCertificate`, `CanonicalProgram`
  with derivative states `q_z=(W/z,B/z)`, and `Query`;
- a genuinely dependent `Query.Answer` family:
  `Query.edit u -> EditAnswer` and
  `Query.install iq -> InstallAnswer`; queries are syntactically typed but need
  not name state-valid objects;
- two independent answers: `SemanticAns` is defined only through the
  declarative history judgment, realization/specification, and an independent
  `SemanticInstallable` relation; `CompilerAns` is defined only through
  executable derivation, fixed point, raw certificate checking, and
  compilation. An edit answer distinguishes
  `structuralReject`, `rejectNoRealization`, and `greatestRealization`; an
  installation answer distinguishes `installAccept` and `installReject`.
  Both functions are total on every valid view and syntactically typed query.
  Compiler-specific diagnostic text and proof encodings are normalized away
  only after verification; certificate validity itself is never erased before
  deciding installation. Neither answer is defined in terms of the other.
- `SemanticInstallable(V,iq)` over an operational-independent
  `FullView`/`DecisionState` requires, without invoking the executable
  verifier, that the submitted artifact's normalized source is the current
  full cut, its derivation is the current declarative candidate derivation,
  its languages are the declarative greatest realization, its reachable
  deterministic marked program is cardinal-minimal for those languages, its
  target allocation is feasible and matches the derivation, and its symbolic
  seals are the recomputed equivariant constructors over exactly those fields;

Seals and digests are pure recomputed functions of enumerated base fields, not
extra information stores. Frozen theorems:

- `deriveEdit_deterministic`
- `deriveEdit_preserves_valid`
- `deriveEdit_sound_complete`
- `structuralFailure_iff_noHistoryDerivation`
- `contractSemantics_completionObservable`
- `contractResidual_linearizations`
- `resolve_deterministic`
- `resolve_length`
- `resolve_occurrence_projection`
- `resolve_fresh_cell_unique`
- `resolve_streaming`
- `resolve_authority_word`
- `resolve_prefix`
- `phi_monotone`
- `greatestPostfixed_fixed`
- `greatestPostfixed_is_realization_iff_nonempty`
- `realization_subset_greatestPostfixed`
- `declarativeSpec_unique`
- `semanticEditAnswer_exhaustive`
- `semanticInstallAnswer_exhaustive`
- `semanticAns_equivariant`
- `compilerDiagnostic_normalization_sound`
- `certificateNormalization_preservesInstallDecision`
- `verifyPruningCertificate_eq_greatest`
- `compilerAns_eq_semanticAns`
- `structuralFailure_sound`
- `emptyPruningCertificate_excludes_every_realization`
- `postfixed_iff_indexedGeneralizedNonblocking`
- `ordinaryMarkerNonblocking_strictly_weaker`
- `canonicalProgram_generated_marked`
- `canonicalProgram_derivative_exact`
- `canonicalProgram_minimal_up_to_renaming`
- `residual_greatestPostfixed_coherent`

Together these must prove the paper's exact-compilation clause against an
independently defined realization—not merely show that one executable checker
agrees with another. Canonical minimality is cardinal minimality among
reachable deterministic partial marked programs realizing the same
\((W,B)\); only an equally minimal program is required to be isomorphic up to
state renaming.

### 2. `AuthorityContinuity/AgentHistoryAdmission/OperationalSemantics.lean`

Definitions:

- one literal empty `genesis`;
- `CutOrigin = root InitialDerivation | edit HistoryDerivation`; the root form
  checks a registered base contract and policy without inventing a seventh
  history edit, while every later cut names one of the six edit derivations;
- a common `CutSpecification` projected by both root and edit origins, carrying
  source, target, derived indexed contract, policy, registry, epoch, and
  semantic realization instance; promise/certificate/monitor coherence is
  parameterized by this common specification rather than by an edit request;
- a separate pre-slice `BootstrapStep` relation for registration and checked
  initial installation, and `SystemStep` as bootstrap-or-installed execution;
  registration and initial installation are not constructors of the paper's
  installed-slice `KernelStep`;
- a constrained `RegisteredSlice` input containing contracts, schemas, policy,
  and authenticated identity rows, but no receipts, cursor, outbox, epoch,
  certificate, result future, monitor state, or preinstalled cut;
- checked initial installation that constructs those runtime fields and is
  deterministic from the registered slice and a fresh private namespace/domain
  seed chosen by the bootstrap registration event. Every subsequent epoch,
  gate, handle, and certificate name is deterministically allocated from
  `(namespace, schemaVersion, viewVersion, request, role)`, matching the paper;
  alternative registration traces may choose different private seeds without
  injecting a receipt, cursor, epoch, certificate, or program;
- `AgentSec` with the paper's five named coherence clauses;
- independent inductive `IdealStep` and `KernelStep` relations, with separate
  guards and updates. `KernelStep` must not be defined as `IdealStep` plus
  metadata.
- `AtomicSwapFeasible(S,δcand,M,allocation)` and
  `ExactAtomicRealization(S,δcand,M,B,allocation)`. The latter requires a
  declarative realization and independent atomic-swap feasibility; neither
  definition mentions `Admit`, the fixed point, compiler/checker output,
  canonical monitor, ideal `Edge`, kernel installation premises, or
  `AgentSec`.

The five clauses are frozen extensionally:

1. core/schema coherence includes the well-formed core, current certificate,
   a checked `CutOrigin` (root only for initial installation, otherwise a
   history derivation), and a full-target lift for every required outcome;
2. promise coherence equates stored indexed completions to the nonempty
   greatest fixed point, generated language to its projected prefix closure,
   and certificate verification to the same source cut;
3. execution coherence equates the resolved trace, structured residual, and
   authority word to source-plus-prefix; requires unique Fresh receipts,
   earlier-receipt Alias, ordered outbox preparation/release, monotone phases
   and stable futures, and authenticated Save-only checkpoint extension;
4. monitor coherence makes the installed program isomorphic to the canonical
   monitor and its state exactly `q_r`;
5. epoch coherence requires exactly one active epoch, one authenticated current
   binding per live occurrence, no handles from inactive epochs, no
   reactivation of closed epochs, and fresh candidate epochs that are
   unallocated or inactive and unbound.

The exhaustive installed-slice kernel event relation contains `freshUse`,
`aliasUse`, successful edit/installation separately for each of the six edits,
`save`, `preload`, authenticated retry, durable replacement-handle-bundle
retrieval, result delivery, denial, dispatch, settlement, failed/stale
installation, and crash/recovery. Denial covers failure of every
occurrence/gate/handle/invocation/epoch/branch/monitor guard and every invalid
or argument-changing retry. Request arrival and scheduler choice have no
durable transition and are not state-changing constructors. Ideal steps
contain the semantic counterparts; preload and failed installation are
kernel-only silent steps.

Frozen theorems:

- `initialize_agentSec`
- `initialize_rootCut`
- `nonRootCut_hasEditDerivation`
- `historyDerivation_preserves_outcomes_lineage_and_handoff`
- `kernelStep_preserves_agentSec`
- `kernelTrace_preserves_agentSec`
- `fresh_before_install_stale`
- `alias_before_install_stale`
- `install_before_old_use_denied`
- `six_edits_closed`
- `fixedPoint_nonempty_iff_exactAtomicRealization`
- `compiler_installPremise_iff_exactAtomicRealization`
- `semanticInstallable_iff_verifiedInstall`
- `successfulEdge_iff_exactAtomicRealization`

`kernelTrace_preserves_agentSec` quantifies over the reflexive-transitive
closure of the exhaustive event relation, establishing closure at every finite
prefix rather than testing a bounded list of traces.

### 3. `AuthorityContinuity/AgentHistoryAdmission/ReachableEvidence.lean`

Definitions:

- `Factor`, `FactorMask`, typed `MaskedView`, explicit `eraseOccCell` and
  `eraseReceiptCell`, a target-only view `tauTgt`, and private-name isomorphism
  after dependent-field deletion;
- `InputQ = Quotient(FullView × Query)` under diagonal typed permutations,
  `ProjectedInputQ(J)` over `(project_J view, query)`, and `Exact` as existence
  of a decoder from projected joint inputs to the equivariant semantic answer;
  no equivalence between the setwise stabilizer of a structured query and the
  pointwise fixer of its support is assumed;
- `joinFactors : P -> I -> E -> C -> Option FullView`, unique base-field
  ownership, typed-key agreement, canonical recomposition, and dependency
  deletion that removes seals/digests/foreign-key paths transitively;
- the dependency schema is static and unary. Although gate and handle records
  are I-owned, every such row has declared foreign-key dependencies on its C
  epoch/ownership record. Erasing C therefore deletes all gate/handle rows and
  paths whose transitive schema dependency reaches seed, epoch, or ownership
  for every input, regardless of values or which pair is later compared;
- answer equivalence and the canonical `DecisionQuotient`, all over `InputQ`;
- concrete finite P/I/E/C and occurrence--cell/receipt--cell separating worlds;
- `Reachable S := Relation.ReflTransGen (fun a b => exists e, SystemStep a e b)
  genesis S`, so the same relation contains the constrained bootstrap prefix
  and subsequent installed-slice kernel events.

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
- `joinFactors_undefined_on_disagreement`
- `joinFactors_recomposes_valid`
- `projection_commutes_with_privateRenaming`
- `projection_wellDefined`
- `projectedInput_wellDefined`
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
- `targetOnly_not_exact`
- `all_separation_worlds_reachable`

Each lower bound therefore requires both a proved projection
equality/isomorphism and proved opposite declarative answers. Opposite answers
alone do not count.

### 4. `AuthorityContinuity/AgentHistoryAdmission/DurableRefinement.lean`

Definitions:

- fully parameterized trusted event records carrying every hidden guard
  payload, with simultaneous state/event private-name renaming;
- `SecurityObservation` exactly for `Edge(Edit)`, `Fresh(Occurrence,Cell)`,
  `Alias(Occurrence,Cell)`, `deny(Occurrence)`, and `Dispatch(Cell)`, with all
  other events silent;
- explicit `obs`, `alphaI`, `alphaS`, relation `R`, tau closure, weak step, and
  divergence-insensitive `WeakBisimulation`; `alphaI=alphaS` means equality in
  the common nominal quotient, not equality of arbitrarily chosen raw names;
- `R(rho,I,S)` carries one typed partial bijection/nominal world `rho` that
  fixes only public atoms, maps the common abstractions, and is extended
  monotonically—not replaced—when a step allocates or extrudes a fresh
  observable identifier. Previously observed private atoms retain their
  existing cross-machine `rho` pairs; they need not become identical raw names;
- a common abstraction containing exactly normalized history, receipt ledger,
  outbox, admitted semantic cut, resolved prefix, result futures, abstract
  active epoch, and live gate bindings; it excludes the phase protocol, seals,
  preload contents, and handoff metadata;
- `EventDerivative : Quotient(State × Event) -> Option (Quotient State)` under
  simultaneous private-name renaming, defined exactly on enabled guards, plus
  a trace derivative on `Quotient(State × List Event)` so identities allocated
  or reused across events are renamed consistently; ideal and kernel state/event
  types receive separate instances of this generic construction;
- `obs` is equivariant. A visible match uses the same persistent `rho`, and the
  successor relation carries an extension `rho'` whose restriction agrees with
  `rho` on every previously observed or still-live atom in its domain and
  codomain, while both maps fix Public. Evidence is compared on the diagonal
  orbit of the entire observable trace, never by independent per-label orbits;
- `TxImage(pre, post, linearized)` and `recover`, making crash-stable atomicity
  a typed premise;
- matching over every event constructor in the two exhaustive LTSs, including
  silent paths for Save, preload, failed/stale installation, retry, retrieval,
  delivery, settlement, request/scheduling when present, and crash/recovery.

Frozen theorems:

- `recover_before_eq_pre`
- `recover_after_eq_post`
- `recovered_crash_tau`
- `event_equivariant`
- `eventDerivative_wellDefined`
- `eventDerivative_defined_iff_guard`
- `eventDerivative_successor_evidence`
- `eventDerivative_iff_step`
- `traceDerivative_wellDefined`
- `traceDerivative_iff_labeledTrace`
- `observableMatching_equivariant`
- `obs_equivariant`
- `observableTrace_equivariant`
- `weakBisim_preserves_observationTraceOrbit`
- `idealStep_matches_kernel`
- `kernelStep_matches_ideal`
- `agentHistoryAdmission_weakBisimulation`
- `everyGoodInitialPair_weakBisimilar`
- `independentDomains_asyncProduct`
- `agentSecurityStateCharacterization`

The assembly theorem must expose all four clauses: the four-way exact
compilation equivalence (fixed point, independent atomic realization, full
install premise, and successful weak Edge), factor/incidence/target-only
tightness on reachable pairs, representative-independent finite-sequence
derivatives and closure, and durable bidirectional weak bisimulation for every
good post-installation pair. Supporting corollaries include canonical-monitor
minimality and asynchronous product composition for disjoint domains.

The four-way equivalence explicitly separates `origin(cold)`—the root or prior
edit that produced the already installed cut—from
`δcand : HistoryDerivation(S.H,u,...)`, the new candidate derivation from the
current progressed history. Its common premises are:

- `AgentSec(S,cold,r)`;
- `δcand` starts from exactly `S.H`, has `δcand.ηminus = S.H.epoch`, and names
  the exact target gates;
- the honest raw compiler output is computed from exactly
  `(S.κ,S.H,S.Δ,S.out,S.policy,u)`;
- the candidate allocation is exactly `δcand.ηplus`, is unallocated or
  inactive, unbound, not closed, and has all target gates fresh and unbound.

Under only those shared premises, the theorem equates:

1. nonempty \(\widehat B^\dagger_{\delta cand}\);
2. existence of `ExactAtomicRealization(S,δcand,M,B,allocation)`;
3. the full executable installation premise for the exact compiler output;
4. a weak kernel path whose hidden successful label is
   `installSuccess(u,δcand,output,allocation)` to some \(S^+\) satisfying
   `AgentSec(Splus,cδplus,epsilon)`, where `cδplus` is constructed from that
   same candidate derivation, compiler output, and allocation.

Only after this equivalence is established is the hidden label projected to
the public observation `Edge(u)`. Bare `Edge(u)` is not used to select the
artifact or allocation. Structural rejection is outside this equivalence and
is covered by answer exhaustiveness. Nonempty
\(\widehat B^\dagger\) is never asserted to imply installation for an
unrelated, stale, closed, or already-bound epoch.

## Binding Paper-Contract Audit

A reverse audit after the first plan review found that the frozen PDF currently
defines every valid `BootOK` post-installation state as initial, making its
lower-bound worlds length-zero reachable. That is the reviewer-identified
reachability defect, not the semantics to mechanize. The stronger genesis
theorem above is the intended repair and therefore requires a later,
meaning-preserving paper amendment if it succeeds.

The C pair is not allowed to rely on a same-run transition that changes only C.
Instead, both states must be reachable from the common empty genesis through
alternative bootstrap registrations that differ only in their fresh private
namespace/domain seed, followed by deterministic checked initial installation.
After erasing C, seed/epoch ownership, and every dependent authenticator, their
P/I/E views are isomorphic. The input type is the diagonal nominal quotient
`InputQ = Quotient(FullView × Query)`; projection at a fixed query is analyzed
inside that diagonal quotient without assuming query rigidity.
Every collision theorem, especially C, states equality of projected joint
inputs rather than equality of view orbits alone.

The C witness must exhibit one permutation that fixes
`Public ∪ supp(query)` pointwise, maps the two projected views, proves that
every differing query-supported atom was erased, and proves every retained
query-supported name and fact literally identical. Gates/handles derived from
the seed are deleted by the same predeclared unary dependency closure on both
worlds, never by a pair-dependent comparison. This deletion is compatible with
I ownership because the erased C foreign-key target is mandatory for those
rows. Seals and digests are equivariant symbolic constructors whose support is
their payload, never raw strings with a trivial name action. The common install
query is accepted in the world that minted it and stale in the independently
initialized world.

The real preflight is intentionally narrower than full completion: it checks
that the independent declarative and executable encodings elaborate and
reproduce the `[2,1,0]` shared-prefix fixture. It must represent the durable
authority prefix separately from the candidate trace and map cells through
authority labels; using cell strings directly as policy symbols is rejected.
A positive fixture result does not count as any general theorem above.

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
| finite core | decisive | all `FiniteCore` definitions and every theorem frozen by name above |
| operational closure | decisive | exhaustive bootstrap/system/kernel relations, five-clause `AgentSec`, and every operational theorem frozen by name above |
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
