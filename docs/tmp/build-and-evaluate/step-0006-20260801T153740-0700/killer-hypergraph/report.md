# Killer hypergraphs, safe-order synthesis, and atomic sealing

**Read-only theorem/novelty stress report, 2026-08-01.** This report does not
change the canonical story, paper, artifact, or Lean development.

## Executive verdict

The proposed extension contains one important correction and one important
novelty warning.

1. **There is no exponential subset dynamic program for static safe-order
   existence.** Under the paper's stated fixed-batch semantics, a safe owner
   order is found by a backward monotone peeling algorithm. It uses at most
   (O(|P|^2|mathcal K|)) arithmetic work, or (O(|P|^2)) calls to a generic
   support oracle. If peeling stops, the unique residual core is a short,
   independently checkable proof that no serial order exists.
2. **The abstract result is classical.** Reversing a safe execution order turns
   each minimal killer into an AND/OR waiting condition: every bundle must have
   at least one previously executed alternative. This is exactly the trace
   condition of a conflict-free Dual Event Structure and the feasibility model
   treated by Möhring, Skutella, and Stork. Monotone, choice-independent peeling
   is a pruning process/antimatroid. The hypergraph existence theorem, greedy
   algorithm, and dead-core obstruction therefore cannot honestly be sold as a
   new CSF-level scheduling theory.
3. **The authority instantiation is nevertheless useful and sharper than the
   current paper says.** Owner support in the current nonnegative,
   downward-closed model does not require a global guarded optimization oracle.
   The singleton configuration ({b}) is always the cheapest support witness.
   Consequently, every owner becomes a vector-valued job with a promotion
   vector (p_b) and a start-deadline (h_b). This yields a compact arithmetic
   scheduler even when the explicit minimal-killer family is exponential.
4. **A meaningful sealing problem is nontrivial, but its objective must be
   stated carefully.** Minimizing the number of atomic blocks is vacuous: one
   block containing the entire batch is always feasible. A precise alternative
   is the minimum-cost *final atomic seal*: find owners (H) that execute as one
   final atomic block after all owners in (P\setminus H) execute serially. This
   problem has an exact polynomial verifier and is NP-complete even for one
   scalar resource and a pure-choice source contract, by a direct covering-
   knapsack reduction. In the explicit killer representation, rank-one killers
   admit an SCC algorithm, while weighted rank-two instances are already
   NP-hard by a Vertex Cover reduction.
5. **This can become a stronger contribution than Boundary II only as an
   agent-authority package, not as “killer hypergraphs.”** The credible package
   is: derive vector deadlines from conditional-to-durable authority promotion;
   synthesize a safe order or emit a canonical authority-dead-core certificate;
   choose an explicit serial-or-seal repair; and make the certificate versioned
   under Fork/Restore/Merge/Abort/Revoke and crash-stable Prepare/Dispatch. The
   last, dynamic part still needs a new theorem and implementation. Static
   dependency mutation by itself is also occupied by dynamic-causality event
   structures.

The conservative recommendation is therefore:

> Use the peeling theorem as a compact runtime algorithm and make Boundary II
> its all-orders corollary. Do not headline the hypergraph abstraction. Promote
> this direction only if the paper proves a versioned lifecycle-preservation
> theorem and implements serial-or-seal admission at a real agent dispatch
> boundary.

## 1. Exact authority reduction

### 1.1 Fixed-batch notation

Fix the same ambient assumptions as Boundary II:

- a well-formed source authority state;
- a fixed owner set and fixed promotion batch until completion;
- nonnegative componentwise claim weights;
- unique, disjoint owner groups;
- exact cumulative promotion repair;
- eager, irreversible cleanup of every unsupported owner with a remaining
  tentative bundle; and
- no interleaved lifecycle transition that changes the batch, owner epochs,
  capacity, durable load, or contract.

Let (P) be the promoted owners, and let

\[
p_b = \sum_{c\in U_b}w(c),
\qquad
p(S)=\sum_{b\in S}p_b,
\qquad
h_b=G-d-r_b .
\tag{1}
\]

All quantities are vectors in (mathbb N^{\mathcal K}). Here (r_b) is the
full source tentative demand of owner (b), not merely the part promoted in
this batch. Since (U_b\subseteq Q_b), (p_b\le r_b) componentwise.

For an owner set (S\subseteq P), write (F_S) for the exact safe family after
promoting all groups in (S), before the denotationally inert restriction of
unsupported owners. The load equation from the Boundary II stress report is

\[
L_S(C)
=d+p(S)+\sum_{z\in C}\bigl(r_z-\mathbf 1[z\in S]p_z\bigr).
\tag{2}
\]

### 1.2 Singleton-support lemma

**Lemma 1 (support is a singleton inequality).** For every promoted set
(S\subseteq P) and owner (b\in P),

\[
\mathsf{Supp}_b(F_S)
\quad\Longleftrightarrow\quad
p(S\setminus\{b\})\le h_b .
\tag{3}
\]

**Proof.** Source well-formedness supplies some source configuration containing
(b). Downward closure therefore supplies ({b}\in\Phi). Equation (2) gives

\[
L_S(\{b\})=d+r_b+p(S\setminus\{b\}).
\tag{4}
\]

For any (C\ni b),

\[
L_S(C)-L_S(\{b\})
=\sum_{z\in C\setminus\{b\}}
  \bigl(r_z-\mathbf 1[z\in S]p_z\bigr)\ge0,
\tag{5}
\]

because (p_z\le r_z). Thus, if any configuration supports (b), the singleton
does; and the singleton supports (b) exactly when (3) holds. ∎

