# Boundary II mathematical stress test

## Executive verdict

**Correctness.** Boundary II is correct under the intended ambient scope: a
well-formed authority-continuous source, a fixed atomically valid batch of
uniquely owned tentative claims, nonnegative additive demand, exact cumulative
prefix repair, total eager cleanup of every unsupported owner that still has a
tentative bundle, and no intervening lifecycle mutation. The published proof is
short but sound once two derived properties are made explicit:

1. promoting more claims can only shrink the safe configuration family; and
2. promoting owner `b`'s own claims does not change the load of configurations
   that contain `b`.

The necessity proof also silently uses source owner-support well-formedness. A
one-owner countermodel refutes the theorem if that ambient premise is dropped.
The paper establishes the premise globally, but the Boundary II statement
should repeat it or define “valid atomic batch” to include validity of its source.

**Reduction.** Once promotion is abstracted as an antitone family filter and
cleanup as eager deletion on loss of support, the iff is a generic
“last-owner obstruction” lemma. Threshold arithmetic, downward closure,
choice/parallel syntax, vector capacity, frozen guard syntax, lineage, and
agent state are not used in the generic proof. The authority model is needed
only to establish antitonicity, owner self-neutrality, prefix admissibility, and
path-independent filtering.

**Closest generic notion.** The theorem's target property is already familiar:

- Flanagan--Godefroid transition independence is enabledness preservation plus
  commutation.
- Katz--Peled conditional independence makes that commutativity
  state/context-predicate dependent.
- van Glabbeek--Plotkin's asynchronous step requires every intermediate
  configuration in the interval.

Boundary II does not introduce a new notion of independence. Its real residual
result is a **closed-form characterization** specialized to this promotion
calculus: one final repaired family and one support query per promoted owner
are necessary and sufficient for the otherwise prefix-quantified property that
all owner-group transitions stay enabled and commute over the whole batch
cube. This is more than merely naming a predicate, because the equivalence is
false without antitonicity and owner self-neutrality. But the equivalence is a
two-property order-theoretic derivation, so it is too small by itself to carry a
breakthrough-level CSF theory story.

**Recommended response.** Mechanize the generic lemma and authority
instantiation, but present Boundary II as a useful closed-form runtime rule, not
as a new concurrency theory. The smallest extension with materially greater
theory and industrial value is to solve the problem that the paper currently
leaves as prose: when final support fails, characterize and synthesize **some**
safe order, detect when no serial order exists, and minimize the groups that
must be atomically sealed. A minimal-killer hypergraph gives an exact starting
point and makes Boundary II the all-orders corollary of a larger scheduling
theory.

## 1. Exact restatement of the current semantics

Fix a source authority state with owner set `B`, downward-closed permitted
family \(\Phi\), durable demand \(d\), owner bundle demands \(r_b\), and
capacity \(G\). Let \(U\) be a nonempty set of distinct tentative claims and
let

\[
U_b = U\cap Q_b, \qquad
P = \{b\mid U_b\ne\varnothing\}.
\]

For any promoted prefix \(S\subseteq U\), write

\[
W(S)=\sum_{c\in S}w(c),\qquad
S_b=S\cap Q_b.
\]

Before cleanup, the load of configuration \(C\) after promoting exactly
\(S\) is

\[
\begin{aligned}
L_S(C)
  &= d+W(S)+\sum_{b\in C}\bigl(r_b-W(S_b)\bigr)\\
  &= L_\varnothing(C)
     +\sum_{\substack{c\in S\\\mathsf{own}(c)\notin C}}w(c).
\end{aligned}
\tag{1}
\]

The exact safe family for the prefix is

\[
F_S=\{C\in\Phi\mid L_S(C)\le G\}.
\tag{2}
\]

For any family \(F\), define owner support by

\[
\mathsf{Supp}_b(F)\quad\Longleftrightarrow\quad
\exists C\in F.\ b\in C.
\tag{3}
\]

The sequential machine begins with \(S=\varnothing\). A nonempty owner group
\(U_b\) may execute only while its claims remain tentative and its owner/grant
epochs remain open. The step moves \(U_b\) to durable status, installs the exact
cumulative repair, and immediately closes every owner `z` that both:

- still has a nonempty tentative bundle; and
- has no support in the newly repaired family.

Closing `z` moves its remaining tentative claims to terminal `X` and restricts
the contract away from `z`. Since an unsupported owner occurs in no surviving
configuration, that final restriction does not further change the denotation.

The atomic step promotes all of \(U\), installs \(F_U\), then performs the same
cleanup once. Boundary II says:

\[
\begin{split}
&\text{every permutation of }\{U_b\mid b\in P\}
\text{ is executable and reaches the atomic}\ (D,Q,X,F)\\
&\qquad\Longleftrightarrow\qquad
\forall b\in P.\ \mathsf{Supp}_b(F_U).
\end{split}
\tag{BII}
\]

The equality is intentionally denotational in the contract component. A serial
execution normally retains several syntactic guard rows, whereas the atomic
execution can retain one batch row. The paper correctly compares
\(\front(T)\), not guard syntax.

## 2. The four facts that actually prove the theorem

Equation (1) immediately yields the core facts.

### 2.1 Antitone filtering

For nonnegative weights,

\[
S\subseteq S'\quad\Longrightarrow\quad
L_S(C)\le L_{S'}(C)\quad\Longrightarrow\quad F_{S'}\subseteq F_S.
\tag{M}
\]

Thus a witness in the final family is a witness at every earlier prefix.

### 2.2 Owner self-neutrality

For any \(C\ni b\), moving a claim from \(Q_b\) to \(D\) adds and subtracts
the same demand in the load of `C`. Hence

\[
C\ni b\quad\Longrightarrow\quad
L_{S\cup U_b}(C)=L_S(C).
\tag{N1}
\]

In particular,

\[
\mathsf{Supp}_b(F_{U\setminus U_b})
\Longleftrightarrow
\mathsf{Supp}_b(F_U).
\tag{N2}
\]

This law, rather than generic filter commutation, powers the necessary
direction.

### 2.3 Prefix structural admissibility

Atomic validity supplies \(d+W(U)\le G\), open and uniquely owned claims,
fresh injective effect assignments, and valid bindings. Nonnegative demand gives
\(d+W(S)\le d+W(U)\le G\) for every prefix. With a fixed lifecycle and no
premature cleanup of a promoted owner, all non-resource premises are inherited
by group restrictions of the atomic assignment.

### 2.4 Path-independent exact repair

Exact prefix rows compose as cumulative filtering. Cleanup removes claims only
from owners absent from the current family; those owners cannot reappear under
(M), and their removed claims contribute to no surviving configuration. It
follows inductively that a successful serial prefix has the same denotational
family as \(F_S\), regardless of the order used to reach `S`.

These four facts plus eager cleanup are sufficient. No event-structure axiom,
downward-closure argument, cograph property, vector-specific law, or agent
operation appears in the iff proof.

## 3. Generic last-owner obstruction lemma

The threshold model can be factored out completely.

Let `P` be a finite set of actions indexed by owners. For each
\(S\subseteq P\), let \(F(S)\) be a context family and let action `b` remain
enabled after prefix `S` exactly while `b` has not executed and
\(\mathsf{Supp}_b(F(S))\) holds. After every action, eagerly and irreversibly
disable every remaining action whose owner has no support. Assume:

1. **antitonicity:** \(S\subseteq S'\Rightarrow F(S')\subseteq F(S)\);
2. **self-neutrality:**
   \(\mathsf{Supp}_b(F(P\setminus\{b\}))
    \Leftrightarrow\mathsf{Supp}_b(F(P))\);
3. all actions start structurally enabled, and successful action effects commute
   modulo the chosen endpoint observation.

Then all permutations of `P` execute and have the same endpoint iff every `b`
has support in \(F(P)\).

### Sufficiency audit

Assume every `b` has final support. At any prefix \(S\subseteq P\), for every
remaining `b`, antitonicity gives

\[
F(P)\subseteq F(S),
\]

so its final witness is still present. Eager cleanup therefore cannot disable a
remaining owner. Prefix structural premises are inherited, so every next group
is executable. Commutative exact filtering gives the common final denotation.

