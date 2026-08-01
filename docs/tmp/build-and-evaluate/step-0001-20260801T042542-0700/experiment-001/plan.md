# Experiment Plan: RQ3 Mechanized Lifecycle Core

## Research Question

- RQ exactly as written in the paper: **RQ3: Does the abstract invariant refine a real agent lifecycle?** Which facts must a concrete runtime expose so checkpoint, exclusive/parallel fork, selection, abort, replace/live restore, merge, revocation, uncertain dispatch, and settlement preserve authority continuity?
- Specific uncertainty tested here: Whether the paper's closed authority-changing transition core can be stated and proved in Lean 4 without `sorry`, project axioms, or a derived-case preservation premise that simply assumes the conclusion.
- Why the answer matters: The current paper relies on auditable paper proofs and bounded Python checks. A kernel-checked development would directly test the strongest outstanding correctness objection and expose any circular or underspecified rule before runtime integration.

## Paper-Value Admission

- Planned role: supporting evidence toward RQ3. A real dispatch-owning adapter remains necessary to answer the concrete-runtime part of RQ3.
- Largest credible paper story this experiment could unlock: Authority continuity is not only a paper model; its abstract lifecycle preservation and conditional trace-refinement core is replayed by the Lean kernel from explicit lifecycle premises.
- Strongest reviewer reject argument or load-bearing uncertainty addressed: The current closed LTS and two iff theorems may still hide a prose well-formedness premise, circular certificate assumption, or unhandled transition case.
- Independent evidence added beyond existing runs and published results: The Python artifact enumerates small instances but cannot prove universally quantified lifecycle preservation or validate that the paper proof terms type-check. Lean checks symbolic theorems over arbitrary finite inputs and the inductive trace relation.
- Why the result is not tautological, already settled, or dominated: Encoding only the definitions would be dependency work. Admission requires derived proofs for simulation topology changes, exact Prepare/cleanup, restriction/revocation, ticket history, and trace induction, plus executable admission-checker soundness for checked-target cases. The strongest alternative is a real adapter litmus, but that would leave the paper's primary theory claim at paper-proof level.
- Paper decision if positive: Report a mechanized core with exact scope, theorem inventory, proof size, zero project axioms, and one clean build command; strengthen RQ3 evidence without enlarging the scientific claim.
- Paper decision if contradictory, mixed, or inconclusive: Preserve the failed obligations as raw evidence, repair an underspecified rule if the scientific contract is unchanged, and keep the paper at paper-proof scope if the full admitted theorem matrix does not build.
- Best alternative experiment and why this one has higher decision value: A dispatch-owning Codex/Claude proxy would improve agent grounding, but optional product hooks cannot establish the theorem and building a complete proxy before the kernel stabilizes risks implementing a flawed contract.

## Expected And Alternative Outcomes

- Current expected answer: Lifecycle preservation should require explicit claim partition, epoch monotonicity, support, binding, and rule-local solvency premises but no additional target-WF/AC assumption for derived cases.
- Strongest competing explanation: The iff results are definition expansions and the LTS preservation theorem succeeds only because a certificate premise already contains target authority continuity.
- Result that would contradict the expectation: Any paper-facing theorem needs `sorry`, a project axiom, an undeclared foundational axiom, or an `AC target`/`WF target` premise in a derived transition case; or one paper transition lacks enough premises to prove partition/AC preservation.

## Published Precedent And Real Assets

- Closest published protocol: CSF theory papers commonly pair paper semantics with Lean/Rocq/Isabelle developments; this experiment follows the standard kernel-checked theorem-development protocol rather than treating tests as proofs.
- Official system/model/data/benchmark/tool and version: Official Lean 4 release `v4.30.0`, pinned by `lean-toolchain` and built with Lake.
- What is reused: Lean's official kernel, the version-matched Mathlib finite-set library, Lake build graph, and `#print axioms`/`leanchecker` audit path.
- Necessary deviations or custom glue: Project-specific definitions and proofs only. No custom proof checker, result schema, or generated theorem oracle.

