# Authority Continuity for History-Transforming Agents

**Status:** BOOTSTRAP scientific contract. Definitions and results are proposed until their paper proofs and Lean development are complete.

## 1. The missing boundary

Agent runtimes copy and recombine computation through checkpoint, restore, best-of-\(N\), parallel subagents, human edit-and-resume, and merge. Authority and external effects do not follow the same rollback rules.

The key distinction is not “state versus external resources” alone. It is between:

- a **conditional commitment** that a branch may exercise only if a compatible future is retained; and
- a **durable consumption** that every future must now account for because an effect escaped the rollback boundary.

Pure computation may be copied freely. Conditional authority may be shared among futures that are guaranteed to be mutually exclusive. It cannot be copied into futures that may survive together. Most importantly, a conditional claim cannot simply escape from a speculative branch: escape promotes it into consumption charged to every remaining future.

The proposed paper contribution is a concrete lifecycle semantics and its adequate abstract authority contract. Linear resources, append-only ledgers, event structures, cograph dynamic programming, and maximum-weight independent set are prior machinery, not claimed as new.

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

## 5. Structured lifecycle contracts

Common runtimes can expose an explicit contract

\[
P ::= \mathbf 0 \mid b \mid P\mathbin{\Box}P \mid P\parallel P,
\]

where every branch label occurs once, \(\Box\) retains at most one alternative, and \(\parallel\) may retain both sides. Its downward-closed frontiers are

\[
\begin{aligned}
\Phi(\mathbf0)&=\{\varnothing\},\\
\Phi(b)&=\{\varnothing,\{b\}\},\\
\Phi(P\Box Q)&=\Phi(P)\cup\Phi(Q),\\
\Phi(P\parallel Q)&=\{C\cup C'\mid C\in\Phi(P),C'\in\Phi(Q)\}.
\end{aligned}
\]

The conflict graphs induced by this grammar are cographs: choice is graph join, parallel is disjoint union, and the syntax tree is a cotree. The familiar recurrence

\[
\begin{aligned}
R(\mathbf0)&=0,\\
R(b)&=\mathsf{load}(Q_b),\\
R(P\Box Q)&=R(P)\vee R(Q),\\
R(P\parallel Q)&=R(P)+R(Q)
\end{aligned}
\]

is the classical weighted-independent-set dynamic program on cographs. We use it as an implementation corollary, not a new algorithm.

A general downward-closed family need not be representable by pairwise conflict. Three branches may be pairwise compatible while the triple is forbidden. General semantics therefore uses \(\Phi\); a graph is used only under an explicit pairwise-decomposable assumption.

## 6. Lifecycle rules and weakest admission conditions

Every rule has a linearization point in the durable ledger.

### Issue and acquire

An issuer creates fresh grant capacity or explicitly extends compatible coordinates of \(G\). Creating a process, branch, checkpoint, image, or claim ID never issues authority.

### Reserve

Add a fresh claim \(c\) to \(Q_b\) only when its branch and grant epoch are live, its binding is valid, partition (P) is preserved, and the target state satisfies (AC).

### Checkpoint

Copy \(V_b\) and durable references. The abstract authority state does not change.

### Choice and parallel fork

Fork may copy \(V_b\), but it may not copy claims. Existing \(Q_b\) claims must be transferred exactly once, partitioned among children, retained by an explicit parent escrow, or moved to \(X\). A pure child begins with \(Q=\varnothing\).

Choice installs \(\Box\); parallel fork installs \(\parallel\). Any claim reassignment is admitted against the target state.

### Durable select and abort

Selection durably restricts \(\Phi\) and tombstones losing epochs before releasing their tentative claims. Abort of \(b\) simultaneously removes every frontier containing \(b\), tombstones its epoch, and moves \(Q_b\) into \(X\). It never removes \(D\), reopens an epoch, or clears an uncertain dispatch. Withdrawing an individual claim is itself a durable weakening of the branch's conjunctive guarantee, not a free mutation.

For a selected branch \(b\), define

\[
\Phi{\downarrow}b
=
\{C'\mid \exists C\in\Phi.\ b\in C\land C'\subseteq C\}.
\]

### Escape and uncertain dispatch

For \(c\in Q_b\), plain escape proposes

\[
D'=D\cup\{c\},
\qquad
Q'_b=Q_b\setminus\{c\},
\]

without changing \(\Phi\). This target must be admitted before external observation. Accounting occurs before dispatch; a crash with unknown sink outcome leaves \(c\in D\).

Let

\[
M_{\neg b}
=
\bigvee_{\substack{C\in\Phi\\b\notin C}}q(C).
\]

The exact additional capacity for plain escape is

\[
\boxed{
\Delta_{\mathrm{esc}}(b,c)
=
[d+w(c)+M_{\neg b}-G]^+.
}
\tag{E}
\]

