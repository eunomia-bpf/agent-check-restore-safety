# Source-grounded full-paper reread

## Node metadata

- **Timestamp:** 2026-08-01T15:25:31-07:00
- **Parent:** `step-0005-20260801T150830-0700/milestone-review-001`
- **Objective:** Re-evaluate the entire current manuscript against the primary-source attack, with no author-intent or cycle-artifact priming.
- **Classification and bar:** CSF 2027 security theory / programming languages with a supporting runtime instantiation. The deciding bar is security significance plus formal novelty and assurance; the Codex study is judged as a refinement/correspondence artifact, not an AI benchmark.
- **Review-state disclosure:** After fixing `02-external-search.md`, I reread `main.tex`, all nine section files, the complete bibliography, all theorem/proof text and Table I, and the compiled paper presentation from page one. I still had not opened `docs/idea-story.md`, `docs/evaluation.md`, prior cycle reports, code, experiment artifacts, or change summaries.

## Inputs, provenance, and method

This was a second complete read of the current paper under `docs/paper/`, not an edit or selective response to the blind findings. I traced four implied research questions through abstract, introduction, formal definitions, lifecycle rules, results, algorithm, validation, related work, limitations, and conclusion. For each headline result I asked: what is established by proof, what is merely checked on bounded states, what is mechanized, what is demonstrated on a real runtime, and what remains an assumption. I then tested the paper's novelty sentences against the closest primary sources identified in the external pass.

## Updated reconstruction

The paper's deepest contribution is not the observation that external effects survive rollback and not the use of a downward-closed family by itself. It is a security contract for **advance finite-use promises whose support changes when alternative continuations escape or become co-durable**. The contract indexes conditional load by each permitted durability configuration; `Prepare` changes a tentative promise into globally durable consumption and freezes the exact safe restriction; topology changes must conserve claims and either simulate the old contract or pass fresh admission.

That produces two sharply scoped results:

1. In a fixed-topology, Reserve-only batch fragment, exact independent branch-local budget checking is possible exactly when the residual down-set equals the product of its one-branch projections, tested at the product's greatest corner.
2. For a fixed valid atomic promotion batch, grouped by source owner, with exact prefix repair, immediate cleanup, and no lifecycle interleave, all serial orders remain enabled and reach the atomic result exactly when every promoted owner has final support.

The paper is commendably explicit that configuration semantics, resource residuation, threshold predicates, guards, cographs, linear consumption, and supervisor synthesis are not new. Its abstract and validation also explicitly say the Codex adapter is not complete mediation or product-wide refinement. Those qualifications prevent several easy overclaim objections. They do not, however, supply the missing positive case for why the remaining theorem delta is a substantial CSF contribution.

## Simple principle and taste assessment

The project does have a simple organizing principle: **authority follows durable support, not copied state**. It is memorable, predicts all major examples, and connects lifecycle topology, external effect timing, and finite authority without depending on agent branding.