For endpoint equality, every owner with a nonempty bundle after removing all of
`U` is terminalized exactly when it lacks support in \(F_U\), whether cleanup
detects that fact early or at the final step. Promoted owners cannot be
terminalized early under the hypothesis. Therefore `D`, `Q`, `X`, and the final
family equal the atomic target.

### Necessity audit

Suppose promoted owner `b` lacks final support. Put `b` last. If some preceding
group is disabled, that permutation already fails. Otherwise the system reaches
the prefix \(P\setminus\{b\}\). By self-neutrality, `b` has no support there.
Its nonempty group is still tentative, so cleanup after the last preceding
action closes `b` and terminalizes \(U_b\). The last action is disabled.

There is one edge case hidden by this prose: if `P={b}`, no preceding cleanup
occurs. Source owner-support well-formedness plus self-neutrality rules out the
premise that `b` lacks final support. Without source well-formedness, necessity
is false; Countermodel S below is minimal.

### Conclusion of the proof audit

The theorem is not circular and neither implication is false in the intended
model. However, its generic proof is essentially the two inclusions (M) and
(N2), followed by the operational definition of eager cleanup. The quantitative
model supplies a useful closed form for those properties, but it does not make
the serialization argument mathematically deep.

## 4. Mapping to the closest generic notions

### 4.1 Flanagan--Godefroid transition independence

Definition 1 of Flanagan and Godefroid, *Dynamic Partial-Order Reduction for
Model Checking Software* (POPL 2005), calls two transitions independent when:

1. executing one preserves whether the other is enabled; and
2. when both are enabled, the two execution orders reach the same unique state.

That is precisely the pairwise operational content of Boundary II. At a prefix
`S`, two owner-group Prepare transitions commute denotationally because exact
filters commute. The only obstacle to their independence is that the first
transition's eager cleanup can disable the second. Final support eliminates
that obstacle in every reachable prefix context.

Boundary II is global/batch contextual independence, not a new independence
definition: it proves that all adjacent swaps are legal throughout the fixed
batch cube, hence all permutations are equivalent. It does not cover arbitrary
concurrent interference, changing batches, or lifecycle transitions.

### 4.2 Katz--Peled conditional independence

Katz and Peled, *Defining Conditional Independence Using Collapses* (TCS 101(2),
1992), explicitly extend trace semantics so that commutativity depends on a
predicate describing the current global-state context. The primary abstract
states that the same two operations may be dependent in one context and
independent in another. Flanagan--Godefroid's independence definition is itself
adapted from this work.

Final owner support therefore cannot be presented as a new idea of
state-dependent independence. It is a concrete context predicate for a fixed
batch:

\[
\mathsf{AllFinalSupport}(A,U)
=\bigwedge_{b\in P}\mathsf{Supp}_b(F_U).
\]

There is nevertheless one actual derivation beyond predicate naming. In an
arbitrary conditionally independent transition system, a predicate at the final
context says nothing about all intermediate contexts. Here (M) transports final
witnesses backward to every prefix, while (N2) turns failure in the final context
into failure at `b`'s last-predecessor context. Consequently

\[
\mathsf{AllFinalSupport}(A,U)
\Longleftrightarrow
\forall S\subsetneq P.\ \forall b\in P\setminus S.\
  \mathsf{Enabled}_b(A_S),
\tag{4}
\]

with commutation supplying equal endpoints. Equation (4) reduces up to
\(2^{|P|}|P|\) contextual enabledness checks to `|P|` support checks on one
final repaired contract. Countermodels M and N below show that this collapse is
not valid by definition for arbitrary conditional independence.

This is the defensible delta: a **domain-specific closed-form decision
criterion for conditional independence**, not a new conditional-independence
semantics. The full Katz--Peled article was not available as a local PDF during
this stress test; the scope statement above is verified against its primary
publisher/Technion abstract and against Flanagan--Godefroid's explicit
attribution. The experiment's final source map should verify the exact collapse
definitions from the full text before making a theorem-level novelty claim.

### 4.3 van Glabbeek--Plotkin asynchronous steps

