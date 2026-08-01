# External primary-source novelty and reality attack

## Node metadata

- **Timestamp:** 2026-08-01T15:18:04-07:00
- **Parent:** `step-0005-20260801T150830-0700/milestone-review-001`
- **Objective:** Falsify the blind-read novelty, relevance, and submission-fit case using current primary sources before rereading the paper.
- **Classification and bar:** CSF 2027 security theory / programming languages with a supporting runtime instantiation. I apply a security/formal-methods bar: the security property and threat boundary must be meaningful; the formal advance over the closest semantic models must be explicit; and the runtime evidence must test the assumptions connecting the theorem to protected effects. I do not apply an AI benchmark bar.
- **Review-state disclosure:** This search began only after `01-blind-read.md` fixed the paper-only attack map. I still had not read `docs/idea-story.md`, `docs/evaluation.md`, prior `docs/tmp` steps, cycle code, experiment artifacts, review reports, or author change summaries. The search used the paper's bibliography and claims only to generate adversarial queries, not as evidence that those claims were correct.

## Inputs, provenance, and method

I searched for and directly opened official runtime documentation/source, the official CSF call, original formal papers, proceedings-hosted PDFs, and authors' current preprints. Search-result snippets, blogs, Wikipedia, and secondary summaries were discovery aids only and are not evidence below. GitHub issue discussions and an abstract-only student repository item were excluded from claim support. Recent 2026 arXiv work is labeled as preprint evidence rather than treated as peer-reviewed fact.

The search questions were: (1) whether actual runtimes expose the relevant lifecycle and rollback boundary; (2) whether escaped-effect and stale-authority failures are real rather than hypothetical; (3) whether the paper's configuration family, residual region, non-pairwise promotion example, guards, and exact boundaries already follow from established formalisms; (4) which current systems constitute stronger enforcement baselines; and (5) whether the manuscript fits CSF's current scope and length rule. Queries combined terms such as “configuration structures ternary conflict,” “event structures resource consumption configurations,” “linear logic consumable credentials,” “supervisory control propositional guards state tree,” “agent checkpoint fork external side effects authority,” and the names of the paper's closest 2026 systems.

## Source-grounded results

### 1. The problem and challenged belief are real

