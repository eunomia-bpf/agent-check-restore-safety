# Idea And Hypothesis History

## Initial Narrative

### Problem and stakes

Agent runtimes increasingly support checkpoint, restore, best-of-N exploration, parallel subagents, speculative tools, durable memory, and branch merge. These operations copy or recombine computation while the agent continues to act on resources outside the copied state: APIs, payments, messages, secrets, approvals, quotas, credentials, and other principals. Existing authorization is normally checked per action or per live process. Existing checkpoint protection normally asks whether local state is fresh or whether an effect has already happened. Neither model says how one bounded authorization is allowed to flow through an intentionally branching execution whose alternative results may later be selected, discarded, or merged.

The stakes are larger than duplicate RPCs. A restored or forked agent can revive one-use approval, spend the same delegated budget in concurrent descendants, bypass revocation from an old checkpoint, expose data from a losing speculative branch, or merge two individually authorized but mutually exclusive outcomes. As agent execution becomes more adaptive, a security model that treats each branch as an isolated session either copies authority unsafely or disables useful exploration by partitioning all authority in advance.

### Challenged belief

The status quo implicitly assumes that fork has one authorization meaning: copy the process view and rely on idempotency, or split linear authority among children. The project challenges that belief. Whether authority may be shared is not determined by the act of forking or by byte identity of a retry. It is determined by which descendants' effects are allowed to become durable together.

### Central principle

Computation may fork freely; authority may be shared only across mutually exclusive durable futures.

A choose-one exploration and an all-commit parallel spawn can have identical branch-local snapshots but require different authorization. A replacing restore is a choice only after the old continuation irreversibly loses commit eligibility; otherwise it is a concurrent fork. A merge can change previously exclusive alternatives into co-durable results and is therefore an authorization event, not only a workspace conflict-resolution operation.

### Proposed method

Represent each root grant as a finite labeled event structure. Unique authority events express bounded uses; causality expresses required order; conflict expresses exclusive authorized alternatives; labels bind events to concrete effects and commit-time evidence; obligations record liabilities created by exercising authority.

Represent the agent runtime by an append-only execution graph plus a downward-closed family of branch frontiers whose effects may become durable together. For every admissible durable frontier, globally exercised authority events plus that frontier's tentative reservations must embed injectively into a valid configuration of every relevant grant. This one invariant makes choose-one speculation additive, co-committable execution multiplicative, and topology-changing restore or merge subject to reauthorization.

Separate reconstructable branch state from monotone security state. Checkpoints may copy workspaces, model context, plans, and staged effects. They may not roll back exercised authority, revocation epochs, branch-selection decisions, uncertain dispatches, effect receipts, delegated ownership, or incurred obligations. Issue-time effects are charged immediately even in a losing branch; only effects held behind a trusted commit boundary may use topology-conditional reservations.

### Intended contributions

1. A formal semantics of authority continuity for forkable agents that covers sequence, exclusive choice, parallel execution, delegation, checkpoint, two restore modes, revocation, abort, effect timing, and merge.
2. A topology-sensitive conservation theorem and necessary-and-sufficient admission rules for sharing bounded authority and joining branch results.
3. Two necessity results: a monitor that cannot observe branch compatibility cannot be both sound and maximally permissive, and a checkpoint-local monitor cannot enforce bounded authority across irreversible effects and arbitrary restore.
4. A mechanized finite model and executable schedule explorer that derive counterexamples for weakened semantics rather than relying only on prompt attacks.
5. A small reference monitor and real-framework validation showing the difference among clone-all, split-all, global-ledger-only, and topology-aware enforcement, with modest performance measurements.

### Scope

The target is authorization integrity for adaptive agents with bounded or protocol-structured grants and effects outside a branch's rollback domain. The theory is intentionally applicable to non-LLM adaptive runtimes, but semantic retry, cheap branching, delegated subagents, heterogeneous state, and natural-language merge make agents the primary instance.

The first paper does not solve natural-language intent extraction, prove that an authorized action is beneficial, provide exactly-once execution for arbitrary non-idempotent Byzantine services, or fully formalize confidentiality of merged natural-language knowledge. Existing ACRFence attacks and framework evidence become motivation and litmus tests; its analyzer-LLM effect matching is not the new trusted core.

### Ambitious target claim

Per-action and per-branch authorization are insufficient for intentionally forkable agents. Sound and permissive authorization requires tracking the topology of possible durable outcomes and conserving each grant over every jointly durable descendant set. A finite event-structure model yields precise, compositional rules for fork, restore, delegation, revocation, abort, and merge, and these rules can be mechanized and enforced without serializing speculative computation.

### Provisional paper-level research questions

- **RQ1 — Expressiveness:** Can one compact authority model represent single-trace capabilities, bounded use, temporal protocol, mutually exclusive exploration, co-committable subagents, restore, and merge without granting the union of all possible plan effects?
- **RQ2 — Security:** Do the operational rules preserve durable-frontier authority conservation, revocation closure, delegation confinement, obligation persistence, and safe join under arbitrary schedules and crashes?
- **RQ3 — Necessity:** Which trusted topology and non-rollback state are necessary for sound yet permissive enforcement, and do real agent runtimes expose the indistinguishable local states used by the impossibility results?
- **RQ4 — Practicality:** Does a small reference monitor eliminate the litmus violations while preserving late-bound exploration, and what latency or contention does it add at checkpoint, restore, reserve, commit, and merge?

### Evaluation promise

The primary evidence is machine-checked definitions and proofs plus an executable bounded model that generates minimal violating schedules when premises are removed.  Empirical evidence is deliberately supporting: one frozen lifecycle suite crosses a real dispatch-owning Codex App Server boundary, compares four policies, and injects worker crashes around one isolated sink.  It tests correspondence and premise feasibility, not workload prevalence, end-to-end product mediation, prompt quality, or latency.

### Falsifiers

The central claim fails if closest work already gives an equivalent compatibility-indexed authority invariant and safe-merge characterization; if the result is a direct renaming of standard event structures or linear logic with no lifecycle-specific theorem; if branch compatibility cannot be enforced or observed in real runtimes; if safe sharing requires serializing all exploration; or if the model cannot state an honest guarantee for issue-time and uncertain external effects.

## Belief And Principle Evolution

