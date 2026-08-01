# Crab / ACRFence closest-work audit

Audit date: 2026-08-01 (America/Vancouver)
Audited repository: `agent-check-restore-safety`, commit `84671890dcf98a47fce67c15a11714c59fd02075` on `main`
Scope: claim-level, full-text, read-only novelty attack against the current paper, `docs/idea-story.md`, `docs/background-related-work.md`, the Lean development, and Boundaries I--II. This report is the only repository file created by the audit.

## 1. Executive verdict

Both papers are real, correctly titled, and highly relevant 2026 primary sources.

- **Crab is a setting and systems-motivation collision, not a theorem collision.** It already owns the phrase and claim family around an **agent--OS semantic gap**, incomplete chat/filesystem recovery, efficient full sandbox C/R, proactive rollback, speculative fork, and RL rollout branching. It does **not** model irreversible effects outside the sandbox, bounded authority, branch-conditioned reservations, co-durable outcomes, merge authorization, or conditional-to-durable promotion.
- **ACRFence is a direct problem/framing collision.** It already identifies **semantic rollback attacks**, names **Action Replay** and **Authority Resurrection**, demonstrates them with Claude Code plus MCP fixtures, proposes an irreversible-effect log, and enforces a prose **replay-or-fork** rule. The current project cannot claim discovery of the agent C/R external-effect problem, resurrected one-use credentials, nondeterministic post-restore request drift, or effect-log replay/fork mitigation.
- **Neither paper contains the current paper's semantic object or headline results.** Neither defines authority over a downward-closed family of co-durable branch sets; neither has a correlated residual admission profile; neither states the Cartesian-factorization iff of Boundary I; neither has exact authority promotion, support-triggered cleanup, or the final-owner-support iff of Boundary II; neither distinguishes choice/parallel Fork, replacing/live Restore, and Merge through checked lineage projections.
- **The surviving contribution is therefore not “safe checkpoint/restore for agents.”** It is: bounded authorization for intentionally history-transforming executions, where fork/restore/merge change which branch commitments may become durable together, plus exact runtime tests for decentralizing reservation and serializing irreversible promotion.
- **The broad novelty story is already taken; the theorem/interface story survives but is fragile.** Boundary I is untouched by these two papers. Boundary II is also untouched by them, but the separate formal closest-work audit shows that its generic concurrency shape is established and only the final-support closed form is potentially new. The Lean development currently mechanizes the closed lifecycle and conditional trace theorem, **not Boundary I or Boundary II**.

### Reject-risk verdict

**Current risk: HIGH / likely weak reject unless reframed and the headline boundaries are mechanized.** A reviewer can currently summarize the paper unfairly but plausibly as “formal ACRFence plus capability accounting,” because ACRFence is only dispatched in two sentences in Related Work and is absent from the introduction and threat-model framing. Crab can likewise be used to reject any broad claim that agents newly reveal heterogeneous or non-chat checkpoint state.

These two papers do **not** kill the paper. They kill the broad problem novelty and force the paper to win on the following narrower package:

1. co-durable-future authority rather than local recovery correctness;
2. conditional reservations rather than only post-effect deduplication;
3. exact topology-sensitive admission across choice, parallelism, live/replace restore, and merge;
4. Boundary I's residual product-factorization criterion; and
5. Boundary II's authority-specific final-support certificate, presented as a specialization of established conditional independence rather than a new concurrency theory.

Without that refocus, reject risk is about **8/10**. With explicit closest-work separation, a direct ACRFence counterexample, honest theorem scoping, and Lean proofs of both iff results, the risk attributable to these two papers falls to roughly **4--5/10**; the remaining risk is the generic-resource/concurrency closest-work issue already documented elsewhere in Step 0006.

## 2. Source integrity and search boundary

### 2.1 Verified primary sources