Frontiers containing \(b\) see no load change; frontiers not containing \(b\) inherit the newly universal \(w(c)\). This is why an issue-time effect in a speculative branch cannot rely only on choice sharing.

There are several safe ways to proceed:

1. keep the effect staged until durable selection;
2. restrict the lifecycle to the maximal safe family defined in Section 7, promote \(c\), then dispatch;
3. atomically condition the lifecycle on \(b\), move eliminated tentative commitments to \(X\), promote \(c\), then dispatch;
4. acquire at least \(\Delta_{\mathrm{esc}}\) compatible capacity.

### Restore-replace

For a structured context \(E[b]\), atomically tombstone the old continuation and replace it by \(E[b']\) with a fresh epoch. Transfer an old tentative claim exactly once only if its issuer permits the transfer and the staged object needed by its binding remains durably available or is proven binding-equivalent after restore; otherwise move it to \(X\). Reconstruct \(V\) from the snapshot but validate all references against the current ledger. A binding-preserving alpha-renaming with exact transfer preserves need.

### Restore-live

For a structured context \(E[b]\), retaining the old continuation replaces the leaf by \(E[b\parallel b']\), not by \(E[b]\parallel b'\). This preserves every conflict inherited from the surrounding context. The restored branch starts with empty \(Q\) or receives a nonduplicating, issuer-permitted partition of existing claims. The restore operation itself need not create a deficit; copying old claims, subsequent reservations, or later reclassifying exclusive outcomes as co-durable does.

### Merge

Merging only reconstructable values has no authority effect. There is no unique authority topology induced by a workspace merge, so every authority-bearing merge supplies an explicit target policy \(\Phi'\), source tombstones, and claim transfers. A join-merge may replace sources already contained in one co-durable cone; an alternative-synthesis merge creates a new topology and is admitted as an extension. Claims transfer exactly once, subject to binding preservation. Claims already in \(D\) are never transferred or erased.

### Revoke

Close the durable grant epoch, move its tentative commitments into \(X\), and forbid new reserve/escape under it. Historical \(D\) remains recorded. A restored snapshot retains a stale reference, not revived authority.

## 7. Proposed central results

### Theorem 1: abstraction soundness and conditional exactness

Assume the concrete runtime enforces claim uniqueness, trusted staging, once-only or conservatively charged dispatch, and actual frontiers are contained in \(\Phi\). Then \(\mathsf{AC}(\alpha(s))\) implies that every concrete lifecycle resolution is solvent.

The converse holds only if \(\Phi\) exactly characterizes normatively selectable outcomes and every retained \(Q_b\) is a conjunctive, jointly realizable bundle. Under those assumptions, a violating frontier witnesses an insolvent concrete resolution. We keep the one-way theorem as the general guarantee and state the conditional converse explicitly rather than hiding exactness in the definition.

### Theorem 2: lifecycle preservation

Starting from a well-formed authority-continuous state, Issue, admitted Reserve, Checkpoint, nonduplicating fork, durable Select/Abort, admitted Escape, both restore rules, admitted Merge, and Revoke preserve:

1. authority continuity;
2. the global claim partition including terminal set \(X\);
3. monotonic durable consumption;
4. non-resurrection of closed branch and grant epochs.

The proof is induction over concrete transitions and their abstraction. Escape requires its target admission or one of the promotion rules below; without it, the theorem is false. Contextual restore and policy-parametric merge make the target topology explicit rather than hiding safety in UI names.

### Theorem 3: maximal safe escape support

For \(c\in Q_b\), define its post-promotion load on an old frontier:

\[
\ell'_{b,c}(C)
=
d+w(c)+q(C)-\mathbf 1_{b\in C}w(c).
\]

Define

\[
\Phi^*_{b,c}
=
\{C\in\Phi\mid \ell'_{b,c}(C)\le G\}.
\tag{M}
\]

\(\Phi^*_{b,c}\) is downward closed. Promoting \(c\) while restricting the lifecycle to \(\Phi^*_{b,c}\) is safe without new capacity or cancellation of any other claim. Moreover, \(\Phi^*_{b,c}\) is the unique inclusion-largest topology restriction with those properties: every safe \(\widehat\Phi\subseteq\Phi\) for the same promoted target satisfies \(\widehat\Phi\subseteq\Phi^*_{b,c}\).

This is the most permissive abstract zero-capacity repair. It can retain safe futures not containing \(b\) when slack exists.

### Lemma 4: witnessed escape promotion

In an authority-continuous state, atomically restricting the lifecycle to \(\Phi{\downarrow}b\), moving eliminated branch claims to \(X\), moving \(c\in Q_b\) into \(D\), and only then dispatching preserves (AC) without new capacity.

For a target frontier not containing \(b\), downward closure and the definition of \(\Phi{\downarrow}b\) provide an old frontier containing that target together with \(b\); its old safe load already includes \(c\). This is the formal justification for “stage until a durable resolution witnesses \(b\).” It is a conservative instance of Theorem 3: \(\Phi{\downarrow}b\subseteq\Phi^*_{b,c}\), sometimes strictly.

### Theorem 5: batched promotion confluence

For a finite set \(S\) of tentative claims, with \(\beta(c)\) denoting the owner of \(c\), define

\[
\ell'_S(C)
=
d+\sum_{c\in S}w(c)+q(C)
-\sum_{c\in S,\,\beta(c)\in C}w(c)
\]

and \(\Phi^*_S=\{C\in\Phi\mid \ell'_S(C)\le G\}\). If the empty frontier fits after promotion, this is the unique largest zero-capacity, no-other-cancellation restriction for the batch. For disjoint \(S,T\), sequential maximal repairs in either order equal the repair for \(S\cup T\). Promotion can only preserve or increase the load of an old frontier, so a frontier removed by the first filter cannot become safe after the second promotion. The final claim partition and surviving frontier family are therefore order independent.

### Theorem 6: snapshot-local monitor impossibility

Consider the same restored bytes \(V_r\), one-unit grant, and one-unit Reserve proposal for restored branch \(r\). In a replace world, the old branch is tombstoned and the proposal is safe. In a live world, the old branch \(b\) remains parallel with \(r\) and holds a one-unit commitment, so the same proposal is unsafe.

Any checker whose decision is a function only of \(V_r\) and the proposal returns the same answer in both worlds. Acceptance is unsound in the live world; rejection is not maximally permissive in the replace world. Therefore a checker that is both sound and complete relative to (AC) must consult durable lifecycle and claim state. Snapshot bytes alone are insufficient.

This theorem is specific to the checkpoint lifecycle distinction. It does not claim a topology-aware monitor is necessary for pure delayed-escrow computation.

### Repair taxonomy

In the monotone, additive, noncompensable model, an unsafe target can be repaired by acquiring compatible capacity, weakening still-tentative guarantees, or restricting/delaying the lifecycle. This is a useful implementation taxonomy, not a headline theorem: it follows from the fields on which (AC) depends. Trusted negative receipts, stable-ID coalescing, compensation, renewable quotas, and protocol changes add operations outside the current model.

### Corollary 6: weakest quantitative repair

For a fixed proposed target \(\widehat\Sigma'\) with no cancellation and freely extensible independent coordinates, the least additional vector is

\[
[\mathsf{need}(\widehat\Sigma')-G]^+.
\]

This is ordinary componentwise monus and is not claimed as new mathematics. Equation (E) is its escape-specific form.

### Corollary 7: inherited algorithmic boundary

For structured contracts, the classical cograph cotree recurrence computes exact need in \(O(|P||\mathcal K|)\). If pairwise conflict is instead supplied as an arbitrary graph \(H\), scalar unsafety

\[
\exists I\text{ independent in }H.\ \sum_{b\in I}q_b>G
\]

is NP-complete and universal safety is coNP-complete, inherited directly from Independent Set/MWIS. Explicitly enumerated frontiers are scanned in polynomial time, and many restricted graph classes remain tractable. These are representation consequences, not headline novelty.

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

Lean 4 should define the concrete/abstract states, claim partition, frontier family, lifecycle rules, and abstraction. The minimum checked result set is:

- abstraction soundness and the realizability-qualified reverse direction;
- lifecycle preservation;
- plain-Escape counterexample;
- exact Escape formula;
- maximal safe escape support and witnessed promotion;
- snapshot-local monitor impossibility;
- structured recurrence correctness.

An executable explorer should mutate one premise at a time and synthesize the shortest violating history. A small deterministic monitor should implement structured admission and compare snapshot-local clone, split-all, delayed escrow, transaction-only, and topology-aware conditional commitments.

The empirical role is limited: instantiate the separating executions in at most two agent runtimes, identify their true restore/selection/merge contract, and measure only monitor operations that are actually implemented.

## 10. Novelty boundary and falsifiers

The paper does **not** claim novelty for:

- linear or consumable authority;
- non-rollbackable ledgers and epoch fencing;
- event-structure configurations;
- choice/max and parallel/sum resource algebra;
- cograph dynamic programming or MWIS hardness;
- transactions, effect staging, or stable idempotency tokens.

The claim survives only if the concrete lifecycle semantics, snapshot-local impossibility, maximal escape-support result, and contextual restore/merge rules are not already present together in prior work and if real agent runtimes expose enforceable lifecycle decisions.

It fails if conditional commitments cannot be distinguished from mere intentions, if topology labels cannot be trusted, if every claimed distinction reduces to a flat ledger at dispatch time, or if the maximal-support and monitor-necessity results do not add a lifecycle-specific boundary beyond established anti-rollback work.