| Date | Prior belief/model | External evidence | Updated principle | Paper impact |
|---|---|---|---|---|
| 2026-07-31 | A non-rollbackable global capability ledger plus fork-time splitting is the main contribution. | Consumable credentials, linear capabilities, separation logic, and rollback protection already occupy global consumption, split/merge, and monotone-state mechanisms. | Authority accounting must depend on which branches may become durable together; merge and live-original restore can change that relation. | Makes topology-sensitive admission and the soundness-versus-permissiveness impossibility the core, with the ledger as implementation machinery. |
| 2026-07-31 | Event-structure embeddings and topology-oblivious permissiveness are the core theorem story. | Standard event-structure morphisms already preserve configurations with local injectivity. A parent-held escrow lets pure candidate branches compute and transfers one capability only after selection, refuting the claimed impossibility/strict-dominance result. | The new object is the exact authority demand created when a lifecycle transition makes claims newly co-committable. | Replaces the invalid permissiveness theorem with a minimal-deficit theorem and a tractability boundary between structured choice/parallel trees and general merge graphs. |
| 2026-07-31 | Exact deficit and structured/general complexity can carry the paper. | The deficit is ordinary componentwise monus; choice/max and parallel/sum are the classical cograph cotree MWIS recurrence; arbitrary-graph NP/coNP follows directly from MWIS. A concrete counterexample also shows that plain Escape breaks the proposed preservation theorem. | Treat branch claims as conditional commit guarantees. The lifecycle-specific boundary is promotion from branch-conditional authority to universally charged durable consumption, plus topology expansion before irreversible escape. | Makes concrete/abstract adequacy, Escape Promotion, and the irreversible repair trilemma the lead results; retains max/sum, deficit, and hardness only as prior-math corollaries. |
| 2026-07-31 | Adequacy and a three-way repair theorem can be headlines. | Per-claim realizability does not justify summing mutually exclusive effects inside one branch; over-approximated frontiers refute the adequacy converse; the repair trilemma merely enumerates fields. Context-free restore and merge rules also create wrong frontiers. | Require conjunctive branch bundles and exact frontiers only for the converse. Make contextual restore, policy-parametric merge, snapshot-local impossibility, and the unique maximal safe escape-support restriction the core. | Removes circular and taxonomic claims; adds a stronger most-permissive promotion theorem and an explicit information-necessity result. |
| 2026-07-31 | Headroom/residual/full-abstraction plus frozen guards are by themselves the breakthrough. | Final hostile review showed that residuation, knowledge intersection, and threshold filtering are largely classical/definitional; it also found an invalid snapshot litmus, missing WF filtering, a revoke/dispatch gap, false syntactic contract equality, and an overclaim that freezing is required for AC. The same model yielded two stronger iff results. | The scientific boundary is when correlated authority factorizes into independent capabilities, and when commuting promotions remain executable under owner cleanup. Freezing is an explicit audit-continuity rule; concrete trace safety is a refinement obligation. | Adds the exact rectangularity/decentralization criterion and universal owner-group serializability iff final support; repairs ticket phases, structural signatures, owner/correlation reporting, and v4 executable evidence. |
| 2026-08-01 | Two exact boundaries plus prose lifecycle rules are enough for a CSF theory submission. | Independent PC review scored the draft 5/10: the two boundaries were judged valuable, but the claimed transition induction had no closed rule set; the grammar omitted checkpoint/retry/crash, structural steps could discard prepared tickets, and injective transfer conflicted with splitting. | A theorem about an agent lifecycle must quantify over a least generated transition relation. Every topology, admission, seal, attempt, recovery, settlement, and revocation step needs a checked premise and explicit target update. | Replaces prose semantics with a closed certificate-checked LTS, scopes capability claims to Cartesian budget products, makes serial-or-seal choices precise, and extends the artifact to v5 lifecycle traces. |
| 2026-08-02 | A one-use origin token must have at most one current claim occurrence. | Consumable credentials show that copied representations are safe behind one atomic ratifier.  The repaired model also gives the opposite temporal witness: one restored occurrence can create two fresh commitments through cloned cells.  Winskel-style configuration morphisms already own configuration preservation and local injectivity, while escrow owns global rights conservation. | Separate `history handle -> semantic redemption cell -> source authority atom -> durable commitment`.  Handle aliases may collapse to one cell; different cells may share one atom only across trusted mutually exclusive complete histories; durable commitments remain a fixed prefix after Prepare. | Reopens the central representation, demotes occurrence linearity and scalar escrow to strict profiles, and makes typed agent operator refinement plus the missing-observation lower bound the prospective contribution.  The classical morphism iff is only a completeness bridge. |
| 2026-08-02 | The inability to pre-enumerate a dynamically Forked/Restored/Merged agent graph, or the difference between its control and external-effect graphs, may itself distinguish agents from traditional systems. | Process calculi, dynamic-causality and reversible event structures, graph rewriting, adaptive workflows, and rollback recovery already cover online topology, changing dependencies, rollback, and distinct output histories.  A same-prefix exclusive/parallel pair shows that the actual issue is future-contract information at independent authority materialization.  A stronger counterexample shows that copying an exclusive choice gate twice product-composes `{a}` from one copy with `{b}` from the other even when both copies resolve their leaf handles to the same cells. | Do not enumerate a future graph.  Maintain a versioned, authority-relevant future contract whose configuration family conservatively covers real co-durable completions.  A shared Fork must alias the authoritative choice/fence controller, not merely its leaf cells.  Computation may fork without authority; independently redeemable authority requires an exact contract for completeness, shared ratification, deferred delegation, or worst-case rejection. | Removes another broad novelty claim.  Adds contract-relative arbitrary-extension soundness, no-silent-topology-expansion, a gate-cloning witness, and a precisely scoped observation lower bound to the typed runtime contribution. |
| 2026-08-02 | A useful tool might simply choose `Copy/Share/Split/Persist/Revalidate/Reject` for each checkpointed resource. | Plan 9 `rfork` already exposes per-resource share/copy/new flags; *Secure the Clones* verifies declared maximum-sharing clone policies; PORTICO compiles explicit agent contracts to epoch capabilities.  The newly mechanized minimal-nonface theorem instead shows that controller correlation and redemption-cell identity are independent obligations, and that multiway constraints can be invisible to every pairwise check. | Make the artifact a semantic-first, witness-carrying compiler.  For fixed candidate semantics under complete observation and controllable pruning, compute the greatest pointwise-safe subfamily; derive the least common-coordination equivalence under maximal asynchronous recombination and its finest exact partition; separately repair lineage collisions and preserve durable commitments; only then lower to runtime actions.  Return a Pareto frontier when share/split implementations are incomparable. | Rejects clone-policy code generation as the contribution.  The prospective novelty is a typed Fork/Restore/Merge synthesis theorem jointly transporting future correlation, linear redemption, and durable commitment, plus refinement-certified lease reuse and minimal counterexamples. |
| 2026-08-02 | Union/tensor generation plus an exhaustive three-case `Or` is already an exact typed admission theorem. | Hostile formal review found two hidden premises.  Without `required ⊆ candidate`, full admission and required rejection overlap.  Without normalized commitment-occurrence identities, set union silently collapses two independent cross-arm obligations that happen to reuse one name. | A valid typed contract yields a proved pairwise-exclusive trichotomy.  The compiler exposes four proof obligations—`Inherit`, `ReadmitOK`, `NeedsMechanism`, and pruning-only `Reject`—and treats arm tagging/intentional aliases as explicit adapter evidence.  Structural inheritance composes without enumerating the future graph, but it fixes the durable prefix; receipt growth forces readmission. | Closes the first typed theorem layer, prevents a malformed-contract/vacuity claim, and turns identity normalization into a checked compiler boundary.  It also narrows “lease survival” to structural lease-binding transport; authentication, revocation, expiry, and effect-digest validity remain runtime obligations. |
| 2026-08-02 | The contract-indexed evidence tuple and its several supporting theorems can be presented as one large contribution. | A strongest-baseline audit showed that a serialized atomic monitor already prevents replay, double redemption, and forbidden unions, so topology-aware admission is not necessary for safety alone.  Configuration families, range control, invariant confluence, anti-rollback, consumable credentials, and commit-time authorization already own the individual ingredients. | Treat the atomic monitor as the reference semantics.  History admission is the exact compilation criterion for specializing that monitor into the controller topology created by an Agent Fork, Restore, or Merge while preserving every declared required future. | Rebuilds the paper around one Agent History-Admission/Monitor-Compilation Theorem with safety, transparency, necessity, composition, and tight evidence clauses.  The old component theorems become lemmas; identity and arity results establish worst-case representation tightness; the tool becomes a proof-producing compiler rather than a collection of checks. |

## Hypothesis Frontier

