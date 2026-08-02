# Experiment Plan: RQ3 dynamic redemption topology

**Revision 2.**  The independent plan review rejected global scalar
conservation as the complete model.  This revision makes a
configuration-indexed semantic-cell quotient the hypothesis and retains
scalar escrow conservation only as the detached/product-independent
corollary.  It also distinguishes fresh authority commitments from retry
responses, returned tickets, and external sink receipts.

## Research Question

- RQ exactly as written in the paper: **Does the abstract invariant refine a
  real agent lifecycle? Which facts must a concrete runtime expose so
  checkpoint, exclusive/parallel fork, selection, abort, replace/live restore,
  merge, revocation, uncertain dispatch, and settlement preserve authority
  continuity?**
- Specific uncertainty tested here: whether a two-stage map from history
  handles to semantic redemption cells and from those cells to source
  authority atoms exactly characterizes preservation of bounded authority over
  every lifecycle-feasible future, and whether typed Fork, Restore, Merge,
  Prepare, Retry, and Settle derive this property without assuming it.
- Why the answer matters: the current occurrence-count invariant rejects safe
  shared aliases and undercounts temporal restore attacks.  A correct answer
  decides whether the paper has an agent-lifecycle theorem rather than a
  renamed linear-resource or workspace-rollback rule.

## Paper-Value Admission

- Planned role: **decisive**.
- Largest credible paper story this experiment could unlock: agent history
  operators dynamically change the relation from copied action handles to
  rollback-independent admission state.  Histories and representations may be
  copied, but independently redeemable capacity cannot be amplified.  A
  mechanized operator contract refines shared ratification, fencing, and escrow
  into safe agent Fork/Restore/Merge histories.
- Strongest reviewer reject argument or load-bearing uncertainty addressed:
  active-domain cardinality may be definitional, occurrence linearity is not
  necessary behind one atomic redeemer, and generic coordination/escrow is
  prior work.  The experiment must therefore derive safety from explicit cell
  transitions and prove the lifecycle-specific operator obligations.
- Independent evidence added beyond existing runs and published results: the
  repository already proves occurrence transport and stable post-Prepare
  bindings, but it has no event-based quota ledger, no safe-alias witness, no
  cloned-cell temporal attack, and no conservation proof for domain-changing
  operators.  Existing literature establishes the component mechanisms, not
  their typed transport through agent lifecycle operations.
- Why the result is not tautological, already settled, or dominated: a cell is
  an independently addressed linearization object, not an equivalence class
  defined by which calls happen to succeed.  Co-redeemability comes from the
  independently defined lifecycle semantics.  The proof must give an exact
  universal-resource interpretation of the resulting configuration morphism
  and typed operator refinement; local injectivity and configuration
  preservation themselves are credited as classical event-structure
  machinery.  No constructor may take target safety, per-cell uniqueness, or
  target potential as a premise.
- Paper decision if positive: center RQ3 on event-based domain conservation and
  typed lifecycle refinement; retain current occurrence linearity only as the
  injective, independently-preparable representation corollary.
- Paper decision if contradictory, mixed, or inconclusive: if conservation
  cannot be derived without target-safety premises, retain only shared-gate and
  clone counterexamples and narrow the paper to an architectural separation
  result; if only some operators preserve it, state those operators and make
  the others require reauthorization or stop.
- Best alternative experiment and why this one has higher decision value: more
  trace counting cannot reveal shared physical admission state or prove
  safety.  This experiment repairs a known false central claim and directly
  tests the paper's remaining novelty boundary.

## Expected And Alternative Outcomes

- Current expected answer: let

  ```text
  history handles H --resolve--> semantic cells D --lineage--> authority atoms U.
  ```

  `resolve` may identify arbitrarily many aliases.  For every trusted
  co-redeemability configuration `F`, `lineage` must be injective on
  `image(resolve,F)`, and that image must map to an allowed source authority
  configuration after durable commitments are retained.  The expected exact
  theorem says this structural condition is equivalent to preserving **every**
  finite nonnegative additive bounded-authority policy.  A collision yields a
  capacity-one double-redemption witness; a forbidden image yields a separating
  nonnegative weight vector.

  The source family is finite and downward closed.  Source authority is
  normalized into unit atoms, and target cell rights inherit their weights
  through `lineage`; graded atom splitting is outside this iff.  The trusted
  configuration family must be complete for actual Prepare co-redeemability:
  whenever isolated cell executions can product-compose, some row contains
  them together.

  Prepare atomically moves one conditional authority atom into a globally
  charged fresh commitment and takes the lifecycle derivative that removes or
  fences futures incompatible with that commitment.  Typed history operators
  preserve the quotient-morphism condition through arbitrary checked traces.

  For the detached/product-independent profile, the configuration family has
  an all-domains row and the full invariant reduces to the established scalar
  potential

  ```text
  Phi = weight of all durable commitments + sum of allocated unspent rights.
  ```

  This corollary is not claimed as new.
