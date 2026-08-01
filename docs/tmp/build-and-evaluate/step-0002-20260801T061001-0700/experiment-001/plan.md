# Experiment Plan: RQ3 Canonical Topology Closure

## Research Question

- RQ exactly as written in the paper: **RQ3: Does the abstract invariant refine a real agent lifecycle?** Which facts must a concrete runtime expose so checkpoint, exclusive/parallel fork, selection, abort, replace/live restore, merge, revocation, uncertain dispatch, and settlement preserve authority continuity?
- Specific uncertainty tested here: whether choice/parallel Fork, replace/live Restore, and explicit Merge targets can be computed from finite operation data, then have structural well-formedness and authority continuity derived by a sound executable checker rather than supplied as fields of a logical target certificate.
- Why the answer matters: the previous Lean run received a mixed verdict precisely because `TopologyShape` packages most target well-formedness facts. Until this interface closes, the paper cannot honestly claim a mechanized lifecycle theorem.

## Paper-Value Admission

- Planned role: decisive evidence for the abstract-topology half of RQ3.
- Largest credible paper story this experiment could unlock: a kernel-checked, closed lifecycle in which history-transforming operations build their targets, transport conditional authority through a monotone zero-preserving projection, conserve split claim fibers, and preserve authority continuity without assuming target invariants.
- Strongest reviewer reject argument or load-bearing uncertainty addressed: the preservation theorem holds only because arbitrary target `A'` and fieldwise target-WF facts are smuggled into `TopologyShape`.
- Independent evidence added beyond existing runs and published results: the run replaces that logical interface with deterministic target builders and Boolean certificate checks, including fresh fragment issuance and the four canonical Fork/Restore shapes absent from the first mechanization.
- Why the result is not tautological, already settled, or dominated: success requires source-to-target history, epoch, transfer, projection, and load obligations to be checked over concrete finite data and assembled into `LWF`/`AC`. For the four canonical operations, even an atomized re-enumeration of all target-WF fields fails admission: their structure and load simulation must be derived from the exact builder, source invariants, and checked transfer conservation. Only arbitrary Merge may enumerate target structure.
- Paper decision if positive: update the paper after independent result review to report the exact canonical topology/checker scope and retain explicit limits around Boundary I/II and a concrete adapter.
- Paper decision if contradictory, mixed, or inconclusive: keep the run internal, record the smallest failed obligation, and do not broaden the paper's mechanization claim.
- Best alternative experiment and why this one has higher decision value: a dispatch-owning Codex/Claude adapter is the next RQ4 experiment, but it cannot repair the current circular-looking abstract preservation interface. Boundary I/II mechanization would strengthen headline mathematics while leaving the claimed lifecycle theorem open.

## Expected And Alternative Outcomes

- Current expected answer: finite canonical topology construction plus a source-local transfer checker is sufficient; canonical target core/lifecycle WF and load simulation follow from the builder and source invariants, while arbitrary Merge needs a separate finite structure checker. Target AC then follows from source AC and derived or checked simulation, except in explicitly named direct-admission Merge.
- Strongest competing explanation: checking enough facts to handle arbitrary fragments and guarded configurations degenerates into directly checking the whole target invariant, so the claimed proof-object architecture has no meaningful separation from a global target solver.
- Result that would contradict the expectation: any canonical theorem needs an arbitrary target state, a target `WF`/`LWF`/`AC` premise, a checker that simply decides `WF` or `AC` wholesale, a project axiom/placeholder, or transfer semantics that cannot represent fresh fragments without reviving terminal IDs.

## Published Precedent And Real Assets

- Closest published protocol: CSF theory artifacts commonly kernel-check a finite semantic core and use small executable decision procedures for finite proof obligations. The novelty is the history-transforming authority specialization, not finite enumeration or event-structure projection itself.
- Official system/model/data/benchmark/tool and version: pinned Lean 4 `v4.30.0`, Lake 5.0.0, and Mathlib `v4.30.0`.
- What is reused: the existing `AuthorityContinuity` finite carriers, AC checker, lifecycle/ticket proofs, audit script, and deterministic Python artifact.
- Necessary deviations or custom glue: one new topology module, operation-specific target builders, atomized finite Boolean checks and soundness proofs, operation-specific theorem wrappers, and an audit module with positive and rejecting witnesses.

