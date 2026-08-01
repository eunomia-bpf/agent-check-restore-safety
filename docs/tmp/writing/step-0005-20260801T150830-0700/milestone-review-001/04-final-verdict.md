# Final milestone acceptance verdict

## Node metadata

- **Timestamp:** 2026-08-01T15:33:12-07:00
- **Parent:** `step-0005-20260801T150830-0700/milestone-review-001`
- **Objective:** Decide whether the current project is ready to pass the CSF 2027 milestone, after a blind paper attack, primary-source novelty attack, source-grounded reread, and post-judgment audit of author intent and actual artifacts.
- **Classification and bar:** Security theory / programming languages with a supporting runtime instantiation. I apply the CSF theory/security bar, not an AI benchmark or general systems-throughput bar.
- **Final verdict:** **MILESTONE NOT ACCEPTED — reject / major revision.** The project has a strong organizing principle, a coherent closed semantics, and unusually honest artifact boundaries. It is not yet submission-ready because the theorem-level novelty remaining after established configuration/resource semantics are removed has not been demonstrated strongly enough.

## Review-chain disclosure and linked evidence

This verdict follows the required serial, initially unprimed process:

1. [Blind full-paper read and attack map](./01-blind-read.md) — fixed before any author framing, prior reports, code, or external search.
2. [External primary-source novelty and reality attack](./02-external-search.md) — fixed before rereading or opening author/cycle state.
3. [Source-grounded full-paper reread](./03-full-reread.md) — fixed before inspecting `docs/idea-story.md`, `docs/evaluation.md`, prior step reports, code, or experiment outputs.

Only after those three reports were frozen did I inspect the idea/hypothesis history, evaluation contract, prior gate reports/reviews, Lean development and logs, bounded Python artifact, Codex adapter, retained JSON/SQLite/JSONL evidence, and current canonical project documents. I did not read any of that material while forming the paper-only attack. I made no change to the paper, canonical documents, code, artifacts, or version-control state, and issued no Git command. The only files created are the four reports in this directory.

## Decisive acceptance judgment

The paper's simple principle is good: **authority follows durable support, not copied state**. Official runtime documentation and current security preprints validate the challenged belief that checkpoint/fork histories and irreversible external effects occupy different rollback domains ([Claude checkpointing](https://code.claude.com/docs/en/checkpointing), [Codex app-server protocol](https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md), [ACRFence](https://arxiv.org/html/2603.20625v1), [Ghost Tool Calls](https://arxiv.org/html/2606.02483v1)). The project is therefore not solving an invented problem.

