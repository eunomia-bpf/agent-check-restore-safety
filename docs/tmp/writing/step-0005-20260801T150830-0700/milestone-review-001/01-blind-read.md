# Blind full-paper read and attack map

## Node metadata

- **Timestamp:** 2026-08-01T15:10:44-07:00
- **Parent:** `step-0005-20260801T150830-0700/milestone-review-001`
- **Objective:** Form an unprimed, paper-only CSF acceptance assessment and an external-verification attack map.
- **Review classification:** Security theory / programming languages, with a supporting runtime instantiation. Target venue: IEEE CSF 2027. The paper makes a security invariant, lifecycle-semantics, theorem, and enforcement-interface contribution; it is not an AI benchmark paper. I therefore apply the CSF/security-systems bar: a meaningful security property, explicit attacker and trust boundaries, rigorous semantics/proofs, closest formal foundations, and a credible path from the abstract monitor to protected effects.
- **References loaded:** `iter-review-critique/references/research-taste.md` and `iter-review-critique/references/systems-review.md`. The AI/ML review reference was intentionally not loaded because neither a learned method nor a benchmark claim is primary.
- **Ambiguity:** The artifact includes a Codex adapter, but the paper explicitly disclaims product-wide refinement and complete mediation. I treat that adapter as a correspondence witness, not as the main contribution or as empirical proof of the formal security claim.
- **Reviewer-context disclosure:** Before fixing this attack map I read `docs/user-instruction.md` as required by the orchestration, then only the review skill/reference files and the current paper sources/PDF. This exposes the venue and the user's desired high-level direction, but not any author's intended answer or prior verdict. I did **not** read `docs/idea-story.md`, `docs/evaluation.md`, any prior `docs/tmp` report, code/experiment artifacts, review report, or change summary.

## Inputs and provenance

I read the complete current paper rooted at `docs/paper/main.tex`: abstract; all nine included section files; conclusion and AI-use acknowledgment; `references.bib`; the compiled 13-page `main.pdf`; and all claim-bearing equations, theorem statements, examples, and Table I. There are no external figure files: the paper's only displayed evidence artifact is the validation table, with other examples expressed in text and mathematics. A clean temporary-directory `latexmk` build succeeded and produced 13 pages with resolved citations/references; only two underfull-box warnings remained. No paper or repository state was edited.

## Method

I first reconstructed the paper as one security argument, then attacked each link without external search: problem reality; challenged belief; principle; formal object; lifecycle mechanism; security theorem; two claimed exact boundaries; validation; runtime correspondence; limitations; and related-work positioning. External claims are listed as questions rather than accepted facts at this stage.

## Paper-only reconstruction

### Problem, stakes, and challenged belief

The paper argues that copied computational state is not the security state of an execution that can intentionally fork, restore, retain parallel continuations, merge results, and emit irreversible effects. A one-use grant may safely back conditional commitments in mutually exclusive branches, but an escape or later co-durable merge can make those commitments jointly count. The challenged operational belief is that branch isolation, rollback/state continuity, per-branch capability balances, first-commit-wins, or transaction-level validity is enough to preserve use-limited authority.

The stakes are real if all of the following hold: runtimes offer intentional history transformation; branches can obtain advance authority guarantees; lifecycle topology can change after reservation; protected external effects can escape before selection; and the monitor can reliably mediate those effects and lifecycle changes. The paper acknowledges that parent escrow avoids the problem for pure candidates and that current product hooks do not establish full mediation. Consequently, the practically important population is narrower than “tool-using agents” generally: it is runtimes that expose conditional branch-local reservation or joint lifecycle admission.

### Simple principle

In one sentence: **charge every conditional or escaped use of authority against every durable future in which that use can contribute, rather than against the copied state or originating branch alone.**

This principle is clear, intuitive after stated, and separable from the artifact name. It predicts that exclusivity can safely share authority, escape expands a claim's support, merge can make previously alternative load additive, and exact local budgets exist only when the residual authorization region factorizes.

### Artifact/mechanism and causal chain

The formal state tracks vector grant capacity, durable/terminal/tentative claim partitions, branch owners and epochs, a downward-closed family of permitted durability configurations, guarded choice/parallel contracts, stable effect tickets, and receipts. Authority continuity requires durable demand plus every configuration's conditional demand to remain within issued capacity. Lifecycle operations preserve this invariant through checked structural simulation or direct target admission; `Prepare` moves tentative claims into durable consumption and installs an exact frozen guard before dispatch; stable IDs account conservatively across crash and retry. The causal connection to the principle is direct: the permitted configuration family is the support of conditional authority, and promotion turns support-conditional load into global load.

