# Authority Continuity for History-Transforming Agents

**Status:** Revision-4 scientific contract. The executable Python model checks the bounded instances reported in the paper. A Lean 4 finite-carrier submodel machine-checks selected lifecycle/trace obligations, but an independent mixed verdict keeps it out of the paper until canonical topology construction and certificate checking replace the generic target-WF interface.

## 1. The missing boundary

Agent runtimes copy and recombine computation through checkpoint, restore, best-of-\(N\), parallel subagents, human edit-and-resume, and merge. Authority and external effects do not follow the same rollback rules.

The key distinction is not “state versus external resources” alone. It is between:

- a **conditional commitment** that a branch may exercise only if a compatible future is retained; and
- a **durable consumption** that every future must now account for because an effect escaped the rollback boundary.

Pure computation may be copied freely. Conditional authority may be shared among futures that are guaranteed to be mutually exclusive. It cannot be copied into futures that may survive together. Most importantly, a conditional claim cannot simply escape from a speculative branch: escape promotes it into consumption charged to every remaining future.

The proposed paper contribution is a concrete lifecycle semantics and its adequate abstract authority contract. Linear resources, append-only ledgers, event structures, cograph dynamic programming, and maximum-weight independent set are prior machinery, not claimed as new.

The sharper thesis is:

> A checkpoint is missing not generic “history,” but the minimal residual authorization profile for the next action class. Single-branch Reserve needs a headroom vector; joint Reserve, fork, and merge need a correlated downset; and escape promotion can force the policy representation beyond a choice/parallel topology into quantitative durable guards.

## 2. Threat and trust model

The agent, model output, branch-local workspace, model context, plans, and tool arguments are untrusted. The runtime may crash or restore any reconstructable state. An operator may invoke documented fork, restore, abort, and merge operations. External services may expose non-idempotent or information-revealing effects.

The trusted computing base contains:

- an issuer or deterministic policy that assigns grant ID, type, scope, epoch, binding, and demand;
- a non-rollbackable ledger;
- the branch lifecycle controller that decides commit eligibility, selection, tombstones, and merge;
- a staging/dispatch gate and durable receipt or conservative uncertain-dispatch record.

The model does not trust an LLM to decide whether two effects are semantically equivalent. An LLM may propose a typed binding, but the trusted policy must accept it.

The guarantee is authorization integrity for bounded, noncompensable effects. It does not guarantee exactly-once execution at an arbitrary Byzantine sink, infer user intent, or make an already leaked secret retractable.

## 3. Concrete runtime state

A concrete state has two rollback domains.

### Reconstructable state

\(V_b\) contains the workspace, model context, plan, staged payloads, and other branch-local values for branch epoch \(b\). A checkpoint contains \(V_b\) plus references into the durable ledger. It does not contain authoritative copies of claims, grant epochs, receipts, or branch eligibility.

### Durable security state

The ledger records:

- issued capacity and grant epochs;
- globally unique claim IDs and their current owner;
- live and tombstoned branch epochs;
- conditional reservations;
- durable selections, transfers, aborts, merges, and revocations;
- escaped-effect receipts and uncertain dispatches.

A conditional reservation is a real runtime promise, not merely an agent intention:

> if its branch is retained under the declared lifecycle contract and the grant is not revoked, the claim can pass the trusted commit gate without acquiring new authority.

This promise makes topology relevant. A delayed-escrow implementation that gives pure candidates no advance claim is safe and is represented by empty branch reservations until selection.

Each \(Q_b\) is a **conjunctive bundle**: all of its claims are assumed jointly realizable if \(b\) is retained. An internal either/or action must be exposed as a lifecycle choice with separate branches. Without this condition, summing \(Q_b\) is only a conservative upper bound and the exactness direction of the abstraction theorem is false.

An effect is **staged** only if it remains behind a trusted gate. A remote read, secret-bearing query, notification, or ambiguous dispatch may be externally observable at issue time and therefore counts as escaped even if it performs no remote write.

## 4. Abstract authority contract

### 4.1 Typed capacity and claims

Let \(\mathcal K\) be a finite set of authority coordinates. A coordinate is refined enough to fix issuer, scope, grant epoch, and resource type; for example, “one charge to account \(a\) under approval epoch \(\nu\),” not merely “one payment.”

Issued capacity is