## Comparison

- Proposed system or method: computed choice/parallel Fork and replace/live Restore descriptors; explicit Merge descriptors; a claim transfer map with exact target domain, fresh-or-retained provenance, no retained-plus-fragment mixture, typed grant agreement, and componentwise fiber conservation. Canonical `Mono_0(pi)`, lifecycle shape, structural WF, and configuration simulation are derived. Arbitrary simulation Merge separately checks structural atoms, `Mono_0(pi)`, and simulation; direct-admission Merge uses the same structure checker plus `checkAC target` and has no projection premise.
- Main baselines and the competing position each represents: (A) current `TopologyShape`, representing fieldwise logical target certification; (B) direct `checkAC target`, representing global re-admission without simulation; (C) restriction-only topology, representing a safe but expressively incomplete lifecycle.
- Why each main baseline needs a matched run instead of citation alone: all three are repository interfaces. The audit compares theorem signatures and executable witnesses against the new interface; no performance claim is made.
- Controls or ablations, labeled separately: reject a copied full-demand fragment fiber; reject reuse of a terminal fragment ID; reject reopening a closed branch epoch; reject parallel co-durability that exceeds source load; accept a valid choice fork, valid parallel split, replace restore, live restore, simulation merge, and direct-admission merge.
- Conclusion if each main baseline matches or wins: if canonical operations still require `TopologyShape`-equivalent Prop fields, or only direct target AC checking works, the experiment is mixed and the paper retains no mechanization claim.
- Information, tuning, and compute fairness: all theorem names and forbidden premises below are frozen before implementation; failures are not repaired by weakening the target statement.
- Split or leakage rule when relevant: not applicable.

## Workloads And Metrics

- Real workloads or tasks: the paper's four canonical topology forms, explicit simulation/direct Merge, retained claims, fresh fragments, cancellation, guarded configuration preimages, and monotone branch epochs.
- Primary metrics: all frozen constants build; zero `sorry`/`admit`/project axioms; no forbidden theorem premises; all positive/rejecting audit examples evaluate as specified; clean build and fresh kernel replay succeed.
- Correctness check or ground truth: Lean elaboration/kernel checking, `#print axioms`, signature audit, and independent statement-to-paper review.
- Repetitions, seeds, and uncertainty: deterministic; one real preflight, one final clean build, one fresh kernel replay, and one independent result review.
- Cost estimate when material: local CPU only; expected proof development dominates build time.

## Planned Runs

| Run group | Role | Workload | System/method | Repetitions | Decision consequence |
|---|---|---|---|---:|---|
| canonical | proposed | choice/parallel Fork; replace/live Restore | exact deterministic builder + source-local transfer checker | 1 clean build | Must derive exact shape, target `LWF`, active-branch exactness, simulation, and `AC` for all four forms |
| merge-sim | proposed | explicit simulation Merge | finite structure + projection + simulation checkers | 1 clean build | Must preserve `LWF`/`AC` without target-AC checking |
| merge-direct | proposed | explicit direct-admission Merge | same structure checker + `checkAC target` | 1 clean build | Must remain visibly distinct from simulation mode |
| transfer | control/ablation | retained IDs, fresh fragments, copying, terminal reuse | executable transfer checks | 1 | Must accept conservation and reject duplication/resurrection |
| lifecycle | control | restriction freshness, epochs, tickets/history | existing proofs plus restriction repair | 1 | Prevents safe-but-dead lifecycle regression |
| audit | control | all frozen constants and witnesses | source scan, `#print axioms`, `leanchecker` | 1 | Vetoes positive interpretation on hidden trust |

## Execution

