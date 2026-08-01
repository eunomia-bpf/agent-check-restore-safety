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

**Consumable Credentials** (Bauer, Garriss, and Reiter, NDSS 2007) already combines linear authorization logic with distributed ratification so that use-limited authority cannot be productively consumed more than once. It occupies “credentials can be copied syntactically but consumption is globally linear.”

**Capstone** (Yu et al., USENIX Security 2023), CHERI-style capability work, linear capabilities, and separation logics already occupy authority attenuation, transfer, revocation patterns, and resource composition. **DisLog** (POPL 2024) additionally reasons explicitly about nested fork-join structure. These works mean that “do not clone a one-shot token at fork” is not a paper-level novelty.

Surviving distinction: those systems do not, in the inspected models, define admission for a runtime operation that changes which previously alternative descendant claims may become durable together. Our claim must be about a changing durable-outcome contract, not about discovering linearity.

### 3.2 Rollback, fork detection, and monotone state

**Memoir** (IEEE S\&P 2011), **ROTE** (USENIX Security 2017), **LCM** (2017), and later TEE state-continuity work already establish that security-sensitive history cannot live only in rollbackable state. They use trusted nonvolatile summaries, distributed witnesses, or fork-linearizable views to prevent stale protected state from becoming current.

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

The surviving candidate contribution is a lifecycle security boundary:

> Replace and live restore may reconstruct the same computation yet require opposite admission decisions, so snapshot state alone cannot support sound and maximally permissive authorization. When a conditional claim escapes, the unique largest zero-capacity/no-other-cancellation repair retains exactly the old futures whose post-promotion load fits the grant.

This remains publishable only if the paper shows that (i) common agent lifecycle APIs genuinely change co-durability, (ii) nearby authorization and transaction models accept a violating history or reject a safe useful one, and (iii) the structured/unstructured representation choice creates a meaningful enforcement boundary rather than merely restating a textbook graph problem.

## 4. Current novelty verdict

| Candidate claim | Status | Reason |
|---|---|---|
| Non-rollbackable consumption state is necessary. | Established premise | Anti-rollback and consumable-credential work already owns it. |
| Forking must not clone linear authority. | Established premise | Linear capabilities and resource logics already own it. |
| Authority over co-durable descendant sets. | Promising semantic contribution | No equivalent agent lifecycle contract was found; event structures and linear resource logics provide substrates and strong conservation precedents. |
| Snapshot-local sound-and-maximally-permissive impossibility. | Leading, still closest-work sensitive | The replace/live indistinguishable worlds are checkpoint-specific; anti-rollback work already establishes the broader need for monotone history, so the paper must state the narrower novelty honestly. |
| Unique maximal safe escape-support restriction and promotion confluence. | Leading mathematical result | The filter is simple but gives an exact weakest lifecycle precondition and an order-independent batch rule; it must be proved and shown useful in a monitor. |
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

- `reference/closest-work/`: Consumable Credentials, Capstone, DisLog, Memoir, ROTE, LCM, ACRFence, Fork/Explore/Commit, Atomix, Cordon, DART, Ghost Tool Calls, Commit-Time Authorization, and Agent libOS.
- `reference/foundations/`: Winskel event structures, the Capability Calculus, resource-aware session types, and workflow concurrency-threshold analysis.
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
