# Workload Shift, System Boundary, and the Role of PL

## 1. The workload changed from executing a history to editing a space of histories

The important change is not that an LLM is nondeterministic. Traditional systems already contain nondeterminism, concurrency, rollback, and external I/O. The change is that an agent runtime makes **history transformation a normal programming operation**:

- it creates several candidate continuations intentionally rather than only after a failure;
- it keeps old checkpoints addressable and may resume them repeatedly;
- a “restore” may replace the current continuation or create another live one;
- subagents reserve authority and interact with tools before a winner is selected;
- operators and models dynamically change whether branches are alternatives or may coexist;
- merge combines semantic artifacts and provenance from histories that were previously incompatible;
- effects cross many rollback domains, including services, humans, logs, messages, and uncertain network sends.

A traditional recovery question is usually: *which prefix is the valid history, and how can execution continue consistently from it?* The new question is: *which sets of descendants may still contribute to the durable result, which promises were made in each descendant, and which observations have already escaped every possible rollback?*

This moves the security object from one current state to a family of possible durable futures.

## 2. Four kinds of state replace the fiction of one checkpointable state

An agent's relevant state has at least four components:

| Component | Examples | May a workspace checkpoint overwrite it? |
|---|---|---|
| Reconstructable computation | files, prompts, model context, plans, cached observations, staged payloads | yes, within the checkpoint's actual coverage |
| Lifecycle control | live branch epochs, exclusive/parallel structure, durable selection, tombstones, merge eligibility, restore mode | no; it determines which histories remain possible |
| Authorization history | issued grants, claim identity, ownership, reservations, consumption, revocation epochs | no; rolling it back resurrects or duplicates authority |
| External history | payments, messages, disclosures, remote writes, receipts, uncertain sends, human knowledge | generally no; compensation is a new effect, not erasure |

No storage technology gives a meaningful “rollback everything” operation over this product. A filesystem snapshot covers only part of the first row. A database transaction covers one service. A remote observer or a human is not inside either boundary. Even if a system could kill every local continuation, deleting durable selections, revocations, or consumption records would make the restored execution less secure.

Full rollback is also the wrong policy for intentional exploration. Restore-live is supposed to retain the old continuation; best-of-N is supposed to keep alternatives until selection; merge is supposed to retain information from more than one branch. Safety must classify these histories rather than erase the features that created them.

## 3. What changes relative to traditional mechanisms

### Checkpoint and rollback protection

Classic crash recovery usually seeks one consistent continuation. TEE rollback protection and fork-detection systems treat divergent histories as an attack to prevent or expose. Agent runtimes intentionally create divergence and sometimes intentionally retain several outcomes. “Reject every fork” therefore destroys the workload, while “accept every named fork as fresh” creates authority.

### Transactions and durable execution

Transactions answer whether a set of effects settles atomically and recovery observes a consistent transaction history. They do not by themselves answer whether two individually valid transactions are jointly entitled to consume two uses of a one-use grant. Transaction validity and authority solvency are independent dimensions. The proposed monitor imports staging/outbox machinery; it does not replace it.

### Capabilities and per-action reference monitors

A conventional capability names who may perform which operation on which resource. Linear capabilities additionally prevent one token from being copied into concurrent owners. That is necessary but too coarse for intentional alternatives:

- splitting one capability at every fork is safe but rejects the useful promise “either candidate may deploy if selected”;
- copying it into both branches is unsafe if both may later commit;
- parent escrow is safe for pure speculation but offers no advance branch-local guarantee;
- per-action checking sees the action that happens now, not all branch commitments the runtime has promised may later settle.

The missing dimension is a claim's **future support**: the durable outcomes in which its demand must be funded. In the current model,

\[
\mathsf{supp}(c)=
\begin{cases}
\{C\in\Phi\mid b\in C\}, & c\in Q_b,\\
\Phi, & c\in D,\\
\varnothing, & c\in X.
\end{cases}
\]