- Authoritative command or workflow: `cd lean && lake clean && lake exe cache get && /usr/bin/time -v lake build AuthorityContinuity && ./scripts/audit.sh`; the audit performs `lake env leanchecker --fresh AuthorityContinuity.Main`.
- Real preflight case: compile a minimal fresh-fragment split through the final canonical builder, transfer checker, fiber-load theorem, and preservation theorem; show the path has no project axioms.
- Full completion rule: `AuthorityContinuity.Main` imports the new topology and audit modules; every frozen constant and executable witness below passes from a clean tree; a source/signature audit confirms no arbitrary target or target-invariant premise in canonical theorems. The old `Step.topology`/`Step.directMerge` entry points are removed from the authoritative transition relation, and the final trace theorem ranges over the full lifecycle including all prior non-topology rules.
- Raw-result path: `lean/results/topology-preflight.log`, `lean/results/topology-build.log`, `lean/results/topology-axioms.log`, and this experiment's result review.
- Checkpoint or recovery approach: Lake incremental builds during proof development; only the final clean build is reported.

## Interpretation

- Positive result: all canonical operations compute exact, non-degenerate targets and preserve lifecycle invariants from source invariants plus `checkTransfer = true`; the two Merge modes use distinct checked descriptors; the single authoritative full-lifecycle `Step` and trace theorem use no old fieldwise topology entry; transfer and epoch mutations reject the frozen negative cases; audits pass.
- Negative or contradictory result: an operation is unrepresentable, a source-safe accepted certificate produces an unsafe target, or a theorem needs a forbidden premise/axiom.
- Mixed or inconclusive result: only some canonical forms or identity-only transfer build, or structural safety is obtained only by whole-target invariant checking. Such results remain internal.
- Target paper figure or table: one compact table mapping each lifecycle operation to its deterministic update, checked finite premises, preservation theorem, and remaining runtime assumptions.

## Reproducibility Notes

- Software and data versions: Lean `v4.30.0`; Lake 5.0.0; Mathlib tag `v4.30.0`; exact revisions recorded in logs.
- Config and seed notes: deterministic, no seeds.
- Known deviations: this experiment does not mechanize Boundary I/II, prove natural-language binding correctness, or instantiate complete mediation and aggregate sink outcomes in Claude/Codex.

## Frozen Canonical Semantics

For source support \(B=\bigcup\front(T)\), the builder computes the following exact target family, not an arbitrary safe restriction. The projection collapses the listed descendant set to the source parent and otherwise preserves context branches.

- choice Fork replaces supported open `b` by two distinct fresh epochs `b0,b1`; target configurations are exactly active target subsets whose projection is source-allowed and which do not contain both children;
- parallel Fork has the same replacement, but permits both children whenever the projected source configuration containing `b` is allowed;
- replace Restore closes `b`, opens fresh `b'`, and exactly alpha-replaces `b` by `b'` in every pulled-back guarded configuration;
- live Restore keeps `b`, opens fresh `b'`, and permits either or both descendants exactly when the collapsed source configuration is allowed.

Unrelated context branches and all guarded source configurations are preserved by preimage under the canonical projection. The mechanized topology invariant additionally states that open branch epochs equal the extensional support of the allowed family; canonical theorems take this exactness for the source and derive it for the target.

The checked finite fragment model is deliberately precise about its scope. `rho` maps exactly the target tentative IDs to source tentative IDs. A fiber contains either retained source ID `c`, or only target IDs that were `unissued` in the source, never both. Unretained old tentative IDs become terminal; durable and terminal claim history is definitionally unchanged; every target member has the same `grantOf` as its source; and every coordinate's fiber sum is at most source demand. These are **preallocated-unissued finite fragments**. Compatible refined effect binding and issuer approval are not represented by the current Lean state and remain explicit non-mechanized paper premises.

## Frozen Interface And Theorem Matrix

The new root-facing module is `AuthorityContinuity.Topology`. Plain names are preferred over new branded terminology.