| ID | Parent | Prediction | Falsifier | Evidence for/against | Status | Decisive next test | Reopen condition |
|---|---|---|---|---|---|---|---|
| H1 | root | Compatibility-indexed authority admits safe choose-one exploration and rejects co-durable double use; topology changes require reauthorization. | Equivalent prior formalization, or no lifecycle theorem beyond standard event-structure morphisms. | The invariant remains useful, but its event-structure formulation is established mathematics and two proposed permissiveness theorems have an escrow counterexample. | supporting | Retain only as scalar/vector safety semantics and prove lifecycle preservation. | Reopen as lead only if it yields a nonstandard representation result. |
| H2 | root | A monotone global ledger with first-commit-wins is sufficient; branch topology adds no paper-level value. | A topology-changing merge has a nonzero authority deficit that the flat ledger cannot predict without reconstructing co-committability. | Parent escrow defeats the early-partition strawman, strengthening this alternative; general merge admission remains unresolved. | serious alternative | Compare global first-commit-wins with exact deficit on choice-to-merge and live-original restore. | Promote if deficit adds neither accepted behavior nor advance reservation guarantees. |
| H3 | root | Semantic transactions and effect staging already solve the security problem; authority needs no separate model. | Bounded, revoked, delegated, or mutually exclusive authority can be violated even when effects obey transaction isolation. | Atomix/Cordon occupy staging; current hypothesis is that they do not constrain authority across compatible descendants. | serious alternative | Encode the same lifecycle in a transaction-only baseline and search for an authority-invalid but transaction-valid history. | Promote if every authority invariant reduces to transaction validity. |
| H4 | H1 | The exact additional authority needed by a topology change is its maximal newly co-committable claim load above the current grant; structured choice/parallel trees compute it linearly, while general conflict graphs cross an NP/coNP boundary. | The deficit is already a known authorization result, the general-graph reduction is incorrect, or real runtimes never preserve tentative claims across topology changes. | Full-text audit confirms that the arithmetic is classical monus, cograph MWIS dynamic programming, and inherited graph hardness. | supporting only | Use these facts transparently as implementation corollaries. | Reopen only if a lifecycle-specific representation theorem adds nonclassical content. |
| H5 | H4 | A lifecycle-aware abstraction is adequate exactly when branch claims are enforceable conditional commit guarantees; promotion to escaped consumption and topology expansion admit only three sound repairs: acquire authority, withdraw tentative commitments, or restrict/reject the lifecycle change. | Equivalent concrete/abstract theorem in prior work, a repair outside the trilemma under the stated fixed-binding scope, or inability to expose a trustworthy runtime lifecycle contract. | Hostile review produced per-claim mutual-exclusion and over-approximated-frontier counterexamples; after adding joint realizability/exactness, the converse is close to the model contract. The trilemma is field enumeration. | supporting only | Keep one-way soundness generally and a conditional converse; retain the repair list only as system taxonomy. | Reopen only if concrete semantics yields a nondefinitional refinement theorem. |
| H6 | H5 | Durable lifecycle information is necessary for sound and maximally permissive restore-time admission, and every conditional-to-durable promotion has a unique largest zero-capacity/no-cancellation safe support restriction. | Snapshot-local checker can distinguish replace/live without durable state, the maximal family is not downward closed, or a larger safe restriction exists. | The snapshot pair is valid, but generic information hiding is classical. The abstract filter is set-theoretically largest but can silently eliminate another owner's entire support and is not representable by the base grammar. | supporting only | Retain as corollaries of the residual-profile and guarded-closure results; delete “no-other-cancellation.” | Reopen only if a stronger operational maximality result survives support cleanup. |
| H7 | H6 | The action-class residual profile is the precise checkpoint-missing authorization state: headroom is fully abstract for one-step Reserve but not update-closed; the correlated residual downset is fully abstract and update-closed for fixed-topology Reserve; promotion forces a compact guarded-policy completion and final-owner-support/atomic-seal boundary. | A pair with equal residual but different Reserve behavior; failure of the residual derivative law; a base choice/parallel representation of the promotion witness; or prior work with the same co-durable authority specialization. | Closed-form proofs, choice/parallel correlation witnesses, the \(U_{2,3}\) nonclosure witness, frozen-guard executable checks, operational order counterexample, and supervisory-control scope audit all support the package. | leading | Finish paper proofs, mechanize the residual/guard/trace core, and implement one complete-mediation adapter path. | Demote if closest work contains the same residual authority semantics or the concrete refinement cannot cover all protected effects. |
| H8 | H7 | Correlated authority admits an exact architectural classification: it can be decentralized into independent branch capabilities iff \(\mathcal R=\operatorname{Box}(H)\); escape batches can be serialized in every owner order iff every promoted owner has final support. | A nonrectangular residual enforced soundly and single-branch-completely without coordination, or an absent-final-support batch whose every owner-group order remains enabled. | Paper proofs are short and noncircular; v4 checks 730 factorization cases (296 rectangular, 434 nonrectangular), positive/negative serial orders, real fresh-Reserve snapshot states, and only WF headline states. | leading | Mechanize both iff results and implement the factorization/owner-support decision path in one mandatory tool proxy. | Demote if prior work gives the same online capability-factorization and cleanup-serializability results for dynamic lifecycle authority. |
| H9 | H8 | A sound proof checker plus the closed Reserve/Struct/Merge/Prepare/ticket/Revoke rules preserves authority continuity and stable-ID effect coverage. | An admitted target violates AC or claim partition, a topology rule loses durable history, or crash/retry/revoke rebinds an operation or undercharges its aggregate outcome. | Lean machine-checks computed exact choice/parallel Fork and replacing/live Restore, source-local transfer and fiber conservation, two distinct Merge modes, all prior lifecycle rules, full trace induction, stable bindings, and conditional effect coverage. A fixed Codex adapter matches 89/89 P3 decisions and 20/20 P3 replays; the four-policy suite separately matches all 44 raw callbacks. The concrete theorem still assumes product-wide mediation and truthful arbitrary sinks. | leading support: abstract theorem plus bounded concrete witness | Generalize identifier allocation and close topology-activation crash atomicity before claiming a larger refinement. | Reopen on any counterexample to a checked premise or mismatch in the retained composite audit. |
| H10 | H9 | Ordinary agent traces are observationally insufficient for sound-and-complete authority-continuity admission; a compact trusted authority/effect event algebra may make the abstract checker replayable online. | Standard trace fields distinguish both the replace/live and retry/new-operation witnesses, the proposed extension still leaves different decisions observationally identical, no proposed event class is individually necessary, or event replay cannot reconstruct the checker state and decision. | Primary-source audit finds that available schemas omit some combination of topology, grant/claim lineage, durable effect phase, and receipts. In the frozen suite, O0 and O1 each retain exactly three mixed-label fibers (topology, lineage, phase), while O2 retains none and independently replays all 20 P3 chains. This is fixed-suite evidence, not a general irredundancy or minimality theorem. | supporting extension, bounded evidence | Prove a componentwise necessity/quotient result or keep observability as validation rather than a headline theorem. | Demote if the event bundle is merely a copy of checker state, cannot be collected at dispatch, or a standard schema supplies an equivalent trusted quotient. |
| H11 | H9,H10 | A typed agent lifecycle safely transports unit-normalized bounded authority exactly through a configuration-indexed semantic-cell quotient, while rollback-local clone availability forces a double-commitment history unless the runtime shares a linearizer, durably fences the joint future, or allocates distinct authority atoms. | The operational cell model must assume per-cell uniqueness; the source/target families are chosen circularly; a fourth mechanism preserves isolated availability and capacity; typed Fork/Restore/Merge do not compose; or closest work already gives the same runtime refinement. | Lean now checks the cell/atom quotient bridge, operational commitment LTS, durable-prefix transport, exact coordination decomposition, six typed operators, compositional structural refinement, and the choice-versus-parallel no-pruning separation.  Hostile review forced valid-contract and normalized-occurrence premises into the interface. | active leading candidate; theorem spine mechanized, concrete refinement open | Connect the checked layers in one witness compiler, formalize fail-closed identity/alias validation, and test generated certificates at the real callback seam. | Demote if the integrated compiler only restates configuration morphisms/escrow, if semantic occurrence identity cannot be refined by a trusted runtime boundary, or if product-composable clones avoid the lower bound under the stated assumptions. |
| H12 | H11 | A versioned co-durability contract is the sufficient statistic for authority safety over an unknown future agent graph: an overapproximation gives arbitrary-extension soundness, exactness permits structural completeness, and topology expansion must be admitted before reachability.  Shared Fork aliases one authoritative contract/gate instance; cloning that gate is a product expansion even when leaf-cell resolution is unchanged. | A prefix-only checker can remain both sound and complete while immediately issuing independently redeemable authority in the exclusive/parallel indistinguishable pair; two cloned choice gates cannot jointly realize configurations absent from one gate; silent contract expansion preserves all outstanding certificates; or the result reduces to an uninstantiated generic contract theorem with no agent operator refinement. | Structural refinements now compose edge by edge without enumerating the eventual graph; typed choice and parallel generate different complete futures from the same arm contracts; a fixed durable prefix transports, while the existing receipt-growth witness blocks stale snapshot reuse.  Arbitrary-extension and contract-hash enforcement remain unproved. | active subclaim of H11; typed local transport mechanized | Add contract-digest binding and no-silent-expansion at certificate installation, then instantiate the observation pair at the real callback seam. | Demote to motivation if gate identity adds no decision power beyond cell identity or if the remaining theorem says no more than generic assume-guarantee refinement. |
| H13 | H11,H12 | A small proof-producing admission compiler is the nontrivial synthesis contribution: it derives operator-level co-durability, preserves or rechecks structural authority state, computes required coordination, and returns one independently verifiable outcome plus a compact obstruction. | Its result is only a per-resource clone-flag table; the verifier must trust the compiler; undeclared aliases or missing receipt fields can still yield acceptance; or no real runtime manifest can satisfy the premises. | The component algorithms and their exactness boundaries are mechanized separately, and the four semantic outcomes now have a single soundness theorem.  Compiler integration, certificate schema, minimal-witness policy, and runtime extraction are still open. | active decisive artifact hypothesis | Implement the deterministic offline compiler and independent verifier with exhaustive small-model mutation tests before writing an adapter. | Demote if integration adds no theorem-visible information beyond existing clone/capability compilers or if certificates cannot fail closed under incomplete manifests. |

## Claim Evolution