### Claimed contributions and scope

1. A closed certificate-checked lifecycle LTS and conditional trace-safety result under complete mediation, bounded truthful demands, crash-atomic persistence, and sink retry assumptions.
2. Boundary I: a necessary-and-sufficient corner test for when fixed-topology batch-Reserve is exactly a Cartesian product of noncommunicating branch-local budgets.
3. Boundary II: a necessary-and-sufficient final-owner-support test for order-independent owner-group promotion under exact prefix repair, immediate cleanup, and no interleaved lifecycle mutation.
4. Validation through a Lean development of the finite canonical lifecycle (but not Boundaries I--II), exhaustive bounded Python exploration, and a fixed Codex 0.146.0 correspondence witness (but not complete mediation/refinement).

### Paper-level RQs and evidence mapping

The paper does not state explicit RQs or organize the validation around them. Its argument nevertheless implies four load-bearing questions:

| Implied RQ | Goal/claim mapping | Paper's answer and evidence | Blind readiness |
|---|---|---|---|
| RQ1. What security state and invariant are necessary for authority across fork/restore/merge/escape? | Definitions 1--2, guarded contracts, LTS, preservation and trace corollary | A residual profile over permitted co-durable branch configurations; paper proofs plus a Lean model of the finite canonical lifecycle | **Partly answered.** The abstract property is crisp, but the complex preservation proof is only sketched in the paper and the concrete theorem is conditional on unvalidated mediation/binding assumptions. |
| RQ2. When can reservation be decentralized into noncommunicating branch-local capabilities? | Headroom, residual derivative, Boundary I | Exact iff the all-headrooms corner satisfies every residual inequality; short mathematical proof and exhaustive finite checks | **Answered in the stated fixed-topology fragment**, subject to novelty verification and clarity about the narrow checker class. |
| RQ3. What exact policy repair does escape require, and when is serial promotion order-independent? | Promotion nonclosure, guard closure, owner support, Boundary II | One frozen threshold row gives maximal exact pruning; all owner-group orders succeed iff promoted owners retain final support; short proof and finite checks | **Answered under strong operational assumptions**, subject to novelty verification and formal scrutiny of cleanup/order semantics. |
| RQ4. Does the design correspond to a real agent runtime and its protected effects? | Validation and discussion | 20 fixed Codex histories, 89 decisions, adapter-owned topology, client-owned dispatch, loopback sink | **Unanswered at submission strength.** The paper candidly says this is not complete mediation, generic merge, or product refinement; therefore it cannot establish the deployed security property. |

A theory-led CSF paper need not mimic an empirical benchmark paper, but the absence of explicit questions makes it difficult to distinguish theorem evidence, mechanization coverage, bounded model validation, and runtime correspondence. Under the review contract, all paper-level RQs/evidence are **not submission-ready** because RQ4 remains only a conditional witness and because the main boundaries are outside the mechanization.

## Initial paper-only verdict

**Major revision, leaning reject at a fresh-submission bar.** The paper has a memorable, potentially useful security principle and two exact boundaries. It is unusually candid about assumptions and nonclaims. However, the current manuscript asks the reviewer to accept that an elementary-looking resource/configuration construction constitutes a novel security foundation while (i) the closest event-structure, resource-semantics, capability, and supervisory-control comparison is asserted rather than demonstrated, (ii) the theorem carrying concrete security assumes the two hardest deployment obligations, truthful semantic binding and complete mediation, and (iii) the runtime experiment explicitly does not test those obligations. The artifact validates definitions and a narrow correspondence but does not yet close the abstract-to-real security argument.

### Strongest plausible reject argument

The work may be a clean repackaging of standard configuration semantics plus additive resource accounting, with an adapter demo that cannot enforce the stated threat model. The core invariant is “every permitted configuration fits the budget”; Boundary I is the downward-closed region's equality with its coordinate box iff its greatest corner is feasible; exact promotion is intersection with a budget inequality; and order-independence follows from monotonicity plus cleanup support. Unless primary literature shows that the particular conditional-authority abstraction and lifecycle promotion results are not already immediate instances of event structures, BI/residuation, linear capabilities, resource-constrained workflow/supervisory control, or consumable credentials, the security novelty may be insufficient for CSF. Even if novel, the real-runtime story assumes accurate co-durability topology, effect binding/demand, and complete mediation, while the Codex witness leaves those assumptions to adapter metadata and client-owned dispatch. Thus the paper could be judged both theoretically incremental and operationally unvalidated.