## Comparison

- Proposed system or method: A Lean development of typed capacity/claims, finite durability contracts, exact promotion cleanup as required by Prepare, the certificate-checked transition kernel, and trace preservation. Boundary I and Boundary II are explicitly outside this RQ3 experiment's success condition.
- Main baselines and the competing position each represents: No matched runtime baseline is scientifically meaningful for proof checking. The existing paper proof and Python bounded explorer are prior evidence, not baselines; their limitations motivate the mechanization.
- Why each main baseline needs a matched run instead of citation alone: Not applicable.
- Controls or ablations, labeled separately: clean `lake build`; repository scan for `sorry`/`admit`/project `axiom`; `#print axioms` for every paper-facing theorem; `leanchecker` replay of the root `.olean`; one deliberately weakened premise retained only as a non-building mutation log if it exposes a real dependency.
- Conclusion if each main baseline matches or wins: If only bounded enumeration succeeds while a symbolic theorem fails, the paper must retain bounded-validation language and report the missing proof as unresolved internally.
- Information, tuning, and compute fairness: The theorem statements are frozen before proof attempts and remain aligned with the paper; they will not be weakened to make Lean accept them.
- Split or leakage rule when relevant: Not applicable.

## Workloads And Metrics

- Real workloads or tasks: The exact paper theorem statements and lifecycle rules, not synthetic benchmark propositions.
- Primary metrics: Number of frozen paper-facing theorem statements that build; whether every derived lifecycle case and trace induction are kernel checked; project axioms or `sorry` count (target zero).
- Correctness check or ground truth: Lean elaboration and kernel checking, plus manual statement-to-paper alignment reviewed against `model.tex`, `semantics.tex`, and `results.tex`.
- Repetitions, seeds, and uncertainty: Deterministic; one clean rebuild after deleting build outputs and a second independent statement audit.
- Cost estimate when material: One Lean toolchain download and a bounded proof-development pass; no paid service or external effect.

## Planned Runs

| Run group | Role | Workload | System/method | Repetitions | Decision consequence |
|---|---|---|---|---:|---|
| admission | proposed | finite AC checker for Reserve/direct Merge | Lean 4 executable checker plus soundness proof | 1 clean build | Validates checked-target wiring without pretending target AC is derived |
| lifecycle | proposed | partition, epoch/ticket, Prepare, one-step and trace preservation | Lean 4 inductive semantics | 1 clean build | Determines whether RQ3 receives mechanized abstract-preservation evidence |
| audit | control | all paper-facing theorems | axiom/sorry scan and kernel replay | 1 | Vetoes a positive result if undeclared trust remains |

## Execution

- Authoritative command or workflow: `cd lean && lake clean && lake exe cache get && lake build AuthorityContinuity && ./scripts/audit.sh`. The official Mathlib cache restores pinned dependency artifacts after cleaning the project; the audit invokes `lake env leanchecker --fresh AuthorityContinuity.Main` and ordinary text scans only.
- Real preflight case: Pin Lean `v4.30.0`, build one theorem imported through the final Lake package, and print its axioms.
- Full completion rule: The root module `AuthorityContinuity.Main` imports every theorem module; every frozen paper-facing constant below builds from a clean checkout and passes the axiom audit; the checked-in README lists exact scope and non-mechanized assumptions.
- Raw-result path: `lean/results/build.log`, `lean/results/axioms.log`, and the current experiment result review.
- Checkpoint or recovery approach: Lake's normal incremental build during development; the reported result comes only from a final clean build.

## Interpretation