| Date | Ambitious target claim | Evidence status | Unresolved uncertainty | Next evidence program |
|---|---|---|---|---|
| 2026-07-31 | Durable-outcome topology is the missing semantic input for conserving authority across forkable agent execution. | Formal sketch and preliminary primary-source audit only. | Closest event-structure/linear-logic claim, theorem feasibility, and enforceable topology API. | CSF/closest-work full-text audit; finite semantics; safe-sharing and topology-oblivious proofs. |
| 2026-07-31 | A fork, restore, or merge is authority-safe exactly when every newly co-committable claim fits the remaining typed grant; otherwise the transition must cancel claims or acquire the exact deficit before effects escape. Structured execution contracts make this exact check linear; unstructured merge graphs make it intractable. | Root-checked mathematical sketch; no proof or mechanization yet. | Prior art for max-plus resource demand; exact complexity class and assumptions; whether tentative guarantees matter in real runtimes. | Full-text novelty audit, paper proof, Lean semantics, and a choice/parallel versus arbitrary-merge checker. |
| 2026-07-31 | Authority continuity is a solvency property for conditional commit guarantees across history-transforming execution. A conditional claim may be shared across exclusive futures, but escape promotes it into consumption borne by every future; unsafe promotion or topology expansion must acquire authority, withdraw still-tentative commitments, or be blocked. | Concrete Escape counterexample, exact promotion rule, durable-select construction, and claim-oriented novelty audit; proof and mechanization remain open. | Adequacy reverse direction requires realizable guarantees; repair theorem scope; trustworthy topology hooks in real runtimes. | Write concrete/abstract semantics and complete paper now, then mechanize the small core and validate fixed litmus histories. |
| 2026-07-31 | Snapshot bytes are insufficient to authorize history-transforming agents: replace and live restore can reconstruct the same state yet require opposite Reserve decisions. Given durable lifecycle state, effect promotion admits a unique largest safe future family without new capacity or other cancellations. | Precise indistinguishable-world construction and candidate maximal-support formula; independent proof and mechanization pending. | Closest anti-rollback formulation, downward-closure proof, structured approximation, and runtime access to contextual restore state. | Rewrite theorem chain and paper; implement explorer first; mechanize finite frontier/promotion core. |
| 2026-07-31 | Checkpoint safety is missing the residual authorization profile for the next action class, not generic history: headroom suffices for one-step Reserve, a correlated downset is the update-closed Reserve controller, and escape requires frozen quantitative policy guards plus effect sealing. | Paper proofs drafted; exhaustive guarded artifact validates 3,428 repairs, 15,294 membership checks, 13,680 batch cases, the representation and frozen/dynamic counterexamples, and lineage transport. | Closest resource-residuation formulation; mechanized trace refinement; full mediation in a real adapter. | Finish CSF paper rewrite, hostile-review it, mechanize the small theorem core, then add one mandatory tool proxy adapter. |
| 2026-07-31 | The residual is the checkpoint-missing state, but the agent-specific contribution is its runtime architecture boundary: exact independent capabilities iff the residual is rectangular, and universal owner-group escape serialization iff every promoted owner has final support. | Paper proofs, explicit capability/cleanup counterexamples, one-shot ticket semantics, and v4 exhaustive checks over 1,312 WF states/730 safe sources; no Lean or complete runtime adapter yet. | Closest dynamic capability-factorization prior art; mechanized preservation and iff proofs; complete mediation in Codex/Claude. | Freeze the corrected CSF draft, mechanize the two iff results plus tickets, then build one dispatch-owning adapter rather than a broad benchmark. |
| 2026-08-01 | The two exact boundaries become a defensible lifecycle theorem only when every abstract step is generated by an explicit checked rule. | Closed LTS, explicit simulation/admission/seal certificates, fragment-conserving transfer, stable-ID attempts, and v5 bounded lifecycle exploration; no Lean or real adapter yet. | Soundness of the proof-object checker, arbitrary merge projection trust, complete mediation, and symbolic scaling. | Re-review the closed paper; then prioritize Lean and one dispatch-owning adapter over a broad benchmark. |
| 2026-08-01 | A clean Lean build of ten frozen names is sufficient evidence that the paper lifecycle is mechanized. | The kernel and axiom audits passed, but independent result review found that generic topology structural WF is supplied fieldwise and canonical Fork/Restore/Merge/transfer checking is absent. | Treat the run as a mixed finite-submodel result, keep it out of the paper, and make computed canonical topology plus checker soundness the next proof gate. | Close the topology interface before runtime claims; then test complete mediation in a dispatch-owning adapter. |
| 2026-08-01 | The finite canonical abstract lifecycle can derive, rather than assume, safety of history transformations from operation data and source-local checks. | Exact Fork/Restore builders, preallocated-fragment transfer and fiber conservation, distinct simulation/direct Merge, a single full Step/Trace, named controls, a clean 755-job build, fresh kernel replay, and two positive independent reviews. | Dynamic ID allocation, issuer approval, refined effect binding, complete mediation, sink truthfulness, and production refinement remain outside the theorem. | Promote the finite abstract-lifecycle mechanization into the paper; next measure the trace observability gap and instantiate one dispatch-owning adapter. |
| 2026-08-01 | The next agent-specific boundary may be observability: ordinary tool traces identify calls but not the durable authority/effect state needed to decide history transformations. | Primary-source schema audit of real and benchmark trajectories plus official Codex/Claude lifecycle interfaces; SWE-chat uniquely joins sessions, checkpoints, commits, and transcripts, but no available asset carries the full theorem state. | A distinct irredundancy or quotient theorem, prevalence of relevant operations, gated SWE-chat/AgentBench access, and complete dispatch ownership remain open. | Keep the current paper thesis fixed; test a hierarchy of observation erasures and a compact replay schema as RQ4, then combine public workload evidence with controlled instrumented histories. |
| 2026-08-01 | A dispatch-owning real-runtime path can test whether the abstract lifecycle premises are observable and enforceable without turning the paper into a benchmark study. | A revision-2 Codex 0.146.0 run crosses native fork and dynamic-tool callbacks: P3 matches 89/89 frozen decisions and 20/20 replays; all 44 callbacks match raw JSONL; 33 worker crashes recover; O0/O1/O2 have 3/3/0 mixed-label fibers. Independent review accepts the run after rejecting and retaining a flawed pilot. | The result is one isolated queryable sink with adapter-defined Restore/Merge, worker-only crashes, sibling native histories, and one fixed Merge certificate; topology activation, generic certificates, product-wide mediation, and a general observation lower bound remain open. | Report it as bounded composite correspondence evidence, keep the two exact theoretical boundaries as the paper's headline, and do not claim native Codex refinement. |
| 2026-08-02 | Current-occurrence linearity is the exact discrete transport condition for all one-use agent authority. | Two live history aliases can safely share one durable cell, so occurrence linearity is not necessary.  Conversely, same-label cloned cells can produce distinct fresh authority receipts, and a later Restore can double spend despite one instantaneous occurrence.  Primary sources place shared ratification, escrow, fencing, rollback-independent state, and configuration morphisms in prior work. | Use a two-stage quotient and count fresh durable commitments.  Full safety is configuration indexed; global scalar conservation is only the product-independent detached profile. | Freeze the revision-2 RQ3 experiment.  Do not rewrite the paper until operational commitment and typed operator theorems pass; keep the existing Codex/private-trace evidence at its prior narrow scope. |

## Rejected Or Dormant Paths

| Path | Why rejected/dormant | Raw evidence | Revisit trigger |
|---|---|---|---|
| Analyzer-LLM semantic fingerprinting as the core defense | It leaves the LLM in an authorization-critical role and does not define forked authority, revocation, delegation, or merge. | Existing `main.tex` mitigation and stated limitations. | Reuse only as an optional effect-equivalence heuristic outside the formal TCB. |
| Generic workspace rollback safety | Too broad and not agent-specific; transactions, compensation, and checkpoint systems already own much of it. | Existing systems literature and current ACRFence framing. | Revisit only for a specific theorem required by authority continuity. |
| Always partition authority at fork | Safe for concurrency but unnecessarily rejects mutually exclusive late-bound exploration. | Two-branch separation example; linear capability prior work. | Revisit if no enforceable choose-one topology exists. |
| Event structures as the headline novelty | Configuration preservation and local injectivity are standard; using them directly would look like notation replacement. | Winskel event structures and reviewer construction. | Revisit only as appendix proof substrate or if a new representation theorem emerges. |
| Topology-oblivious monitor impossibility / conditional reservation strictly dominates partition | A parent-held escrow can delay authority transfer until winner selection, preserving safety and useful pure speculation. | Concrete four-step counterexample from independent theory review. | Revisit only under an explicit pre-selection availability guarantee that is itself practically necessary. |
| Unqualified adequacy iff / repair trilemma as headline | Per-claim realizability and over-approximated frontiers refute the converse; after stronger assumptions it approaches the contract definition. The trilemma only lists mutable fields. | Same-branch internal-choice counterexample, unreachable-frontier counterexample, and second hostile review. | Revisit only through a genuine concrete refinement result. |

## Narrative Evolution

| Date | Before -> after | Reason and decisive evidence/instruction | Root disposition | Initial vs previous vs chosen comparison | Evidence | Revisit condition |
|---|---|---|---|---|---|---|
| 2026-07-31 | Event-structure authority plus sound/maximally-permissive impossibility -> typed consumable claims plus exact topology-change deficit and tractability boundary. | The event-structure invariant is close to a standard morphism, and parent-held escrow refutes the proposed impossibility. The user asked for simple, intuitive, nontrivial, large theory rather than formalistic complexity. | Accept the critique; retire the invalid theorems; keep durable-frontier conservation as the safety definition and make deficit/complexity the scientific contribution. | The Initial Narrative found the right large problem but stacked too many concepts. The immediately previous version had broader vocabulary but weaker/false results. The chosen version is smaller in mechanism, larger in theorem consequence, and more faithful to the requested CSF theory target. | Primary-source novelty map in `docs/background-related-work.md` and current model in `docs/design.md`. | Reopen if full-text search finds the deficit theorem, the complexity reduction fails, or typed claims cannot express the motivating lifecycles. |
| 2026-07-31 | Deficit/complexity headline -> conditional commit guarantees, concrete/abstract adequacy, Escape Promotion, and irreversible repair trilemma. | Full-text audit showed the arithmetic is classical cograph/MWIS/monus machinery. Independent proof review found a two-branch counterexample to plain Escape and a durable-select construction that repairs it without new capacity. | Accept and pivot. Define exactly what a tentative claim promises, make effect escape a support-changing lifecycle operation, and prove why irreversible history removes cancellation as a repair. | Initial narrative supplied the large execution-tree intuition; the prior version made it precise but claimed classical math. The chosen version uses that math transparently while placing novelty in a concrete security semantics and necessary/sufficient repair boundary. | docs/background-related-work.md; current docs/design.md; proof-review counterexample recorded in the design. | Reopen only if adequacy cannot be made bidirectional or the repair result remains definitional under an honest concrete semantics. |
| 2026-07-31 | Adequacy/repair headline -> snapshot-local impossibility plus unique maximal safe escape support. | A second hostile review found an internal-choice counterexample, an unreachable-frontier counterexample, a missing terminal claim set, and incorrect context-free restore/merge rules. It also derived a strictly more permissive escape repair than durable-select. | Accept all blockers. Add conjunctive bundles, terminal IDs, contextual leaf replacement, explicit merge policies, general soundness with only a conditional converse, and demote repair to taxonomy. | The initial story correctly separated rollback domains; the previous versions found conditional authority but repeatedly overclaimed elementary consequences. The chosen theory now has two falsifiable results whose statements do not assume their conclusions. | Current docs/design.md and the second hostile review. | Reopen if maximal support is not representable or the snapshot-local theorem is already subsumed by an equivalent lifecycle-aware anti-rollback theorem. |
| 2026-07-31 | Abstract maximal-support filtering -> proof-carrying authority-support contracts. | Hostile review found that promotion of \(b\) in \(b\Box(x\parallel y\parallel z)\) can permit every pair of \(x,y,z\) while forbidding their triple, which is not representable by the base choice/parallel grammar. It also found missing effect coverage, ghost-live branches, and a gap between algebraic batch commutation and operational serialization. A supervisory-control audit showed that generic maximal permissiveness, partial-observation synthesis, AND/OR state trees, guards, and BDDs are established. | Accept and pivot. Demote the set filter to an abstract specification; add exact frozen threshold guards, explicit support/cancellation reporting, lineage transport, local simulation certificates, and a trace theorem requiring durable accounting before dispatch. Scope batch confluence to atomic or support-preserving promotions. | The initial narrative supplied support-changing histories; the previous version found the exact abstract filter but mistook set-theoretic maximality for an implementable controller. The chosen version turns the representation failure into a theorem and a runtime protocol while explicitly building on supervisory control. | Third hostile review; Ma--Wonham state-tree structures; Feng--Wonham--Thiagarajan guarded transaction processes; Cieslak et al. and Cai--Zhang--Wonham on partial observation. | Reopen if frozen guards do not transport compositionally, the forward simulation remains circular, or closest work already contains conditional-to-durable authority promotion with the same runtime protocol. |
| 2026-07-31 | Residual/guard package -> exact capability decentralization plus cleanup-aware escape serialization. | A fourth hostile review showed that most residual algebra is classical, exposed invalid structural/snapshot/ticket assumptions, and derived two stronger iff results: residual rectangularity and final-owner support. | Accept every correctness blocker. Define a common structural signature and WF+AC scope, repair the snapshot pre/post test, use one-shot tickets, distinguish AC from no-silent-policy-expansion, count predicate circuits, report lost correlations, and make the iff architectural boundaries the headline. | The initial narrative correctly asked what checkpoint bytes omit. The prior version found the residual but risked presenting accepted-set algebra as new theory. The chosen version now says exactly when a runtime may compile correlation away into capabilities and exactly when abstractly commuting escapes survive branch cleanup. | Fourth hostile theory review; v4 executable JSON SHA-256 `1907996d85619a46afb7f705e3fab2e9bf040ae4b41fe93fd5297414ba47457b`; current paper theorems. | Reopen if mechanization refutes either iff, if complete mediation cannot be realized, or if primary prior work already states the same dynamic capability/cleanup criteria. |