Definition 2.1 of van Glabbeek and Plotkin, *Configuration Structures, Event
Structures and Petri Nets*, defines an asynchronous step \(x\to y\) by requiring
every \(Z\) in the interval \(x\subseteq Z\subseteq y\) to be a configuration.
The paper explains this as the requirement that the concurrently added events
can occur in any order.

Map each owner group to a scheduling event and each completed-group set `S` to
a prefix context. Declare `S` legal when every still-pending owner has support
after `S` and the cumulative prefix is structurally admissible. Then “every
owner-group permutation is executable” means that the entire Boolean interval
between \(\varnothing\) and `P` is legal: exactly the asynchronous-step/all-
intermediate-configurations shape.

Configuration structures supply the arbitrary prefix family and the generic
all-intermediates criterion. They do not supply owner support, conditional-to-
durable accounting, or equation (1). Boundary II contributes only the fact that
for this specialized filter, the whole interval can be decided at the final
corner using (M) and (N2).

### 4.4 Supervisory enabledness and guarded workflows

A finite supervisor can encode state `(promoted-set, closed-owners)`, make
`promote_b` controllable, and make eager cleanup a deterministic plant update.
It can then disable unsafe orders or synthesize a nonblocking sublanguage.
State-tree and guarded-transaction work already translates such control state
into predicates/guards. Thus generic “enable only safe transitions,” maximal
legal pruning, contextual guards, and coordinator synthesis are prior art.

The final-support test is a specialized symbolic shortcut for one frozen batch;
it avoids constructing its entire prefix plant. It is not a replacement for a
supervisor under changing topology, partial observation, uncontrollable cleanup,
or liveness requirements.

### 4.5 Resource-tracking games and configuration resources

Resource-tracking concurrent games already attach an algebra of sequential and
parallel consumption to event-structure configurations. They do not directly
define the paper's conditional-to-durable owner transfer or eager deletion of
unsupported future owners. That missing cleanup operator is a genuine semantic
specialization. Once the operator and laws (M)/(N2) are added, however, Boundary
II follows generically; the proof does not use a novel resource algebra.

## 5. Assumption-independence matrix