The acceptance blocker is narrower: the paper has not established that its remaining lifecycle-specific formal advance is large enough for CSF once known foundations are credited. Configuration structures already treat arbitrary permitted families and explicitly model the “all pairs, not the triple” pattern as ternary conflict/propositional theory ([van Glabbeek and Plotkin](https://arxiv.org/abs/0912.4023)). Resource-sensitive event semantics already combine configurations and resource consumption ([Resource-Tracking Concurrent Games](https://link.springer.com/chapter/10.1007/978-3-030-17127-8_2)); consumable credentials already model globally consumed use-limited authorization ([Consumable Credentials](https://www.ndss-symposium.org/wp-content/uploads/2017/09/Consumable-Credentials-in-Linear-Logic-Based-Access-Control-Systems.pdf)); supervisory control and guarded transaction processes already supply maximally permissive guarded restrictions. The manuscript honestly disclaims most of these ingredients, but it neither cites the closest configuration/resource formulation nor gives a theorem-level translation and separation.

After that subtraction, Boundary I is a useful but elementary greatest-corner characterization for one deliberately restricted Cartesian-product checker class. Boundary II—the final-owner-support iff result under exact prefix repair and immediate cleanup—is the strongest plausible novelty. It survived the targeted primary-source attack, but it is narrowly scoped, not mechanized, and not positioned as a formal delta from configuration structures and guarded/supervisory semantics. That is the one **CSF-theory blocker**.

The incomplete real-runtime refinement is **not automatically a theory-paper blocker**. The abstract and validation clearly disclaim complete mediation and product-wide refinement. If the paper remains theory-led and treats the Codex adapter as illustrative correspondence, full production mediation is a major optional strengthening. It becomes a blocker only if the submission continues to use the adapter as evidence that the conditional concrete trace theorem holds for Codex or another deployed runtime.

## Actual-cycle and user-intent audit

### What the cycle did well

The actual project trajectory is materially better than a paper-only read reveals:

- It repeatedly retired false or classical headline claims rather than hiding them. The idea history records the escrow counterexample, the classical monus/cograph boundary, invalid escape preservation, over-approximated frontier issue, revoke/ticket gap, and failed first topology mechanization.
- It followed the user's theory-first preference. The current evaluation contract allocates primary weight to definitions, proofs, Lean, and exhaustive counterexamples; it explicitly rejects prompt benchmarking as theorem evidence.
- It closed a real earlier proof gap. The final Lean relation has one authoritative `Step`, computed canonical fork/restore targets, separately checked simulation/direct merge, transfer-fiber conservation, ticket binding, trace closure, and only documented foundational dependencies. The retained 755-job build and kernel/axiom logs are internally consistent.
- It maintained experiment integrity. The first adapter pilot was preserved and rejected for erased aliases, an oracle-only label, and an uncertified merge; revision 2 repaired the evidence without changing the oracle. Retained hashes match the cycle report.
- Independent read-only verification in this review passed all 24 bounded-model tests and all 33 adapter tests, including the live Codex app-server preflight. The compact retained report contains 89/89 P3 decisions, 20/20 replays, 44/44 callback matches, 33/33 distinct-process recoveries, no unmediated/duplicate outcome in the fixed suite, and the stated baseline false-accept/reject counts.

These are real strengths. They support internal correctness and honest scope; they do not answer the closest-theory novelty question.

### Where the cycle fell short of the user's intent

The user asked for a high-ambition, novel, theory-heavy CSF paper with a simple principle and practical/industrial consequence. The cycle delivered ambition, a simple principle, and substantial formal/artifact work. It has not yet delivered the two hardest parts of that intent:

1. **Novelty at the required altitude.** The project's own falsifier says to demote the lead claim if it is a direct renaming of event structures/linear logic with no lifecycle-specific theorem. The newly opened configuration-structure source makes that falsifier live. The current paper's higher-order support example is known semantic substrate, not evidence of a new policy-language phenomenon.
2. **Demonstrated practical consequence.** The project shows that its controller admits fixed-suite histories rejected by split-all or parent escrow, but does not establish an important workload that needs an enforceable pre-selection guarantee. A conservative design such as Agent libOS capability attenuation/one-shot reserve-consume, parent escrow, first-commit-wins, or effect staging may simply trade away availability ([Agent libOS](https://arxiv.org/html/2606.03895v2), [Cordon](https://arxiv.org/html/2606.17573v1)). The paper has not measured why recovering that availability matters.

The cycle also missed its own minimum mechanization target: `docs/evaluation.md` names residual exactness, guarded promotion, and final-owner-support serializability, while the Lean README and paper explicitly exclude Boundaries I--II. That scope statement is honest, but it means the mechanized artifact does not cover the two results advertised as the paper's exact boundaries.

## Ranked final findings and routing

### Blocker — required for a CSF theory submission

1. **Theorem-level novelty separation is unresolved.**
   - **Failed inference:** a new security interpretation plus a closed lifecycle LTS does not by itself show that the residual/guard/order results are a substantial formal advance over configuration structures, resource-sensitive event semantics, consumable credentials, and supervisor-generated guards.
   - **Required evidence:** add the missing closest sources; give an explicit encoding/translation table; identify a separating lifecycle trace/property or theorem not inherited from the classical models; and show why Boundary II is not a direct special case of known configuration filtering plus enabledness/cleanup.
   - **Route:** first **`research-literature-novelty` / idea gate**, then **EXPERIMENT_GATE** for a mechanized encoding or counterexample. Do not enter final prose polishing until this resolves. If the theorem delta collapses, reframe as a security-systems application and strengthen enforcement evidence rather than invent a new term.

### Major — required to make the theory package credible

2. **The headline boundaries are outside Lean.** Mechanize Boundary I, exact guarded promotion, and especially Boundary II over the stated assumptions; publish a theorem-to-paper coverage matrix and fuller proof material. Route: **EXPERIMENT_GATE**, then **WRITE_GATE**.

3. **Paper RQs and evidence roles are implicit.** The repository has a clear RQ contract, but the manuscript does not. State the current RQs and separate paper proof, Lean coverage, bounded falsification, and runtime correspondence. Route: **WRITE_GATE after the novelty decision**.

4. **The availability/usefulness case is not established.** Compare against conservative attenuation/splitting, parent escrow, first-commit-wins, and staging on one end-to-end task requiring an advance branch-local guarantee. The critical metrics are unsafe effects and useful safe histories rejected/completed, not latency. Route: **EXPERIMENT_GATE**. This is the highest-value systems experiment if the paper retains a practical/industrial claim.

### Major only if concrete-runtime safety remains load-bearing

5. **Complete mediation and concrete refinement are untested outside one isolated client-owned sink.** A production-strength claim needs a mandatory protected boundary, explicit bypass inventory, topology activation crash windows, stable binding, and a concrete-to-abstract event map. Agent libOS, Cordon, and Commit-Time Authorization demonstrate a stronger current experimental bar ([Commit-Time Authorization](https://arxiv.org/html/2607.10487v1)). Route: **EXPERIMENT_GATE**. For a purely theory-led submission, instead preserve the current disclaimers and demote most adapter detail to the artifact/appendix; do not spend the next cycle on a broad runtime benchmark.

### Minor / writing

6. Reduce the concept surface: merge “conditional commitment” with “tentative claim”; present semantic future family → quantitative residual → durable guard representation as one pipeline; demote the known ternary-conflict proposition; retain “authority continuity” and the durable-support principle.

7. Keep every theorem qualifier adjacent to “exact runtime boundary.” Boundary I is fixed-topology and Reserve-only; Boundary II assumes a fixed valid batch, owner grouping, exact prefix repair, immediate cleanup, and no lifecycle interleave.

## RQ readiness and milestone state

| Paper question | Final readiness | Acceptance condition |
|---|---|---|
| Security state/invariant and lifecycle preservation | **Promising, not ready** | Resolve closest-formalism novelty and expose proof/Lean coverage precisely |
| Product-local reservation boundary | **Mathematically answered, contribution not ready** | Show importance of the checker class and delta beyond elementary rectangularity; mechanize it |
| Promotion representation and universal owner-order boundary | **Strongest asset, not ready** | Credit known configuration expressiveness; prove the lifecycle-specific delta; mechanize Boundary II |
| Real-runtime correspondence/security | **Supporting correspondence only** | Either keep non-load-bearing, or implement mandatory mediation/refinement before claiming concrete safety |

No paper-level RQ package is currently submission-ready. The milestone should loop, not advance to final submission writing.

## Strongest alternate explanation and decisive next test

The strongest alternate explanation is that the project is a careful application of known configuration/resource/supervisory semantics to agent lifecycle vocabulary, while conservative escrow/attenuation or staging already solves safety and the new machinery only recovers unmeasured availability.

The decisive next test is formal, not another broad implementation pass: encode the paper's `Phi`, quantitative labels, and promotion filter as a configuration structure/propositional theory with resources. Then prove exactly what does—or does not—remain of Boundary II once immediate owner cleanup and operational enabledness are added. This single task directly evaluates the project's own falsifier. If a genuinely new iff theorem remains, make it the paper center and mechanize it. If not, pivot the contribution type explicitly.

The decisive later systems experiment is one protected-boundary paired study comparing residual contracts with conservative attenuation/escrow and staged commit on a task that genuinely requires advance guarantees. It is secondary to resolving the theory blocker.

## Alternatives and final decision

- **Preferred path:** stay theory-led, perform the exact closest-model encoding, mechanize both boundaries, simplify the paper around Boundary II and the durable-support principle, and retain the Codex result as a bounded correspondence witness.
- **Fallback path:** if the formal delta is mostly inherited, reframe as a security-systems paper, build mandatory mediation, and demonstrate a practical availability benefit against current conservative/staged baselines.
- **Rejected path:** add more agent workloads, prompt benchmarks, dataset counts, or performance numbers before resolving novelty. They do not repair the CSF theory blocker.

**Routing decision:** return to a focused literature/idea and formal-experiment loop. Do not proceed directly to a final WRITE gate or submission. The project is incomplete-but-promising rather than merely overcomplicated: its central principle and Boundary II deserve preservation, but acceptance requires one more high-information cycle.

## Project-memory and tree updates

- Durable new closest-work risk: configuration structures already provide the higher-order family/propositional-theory substrate used by the promotion witness.
- Leading novelty candidate: final-owner-support as an operational universal-serializability condition under exact prefix repair and immediate cleanup.
- Evidence classification: Lean proves the finite canonical lifecycle, not Boundaries I--II; the adapter proves fixed-suite composite correspondence, not product refinement.
- Highest-priority next node: exact configuration/resource encoding and Boundary-II separation/mechanization.
- Secondary next node: advance-guarantee workload plus conservative-baseline comparison.

No canonical project memory was changed by this review; these updates are recommendations for the orchestrator to record after accepting the verdict.

## Completion assessment and uncertainty

This milestone review is complete. The paper, current author intent, evaluation contract, and material cycle artifacts have all been audited in the required order. Confidence is high that the problem and principle are meaningful, high that the current artifact claims are internally consistent within their stated scope, high that the manuscript is not yet acceptance-ready, and medium on ultimate novelty priority because the external attack was targeted rather than a systematic literature review. The verdict should therefore trigger the focused novelty/mechanization loop, not abandonment.

## Next node

Run a claim-oriented `research-literature-novelty` node centered on configuration structures, resource-labeled event semantics, consumable authorization, and cleanup-aware serialization; pair it with one `research-experiment-design` node whose artifact is a mechanized translation or separating theorem for Boundary II. Return to writing only after that result determines whether the paper remains theory-led or pivots to a systems-security contribution.