\[
G\in\mathbb N^{\mathcal K}.
\]

Each claim \(c\) has a globally unique ID, an effect binding, and demand

\[
w(c)\in\mathbb N^{\mathcal K}.
\]

Issued claim IDs form a global disjoint partition

\[
I_{\mathrm{issued}}
=
D\;\dot\cup\;X\;\dot\cup\;\dot\bigcup_{b\in B}Q_b.
\tag{P}
\]

\(D\) contains durable or conservatively uncertain consumptions. \(X\) contains cancelled or terminal claim IDs, which can never be reused. \(Q_b\) contains conditional commitments owned by live branch epoch \(b\). Partition (P) prevents restore or fork from placing the same claim in two branches. A fresh copied claim is a second claim and contributes a second demand.

Only tentative \(Q_b\) claims require a currently live grant and branch epoch. Claims in \(D\) are historical consumption and remain recorded after their epoch closes.

### 4.2 Co-durable futures

Let \(B\) be the live branch epochs and let

\[
\Phi\subseteq 2^B
\]

be a nonempty, downward-closed family. \(C\in\Phi\) means that every branch in \(C\) is allowed to have its reserved outcomes retained together. Downward closure says discarding additional tentative branches remains possible.

The runtime, not the agent, vouches for \(\Phi\). A false “exclusive choice” label is a violation of the trusted lifecycle contract. If \(\Phi\) over-approximates actual outcomes, (AC) remains sound but can reject a concretely safe state. Exactness requires \(\Phi\) to characterize the normatively selectable outcomes exactly and every \(Q_b\) bundle to be jointly realizable.

Define

\[
d=\sum_{c\in D}w(c),
\qquad
q(C)=\sum_{b\in C}\sum_{c\in Q_b}w(c).
\]

For vectors, \(\bigvee\) is the componentwise supremum. Then

\[
M(\Phi,Q)=\bigvee_{C\in\Phi}q(C),
\qquad
\mathsf{need}(\Sigma)=d+M(\Phi,Q).
\]

### 4.3 Authority continuity

The abstract state is authority-continuous iff every lifecycle outcome can honor all of its admitted commitments:

\[
\boxed{
\mathsf{AC}(\Sigma)
\;\stackrel{\mathrm{def}}{\Longleftrightarrow}\;
\forall C\in\Phi.\ d+q(C)\le G.
}
\tag{AC}
\]

Equivalently, \(\mathsf{need}(\Sigma)\le G\). The vector supremum need not be realized by one frontier; it exactly characterizes componentwise safety.

Non-numeric well-formedness additionally requires unique branch labels, the claim partition, live scope/binding for tentative claims, once-only dispatch per claim (or a stable sink operation ID), and monotonic branch/grant epochs.

## 5. Authority-support contracts

### 5.1 Base topology

Common runtimes can expose an explicit base contract

\[
P ::= \mathbf 0 \mid b \mid P\mathbin{\Box}P \mid P\parallel P,
\]

where every branch label occurs once, \(\Box\) retains at most one alternative, and \(\parallel\) may retain both sides. Its downward-closed durability configurations are

\[
\begin{aligned}
\Phi(\mathbf0)&=\{\varnothing\},\\
\Phi(b)&=\{\varnothing,\{b\}\},\\
\Phi(P\Box Q)&=\Phi(P)\cup\Phi(Q),\\
\Phi(P\parallel Q)&=\{C\cup C'\mid C\in\Phi(P),C'\in\Phi(Q)\}.
\end{aligned}
\]

This is an AND/OR state tree. Its conflict graph is a cograph and its max/sum admission recurrence is classical. Neither fact is claimed as new.

### 5.2 Frozen support guards

Pure choice/parallel topology is not closed under support-changing effects. We therefore extend it with durable guard rows:

\[
T ::= P \mid T\wedge h,
\qquad
h=(\{(a_i,\lambda_i)\}_{i=1}^{m},r).
\]

Here \(a_i,r\in\mathbb N^{\mathcal K}\) are frozen constants and \(\lambda_i:2^B\to\{0,1\}\) is an explicitly represented monotone, zero-preserving lineage predicate. A configuration satisfies the row iff

\[
C\models h
\quad\Longleftrightarrow\quad
\sum_i a_i\lambda_i(C)\le r.
\]