| 2026-08-01 | Two exact boundaries with certificate-flavored prose -> two exact boundaries over a closed certificate-checked lifecycle LTS. | Final PC review accepted the importance and core novelty but identified a submission blocker: no exhaustive inference rules, undefined certificate objects, ambiguous split transfer, and no artifact coverage of tickets/crashes. | Accept the blocker. Define the least generated relation, sound proof checker, deterministic target builder, complete core rules, and stable-ID attempt semantics; add bounded recovery and structural-simulation exploration. | The initial narrative wanted a large, principled agent execution theorem. Earlier versions repeatedly enlarged claims without closing the transition relation. The chosen version narrows capability/RL scope but makes the actual lifecycle safety claim checkable rule by rule. | Independent 5/10 PC review; v5 artifact with 24 tests, 8 recovery states/22 edges, 26 structural frontier checks, and explicit tombstoned-owner rejection. | Reopen if a second independent review finds an ungenerated transition, circular certificate premise, or mismatch between the rules and executable model. |
| 2026-08-01 | Interface survey and hypothetical adapter -> fixed real Codex boundary with a composite correspondence audit. | Public traces motivated the missing topology/authority/effect fields, but only a dispatch-owning experiment could control causality and crash points. The first 80-run pilot was rejected for erased aliases, an inferred attempt label, and an uncertified Merge; revision 2 repaired evidence without changing the oracle and passed independent review. | Accept the fixed instantiation, not a broad refinement claim. Decompose native setup forks from lifecycle materializations, expose the topology crash window, and keep replay, App Server, fault, and sink checks distinct. | Earlier story risked treating interface availability or dataset fields as implementation evidence. The chosen story uses public traces for workload/observability and a real local runtime for a narrow premise witness, leaving theory primary. | `adapter/`, Step 0004 plan/rejected pilot/final review, 33/33 tests, 89/89 P3 decisions, 20/20 replays, and raw App Server/SQLite evidence. | Reopen if the checker join is unsound, a retained database disagrees with its summary, or broader claims need native Restore/Merge and topology crash atomicity. |
| 2026-08-02 | Occurrence-linear token transport -> configuration-indexed semantic-cell quotient with durable commitments. | A hostile prior-work/theorem audit found safe shared aliases, same-label cloned-cell double spend, exclusive-choice and temporal-restore counterexamples to static domain counting, and the classical status of ratification, escrow, configuration morphisms, and fencing.  Two-round experiment review accepted the corrected theorem package and rejected scalar conservation as a complete model. | Accept the larger reconstruction authorized by the user's request for a broader, nontrivial Agent-specific theory.  Preserve co-durable conditional authority from the Initial Narrative; change only its representation and operational refinement. | The Initial Narrative correctly made compatibility and monotone external state central.  The immediately previous occurrence model made Prepare concrete but overidentified representations with redeemable state.  The chosen model composes the two: aliases quotient at a semantic cell, independent cells map locally injectively to source atoms over complete histories, and fresh commitments persist across Restore/Merge. | Step 0007 hostile novelty audit, approved experiment-002 plan, supporting Lean frontier, and seven-case semantic matrix; decisive mechanization is in progress. | Reopen if typed operators cannot derive the quotient map, the operational LTS needs target safety as a premise, or the final novelty collapses to only the classical morphism/escrow lemmas. |
| 2026-08-02 | Unknown dynamic agent graph and nonisomorphic history/effect graphs -> versioned authority-relevant future contract over typed online extensions. | The user challenged whether a dynamic Fork/Restore/Merge graph can be specified.  Primary-source audit found dynamic-causality event structures, reversible event structures, graph rewriting, workflow migration, rollback output commit, and generic contracts already cover the broad phenomena.  The same current prefix can nevertheless admit an exclusive safe completion and a parallel unsafe completion when detached cells share one atom. | Reject graph-dynamicity as novelty.  Specify the generator and its future contract, not concrete future IDs.  State the impossibility only at independent authority materialization and explicitly retain deferred delegation, shared ratification, and conservative rejection as escapes. | The Initial Narrative correctly focused on possible jointly durable futures but treated their family too extensionally.  The previous cell model supplied the right identities.  The chosen version makes the family an online, versioned runtime contract and makes topology expansion an admission event. | Open-future contract audit and the exclusive/parallel Lean fixtures. | Reopen if the contract cannot be generated compositionally, if silent expansion is harmless under outstanding detached authority, or if the remaining result is only a renaming of assume-guarantee reasoning. |
| 2026-08-02 | Readiness checking plus witnesses -> a checked greatest co-liveness pruning proposal. | The user asked for a theory-guided tool with larger, nontrivial novelty.  A greatest hereditary-safe restriction makes the checker constructive, but range-control literature shows that generic maximally permissive synthesis between lower and upper bounds is established. | Keep contract-indexed observation arity as the controller-theory headline; retain greatest pruning as a constructive corollary and theory-to-tool bridge, explicitly scoped to one submitted Gamma and fixed access/local families. | The Initial Narrative required useful enforcement without serializing exploration.  The previous narrative decided and diagnosed one manifest.  The chosen construction preserves every safe downward-closed co-liveness alternative in its scope and exactly decides whether pruning can retain required behavior, without claiming a new general synthesis theory. | Lean greatestness/feasibility theorems; independent compiler/verifier output; U(2,3) install-and-resubmit test; Yin--Lafortune range-control comparison. | Reopen if proof/tool semantics diverge, a closer typed-history construction appears, or no runtime can install the proposed restriction. |
| 2026-08-02 | Several admission, obstruction, pruning, and projection theorems -> one two-stage, contract-indexed exact evidence boundary. | Final hostile review found no fatal mathematical error but warned that presenting elementary set filters and six surface labels as co-equal novelties hid the strongest result.  A direct Lean corollary was also missing for the tool's claim that evaluating the submitted complete projection itself matches hidden-Gamma readiness. | Treat `(raw manifest, q_cell, q_ctrl, Gamma) -> (R,F,E,L, Pi_{<=r} Gamma) -> Ready` as the theorem spine.  Fixed-manifest collisions make the two identity relations independently nonerasable for exact admission; an arbitrary-k cover makes every uniformly lower arity insufficient; the complete contract-indexed projection is sufficient.  Call this worst-case information irredundance, not a unique or pointwise-minimal encoding. | This enlarges the contribution by characterizing the exact runtime evidence interface rather than by adding a complex runtime or more operator syntax.  Choice/tensor/replacement, greatest filtering, obstruction extraction, and runtime transport remain constructive support. | Lean projection downward-closure/idempotence and adapter-facing exact-projection corollary; well-formed two-by-two quotient fixture; arbitrary-k U(k,k+1) lower bound; three-mode compiler/verifier. | Reopen if closest work derives the same typed-edge-and-prefix-indexed interface, if a fixed-E,L counterexample refutes projection sufficiency, or if an adapter cannot attest projection completeness. |

## Superseded Frontier Before the Atomic-Monitor Audit