### Strongest paper-internal evidence against that reject

The paper cleanly separates known components from its claimed novelty, gives falsifiable exact boundaries rather than a feature list, states a concrete adversary and TCB, preserves stable effect bindings across crash/retry/revocation, supplies counterexamples that distinguish per-branch headroom from correlated residual state, and explicitly limits the Codex result. This is closer to simple-but-deep theory than terminology-only systems work if the external novelty attack survives.

## Ranked blind findings

### Blockers

1. **Evidence/evaluation — no evidence that the stated concrete security theorem applies to a real runtime.** The abstract, introduction, trace corollary, validation, and discussion condition security on complete mediation, truthful typed binding/demand, trusted topology, and sink bounds. The fixed adapter instead owns the topology and dispatch, uses a loopback isolated sink, excludes built-in/direct tool paths and generic merge, and explicitly disclaims refinement. The reviewer cannot infer that the adversarial model output cannot bypass or lie to the protected boundary. Repair route: **EXPERIMENT_GATE**, preserving the ambitious claim by implementing or measuring a mandatory mediation boundary for at least one real runtime and providing a refinement map for fork/restore/merge/effect events, including bypass tests and crash windows. If the intended contribution is purely foundational, the paper needs to make RQ4 non-load-bearing and replace the present product-flavored evidence with a rigorous formal case study rather than imply current deployability.

### Major findings

2. **Novelty/scientific framing — the novelty case is not yet discriminating enough.** The paper acknowledges that configurations, linear resources, residual implication, guards, cographs, and supervisory control are classical, but it never places its state and operations in a theorem-level comparison with the closest general model. A skeptical reviewer can view `AC`, residuals, rectangularity, and promotion filtering as straightforward specializations. Repair route: **WRITE_GATE plus targeted literature work**, potentially **EXPERIMENT_GATE** only if a separating counterexample must be mechanized. State a precise non-encodability, mismatch, or new compositional theorem against the closest event/resource/supervisory formalism; do not merely rename configuration-wise capacity.

3. **Technical mechanism/evidence — the proof burden and mechanization coverage are mismatched to the headline.** The full LTS includes transfer fibers, fresh fragmentation, epochs, support witnesses, arbitrary guarded predicates/projections, cleanup, ticket phases, revocation, and two merge modes. The paper proof of lifecycle preservation is a single case-analysis paragraph. Lean covers a finite canonical lifecycle but explicitly excludes Boundaries I--II, semantic binding, issuer approval, complete mediation, and sink truthfulness. The two advertised exact boundaries are checked only by hand proof plus bounded enumeration. Repair route: **EXPERIMENT_GATE** (formal experiment): mechanize both boundaries and the guarded promotion/serial cleanup correspondence over the stated generality, publish a theorem-to-code coverage table, and add proof details/appendix via **WRITE_GATE**.

4. **Global logic/consistency — the paper lacks explicit, stable paper-level RQs and mixes proof, finite validation, and runtime correspondence as one validation story.** The two “boundaries” are clearer than the evidence plan, but RQ1/RQ4 are implicit, and Table I aggregates definition transcription checks, theorem counterexamples, and lifecycle state enumeration without mapping them to contributions. Repair route: **WRITE_GATE**. State two to four RQs early; organize validation by theorem soundness, model counterexample coverage, and runtime correspondence; mark the concrete-runtime refinement RQ honestly unresolved unless new evidence answers it.

5. **Scientific framing/real-world relevance — the useful population may be narrower than the headline suggests.** The paper itself observes that parent escrow suffices for pure candidates and that the calculus matters when branches receive advance guarantees or joint actions. It has no sourced evidence that deployed or proposed runtimes expose such reservations, that operators merge authority-bearing alternatives, or that use-limited grant oversubscription has occurred. Repair route: **WRITE_GATE backed by external source verification**; ground the challenged belief and target workload in primary runtime/proposal evidence and give one end-to-end scenario whose conditional promise cannot be represented by escrow, ordinary transactions, or linear splitting without losing a required liveness/availability guarantee.

### Minor findings