| Lean constant | Required scope | Forbidden shortcut |
|---|---|---|
| `restrictLifecycle_epoch_exact` | retained epochs are unchanged; excluded open epochs close; excluded closed epochs stay closed; excluded unissued epochs remain unissued | closing every excluded identity |
| `canonicalProjection_zero` | every canonical Fork/Restore projection maps `∅` to `∅` | checker premise |
| `canonicalProjection_mono` | every canonical projection is monotone | checker premise |
| `checkTransfer_sound` | `checkTransfer A d = true` yields exact domain, retained-or-fresh provenance, no retained/fragment mixture, grant agreement, and coordinatewise fiber conservation | Prop certificate supplied by caller |
| `topology_fiber_conservation` | checked transfer and canonical owner/projection relation imply target conditional load is no larger than projected source conditional load; all four canonical preservation proofs use this theorem | an independent per-configuration simulation recheck |
| `choiceFork_allowed_iff` | exact choice membership: pulled-back source membership plus child exclusivity and active target support | arbitrary safe restriction |
| `parallelFork_allowed_iff` | exact parallel membership, including the jointly present child case | arbitrary safe restriction |
| `replaceRestore_allowed_iff` | exact contextual replacement membership | arbitrary safe restriction |
| `liveRestore_allowed_iff` | exact contextual live membership, including old/new co-presence | arbitrary safe restriction |
| `choiceFork_preserves_wf_ac` | computed choice target preserves `LWF`/`AC` | arbitrary `A'` or target invariant premise |
| `parallelFork_preserves_wf_ac` | computed parallel target preserves `LWF`/`AC` | arbitrary `A'` or target invariant premise |
| `replaceRestore_preserves_wf_ac` | computed replacing-restore target preserves `LWF`/`AC` | arbitrary `A'` or target invariant premise |
| `liveRestore_preserves_wf_ac` | computed live-restore target preserves `LWF`/`AC` | arbitrary `A'` or target invariant premise |
| `checkMergeStructure_sound` | atomized finite Merge checks yield core structural, history, transfer, active-branch, and epoch obligations | deciding `LWF target` wholesale |
| `simulation_merge_preserves_wf_ac` | explicit simulation descriptor plus structure/`Mono_0`/simulation checks preserves `LWF`/`AC` without target-AC checking | `checkAC target` or fieldwise Prop certificate |
| `direct_merge_preserves_wf_ac` | explicit direct descriptor plus the same structure checker and `checkAC target` preserves `LWF`/`AC`, with no projection premise | conflating the two Merge modes |
| `step_preserves_wf_ac` | the single authoritative full-lifecycle `Step`, covering all old non-topology rules, the four canonical operations, and the two checked Merge modes, preserves `LWF`/`AC` and active-branch exactness | old `TopologyShape` topology constructor or a topology-only replacement relation |
| `trace_preserves_wf_ac` | the authoritative full lifecycle trace preserves the same invariants | topology-only trace or target invariant premise |

The canonical checker may check only operation freshness/distinctness and the source-local transfer conditions above; it may not enumerate the canonical target contract to recheck empty/downward/support/open/active-exact facts or per-configuration simulation. Those facts are the builder proofs. Arbitrary Merge uses separately named Boolean atoms for empty configuration, downward closure, support, open configuration/owner/grant epochs, active-branch exactness, branch-epoch/history monotonicity, and transfer validity. Simulation Merge additionally checks `Mono_0` and per-configuration simulation. Direct Merge alone may call the existing sound `checkAC`.

The audit additionally freezes positive witnesses for valid choice, parallel split, replace, live restore, fresh fragmentation, simulation Merge, and direct Merge. It freezes rejections for full-demand copying, retained-plus-fragment mixing, terminal-ID reuse, `rho` targeting a non-tentative source, closed-epoch reopening, unsafe co-durable parallelization, an unsafe direct target, and choice-child co-presence. A separating witness must also show a safe direct-admission Merge for which the proposed simulation certificate fails. Definition audits confirm that topology targets cannot mutate durable claim status, tickets, or receipts and that replace cannot keep the old epoch open.