**Central claim under test.** The paper characterizes a two-stage exact evidence
boundary for online history admission:

```text
(raw manifest, q_cell, q_ctrl, Gamma)
  -> (Required, Admitted, access, local families, Pi_<=r(Gamma))
  -> exact structural-readiness Boolean.
```

Agent histories copy action handles and grow an online control graph, but
safety is determined by a distinct redemption and commitment topology.  The
concrete future graph need not be enumerated.  A runtime instead maintains a
versioned future contract `Gamma` and resolves

```text
history/control prefix + Future_Gamma
    -> semantic linearization cells
    -> source authority atoms
    -> durable commitments and receipts
```

`Future_Gamma` conservatively covers the cell configurations whose fresh
Prepare commitments may coexist under every compliant extension.  Aliases may
share one cell.  A shared Fork also aliases one authoritative
choice/fence-controller instance; copying the same leaf-cell references behind
two independent choice gates can product-compose futures that one gate kept
exclusive.  Independent cells may reuse one source atom only when a
durable lifecycle decision prevents them from appearing in one complete
history; otherwise the runtime must share a linearizer, defer delegation,
allocate distinct escrow atoms, fence/consolidate, reauthorize, or reject.
Prepare creates a fresh durable commitment and all later
retry/dispatch/settlement phases retain that identity and the relevant contract
version across Restore and Merge.  Contract expansion is admitted before it
becomes reachable; a checkpoint cannot silently restore an older exclusivity
promise.

The planned artifact is not a checkpoint engine and does not choose clone flags
from resource names.  It is a small offline witness-carrying compiler and an
independent certificate verifier.  The theory fixes both its intermediate
representation and its fail-closed result lattice:

```text
runtime manifest + typed history operation + Future_Gamma
  + normalized occurrence cells / explicit aliases
  + cell/atom lineage + outstanding lease bindings + durable receipts
    -> greatest pointwise-safe subfamily (in the fixed fully observed scope)
    -> least common-coordination equivalence under localProduct
       / finest exact partition
    -> structural lineage and durable-prefix transport check
    -> Inherit | ReadmitOK | NeedsMechanism | Reject
    -> backend obligations + independently checkable certificate
       or a minimal collision / forbidden-union / prefix-replay witness
```

The controller layer now has a constructive output rather than only a
readiness test.  After fixing the greatest prefix-safe future, it filters the
submitted co-liveness family to the greatest downward-closed subfamily whose
raw controller product remains admitted.  This restriction covers required
behavior exactly when any co-liveness-only pruning under fixed access and local
families can do so.  The compiler reports a non-authorizing proposal;
installation and resubmission remain runtime steps.  This greatest-filter fact
is supporting classical synthesis machinery; the observation-arity upper and
lower bounds remain the controller-theory headline.

`Inherit` requires a version-monotone configuration refinement whose lineage
square commutes and whose durable prefix is unchanged.  `ReadmitOK` means the
old structural certificate cannot be reused but the entire generated candidate
passes the current prefix check.  `NeedsMechanism` means every declared
required behavior survives only after installing the synthesized pruning and
coordination fence.  `Reject` is exact only for the fixed frontier, lineage,
generated contract, and pruning-only repair scope; reissuing cells, changing
lineage, or acquiring authority is a new request.  These are semantic admission
classes, not deployment readiness.  A runtime may execute a protected effect
only when the verifier accepts an `Inherit` or `ReadmitOK` certificate *and*
independently verifies that the concrete controller partition realizes the
derived coordination contract.  A missing/cut gate is a nonauthorizing
deployment obligation even when the full semantic family is safe.

The first synthesis layer is now mechanized.  Minimal nonfaces induce the
least common-coordination equivalence under maximal asynchronous `localProduct`;
its classes are the finest exact controller partition up to label renaming.
This is a logical coordination domain, not a physical co-location mandate: a
shared durable controller, lock, or consensus protocol may realize it.  A cut constraint generates an additive policy
witness, and the `U_{2,3}` fixture proves that every pair can be legal while a
three-way combination still requires one coordination component.  This layer
is credited as classical combinatorial machinery rather than headline novelty.

The second synthesis layer is also mechanized for a fixed, fully observed
candidate family.  A durable prefix `P` is extracted from immutable receipt
bindings only behind a checked safe-ledger gate (where atom identity names an
indivisible unit and includes authority root/issuer, scope, and version/nonce
or unit index), plus a separate proof that the prefix belongs to the source
family.  A future
configuration `C` survives exactly when its lineage map is
locally injective, its image is disjoint from `P`, and `P ∪ image(C)` was
admitted by the source contract.  Universal preservation of every additive
source policy is equivalent to this pointed configuration morphism.  Filtering
by these conditions yields the greatest safe subfamily in this fixed scope; a
separate theorem requires every behavior supplied as `required` to survive.
This prevents silent pruning relative to that input but is genuinely
non-vacuous only when the adapter supplies complete, meaningful leaf
contracts.  The resulting downset composes with the first
layer to derive its least required coordination relation.  A receipt for one
atom blocks snapshot-only resurrection of that atom, while a distinct-atom
future remains structurally transportable.  The latter shows only that this
invariant does not force blanket invalidation.

The third synthesis layer is now mechanized.  Six typed constructors distinguish
exclusive Fork from parallel Fork, replacing Restore from live-original
Restore, and select Merge from join Merge.  They derive the operator-level
may/required family by choice or tensor composition, preserve well-formedness,
and prove `required ⊆ candidate`.  A valid operation at a fixed durable frontier
has an exhaustive and pairwise-exclusive classification: full readmission,
required-preserving proper pruning, or pruning-only rejection.  A four-way
classifier splits full admission into structural `Inherit` and `ReadmitOK` and
has one soundness theorem for all outputs.  Versioned structural refinements
compose, so a dynamic execution graph is checked edge by edge rather than
pre-enumerated.  The same old structural lease binding can transport to two
mutually exclusive target cells, while changing only the operator to parallel
makes the joint required future inadmissible and leaves no pruning repair.

The type `D` denotes globally normalized semantic commitment occurrences, not
physical resources or controllers.  Independent arm occurrences must be
distinct (normally arm-tagged); reuse of one identity declares one intentionally
shared obligation.  The compiler must reject undeclared cross-arm aliasing.
The typed constructors derive only operator-level composition from leaf
may/required contracts; they do not infer those contracts, cell normalization,
lineage, receipt aggregation, or concrete runtime reachability.  Lease results
prove structural binding transport only—not token authentication, revocation,
expiry, signature validity, effect-digest binding, remote exactly-once, or sink
settlement.

**Current RQs.** (1) finish the policy-independent cell/commitment LTS while
crediting classical configuration morphisms; (2) connect the now-mechanized
typed operator, structural refinement, prefix filter, and coordination layers
through one proof-producing compiler; (3) prove no-silent-contract-expansion
and the precisely scoped future-contract lower bound at independent authority
materialization; (4) prove which of co-redeemability, semantic cell identity,
durable commitment history, contract version, and alias declaration a
sound-and-permissive adapter must observe; and (5) validate one concrete
Claude/Codex manifest extractor and certificate-verification seam.
Existing Codex and private paper-formation traces remain bounded
correspondence and observability evidence, not product-wide refinement or
safety prevalence.

## Current Frontier: Phase-1 Rewrite Contract

**One security property.**  A post-edge Agent epoch is *history-admissible*
when it is both:

1. **monitor-sound:** every durable effect history it can realize is accepted
   by the strongest serialized atomic monitor for the same durable receipt
   frontier; and
2. **required-transparent:** every declared required outcome that the monitor
   permits remains realizable after the edge.

This deliberately makes the global monitor the reference semantics instead of
claiming that history admission is necessary for safety in every architecture.
The new question is when an Agent runtime may soundly preauthorize detached or
independently live controllers without consulting that monitor at every
effect, while retaining the behavior promised by Fork, Restore, or Merge.

**One theorem.**  A typed Agent edge uniquely derives its candidate and required
families from its before/after history relation and leaf contracts.  At durable
frontier \(D\), let \(\mathsf{Adm}_e\) be the complete trace language of the
atomic monitor, and let \(\mathsf{Phys}(E,L,\Gamma)\) be the complete durable
language of the installed controller epoch.  Under a checked edge-cut
refinement (the old epoch is closed, receipt growth races invalidate the seal,
retained-cell lineage commutes, and the manifest exactly abstracts the new
controllers), the Agent History-Admission Theorem proves

\[
\begin{aligned}
&\text{monitor-sound and required-transparent}\\
&\quad\Longleftrightarrow\
  \mathsf{Required}_e
  \subseteq \mathsf{Phys}(E,L,\Gamma)
  \subseteq \mathsf{Adm}_e\\
&\quad\Longleftrightarrow\
  \mathsf{HA}\!\left(
    e,\mathcal A,D,q_{\rm cell},\ell,q_{\rm ctrl},
    E,L,\Pi_{\le r_e}(\Gamma)
  \right)=\mathsf{accept}.
\end{aligned}
\]

The proof first establishes the nontrivial reference-language equality
\(\mathsf{Traces}(\mathsf{GlobalMonitor}_e(D))=\mathsf{Adm}_e\): downward
closure makes every ordering of an admitted configuration pass every atomic
prefix check, while ledger monotonicity makes every accepted execution remain
inside the authority family.  It then connects the controller epoch to this
language through the manifest semantics.  This gives four consequences of the
same characterization:

- **safety:** compiled controllers refine the atomic monitor;
- **transparency:** required monitor-legal outcomes are retained;
- **necessity:** a forbidden combination spanning independent commit domains
  forces coordination/reservation, loss of some required behavior, or
  rejection;
- **tight representation:** edge mode, durable frontier, semantic-cell
  identity, controller identity, and contract-indexed co-liveness information
  cannot in general be erased while preserving exact verdicts.

The theorem does not claim that its literal evidence tuple is the unique
encoding.  It claims only that each semantic distinction, or equivalent
information, is necessary in the worst case.  Minimal nonfaces, greatest safe
pruning, range control, configuration morphisms, and the
\(U(k,k+1)\) skeleton are credited as classical supporting machinery.

**Agent specificity.**  The six labels are not aliases for three set
constructors.  They are before/after history relations:
choice Fork creates exclusive descendants, parallel Fork creates co-live
descendants, replace Restore first closes the old continuation, live Restore
retains it, select Merge keeps one outcome, and join Merge makes outcomes
co-durable.  The edge relation derives the effect-family contract; the adapter
may not simply assert the target family.  A version-bound installation seal
linearizes between receipt observation and old-epoch closure.  Any concurrent
Prepare grows the receipt frontier and makes the seal fail; a successful seal
prevents the old epoch from preparing new effects.

**Tool and evidence.**  The artifact remains deliberately small: a
proof-producing offline compiler and independent verifier for the theorem's
manifest-level criterion, plus Lean proofs for the typed-family, durable-prefix,
controller-cover, identity-separation, and arity components.  The paper must
enumerate exactly which bridge lemmas remain pen-and-paper.  Existing
Claude/Codex traces are not security evaluation and should not occupy a main
contribution; at most they motivate why runtime-native trusted fields are
needed.

**Paper research questions.**

1. When is the controller epoch produced by an Agent Fork, Restore, or Merge
   exactly a sound and required-transparent specialization of a serialized
   atomic monitor?
2. Which edge, receipt, identity, lineage, and co-liveness information is
   sufficient—and worst-case necessary—to decide that question?
3. Can a small proof-producing compiler decide the criterion, emit useful
   obstructions or repairs, and have its result independently verified?

**One-sentence claim.**  History admission is the exact, worst-case-tight
compilation criterion for replacing a serialized durable-authority monitor by
the controller topology created by an Agent Fork, Restore, or Merge edge.

## Current Frontier: Causal Epoch Rewrite Contract

The first monitor-compilation rewrite failed independent CSF review for one
shared reason: its endpoint sandwich was largely definitional, its unordered
families could not express approval-before-payment or merge causality, and its
claimed controller and installation facts were external attestations.  The
next rewrite therefore supersedes, rather than repairs, the preceding
contract.

**One new object.**  A raw protected action is
\(\mathsf{use}(j,h)\), pairing a gate-use occurrence with a ledger-backed
handle occurrence.  A bounded protected slice of Agent execution is generated
by
\[
  P ::= \mathbf 0 \mid \mathsf{use}(j,h)
      \mid P;P \mid P\oplus P \mid P\parallel P .
\]
Sequence records causal prerequisites, tagged choice records exclusive
alternatives, and parallel is order-preserving shuffle.  The slice ends at the
next history edge; unrestricted internal reasoning is outside the alphabet,
and a newly materialized protected action triggers a new slice rather than
requiring the complete Agent future to be predicted.

The six Agent operations are distinct before/after cuts over this calculus:
choice and parallel Fork use \(\oplus\) and \(\parallel\); replacing Restore
atomically retires the current continuation before reinstating the checkpoint;
live Restore shuffles both continuations; select Merge names the winning
branch, retires the loser, and sequences the winner before the join
continuation; join Merge sequences the join continuation after a shuffle of
both inputs.  Thus Restore and Merge modes affect both the trace language and
which source controller epochs the installer must fence.

**Normalized causal reference.**  Authenticated ledger anchors induce the
cell quotient; the first successful redemption emits one semantic cell and a
retry or replay stutters.  Source controller anchors identify exactly the
classes that installation must close.  The compiler does not accept a target
controller quotient or a claimed \(E,L,\Gamma\): it mints the target epoch and
binds every target gate use itself.

Let \(\mathcal A\subseteq\mathcal U^*\) be a finite-state,
prefix-closed durable-authority policy and let \(\delta\in\mathcal A\) be the
authenticated receipt trace.  Normalizing a typed edge request \(R\) gives a
prefix-closed plant language \(\mathsf{Plant}_R\) over fresh semantic cells and
a lineage homomorphism \(\ell^*\).  Its exact reference future is
\[
  F_R=\{\sigma\in\mathsf{Plant}_R
       \mid \delta\ell^*(\sigma)\in\mathcal A\}.
\]
This is the complete language of the strongest atomic monitor at the observed
history cut.  It preserves order: a payment-before-approval trace, a losing
choice arm after selection, or a join continuation before both prerequisites
is absent even when it has the same endpoint set as a legal trace.

**Canonical epoch.**  The compiler constructs the residual automaton of
\(F_R\).  Its state after \(\sigma\) is the right residual
\(F_R/\sigma=\{\rho\mid\sigma\rho\in F_R\}\), and it enables a fresh cell
\(d\) exactly when \(\sigma d\in F_R\).  The target epoch is therefore a
compiler-produced controller program, not a verdict about a caller-described
manifest.  Classical residual/minimal-automaton facts are credited as
machinery; the claimed contribution is the raw Agent-edge-to-installed-epoch
correctness boundary.

**One theorem.**  The *Canonical Causal Epoch Theorem* relates four views of
one history cut:

1. every promised partial-order outcome of the typed edge has a linearization
   in \(F_R\);
2. there exists a monitor-sound epoch preserving every such outcome;
3. the canonical residual epoch exists and has fresh-trace language exactly
   \(F_R\), not merely a language between supplied bounds; and
4. after a successful version/frontier-bound installation, the kernel LTS is
   a trace refinement of the reference monitor across arbitrary
   Prepare/Install races and across successive Agent edges.

The forward construction is the residual epoch.  The reverse direction uses a
missing promised outcome as a complete impossibility witness.  Exact language
equality makes the canonical epoch maximally transparent among monitor-sound
epochs.  A commutative endpoint family is only the permutation-invariant
corollary already covered by the existing Lean development.

**Installation is semantics, not an assumption.**  The durable LTS contains:

- `Prepare`, which requires an active epoch, a residual transition, and an
  unspent ledger cell/authority atom, then atomically updates controller state
  and appends the receipt;
- `Install`, which compares the policy version, view version, exact receipt
  trace, source-epoch set, and program hash, and in one linearized cut closes
  every source controller class, mints and opens the target epoch, and binds
  target gate uses; and
- `Replay/Retry/Settle`, which may resolve old receipts but emits no fresh
  authority event.

If an old `Prepare` linearizes first, the receipt trace changes and the install
CAS fails without state change.  If `Install` linearizes first, the old epoch
has no fresh-Prepare transition.  This cut, plus induction over successful
installs, is the nonclassical dynamic part of the theorem.  Linearizable,
crash-stable ledger/CAS storage and complete mediation remain explicit TCB
assumptions; old-epoch closure is no longer an unmodeled premise.

**Promises without prophecy.**  A promise is a bounded protected outcome
declared by the Agent operation/API, not a prediction of all future model
behavior and not a fairness guarantee.  Understating it can weaken only the
feature-preservation claim, not monitor safety; overstatement may reject the
edge.  New protected actions require a new edge request.  Empty promises are
reported as offering no transparency claim rather than used to manufacture a
positive result.

**Paper boundary.**  The new causal calculus, residual-epoch equality, and
installer invariant receive self-contained paper proofs.  Existing Lean and
Python evidence is described only as checking the unordered endpoint
corollary; it does not mechanize the causal main theorem or a production
installer.  The paper makes no claim of optimal controller sharding, real
Codex/Claude complete mediation, physical exactly-once delivery, policy
inference from natural language, or external sink rollback.

**One-sentence claim.**  A Fork, Restore, or Merge can cross a live Agent
history cut without retaining the global authority monitor exactly when its
promised causal outcomes survive the durable-policy residual; the canonical
residual epoch preserves the entire surviving monitor language, and a
frontier-CAS installation makes that equivalence stable under stale-history
and fresh-commit races.

## Current Frontier: Exact Agent History Realization Contract

The causal-epoch rewrite failed four independent CSF reviews for the same
substantive reasons.  Its promises lived over raw occurrences while its
reference language lived over normalized cells; its request supplied the
plan, promise family, source set, and anchors that the claimed Agent
refinement needed to derive; its runtime checked only a cell transition, so a
wrong gate occurrence could borrow an enabled cell; and its reference future
contained pointwise-safe dead ends.  The revision below supersedes that
contract rather than patching those defects.

**One security object: the Agent history machine.**  A trusted state is
\[
  H=(G,T,K,\rho,\mathsf{owner},\chi,\nu).
\]
\(G\) is an append-only Fork/Restore/Merge provenance DAG; \(T\) is its live
frontier with choice, parallel, selected, and joined structure; \(K\) is an
immutable checkpoint registry; \(\rho\) authenticates every logical protected
occurrence, gate, semantic redemption cell, and authority lineage;
\(\mathsf{owner}\) maps live gates to controller generations; \(\chi\) records
completed logical occurrences, including aliases; and \(\nu\) is the trusted
view version.  The non-restorable store separately holds policy version
\(\kappa\), exact authority-receipt trace \(\delta\), receipt phases, and an
ordered outbox.