- Positive result: All admitted theorem groups build without project axioms or sorry; the paper may call this abstract lifecycle-preservation core Lean-mechanized while retaining honest boundaries around the concrete adapter and Boundary I/II paper proofs.
- Negative or contradictory result: A failed obligation identifies either a missing LTS premise or an overstrong theorem. Repair only if the existing claim and RQ remain unchanged; otherwise do not rewrite the story without user approval.
- Mixed or inconclusive result: Partial modules remain internal dependency evidence and do not enter the paper as mechanization.
- Target paper figure or table: A compact artifact table listing mechanized definitions/theorems, Lean/LOC/build time, and remaining trusted/runtime assumptions.

## Reproducibility Notes

- Software and data versions: Lean `v4.30.0`; exact Lake and compiler versions captured in the build log.
- Config and seed notes: Deterministic, no seeds.
- Known deviations: This experiment proves the abstract formal kernel and a conditional trace theorem, not a refinement of current Claude/Codex deployments, complete mediation, correctness of natural-language effect binding, Boundary I, or Boundary II.

## Frozen Theorem Matrix

The root module is `AuthorityContinuity.Main`; it imports the modules containing every constant below. Names and logical scope are fixed before proof development.

| Lean constant | Paper correspondence | Quantifiers and assumptions | Required conclusion |
|---|---|---|---|
| `checkAC_sound` | Definition 2 and checked Reserve/direct-admission Merge | every finite state `A`; `checkAC A = true` | `AC A` |
| `guardClosure_iff` | Lemma `thm:guard-closure`, restricted to the Prepare dependency | every source contract, promotion batch, and configuration | membership in the installed exact guard iff old membership and promoted load is within `G` |
| `simulation_preserves_ac` | Equation `eq:simulation`; topology case of `thm:preservation` | source/target states and projection; source `AC`; target configurations project to source configurations with no larger load | target `AC`, with no target-AC premise |
| `restriction_preserves_wf_ac` | Select/Abort/Revoke cases of `thm:preservation` | source state and retained configuration/claim sets; source `WF` and `AC`; explicit subset/load-decrease premises | target `WF` and `AC`, with no target-WF/AC premise |
| `prepare_preserves_wf_ac` | Prepare/cleanup case of `thm:preservation` | source state and unique promotion batch; source `WF` and `AC`; open/bound claims; exact guard/cleanup construction | target `WF` and `AC`, with no target-WF/AC premise |
| `ticket_step_preserves_wf_ac` | Dispatch/Retry/Crash/Settle cases of `thm:preservation` | source and ticket-only successor; source `WF` and `AC`; stable-ID phase rule | successor `WF` and `AC`, and the operation-to-claim binding is unchanged |
| `step_preserves_wf_ac` | Theorem `thm:preservation` | every inductively generated abstract `Step A η A'`; source `WF` and `AC` | target `WF` and `AC`; checked-target constructors use `checkAC A' = true` for the quantitative AC obligation and constructor-local structural evidence for WF, never target `WF A'`/`AC A'` premises; every other case calls a derived theorem above |
| `trace_preserves_wf_ac` | induction used by Corollary `thm:trace` | every reflexive-transitive abstract trace from `A` to `A'`; source `WF` and `AC` | target `WF` and `AC` |
| `effect_coverage` | Lemma `lem:coverage` | every finite stable-ID attempt map with injective claim bindings and per-operation aggregate actual demand bounded by its durable claim | aggregate actual demand is bounded by durable demand |
| `concrete_trace_authority_safety` | Corollary `thm:trace` | abstract trace preservation, complete-mediation/simulation hypotheses, effect coverage, and a currently permitted configuration | actual durable demand plus its conditional demand is bounded by `G`; hypotheses remain explicit |

`Chk` is instantiated for the finite model by executable `checkAC`; `checkAC_sound` is mandatory. Other certificate languages remain logical premises and are not reported as a mechanized general proof-object checker.

The audit fails on `sorryAx`, `admit`, omitted matrix constants, or any project-declared `axiom`. Permitted Lean foundations are reported, not hidden: `propext`, `Quot.sound`, and `Classical.choice` are allowed when introduced by finite-set extensionality or Mathlib; every other axiom requires plan deviation and result-review approval.