6. **Writing — the central story is dense and noun-heavy despite a simple principle.** “Durability configuration,” “residual authorization profile,” “frozen quantitative support guard,” “lineage projection,” and certificate variants arrive rapidly. Most terms are semantically distinct, but “conditional commitment” and “tentative claim” can likely be merged, and “guarded contract”/“frozen threshold guard” should be presented as representation versus installed row rather than adjacent branded concepts. A compact running diagram or state table would materially improve reviewability.

7. **Evidence presentation — the 13-page PDF builds cleanly, but the validation table is the only conventional table/figure.** The main text appears to remain within the 12-page non-reference limit because references begin on page 12, but exact compliance should be checked against the current CSF counting rule. The runtime counts are difficult to audit without a manifest, artifact URI/hash, policy definitions, or confidence that “89 decisions” exercises meaningful diversity.

8. **Scope/claims — “exact runtime boundaries” is broader than the theorem domains.** Boundary I is fixed-topology, Reserve-only, batch admission against a Cartesian product class. Boundary II assumes a fixed valid atomic batch, owner-group granularity, exact prefix guards, immediate deterministic cleanup, and no interleaving. The abstract lists most qualifiers, but the title/introduction still invite a broader reading across fork, restore, and merge.

### Nits

9. **Writing:** Capitalization of `Reserve`/`Prepare`, “escape”/“promotion,” and “restore-live”/“live restore” should be made uniform. The clean build reports only two underfull boxes, not a substantive submission problem.

## Load-bearing external-verification attack map

| Question to attack | Why it is load-bearing | Primary source families to open |
|---|---|---|
| Do current agent runtimes actually support native fork, resume/checkpoint, parallel descendants, merge/commit, and pre-tool control with the claimed semantics/limitations? | Establishes the problem population and whether the challenged belief is real | Official Codex and Claude documentation/protocol schemas; official runtime repositories/releases |
| Is conditional use-limited authority over mutually exclusive branches already captured by consumable credentials, linear capabilities, BI/separation residuation, event structures, or resource-aware type systems? | Determines foundational novelty | Original papers/PDFs and formal definitions, not surveys |
| Are residual-region factorization and threshold promotion already standard resource-constrained workflow or supervisory-control results? | Attacks Boundaries I--II directly | Original workflow-threshold, supervisory-control, state-tree/guard-synthesis papers |
| Does output-commit/transaction literature already solve the escape-to-durable transition under branching? | Tests whether promotion is a new authorization problem or an old recovery transaction | Original rollback-recovery/output-commit and recent agent transaction papers |
| Do the 2026 adjacent agent papers exist and make the precise claims attributed to them? | Much of the real-world and novelty positioning rests on very recent preprints | Primary arXiv PDFs/repositories for ACRFence, Crab, Fork/Explore/Commit, Agent libOS, Atomix, Cordon, DART, Ghost Tool Calls, Commit-Time Authorization |
| Is the CSF 2027 scope, page rule, AI acknowledgment rule, and current submission bar accurately reflected? | Submission readiness and venue fit | Official CSF 2027 call and official IEEE policy |

## Alternatives and decision

The most promising interpretation is not “a secure Codex extension” but a security/PL contract for **advance use-limited guarantees under changing co-durability**. That is a defensible larger claim if external work does not already give the same object and if the paper supplies a credible enforcement/refinement path. The conservative alternative is an application note combining known resource semantics with agent lifecycle vocabulary; that is unlikely to clear CSF. I do not recommend shrinking to a workspace rollback bug or a narrow Codex policy.

## Tree/search updates

- Attack branches opened: foundational novelty; exact-boundary prior art; runtime reality/mediation; venue compliance; recent same-claim agent work; proof/mechanization coverage.
- Highest-information next action: primary-source search and direct opening of the closest formal/resource and current agent-runtime papers, with explicit attempts to falsify novelty and deployed applicability.

## Project-memory updates

No canonical project memory was read or changed. Candidate durable observation for the orchestrator: review this as security theory/PL with a runtime witness, and keep “complete mediation + truthful topology/binding are unvalidated” separate from the source-grounded novelty verdict.

## Completion assessment and uncertainty

The blind phase is complete. The paper-only attack map is fixed before external search. Main uncertainty is whether the apparently elementary theorems are novel in their lifecycle-specific combination and whether current runtime interfaces provide enough authoritative topology/effect control to make the abstraction useful.

## Next node

Mandatory external search and primary-source opening, followed by a full-paper reread. Do not consult prior author framing or cycle artifacts before the source-grounded assessment is fixed.