- Strongest competing explanation: all useful safety follows directly from a
  fixed centralized ratifier or generic escrow, so the agent operators add no
  theorem beyond choosing a known mechanism.
- Result that would contradict the expectation: a map satisfying the stated
  configuration and local-injectivity conditions fails some additive policy;
  a map violating either condition nevertheless preserves every additive
  policy; a checked operator creates more weighted fresh commitments than the
  grant permits; shared aliases require one authority atom each; or a cloned
  rollback-local cell preserves isolated availability and bounded use without
  shared state, prior allocation, fencing, or loss of availability.

## Published Precedent And Real Assets

- Closest published protocol: consumable credentials/online ratification for
  shared aliases; invariant confluence and bounded-counter escrow for detached
  replicas; fencing and stable completion records for stale incarnations and
  retry; rollback-independent security state for VM restore.
- Official system/model/data/benchmark/tool and version: Lean 4.30.0 with the
  repository-pinned Mathlib; the existing deterministic controller and Codex
  App Server `0.146.0` adapter path; the already scoped self-hosted
  paper-formation trace only for workload/observability correspondence.
- What is reused: the existing lifecycle/transfer/Prepare/ticket semantics,
  durable SQLite controller, crash injection, semantic replay, and real
  client-owned dynamic-tool callback.
- Necessary deviations or custom glue: a small separate quota-cell model is
  permitted because the existing claim model hard-codes occurrence linearity.
  Runtime tests may add only adapter instrumentation and a reference model;
  they may not introduce a new experiment-control protocol or infer a domain
  from an untrusted string label.

## Comparison

- Proposed system or method: typed history operations over trusted
  handle-to-cell references, a configuration-preserving/local-injective
  cell-to-authority lineage map, epoch-fenced cells, globally stable authority
  commitments, and conditional or escrowed right transport.
- Main baselines and the competing position each represents:
  1. occurrence-linear admission represents the current conservative claim
     that every live representation must be unique;
  2. checkpoint-local clone represents independent availability with copied
     admission state;
  3. one shared atomic ratifier and pre-split escrow are cited mechanism
     baselines and positive controls, not claimed inventions.
- Why each main baseline needs a matched run instead of citation alone: only
  the first two need matched executions to expose the strict safe-alias and
  unsafe-clone differences on the same lifecycle histories.  Published
  ratification and escrow results are cited; their mechanisms are instantiated
  only to validate the operator mapping.
- Controls or ablations, labeled separately: domain-label equality without
  shared storage; two physical endpoints sharing one cell; trusted exclusive
  versus co-redeemable parallel children; stale epoch after Restore; view-only
  versus consolidating Merge; Merge that drops commitments; same operation key
  across the same or distinct cells; digest conflict; debit/commit/dispatch
  crash cuts; fresh controller commitment versus retry response and sink
  deduplication.
- Conclusion if each main baseline matches or wins: if occurrence linearity is
  equally permissive, the quotient generalization adds no value; if local clone
  remains safe under the stated availability schedule, the separation theorem
  is false; if only a fixed central service works, detached typed operations
  must be removed rather than relabeled.
- Information, tuning, and compute fairness: all policies see the same explicit
  lifecycle action, cell identity resolved by the trusted harness, current
  epoch, operation ID, digest, and crash schedule.  No policy sees the oracle's
  final label.
- Split or leakage rule when relevant: private trajectory contents remain
  local and aggregate; they select histories and test observability only, not
  theorem correctness or prevalence.

## Workloads And Metrics

- Real workloads or tasks: shared-gate aliases; trusted exclusive and live
  parallel Fork of independent cells; detached cloned controller; fenced
  escrow split; sequential restore after a prior commitment; view-only and
  consolidating merge after partial use; same-key retries; and crash cuts
  around Prepare.  At least one shared-gate path must traverse the installed
  Codex client-owned tool callback.
