# Literature, Novelty, and CSF Fit

**Status:** living claim-oriented audit, last updated 2026-08-01. A paper is listed here only after at least its abstract, introduction, claimed contributions, model, and evidence sections have been inspected. “Not found” means not found in the searched corpus, not a universal priority claim.

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

**Memoir** (IEEE S\&P 2011), **ROTE** (USENIX Security 2017), **LCM** (2017), and later TEE state-continuity work already establish that security-sensitive history cannot live only in rollbackable state. They use trusted nonvolatile summaries, distributed witnesses, or fork-linearizable views to prevent stale protected state from becoming current. **Crab** (arXiv 2026) instead targets agent sandbox recovery fidelity and efficiency: it classifies OS-visible effects and supports fault recovery, preemption, speculative execution, and RL rollout branching. Crab already owns the broad agent--OS semantic-gap and full-sandbox C/R story. Its correctness target is reconstruction of sandbox-local filesystem, process, and runtime state; it does not model an irreversible service outside that recovery domain, bounded authority, branch-conditioned reservations, co-durable outcomes, promotion, or merge admission.

[**Toward Systems Foundations for Agentic Exploration**](https://arxiv.org/abs/2510.05556) and its open-source [**StateFork**](https://github.com/Alex-XJK/StateFork)/[**Waypoint**](https://github.com/Alex-XJK/waypoint) stack make the adjacent systems boundary explicit. They provide snapshot/restore/fork abstractions over filesystem, process, shell, and terminal state, while identifying external side effects as requiring fork-aware services or interception. They therefore strengthen the workload premise and provide a future native C/R integration target; they do not supply the authority lineage, protected-effect receipts, or co-durability admission theorem studied here.

Surviving distinction: anti-rollback normally rejects or detects histories that diverge from a valid linear continuity relation. Agent exploration intentionally creates alternatives and sometimes preserves several outcomes. The new problem is to authorize this non-linear lifecycle without treating every fork as an attack or every branch as independently funded. The non-rollbackable ledger is a premise and enforcement substrate, not the contribution.

### 3.3 Transactions and external effects

**Atomix** separates execution, sealing, progress/frontier checks, and settlement for agent tool effects. **Cordon** defines semantic transaction boundaries for composed tool flows. **DART** asks whether a local rollback remains semantically recoverable after downstream commitment. Classic output-commit, sagas, durable execution, idempotency, and transactional outboxes already cover much of staged versus escaped effect handling.

Surviving distinction: transaction validity does not itself answer whether two individually well-formed branch effects are jointly authorized under one bounded grant. Our model imports staging/escape as effect facts, then checks an orthogonal typed-authority property over co-durable descendants. A decisive litmus must exhibit a history that is transaction-valid but authority-invalid.

### 3.4 Agent execution and authorization

**Fork, Explore, Commit** supplies nested branch contexts, isolated filesystem/process state, and first-commit-wins selection. **Agent libOS** exposes explicit capabilities, hierarchical budgets, child processes, checkpoints, and checkpoint-derived images. **Commit-Time Authorization** binds durable effects to authority that remains valid at settlement. **Ghost Tool Calls** shows that a losing speculative branch may leak information before selection. **ACRFence** already identifies semantic rollback, Action Replay, and Authority Resurrection after conversation restore. It proposes an irreversible-effect log and a prose classifier that returns a cached response for equivalent replay, blocks a semantically different call until an explicit fork/new branch is declared, and rejects obvious reuse of consumed credentials. Its paper explicitly leaves the mitigation unimplemented.

These papers make an agent wrapper insufficient. In particular:

- first-commit-wins safely handles choose-one output but says little about a later merge or live-original restore;
- a branch ID never creates new authority;
- a global capability ledger can safely delay delegation until selection, defeating any claim that authority must always be partitioned or conditionally reserved at fork time;
- commit-time freshness and pre-commit disclosure are adjacent lifecycle properties, not substitutes for bounded authority across compatible descendants;
- ACRFence must not be caricatured as permitting arbitrary credential reuse after a fork: it separately checks consumed credentials. Its precise open boundary is that a new branch identifier is not an authorization derivation. The policy does not define how bounded aggregate authority is split or conditionally shared, whether old and new branches may both become durable, or how restore and merge transport claims.

The paper must therefore attribute the external-effect rollback problem and the two named attacks to ACRFence rather than claim their discovery. The direct separating history begins *before* any effect exists: two alternative continuations receive advance promises backed by one bounded grant, a live restore or merge changes their co-durability, and both later issue distinct authorized actions. A pairwise post-effect replay classifier has no aggregate authorization fact with which to decide that history. ACRFence is a prose-policy baseline, not an implementation/performance baseline.

### 3.5 Concurrency structures and resource algebra

Winskel-style event structures already provide configurations, causality, conflict, and locally injective configuration-preserving maps. More directly, van Glabbeek and Plotkin's [configuration structures](https://arxiv.org/abs/0912.4023) model arbitrary permitted configuration families and explicitly encode ternary conflict: every pair may be permitted while the triple is forbidden. [Resource-Tracking Concurrent Games](https://link.springer.com/chapter/10.1007/978-3-030-17127-8_2) combines event-structure configurations with a resource algebra for sequential and parallel consumption. Process algebras, workflow nets, and resource analyses have long assigned resources to concurrent actions. Consequently:

- the use of a conflict/configuration model is proof machinery, not novelty;
- the all-pairs-but-not-the-triple promotion witness is established higher-order conflict, not by itself a new policy-language result;
- structured choice/parallel terms induce cographs: choice is graph join, parallel is disjoint union, and max/sum is the classical cotree dynamic program;
- maximum-weight independent set hardness follows directly once an arbitrary conflict graph and additive branch weights are chosen; workflow concurrency thresholds already use related reductions.

Primary anchors are van Glabbeek and Plotkin, “Configuration Structures, Event Structures and Petri Nets” (TCS 2009); Alcolei, Clairambault, and Laurent, “Resource-Tracking Concurrent Games” (FoSSaCS 2019); Corneil, Perl, and Stewart, “A Linear Recognition Algorithm for Cographs” (SIAM J. Computing 1985); Meyer, Esparza, and Völzer, “Computing the Concurrency Threshold of Sound Free-Choice Workflow Nets” (TACAS 2018); Terauchi and Aiken, “A Capability Calculus for Concurrency and Determinism” (CONCUR 2006); and Das, Hoffmann, and Pfenning, “Work Analysis with Resource-Aware Session Types” (LICS 2018). The audit therefore treats configuration expressiveness, the resource algebra, conservation pattern, and complexity boundary as established machinery.

The operational left side of Boundary II is also established concurrency structure. Flanagan and Godefroid define independence by preservation of enabledness plus commutation; Katz and Peled permit state-predicate conditional independence; van Glabbeek and Plotkin's asynchronous step requires every intermediate configuration; and Fecher and Majster-Cederbaum model set-indexed disabling followed by remainder cleanup. Thus “all schedules exist,” conditional commutativity, and executed work deleting disabled future work are not new. No inspected source, however, derives the paper-specific guard

\[
K_O=\bigwedge_{b\in O}\mathsf{Supp}_b(F_O)
\]

from exact authority promotion and proves it complete for both the fixed-batch asynchronous cube and equality with an atomic seal. The defensible delta is this closed-form authority certificate and refinement, not a new notion of concurrency or serializability. Its proof must be translated to the real `PrepareOK` transition and mechanized before it can carry a headline claim.

The surviving candidate contribution is an action-class authorization boundary:

> For fixed-topology batch Reserve, a checkpoint may omit a correlated residual admission profile. That profile factorizes into a Cartesian product of noncommunicating branch-local budgets exactly at a closed-form rectangularity boundary. Conditional-to-durable promotion can force higher-order policy, and final-owner support exactly characterizes when every owner-group order remains enabled under immediate cleanup.

This remains publishable only if the paper shows that (i) common agent lifecycle APIs genuinely change co-durability, (ii) nearby authorization and transaction models accept a violating history or reject a safe useful one, and (iii) final-owner support is derived as a complete authority-specific guard rather than inherited as a generic concurrency result. Step 0006 found no literal prior theorem, but also found that generic independence, full-cube, disruption, and selected-order feasibility structure are established. Headline mechanization and an agent-specific versioned lifecycle refinement now remain the current CSF-theory blockers.

### 3.6 Safe-order synthesis and atomic repair

Under the paper's fixed-batch assumptions, selected-order synthesis is simpler
than the initial subset-DP proposal. Let `p_b` be owner `b`'s promoted vector,
`r_b` its full tentative demand, `d` the durable load, and
`h_b = G - d - r_b`. Source owner support, downward closure, nonnegative
demand, and `p_b <= r_b` make the singleton `{b}` the cheapest support witness:

\[
\mathsf{Supp}_b(F_S) \quad\Longleftrightarrow\quad
\sum_{a\in S\setminus\{b\}}p_a\le h_b.
\]

Thus a forward owner order is safe exactly when each owner's predecessor load
fits its vector start deadline. Backward peeling repeatedly chooses any owner
`b` in the remaining set `R` satisfying
`sum_{a in R \ {b}} p_a <= h_b`. Eligibility is monotone as `R` shrinks, so
any choice is complete. Emptying `R` yields a safe order; a stuck, choice-
independent residual yields a compact no-order certificate by naming, for each
residual owner, one overloaded coordinate. The direct implementation costs
`O(n^2 k)` arithmetic, or `O(n^2)` generic support queries; the scalar case is
ordinary earliest-due-date scheduling. Boundary II is exactly the corollary in
which every owner is eligible in the initial remaining set, hence every order
works.

This abstract algorithm is not new. Möhring, Skutella, and Stork's
*Scheduling with AND/OR Precedence Constraints* gives the same peeling
feasibility algorithm and generalized-cycle obstruction after reversing the
minimal authority-killer relation. Arbach et al.'s conflict-free Dual Event
Structure traces express the same AND-of-OR prerequisite rule. Ardila and
Maneva show that a process in which an element, once removable, remains
removable is an antimatroid/pruning process with a unique residual core.
Consequently, killer hypergraphs, arbitrary eligible choice, and the dead core
are reusable machinery, not a headline contribution. The authority-specific
benefit is a compact derivation from vectors, avoiding an exponentially large
explicit killer family and emitting arithmetic certificates.

A more useful fallback is *serial or seal*: serialize owners that peeling can
remove, then execute a chosen remainder `H` in one final atomic Prepare. A
candidate exact criterion requires peeling to empty `P \ H` and every
`b in H` to remain supported after that prefix. The internal Step 0006 proof
gives a minimum-cost formulation that is weakly NP-complete even for a scalar
pure-choice contract, and an explicit rank-two killer reduction from Vertex
Cover. These hardness facts are not by themselves novel: Jain, Hajiaghayi, and
Talwar already study minimum-cost generalized AND/OR deadlock repair, while
transaction chopping and dynamic-causality event structures cover adjacent
atomic grouping and changing-dependency structure. The reductions must also be
independently reviewed and mechanized before entering the paper.

The plausible new package is therefore a version-bound authority certificate:
derive vector deadlines from conditional-to-durable promotion; return a safe
order, dead core, or explicit atomic seal; and prove which Fork/Restore/Merge/
Abort/Revoke transitions preserve the certificate and which invalidate it
before Dispatch. Static peeling is the runtime algorithm. Lifecycle refinement,
crash-stable installation with a prepared effect ticket, and enforcement at a
real agent dispatch boundary must carry the agent-specific novelty.

### 3.7 Supervisory control, partial observation, and guarded workflows

Ramadge--Wonham supervisory control already asks for the largest legal behavior obtainable by disabling controllable events. Under full observation, supremal controllable sublanguages and fixpoint algorithms are classical. Under partial observation, the boundary is more delicate: standard observability is not closed under union, so a unique supremal observable-and-controllable sublanguage need not exist. Cieslak, Desclaux, Fawaz, and Varaiya established this partial-observation setting; Cai, Zhang, and Wonham later introduced relative observability, which fixes an ambient language, is union-closed, and therefore recovers a computable supremal policy at the cost of a stronger condition.

Two structured-control results are especially close. Ma and Wonham's state-tree structures use hierarchical AND/OR state organization, predicates, BDDs, and recursive symbolic synthesis to obtain optimal nonblocking supervisors. Feng, Wonham, and Thiagarajan synthesize control logic for communicating transaction processes and translate it into propositional guards on message-sequence charts. Consequently, this project must not claim the following as new:

- maximally permissive control as a generic objective;
- guards, predicates, BDDs, or AND/OR state trees as a generic representation;
- supervisor synthesis under partial observation;
- translating a safety policy into guarded workflow execution.

The useful connection is instead a scope test and a source of proof machinery. A snapshot-only hook is a partially observing controller. A durable claim certificate refines its observation. General partial-observation synthesis may lack a unique most-permissive policy, so the paper must not make that claim for arbitrary hidden lifecycle events.

The surviving specialization is an *online authority-support transformer* for a dynamically created agent history. Its plant is not a fixed workflow known before synthesis: branch epochs, effect bindings, typed claims, and merge projections are created during execution. Escape changes a claim from branch-conditional support to durable support, and the effect gate must linearize accounting before an external observation. The candidate new results are therefore limited to this semantics: an exact criterion for compiling correlated residuals into independent capabilities; a cleanup-aware iff criterion for promotion serialization; non-closure of pure choice/parallel contracts under authority promotion; and an exact threshold repair with lineage transport. Freezing is an explicit no-silent-policy-expansion rule, not a generic AC necessity. Classical supervisory control remains the encompassing control-theoretic framework.

This comparison changes the intended wording from “authority-controller synthesis under partial observation” to “a certificate-checked online specialization of supervisory control for authority support in history-transforming runtimes.” It also creates a hard novelty obligation: if the final theory only adds threshold predicates to an AND/OR tree, it is not a CSF contribution.

### 3.8 Agent trajectories and the observability boundary

Real trajectories are necessary for workload grounding, but they answer a
different question from the safety theorem. They can show which lifecycle
operations, retries, tool failures, and outward-facing commands occur; they
cannot prove authority continuity. The source-audited assets divide into three
evidence families:

| Asset | Evidence available | Use here | Missing security state |
|---|---|---|---|
| [Trace Commons Agent Traces](https://huggingface.co/datasets/trace-commons/agent-traces) | Pinned public revision `112ebd4d03ce852b00e935d523107c3d0c9a65bf`; all 30 donated sessions were read through the Dataset Viewer, comprising 18,012 trace events, 4,264 tool calls, 4,262 results, and 953 file-history snapshots | Direct schema-level contrast between a real runtime's recoverable file history and tool activity aimed at repositories, processes, networks, databases, packages, and deployment systems; also exposes two calls with no matching result | No trusted semantic Fork/Restore edge, authority/grant lineage, effect phase, durable receipt, compensation/idempotence contract, or relation between a local snapshot and external truth; the sample is small and Claude-Code-heavy |
| [UW TraceLab v0.0.2](https://github.com/uw-syfi/TraceLab/releases/tag/v0.0.2) ([paper](https://arxiv.org/abs/2606.30560)) | Fixed public release with 665,453 Claude/Codex rounds, 8,058 sessions from 52 deduplicated users, and 743,819 tool records; all rows were mechanically scanned at SHA-256 `11ce51ec0a25e3d1d95b025bca2f7d1647e47571eb7cc968acd5fc64d4b4fb65` | Strongest ungated real-runtime workload and ordinary-telemetry audit: ordering, tool correlation, errors, process continuations, and orchestration-like tool names | Public normalization omits semantic fork/restore parentage, authority/grant lineage, protected effect identity and phase, durable external state/receipt, and a crash-relative-to-effect boundary |
| [SWE-chat](https://huggingface.co/datasets/SALT-NLP/SWE-chat) ([paper](https://arxiv.org/abs/2604.20779)) | 5,851 in-the-wild coding sessions, 2,692,480 transcript entries, 13,406 checkpoints, 14,459 commits, and full tool/command/diff fields across Claude Code, Codex, Gemini CLI, and others | Primary natural-workload census for checkpoints, continuation, subagents, Git history changes, and commands that may cross the workspace boundary | Checkpoint is a save point, not a typed Restore event; no grant/claim lineage, durable-support contract, stable cross-retry effect identity, effect phase, or external before/after state |
| [General AgentBench trajectories](https://huggingface.co/datasets/cx-cmu/agent_trajectories) | 8,653 controlled trajectories over SWE, terminal, search, MCP, and stateful tool benchmarks, with messages, tool calls, rewards, and evaluation details | Cross-domain check that retries, failures, and stateful operations are not coding-only phenomena | Four passes are independent fresh attempts, not forks; exact generation-time tool menu is not always reconstructable; no authority or topology semantics |
| [Agent LLM Traces](https://huggingface.co/datasets/DiscoPosse/agent-llm-traces) | 1,781 OpenTelemetry-style traces with timestamps, tool definitions/calls/results, response IDs, token use, and error status; a six-row public pilot found repeated call signatures under different IDs | Timing, fan-out, failure, retry-candidate, and ordinary telemetry-schema audit | Calls/results repeat inside cumulative messages; current Viewer schema has no parent span or independent tool-execution span, branch lifecycle, authorization lineage, protected-effect phase, or durable external receipt |
| [Microsoft Orchard](https://huggingface.co/datasets/microsoft/Orchard) | 107,185 software-engineering trajectories plus 3,070 GUI rollout prefixes; public Viewer/download, structured calls, and resolved/unresolved metadata | Large controlled workload, negative-outcome, and command-schema control | Independent sandbox rollouts are not history-transforming continuations and omit trusted authorization/external-effect history |
| [WebArena](https://github.com/web-arena-x/webarena) and [WebArena-Verified](https://github.com/ServiceNow/webarena-verified) | Stateful self-hosted web tasks plus Playwright/network traces and HAR/evaluator artifacts for selected trace families | Demonstrates that some public assets expose external request order and task-specific durable state beyond a filesystem | No history-transforming lifecycle, capability provenance, stable protected-effect/idempotency contract, or crash boundary; benchmark reset is not the paper's durable multi-owner world |
| [AgentRx](https://github.com/microsoft/AgentRx) and [coding-agent-misalignment](https://github.com/ND-SaNDwichLAB/coding-agent-misalignment) | Failure taxonomies and a replication package studying 20,574 real coding sessions | Select failure classes and manually audit damaging history changes | Taxonomy/issue evidence is not a complete executable lifecycle trace |

The [Agent Data Protocol](https://github.com/neulab/agent-data-protocol)
standardizes ordinary call correlation as `tool_call_id` and links an
observation with `source_call_id`. This is valuable interchange machinery, but
call correlation is not an authorization or idempotency contract: it does not
say whether a call was prepared, dispatched, uncertain, retried as the same
protected operation, or charged to a durable claim.

The inspected product interfaces expose a useful split. The official
[Codex App Server protocol](https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md)
has thread/turn/call identifiers, records `forkedFromId`, and can send an
experimental dynamic-tool request to the client. It is therefore the leading
dispatch-owning adapter path. Claude Code's official
[checkpoint limitations](https://code.claude.com/docs/en/checkpointing#limitations)
explicitly exclude Bash modifications, most subagent edits, and external or
concurrent-session changes, directly demonstrating that checkpoint state and
the effect-bearing world have different rollback domains.

This schema audit suggests, but does not yet prove, a stronger result. Define
three observation maps: `O0` retains checkpoint/workspace state, `O1`
also retains ordinary session/call/result telemetry, and `O2` additionally
retains trusted lifecycle, authority-lineage, and effect-lifecycle events. A
decision fiber is keyed by the same next request:
`K_i=(alpha(O_i(prefix)), normalize(next_action))`, with run-local IDs
alpha-renamed, alias/order structure preserved, and absolute timestamps
removed. A nontrivial theorem program would establish:

1. **ordinary-trace insufficiency** with independent `O1`-equivalent witness
   families: replacing versus live Restore for topology; two claims mapped to
   one one-unit grant versus distinct transferred fragments for authority;
   and remote-success-before-crash versus never-dispatched (or
   retry-versus-new-operation) for effects;
2. **componentwise necessity or an information lower bound:** erasing topology
   lineage, authority lineage, or stable effect identity/phase from `O2`
   recreates a corresponding pair with different safe decisions; and
3. **conditional replay sufficiency:** authenticated, self-contained `O2`
   events reconstruct the initial `LifecycleState`, each abstract label and
   successor state, and the checker decision; the corresponding concrete edges
   then prove a `SimulatedTrace`, assuming complete mediation, a
   non-rollbackable anchored log, validated certificates, and a truthful
   idempotent/queryable sink.

The first topology pair alone reuses the existing snapshot
indistinguishability corollary; logging every checker field and rerunning the
checker would be tautological. The observability result becomes a distinct
contribution only if it characterizes an irredundant event basis, a minimal
observation quotient, or a comparable monitorability boundary. Otherwise it
remains motivation for the public schema study and controlled traces. No
audited public asset contains the trusted joint lifecycle, authority,
durable-support, protected-effect, crash-boundary, and ordering state required
for exact admission. Individual components do exist: LangSmith exposes
call-tree parentage and order, SWE-chat links checkpoints to Git outcomes, and
WebArena exposes some external requests/state. The defensible result is joint
insufficiency, not that every ordinary trace lacks every component.

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
| Promotion non-closure plus authority-support guards and lineage transport. | Supporting specialization | Configuration structures already own higher-order conflict/propositional configuration families. The remaining value is deriving the exact frozen row from irreversible promotion and preserving it through lifecycle lineage, not discovering non-pairwise policy. |
| Universal owner-group serializability iff final support. | Leading but acceptance-blocked | Captures the operational interaction between exact promotion and deterministic branch cleanup; absent support constructs a failing order, while final support protects every prefix. It must now be separated theorem-by-theorem from configuration filtering/supervisory enabledness and mechanized over its stated assumptions. |
| Ordinary-trace non-identifiability and a compact authority/effect replay schema. | Candidate extension | Available schemas correlate tool calls but omit trusted topology, claim/grant lineage, effect phase, and durable receipts. It is a distinct result only if independent witnesses plus an irredundancy, lower-bound, or observation-quotient theorem go beyond the existing snapshot corollary; otherwise the schema is supporting instrumentation. |
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

Trajectory dataset cards and available schemas were inspected through their
primary repositories on 2026-08-01; representative Viewer rows were inspected
for Agent LLM Traces and Orchard SWE. TraceLab v0.0.2 was downloaded to an
ephemeral directory, hash-verified, and mechanically scanned in full; the
release URL and SHA-256 above pin the analyzed bytes, while no user content or
bulk trace file is retained in the repository. SWE-chat and General AgentBench
require accepting gated access terms and sharing contact information. Orchard revision
`70c05ec1f20f823ae6adc60374922e9271bb74e2` is public/ungated and its Viewer is
live. The current environment is not authenticated, so the study plan must not
report SWE-chat or General AgentBench rows as locally analyzed.

## 7. Writing consequence

The introduction must not begin with LLM nondeterminism or duplicate UUIDs. It should begin with two executions that copy the same checkpoint but differ only in the runtime's durable-outcome contract. The headline is a missing authorization boundary for history-transforming computation; tool-using agents make that boundary common because they combine cheap branching, long-lived delegated authority, external effects, human resume, and semantic merge.

The paper can honestly target CSF if it delivers:

- one compact operational model with explicit trusted and rollbackable state;
- a security property independent of the enforcement rules;
- an exact lifecycle-admission theorem plus at least one non-definitional separation or lower bound;
- a mechanized conservation proof and generated counterexamples for weakened rules;
- a small deterministic monitor/explorer and limited real-runtime evidence.