The semantics intersects the base family with every row. Nonnegative coefficients and monotone predicates preserve downward closure; zero preservation keeps the empty configuration. At creation, \(\lambda_b(C)=\mathbf1[b\in C]\). Under the controller's no-silent-policy-expansion rule, the row is frozen and never reads current \(Q\). Withdrawal may make an explicitly re-admitted expansion authority-safe, but it must not silently mutate a durable audited decision. Predicate-circuit size is part of the representation.

Lifecycle refinement transports a row through a monotone, zero-preserving projection \(\pi:2^{B'}\to2^B\) by substituting \(\lambda_i\leftarrow\lambda_i\circ\pi\). For example:

- replace \(b\) by \(b'\): \(z_b\leftarrow z_{b'}\);
- refine \(b\) into live descendants \(R\): \(z_b\leftarrow\bigvee_{x\in\mathsf{Leaves}(R)}z_x\);
- merge: the operation must supply and pay for an explicit projection circuit, since copied files do not determine which source lineages the result inherits.

The disjunction is important. If two parallel descendants are retained, an old lineage coefficient is charged once, not copied twice.

### 5.3 Support and induced cancellation

Define

\[
\mathsf{supp}_T(b)=\{C\in\Phi(T)\mid b\in C\}.
\]

A conditional commitment owned by \(b\) is live only if \(\mathsf{supp}_T(b)\ne\varnothing\). Restricting a contract can remove every support for another owner; this is semantically a cancellation even if no \(Q_b\) field was explicitly edited. Retaining one witness per owner does not preserve every old co-durability configuration. A conforming implementation must therefore return both unsupported owners and removed maximal configurations/correlation obligations, tombstone unsupported owners, and move their tentative claims to \(X\). It may not call the operation “no-other-cancellation.”

## 6. Certificate-checked lifecycle semantics

### 6.1 Configurations, proposals, and effect labels

The abstract durable controller state is

\[
A=(G,N,B,D,X,Q,T,J,R),
\]

where \(N\) records grant and branch epoch status, \(J\) maps stable protected operation IDs to one-shot \(\mathsf{prepared}\), \(\mathsf{inflight}\), or \(\mathsf{uncertain}\) tickets, and \(R\) contains settled receipts. Reconstructable values \(V\) are paired with \(A\) in a concrete state but are not authoritative. \(G\) is the historical capacity issued for each typed grant epoch. Revocation closes an epoch to new Reserve/Prepare; it does not erase capacity, past consumption, or an operation already sealed before revocation.

Controller proposals are

\[
\begin{split}
u ::= {}&\mathsf{reserve}(b,c)\mid\mathsf{fork}_{\Box/\parallel}(E[b],\rho)
\mid\mathsf{select}(S)\mid\mathsf{abort}(b)\\
&\mid\mathsf{restore}_{\mathsf{replace/live}}(E[b],\rho)
\mid\mathsf{merge}(T',\pi,\rho)\mid\mathsf{prepare}(S,\bar e)\\
&\mid\mathsf{checkpoint}\mid\mathsf{dispatch}(e)\mid\mathsf{retry}(e)
\mid\mathsf{crash}\mid\mathsf{settle}(e,o)\mid\mathsf{revoke}(\nu),
\end{split}
\]

The transition relation is the least relation generated by the paper's rules. A transition is \(A\xrightarrow{u/\eta}A'\), with \(\eta=\tau\) for internal control or \(\eta=\mathsf{attempt}(e,c)\) for a protected sink attempt. Dispatch and Retry may expose the same stable \((e,c)\); effect accounting aggregates them by operation ID.

### 6.2 Local simulation certificates

For a topology-changing transition that does not add durable consumption, the adapter supplies a monotone, zero-preserving projection \(\pi:2^{B'}\to2^B\) and a claim transfer map. The certificate obligations are:

1. \(G,D,J,R\) are preserved exactly; \(X\) and epoch closure are monotone;
2. every target configuration maps to an allowed source configuration;
3. every target tentative claim is unchanged or a fresh issuer-approved fragment of one source claim; per-source fragment demand is conserved, images are disjoint, and eliminated source IDs move to \(X\);
4. binding, scope, and open-epoch checks hold; and
5. for every target configuration \(C'\),
   \[
   d'+q'(C')\le d+q(\pi(C')).
   \tag{SIM}
   \]

Condition (SIM) proves target demand is simulated by an already solvent source rather than assuming the target satisfies (AC). Structured fast paths have compositional proof objects; guarded targets may use a global oracle to produce a proof checked by the small trusted checker. General Reserve and Merge without simulation use a direct-admission certificate.

The rules are:

- **Checkpoint:** copy \(V\) and ledger references; \(A\) is unchanged.
- **Choice/parallel fork:** replace the leaf in its context; claims are transferred, partitioned, escrowed, or cancelled exactly once. Copying \(V\) never copies a claim.
- **Select/abort:** durably restrict \(T\), tombstone eliminated epochs, and move their tentative claims to \(X\). This is a load-decreasing fast path.
- **Restore-replace:** contextual alpha-renaming plus a binding-preserving fragment transfer is a simulation fast path.
- **Restore-live:** replace \(E[b]\) by \(E[b\parallel b']\), transport old guards by lineage disjunction, and start the clone empty or partition claims without duplication.
- **Merge:** supply \(T'\), tombstones, transfers, and \(\pi\). A workspace diff is not a certificate.
- **Revoke:** close the epoch, cancel its tentative claims, and retain \(D\), \(X\), issued IDs, and receipts.

### 6.3 Prepare before dispatch

For a batch \(S\) of tentative claims, let

\[
d_S=d+\sum_{c\in S}w(c),
\qquad
a_{S,b}=\sum_{c\in Q_b\setminus S}w(c),
\qquad
r_S=G-d_S.
\]

If \(r_S\ngeq0\), topology restriction alone cannot cover even the empty configuration. Otherwise define the frozen repair row

\[
H_S(C)\quad\Longleftrightarrow\quad
\sum_{b\in C}a_{S,b}\le r_S.
\tag{GRD}
\]

The formal `prepare` rule atomically:

1. moves every \(c\in S\) from \(Q\) to \(D\);
2. conjoins the frozen row \(H_S\) with \(T\);
3. records a fresh prepared ticket \(J(\bar e(c))=(c,\mathsf{prepared})\) for each claim, plus support witnesses, removed correlations, or explicit induced cancellations; and
4. persists the new state hash before returning the ticket.

`dispatch(e)` changes prepared to inflight and emits \(\mathsf{attempt}(e,c)\). Crash maps inflight to uncertain while leaving prepared work intact. Retry from inflight/uncertain emits another attempt with the same stable \((e,c)\) and returns the phase to inflight; coverage requires trusted deduplication or an aggregate demand bound. `settle(e,o)` consumes the ticket into a receipt; a prepared ticket may settle only as cancelled. Neither path returns the claim to \(Q\) or removes it from \(D\).

The trusted gate must cover every protected dispatch. A hook that observes only some tool paths is an adapter, not the complete trusted computing base.

## 7. Central results

### Theorem 1: abstract preservation and concrete refinement

For the abstract rules, a well-formed authority-continuous source remains well formed and authority-continuous after every admitted transition. Every attempt uses a stable ID and a matching claim already in \(D\); Retry cannot allocate a new logical operation or claim. A closed epoch authorizes no new Reserve/Prepare, although an operation sealed before closure may finish because its demand is already durable.

The proof checks (SIM), load-decreasing rules, exact Reserve, (GRD), claim movement, and ticket phases by cases. A separate refinement corollary says that a completely mediated concrete adapter whose steps simulate these rules inherits trace-prefix solvency. That corollary is an implementation obligation, not evidence that today's optional product hooks already provide complete mediation.

### Theorem 2: residual authorization is the missing checkpoint state

For \(C\in\Phi(T)\), define its componentwise slack

\[
s_\Sigma(C)=G-d-q(C).
\]

For a supported branch \(b\), define single-branch headroom

\[
H_\Sigma(b)=
\bigwedge_{\substack{C\in\Phi(T)\\b\in C}}s_\Sigma(C),
\]

where \(\bigwedge\) is componentwise minimum and an unsupported branch has value \(\bot\). A fresh \(\mathsf{reserve}(b,w)\) is safe exactly when its structural/binding checks hold and \(w\le H_\Sigma(b)\). If proposals include every natural amount in every coordinate, two states authorize exactly the same single-branch Reserve proposals iff their structural predicates and \(H\) agree. Thus \(H\) is fully abstract for one-step single-branch Reserve.

Let \(B^+=\{b\mid H_\Sigma(b)\ne\bot\}\); unsupported branches are structurally ineligible for Reserve.

Headroom is not an update-closed controller state. With \(G=1\), no current claims, and two branches, exclusive choice and parallel composition both have \(H=(1,1)\). Both accept one unit for \(b_1\), but afterwards their headroom is respectively \((0,1)\) and \((0,0)\). No deterministic updater can derive exact new headroom from old \(H\) and the accepted action alone; the missing information is cross-branch correlation.

The exact correlated residual profile is

\[
\mathcal R_\Sigma=
\left\{
x\in\mathbb N^{B^+\times\mathcal K}
\ \middle|\
\forall C\in\Phi(T).\ \sum_{b\in C}x_b\le s_\Sigma(C)
\right\}.
\tag{RES}
\]

It is precisely the set of simultaneous fresh reservation batches that can be added. For the Reserve-only fragment it is also update-closed:

\[
x\in\mathcal R_\Sigma
\Longrightarrow
\mathcal R_{\Sigma+x}
=
\{y\mid x+y\in\mathcal R_\Sigma\}.
\tag{RESID}
\]

Consequently \(\mathcal R_\Sigma\) is a fully abstract residual controller state for arbitrary sequential or simultaneous Reserve, while \(H\) is only its collection of single-branch slices. The same choice/parallel pair separates them: each branch alone has one unit of headroom, but the batch assigning one unit to both is accepted only by choice.

Let \(\operatorname{Box}(H)=\{x\mid0\le x_b\le H_\Sigma(b)\}\). The residual's projection on each branch is exactly its headroom interval, and

\[
\mathcal R_\Sigma=\operatorname{Box}(H)
\quad\Longleftrightarrow\quad
\forall C\in\Phi(T).\ \sum_{b\in C}H_\Sigma(b)\le s_\Sigma(C).
\]

This is the exact decentralization boundary. If it holds, independent branch-local capabilities are sound for arbitrary concurrent Reserve and complete for each branch alone. If it fails, a runtime must retain correlated coordination/escrow, reduce at least one local budget, or restrict the lifecycle. The fixed choice state is rectangular; the parallel/live state with the same \(H=(1,1)\) is not.

Topology changes, promotion, revocation, and dispatch require more than the Reserve residual. Let

\[
\mathcal A(h)=(G,N,B,D,X,Q,T,J,R,\mathsf{bindings})
\]

be the durable projection of history \(h\). Equality of \(\mathcal A\), modulo fresh-ID renaming, is sufficient for all controller decisions. Its component classes are necessary by paired replay, resurrection, clone-duplication, choice/parallel, scope-substitution, and uncertain-dispatch histories. The tuple may be quotiented further by full future authorization equivalence; the claim is not that its byte encoding is globally minimal.

The theorem's systems consequence is precise: checkpoint safety is missing the residual authorization profile for the action class, not an undifferentiated copy of “history.” That profile may be held in a global ledger or a fresh authenticated residual certificate; the theorem does not prescribe one storage architecture.

### Theorem 2b: exact precision loss under partial observation

For an observation \(o\), let \(K(o)\) be the reachable concrete authority states consistent with it. Define

\[
H_o^K(b)=\bigwedge_{\Sigma\in K(o)}H_\Sigma(b),
\qquad
\mathcal R_o^K=\bigcap_{\Sigma\in K(o)}\mathcal R_\Sigma.
\]

The unique pointwise-greatest sound memoryless one-step checker accepts \(\mathsf{reserve}(b,w)\) exactly when every possible state satisfies the structural premises and \(w\le H_o^K(b)\), and accepts a batch \(x\) exactly when it is structurally admissible everywhere and \(x\in\mathcal R_o^K\). It is as precise as every concrete-state checker iff the concrete action-acceptance sets are identical across the observation fiber. Under constant structural admissibility and a coordinate-complete proposal space, this reduces to constancy of \(H_\Sigma\), respectively \(\mathcal R_\Sigma\). Otherwise the intersection measures the exact safe false-rejection boundary.

This is a closed-form specialization of classical knowledge-based control, not a claim about a full supremal nonblocking supervisor. Trace safety still requires complete mediation and induction over gated transitions. Snapshot-only replace/live ambiguity is one fiber with nonconstant residual profiles.

### Theorem 3: promotion destroys base-contract representability

Let

\[
P=b\Box(x\parallel y\parallel z),
\]

give each branch one scalar unit, and set \(G=3\). The source is safe. After promoting \(b\)'s claim, the largest safe restriction permits every singleton and every pair among \(x,y,z\), but forbids their triple. No unique-leaf choice/parallel contract, and no pairwise conflict graph, represents this family: allowing every pair forces the conflict graph to have no edge, which also permits the triple.

Thus exact authority promotion can introduce a higher-order conflict even when the source lifecycle is a structured tree. This is the representation gap hidden by the old abstract-filter theorem.

### Theorem 4: compact exact closure under promotion

For any finite contract \(T\) and batch \(S\) with \(r_S\ge0\),

\[
\Phi(T\wedge H_S)
=
\{C\in\Phi(T)\mid d_S+q_S(C)\le G\}.
\]

Hence one new vector-threshold row with \(O(|B||\mathcal K|)\) coefficients and singleton lineage tests exactly represents the unique largest topology-only safe pruning for fixed claims, without enumerating configurations. Existing predicate circuits and later projection-composition size are counted separately. The construction strictly extends base choice/parallel expressiveness by Theorem 3.

The theorem is a closure result for this authority-support transformation, not a claim that threshold predicates or guarded state trees are new. Installing the row is a semantic lifecycle restriction and must be explicitly authorized. Freezing is the additional audit rule that forbids implicit later expansion; a load decrease may instead trigger an explicit re-admission. If repair eliminates owner support or old correlations, those changes must be returned.

### Theorem 5: owner-liveness criterion

Let \(O=\{b\mid Q_b\ne\varnothing\}\). The exact promotion repair preserves at least one support witness for every existing owner iff

\[
\forall b\in O.\ \exists C\in\Phi(T\wedge H_S).\ b\in C.
\]

If the condition fails for \(b\), no smaller topology restriction can preserve \(b\)'s support, because every safe restriction is a subset of the exact filter. The runtime must therefore acquire capacity, reject/delay the effect, or explicitly cancel the unsupported promise. Even when the condition holds, old joint configurations can disappear; the API must also report removed maximal configurations or declared correlation obligations. This corrects the false “promise-preserving/no-other-cancellation” wording.

### Theorem 6: guard transport and universal owner-group serializability

Composing each frozen predicate with a zero-preserving lifecycle projection \(\pi\) preserves its old meaning under fork, restore, and explicit merge. Adjacent disjoint promotions over the same lifecycle state have the same denotational contract in either order because the final row for \(S\cup T\) implies both intermediate rows.

For a valid batch \(U\), group its claims by owner. Under exact prefix repair, fixed lifecycle state, and deterministic immediate cleanup, every owner-group order remains enabled and reaches the atomic batch's denotation iff each promoted owner has support in the final repaired family. Sufficiency follows because the final family is contained in every prefix family. For necessity, put an unsupported owner last: promoting its own claims would not change load on configurations containing it, so the other groups already remove all its support and cleanup disables it. If the condition fails, effects must be prepared atomically as one batch or replanned.

### Theorem 7: honest complexity boundary

Membership of one concrete retained set in a sparse guarded contract is linear in the contract representation. Pure base contracts admit the classical \(O(|P||\mathcal K|)\) cotree recurrence. In contrast, universal admission for compact guarded contracts is coNP-complete even with an all-parallel base and one scalar guard: its complement asks whether a subset satisfies one knapsack capacity while exceeding a value threshold.

Practical implementations can compile small quotas to a ZDD, use pseudo-polynomial residual-capacity dynamic programming, or invoke an incremental pseudo-Boolean solver. A solver timeout fails closed. Crucially, exact escape repair itself constructs (GRD) directly and does not solve the global optimization problem; optimization is needed to prove a row redundant, admit a new unrestricted promise, or find globally preferred cancellations.

### Corollary: snapshot-only checking is imprecise

Replace and live restore can reconstruct the same \(V_r\) while their durable contract and old-branch eligibility differ. A one-unit Reserve is safe in the replacing world and unsafe in the parallel live world. Any snapshot-only checker makes the same decision in both, so it is either unsound or rejects a safe proposal. This is one componentwise-necessity witness for Theorem 2 and an instance of partial-observation control, not a claim that a global ledger is the only possible remedy.

## 8. Minimal separating executions

### Safe choice, unsafe plain escape

Let \(G=1\), \(D=\varnothing\), and two exclusive branches each hold a one-unit claim. The state is safe. Moving one claim into \(D\) while the other alternative remains possible yields load two in the other frontier. This is the counterexample that forces escape admission.

### Safe choice, unsafe merge

Two one-unit commitments are safe under \(b_1\Box b_2\). A merge that retains both converts their relationship into co-durability and must acquire capacity, cancel one commitment, or reject the merge.

### Restore bytes do not determine authority

Restore-replace and restore-live can reconstruct identical \(V\). In the first, the old epoch is durably dead; in the second it remains a parallel continuation. A snapshot-local checker observes the same bytes but the lifecycle contract and valid claim assignments differ.

### Transaction-valid, authority-invalid

Two staged tool transactions can each be internally valid and settle cleanly while their jointly retained effects consume two claims from a one-unit grant. Transaction integrity does not imply authority continuity.

### Pure delayed escrow

Two alternatives compute with empty \(Q\); the parent transfers one claim only after durable selection. This is safe in both a flat ledger and the proposed model. It prevents the paper from claiming topology is necessary when no advance commitment exists.

## 9. Mechanization and executable validation

The dependency-free Python artifact mirrors the finite mathematics rather than simulating an LLM. It exhaustively checks authority continuity, headroom admission, correlated residual batch admission and derivatives, exact promotion guards, the higher-order representation witness, frozen versus dynamically recomputed guards, lineage transport, and the scoped batch-order condition. Checked JSON is deterministic and must be reproduced byte for byte. These checks find modeling errors and validate finite witnesses; they are not proofs for unbounded states.

The first Lean 4 pass now defines finite typed vectors, downward-closed durability families, a structural claim partition with distinct unissued/terminal states, executable AC admission, computed restriction, exact Prepare/cleanup, stable tickets and receipts, terminal/epoch monotonicity, a labeled trace simulation, effect coverage, and a conditional trace-solvency theorem. These results quantify over arbitrary finite carrier types and pass a clean build, source/axiom audit, and fresh kernel replay.

The independent result review is mixed. The topology constructor's load-solvency consequence is derived from source AC and a simulation inequality, but its structural target WF is supplied fieldwise by a logical `TopologyShape` certificate. The development does not yet construct the paper's canonical Fork/Restore/Merge targets, check `Mono_0(pi)` or `rho` fiber conservation, issue fresh fragments, or mechanize Boundaries I/II. The current result therefore remains internal; the next mechanization must close this exact interface rather than enlarging claims around it.

The runtime study is deliberately small. One mandatory tool proxy or dispatch-owning SDK/App Server client should instantiate fresh branch epochs, Prepare-before-Dispatch, stable operation IDs, and conservative uncertain outcomes. Product hooks alone demonstrate lifecycle correspondence but not complete mediation. Performance numbers are paper-worthy only after that path actually enforces every protected effect.

## 10. Novelty boundary and falsifiers

The paper does **not** claim novelty for:

- linear or consumable authority;
- BI-style resource composition, residuation, or the additive derivative identity in isolation;
- non-rollbackable ledgers and epoch fencing;
- event-structure configurations;
- choice/max and parallel/sum resource algebra;
- cograph dynamic programming or MWIS hardness;
- generic maximally permissive supervisory control, partial-observation synthesis, guards, predicates, or BDDs;
- transactions, effect staging, or stable idempotency tokens.

The claim survives only if the following package is absent from prior work and operationally meaningful: a closed-form action-class residual for co-durable conditional authority; the strict separation between one-branch headroom and an update-closed correlated residual; lifecycle transformations that change authorization equivalence without changing reconstructed bytes; promotion-induced nonclosure of a natural choice/parallel policy; compact frozen-guard completion; and the owner-support/atomic-seal bridge to external effects.

It fails if conditional commitments cannot be distinguished from mere intentions, if topology labels cannot be trusted, if all useful workloads can delay authority transfer until selection, if an equivalent co-durable residual controller already exists, or if no deployable boundary can completely mediate the claimed external effects. The paper must narrow rather than relabel classical resource or supervisory-control results if any of these falsifiers fires.