Thus an authority claim is not only an identity, binding, owner, and quantity. It is a contingent liability indexed by possible futures. Exclusive branches can reuse collateral because their supports never overlap in one frontier. Parallel branches require the sum because their supports overlap. Escape is a support expansion from “futures retaining branch \(b\)” to “every remaining future.” Merge can create new overlap between supports that used to be exclusive.

This is the conceptual difference from both a flat capability ledger and a workspace safety model.

The corresponding authorization state is not just a scalar “remaining budget.” For one fresh reservation on branch \(b\), the exact answer is the minimum headroom over every still-permitted future containing \(b\). For a batch across branches, the exact state is a correlated downward-closed region of additional branch-indexed demands. Exclusive and parallel contracts can expose the same per-branch headroom while accepting different batches. This correlation is why a checkpoint containing only local capability balances cannot precisely authorize later fork, merge, or parallel delegation.

The correlated residual region has an operational advantage: in the Reserve-only fragment, accepting a batch \(x\) updates the residual by residuation, retaining exactly those \(y\) for which \(x+y\) was previously admitted. Per-branch headroom lacks this update property. Lifecycle transformations then act on this residual structure: selection restricts it, live restore and merge change its correlation, and escape changes both durable load and the support policy.

There is an exact boundary for turning this correlated object back into conventional branch-local capabilities. Let \(\operatorname{Box}(H)\) be the product of every supported branch's headroom interval. The residual factorizes iff the all-headroom corner satisfies every permitted durability configuration. Only then can noncommunicating branch checkers be simultaneously sound for arbitrary concurrent Reserve and complete for each branch in isolation. If the criterion fails, a runtime must preserve a shared coordinator/escrow, reduce at least one delegated capability, or restrict which descendants may coexist. Choice can pass this test while a live restore or merge that turns the same branches parallel fails without changing either local balance.

## 4. The system is a lifecycle-aware authorization settlement layer

The trusted path has three cooperating mechanisms:

1. **Lifecycle controller.** It durably records branch epochs and the contract describing which branches may be retained together. Replace, live restore, selection, abort, and merge are security events, not UI labels.
2. **Authority ledger.** It records fresh claim IDs, typed demand, effect bindings, conditional ownership, durable/uncertain consumption, terminal IDs, and closed grant epochs. It is monotone where rollback would be unsafe.
3. **Effect gate.** It stages effects where possible, promotes a claim before dispatch, persists an uncertain record before a possibly ambiguous send, and reconciles only with trusted sink evidence.

The untrusted model may propose a tool call or lifecycle change. It cannot certify semantic equivalence, claim binding, exclusivity, or a successful undo. Those facts come from typed tool schemas, issuers, the controller, and effect protocols. An LLM classifier may help outside the TCB, but a positive classifier result is not authorization evidence.

This architecture adds a reserve--transform--promote--settle protocol to ordinary per-action authorization:

- **Reserve:** make an enforceable conditional promise in a branch.
- **Transform:** fork, restore, select, abort, or merge the future contract.
- **Promote:** when an effect escapes, change its support to durable history and admit the resulting contract.
- **Settle:** dispatch only after durable accounting; never let abort erase settled or uncertain consumption.

## 5. What formal semantics and PL contribute

The value of PL is not decorative notation and not a proof that “the implementation checks the invariant it checks.” It supplies abstractions that separate four questions commonly conflated in agent systems.

### A lifecycle calculus

An operational semantics gives names to replace versus live restore, conditional versus durable claims, staged versus escaped effects, contextual restore, and policy-explicit merge. This prevents security arguments from relying on ambiguous product verbs such as “rewind,” “fork,” or “commit.”

### Linear, graded, and modal structure

Three established PL ideas have distinct jobs:

- **linear/affine ownership** prevents one claim ID from being copied or resurrected;
- **graded resource tracking** records typed vector demand and derives exact admission conditions;
- **possible-world/modal indexing** records the future support of a promise and how lifecycle operations transform it.