| Premise | Sufficiency | Necessity | What happens if removed | Minimal weaker requirement |
|---|---:|---:|---|---|
| Well-formed source: every tentative owner is supported | inherited prefix enablement | **essential for one-owner edge case** | Countermodel S has one executable group and no final support | Every promoted owner is initially enabled/supported, or run cleanup before the first group |
| Unique claim IDs and disjoint owner partition | **essential operationally** | structural | Countermodel A lets the first group consume the second group's aliased claim although both owners have final support | The groups are disjoint linear resources and restrictions of one valid atomic assignment |
| Fixed batch and fixed source owner map | **essential to state the final query** | **essential to choose “last”** | Adding/removing/rebinding a group invalidates `F_U` and `U_b` | A versioned batch whose membership and owner map are immutable until completion |
| Atomically valid batch | prefix base checks | defines atomic comparison | Without it the target may reject even the empty configuration and “same atomic result” is undefined | All prefixes structurally admissible plus a defined exact final target |
| Nonnegative additive demand | **gives antitonicity** | helps prefix inheritance | Countermodel M has final support reappear after a negative/refund group, so final support does not protect a prefix | Direct antitonicity \(F_{S'}\subseteq F_S\) |
| Owner self-neutrality | not needed if antitonicity holds | **essential** | Countermodel N has one successful group whose own promotion removes its final support | Support equivalence between \(F_{U\setminus U_b}\) and \(F_U\) for each `b` |
| Exact cumulative prefix repair | endpoint equality and preservation of final witnesses | exact predecessor/final comparison | Conservative under-filtering breaks sufficiency; unsafe over-filtering breaks necessity | For sufficiency, every prefix contains `F_U`; for necessity, predecessor support equals final support; all paths have the atomic endpoint |
| Immediate cleanup | protects WF but may disable later group | **essential** | Countermodel C succeeds in both orders if unsupported batch members are retained until batch end | Cleanup occurs before any later unprepared group, unless the batch already owns an atomic seal |
| Cleanup closes **all and only** unsupported owners with nonempty tentative bundles | **essential** | **essential** | Closing a supported owner breaks sufficiency; skipping an unsupported owner breaks necessity | Exact cleanup set; “deterministic” is then derived rather than separately needed |
| Cleanup irreversibility | **essential across prefixes** | essential to the failing order | Reopening a tombstoned owner can make a later group executable | Terminal ownership cannot be revived inside the batch/version |
| No lifecycle interleaving | **essential** | fixed-context premise | Countermodel I aborts a finally supported owner between two groups | A rely condition preserving owner map, epochs, support and batch version, or a batch seal |
| Grouping by owner | convenient | convenient for last-owner proof | Not fundamentally required: claim-level actions work if each action has one self-neutral support key | A partition into support-neutral action classes |
| Downward closure of \(\Phi\) | unused | unused | The generic proof is unchanged for an arbitrary set family | None for Boundary II itself |
| Choice/parallel or guarded syntax | unused | unused | Only representation changes | A support oracle and exact family transformer |
| Vector naturals rather than one scalar | unused after (M)/(N2) | unused | Scalar examples already realize the boundary | Any ordered resource domain establishing (M)/(N2) |
| Finite family | not logically needed | finite permutations only | Infinite variants require a different order quantifier | Finite promoted batch suffices; `B` itself need not be finite for this lemma |

The matrix shows that the mathematically minimal theorem has far fewer premises
than the paper model. “Exact prefix guards” and “natural-number capacity” are
one way to establish the real premises, not the premises themselves.

## 6. Small countermodels

All families below include every subset needed for downward closure. Weights are
scalar unless stated otherwise.

### Baseline C: final support absent and one order fails

This is the paper's sharp nonnegative witness and should remain the canonical
cleanup example.

- Owners: \(B=\{s,t\}\).
- Family: \(\Phi=\{\varnothing,\{s\},\{t\}\}\) (exclusive choice).
- Capacity: \(G=2\).
- Bundles: \(Q_s=\{c_s:1\}\) and
  \(Q_t=\{c_t:1,u:1\}\).
- Batch: \(U=\{c_s,c_t\}\).

Atomic promotion has durable load two and retains
\(F_U=\{\varnothing,\{s\}\}\); `t` has no final support, and atomic cleanup
terminalizes only residual claim `u`. If `s` goes first, the `t` configuration
has load three, so eager cleanup terminalizes both `c_t` and `u`; `t` cannot go
second. If `t` goes first, both owners remain supported, then `s` executes and
the result equals the atomic cleaned target.

This witness also shows that “failure of final support” means “not every order,”
not “no serial order.”

### Countermodel S: remove source owner-support well-formedness

- One owner `b`; \(\Phi=\{\varnothing\}\).
- \(G=1\), \(Q_b=\{c:1\}\), \(U=\{c\}\).
- Keep branch/grant epochs open and all IDs/bindings valid.

The source satisfies the capacity invariant but not owner-support WF. Its only
group can promote: the empty configuration has durable load one, and cleanup
has no remaining tentative bundle to remove. Thus the only permutation
succeeds while `b` has no support in \(F_U\). This refutes necessity unless
source WF (or initial cleanup) is explicit.

### Countermodel A: remove linear/disjoint owner grouping

- Two owners `s,t`, full family \(2^{\{s,t\}}\), ample capacity.
- Alias one physical claim `c` into both \(U_s\) and \(U_t\).

Both owners have final support, but the first group moves `c` out of tentative
state and the second group no longer owns a tentative claim. This violates the
left-to-right direction. The ordinary ledger partition excludes the example;
its purpose is to show that uniqueness is a linearity premise, not harmless
notation.

### Countermodel M: remove antitonicity/nonnegative demand

Use signed resource deltas.

- Owners: `s,r,t`; exclusive singleton family
  \(\{\varnothing,\{s\},\{r\},\{t\}\}\).
- \(G=1\).
- Claims: \(c_s:+1\), \(c_r:-1\), \(c_t:+1\), each owned by its named owner.
- Batch: all three claims.

The source is safe. Atomic promotion has total durable demand one, so every
owner has final support. But after promoting `s` first, the `t` configuration
has load two and is removed; eager cleanup terminalizes `c_t`. Promoting the
refund `r` later would have made the final `t` configuration safe again, but
the prefix restriction and tombstone cannot reopen it. Final support therefore
does not imply all-order executability without antitonicity.

Three owner groups are minimal for this pattern: one group temporarily harms
the pending owner, one later group repairs the harm, and the pending owner is a
third group that cleanup can disable.

### Countermodel N: remove owner self-neutrality

- One owner `b`; \(\Phi=\{\varnothing,\{b\}\}\), \(G=1\).
- One conditional claim \(c:1\) owned by `b`.
- Modify promotion to impose an additional one-unit retention fee only on
  configurations containing `b`.

The exact post-promotion family is \(\{\varnothing\}\), but the only group is
enabled initially and executes atomically; no tentative bundle remains for
cleanup. The only permutation succeeds although final support is false.
Standard authority accounting rules this out because moving an owner's own
claim from conditional to durable is exactly load-neutral on owner-containing
configurations. This is the smallest witness that (N2), not generic
commutation, is essential to necessity.

### Countermodels E: remove exact prefix repair

**Safe conservative under-filtering breaks sufficiency.** Let `s,t` have the
full family \(2^{\{s,t\}}\), one unit claim each, \(G=2\), and promote both.
The exact final family supports both owners. After `s` first, let a conservative
approximation unnecessarily remove every configuration containing `t`.
Cleanup closes `t`, so a finally supported owner cannot execute.

**Unsafe over-filtering breaks necessity.** Start from baseline C, but after
`s` first temporarily retain the overloaded `t` configuration. Cleanup does not
close `t`; after `t` executes, install the exact final filter. Both orders can
finish even though `t` lacks final support. This second variant violates the
capacity invariant, as it must: any sound prefix family is a subfamily of the
exact filter. It separates the logical role of exactness from the safety role.

Exactness is stronger than necessary. Sufficiency needs a no-over-pruning
condition \(F_U\subseteq F^{actual}_S\) for every prefix plus the correct final
endpoint. Necessity needs the actual last-predecessor context to expose every
finally unsupported owner.

### Countermodel I: allow lifecycle interleaving

- Owners `s,t`, full family, one unit claim each, \(G=2\), batch both claims.
- Both owners have support in the exact final family.
- Execute `s`, then interleave `Abort(t)` (or close `t`'s branch epoch), then
  attempt `t`.

The second group is disabled despite final support in the frozen source
calculation. This is intentionally simple: Boundary II is a frozen-batch serial
decomposition theorem, not a concurrency theorem against Fork/Restore/Merge,
abort, revocation, or scheduler races.

### Countermodel D: make cleanup optional or local-only

Reuse baseline C. If unsupported batch members are exempt from cleanup until
the batch ends, or cleanup only examines the owner that just executed, `s`
first no longer terminalizes `c_t`. Then `t` can execute and both orders reach
the atomic result although final support is absent.

This behavior is not inherently unsafe if the full batch was already atomically
validated and sealed. It is exactly a different runtime protocol. Therefore
Boundary II characterizes **unsealed eager-cleanup serialization**, not all
reasonable serial implementations.

### Countermodel X: make cleanup nondeterministic

Again reuse baseline C. A cleanup choice that skips unsupported `t` makes the
otherwise failing order succeed; a choice that may close a supported owner
breaks the positive direction in the two-owner ample-capacity example. The
essential premise is not determinism as an abstract property but that cleanup
closes exactly all and only unsupported owners with remaining tentative claims.
Given a fixed family, that set is already deterministic.

## 7. Novelty verdict

### What survives

Boundary II is not literally a definition. It proves the nontrivial extensional
equality in equation (4): a final-state support predicate characterizes a
property quantified over every prefix and every next owner group. The equality
can save exponential prefix exploration for the universal-all-orders question,
although each owner-support query may still require the guarded-contract oracle.
The negative and mutation countermodels show exactly why the equality holds in
this calculus and not in arbitrary context-dependent transition systems.

The agent-runtime interpretation is also useful: an unsealed effect batch may
be freely scheduled precisely when irreversible cleanup cannot delete any
still-pending effect owner. This turns a subtle runtime race into a checkable
rule and justifies the “serial or seal” guidance.

### What does not survive

The target property—contextual enabledness preservation plus commutation—is
generic transition/conditional independence. The all-intermediate-prefix form
is generic asynchronous-step semantics. State predicates for conditional
commutativity, arbitrary configuration families, resource-sensitive
concurrency, and supervisor guards are established. The Boundary II proof then
uses only antitonicity and owner self-neutrality.

Accordingly, the result should not be advertised as:

- a new notion of serializability or independence;
- a new event/configuration semantic phenomenon;
- a theorem that fundamentally requires agent checkpoint/restore; or
- by itself, a large foundational breakthrough.

It is best described as:

> For a fixed valid conditional-to-durable authority batch under exact
> cumulative filtering and eager irreversible cleanup, final owner support is a
> closed-form necessary-and-sufficient test for contextual independence of all
> owner-group Prepare transitions.

That is a clean specialization and runtime decision rule. A kernel proof would
raise confidence and clarify assumptions but would not, by itself, raise the
novelty altitude.

### Overall assessment

**Novelty status: mathematically valid, useful, but acceptance-blocked as the
sole headline theory result.** It is not directly quoted as a theorem in the
inspected generic sources because they do not contain the paper's owner-cleanup
operator. Yet after adding that operator, the iff is immediate enough that a
skeptical reviewer can reasonably call it a specialized conditional-
independence lemma. The paper needs either a larger theorem around scheduling
and coordination or a much stronger agent-runtime refinement result.

## 8. Smallest extension that becomes non-trivial and useful

### 8.1 Move from “all orders?” to exact safe-order synthesis

Let `P` be the promoted owners and, for each `b`, define its minimal killer
hyperedges. Here \(F_K\) abbreviates the exact family after promoting
\(\bigcup_{k\in K}U_k\):

\[
\mathcal K_b=\min_{\subseteq}
\{K\subseteq P\setminus\{b\}
  \mid \neg\mathsf{Supp}_b(F_K)\}.
\tag{5}
\]

Antitonicity means that once a prefix contains a killer edge, `b` stays
unsupported. A permutation \(\pi\) is executable exactly when

\[
\forall b\in P.\ \forall K\in\mathcal K_b.\
K\nsubseteq \mathsf{Pred}_\pi(b),
\tag{6}
\]

or equivalently, `b` precedes at least one member of every one of its killer
sets. This is a disjunctive precedence system, not ordinary pairwise conflict.

Boundary II becomes the easy all-orders corollary: every order works iff every
\(\mathcal K_b\) is empty, which is equivalent by self-neutrality to every
owner having final support.

This extension distinguishes three operationally important cases:

1. **any order:** all final owners supported;
2. **some orders:** baseline C has
   \(\mathcal K_t=\{\{s\}\}\), so `t` must precede `s`;
3. **no serial order:** let both owners have a promoted one-unit claim and an
   additional residual one-unit claim, use exclusive choice and \(G=2\).
   Promoting either owner first removes the other's support. Then
   \(\mathcal K_s=\{\{t\}\}\) and
   \(\mathcal K_t=\{\{s\}\}\); the precedence constraints cycle and the batch
   must be sealed or coordinated.

Even without materializing all minimal killer sets, an exact dynamic program
over owner subsets can synthesize an order:

\[
\begin{aligned}
\mathsf{Reach}(\varnothing)
  &=\bigwedge_{c\in P}\mathsf{Supp}_c(F_\varnothing),\\
\mathsf{Reach}(S')
  &=\bigvee_{b\in S'}\left(
      \mathsf{Reach}(S'\setminus\{b\})\land
      \bigwedge_{c\in P\setminus S'}\mathsf{Supp}_c(F_{S'})
    \right).
\end{aligned}
\tag{7}
\]

Equation (7) gives an executable order and a checkable support certificate, or
proves that no unsealed serial order exists. A first implementation is
\(O(2^{|P|}|P|^2)\) support-oracle calls; the research questions are whether
the guarded/cotree structure admits a polynomial special case, whether general
existence/minimum sealing is NP-hard, and how to return small obstruction
certificates.

This is the **minimum recommended extension** because it directly implements
the paper's current unexplained instruction to “validate a particular order.”
It adds a real algorithmic problem, richer counterexamples, a useful
certificate, and a theorem of which Boundary II is only one corollary.

### 8.2 Add minimum atomic sealing/coordinator synthesis

When no serial order exists, contract strongly connected or mutually killing
owner sets into atomic seal groups. Optimize the number of sealed groups,
maximum sealed resource, or coordination cost while preserving a serial order
between groups. This turns the theory into a runtime planning algorithm rather
than a binary warning. The symmetric two-owner countermodel is the smallest
mandatory-seal certificate.

Claims of complexity must be proved rather than inferred from generic
supervisory-control hardness. A reduction should use the actual support oracle
and batch semantics, and a tractable result for pure choice/parallel cotrees
would be particularly valuable.

### 8.3 The agent-specific strengthening

The current theorem freezes exactly the feature that makes agents unusual:
Fork, live/replace Restore, Merge, abort, revocation, and crashes can occur while
effects are being prepared. After the static scheduling extension, the next
agent-specific theorem should characterize when a planned order remains valid
under lineage-preserving lifecycle transitions, or prove that a versioned batch
lease/atomic seal is necessary.

A strong target would combine:

- the support-killer schedule certificate;
- a contract/version dependency set;
- permitted commuting topology transitions under lineage projection; and
- crash-stable Prepare tickets before external dispatch.

Then the runtime can optimistically execute while unrelated agent work
continues, reject only support-invalidating lifecycle races, and atomically seal
only the irreducible owner groups. That would be recognizably agent-runtime
specific; the present frozen-batch iff is not.

## 9. Mechanization guidance

The planned Lean work should separate the result into two layers.

1. **Generic layer.** Define a finite action set, antitone context family,
   support predicates, owner self-neutrality, eager cleanup, and commuting
   endpoint observation. Prove the last-owner obstruction iff. This theorem
   should contain no capacities, claims, guards, or agent operations.
2. **Authority instantiation.** Prove equation (1), antitonicity from natural
   weights, self-neutrality, prefix admissibility from atomic validity, exact
   path independence despite cleanup, and equality of `D/Q/X/front(T)`.

The mutation suite should include at least S, M, N, conservative E, I, and D.
If the generic theorem compiles after assuming “all prefixes enabled” or
defining enabledness as final support, the mechanization is circular and adds
no evidence.

The best Step 0006 outcome is therefore not merely `#print axioms` on the
current iff. It is a candid result showing:

- what is generic conditional independence;
- the exact two algebraic laws supplied by authority promotion;
- the hidden source-WF dependency;
- a mechanized one-final-query collapse; and
- a concrete next theorem for safe-order/minimum-seal synthesis.

## 10. Sources inspected for this stress test

- Current paper: `sections/model.tex`, `semantics.tex`, `results.tex`,
  `algorithm.tex`, and `validation.tex`.
- Current design/executable definitions: `docs/design.md`,
  `artifact/authority_continuity.py`, `artifact/explore.py`, and the existing
  Boundary II tests.
- van Glabbeek and Plotkin, *Configuration Structures, Event Structures and
  Petri Nets*, especially Definitions 1.1 and 2.1 and the ternary-conflict
  example; local full PDF under `reference/foundations/`.
- Flanagan and Godefroid, *Dynamic Partial-Order Reduction for Model Checking
  Software*, especially Section 2.2, Definition 1; local full PDF under
  `reference/foundations/`.
- Katz and Peled, *Defining Conditional Independence Using Collapses*, TCS
  101(2):337--359, DOI `10.1016/0304-3975(92)90054-J`; primary publisher and
  Technion metadata/abstract inspected, with its role also confirmed by the
  Flanagan--Godefroid attribution.
- Alcolei, Clairambault, and Laurent, *Resource-Tracking Concurrent Games*,
  especially the resource bimonoid and event-configuration definitions; local
  full PDF under `reference/foundations/`.
- Feng, Wonham, and Thiagarajan, *Designing Communicating Transaction Processes
  by Supervisory Control Theory*, especially the supervisor/guard synthesis
  setup; and Ma--Wonham state-tree structures, under
  `reference/supervisory-control/`.