This lemma is stronger operationally than the current algorithm prose. Global
safety of a guarded contract can still require pseudo-Boolean optimization, but
**owner support for this exact promotion scheduler does not**. A support
certificate is the singleton plus the componentwise inequality (3). If the
paper retains the claim that promotion support “may require the guarded oracle,”
it should distinguish arbitrary global admission from this owner-support query.

The lemma also explains why choice/parallel syntax is not needed for order
synthesis after the source has been validated. Syntax establishes downward
closure and structural presence; the scheduler subsequently needs only
((p_b,h_b)).

### 1.3 Exact safe-order theorem

Let (pi=(b_1,\ldots,b_n)) be a permutation of (P), and let
(S_i=\{b_1,\ldots,b_{i-1}\}).

**Theorem 2 (vector start-deadline characterization).** The serial execution in
order (pi) is enabled through every Prepare and reaches the same cleaned
denotational endpoint as the atomic batch iff

\[
\forall i\in\{1,\ldots,n\}.\quad p(S_i)\le h_{b_i}.
\tag{6}
\]

**Proof sketch.** Immediately before (b_i), its group can still be open only
if cleanup has not terminalized it. By Lemma 1, support at that prefix is exactly
(6). Because promotion load only increases, support at (S_i) implies support
at every earlier prefix, so (b_i) could not have been cleaned earlier.
Conversely, if (6) fails, exact cleanup after the first prefix at which support
is lost makes the later Prepare impossible. Exact path-independent filtering and
the Boundary II structural premises then give atomic endpoint equality for every
successful complete order. ∎

Equivalently, define a vector completion deadline

\[
\delta_b=h_b+p_b .
\tag{7}
\]