| Work | Primary metadata | Verified authors/status | Full-text bytes inspected | SHA-256 |
|---|---|---|---:|---|
| Crab | [arXiv:2604.28138](https://arxiv.org/abs/2604.28138), [v1 PDF](https://arxiv.org/pdf/2604.28138v1), [v1 TeX source](https://arxiv.org/e-print/2604.28138v1) | Tianyuan Wu, Chaokun Chang, Lunxi Cao, Wei Gao, Wei Wang; submitted 2026-04-30 17:20:19 UTC; cs.OS with cs.AI cross-list; 15 pages; v1 only on the audited date. Wei Wang's [author publication page](https://www.cse.ust.hk/~weiwa/publications.html) independently lists it as an April 2026 preprint. | PDF 1,496,161 bytes; source archive 813,506 bytes | PDF `faa2188190cc191240596a92487b86df4fda75e345da8b3b41542773c0ab23c0`; source `6b9b82ff70df7fc6fe5330103477298c289f1a6a9eed77b0e47420aa2eb5010e` |
| ACRFence | [arXiv:2603.20625](https://arxiv.org/abs/2603.20625), [v1 PDF](https://arxiv.org/pdf/2603.20625v1), [v1 TeX source](https://arxiv.org/e-print/2603.20625v1), [author-hosted slides](https://www.yunwei37.com/presentation/acr-fence/) | Yusheng Zheng, Yiwei Yang, Wei Zhang, Andi Quinn; submitted 2026-03-21 03:39:36 UTC; cs.CR; journal reference “CoDAIM workshop 2026”; 4 pages; v1 only on the audited date. | PDF 463,072 bytes; source archive 110,693 bytes | PDF `5b88ebb1f9dc1cb136c2e8b282a5b9d31122dc172ecd9c1893f4a5b578e86263`; source `f0d4d709b3aea8526da02549c0ba7fe27450a0a72e902fe9b461e22552ee037a` |

The repository copies `reference/closest-work/crab-agent-sandbox.pdf` and `reference/closest-work/acrfence.pdf` match the freshly downloaded arXiv v1 PDFs byte-for-byte at the two PDF hashes above. No replacement or modification was made.

The arXiv pages and source archives do not link an official code artifact for either paper. Exact-title and arXiv-ID GitHub searches found no author-owned implementation repository on 2026-08-01. This matters differently for the two works: ACRFence explicitly says its mitigation was not implemented (PDF p. 3, §6), while Crab describes and evaluates a system but supplies no paper-linked public artifact in the inspected primary sources.

### 2.2 Audit snapshot of the current project

| Artifact | SHA-256 |
|---|---|
| `docs/paper/main.pdf` (13 pages, built 2026-08-01 15:04 PDT) | `96c854514b701c9ee5c65b74070afe583ff34e6644d6b95056f08aca1a873a64` |
| `docs/idea-story.md` | `ced9041c01f049bcb0170127a7a19cef5450a37e15c54beab40b9decb284461e` |
| `docs/background-related-work.md` | `01543d386d466cc2f2cc8454621f3ce685335f3c1f149a5e3a4d81fd831379d5` |
| `lean/README.md` | `d4b787cf3977241189f164996fd55a9f32a3bbb7afceb131639a3b59e7d6a141` |
| `lean/AuthorityContinuity/Audit.lean` | `99807921f8a9f4267b01b268785c4f5018e038a05ad85a4b07c7588e8d733d2b` |

### 2.3 Declared comparison questions

The audit tested six explicit same-claim threats:

1. Does either paper already own the agent C/R semantic-gap claim?
2. Does either paper already model a protected effect lifecycle or durable-before-dispatch boundary?
3. Does either paper already own semantic rollback and rollback-based authority reuse attacks?
4. Does either paper define authority continuity over forked/co-durable futures?
5. Does either paper formalize choice/parallel fork, replacing/live restore, or merge as authorization events?
6. Does either paper give atomic authority promotion, exact repair, or serialization conditions comparable to Boundaries I--II?

Searches covered arXiv metadata/PDF/source, author-facing pages, exact titles, arXiv IDs, and exact system names on GitHub. Secondary summaries were not used for novelty judgments.

## 3. Full-text claim card: Crab

### 3.1 What Crab actually claims

Crab's scientific target is **recovery fidelity and C/R efficiency for sandbox-local OS state**.

- The abstract and §1 say an agent's effective state spans conversation plus filesystem, process, and runtime artifacts, while existing application recovery misses OS-side state and full per-turn C/R is too costly ([PDF v1](https://arxiv.org/pdf/2604.28138v1), p. 1, Abstract and §1).
- It names the missing cross-layer information the **agent--OS semantic gap**: frameworks see tool calls but not concrete OS effects; the OS sees effects but not turn semantics (p. 1, §1; p. 4, §3.3).
- Its three requirements are recovery correctness, low exposed overhead, and scalability under dense co-location (pp. 1--2, §1; pp. 4--5, §4).
- Its design is a host-side Coordinator, eBPF Inspector, and C/R Engine. It aligns checkpoints to turn boundaries, classifies net filesystem/process changes, overlaps dumps with LLM wait time, and schedules C/R at host scope (pp. 2, 5--8, §§1, 4--5).
- It reports 100% benchmark recovery correctness, up to 87% skipped checkpoint work, and at most 1.9% overhead relative to fault-free checkpoint-free execution under its experiment (pp. 9--11, §§7.1--7.3).
- It explicitly supports proactive rollback, speculative fork/discard-or-commit, spot migration, and tree-based RL rollout reuse (pp. 12--13, §7.5).

The paper has **no formal Definitions, Lemmas, Theorems, or security invariant**. Its “correctness” is benchmark-level reconstruction of the sandbox state needed for task success, not authorization integrity.

### 3.2 What Crab does around replay and atomicity

Crab contains three mechanisms that could be confused with the current paper but are materially different:

1. **Completion gating.** The Coordinator does not release the next LLM response until the preceding checkpoint is durable (p. 6, §5.1). This makes a recovery point complete before later turns, but does not charge or authorize a protected external effect.
2. **Transactional checkpoint publication.** The Manager publishes a versioned manifest only after partial filesystem/process artifacts are assembled successfully (pp. 7--8, §5.3). This is atomicity of checkpoint metadata, not atomic promotion from conditional authority to durable consumption.
3. **Reliable sandbox command replay / fast-forward.** For an external agent controlling a sandbox, Crab logs an outstanding sandbox command and may reissue it after restore; for an agent inside the sandbox, it returns cached LLM responses until logical progress catches up (p. 8, §6). This prevents inconsistency between restored local state and agent progress. It does not define a stable protected effect ID for remote services, an uncertain external-success phase, a use-limited grant, or aggregate deduplication across physical attempts.

Crab also uses the verb “promote” for moving an urgent checkpoint job to a high-priority queue (p. 6, §5.1). This has no connection to the current paper's conditional-to-durable authority promotion.

### 3.3 What Crab does not cover

Full-text and source inspection found none of the following:

- an external irreversible-effect log or receipt model;
- a payment/message/API sink outside the sandbox recovery domain;
- consumable authority, one-use approvals, quotas, revocation, or authorization epochs;
- conditional reservations or a distinction between branch-conditional and globally durable authority demand;
- a family of outcomes that may become durable together;
- choice versus parallel fork as different authority contracts;
- replacing versus live restore;
- merge or authorization of merged outcomes;
- stable effect binding through prepared/inflight/uncertain/settled phases;
- an atomic authority Prepare operation; or
- a serialization theorem.

### 3.4 Claim impact on this project

Crab preempts the following broad claims:

- that conversation/file checkpoints omit important agent execution state;
- that agents require cross-layer C/R spanning chat and OS state;
- that efficient agent sandbox C/R is useful for fault recovery, proactive rollback, speculative execution, and RL branching; and
- that turn-level OS-effect sparsity can make checkpointing efficient.

It does **not** preempt the narrower statement that a complete sandbox checkpoint can still omit **authority and external-effect history outside the sandbox**, nor the claim that intentional co-durability changes quantitative authorization.

## 4. Full-text claim card: ACRFence

### 4.1 What ACRFence actually claims

ACRFence's target is almost exactly the broad problem layer that the current project originally used as motivation.

- The abstract and §1 say post-restore LLM resynthesis can change UUIDs/arguments, causing servers to treat a logical retry as a new irreversible request. It names this a **semantic rollback attack** ([PDF v1](https://arxiv.org/pdf/2603.20625v1), p. 1, Abstract and §1).
- §2 states two prose invariants: irreversible effects must not be replayed across restore, and consumed credentials must remain consumed. It considers both crash-induced restore and deliberate rollback abuse (p. 2, §2).
- §3 names and validates two attack classes (p. 2, §3):
  - **Action Replay:** a post-success crash and restore causes a second request with a fresh reference; 10/10 C/R trials duplicate the commit, versus 0/10 without C/R.
  - **Authority Resurrection:** a one-use approval reappears after rewind and is redirected to another target; 2/2 stateless-validation attempts succeed, while a stateful consumption list rejects them.
- §4 proposes an MCP-proxy-like effect log that records thread/branch IDs, tool name, arguments, and environment context. An analyzer LLM classifies the next post-restore call as semantically equivalent (return cached response), semantically different (block and require an explicit fork/new branch ID), or reuse of a consumed credential (warn/block before attempt) (pp. 2--3, §4).
- §6 explicitly says the experiments validate the attacks but **do not implement ACRFence**; analyzer accuracy, adversarial evasion, overhead, and scale are future work (p. 3, §6).

Like Crab, ACRFence contains **no formal Definition, Lemma, Theorem, proof object, or algorithm with a proved security property**. The “invariants” in §2 are prose requirements.

### 4.2 Exact overlap with the current project

ACRFence directly covers these current-paper premises and litmus ideas:

- reconstructable checkpoint state and irreversible external state have different rollback domains;
- a successful call can be replayed after crash/restore with a different operation ID;
- one-use authority can reappear in an old checkpoint;
- an attacker may deliberately induce restore after a durable effect;
- a branch ID and effect log are relevant durable context; and
- an effect gate/proxy is a natural enforcement location.

The current paper's `docs/evaluation.md` litmus L1 (reserve, dispatch, restore old values, repeat with a fresh operation ID) is a formalized variant of ACRFence's Action Replay. Terminal-ID and epoch non-resurrection likewise formalize the invariant behind Authority Resurrection. These are valuable formalizations, but they are no longer new attacks.

### 4.3 Where ACRFence stops

ACRFence is post-effect and pairwise: it compares a new call with a previously logged effect. It does not model an **advance promise** that a branch may later dispatch an effect without acquiring more authority. It also does not answer how several intentional branches share a bounded grant before selection.

Its “fork” means “declare semantic divergence with a new branch identifier.” The paper does not specify:

- where new authority for that branch comes from;
- whether old and new branches may both become durable;
- whether the old continuation loses commit eligibility;
- whether a one-use grant is split, shared conditionally, or retained by a parent;
- how merge changes the two branches' joint durability;
- how branch-local claims are transported through restore/fork; or
- how a fixed batch is atomically sealed or safely serialized.

ACRFence separately checks obvious reuse of a consumed credential, so it should not be caricatured as simply allowing arbitrary reuse after fork. The precise gap is broader: **a branch identifier is not an authorization derivation**, and the paper has no invariant tying every new divergent branch to fresh or conditionally shareable authority. Aggregate approvals, quotas, and multiple differently bound actions can violate a single grant even when no identical credential token is replayed.

### 4.4 Claim impact on this project

ACRFence fully preempts novelty claims for:

- “semantic rollback attack” as a new class;
- Action Replay and Authority Resurrection as newly identified attacks;
- post-restore request nondeterminism defeating ordinary idempotency keys;
- irreversible effect logging plus semantic replay-versus-fork as a new mitigation concept; and
- a framework survey showing duplicated tool effects around resume/rewind.

It does not preempt:

- co-durable-future authority;
- conditional reservation and correlated residuals;
- topology-sensitive grant conservation;
- choice/parallel and replace/live distinctions;
- merge admission;
- exact promotion repair;
- product factorization; or
- order-independent promotion iff final support.

## 5. Direct comparison matrix

“Covered” below means substantively present after removing paper-specific names, not merely mentioned.

| Dimension | Crab | ACRFence | Current paper / Lean | Novelty consequence |
|---|---|---|---|---|
| Agent C/R semantic gap | **Covered for chat/framework state versus OS-visible sandbox state.** Abstract, §1 p. 1; §3.3 p. 4. | **Covered for local checkpoint state versus irreversible external effects and nondeterministic retry.** Abstract/§1 p. 1. | `docs/paper/sections/lifecycle.tex` separates reconstructable computation, lifecycle, authorization, and external history; paper pp. 2--3. | Broad “checkpoints miss agent state” novelty is gone. The surviving gap must be specifically the missing correlated authority state over co-durable outcomes. |
| Protected effect phase | No protected external-effect lifecycle. Completion gate and checkpoint manifest lifecycle are C/R mechanisms (§5 pp. 6--8). | Logs irreversible calls and distinguishes cached replay, divergent call, and consumed credential (§4 pp. 2--3), but no prepared/inflight/uncertain/settled state or durable-before-attempt theorem. | Paper equations/rules (13)--(20), pp. 5--6; Lean `TicketPhase` and `TicketStep`, `Lifecycle.lean:40--70, 593--637`; `step_attempt_safe`; stable binding trace lift. | Not preempted by these two, but the generic output-commit/idempotency foundations mean it should remain supporting machinery. The distinctive claim is its coupling to branch-conditioned authority. |
| Rollback attack | Only recovery correctness; no adversarial authorization threat model. | **Directly covered and named.** §2 threat model and §3 attacks, p. 2. | Current threat model permits crash, old checkpoint, fresh arguments; L1 and terminal/epoch monotonicity cover the same attack family. | Treat ACRFence as the attack source and litmus baseline. Do not claim attack discovery. |
| Monotone consumed state | No authorization ledger. | **Covered at prose/system level:** consumed credentials stay consumed; stateful validation blocks reuse (§2--§3 p. 2). | Durable/terminal claim partition, closed epochs, tickets/receipts; Lean `trace_terminal_mono`, `trace_epoch_mono`. | Non-rollbackable consumption is established premise. Formal closure is useful but not the paper's novelty center. |
| Authority continuity over co-durable futures | None. | None. Only per-effect replay and consumed-token reuse. | Paper Definition 2, p. 3: for every allowed durability configuration, durable load plus its conditional branch load fits capacity. Lean `Model.lean:82--90` defines `AC`. | Survives this pair. This is the semantic center that must replace “semantic rollback” in framing. |
| Advance branch-local guarantee | None. | None; checks calls on restore path after prior effect exists. | Conditional commitment Definition 1, p. 3; Reserve/headroom/residual results. | Survives. This is the cleanest distinction from ACRFence. |
| Fork | Sandbox snapshot fork for speculation/RL; discard or commit a fork (§7.5 pp. 12--13). No authority semantics. | Explicit new branch ID for semantically different post-restore action (§4 p. 2). No resource derivation or co-durability. | Choice and parallel Fork have different computed contracts and checked claim transfer; Lean `Topology.lean:18--60, 373--394, 734--758`. | “Agents fork” and “fork helps RL” are prior. Choice-vs-parallel authorization and fiber-conserving transfer survive. |
| Restore | Restores sandbox OS state; proactive rollback and recovery (§§5--7). | Rewind/restore is the attack trigger; one coarse “replay or fork” policy. | Replacing Restore closes old lineage; live Restore retains both and can be co-durable. Lean `Topology.lean:396--417, 760--784`. | The replace/live authorization distinction survives and directly exposes why ACRFence's branch-ID rule is incomplete. |
| Merge | Not modeled. | Not modeled. | Explicit Merge descriptor, transfer, target branch epochs, simulation projection or direct target admission; Lean `Merge.lean:18--45, 114--149, 223--247, 345--395`. | Strong surviving interface contribution, though configuration/projection mathematics has broader prior art. |
| Atomic publication / sealing | Transactional publication of a complete checkpoint manifest (§5.3 pp. 7--8). | No atomic batch operation; mitigation is per restored call. | `Prepare` atomically moves claims to durable, installs exact repair/cleanup, creates stable tickets; paper §IV-B pp. 5--6; Lean `prepareState`, `Lifecycle.lean:375--406`. | Crab's transactional checkpoint publication is not prior art for authority promotion. The word “atomic” must always say what is atomically installed. |
| Promotion representation | No. High-priority queue “promotion” is unrelated. | No. | Proposition 2 and Lemma 3, paper p. 7: choice/parallel non-closure and one exact frozen threshold row. | Survives this pair; generic threshold/configuration machinery is not new. |
| Boundary I | None. | None. | Theorem 1, p. 7: residual equals product of local headroom intervals iff the all-headrooms corner satisfies every configuration slack inequality. | Completely untouched by these two; still closest-work-sensitive because the proof is a short downset/box argument. |
| Boundary II | None. | None. | Theorem 2, p. 8: every owner-group order remains enabled and reaches the atomic result iff every promoted owner has final repaired support. | Completely untouched by these two; still at moderate/high global novelty risk because generic enabledness preservation, commutation, disruption, and asynchronous cubes are established. |
| Trace theorem | No authorization trace theorem. | No theorem and no ACRFence implementation (§6 p. 3). | Theorem 3 and Corollary 1, p. 8; Lean `trace_preserves_wf_ac`, `effect_coverage`, `concrete_trace_authority_safety`. | Survives, but is explicitly conditional on mediation, simulation, demand bounds, and truthful-enough sinks. |
| Evaluation | Sandbox recovery/performance, 100 tasks per setting, proactive rollback, speculation, spot, RL (§7 pp. 8--13). | Attack PoC: 10 replay trials and 2 authority-resurrection attempts; no mitigation implementation (§§3,6 pp. 2--3). | Bounded model, Lean abstract lifecycle, fixed Codex adapter; no complete mediation. | Crab is a workload/system precedent, not a numerical baseline. ACRFence's decision rule should be modeled in the litmus suite; there is no official implementation to benchmark fairly. |

## 6. Claim-by-claim novelty attack

Risk here is **global same-claim risk**, informed by these papers plus the project's existing related-work audit.

| Plain claim, with project terminology removed | Status after audit | Risk | Required paper action |
|---|---|---:|---|
| Agent checkpoints omit state needed for correct recovery. | **Preempted by Crab.** | High | Cite Crab in the introduction/lifecycle motivation and narrow the missing state to external authority plus durable-support correlation. |
| Agent restore cannot undo external effects and can regenerate a different request. | **Preempted by ACRFence and classic output-commit work.** | High | Present as an established attack premise, not discovery. |
| Restore can replay an action or resurrect one-use authority. | **Preempted by ACRFence.** | High | Attribute the attack names; use them as litmus tests. |
| An irreversible-effect log and replay-versus-fork policy mitigate semantic rollback. | **Preempted by ACRFence.** | High | Do not claim the effect gate/log shape as novel; show where it is insufficient for aggregate authority. |
| Security consumption, revocation, and uncertain effects must outlive rollbackable values. | Established premise; ACRFence covers consumption, while Memoir/ROTE/LCM and output-commit literature cover the general principle. | High | Keep as trusted-state architecture, not contribution headline. |
| A full sandbox checkpoint still cannot roll back an external API or authorization issuer. | Not contradicted by Crab; indeed it is outside Crab's target. | Low as a factual distinction, high as a novelty claim | State as scope separation, not “our discovery.” |
| A bounded grant must fund every set of branch outcomes that may still become durable together. | Not in Crab or ACRFence. Generic resource/configuration semantics are foundations, but the agent lifecycle specialization remains plausible. | Medium | Make this the opening problem statement and define co-durability before mentioning retry details. |
| Exclusive alternatives can conditionally share an advance authorization promise; parallel/co-durable branches cannot. | Not in the audited pair. Parent escrow remains a safe alternative for pure candidates. | Medium | State exactly that the result matters only when branches receive advance guarantees or lifecycle actions admit batches. |
| Restoring while retaining the old continuation is authorization-wise parallel, whereas replacing restore is renaming/choice. | Not in the audited pair. | Low/medium | Use as the direct separating example against ACRFence's coarse restore/fork rule. |
| Merge is an authorization event because it can turn exclusive claims into co-durable claims. | Not in the audited pair. Transaction/configuration prior art still applies. | Medium | Keep as an interface consequence and require explicit projection or target admission. |
| The exact Reserve behavior is a correlated residual; independent branch budgets are exact iff the residual is rectangular. | Not in the audited pair; no equivalent claim found in the current literature map. | Medium | Keep as Boundary I. Avoid claiming residuation or rectangular downsets themselves as new. Mechanize the iff. |
| Conditional-to-durable promotion can require higher-order policy beyond choice/parallel syntax. | Not in the pair, but arbitrary configuration families and threshold guards are established. | Medium/high | Keep as the authority-specific non-closure witness and construction, not a new policy language. |
| Every owner-group promotion order works exactly when all promoted owners survive final support cleanup. | Not in the pair; exact closed form not found elsewhere, but generic conditional independence/disabling is established. | Medium/high | Present Boundary II as an authority-specific weakest precondition/certificate; cite generic independence. Mechanize it over the real `PrepareOK` transition. |
| A closed lifecycle preserves authority and every physical attempt is bounded by a durable uniquely bound claim. | Not in Crab/ACRFence. Generic linear authorization/output commit cover components. | Medium | Keep as integration theorem. Do not imply current Codex hooks prove complete mediation. |
| C/R is useful for speculative agents and RL rollout branching. | **Preempted as a workload/system claim by Crab.** | High | Cite Crab in the RL subsection; claim only conditional applicability to authority-bearing rollouts. |

## 7. What is still exclusive in the audited pair

“Exclusive” here means **absent from Crab and ACRFence**, not globally unprecedented.

### 7.1 Semantic/interface contributions that survive

1. **Co-durable authority state.** The state is not one current branch plus a consumed-effect log. It is `(G,D,Q,Phi)` where `Q_b` is an advance conditional promise and `Phi` identifies all branch sets that may contribute to one durable result. Current paper Definition 1 and Definition 2, PDF p. 3.
2. **Four topology meanings, not one clone operation.** Choice Fork, parallel Fork, replacing Restore, and live Restore compute different target configuration families. Merge is separate and needs a projection simulation or direct admission. Paper §IV-A, pp. 4--5; Lean `Topology.lean` and `Merge.lean`.
3. **Conservative claim transfer.** The target's conditional load must be dominated by a projected source configuration, with exact domain/provenance/grant agreement and coordinatewise fiber conservation. Lean `Transfer.topology_fiber_conservation`; audited in `Audit.lean`.
4. **Prepared authority before emission.** Exact Prepare changes claim status, freezes the repair, cleans unsupported owners, and installs stable tickets in one durable step. Dispatch emits only from a prepared ticket; crash makes inflight uncertain; retry preserves `(effect_id, claim_id)`; settlement records a receipt. Crab has C/R completion gates and ACRFence has a post-effect log, but neither couples this phase machine to co-durable authority.
5. **Merge as authority re-admission.** Neither closest paper has merge. The current direct/simulation Merge split is a concrete checked interface rather than a prose warning.

### 7.2 Theorem contributions that survive

1. **Boundary I / exact product factorization.** Theorem 1, current PDF p. 7, is absent from both papers. It says exactly when a correlated batch-admission set can be implemented as independent branch-local budget capabilities without sacrificing joint soundness or singleton completeness.
2. **Boundary II / final support iff universal owner-order execution.** Theorem 2, current PDF p. 8, is absent from both papers. Its surviving novelty is the one-final-policy support certificate for this authority-promotion calculus, not universal serializability as a general concept.
3. **Closed-lifecycle preservation.** Theorem 3 and Corollary 1, p. 8, combine topology, promotion, crash/retry, epochs, and protected outcomes. Neither closest paper has any theorem.

### 7.3 Claims that are only supporting, even though the two papers do not state them

- non-rollbackable ledgers;
- stable operation IDs and deduplicated retry;
- generic guarded-policy filtering;
- maximally permissive one-step knowledge intersection;
- arbitrary downward-closed configuration families;
- atomic commit/publication as a general pattern; and
- generic transition commutation/serializability.

These remain prior-art-sensitive through the older foundations already recorded in `docs/background-related-work.md` and `formal-closest-map/report.md`.

## 8. Boundary I and Boundary II under the new closest work

### 8.1 Boundary I

**No overlap with Crab.** Crab chooses checkpoint granularity from observed OS effects. It has neither bounded branch authority nor an admission region. Its checkpoint sparsity metric is unrelated to factorization of a correlated residual.

**No overlap with ACRFence.** ACRFence makes a three-way decision about one post-restore call relative to one logged effect. It has no batch proposal language, branch-local budget, singleton completeness criterion, or product composition.

**Surviving exact claim.** In the fixed-topology Reserve-only fragment, the current paper first derives branch headroom and the correlated residual, then proves:

\[
\mathcal R_\Sigma=\prod_b[0,H_\Sigma(b)]
\quad\text{iff the all-headrooms corner is safe in every }C\in\Phi.
\]

Theorem 1 is precise and architecturally meaningful: it identifies when noncommunicating branch-local capability checkers are exact. Its proof is short and its mathematical core is a downward-closed set versus its projection box, so the paper should not sell it as new convex/downset mathematics. The novelty claim is the **action-class compilation boundary for branch-conditioned authority**.

**Current evidence gap.** The current PDF and `lean/README.md` explicitly say Boundary I is not mechanized. The Python explorer exhaustively checks 730 bounded source states, but that is not a proof. Since ACRFence can make the paper look like an incremental formalization, kernel-checking Boundary I would materially strengthen the defense that the contribution is a theorem/interface result rather than a renamed attack.

### 8.2 Boundary II

**No overlap with Crab.** Crab's “transactional” operation is checkpoint-manifest publication and its “promotion” is queue priority. There are no conditionally supported claims, eager owner cleanup, effect batches, or scheduling theorem.

**No overlap with ACRFence.** ACRFence checks calls one at a time and has no atomic multi-owner seal, prefix repair, cleanup, or order comparison.

**Surviving exact claim.** For a fixed atomically valid batch, exact prefix repair, immediate deterministic cleanup, and no interleaving, every source-fixed owner-group permutation stays enabled and reaches the same denotational authority result as atomic promotion iff every promoted owner occurs in some final repaired configuration (Theorem 2, current PDF p. 8).

**Remaining global prior-work risk.** Step 0006's formal closest map shows that the left side is standard local transition independence/full asynchronous-cube structure, and support-triggered cleanup is an instance of established disruption/disabling semantics. The current theorem survives only as the authority-specific derivation of a complete final-state predicate and equality with the atomic seal. It should be framed as:

> For cleanup-aware conditional-to-durable authority promotion, final repaired support is a necessary-and-sufficient one-shot certificate for every owner serialization and atomic-seal refinement.

It should not be framed as a new theory of concurrency, commutation, conflict, or serializability.

**Current evidence gap.** Boundary II is also absent from Lean. `Lifecycle.lean` already defines the real `PrepareOK`, `prepareState`, exact repair, and deterministic cleanup, so a mechanization should quantify actual source-fixed owner permutations and prove enabledness plus `.auth` equality with the atomic target. A bespoke abstract checker that defines serializability in terms of final support would not close the novelty/evidence gap.

## 9. Lean model audit against Crab and ACRFence

### 9.1 What Lean already establishes beyond the two papers

The Lean development is materially stronger than either closest paper at the formal level:

- `Model.lean:28--90` defines a finite typed claim partition, allowed durability configurations, and semantic authority continuity.
- `Lifecycle.lean:40--119` separates branch/grant epoch state, one-shot tickets/receipts, unique operation-to-claim binding, and support well-formedness.
- `Lifecycle.lean:375--427` defines atomic `prepareState` and `PrepareOK`; `prepare_preserves_wf_ac` derives target WF and AC rather than assuming them.
- `Lifecycle.lean:593--637` defines `attempt`, `prepared/inflight/uncertain`, crash, retry, and settle.
- `Topology.lean:373--417` proves exact membership characterizations for choice/parallel Fork and replacing/live Restore.
- `Topology.lean:600--623` derives target authority continuity through coordinatewise transfer/fiber conservation.
- `Merge.lean:223--247` exposes simulation admission separately from direct target-AC admission, and `Merge.lean:345--395` proves both safe.
- `Step.lean` gives one closed lifecycle relation and preservation theorem.
- `Trace.lean:39--92, 176--210, 219--316` proves trace preservation, stable final binding for attempts, effect coverage, and conditional concrete trace safety.

Crab has no authorization invariant; ACRFence has no formal semantics or implementation. Thus the mechanized lifecycle is a genuine separation from both.

### 9.2 What Lean does not establish

The paper and report must not let the strength of the lifecycle mechanization leak into unsupported statements about the headline theorems:

- `lean/README.md` explicitly excludes Boundary I and Boundary II.
- The Lean model does not prove natural-language/tool-argument equivalence, which is ACRFence's analyzer problem.
- It assumes a fixed finite identifier type; “fresh” fragments are preallocated and source-`unissued`.
- It does not prove that today's Codex/Claude hooks completely mediate protected effects.
- It does not prove a sink is exactly-once or truthful; aggregate actual outcome is a premise.
- It does not prove a workspace merge implies the supplied authorization projection.

The correct comparison is therefore:

| Property | Crab | ACRFence | Lean status |
|---|---|---|---|
| Sandbox recovery fidelity | Implemented/evaluated | Uses conversation-level restore | Not modeled |
| Semantic argument equivalence | Not modeled | Proposed analyzer LLM, not implemented | Assumed in typed binding/policy; not proved |
| Consumed authority survives restore | Not modeled | Prose invariant + stateful-validation experiment | Mechanized terminal/epoch monotonicity in the abstract LTS |
| Durable before protected attempt | Not modeled | Effect log around irreversible calls, no formal phase guarantee | Mechanized under lifecycle WF and `PrepareOK` |
| Stable retry binding | Reliable local command reissue, no protected external ID theorem | Semantic comparison may return cached response | Mechanized `(e,c)` preservation and aggregate bound |
| Fork/restore authority topology | None | New branch ID only | Mechanized choice/parallel and replace/live targets |
| Merge authority | None | None | Mechanized explicit simulation/direct admission |
| Boundary I | None | None | Paper proof + bounded Python only |
| Boundary II | None | None | Paper proof + bounded Python only |

## 10. Audit of canonical story and related work

### 10.1 `docs/idea-story.md`

The story already contains the right core differentiation at lines 7--27: the stakes exceed duplicate RPCs; fork semantics depend on which descendants may become durable together; replacing restore differs from a still-live old continuation; merge changes co-durability.

It also correctly demotes ACRFence at line 41 to motivation/litmus evidence and excludes analyzer-LLM effect matching from the trusted core.

However, three parts are now unsafe or stale:

1. Lines 7--9 can still read as discovery of the external-effect/one-use-approval rollback problem. They need explicit attribution to ACRFence and Crab before introducing the co-durability gap.
2. The initial RQs at lines 49--52 promise temporal protocols, delegation confinement, obligations, latency, and a broader monitor than the current paper proves. They are not aligned with `docs/evaluation.md` or the 13-page paper.
3. The ambitious claim at line 45 says the rules cover delegation and can be enforced without serializing exploration. The current paper's real contribution is narrower: natural-number-vector authority, typed claims, checked topology, and conditional deployment assumptions. Parent escrow is a safe alternative for pure candidates.

### 10.2 `docs/background-related-work.md`

The document has already recorded the correct high-level distinctions:

- Crab targets agent sandbox recovery fidelity and efficiency, not escaped external authority (line 63).
- ACRFence identifies replay and resurrection, while “replay or fork” is not a complete authorization rule (lines 77--85).
- The final novelty table demotes non-rollbackable consumption and “replay or fork” while retaining co-durable authority, rectangularity, and final support (lines 194--216 in the audited file).

The weakness is evidentiary granularity. The Crab and ACRFence treatments are only one or two sentences and do not expose the most dangerous overlaps:

- Crab's explicit RL/fork/proactive-rollback evaluation;
- Crab's completion gate, transactional checkpoint publication, and fast-forward/reissue mechanisms;
- ACRFence's two invariants and attack models;
- ACRFence's 10/10 and 2/2 attack results;
- ACRFence's explicit lack of an implementation; and
- the exact counterexample showing why a new branch ID does not derive new aggregate authority.

This report supplies that missing evidence but does not update the canonical document by instruction.

### 10.3 Current paper

The current title and abstract are substantially safer than the original story because they lead with authority continuity, conditional commitments, residuals, and exact boundaries rather than “semantic rollback.” The introduction's first example is also co-durability-specific.

The remaining problem is citation placement. Crab and ACRFence appear only in Related Work (current PDF pp. 11--12). A reviewer sees several pages of heterogeneous-state, post-restore nondeterminism, external effects, and RL discussion before seeing that the closest 2026 works already own those premises.

At minimum, the final paper should cite:

- Crab when first distinguishing conversation/filesystem state from sandbox OS state and when discussing speculative/RL C/R; and
- ACRFence when first mentioning regenerated tool arguments, duplicate external effects, consumed approvals, or adversarial crash/rewind.

The paper should then immediately state the non-overlap: both systems reason about recovery/effects in one restored history, while the present work reasons about bounded authority over a **family of intentionally co-durable futures**.

## 11. Framing, title, and RQ changes

### 11.1 Framing

**Required framing change:** treat the agent C/R semantic gap and semantic rollback attack as established, then ask the larger unsolved question.

Unsafe lead:

> Agent checkpoints miss external state, so restore can replay effects or revive authority.

Defensible lead:

> Recent agent C/R systems have exposed two complementary gaps: application checkpoints omit OS execution state, and restore can replay irreversible external effects or consumed credentials. Neither determines how one bounded authorization may be promised across intentionally forked continuations whose outcomes can later be selected, retained together, or merged.

The paper should use ACRFence as an explicit negative baseline:

1. one one-use aggregate approval backs two exclusive branch promises;
2. one branch escapes or restore creates a divergent explicit fork;
3. the new branch ID satisfies “fork” syntax but supplies no new grant;
4. if both effects become durable, the history is ACRFence-compatible at the branch-ID layer yet violates aggregate authority unless a fresh/split/conditional claim is supplied.

This example must avoid identical-token reuse so that it tests the missing aggregate authorization rule rather than ACRFence's separate consumed-token detector.

### 11.2 Title

The current title, **“Authority Continuity: Residual Contracts for Fork, Restore, and Merge,” is directionally correct and should not be replaced by any title centered on checkpoint safety, semantic rollback, replay, or agent C/R.** Those spaces are now visibly occupied.

A small sharpening would help:

> **Authority Continuity: Residual Authorization for Fork, Restore, and Merge**

or, if the authors want the semantic object in the title:

> **Authority Continuity over Co-Durable Futures**

“Residual authorization” is clearer than “residual contracts” and prevents a systems reviewer from mistaking the paper for another recovery protocol. No title change is mandatory if the abstract and introduction make this distinction explicit.

### 11.3 Research questions

`docs/evaluation.md` has the current operative RQs. RQ1's title, “What authorization state is a checkpoint missing?”, is too close to Crab/ACRFence even though its evidence is differentiated. Recommended paper-facing RQs are:

1. **Exact authority state:** What summary exactly determines reservation admission over all outcomes that may still become durable together?
2. **Decentralize or seal:** When does that correlated residual factor into independent branch capabilities, and when can conditional-to-durable promotion be serialized rather than atomically sealed?
3. **Lifecycle preservation:** Which checked transfer, epoch, and effect-phase facts suffice to preserve the invariant through choice/parallel fork, replacing/live restore, merge, crash, retry, and revocation?

The current RQ4 algorithmic boundary can be folded into RQ1/RQ2 as the representation and complexity consequence. The older `docs/idea-story.md` RQs should eventually be synchronized because they promise broader temporal-protocol/delegation/latency results that are not the current paper.

Do **not** use an RQ asking whether semantic rollback attacks exist, whether checkpoints omit OS state, whether effects can replay, or whether C/R helps RL. Crab and ACRFence already answer those questions.

## 12. Baseline and evaluation implications

### 12.1 Crab

Crab is not a runnable main baseline for the authorization theorem: it controls a different layer and has no paper-linked artifact. It is:

- a **citation-only systems precedent** for sandbox-state fidelity, efficient checkpointing, proactive rollback, speculative execution, and RL branching;
- a **composition point** showing that even a complete Crab-style sandbox restore would still require non-rollbackable authority/effect state outside the snapshot; and
- a useful real-world workload source for histories involving fork/restore, but not evidence of authority safety.

A fair comparison should not claim Crab is unsafe under its own recovery target. The separating experiment is conceptual: place the current authority gate outside a Crab-restored sandbox and show which trusted state must not be part of the restored manifest.

### 12.2 ACRFence

ACRFence has no implementation to run fairly, by its own §6. Its published policy should nevertheless be a **mandatory executable decision-rule baseline** in the controlled litmus model:

- same logical effect after restore -> cached replay;
- semantically different effect -> require new branch ID;
- visibly consumed credential -> reject/warn.

The decisive history is a semantically new, explicitly forked, transaction-valid effect that consumes the same aggregate approval/quota without replaying the same token. If the ACRFence-style rule accepts after branch creation while the residual authority checker rejects or requires fresh authority, the experiment demonstrates the exact additional claim.

Do not report analyzer accuracy or overhead without an official implementation. Treat ACRFence's attack experiments as prior evidence, not a number to reproduce for novelty.

### 12.3 Headline proof evidence

The highest-value next evidence is not another rollback PoC. It is:

1. Lean mechanization of Boundary I over the actual residual definitions;
2. Lean mechanization of Boundary II over actual `PrepareOK` and `CoreStep.prepare`, including source-fixed owner groups, all permutations, enabledness, deterministic cleanup, and equality with the atomic authority target; and
3. one controlled ACRFence-style replay/fork baseline history that is safe/unsafe exactly because of co-durability and aggregate authority, not semantic matching.

## 13. Recommended claim language

### Claims to delete or explicitly attribute

- “We identify semantic rollback attacks.”
- “We identify Action Replay / Authority Resurrection.”
- “Existing idempotency assumes identical post-restore requests.”
- “Agent checkpoints miss OS/process state.”
- “C/R enables RL rollout branching / proactive rollback / speculative execution.”
- “An irreversible effect log with replay or fork solves restore.”
- “Non-rollbackable consumption is our contribution.”

### Claims that can remain, with scope

- “We formalize aggregate authority over permitted co-durable branch sets.”
- “A conditional commitment is an advance guarantee tied to durable support, not merely an unexecuted call.”
- “Choice, parallel fork, replacing restore, live restore, and merge induce different authorization targets.”
- “For fixed-topology batch Reserve, correlated admission factors into exact independent branch budgets iff the residual is rectangular.”
- “For exact promotion with eager cleanup, final repaired support exactly characterizes universal owner-order execution and equality with atomic sealing.”
- “Under complete mediation, typed demand bounds, checked lifecycle simulation, and sink aggregate bounds, every protected attempt plus every currently permitted conditional bundle remains within issued authority.”

### Claims that need qualifiers

- “Unique/new”: only for the exact authority-specific boundary, never for residuals, downsets, guards, linear resources, commutation, or checkpoint continuity in general.
- “Mechanized”: the lifecycle and conditional trace theorem are mechanized; Boundaries I--II are not yet.
- “Runtime support”: the Codex adapter is a fixed correspondence witness, not complete mediation or product refinement.
- “RL”: the calculus applies only if a trusted adapter supplies protected claims and merge/provenance semantics; Crab already owns the C/R efficiency/use-case claim.

## 14. Final novelty verdict

### What has been taken

ACRFence takes the most obvious security story: agent restore plus nondeterministic resynthesis can replay irreversible actions or resurrect one-use credentials; keep an effect log and replay or fork. Crab takes the most obvious systems story: agent state spans chat and OS-visible sandbox state; selective cross-layer C/R makes fault recovery, rollback, speculation, and RL branching efficient.

The current project must not compete on either story.

### What survives

The paper still has a defensible, larger question that neither source addresses:

> When an adaptive runtime intentionally changes the set of branch outcomes that may become durable together, what bounded authorization promises remain valid, what state is necessary for exact admission, and when may enforcement be decentralized or serialized?

Boundary I is the strongest surviving theorem relative to these two works. Boundary II also survives, but must be sold as a complete authority-specific certificate inside established concurrency theory. The fork/restore/merge certificate interface, prepared-to-uncertain effect lifecycle, and closed preservation theorem provide the integration layer.

### Submission decision

**Do not abandon the paper because of Crab or ACRFence. Do abandon any framing in which the contribution is “agent checkpoint/restore safety,” “semantic rollback prevention,” or “a durable effect ledger.”** Keep the current authority-centered title, sharpen the subtitle if desired, put both closest works in the introduction, add a direct ACRFence separation history, and mechanize the two headline iff results.

Until those changes happen, the manuscript is vulnerable to a novelty reject despite having technically distinct theorems. After them, Crab becomes complementary substrate and ACRFence becomes the motivating lower layer that the authority-continuity model strictly extends.

## 15. Residual uncertainty

- Both papers were v1-only preprints on the audit date. A later version, venue publication, or artifact could expand their scope.
- Neither arXiv page linked code. Absence of a discoverable official repository is not proof that no private or unindexed artifact exists.
- This audit answers closest-work risk from Crab and ACRFence. It does not supersede the separate formal closest-work report: Boundary II remains exposed to generic conditional independence/disruption results, and Boundary I remains exposed to generic resource-allocation/downset factorization even though no same-claim paper has yet been found.
- ACRFence's analyzer policy is prose, so some borderline histories are underspecified. The fair comparison must state an explicit interpretation rather than attributing behavior the paper never defines.
