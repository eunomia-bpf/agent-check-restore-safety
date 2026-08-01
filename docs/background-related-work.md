# Literature, Novelty, and CSF Fit

**Status:** living claim-oriented audit, last updated 2026-07-31. A paper is listed here only after at least its abstract, introduction, claimed contributions, model, and evidence sections have been inspected. “Not found” means not found in the searched corpus, not a universal priority claim.

## 1. Venue contract: CSF 2027

Primary sources:

- official call for papers: <https://www.ieee-security.org/TC/CSF2027/cfp.html>;
- official program committee: <https://www.ieee-security.org/TC/CSF2027/committee.html>;
- recent accepted-paper lists: [2022](https://www.ieee-security.org/TC/CSF2022/program.html), [2023](https://csf2023.ieee-security.org/accepted.html), [2024](https://csf2024.ieee-security.org/accepted.html), [2025](https://csf2025.ieee-security.org/accepted.html), and [2026](https://www.ieee-security.org/TC/CSF2026/accepted.html).

CSF explicitly asks for foundations: formal security models, relationships between security properties and defenses, and principled techniques or tools for rigorous analysis. A systems vulnerability with only a wrapper defense is therefore a poor fit; a lifecycle security property, nontrivial characterization, proof, and checked artifact are a plausible fit.

The regular-paper limit is 12 IEEE two-column pages, excluding the AI-use acknowledgement, references, and clearly marked appendices. Reviewers need not read appendices, so the main definitions, theorem statements, proof ideas, and decisive counterexamples must fit in the body. Review is double blind. The three outcomes are accept, reject, and major revision. The relevant deadlines are 2026-08-03, 2026-10-15, and 2027-01-28, AoE. The October cycle is the first credible target; January is the fallback if mechanization exposes a model defect.

The PC is unusually capable of detecting shallow repackaging. Chairs Bruno Blanchet and Deepak Garg and PC members working on protocols, program logic, capabilities, information flow, hyperproperties, and proof assistants make the following failure modes especially dangerous:

- calling an append-only ledger or a linear capability new;
- treating standard event-structure configurations as a new security model;
- renaming ordinary transaction recovery as an agent-specific theorem;
- presenting an invariant that holds only because every transition assumes it;
- omitting concurrency, live-original restore, merge, revocation, or escaped effects;
- claiming a formal result without a checked semantics or independently auditable proof.

## 2. What recent CSF theory papers actually look like

The local reading corpus is under `reference/csf-theory/` (PDFs are intentionally git-ignored). The most useful exemplars are:

| Paper | Shape worth copying | Evidence balance |
|---|---|---|
| *Formalizing Stack Safety as a Security Property* (CSF 2023) | Starts from an intuitive but underspecified property, separates it into precise properties, uses short counterexamples to distinguish definitions, then validates them with property-based and mutation testing. | Definitions and relations dominate; executable validation is small but decisive. |
| *Relative Security* (CSF 2024) | Introduces a semantic relation, shows where existing reasoning fails, provides proving and disproving methods, then mechanizes the central results. | Theory plus Isabelle; no conventional performance study is needed. |
| *Security Properties through the Lens of Modal Logic* (CSF 2024) | Earns novelty through a unifying representation, equivalences, separations, and exposed hidden assumptions rather than a new system. | Almost entirely definitions, theorems, and counterexamples. |
| *Nonmalleable Progress Leakage* (CSF 2025) | A new hyperproperty drives a calculus, type system, inference method, and Rocq-checked metatheory. | Pure theory is acceptable because the formal artifact is strong. |
| *Full-System Security on Capability Machines* (CSF 2022) | Treats capabilities and resource reasoning as foundations, not branding; the contribution is the compositional security proof across attacker models and effects. | Machine-checked proofs and representative constructions replace benchmarks. |
| *Robust Safety for Move* (CSF 2023) | Defines a property, gives a generic enforcement result, implements a small analyzer, and checks realistic programs. | A good model for “mostly theory, small real validation.” |
| *FSLH* (CSF 2025) | Finds a missing point between two established security extremes, defines it precisely, and obtains a new defense space. | Mechanized definitions and results are the primary evidence. |

The recurring contribution chain is:

1. a security intuition is currently ambiguous or checked at the wrong semantic boundary;
2. two or three minimal executions show why nearby definitions disagree;
3. a compact property classifies those executions;
4. the paper proves equivalence, strict separation, exact characterization, impossibility, or a sound enforcement theorem;
5. mechanization or executable counterexample generation makes the result auditable;
6. one realistic instantiation shows that the semantic distinction exists outside the calculus.

For this project, 70--80% of the scientific weight should be the model, characterization, complexity boundary, and proof. Mechanization and a deterministic lifecycle explorer are experiments in the sense relevant to CSF. Large prompt benchmarks are neither necessary nor particularly persuasive.

## 3. Closest-work map by claim, not keyword

### 3.1 Consumable authority and capability transfer

**Consumable Credentials** (Bowers et al., NDSS 2007) already combines linear authorization logic with distributed ratification so that use-limited authority cannot be productively consumed more than once. It occupies “credentials can be copied syntactically but consumption is globally linear.”

**Capstone** (Yu et al., USENIX Security 2023), CHERI-style capability work, linear capabilities, and separation logics already occupy authority attenuation, transfer, revocation patterns, and resource composition. Pym, O'Hearn, and Yang's semantics of BI (TCS 2004, DOI 10.1016/j.tcs.2003.11.020) also makes generic resource composition and residual implication established foundations, so neither the word “residual” nor a derivative law over an additive resource monoid is independently novel. **DisLog** (POPL 2024) additionally reasons explicitly about nested fork-join structure. These works mean that “do not clone a one-shot token at fork” is not a paper-level novelty.

Surviving distinction: those systems do not, in the inspected models, give the closed-form action-class residual for promises conditioned on which previously alternative descendants may become durable together, nor connect its representation change to irreversible effect promotion. Our claim must be about a changing durable-outcome contract, not about discovering linearity or residuation.

### 3.2 Rollback, fork detection, and monotone state

**Memoir** (IEEE S\&P 2011), **ROTE** (USENIX Security 2017), **LCM** (2017), and later TEE state-continuity work already establish that security-sensitive history cannot live only in rollbackable state. They use trusted nonvolatile summaries, distributed witnesses, or fork-linearizable views to prevent stale protected state from becoming current. **Crab** (arXiv 2026) instead targets agent sandbox recovery fidelity and efficiency: it classifies OS-visible effects and supports fault recovery, preemption, speculative execution, and RL rollout branching. It demonstrates why conversation or filesystem rewind is not full execution-state restoration, but does not model external authority that has already escaped the sandbox.

Surviving distinction: anti-rollback normally rejects or detects histories that diverge from a valid linear continuity relation. Agent exploration intentionally creates alternatives and sometimes preserves several outcomes. The new problem is to authorize this non-linear lifecycle without treating every fork as an attack or every branch as independently funded. The non-rollbackable ledger is a premise and enforcement substrate, not the contribution.

### 3.3 Transactions and external effects

**Atomix** separates execution, sealing, progress/frontier checks, and settlement for agent tool effects. **Cordon** defines semantic transaction boundaries for composed tool flows. **DART** asks whether a local rollback remains semantically recoverable after downstream commitment. Classic output-commit, sagas, durable execution, idempotency, and transactional outboxes already cover much of staged versus escaped effect handling.

Surviving distinction: transaction validity does not itself answer whether two individually well-formed branch effects are jointly authorized under one bounded grant. Our model imports staging/escape as effect facts, then checks an orthogonal typed-authority property over co-durable descendants. A decisive litmus must exhibit a history that is transaction-valid but authority-invalid.

### 3.4 Agent execution and authorization

**Fork, Explore, Commit** supplies nested branch contexts, isolated filesystem/process state, and first-commit-wins selection. **Agent libOS** exposes explicit capabilities, hierarchical budgets, child processes, checkpoints, and checkpoint-derived images. **Commit-Time Authorization** binds durable effects to authority that remains valid at settlement. **Ghost Tool Calls** shows that a losing speculative branch may leak information before selection. **ACRFence** identifies action replay and authority resurrection after conversation restore.

These papers make an agent wrapper insufficient. In particular:

- first-commit-wins safely handles choose-one output but says little about a later merge or live-original restore;
- a branch ID never creates new authority;
- a global capability ledger can safely delay delegation until selection, defeating any claim that authority must always be partitioned or conditionally reserved at fork time;
- commit-time freshness and pre-commit disclosure are adjacent lifecycle properties, not substitutes for bounded authority across compatible descendants;
- ACRFence's old “replay or fork” rule is unsound as a general authorization rule because the explicit fork may still reuse the same grant.

### 3.5 Concurrency structures and resource algebra

Winskel-style event structures already provide configurations, causality, conflict, and locally injective configuration-preserving maps. Process algebras, workflow nets, and resource analyses have long assigned resources to concurrent actions. Consequently:

- the use of a conflict/configuration model is proof machinery, not novelty;
- structured choice/parallel terms induce cographs: choice is graph join, parallel is disjoint union, and max/sum is the classical cotree dynamic program;
- maximum-weight independent set hardness follows directly once an arbitrary conflict graph and additive branch weights are chosen; workflow concurrency thresholds already use related reductions.

Primary anchors are Corneil, Perl, and Stewart, “A Linear Recognition Algorithm for Cographs” (SIAM J. Computing 1985); Meyer, Esparza, and Völzer, “Computing the Concurrency Threshold of Sound Free-Choice Workflow Nets” (TACAS 2018); Terauchi and Aiken, “A Capability Calculus for Concurrency and Determinism” (CONCUR 2006); and Das, Hoffmann, and Pfenning, “Work Analysis with Resource-Aware Session Types” (LICS 2018). The audit therefore treats the algebra, conservation pattern, and complexity boundary as established machinery.

The surviving candidate contribution is an action-class authorization boundary:

> For fixed-topology batch Reserve, a checkpoint may omit a correlated residual admission profile. That profile factorizes into a Cartesian product of noncommunicating branch-local budgets exactly at a closed-form rectangularity boundary. Conditional-to-durable promotion can force higher-order policy, and final-owner support exactly characterizes when every owner-group order remains enabled under immediate cleanup.

This remains publishable only if the paper shows that (i) common agent lifecycle APIs genuinely change co-durability, (ii) nearby authorization and transaction models accept a violating history or reject a safe useful one, and (iii) the structured/unstructured representation choice creates a meaningful enforcement boundary rather than merely restating a textbook graph problem.

### 3.6 Supervisory control, partial observation, and guarded workflows

Ramadge--Wonham supervisory control already asks for the largest legal behavior obtainable by disabling controllable events. Under full observation, supremal controllable sublanguages and fixpoint algorithms are classical. Under partial observation, the boundary is more delicate: standard observability is not closed under union, so a unique supremal observable-and-controllable sublanguage need not exist. Cieslak, Desclaux, Fawaz, and Varaiya established this partial-observation setting; Cai, Zhang, and Wonham later introduced relative observability, which fixes an ambient language, is union-closed, and therefore recovers a computable supremal policy at the cost of a stronger condition.

Two structured-control results are especially close. Ma and Wonham's state-tree structures use hierarchical AND/OR state organization, predicates, BDDs, and recursive symbolic synthesis to obtain optimal nonblocking supervisors. Feng, Wonham, and Thiagarajan synthesize control logic for communicating transaction processes and translate it into propositional guards on message-sequence charts. Consequently, this project must not claim the following as new:

- maximally permissive control as a generic objective;
- guards, predicates, BDDs, or AND/OR state trees as a generic representation;
- supervisor synthesis under partial observation;
- translating a safety policy into guarded workflow execution.

The useful connection is instead a scope test and a source of proof machinery. A snapshot-only hook is a partially observing controller. A durable claim certificate refines its observation. General partial-observation synthesis may lack a unique most-permissive policy, so the paper must not make that claim for arbitrary hidden lifecycle events.

The surviving specialization is an *online authority-support transformer* for a dynamically created agent history. Its plant is not a fixed workflow known before synthesis: branch epochs, effect bindings, typed claims, and merge projections are created during execution. Escape changes a claim from branch-conditional support to durable support, and the effect gate must linearize accounting before an external observation. The candidate new results are therefore limited to this semantics: an exact criterion for compiling correlated residuals into independent capabilities; a cleanup-aware iff criterion for promotion serialization; non-closure of pure choice/parallel contracts under authority promotion; and an exact threshold repair with lineage transport. Freezing is an explicit no-silent-policy-expansion rule, not a generic AC necessity. Classical supervisory control remains the encompassing control-theoretic framework.

This comparison changes the intended wording from “authority-controller synthesis under partial observation” to “a certificate-checked online specialization of supervisory control for authority support in history-transforming runtimes.” It also creates a hard novelty obligation: if the final theory only adds threshold predicates to an AND/OR tree, it is not a CSF contribution.

## 4. Current novelty verdict

| Candidate claim | Status | Reason |
|---|---|---|
| Non-rollbackable consumption state is necessary. | Established premise | Anti-rollback and consumable-credential work already owns it. |
| Forking must not clone linear authority. | Established premise | Linear capabilities and resource logics already own it. |
| Authority over co-durable descendant sets. | Promising semantic contribution | No equivalent agent lifecycle contract was found; event structures and linear resource logics provide substrates and strong conservation precedents. |
| Snapshot-local sound-and-maximally-permissive impossibility. | Supporting corollary | It is one nonconstant observation fiber of the more general residual-profile precision theorem; generic partial-observation impossibility is classical. |
| Headroom full abstraction and correlated residual controller. | Leading, closest-work sensitive | Gives a closed form for the minimal one-step Reserve behavior, proves per-branch summaries are not update-closed, and gives an update-closed residual derivative for joint Reserve. |
| Residual rectangularity iff an exact Cartesian product of branch-local budgets. | Leading, closest-work sensitive | For fixed-topology batch Reserve, converts correlation into a necessary-and-sufficient runtime test: noncommunicating product-local soundness and one-branch completeness coexist exactly when the residual equals the product of its projections. |
| Unique maximal abstract escape filter. | Supporting specification | Set-theoretic maximality is immediate from filtering and can induce hidden promise cancellations; value comes from representation non-closure, support reporting, and operational sealing. |
| Generic maximally permissive controller / guarded AND-OR policy. | Established framework | Supervisory control, state-tree structures, predicate/BDD synthesis, and guarded transaction processes already occupy this space. |
| Promotion non-closure plus authority-support guards and lineage transport. | Promising, closest-work sensitive | The representation result is specific to conditional-to-durable authority promotion; novelty depends on a concrete lifecycle semantics, explicit audit-continuity choice, and effect coverage rather than the existence of threshold predicates. |
| Universal owner-group serializability iff final support. | Leading, agent-specific | Captures the non-algebraic interaction between exact promotion and deterministic branch cleanup; absent support constructs a failing order, while final support protects every prefix. |
| Exact deficit / repair trilemma. | Demoted | Deficit is ordinary monus; the trilemma enumerates the fields affecting the definition. |
| Structured choice/parallel admission is linear. | Established supporting result | It is the classical cograph cotree recurrence. |
| General-graph safety is coNP-complete. | Established supporting result | It is inherited directly from Independent Set/MWIS and representation-sensitive. |
| Topology-aware reservation strictly dominates delayed escrow. | Rejected | A parent can retain authority while children compute purely and transfer it after winner selection. |
| “Replay or fork” prevents semantic rollback. | Rejected | Forking computation does not mint authority. |

## 5. Required separation examples

The paper needs executable, three-to-six-step histories, not only prose:

1. **Transaction-valid, authority-invalid:** two parallel or merged branches settle distinct valid effects using a one-unit grant.
2. **Snapshot-locally identical, lifecycle-different:** restore-replace and contextual restore-live reconstruct the same bytes but require opposite Reserve decisions.
3. **Safe choice, unsafe merge:** two one-unit reservations are safe under choose-one; retaining both results creates a one-unit deficit.
4. **Losing branch still consumes:** an issue-time disclosure or uncertain dispatch escapes before selection and remains in durable consumption after abort.
5. **Revocation crosses restore:** an old snapshot has a syntactically valid credential but a stale grant epoch.
6. **Delayed escrow is enough for pure candidates:** this prevents the paper from attacking a strawman and clarifies when advance reservation is actually useful.

## 6. Downloaded source inventory

The following full texts are present locally and validated as PDFs:

- `reference/closest-work/`: Consumable Credentials, Capstone, DisLog, Memoir, ROTE, LCM, Crab, ACRFence, Fork/Explore/Commit, Atomix, Cordon, DART, Ghost Tool Calls, Commit-Time Authorization, and Agent libOS.
- `reference/foundations/`: Winskel event structures, the Capability Calculus, resource-aware session types, and workflow concurrency-threshold analysis.
- `reference/supervisory-control/`: partial-observation supervisory control and relative observability; full-text browser copies were also inspected for state-tree structures and guarded communicating transaction processes.
- `reference/csf-theory/`: capability-machine security, FLAQR, Cracking the Stateful Nut, Robust Safety for Move, Formalizing Stack Safety, modal-logic security properties, Relative Security, secure synthesis, FSLH, Nonmalleable Progress Leakage, Cryptographic Choreographies, and unified attack-tree metrics.

Two IACR papers used only as venue-style context were readable from their primary web copies but blocked command-line PDF download: *Nominal State-Separating Proofs* (ePrint 2025/598) and *Computationally-Sound Symbolic Cryptography in Lean* (ePrint 2025/1700). They are not closest work for the scientific claim.

## 7. Writing consequence

The introduction must not begin with LLM nondeterminism or duplicate UUIDs. It should begin with two executions that copy the same checkpoint but differ only in the runtime's durable-outcome contract. The headline is a missing authorization boundary for history-transforming computation; tool-using agents make that boundary common because they combine cheap branching, long-lived delegated authority, external effects, human resume, and semantic merge.

The paper can honestly target CSF if it delivers:

- one compact operational model with explicit trusted and rollbackable state;
- a security property independent of the enforcement rules;
- an exact lifecycle-admission theorem plus at least one non-definitional separation or lower bound;
- a mechanized conservation proof and generated counterexamples for weakened rules;
- a small deterministic monitor/explorer and limited real-runtime evidence.