The untrusted Agent may propose only a typed operation over identifiers already
present in \(H\), plus newly registered leaf contracts where the operation
introduces a future:
\[
\begin{split}
 &\mathsf{ForkChoice}(b,L,R),\quad
 \mathsf{ForkParallel}(b,L,R),\\
 &\mathsf{RestoreReplace}(b,k),\quad
 \mathsf{RestoreLive}(b,k),\\
 &\mathsf{MergeSelect}(g,w,J),\quad
 \mathsf{MergeJoin}(g,J).
\end{split}
\]
It cannot submit a target plan, promise family, source set, anchor family, or
receipt frontier.  Leaf contracts come from the protected tool/API registry;
an unregistered protected call is denied and requires a new admission.

**One contract representation.**  A causal-completion contract
\(\mathcal C\) is a finite nonempty family of finite pomsets over unique
logical protected occurrences.  Different pomsets are complete outcomes;
their order is causal obligation.  Tagged alternative \(\oplus\), disjoint
parallel product \(\otimes\), and ordered product \(\triangleright\) compose
contracts.  There is no separate caller-controlled promise set.

The trusted history rewrite judgment
\[
  H\vdash u\Downarrow
  (H',\mathcal C_{H,u},\mathsf{Src}_{H,u},\mathsf{Tgt}_{H,u})
\]
is deterministic.  Choice and parallel Fork rewrite one live branch into a
tagged alternative or parallel group.  Replace Restore retires the current
continuation and installs a checkpoint clone; live Restore carries the current
continuation beside a clone.  Select Merge verifies the named winner belongs
to the named choice group, retires the group, and sequences its remaining
contract before \(J\); join Merge verifies a parallel group and sequences
\(J\) after the parallel product of every remaining input.  `clone` freshens
logical occurrence and gate identities while retaining authenticated semantic
cell anchors; `carry` retains remaining logical occurrences and cells while
rebinding gates.  The affected live-frontier closure determines every source
owner, and the target frontier determines every compiler-minted binding.

**Length-preserving resolution.**  Raw occurrences and policy events are not
compared as languages.  For a raw linearization \(w=x_1\cdots x_n\), the
deterministic transducer \(\mathsf{Resolve}_{\delta}(w)\) emits one resolved
event per logical occurrence:
\[
  \mathsf{fresh}(x_i,d)
  \quad\text{or}\quad
  \mathsf{alias}(x_i,d),
  \qquad d=q_{\rm cell}(x_i).
\]
The first redemption of \(d\) is fresh; an already receipted cell or a distinct
copied occurrence of the same cell is an alias.  Only the fresh projection
\(\mathsf{auth}(-)\) advances the durable authority policy.  A retry of the
same invocation is the only stutter.  Thus an alias still consumes its exact
logical occurrence, resolves a choice, and may satisfy a join predecessor.

**Exact history admission.**  For each structurally derived outcome
\(p\in\mathcal C_{H,u}\), its safe complete executions are
\[
 M_p(H,u)=
 \{\mathsf{Resolve}_{\delta}(w)\mid
   w\in\mathsf{Lin}(p),\
   \delta\cdot\mathsf{auth}(
      \mathsf{Resolve}_{\delta}(w))\in\mathcal A\}.
\]
Admission is the typed, non-understatable condition
\[
  \mathsf{Admit}(H,u)
  \iff
  \forall p\in\mathcal C_{H,u}.\ M_p(H,u)\ne\varnothing.
\]
The ideal post-cut language is not every pointwise-safe prefix.  It is
\[
  W_{H,u}=
  \mathsf{Pref}\!\left(
    \bigcup_{p\in\mathcal C_{H,u}}M_p(H,u)\right),
\]
the prefixes of all safe complete executions.  Hence every admitted prefix
has a safe completion, every structurally promised outcome remains possible,
and all safe complete linearizations are retained.  The construction is the
greatest language that is history faithful, authority-policy safe,
completion-nonblocking, and covers every derived outcome.

**One theorem: Exact Agent History Realization.**  For every well-formed
history, prefix-closed authority policy, and typed operation, the following
are equivalent:

1. \(\mathsf{Admit}(H,u)\);
2. there exists a history-faithful, policy-safe,
   completion-nonblocking realization covering every derived outcome; and
3. compilation returns an installable controller and cut seal.

When they hold, the compiled controller realizes exactly \(W_{H,u}\), and
every realization satisfying the four requirements has a language contained
in \(W_{H,u}\).  When they fail, a derived pomset \(p\) with \(M_p=\varnothing\)
is a complete impossibility witness for the fixed history, policy, receipts,
and leaf contracts.

The theorem's global clause proves
\[
  \mathsf{CompiledAgent}(H_0)
  \approx
  \mathsf{IdealAtomicHistory}(H_0)
\]
by weak bisimulation for arbitrary sequences of all six operations, fresh
commitments, logical aliases, protected-call results, retries, dispatch,
settlement, and crashes.  The compiler may implement \(W\) by residual
automata, but that classical representation is only a lemma.  The theorem is
about exact realizability of Agent history rewrites.

**Atomic history cut.**  An install re-derives the rewrite and source set from
the current trusted \(H\); compares
\((\kappa,\nu,\delta,\chi,\mathsf{CutDigest})\); closes every derived source
generation; persists \(H\to H'\); activates one target generation; and binds
all target gates in one transaction.  Comparing \(\chi\) as well as \(\delta\)
is essential: an alias can change choice or join progress without appending a
receipt.  If a fresh or alias occurrence wins the race, the seal is stale; if
install wins, the old gate's generation is closed.  The ordered outbox releases
prepared effects in receipt order, so the theorem protects durable
authorization and release order while making no claim about remote network
completion.

**Tightness.**  The trusted observation
\[
 \alpha(H,u)=
 (\mathcal C_{H,u},q_{\rm cell},\ell,\delta,\chi,
   \mathsf{Src}_{H,u},\kappa,\nu)
\]
is sufficient.  Paired indistinguishable histories show componentwise
worst-case irredundance of causal topology, cell identity, controller
ownership, receipt frontier, logical-occurrence frontier, and
choice-versus-parallel mode.  This is an information lower bound, not a claim
that the literal tuple is the only encoding.

**Novelty boundary.**  Sound-and-complete live controller update, update
bridges, most-general property-preserving state transfer, maximal nonblocking
supervision, online DES control, history-dependent authorization, consumable
credentials, commit-time authorization, and epoch fencing are established
prior results.  The claimed result is their missing Agent-history boundary:
the persistent history topology itself derives the new causal-completion
contract and every still-authoritative source; Restore creates new logical
occurrences that retain old semantic effect identities; alias progress can
race the cut without changing receipts; and history persistence, complete
source fencing, and target activation are refined to one durable transition.

**One-sentence claim.**  Agents can rewrite which past continuations remain
capable of acting; history admission characterizes exactly when such a rewrite
has a policy-safe, completion-preserving realization and compiles every
admitted Fork, Restore, or Merge into a runtime globally equivalent to an
ideal atomic Agent-history machine.

## 2026-08-15 Scope Evolution: Safe Change After External Operations

The user raised the target from an Agent-only theorem and adapter to a real
OS-like runtime spanning Codex/Claude, complete Linux virtual machines, and
microservices. Fresh closest-work review changed the scientific center rather
than merely enlarging the artifact.

Dynamic controller update, Live Synthesis, supervisory control, workflow
versioning, stable request identity, output commit, safe network update, and
unknown-result impossibility already own most obvious component claims. The
project therefore does not claim a new maximal controller or a first theory of
live update.

The new thesis is:

> From the complete execution record and a requested semantic change,
> automatically derive the remaining obligations, stable external identities,
> observable uncertainty, and controllable actions; synthesize a safe Rule
> using established control theory; then enforce it atomically across Agents,
> virtual machines, services, and external effects. If no Rule exists, return
> evidence tied to the actual execution and external boundary.

The public vocabulary is reduced to five terms: History, Requirement,
Operation, Rule, and Certificate. The existing Exact Agent History Realization
result becomes the Agent frontend and a special theorem instance. Its fixed
point and coordination results become reusable lemmas; its SQLite/Codex adapter
becomes a differential oracle for the new control service.

The proposed theoretical breakthrough is answer-preserving normalization of
History plus end-to-end correspondence between concrete adapters and the
abstract Rule. A two-way correspondence permits exact acceptance and refusal;
a one-way correspondence supports safety only. The proposed systems
breakthrough is one crash-safe external-action boundary shared by Agent tools,
VM network/device output, and microservice RPCs, with Rule changes serialized
against real Operation progress.

Step 0008 implements the first real slice in `runtime/`: a synced hash-linked
History, stable Operation lifecycle, exact bounded non-stranding planner,
history-bound Certificate, HTTP gateway, and a separate payment durability file
reached over HTTP. The demo recovers a lost payment response across a durable
control-state reopen with two network deliveries but one commit, blocks a
locally valid action that would make another result impossible, and rejects a
stale Certificate after Operation progress. Full VM enforcement, Agent
integration, symbolic scale, an independent checker binary, and the generic
Lean theorem remain open.