Then (6) says that the cumulative completion vector of job (b_i) is at most
(delta_{b_i}). With one resource coordinate, this is ordinary single-machine
deadline feasibility. Earliest-due-date order is the classical solution; see
[Jackson's 1955 report](https://ntrl.ntis.gov/NTRL/dashboard/searchResults/titleDetail/AD152722.xhtml).
Lawler's backward sequencing result is another close scheduling anchor
([Management Science 1973, DOI 10.1287/mnsc.19.5.544](https://doi.org/10.1287/mnsc.19.5.544)).

## 2. Backward peeling, canonical core, and certificate

### 2.1 Algorithm

Maintain the owners (R) that have not yet been placed before the already
constructed suffix. An owner (b\in R) can be the last owner among (R) iff

\[
p(R\setminus\{b\})\le h_b.
\tag{8}
\]

By owner self-neutrality this is equivalently
(mathsf{Supp}_b(F_{R\setminus\{b\}})), or the conceptual query
(mathsf{Supp}_b(F_R)). The former indexing makes the actual forward
predecessor set explicit.

```text
R := P
suffix := []
while R is nonempty:
    choose any b in R with p(R \ {b}) <= h_b
    if no such b exists:
        return NO-ORDER(core = R)
    R := R \ {b}
    suffix := [b] ++ suffix
return SAFE-ORDER(suffix)
```

The deletion sequence is the reverse of the returned forward execution order.

### 2.2 Why arbitrary eligible choice is complete

**Lemma 3 (monotone eligibility).** If (b) is eligible in (R), it remains
eligible in every (R'\subseteq R) containing (b).

This follows immediately from nonnegative (p_a):
(p(R'\setminus\{b\})\le p(R\setminus\{b\})\).

**Theorem 4 (greedy completeness).** Peeling returns a complete order iff some
safe serial order exists. Every choice of an eligible owner is safe; no
backtracking is required.

**Proof.** If the algorithm empties (R), (8) at each deletion is precisely (6)
for the reversed order. For completeness, suppose a safe order of (R) exists
and the algorithm chooses any eligible (b) as the last element. Remove (b)
from the existing safe order and append it. Jobs that formerly followed (b)
lose the nonnegative predecessor load (p_b), so they remain safe; (b) is
safe last by (8). Hence arbitrary eligible choice preserves the existence of a
safe order. If the algorithm is stuck, the last element of any purported safe
order of (R) would have to satisfy (8), a contradiction. ∎

This theorem was also checked computationally against exhaustive permutation
search on random vector instances with up to seven owners and three resource
coordinates; no mismatch was found. That check is diagnostic, not evidence for
the proof.

### 2.3 Choice-independent dead core

Run peeling to a maximal stuck residual (R^\star). It is independent of all
eligible choices.

One proof compares two maximal deletion sequences. If the first sequence deletes
(x) at some stage, then any other terminal residual, after excluding the earlier
deleted elements inductively, is a subset of the state in which (x) was
eligible. Monotone eligibility would make (x) eligible there too, so a terminal
residual cannot contain it. Symmetry gives equal residuals.

Equivalently, delete all currently eligible owners in parallel:

\[
R_0=P,\qquad
R_{i+1}=R_i\setminus
\{b\in R_i\mid p(R_i\setminus\{b\})\le h_b\}.
\tag{9}
\]

This descending iteration reaches the same greatest fixed point (R^\star).
It is the **authority-dead core**. The batch has some serial order iff
(R^\star=\varnothing).

### 2.4 Polynomial no-order certificate

If (R^\star\ne\varnothing), for every (b\in R^\star) choose a coordinate
(k_b) satisfying

\[
\sum_{a\in R^\star\setminus\{b\}}p_{a,k_b}>h_{b,k_b}.
\tag{10}
\]

In any total order, consider the last member (b) of (R^\star). All other
members of the core precede it, so (10) violates its support deadline. Thus

\[
\bigl(R^\star,\{k_b\}_{b\in R^\star}\bigr)
\tag{11}
\]

is a polynomially checkable coNP-style obstruction for this polynomial problem.
It is substantially smaller than an explicit collection of minimal killers.

### 2.5 Complexity

- Maintaining (q_R=p(R)) and scanning all remaining owners gives
  (O(|P|^2|\mathcal K|)) arithmetic time and (O(|P||\mathcal K|)) input
  space.
- In a generic antitone-filter model, the same proof uses at most
  (O(|P|^2)) support-oracle calls.
- In one scalar coordinate, sorting by (delta_b=h_b+p_b) and checking the EDD
  schedule gives (O(|P|\log |P|)) time.
- If minimal killers are explicitly represented, the standard AND/OR queue
  algorithm is linear in total bundle incidence: mark a bundle satisfied when
  its first member is peeled, decrement the unsatisfied-bundle count of its
  target, and enqueue the target when that count reaches zero.

### 2.6 Boundary II is exactly the all-orders corollary

By Lemma 1 and self-neutrality,

\[
\mathsf{Supp}_b(F_P)
\quad\Longleftrightarrow\quad
p(P\setminus\{b\})\le h_b.
\tag{12}
\]

Thus Boundary II says that **every** owner is eligible at the initial reverse
peeling state. Monotonicity then keeps every not-yet-chosen owner eligible, so
every deletion order—and hence every forward permutation—is safe. Conversely,
if (12) fails for (b), the forward permutation that places (b) last fails.

The hierarchy is therefore exact:

| Runtime question | Exact condition |
|---|---|
| Is every owner order safe? | Every (b) satisfies (12) initially (Boundary II). |
| Is some owner order safe? | Backward peeling empties (P). |
| Is no owner order safe? | Peeling returns nonempty (R^\star) and certificate (10). |
| Which order should run? | Reverse any valid peeling sequence. |

## 3. Minimal killers and their exact classical correspondences

### 3.1 Killer hypergraph

For each owner (b), define its inclusion-minimal killer family

\[
\mathcal H_b=min_{\subseteq}
\left\{K\subseteq P\setminus\{b\}
\mid p(K)\not\le h_b\right\}.
\tag{13}
\]

Source support ensures that no killer is empty. For a forward order (pi),
Theorem 2 is equivalent to

\[
\forall b\in P.\ \forall K\in\mathcal H_b.\quad
K\not\subseteq\mathsf{Pred}_\pi(b).
\tag{14}
\]

Since (b\notin K), (14) says that (b) precedes at least one member of every
killer (K).

Reverse the order. For every rooted killer (K\in\mathcal H_b), add a bundle

\[
K\longrightarrow b.
\tag{15}
\]

Then (b) is enabled exactly when every incoming bundle has at least one
previously executed member. This is an AND of OR prerequisites.

### 3.2 Exact Dual Event Structure match

Ordinary Bundle Event Structures are slightly too restrictive because their
stability condition requires distinct alternatives in one bundle to conflict.
Killer members may all occur. Dual Event Structures remove that restriction.

Arbach et al. define a DES trace (e_1\cdots e_n) by the condition that, for
every event (e_i), every bundle pointing to (e_i) intersects the earlier
trace; they explicitly state that DESs are obtained by dropping BES stability
([LMCS 2018, Definitions 2.12--2.13](https://doi.org/10.23638/LMCS-14(1:17)2018)).
With no conflicts, this is exactly (15). Langerak's original BES work is the
historical bundle reference
([FORTE 1992 metadata and ACM record](https://research.utwente.nl/en/publications/bundle-event-structures-a-non-interleaving-semantics-for-lotos/)).

Consequently, “a safe order exists iff the reversed killer structure has a full
trace” is a semantics-preserving renaming, not a new event-structure theorem.

### 3.3 Exact AND/OR scheduling match

Möhring, Skutella, and Stork represent an AND/OR waiting condition as
((X,j)): job (j) must wait for at least one job in (X), and every waiting
condition of (j) must be satisfied. They prove feasibility by exactly the
queue-based peeling algorithm above and characterize failure by a generalized
cycle
([SIAM Journal on Computing 2004, DOI 10.1137/S009753970037727X](https://doi.org/10.1137/S009753970037727X)).

Under the reverse-order map (X=K), (j=b), their model is identical to
(15). Their paper also connects the representation to directed hypergraphs and
antimatroids. Gallo et al. are the standard directed-hypergraph reference
([Discrete Applied Mathematics 1993, DOI 10.1016/0166-218X(93)90045-P](https://doi.org/10.1016/0166-218X(93)90045-P)).

The authority-dead core is therefore an arithmetic specialization of their
generalized-cycle obstruction, not a newly discovered kind of hypergraph cycle.

### 3.4 Exact antimatroid/pruning match

Let a reverse deletion set (A) be feasible when its members can be peeled in
some sequence. Once (b) becomes peelable, deleting more owners cannot make it
unpeelable. The feasible deletion sets are accessible and union-closed: to form
the union of two feasible sets, execute one sequence and then append the missing
members of the other; monotone eligibility preserves every appended step.

Restricted to the peelable ground set (P\setminus R^\star), this is an
antimatroid. The rooted killer sets generate its pruning rules. Ardila and
Maneva state the exact general fact: a removal process in which an element,
once removable, stays removable is a pruning process/antimatroid, and every
protected subset has a unique minimal reachable residual
([Discrete Mathematics 2009, DOI 10.1016/j.disc.2008.08.020](https://doi.org/10.1016/j.disc.2008.08.020)).
Their rooted-set formulation says an element is removable when at least one
member has been removed from every one of its rooted rule sets—again exactly
the killer rule.

Thus choice independence, union closure, the unique core, and the elimination
language all have direct primary prior art. “Greedoid” is too broad a label;
**antimatroid/pruning process** is the exact one.

## 4. Representation and oracle complexity

### 4.1 Explicit killers can be exponentially larger than authority data

Minimal killers should be a proof concept, not the default runtime
representation. With one scalar coordinate, (m) unit promotion vectors, and
threshold (h_b=t-1), every (t)-subset of the other owners is a minimal
killer. The family has size $\binom{m}{t}$, while $((p,h))$ has linear size.

Möhring et al. independently note that a threshold saying a job may start only
after at least (ell) of (2ell) jobs can require exponentially many explicit
waiting conditions. Their linear-time result is linear in this expanded input,
not in a compact threshold encoding.

The paper's arithmetic specialization therefore has a real, although modest,
algorithmic benefit:

- it derives the waiting rules from authority rather than asking users to state
  them;
- it keeps a compact vector threshold rather than enumerating hyperedges; and
- it emits a coordinate witness (10) instead of an expanded generalized cycle.

This is a useful specialization, not a new abstract feasibility class.

### 4.2 Special contract shapes

**Fully parallel owners.** If the source admits all promoted owners together,
source authority continuity gives

\[
d+\sum_{a\in P}r_a\le G.
\]

Since (p_a\le r_a), for every (b),

\[
p(P\setminus\{b\})
\le\sum_{a\in P\setminus\{b\}}r_a
\le G-d-r_b=h_b.
\]

Boundary II holds automatically. A fully parallel source has no static
serial-or-seal problem.

**Pure choice.** A pure-choice source constrains each singleton but need not
constrain joint owner demand. It can therefore exhibit arbitrary interference
between conditional futures after durable promotion. Safe-order existence is
still polynomial in the numeric representation, but minimum sealing is already
hard (Section 5.3).

**Mixed choice/parallel and frozen guards.** Once the source is well formed,
the singleton lemma erases the syntax from this scheduling query. The syntax
still matters for global Reserve/Merge admission and for constructing the exact
guarded endpoint, but not for deciding whether one promoted owner remains
supported.

### 4.3 Generic-oracle boundary

The peeling theorem needs only the following abstract laws:

1. promotion filters are antitone;
2. owner promotion is self-neutral for its support; and
3. support lost under a larger predecessor set cannot reappear.

In a richer policy model lacking the singleton lemma, order synthesis remains
polynomial in support-oracle calls, but the oracle itself can be expensive. The
current paper should make two claims separately:

- **generic theorem:** (O(n^2)) support queries;
- **current authority calculus:** (O(n^2|\mathcal K|)) direct arithmetic.

## 5. A nonvacuous minimum atomic-seal problem

### 5.1 Objective traps

Several superficially natural objectives are trivial or underspecified.

- “Minimize the number of atomic blocks” returns one block containing (P).
- “Minimize the number of seals” also returns one full-batch seal unless seal
  size or coordination cost is charged.
- “Find a minimal seal” is not “find a minimum-cost seal”; inclusion-minimal
  repairs can be arbitrarily expensive.
- Arbitrary abort/kill, permanent all-order repair, one final atomic block, and
  an ordered partition into atomic blocks are different problems.

A paper theorem should choose one operational contract. The cleanest extension
of the existing fixed-batch rule is the following.

### 5.2 Minimum-cost final seal

Choose (H\subseteq P). Owners in (R=P\setminus H) execute as singleton
Prepare operations; then all owners in (H) execute in one atomic Prepare
block. Give each owner a nonnegative coordination cost (c_b), and minimize
(c(H)=\sum_{b\in H}c_b).

**Theorem 5 (exact final-seal criterion).** (H) is a feasible final atomic seal
iff

1. backward peeling empties (R=P\setminus H); and
2. every sealed owner remains supported after that serial prefix:

\[
\forall b\in H.\quad p(P\setminus H)\le h_b.
\tag{16}
\]

**Proof.** If (1) holds, reverse peeling supplies a safe order for (R). If (2)
holds, antitonicity means every owner in (H) remains supported throughout all
earlier prefixes and hence is not cleaned. It is therefore open when the final
atomic Prepare occurs. Original atomic-batch validity supplies the durable-load
premise for that block. Conversely, any such execution gives a serial order of
(R), and every member of the final block must still be supported immediately
before it, which is (16). ∎

In the killer representation, initialize reverse activation with all of (H).
Condition (16) says every bundle rooted in (H) intersects (H); peeling the
rest says that this internally admissible seed activates the entire structure.

The decision version is in NP: guess (H), check (16), and run peeling.

### 5.3 NP-complete even for scalar pure choice

The following is a complete reduction, not an analogy.

Take a 0-1 knapsack decision instance with item values (a_i), item costs
(c_i), target value (V), and budget (W). The question is whether some set
(H) has (sum_{i\in H}a_i\ge V) and
(sum_{i\in H}c_i\le W). We may assume
(0<a_i<V\le A=\sum_i a_i): an item with value at least (V) and affordable
cost makes the instance immediately yes, and unaffordable such items can be
discarded.

Construct a one-coordinate authority state:

- (G=A) and (d=0);
- a pure-choice contract admitting only $\varnothing$ and owner singletons;
- one promoted group per owner with (p_i=a_i); and
- full tentative demand (r_i=V), adding residual tentative demand
  (V-a_i) outside the promoted group.

The source is well formed because (a_i\le r_i=V\le G), and the choice
contract never combines owner bundles. The full atomic batch is valid because
(sum_i p_i=G). Every owner has the common headroom

\[
h_i=G-r_i=A-V.
\tag{17}
\]

For a nonempty final seal (H), condition (16) is

\[
p(P\setminus H)=A-p(H)\le A-V
\quad\Longleftrightarrow\quad p(H)\ge V.
\tag{18}
\]

When (18) holds, every order of (P\setminus H) is safe because its entire
load is at most the common headroom. When (H=\varnothing), no full serial
order exists: its last owner (i) has predecessor load
(A-a_i>A-V) because (a_i<V). Hence there is a final seal of cost at most
(W) iff the original knapsack instance is yes.

The problem is therefore weakly NP-complete even with:

- one scalar resource;
- a pure-choice source contract;
- identical owner headrooms; and
- a compact numeric representation.

This result does not justify claiming that *unweighted* scalar sealing is hard;
the reduction uses an independent coordination cost (c_i). It does justify a
weighted industrial objective—for example, some owners may cover high-risk
external effects or expensive cross-provider coordination.

### 5.4 Explicit killer rank: rank one is tractable, rank two is hard

Let the rank be the largest explicit killer size.

**Rank one.** Write an arc (a\to b) for the singleton killer
({a}\in\mathcal H_b). Reverse peeling is Kahn elimination. A final seal
(H) must be predecessor-closed: if (b\in H), every (a\to b) must also be
in (H). Moreover, (P\setminus H) must be acyclic. Therefore the unique
inclusion-minimal final seal is the predecessor closure of all vertices in
nontrivial strongly connected components. SCC decomposition plus reverse
reachability computes it in linear time; positive costs do not change the
forced set.

**Weighted rank two.** Minimum final seal is NP-hard. Reduce Vertex Cover on
(G=(V,E)). For every vertex (i), create events (s_i,t_i). For every edge
(e=\{u,v\}), create event (x_e), and create a gate (g). Give the events
the following killer bundles:

\[
\begin{aligned}
\mathcal H_{s_i}&=\{\{t_i,g\}\},
&\mathcal H_{t_i}&=\{\{s_i,g\}\},\\
\mathcal H_{x_{\{u,v\}}}&=\{\{s_u,s_v\}\},
&\mathcal H_g&=\{\{x_e\}:e\in E\}.
\end{aligned}
\tag{19}
\]

Set (c(s_i)=c(t_i)=1), and
(c(x_e)=c(g)=2k+1). Ask for a final seal of cost at most (2k).

The budget excludes (x_e) and (g). Internal admissibility forces
(s_i\in H\Leftrightarrow t_i\in H), so (H) selects vertex pairs. An edge
event (x_{\{u,v\}}) becomes peelable exactly when (s_u) or (s_v) is in
the selected seal. The gate becomes peelable only after every edge event; then
the gate releases every unselected pair. Thus the reverse closure reaches all
events iff the selected vertices cover every edge, and seal cost is twice the
cover size. All killers in (19) have size at most two. Small instances of this
gadget were also exhaustively checked against minimum Vertex Cover.

This explicit rank-two instance can be embedded in the paper's vector authority
calculus with polynomial size. For each rooted killer ((K,b)), introduce one
resource coordinate with

\[
G_{K,b}=|K|,\qquad
p_{a,(K,b)}=\mathbf1[a\in K],\qquad
r_{z,(K,b)}=\mathbf1[z=b\ \lor\ z\in K].
\tag{20}
\]

Use a pure-choice source contract. In coordinate ((K,b)), root (b) has
headroom (|K|-1), so exactly prefixes containing all of (K) kill it. A
member (z\in K) also has headroom (|K|-1), but a prefix checked for (z)
omits (z), so that coordinate can never kill (z); every other owner has
headroom (|K|). Singletons are source-safe and the atomic promotion load
equals capacity. Hence (20) realizes precisely the declared rooted killer
clutter.

The rank dichotomy is useful, but it is not by itself a breakthrough: minimum
deadlock repair and feedback problems already have a large literature.

### 5.5 Strong closest optimization work

Jain, Hajiaghayi, and Talwar study minimum-cost generalized AND/OR deadlock
resolution: kill the cheapest transactions so the survivors have an executable
order. They give Set Cover hardness even with one AND node and separately study
a permanent repair intended to survive arbitrary scheduling
([ICALP 2005, DOI 10.1007/11523468_69](https://doi.org/10.1007/11523468_69)).

Our final seal preserves and coordinates effects instead of killing/aborting
owners, so it is not the same optimization problem. Nevertheless, it is close
enough that “minimum repair is NP-hard” or a Set Cover reduction alone is not a
novel contribution. A publishable result would need an authority-specific exact
algorithm, approximation guarantee, parameterization, or dynamic certificate
that the deadlock literature does not supply.

## 6. Closest-work map and novelty risk

| Candidate claim | Closest primary work | Same claim? | Conservative conclusion |
|---|---|---:|---|
| Minimal killers as rooted hyperedges | Gallo et al., directed hypergraphs; Ausiello et al., minimal directed-hypergraph representations | High | Use as representation vocabulary only. |
| Reverse trace requires one earlier member from every bundle | DES trace semantics in Arbach et al.; BES origin in Langerak | Exact after removing conflicts | Do not claim a new event-structure semantics. |
| Safe-order existence by greedy peeling | Möhring--Skutella--Stork AND/OR precedence feasibility | Exact | Their Algorithm 1 and generalized-cycle theorem subsume the abstract result. |
| Once eligible, always eligible; arbitrary choices; unique core | Antimatroid/pruning process in Ardila--Maneva and earlier Korte--Lovász theory | Exact | Call it an antimatroid specialization, not a new greedoid. |
| Scalar start deadlines | Jackson EDD; Lawler backward sequencing | Exact specialization | No scheduling novelty in one coordinate. |
| Conflict-graph acyclicity/serial order | Papadimitriou serializability | Adjacent | Our edges are support loss, not read/write conflict; explain the difference. |
| Semantic commutativity | Weihl commutativity-based concurrency control | Adjacent | Promotion updates commute algebraically but cleanup changes enabledness; this is the authority-specific part. |
| Coarsen atomic groups | Shasha et al. transaction chopping | Close mechanism | Chopping finds fine serializable pieces; sealing coarsens pieces to retain authority. Compare explicitly. |
| Minimum repair of AND/OR deadlock | Jain--Hajiaghayi--Talwar generalized deadlock resolution | Strongly adjacent | Preserving sealed effects is the distinction; hardness alone is weak novelty. |
| Maximally permissive safe scheduling | Ramadge--Wonham supervisory control | Encompassing framework | The arithmetic test is a symbolic specialization, not new supervisor synthesis. |
| Dependencies change after lifecycle events | Arbach et al. dynamic-causality ESs | Strong abstract threat | Novelty must be versioned authority refinement and runtime enforcement, not merely dynamic bundles. |

Primary links for the adjacent database results are:

- Papadimitriou,
  [“The Serializability of Concurrent Database Updates,” JACM 1979](https://doi.org/10.1145/322154.322158);
- Weihl,
  [“Commutativity-Based Concurrency Control for Abstract Data Types,” IEEE TC 1988](https://doi.org/10.1109/12.9728);
- Shasha et al.,
  [“Transaction Chopping: Algorithms and Performance Studies,” TODS 1995](https://doi.org/10.1145/211414.211427); and
- Ramadge and Wonham,
  [“Supervisory Control of a Class of Discrete Event Processes,” 1987](https://doi.org/10.1137/0325013).

The key semantic difference from database serializability is worth retaining.
Database conflicts usually constrain which interleavings are equivalent to a
serial history. Here, even denotationally commuting promotion filters can make a
future owner disappear because exact repair triggers eager cleanup. The schedule
protects a conditional authority promise, not a read/write outcome. That is a
real specialization, but Theorem 4 shows that its static ordering structure is
still classical.

## 7. Agent-specific dynamic extension

Static peeling assumes a frozen batch. Real Codex/Claude-like agent runtimes
violate that assumption in exactly the operations that motivate this project:

- Fork or live Restore creates continuations and can change which owners may
  remain jointly durable.
- Replacing Restore, Select, Abort, and Revoke remove or terminalize owners and
  epochs.
- Merge can add correlations or identify lineages.
- A successful external tool call promotes a conditional claim into durable
  demand.
- A crash can occur between admission, durable ticket creation, dispatch, and
  receipt recording.

A static order is therefore not enough. The promising new object is a
**versioned authority schedule certificate**

\[
\chi=(\mathit{batchId},v,\mathit{contractHash},
      \mathit{ownerEpochs},P,p,h,\sigma,R^\star,\eta),
\tag{21}
\]

where (sigma) is a peeling/safe-order witness, (R^\star) is empty for a
positive certificate or carries the dead core for a negative one, and (eta)
contains either prefix inequalities or the coordinates from (10).

### 7.1 A useful preservation theorem to prove

Suppose a lifecycle transition maps the certified batch to surviving owners
(P'\subseteq P), preserves their owner/grant epochs and effect bindings, and
satisfies

\[
p'_b\le p_b,
\qquad
h'_b\ge h_b
\quad (b\in P').
\tag{22}
\]

Then the restriction of (sigma) to (P') is safe: every predecessor vector
only decreases and every deadline only increases. The same monotonicity lets an
implementation update the core incrementally when owners disappear, capacity
increases, or promotion weights decrease.

This theorem is simple, but it gives a principled runtime contract:

- **projection-safe transition:** transform and retain the certificate;
- **invalidating transition:** batch membership grows, a promotion vector grows,
  a deadline shrinks, an epoch changes, or a lineage is rebound—rerun peeling or
  abort/seal the batch;
- **racing transition:** serialize through a compare-and-swap on batch version or
  reject the stale Prepare certificate.

The real theorem must use the paper's actual Fork/Restore/Merge/Abort/Revoke
rules, not only (22). In particular, support-preserving lineage projection must
show that the new (p,h) truly refine the old authority state. Dynamic-causality
event structures already allow events to add and remove causal dependencies, so
“the dependency graph changes” is not new. The candidate contribution is the
authority-specific refinement rule and its checkable certificate.

### 7.2 Crash and external-effect boundary

A safe order proves only that Prepare operations remain authorized. It does not
prove exactly-once dispatch or reversible external history. A real adapter needs:

1. durable one-shot effect IDs and batch version before dispatch;
2. atomic installation of the selected order/seal certificate with the prepared
   ticket;
3. rejection of stale owner/grant epochs;
4. idempotent receipt reconciliation after crash; and
5. product-wide mediation of every effect sink covered by the theorem.

No scheduling theorem can prove truthful claim weights, complete mediation,
provider idempotence, or the absence of an uninstrumented side channel. Those
remain explicit assumptions/evaluation obligations.

### 7.3 Forked RL rollouts

The same mechanism is relevant to reinforcement-learning or search runtimes
that fork many rollouts from one checkpoint. Conditional claims may be shared
across mutually exclusive rollouts, but an irreversible tool effect in one
rollout becomes durable across the surviving history. The scheduler can decide
whether several rollout effects may be prepared serially, identify an authority
dead core, or require a joint seal.

This does **not** make the result an RL algorithm. It is an authority layer for
rollout environments with external effects. The evaluation should therefore
measure unsafe/overconservative effect admission and coordination cost, not
model reward improvement unless a causal connection is demonstrated.

## 8. Recommended contribution architecture

### 8.1 What is strong enough to retain

The following theorem chain is coherent and useful:

1. **Authority-to-deadline lemma:** derive (p_b,h_b) and prove singleton
   support, eliminating the general support oracle for fixed-batch scheduling.
2. **Serial-or-core theorem:** backward peeling returns a safe Prepare order or
   the canonical coordinate-certified authority-dead core.
3. **Universal-order corollary:** Boundary II is the case in which every owner
   is initially peelable.
4. **Serial-or-seal theorem:** characterize one final atomic fallback by
   Theorem 5; state weighted hardness and tractable rank-one/scalar fast paths
   honestly.
5. **Versioned lifecycle refinement:** prove exactly which real lifecycle rules
   preserve a certificate and which require revalidation/sealing.
6. **Crash-stable runtime refinement:** Prepare before Dispatch under one-shot
   tickets realizes the abstract scheduled trace.

The first four are mathematically clean but mostly classical structure plus a
new domain derivation. The fifth and sixth must carry the agent-specific novelty.

### 8.2 What not to claim

Do not claim:

- a new notion of hypergraph acyclicity;
- a new AND/OR topological sort;
- a new antimatroid or greedoid algorithm;
- that order existence is exponential;
- that owner support requires a global oracle in the current fixed-batch model;
- that minimizing the number of atomic blocks is meaningful without a size/cost
  objective;
- NP-hardness for an unweighted or fixed-rank case not covered by a complete
  reduction;
- that dynamic dependencies alone are agent-specific; or
- safety under arbitrary concurrent lifecycle mutation without a versioned
  linearization point.

### 8.3 Does this beat Boundary II as the main contribution?

**Static answer: no.** The safe-order iff, peeling algorithm, hypergraph
obstruction, and antimatroid core are too directly subsumed by primary prior
work. Replacing Boundary II with those facts as the headline would make the
paper broader but less novel.

**Dynamic authority answer: potentially yes.** “Serial or seal” is a more useful
runtime decision than “all orders or not,” and the compact authority arithmetic
is attractive. It becomes a plausible CSF contribution if the paper adds all of:

- an authority-specific lifecycle preservation/invalidity theorem;
- a checkable, version-bound schedule/core/seal certificate;
- crash-stable integration at one real agent dispatch boundary; and
- workload evidence that real traces contain multi-owner batches for which
  arbitrary order fails but peeling succeeds, plus cases that require sealing.

Without those results, keep the peeling algorithm as a strengthening of the
existing Boundary II section, not a new paper thesis.

### 8.4 Minimal evaluation if pursued

The theory should dominate, but a small evaluation is still necessary:

- extract fixed-batch owner groups from instrumented Fork/Restore/Merge/tool
  histories;
- compare arbitrary order, Boundary-II all-order admission, peeling, full atomic
  sealing, and minimum-final-seal ILP/DP baselines;
- report admitted batches, dead-core size, seal cost, revalidation frequency,
  and certificate-check latency;
- replay crash points between certificate installation, Prepare, Dispatch, and
  receipt; and
- include synthetic threshold instances only to demonstrate exponential killer
  expansion, not as the primary workload evidence.

## 9. Proof obligations and falsifiers

Before canonical adoption, the following obligations should be discharged.

| Obligation | Why it matters | Falsifier |
|---|---|---|
| State source owner-support explicitly in Lemma 1 | Otherwise ({b}) need not be available | One unsupported singleton owner executes despite no support |
| Prove every residual (r_b-p_b) is nonnegative | Needed for singleton minimality | A refund/negative claim makes a larger configuration cheaper |
| Show cleanup restriction is denotationally inert for surviving singletons | Connects arithmetic to the LTS | A removed owner reappears or its claims affect a surviving configuration |
| Freeze batch membership, weights, capacity, epochs, and owner map | Needed for one (p,h) instance | Interleaved Fork/Revoke changes an inequality after certification |
| Specify whether (U_b) is the full owner batch group | Needed for atomic-block semantics | An unmodeled same-owner group is cleaned before later Prepare |
| Define final seal as one atomic Prepare, not delayed cleanup prose | Avoids changing the machine implicitly | Members execute individually while unsupported without a generated rule |
| Mechanize Theorems 2, 4, and 5 over the actual LTS | Prevents abstraction mismatch | Lean/explorer finds a safe inequality order that the rule rejects |
| Audit closest work before a novelty claim | Static result has exact precedents | A cited AND/OR/DES theorem states the claimed result verbatim |

## 10. Search record and primary-source coverage

Search was performed on 2026-08-01. Queries were claim-oriented and name-free
first, then narrowed to primary papers and known terminology.

### 10.1 Query groups

**Directed hypergraphs and elimination**

- `directed hypergraph acyclicity topological ordering elimination algorithm hyperarc tail head primary paper PDF`
- `"directed hypergraph" "topological ordering" acyclic`
- `"B-hypergraph" acyclic directed hypergraph elimination`
- `directed hypergraph cycle topological sort Gallo Longo Pallottino Nguyen 1993`
- `generalized cycle directed hypergraph AND OR feasibility primary`

**Antimatroids, greedoids, and pruning**

- `antimatroid monotone shelling elimination order feasible sequences primary paper`
- `antimatroid feasible words monotone enabling prerequisites learning space primary paper PDF`
- `greedoid elimination ordering monotone property arbitrary eligible element primary source`
- `shelling antimatroid elimination ordering rooted circuits Korte Lovasz primary`
- `Korte Lovasz alternative precedence structures antimatroid paper 1981 DOI`
- `Dietrich antimatroid rooted circuits primary paper DOI`

**Bundles and event structures**

- `bundle event structures disjunctive causality secured configuration enumeration primary paper PDF`
- `"bundle event structures" "secured" configuration`
- `"extended bundle event structures" disabling relation paper`
- `"dual event structures" disjunctive causality bundles`
- `Langerak bundle event structures LOTOS 1992 primary paper`
- `Katoen dual event structures definition event trace bundle`
- `Arbach dynamic causality in event structures journal bundle dual DOI`

**Scheduling and deadlines**

- `OR precedence constraints scheduling primary paper DOI single machine`
- `"AND/OR precedence" scheduling primary paper`
- `"disjunctive precedence constraints" scheduling complexity`
- `project scheduling threshold activities at least k predecessors primary paper`
- `Jackson 1955 scheduling production line maximum lateness EDD primary report`
- `Lawler 1973 optimal sequencing single machine precedence maximum cost paper DOI`

**Deadlock and repair**

- `AND OR wait-for graph deadlock detection knot model primary paper`
- `generalized resource request AND-OR deadlock model knot primary paper`
- `minimum deadlock recovery abort processes wait-for graph NP-hard primary`
- `"The Generalized Deadlock Resolution Problem" authors`
- `"AND-OR directed feedback vertex set"`
- `minimum seed set AND OR graph activation NP-hard target set selection primary paper`

**Transactions and atomic grouping**

- `Papadimitriou serializability concurrent database updates JACM 1979 DOI`
- `transaction chopping algorithms performance studies Shasha Llirbat Simon 1995 DOI`
- `commutativity based concurrency control abstract data types Weihl 1988 DOI`
- `atomic groups transaction serializability grouping scheduling deadlock primary paper`

### 10.2 Primary sources that control the verdict

1. Rolf H. Möhring, Martin Skutella, and Frederik Stork,
   [“Scheduling with AND/OR Precedence Constraints,” SIAM J. Comput. 33(2), 2004](https://doi.org/10.1137/S009753970037727X).
   Exact same-claim source for explicit waiting-condition feasibility, linear
   peeling, and generalized-cycle obstruction.
2. Federico Ardila and Elitza Maneva,
   [“Pruning Processes and a New Characterization of Convex Geometries,” Discrete Mathematics 309, 2009](https://doi.org/10.1016/j.disc.2008.08.020).
   Exact source for monotone removal, antimatroid structure, rooted pruning
   rules, and unique residual closure/core.
3. Youssef Arbach, David S. Karcher, Kirstin Peters, and Uwe Nestmann,
   [“Dynamic Causality in Event Structures,” LMCS 14(1), 2018](https://doi.org/10.23638/LMCS-14(1:17)2018).
   Exact DES trace definition and strongest threat to a generic dynamic-bundle
   claim.
4. Rom Langerak,
   [“Bundle Event Structures: A Non-Interleaving Semantics for LOTOS,” FORTE 1992](https://dl.acm.org/doi/10.5555/646211.683771).
   Original bundle-event-structure anchor.
5. Giorgio Gallo, Giustino Longo, Stefano Pallottino, and Sang Nguyen,
   [“Directed Hypergraphs and Applications,” Discrete Applied Mathematics 42, 1993](https://doi.org/10.1016/0166-218X(93)90045-P).
   Directed-hypergraph and AND/OR graph foundation.
6. Kamal Jain, MohammadTaghi Hajiaghayi, and Kunal Talwar,
   [“The Generalized Deadlock Resolution Problem,” ICALP 2005](https://doi.org/10.1007/11523468_69).
   Strongest optimization-adjacent source for minimum-cost AND/OR repair and
   Set Cover hardness.
7. J. R. Jackson,
   [“Scheduling a Production Line to Minimize Maximum Tardiness,” Report 43, 1955](https://ntrl.ntis.gov/NTRL/dashboard/searchResults/titleDetail/AD152722.xhtml),
   and E. L. Lawler,
   [“Optimal Sequencing of a Single Machine Subject to Precedence Constraints,” 1973](https://doi.org/10.1287/mnsc.19.5.544).
   Scalar deadline and backward-scheduling anchors.
8. Christos H. Papadimitriou,
   [JACM 1979](https://doi.org/10.1145/322154.322158), William E. Weihl,
   [IEEE TC 1988](https://doi.org/10.1109/12.9728), and Dennis Shasha et al.,
   [TODS 1995](https://doi.org/10.1145/211414.211427).
   Serializability, semantic commutativity, and atomic-grouping comparators.

### 10.3 Excluded false friends

- Undirected hypergraph alpha-acyclicity/GYO reduction is not the relevant
  notion; the exact object is directed AND/OR waiting-condition feasibility.
- Acyclic hypergraph partitioning asks for an acyclic quotient and does not
  supply the authority promotion or cleanup semantics.
- Generic target-set selection treats selected seeds as enabled for free. A
  final atomic seal must be internally admissible by (16), so target-set
  hardness does not transfer without a gadget.
- Directed feedback vertex set models deleting/aborting vertices. Sealing keeps
  the owners and executes them atomically; the optimization requires a separate
  reduction.
- View/conflict serializability and transaction chopping do not model owner
  support or eager cleanup, although they are important mechanism-level
  comparators.

## Bottom line

The mathematical correction is decisive: **safe-order synthesis is a monotone
backward peeling problem, not exponential search**. It yields a practical
vector-deadline algorithm, a canonical dead core, and a compact certificate;
Boundary II becomes its elegant universal-order corollary.

The novelty correction is equally decisive: **the static hypergraph,
antimatroid, DES trace, and AND/OR feasibility structure are established**. The
paper should openly reuse them. The potentially new CSF story is not “agents
need hypergraph scheduling.” It is:

> Conditional-to-durable agent effects induce versioned vector deadlines over
> branch owners. A runtime can checkably serialize them, prove that no serial
> order exists, or pay for an atomic seal; lifecycle mutations must refine or
> invalidate that certificate before any irreversible dispatch.

That story is more useful than Boundary II and genuinely agent-specific, but it
becomes a main contribution only after the versioned lifecycle theorem and real
dispatch-boundary enforcement are completed.