The external search validates the challenged belief rather than exposing a strawman. Official Claude documentation states that checkpoint rewind omits Bash and external effects, while official Codex material exposes persistent thread forking ([Claude checkpointing](https://code.claude.com/docs/en/checkpointing), [Claude runtime boundary](https://code.claude.com/docs/en/how-claude-code-works), [Codex app server](https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md)). ACRFence and Ghost Tool Calls independently study replay/resurrection and issue-time leakage in branching or restored agents ([ACRFence](https://arxiv.org/html/2603.20625v1), [Ghost Tool Calls](https://arxiv.org/html/2606.02483v1)).

The work is nevertheless **simple in principle but incomplete in scientific closure**, rather than fully simple-but-deep in its current manuscript. The insight is good; the exact boundaries are clean; the formal substrate is classical and the paper has not yet demonstrated that its narrow new delta produces either a deeper theorem family or a practically important capability unavailable from conservative escrow/attenuation/staging.

## Research-question readiness

| Implied RQ | Full-reread assessment | Submission readiness |
|---|---|---|
| **RQ1. What state and invariant preserve use-limited authority across fork, restore, merge, and escape?** | Definitions 1--2, the claim partition, guarded contracts, certified LTS, preservation theorem, and conditional trace corollary form a coherent answer. The threat/TCB assumptions are unusually candid. But the source-grounded novelty boundary against configuration structures, resource-sensitive event semantics, and consumable credentials remains informal. | **Not ready.** Technically coherent, but novelty and proof depth are not sufficiently demonstrated for the largest claim. |
| **RQ2. When can batch reservation be decentralized to noncommunicating branch-local budgets?** | Boundary I is correct and well scoped. The proof is essentially the greatest-corner fact for a down-set inside the product of its projections; the architectural corollary is useful only for the explicitly chosen Cartesian-product checker class. | **Mathematically answered, contribution case not ready.** Needs a formal/implementation reason this checker class matters and a sharper statement of what is new beyond elementary rectangularity. |
| **RQ3. When is exact serial promotion order-independent under cleanup?** | Boundary II is the strongest result. The sufficiency/necessity proof is intuitive and the negative example distinguishes algebraic guard commutation from operational enabledness. Yet the higher-order conflict motivation is standard configuration-structure expressiveness, and the theorem is neither mechanized nor given a more general concurrency/serialization context. | **Promising but not ready.** This is the best candidate for the paper's core formal contribution after mechanization and closest-work differentiation. |
| **RQ4. Does the abstract security story hold at a real protected runtime boundary?** | The validation section accurately calls the Codex experiment a fixed correspondence witness. It uses native fork, but adapter-defined topology/restore/merge, client-owned dispatch, and a loopback sink. Built-in/direct paths, topology activation crashes, semantic binding, and generic merge are out of scope. | **Not answered at submission strength.** It shows reproducible adapter behavior, not the refinement assumptions of the trace corollary. |

All paper-level questions are therefore not simultaneously submission-ready. A formal paper could make RQ4 explicitly illustrative rather than load-bearing, but it would then need a stronger formal novelty/proof package than the current one.

## Strongest reject argument after reread

**Reject because the manuscript does not yet establish that its new formal contribution is large enough once classical substrate is removed, and its implementation does not close that gap with concrete security evidence.** The family `Phi` and its higher-order conflicts are standard configuration-structure material; van Glabbeek and Plotkin explicitly represent “every pair allowed, triple forbidden” as ternary conflict/propositional theory ([Configuration Structures](https://arxiv.org/abs/0912.4023)). Resource-sensitive event semantics already combine configurations and resource consumption ([Resource-Tracking Concurrent Games](https://link.springer.com/chapter/10.1007/978-3-030-17127-8_2)); consumable credentials already give globally consumed use-limited authority ([Consumable Credentials](https://www.ndss-symposium.org/wp-content/uploads/2017/09/Consumable-Credentials-in-Linear-Logic-Based-Access-Control-Systems.pdf)); supervisor/state-tree work already supplies maximally permissive guarded restrictions. After those are subtracted, Boundary I is an elementary rectangularity test and the main surviving novelty is a narrow immediate-cleanup promotion-order theorem. The paper does not mechanize either headline boundary or compare them at theorem level with those foundations. Its Codex study, meanwhile, explicitly does not mediate the adversarial product paths required by the concrete trace theorem. A reviewer can therefore see a thoughtful synthesis and useful vocabulary without a sufficiently established foundational advance or end-to-end security result.

## Strongest evidence against rejection

No primary source opened in the targeted attack gave the exact security combination of configuration-supported advance quantitative promises, irreversible promotion repair, and the iff final-owner-support criterion for every owner-group serial order. The paper consistently separates assumptions and nonclaims, gives explicit counterexamples, defines stable crash/retry bindings, makes merge certificates first-class, and derives exact rather than heuristic boundaries. The main theorem family is not internally incoherent. With a more discriminating formal comparison, mechanization, and one decisive real protected-boundary experiment, this could become an unusually crisp CSF paper.

## Ranked findings

### Blocker

1. **Novelty and evidence closure — the residual formal contribution is not yet demonstrated to clear the venue bar.**
   - **Location:** Introduction contributions; `Authority over Durable Futures`; Proposition “Choice/parallel is not promotion-closed”; Boundaries I--II; `Related Work` paragraphs on concurrency and supervisory control.
   - **Failed inference:** From “existing ingredients do not by themselves characterize our promise” the reviewer cannot infer that the resulting invariant and exact boundaries constitute a substantial new foundation. The manuscript never maps `Phi` to configuration structures, never compares the promotion row with propositional configuration theories, and omits the closest resource/event model.
   - **External evidence:** Configuration structures already model arbitrary permitted families and explicit ternary conflict; resource-tracking concurrent games already combine event configurations with resource consumption; consumable credentials already enforce use-limited authority. See the primary sources linked above.
   - **Missing evidence:** A formal translation table, separating trace/property, or non-derivability/strict-specialization argument; a broader same-claim novelty map; and mechanized headline results.
   - **Gate and repair:** **EXPERIMENT_GATE** for formal mechanization and separating examples, followed by **WRITE_GATE** for theorem-level closest-work comparison. The safest ambitious revision centers Boundary II and the conditional-promise/security interpretation, and demotes the standard higher-order-conflict observation.

### Major findings

2. **Runtime security — the concrete theorem's critical assumptions are not exercised by the artifact.**
   - **Location:** Threat and trusted boundary; Effect coverage; Concrete trace authority safety; Concrete adapter instantiation; Runtime correspondence; limitations.
   - **Failed inference:** From a matching adapter policy over 89 decisions, the reviewer cannot infer complete mediation, accurate effect binding/demand, authoritative topology, or forward simulation of protected runtime events.
   - **External evidence:** Agent libOS offers explicit checkpoint/fork capability semantics and one-shot reserve/consume discipline; Cordon interposes on tool dispatch and stages external effects; Commit-Time Authorization runs an invalidation/bypass-style matrix ([Agent libOS](https://arxiv.org/html/2606.03895v2), [Cordon](https://arxiv.org/html/2606.17573v1), [Commit-Time Authorization](https://arxiv.org/html/2607.10487v1)).
   - **Missing evidence:** A mandatory sink boundary, enumerated bypass surface, concrete-to-abstract event map, adversarial invalidation traces, crash windows around topology activation, and a comparison with conservative escrow/attenuation.
   - **Gate and repair:** **EXPERIMENT_GATE**. Either implement that boundary for one runtime or remove any suggestion that the adapter supports the concrete trace claim and present it as a small API feasibility appendix.

3. **Formal assurance — proof and mechanization coverage do not match the model's surface or headline.**
   - **Location:** Topology certificates through crash-aware dispatch; Abstract lifecycle preservation proof; both boundary proofs; Lean paragraph.
   - **Failed inference:** A one-paragraph case split plus 755 finite-carrier Lean jobs does not let the reviewer audit the full stated calculus, because the paper's Lean limitations exclude the two named boundaries, semantic binding, complete mediation, and sink truth. “Arbitrary finite carrier types” is also easy to misread beside preallocated identifiers and a separately simplified executable model.
   - **Missing evidence:** Public theorem statement/implementation mapping, proof dependency/assumption inventory, mechanized Boundaries I--II, and longer proof material for transfer fibers, predicate transport, cleanup, and stable tickets.
   - **Gate and repair:** **EXPERIMENT_GATE** for mechanization and artifact audit, then **WRITE_GATE** for an appendix and coverage table.

4. **Evaluation logic — the manuscript aggregates heterogeneous checks without explicit research questions or claim-to-evidence structure.**
   - **Location:** Introduction contributions and entire `Mechanized and Executable Validation` section, especially Table I.
   - **Failed inference:** Counts of enumerated identities, state transitions, Lean build jobs, policy decisions, forks, and crashes are not commensurate evidence. The reader must reverse-engineer which claim each count supports and which headline claims are outside each artifact.
   - **Missing evidence:** Stated RQs; a theorem-to-proof/model/runtime matrix; definitions of history classes and policy decisions; explicit negative controls; and an artifact manifest/hash.
   - **Gate and repair:** **WRITE_GATE** after experiment design is fixed. Organize validation as formal soundness, bounded falsification, and concrete refinement/utility—not as one count-heavy sequence.

5. **Practical importance — the paper proves safety for an unmeasured availability feature.**
   - **Location:** Introduction paragraphs on conservative splitting/escrow; running example; capabilities discussion; runtime validation.
   - **Failed inference:** Showing that conservative policies reject some adapter successors does not show that advance branch-local guarantees are needed by important workloads or that the proposed additional concurrency is worth the guard/oracle complexity.
   - **External evidence and alternative explanation:** Agent libOS-style attenuation, parent escrow, first-commit-wins, or Cordon-style staging may safely avoid the problem. The current work may primarily recover availability from those conservative designs.
   - **Missing evidence:** An end-to-end task where a branch must hold an enforceable advance guarantee, a later lifecycle change is useful, conservative baselines reject useful work, and the proposed monitor safely completes it.
   - **Gate and repair:** **EXPERIMENT_GATE** for a real workload/baseline study; **WRITE_GATE** to present availability as the intended benefit rather than treating conservative designs as incomplete security answers.

### Minor findings

6. **Representation complexity is incompletely characterized.** The paper shows linear construction of one promotion row and coNP-complete universal safety with a single scalar guard, but does not report accumulated-guard growth, projection-circuit growth across repeated lifecycle transformations, solver behavior, or certificate size. Avoid implying a compact practical runtime representation from one-row size alone.

7. **The concept surface can be reduced.** “Conditional commitment” and “tentative claim” denote nearly the same operational object; “guarded contract,” “frozen guard row,” and “residual authorization profile” need one representation diagram rather than repeated verbal introductions. “Durability configuration” and “co-durable future” are both useful, but one should be the formal term and the other only intuition.

8. **Scope language still occasionally outruns theorem scope.** “Two exact runtime boundaries” is acceptable only when immediately qualified. Boundary I is Reserve-only and fixed-topology; Boundary II is a fixed valid atomic batch under exact prefix repair, owner grouping, immediate cleanup, and no interleaving. The title covers fork/restore/merge broadly, while the exact results concern reservation factorization and serial promotion.

### Nits

9. The paper builds cleanly and appears to fit the official 12-page body rule because references begin on PDF page 12; perform a final mechanical page-boundary check. Terminology and operation capitalization (`Reserve`, `Prepare`, “live Restore”) should be normalized. The bibliography's verified-comment metadata is useful for authors but not part of submission evidence.

## Largest claim and decisive evidence

The largest defensible claim is narrower than the paper's broadest framing: **when a runtime offers advance finite-use promises to intentionally alternative continuations, and later operations may change which continuations/effects become jointly durable, authority must be indexed by the permitted co-durability family; this yields exact criteria for product-local Reserve and owner-order-independent promotion under the stated restrictions.**

The single most decisive real-world experiment would implement one mandatory protected dispatch boundary on a runtime with native fork and checkpoint/resume; bind stable operation IDs and finite one-shot grants durably; run paired fork/restore/merge histories across crashes and bypass attempts; and compare (a) null/snapshot-local checking, (b) parent escrow or Agent-libOS-style conservative attenuation, (c) staged/commit-time authorization, and (d) the residual contract. It must report unsafe duplicate/unauthorized effects, useful completed branches or admitted batches, false rejects, recovery behavior, and every unmediated path. That one experiment would simultaneously test problem significance, the availability benefit, and the refinement obligations.

The decisive formal search/experiment is a mechanized encoding comparison: express the paper's state as a configuration structure with resource labels and a propositional theory, then identify and prove exactly which lifecycle/promotion theorem is not inherited from that model. If everything reduces directly, the paper should be reframed as a security application with stronger systems evidence; if Boundary II genuinely adds an operational serialization theorem, make that result central.

## Deletable or mergeable concepts

- Merge “conditional commitment” into “tentative claim,” defining once that a tentative claim is an advance conditional promise.
- Present `Phi`, the residual region, and guarded contracts in one pipeline: semantic future family → quantitative residual → durable representation. Do not introduce each as a separate conceptual destination.
- Demote the non-pairwise-conflict proposition to motivation after citing configuration structures; it is not a headline novelty result.
- Keep “authority continuity” and the durable-support principle. They earn their names by organizing the full paper.
- Move most adapter counts and low-level policy labels to an artifact appendix; retain only claim-bearing comparisons in the paper.

## Alternatives and decision

The best revision does not shrink to a Codex hook patch. It preserves the ambitious formal target but makes an explicit choice:

- **Theory-led path:** establish the precise delta from configuration/resource semantics, mechanize both boundaries, expand proof coverage, and make the adapter plainly illustrative.
- **Security-systems path:** keep the existing formal kernel, implement a mandatory effect boundary, and demonstrate a workload/availability advantage over conservative baselines.

Trying to split the current evidence budget evenly leaves both paths below threshold. My source-grounded paper-only recommendation is **reject / major revision**, with Boundary II and the durable-support principle as the strongest assets to preserve.

## Tree/search updates

- Closed: problem reality, CSF scope fit, internal coherence of the invariant and restricted boundary proofs.
- Acceptance-blocking: formal novelty delta and headline-proof assurance.
- Major open branches: concrete refinement/mediation; practical advance-guarantee workload; baseline comparison; explicit RQ/evidence organization.
- Recommended outer-loop next nodes: `research-literature-novelty` for the exact theory delta and `research-experiment-design` for the one protected-boundary comparison. Use `WRITE_GATE` only after one of those resolves the contribution strategy.

## Project-memory updates

No project memory, idea story, evaluation plan, or cycle artifact was read or changed in this phase. Candidate durable judgment: treat the higher-order configuration example as known substrate; preserve the final-owner-support theorem as the leading novelty candidate; never describe the Codex adapter as concrete trace-safety evidence.

## Completion assessment and uncertainty

The required post-search full reread is complete. Confidence is high in the reject/major-revision judgment and the runtime-evidence gap, medium in the exact severity of the novelty gap because the external pass was targeted rather than systematic, and high that the problem itself is real. No paper or canonical project file was edited.

## Next node

Only now open the author's idea/evaluation state and current-cycle code, experiments, and artifacts. Audit whether the cycle delivered its declared goals and whether it followed the user's high-ambition, theory-led intent; then issue the final milestone verdict without repeating the preceding inventories.