- Primary metrics: weighted number of fresh durable *authority commitments*
  per grant; violation of configuration-indexed capacity; structural checker
  decisions against independent counterexample construction; and preservation
  by every typed transition.  Scalar `Phi` is measured only in the detached
  profile.
- Correctness check or ground truth: Lean transition definitions and theorem
  statements are separate from safety; executable runs retain fresh commitment
  identity, stable operation keys, returned tickets, cell/epoch transitions,
  and external receipts separately.  Retry responses and sink outcome count
  cannot erase multiple commitments produced by distinct cells.
- Repetitions, seeds, and uncertainty: deterministic exhaustive finite
  witnesses for the operator matrix and every named crash cut; no stochastic
  estimate.  Existing trace counts retain their prior descriptive scope.
- Cost estimate when material: one fresh full Lean replay plus deterministic
  adapter tests; performance benchmarking is unnecessary unless the mechanism
  changes the dispatch path materially.

## Planned Runs

| Run group | Role | Workload | System/method | Repetitions | Decision consequence |
|---|---|---|---|---:|---|
| characterization | proposed | finite source/target configuration families | handle quotient and cell-lineage map | exhaustive theorem | proves or falsifies the exact universal-resource iff |
| proof | proposed | arbitrary finite checked histories | operational cell/right/commitment LTS | exhaustive theorem | proves or falsifies operator preservation |
| separation | lower-bound control | cloned or restored eligible local state | two isolated local monitors | exhaustive witness | tests necessity assumptions |
| aliases | strictness control | two live handles | shared cell vs occurrence-linear gate | all call orders | demonstrates added permissiveness |
| operators | proposed | Fork/Restore/Merge/Prepare/Retry/Settle | typed epoch/fence/escrow rules | all named cases | tests lifecycle refinement |
| crashes | ablation | Prepare persistence cuts | non-atomic orders vs atomic commitment | all named cuts | separates safe availability loss from dispatch-without-commitment |
| runtime | correspondence | client-owned Codex tool callback | existing SQLite controller plus domain metadata | deterministic | establishes a real mediation seam |

## Execution

- Authoritative command or workflow: repository `lake build`/kernel axiom audit
  for the formal result, followed by the existing adapter test runner and
  semantic replay command extended only with the named domain cases.
- Real preflight case: four cases through the same controller seam distinguish
  same-cell/different fresh keys, same-cell/same-key retry, cloned-cell/different
  keys, and cloned-cell/same key.  Capacity one permits one fresh commitment in
  the first two cases and exposes two distinct authority receipts in both
  cloned-cell negative controls, regardless of later sink deduplication.
- Full completion rule: the universal-resource iff and every named transition
  theorem elaborate without project axioms or `sorry`; operational
  balance/commit preservation does not assume `singlePerCell`; safe operators
  preserve the configuration-indexed invariant through arbitrary finite
  traces; unsafe clone/restore witnesses produce two distinct authority receipt
  IDs; every runtime case terminates and its commitment ledger independently
  recomputes the result.
- Raw-result path: this experiment directory plus `lean/results/` and the
  existing adapter result hierarchy.
- Checkpoint or recovery approach: retain every failed proof invocation and
  crash-case ledger; rerun affected cells after any semantic change.

## Interpretation

- Positive result: the cell-quotient/configuration-morphism characterization
  and lifecycle refinement are the main theory; operational commitment
  conservation and clone separation connect it to implementation; scalar
  escrow conservation and occurrence linearity are strict corollaries.
- Negative or contradictory result: preserve the counterexample, remove the
  false operator from the positive grammar, and narrow the claim to the
  largest actually proved lifecycle subset.
- Mixed or inconclusive result: separate proved safety from unproved concrete
  refinement; do not call endpoint names or trace metadata a semantic domain.
- Target paper figure or table: one diagram showing handles branching above a
  shared or split redemption topology, plus one theorem/semantic-matrix table;
  no broad throughput graph.

## Reproducibility Notes

- Software and data versions: inherit the pinned versions and hashes already
  recorded by Step 0007; record any new source hash and command.
- Config and seed notes: deterministic; no seeds.
- Known deviations: the core model charges a fresh authority commitment even
  if external dispatch never occurs.  A ticket is a view of that same
  commitment.  The theorem proves at-most authorization commitment, not
  physical exactly-once execution.  An abort/reclaim protocol is outside the
  core unless it supplies authenticated non-dispatch evidence.  The installed
  Codex callback is a real mediation seam, not product-wide native lifecycle
  refinement.