The novelty should not be claimed for any one ingredient. The paper-level object is their combination at a runtime boundary where the possible-world frame itself changes through restore, escape, and merge.

### Abstraction and refinement

A concrete runtime contains payloads, queues, logs, epochs, receipts, and scheduler detail. The abstraction \(\alpha\) keeps only the facts relevant to authorization. A soundness theorem can then show that an abstract authority-continuous state covers every concrete resolution even when the future family conservatively over-approximates reality. A reverse result needs stronger exactness and joint-realizability assumptions and must not be advertised generally.

### Exact safe transformations and representation boundaries

Instead of merely rejecting an unsafe escape, the semantics derives the largest abstract subfamily of old futures that remains safe. The nontrivial implementation question is whether that family can still be represented by the runtime's contract language. Promotion can turn a choice/parallel tree into a higher-order constraint that permits every pair of three branches while forbidding their triple. A threshold row represents this exact restriction compactly. Freezing enforces a no-silent-policy-expansion/audit rule; a later load decrease may justify explicit safe re-admission, but must not mutate a past durable decision. A zero-preserving lineage projection transports the row across later fork, restore, and merge, with predicate-circuit size counted in the representation.

This exposes two semantic costs that an allow/deny API hides. First, filtering can remove owner support or an old co-durability configuration, both of which must be reported. Second, abstract batch filters may commute while operational serialization fails because the first repair tombstones the owner of a later effect. Final-owner support is necessary and sufficient for every ordering of atomic per-owner groups to remain enabled; otherwise arbitrary order is not guaranteed, so the runtime must validate an order, coordinate cleanup, or seal the fixed batch before dispatch.

### Certificate-checked refinement

A topology-changing adapter must preserve durable consumption, terminal IDs, receipts, and inflight/uncertain tickets; it then supplies a monotone, zero-preserving projection from target configurations to source configurations and an injective tentative-claim transfer. A local demand-dominance obligation proves that every target outcome is simulated by a solvent source outcome. Escape uses a different certificate: an exact frozen guard plus a one-shot durable effect ticket. These obligations define the abstract preservation proof; a concrete runtime theorem additionally requires a complete-mediation refinement.

### Counterexample generation and mechanization

An executable finite model finds short counterexamples when a premise is removed. A proof assistant can check the load algebra, downward-closure arguments, claim partition, promotion rules, and transition invariant. These artifacts are especially valuable here because several plausible informal claims fail: internal alternatives invalidate an unqualified abstraction converse; over-approximated frontiers invalidate completeness; context-free live restore creates the wrong compatibilities; and abort cannot delete escaped claims.

## 6. What can be proved

Subject to explicit assumptions, the formal layer can establish:

| Result | Meaning | Essential assumptions |
|---|---|---|
| Authority-continuity soundness | every lifecycle-permitted durable outcome fits the typed grant | actual outcomes are contained in the trusted future contract; bindings and claim identities are valid |
| Conditional completeness | an abstract violation corresponds to a concrete insolvent resolution | exact future family and jointly realizable conditional bundles |
| One-branch headroom characterization | minimum slack over configurations containing a branch accepts exactly its fresh Reserve proposals | safe source state, supported owner, additive coordinate-complete demands, fixed topology |
| Headroom non-updateability | equal per-branch balances can lead to different successor balances after the same accepted Reserve | controller retains only headroom and loses cross-branch correlation |
| Correlated residual controller | the downward residual region accepts exactly all Reserve batches and updates by \(\mathcal R_{\Sigma+x}=\{y\mid x+y\in\mathcal R_\Sigma\}\) | fixed-topology Reserve-only fragment, common structural signature, and nonnegative additive demand |
| Exact decentralization boundary | a Cartesian product of noncommunicating branch-local budget checkers is concurrently sound and one-branch complete iff the residual equals the product of its headroom projections | fixed-topology batch Reserve, supported branches, common structural signature |
| Knowledge-safe one-step checker | intersecting structural acceptance and residual profiles is the greatest sound checker for one observation fiber | memoryless one-step decisions; full precision requires identical concrete acceptance sets, not merely identical snapshot bytes |
| Snapshot-local impossibility | restored bytes alone cannot support both sound and maximally permissive admission | replace/live worlds can expose the same local observation; checker lacks durable lifecycle facts |
| Claim conservation | fork/restore cannot duplicate an issued claim and terminal IDs cannot revive | fresh global IDs, linearized ledger updates, no bypass |
| Non-resurrection | restore cannot reopen a closed branch or grant epoch or erase durable consumption | monotone durable ledger and epoch fencing |
| Compact promotion closure | one vector-threshold row exactly represents the largest topology-only safe pruning for fixed claims | finite downward-closed contract, additive nonnegative demand; freezing additionally assumes no silent policy expansion |
| Base-contract non-closure | promotion can create a higher-order conflict not representable by choice/parallel or pairwise conflict | unique-leaf base grammar and the stated four-branch witness |
| Owner-liveness criterion | exact pruning preserves one support witness per owner iff each owner occurs in the repaired family | this does not preserve every prior co-durability correlation, which must be reported separately |
| Guard transport | lineage substitution preserves the meaning of durable guards across lifecycle refinement | adapter supplies a truthful monotone, zero-preserving projection and pays for its predicate circuit |
| Universal owner-group serializability | every owner-group ordering remains enabled and reaches the atomic denotation iff every promoted owner has final support | valid batch, exact prefix guards, fixed lifecycle state, deterministic immediate cleanup |
| Structured checker correctness | choice uses max, parallel uses sum, exactly matching enumerated frontiers | unique leaves and the structured contract grammar |
| Trace safety | every protected effect has one matching durable claim before dispatch and every trace prefix preserves authority continuity | all relevant operations go through the controller and gate; local simulation/guard certificates hold; crash atomicity satisfies the modeled order |

These are conditional security guarantees, as all meaningful systems theorems are. Their value is that the conditions identify the TCB and produce separating tests rather than remaining hidden in prose.

## 7. What the formal layer cannot prove by itself

The current theory cannot establish:

- that a natural-language request was correctly bound to the issuer's intended operation, resource, amount, or recipient;
- that two semantically different tool calls are equivalent, or that an LLM classifier is adversarially robust;
- that an external service executed exactly once, tells the truth, or supports atomic cancellation;
- that an unknown network send did not arrive; the model can only charge it conservatively;
- that a real runtime exposes every branch, bypass-free tool call, restore, merge, or crash edge assumed by the semantics;
- that the durable store is actually crash-atomic, rollback-resistant, authenticated, and available without a refinement or implementation proof;
- confidentiality, quantitative information leakage, liveness, fairness, or low overhead, unless those properties are modeled and measured separately;
- temporal, bundled, replenishing, compensable, or noncommutative authority under the current additive natural-number algebra;
- that the trusted lifecycle contract \(\Phi\) is truthful if an untrusted agent is allowed to invent exclusivity.

These are not small caveats. They divide the paper's evidence plan. Proof and finite exploration support the semantic claims. Typed bindings and protocol design justify the TCB. Runtime litmus tests establish correspondence to real APIs. Microbenchmarks support only implementation-cost claims. No amount of additional theorem proving substitutes for the last two, and no number of prompt experiments substitutes for the first.

## 8. Consequence for the paper

The paper should not be framed as “a safer checkpoint implementation.” Its larger claim is:

> Agent execution has become a history-transforming workload. Authorization must therefore account not only for current capability ownership, but also for contingent commitments over the set of futures the runtime still permits. Restore, escape, and merge are support-transforming authorization events.

The most useful PL contribution is a small future-indexed authority calculus with a precise proof boundary. The most useful systems contribution is the lifecycle/ledger/effect-gate contract that makes the calculus enforceable. Experiments remain deliberately narrow: show that real runtimes expose the modeled distinctions, validate the executable rules and counterexamples, and measure only the monitor operations actually implemented.