Official Claude Code documentation says checkpoint rewind does not undo Bash-command side effects or external changes, and specifically names remote databases, APIs, and deployments as state that cannot be checkpointed. It separately exposes session forking. Its hooks documentation shows that `PreToolUse` can block covered tool calls, but the event matrix is interface-specific rather than a proof of complete mediation. Sources: [Claude Code checkpointing](https://code.claude.com/docs/en/checkpointing), [how Claude Code works](https://code.claude.com/docs/en/how-claude-code-works), and [hooks reference](https://code.claude.com/docs/en/hooks).

OpenAI's current Codex material describes persistent threads that can be created, resumed, and forked, while the app-server protocol says `thread/fork` copies conversation history into a new thread identifier. It does not expose native authority-aware restore or merge semantics. This supports the paper's use of a real fork operation but also confirms that its restore/merge topology is adapter-assigned rather than product-native. Sources: [OpenAI, “Unlocking the Codex harness”](https://openai.com/index/unlocking-the-codex-harness/) and [Codex app-server README](https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md).

The recent preprint ACRFence reports duplicated irreversible actions under context restore and stale token reuse, then proposes a proxy-level replay-or-fork defense. Crucially, it says the proposed defense is not implemented, so it is evidence of the failure mode and an adjacent design, not empirical evidence for a deployed solution. [ACRFence primary preprint](https://arxiv.org/html/2603.20625v1).

Ghost Tool Calls establishes a related but distinct issue-time boundary: once an external read has been issued, later rollback cannot “unsend” the observation. Its paired replay/real traces reinforce the paper's irreversible-escape premise, although its target property is privacy rather than aggregate use-limited authority. [Ghost Tool Calls primary preprint](https://arxiv.org/html/2606.02483v1).

**Effect on the blind attack map:** the problem is not a strawman. Blind finding 5 should be narrowed: evidence exists for history transformation plus irreversible external effects. What remains unsupported is the prevalence and value of the paper's more specific feature—advance conditional promises sharing a finite grant across alternatives and later becoming jointly durable.

### 2. The closest practical systems raise the runtime-evidence bar

Agent libOS is substantially closer than a generic agent-OS citation. It distinguishes action surface from authority, provides checkpoint restore/fork/commit, attenuates capabilities across forks, and reserves then consumes one-shot grants at commit. It explicitly states that restore does not roll back filesystem, shell, JSON-RPC, MCP, network, human, or provider effects. This is a real conservative design point against which the paper's proposed conditional sharing should be compared. [Agent libOS primary preprint](https://arxiv.org/html/2606.03895v2).

Cordon interposes on tool dispatch, stages external effects, validates a task-scoped transaction over a lineage, and reports a 45-scenario comparison. It expressly presents an operational protocol rather than a new formal semantic model. It is not the same aggregate-capacity theorem, but it is a much stronger runtime baseline for the paper's `Prepare`/dispatch/settle path and for escape containment. [Cordon primary preprint](https://arxiv.org/html/2606.17573v1).

Commit-Time Authorization defines freshness, causality, binding, and eligibility checks with branch tokens and reports a 54-task invalidation matrix in which a guard blocks protected surfaces when invalidating signals occur. Its property is not configuration-wise quantitative capacity, but its experiment is the appropriate comparison for whether a lifecycle monitor actually mediates stale-branch effects. [Commit-Time Authorization primary preprint](https://arxiv.org/html/2607.10487v1).

Fork, Explore, Commit demonstrates copy-on-write branch isolation, nested exploration, process-group control, and first-commit-wins selection. It supports the workload premise but does not solve effects that escaped before selection or conditional finite-authority aggregation. [Fork, Explore, Commit primary preprint](https://arxiv.org/html/2602.08199).

**Effect on the blind attack map:** the paper has a plausible differentiator—less conservative conditional sharing with an availability/advance-guarantee benefit—but never demonstrates that benefit or measures its enforcement. Merely showing 20 adapter histories and 89 policy decisions is materially weaker than the adjacent invalidation, staging, and baseline protocols. A decisive experiment needs a mandatory sink boundary, bypass attempts, fork/restore/merge invalidations, crash windows, and comparison with conservative one-shot attenuation/escrow and staged commit.

### 3. Established theory materially weakens the current novelty presentation

The most important source found is van Glabbeek and Plotkin's configuration-structure theory. It treats a configuration structure as a family of permitted configurations, relates such families to event structures and Petri nets, and explicitly represents ternary conflict with a propositional clause in which every pair of three events is allowed but their triple is forbidden. The paper's promoted-row example has exactly this combinatorial shape. Thus “pairwise compatibility cannot represent all valid post-promotion families” is not itself a new semantic phenomenon; it is the standard expressiveness of a general configuration family over binary conflict. [Configuration Structures, Event Structures and Petri Nets](https://arxiv.org/abs/0912.4023).

Winskel's original event-structure account likewise supplies the configuration/conflict foundation. The manuscript cites it, but it does not compare its exact `Phi` object and threshold row to the more direct configuration-structure/propositional-theory formulation above. [Winskel, Event Structures](https://www.cl.cam.ac.uk/~gw104/Winskel1987_Chapter_EventStructures.pdf).

Resource-Tracking Concurrent Games combines event-structure concurrency with a resource algebra for sequential and parallel consumption. It is not cited by the manuscript. It does not obviously make resource feasibility determine control topology in the same lifecycle-specific way, but it is close enough that a reviewer needs an explicit model and theorem comparison rather than a generic statement that event structures do not provide the paper's invariant. [Resource-Tracking Concurrent Games](https://link.springer.com/chapter/10.1007/978-3-030-17127-8_2).

Consumable Credentials already models linear, globally consumed authorization material and dynamically determined use limits, including conflict-sensitive examples. It appears to govern authorization of individual proofs/effects rather than advance promises supported by alternative future configurations, which is a meaningful distinction, but the current related-work paragraph does not make that formal separation. [Consumable Credentials in Linear Logic Based Access Control Systems](https://www.ndss-symposium.org/wp-content/uploads/2017/09/Consumable-Credentials-in-Linear-Logic-Based-Access-Control-Systems.pdf).

The BI resource semantics used by the paper is indeed established: worlds/resources have a partial composition and comparison structure, and implication is residual to composition. The manuscript correctly disclaims novelty for this algebraic machinery. [Pym, O'Hearn, and Yang, The Logic of Bunched Implications](https://www.cantab.net/users/david.pym/POY-resource-tcs.pdf).

Free-choice workflow resource-threshold work studies resource requirements under choice and concurrency and establishes nontrivial complexity and industrial relevance. State-tree supervisory control and communicating transaction processes already compile hierarchy/transaction policies into propositional guards and maximally permissive controlled behavior. These do not directly yield the paper's frozen quantitative escape row, but they make “hierarchical lifecycle plus guards plus maximal pruning” an unsafe novelty formulation. Sources: [Resource Thresholds of Free-Choice Workflow Nets](https://arxiv.org/abs/1802.08064), [Ramadge and Wonham, Supervisory Control of a Class of Discrete Event Processes](https://www.me.psu.edu/ray/me597DESandSymbolicDyn/ramadgeWonhamJan1987.pdf), and [Communicating Transaction Processes](https://citeseerx.ist.psu.edu/document?doi=bee6fa4df025152b7de366daf96d3e5478989401&repid=rep1&type=pdf).

**Effect on the blind attack map:** the core formal object is more evidently a specialization than the current manuscript admits in its comparison. Boundary I remains a clean characterization for a specified decentralized-checker class, but mathematically it is the greatest-corner test for equality of a down-set with its coordinate box. The raw nonclosure phenomenon behind Boundary II is established ternary conflict/propositional filtering. The potentially new result is narrower and more security-specific: deriving the exact frozen row from irreversible escape and proving the final-owner-support criterion for every serial promotion order under immediate prefix cleanup. That exact theorem survived this targeted search, but the manuscript has not isolated it sharply enough from the known semantic substrate.

### 4. Venue fit is sound; compliance is plausible

The official CSF 2027 call explicitly includes foundational security, formal models and properties, and principled security tools/applications, while warning that work without a clear security foundation risks desk rejection. It permits 12 pages of body excluding bibliography and marked appendices. The built paper has references beginning on PDF page 12, so its body appears to fit, although the final camera-ready layout still needs a mechanical page-boundary check. [Official CSF 2027 call for papers](https://www.ieee-security.org/TC/CSF2027/cfp.html).

## Closest-work comparison and novelty judgment

| Source/model | Same capability or claim | Material difference that may remain novel | Current manuscript gap |
|---|---|---|---|
| Configuration structures | Arbitrary permitted configuration families; higher-order/ternary conflict; propositional constraints | Security derivation from finite authority, escape, and lifecycle promotion | Missing closest citation and theorem-level mapping; promotion nonclosure is presented as more surprising than it is |
| Resource concurrent games / BI | Resource-sensitive concurrency and residual resource composition | Budget feasibility feeds back into which future branch sets may remain durable | No explicit encoding/separation argument against the closest resource-event model |
| Consumable credentials | Linear/global consumption and dynamically limited authority | Conditional advance commitments across mutually exclusive futures and later co-durability | Distinction asserted informally, not demonstrated with a separating trace/property |
| Supervisory control / state-tree guards | Maximal legal pruning and propositional guards over hierarchical behavior | Exact quantitative frozen row tied to escape and stable crash/retry binding | No reduction or theorem delta showing which result is not ordinary supervisor synthesis |
| Agent libOS | Fork/checkpoint, capability attenuation, reserve/consume one-shot authority | Safe sharing across exclusive alternatives may admit work conservative attenuation rejects | No direct baseline or measured availability benefit |
| Cordon / Commit-Time Authorization | Interposed commit/dispatch checks, lifecycle invalidation, external-effect protocol | Aggregate vector capacity over multiple co-durable futures | Adapter does not test mandatory mediation, refinement, or bypass resistance |

No opened primary source stated the exact combination “configuration-supported quantitative conditional promises + irreversible promotion row + iff final-owner support for all owner-group serial promotion orders.” That is positive but insufficient novelty evidence: this was a targeted attack, not a comprehensive systematic literature review, and two much closer formal sources are missing from the current paper.

## Updated reject case and decision

The strongest source-grounded reject case is now more precise: **the threat is real, but much of the claimed formal revelation is existing configuration/resource/supervisory semantics, while the genuinely lifecycle-specific theorem is narrow and the implementation does not enforce its assumptions.** In particular, the “all pairs but not the triple” example is classic ternary conflict, not evidence by itself that promotion creates a newly recognized policy-language requirement. The current paper may therefore offer an elegant security interpretation and two concise special-case lemmas without yet establishing a CSF-sized foundational advance. At the same time, Agent libOS, Cordon, and Commit-Time Authorization demonstrate that stronger real effect boundaries and evaluation protocols are possible; the Codex correspondence witness cannot substitute for them.

Evidence against rejection is also stronger after search. Official runtime documentation and several primary preprints validate the exact rollback/external-effect mismatch. None of the opened sources combines the paper's co-durable aggregate invariant with its promotion-order criterion. The simple principle—authority follows durable support, not copied state—remains memorable, and its availability-oriented distinction from conservative attenuation or escrow may be useful if the authors expose a real workload that requires advance guarantees.

## RQ readiness after external attack

- **RQ1 (security state/invariant): not submission-ready.** Problem relevance is externally supported; formal novelty is not yet discriminated from configuration structures, resource concurrency, and consumable credentials.
- **RQ2 (decentralized reservation boundary): mathematically answered in its narrow domain, but not yet contribution-ready.** The result needs a closest-formalism comparison and evidence that this checker class corresponds to an important decentralized implementation choice.
- **RQ3 (promotion/order boundary): promising but not submission-ready.** The exact serial-order theorem survived the targeted search, while the non-pairwise guard motivation did not. The theorem needs mechanization and a clearer delta from configuration structures and supervisor/guard synthesis.
- **RQ4 (runtime correspondence/security): not submission-ready.** Current primary systems show an appropriate enforcement and evaluation bar that the adapter does not meet.

## Ranked source-grounded findings and routing

1. **Major — novelty/framing:** add the configuration-structures and resource-tracking-concurrency comparisons; reduce the novelty claim around higher-order conflict; state the exact new security theorem and a separating trace/property. Route: **WRITE_GATE**, preceded by a broader `research-literature-novelty` search.
2. **Blocker — concrete security evidence:** the artifact does not establish complete mediation, truthful binding, or topology refinement on an actual runtime. Route: **EXPERIMENT_GATE** for a protected-boundary implementation and adversarial protocol; or consciously make the contribution purely formal and remove concrete-security implication.
3. **Major — baseline/evaluation:** compare conditional sharing with Agent libOS-style finite-use attenuation/escrow and with staged/commit-time enforcement; measure both rejected useful work and security outcomes. Route: **EXPERIMENT_GATE**.
4. **Major — formal assurance:** mechanize the two headline boundaries and connect the general paper theorem to the finite executable model. Route: **EXPERIMENT_GATE** plus proof exposition in **WRITE_GATE**.
5. **Minor — relevance framing:** cite official fork/checkpoint limits and precisely identify the smaller workload population requiring advance guarantees. Route: **WRITE_GATE**.

## Alternatives and decision

The strongest alternate explanation of the observed problem is that conservative capability attenuation, parent escrow, first-commit-wins, or staging already prevents duplicate effects, and that the proposed calculus mainly recovers concurrency/availability for a workload not shown to matter. The paper should embrace and test that contrast rather than imply prior mechanisms are simply unsafe.

The largest defensible claim after search is: **for lifecycle systems that must make finite-use advance promises to alternatives and may later retain, merge, or escape their effects, admissible co-durability—not copied branch state—is the correct authorization index; this yields exact limits on independent budgets and serial promotion.** A broader claim of discovering that rollback does not undo effects, that arbitrary configuration families exceed pairwise conflict, or that policy can be compiled into guards is not defensible.

## Tree/search updates

- Closed as supported: venue fit; native runtime forking; checkpoint/external-effect mismatch; reality of stale/escaped side effects.
- Narrowed but open: uniqueness of the co-durability invariant and exact promotion-order theorem.
- Opened as high priority: configuration-structure encoding; resource-concurrent-game comparison; Agent libOS conservative baseline; real complete-mediation/refinement experiment.
- Excluded from evidence: secondary summaries, search snippets, GitHub issue anecdotes, and sources opened only at abstract/metadata level.

## Project-memory updates

No canonical project memory was read or changed. Candidate durable update: the closest missing theory reference is configuration structures, especially their explicit ternary-conflict/propositional-theory example; the closest practical baseline is Agent libOS's fork/checkpoint plus one-shot reserve/consume discipline.

## Completion assessment and uncertainty

The mandatory targeted external attack is complete and source-grounded. It found no exact same-claim paper, but it did find prior theory that materially narrows two novelty arguments and current systems that materially raise the implementation bar. Confidence is high about problem reality and current adapter limitations, medium about the narrowed novelty claim, and deliberately low about exhaustive priority because a full systematic novelty study was outside this node.

## Next node

Reread the entire manuscript, bibliography, and compiled presentation from page one without consulting author-intent or cycle artifacts. Re-score every finding against the primary-source comparison before opening `docs/idea-story.md` or evaluating the actual cycle.
