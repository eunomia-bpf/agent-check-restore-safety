# Independent hostile audit of serial-or-final-seal theory

**Date:** 2026-08-01  
**Scope:** read-only audit of the Step 0006 `killer-hypergraph` report, plus the
candidate fiber-expansion and persistent-slot generalizations.  This report did
not edit the paper, canonical research records, executable model, or Lean
development, and it did not commit or push anything.

## Executive verdict

The static mathematics is substantially correct, but its publication value and
some theorem premises need tighter treatment.

1. **The singleton-support reduction is correct** under source owner support,
   downward closure, nonnegative demand, and `p_b <= r_b`.  Those are
   load-bearing premises, not presentation details.
2. **The vector start-deadline characterization is correct.**  Under exact
   cumulative repair and eager deterministic cleanup, the inequalities
   characterize both continued enabledness and, for a successful complete
   order, equality with the atomic repaired authority family.
3. **Backward peeling, choice-independent residual core, and the coordinate
   no-order certificate are correct.**  They are also direct specializations of
   established AND/OR precedence feasibility and pruning-process results.  They
   should be used, but not claimed as new concurrency theory.
4. **The final-seal iff is correct only with the valid-full-batch premise made
   explicit.**  Without `d + p(P) <= G`, its two displayed conditions can hold
   while the atomic block itself is inadmissible.
5. **The scalar pure-choice covering-knapsack reduction is correct.**  The
   phrase “weakly NP-complete” needs a pseudo-polynomial upper bound, not only a
   reduction from Knapsack.  Such an upper bound does exist: a direct
   `O(n P^2)` dynamic program, where `P=sum_b p_b`, is given below and matched
   exhaustive search on 226,578 small scalar instances.
6. **The rank-one SCC characterization and rank-two Vertex Cover embedding are
   correct.**  They are useful complexity landmarks, but hardness by itself is
   not a CSF-level novelty claim in view of generalized deadlock resolution,
   minimum knapsack with forcing constraints, and feedback-set literature.
7. **The candidate fiber-expansion theorem is correct and more useful for this
   paper than static minimum-seal hardness.**  A safe source owner can be
   replaced in place by a contiguous fiber in any internal order when total
   tentative demand and total promoted demand are separately conserved and
   every child promotion is contained in its tentative demand.  A source final
   seal lifts to the union of its sealed fibers.
8. **A persistent-slot generalization is valid, but only as a versioned
   residual-budget theorem.**  It supports repeated same-slot splitting,
   conservative same-slot coarsening, deletion, and slot-major partial Prepare.
   It does not authorize a Merge by itself, allow cross-slot coarsening or
   interleaving, tolerate unmatched increases in durable load, or permit claim
   or epoch rebinding.

The strongest Step 0007 direction is therefore not “minimum atomic sealing is
hard.”  It is:

> A versioned schedule can survive agent Fork/Restore refinement by transporting
> ordered authority slots.  Conservative same-slot descendants may be ordered
> locally or sealed together, while cross-slot Merge, effect rebinding, and
> unmatched durable-state change are explicit revalidation boundaries.

This is still a domain-specific refinement theorem, not a wholly new scheduling
theory.  Its value comes from connecting the existing lifecycle transfer
checker, actual Prepare/cleanup semantics, and a usable incremental runtime
algorithm.

## 1. Audited statement and assumptions

Let `P` be the owners of a fixed promotion batch.  For each owner `b`, let

\[
p_b=\sum_{c\in U_b}w(c),\qquad
r_b=\sum_{c\in Q_b}w(c),\qquad
h_b=G-d-r_b,
\]

componentwise over nonnegative resource coordinates.  Thus `p_b <= r_b`.
For `S subseteq P`, promotion produces durable load `d+p(S)` and leaves
`r_z-p_z` conditional demand at promoted owner `z`.

The audit treats the following as mandatory premises:

- the source family is downward closed;
- every owner with a promised tentative bundle has a source support witness;
- the source is authority-safe;
- owner groups are fixed, unique, and disjoint;
- all quantities are nonnegative and every promoted claim is already in its
  owner's tentative bundle;
- repair is the exact cumulative capacity filter;
- unsupported nonempty tentative bundles are cleaned immediately and
  deterministically;
- the batch, capacity, durable load outside this batch, owner map, epochs, and
  bindings do not change during the static theorem; and
- when an atomic endpoint or final seal is mentioned, the full atomic batch is
  itself valid.

Dropping these premises changes the problem.  In particular, negative/refund
claims destroy singleton minimality, an unsupported source owner destroys the
singleton witness, and a lifecycle race can invalidate an otherwise correct
numeric schedule.

## 2. Claim-by-claim mathematical audit

### 2.1 Singleton support

For a configuration `C` containing `b`, exact promotion after owner set `S`
has load

\[
L_S(C)=d+p(S)+\sum_{z\in C}(r_z-\mathbf 1[z\in S]p_z).
\]

Downward closure and source owner support give `{b}` in the source family.  For
every `C` containing `b`,

\[
L_S(C)-L_S(\{b\})=
\sum_{z\in C\setminus\{b\}}
(r_z-\mathbf 1[z\in S]p_z)\ge 0.
\]

Therefore `{b}` is the cheapest possible support witness and

\[
\mathsf{Supp}_b(F_S)
\Longleftrightarrow
p(S\setminus\{b\})\le G-d-r_b=h_b.
\]

**Verdict:** correct.  This is a valuable authority-specific compilation lemma:
the fixed-batch scheduler needs vector arithmetic rather than a global guarded
support oracle.  It is not valid for negative claims, a family without source
support, or a promotion not drawn from `Q_b`.

### 2.2 Start deadlines and successful endpoint equality

For a forward order `b_1,...,b_n`, the Prepare of `b_i` is enabled exactly when

\[
\sum_{j<i}p_{b_j}\le h_{b_i}.
\]

The forward implication follows from the singleton-support result.  Conversely,
the inequalities supply a support witness for every not-yet-prepared owner at
every earlier prefix, so eager cleanup cannot terminalize that owner.

Successful endpoint equality requires more than ordinary deadline scheduling:
it uses the fact that all prefix repairs are intersections of the same
cumulative nonnegative capacity constraints, and that restriction after exact
cleanup is denotationally inert for surviving support.  With those paper
premises, the serial endpoint is the atomic repaired endpoint.

**Verdict:** correct under the stated LTS assumptions.  The arithmetic schedule
alone proves enabledness; the paper's exact-repair and cleanup lemmas are what
prove endpoint equality.

### 2.3 Backward peeling and the residual core

For residual owner set `R`, owner `b` can be placed last exactly when

\[
p(R\setminus\{b\})\le h_b.
\]

Removing owners only decreases the left-hand side, hence eligibility is
monotone.  If a safe order exists, any currently eligible `b` can be moved to
the end: every job crossed by `b` loses the nonnegative predecessor load `p_b`,
and `b` is safe in its chosen last position.  Thus arbitrary eligible deletion
is complete.

All maximal deletion runs have the same residual fixed point `R*`.  If it is
nonempty, choosing for every `b in R*` a coordinate where

\[
\sum_{a\in R^*\setminus\{b\}}p_{a,k_b}>h_{b,k_b}
\]

gives a direct no-order certificate: the last core member in any proposed order
violates its selected coordinate.

**Verdict:** correct, including choice independence and the certificate.  The
abstract result is classical AND/OR feasibility/pruning.  The compact vector
representation and coordinate witness are the useful specialization.

### 2.4 Final atomic seal

For `H subseteq P`, let `R=P\H` execute serially and let `H` execute as one final
atomic Prepare.  The exact criterion is:

1. `R` has a safe order; and
2. `p(R) <= h_b` for every `b in H`.

Condition 2 keeps every sealed owner supported through every prefix of `R`.
Condition 1 supplies the serial prefix.  Full atomic-batch validity supplies
the capacity premise for promoting the final block.

**Mandatory correction:** theorem text must explicitly quantify a valid full
batch.  Without it, take two pure-choice owners with `G=1`, `d=0`,
`r_1=r_2=p_1=p_2=1`, and `H=P`.  Peeling the empty `R` succeeds and every sealed
owner has `p(R)=0<=h_b=0`, yet atomically promoting both owners requires load 2
under capacity 1.

The criterion also assumes that the sealed claims remain open with unchanged
bindings and epochs.  Numeric support cannot revive a claim already aborted,
revoked, or prepared under another effect ID.

**Verdict:** correct after making those premises syntactically visible.

### 2.5 Scalar pure-choice Knapsack reduction

The Step 0006 construction from covering/0-1 Knapsack is sound.  With
`G=A=sum_i a_i`, `r_i=V`, `p_i=a_i`, and common `h_i=A-V`, a nonempty final
seal is feasible exactly when

\[
\sum_{i\in H}a_i\ge V.
\]

The assumptions `0<a_i<V<=A` make every source singleton safe, make the full
atomic batch valid, and rule out an empty serial repair.  Coordination cost is
exactly the Knapsack item cost.

This proves NP-hardness for one scalar resource, pure choice, and common
headroom.  Membership in NP follows from a guessed seal plus peeling.

To justify the stronger adjective **weakly NP-complete**, use the following
pseudo-polynomial algorithm for the complete scalar final-seal problem, not
only the common-headroom reduction.

Let `delta_i=h_i+p_i` and `P=sum_i p_i`.  Enumerate the total serial promotion
load `T=0,...,P`.  A job with `h_i<T` cannot be sealed and is therefore
mandatory in the serial set.  Sort jobs by `delta_i`.  For this fixed `T`, run a
deadline DP indexed by current accepted processing time `t<=T`:

- a mandatory job must be accepted, with `t+p_i<=delta_i`;
- an optional job may be accepted under the same deadline test or sealed at
  cost `c_i`;
- retain the minimum seal cost for every `t` and read the cell `t=T`.

The best cell over all `T` is optimal.  This takes `O(nP^2)` time and `O(P)`
working memory per `T`.  The proof is the standard EDD characterization of a
selected feasible set plus the observation that `h_i>=T` is exactly the final
support condition for every rejected/sealed job.

**Verdict:** reduction correct; “weakly NP-complete” becomes justified when the
pseudo-polynomial upper bound is included.  The DP is useful for moderate
one-dimensional budgets, but its novelty is uncertain because it lies very
close to classical single-machine scheduling with job rejection.

### 2.6 Rank-one explicit killers

For singleton killer `{a}` rooted at `b`, orient the arc `a -> b` in the reverse
activation graph.  A final seal is predecessor-closed, and its unsealed
remainder must be acyclic.  Intersecting any directed cycle forces the whole
cycle into a predecessor-closed seal; this in turn forces every ancestor of a
cycle.

Hence the unique inclusion-minimal final seal is the predecessor closure of all
vertices in nontrivial SCCs.  Killer sets exclude their own root, so self-loops
do not arise from this authority construction.  With nonnegative costs, every
feasible seal contains this forced set, so positive weighting does not change
the answer.

**Verdict:** correct.  State the arc orientation and “nontrivial SCC” convention
explicitly.

### 2.7 Rank-two Vertex Cover gadget and vector embedding

The gadget works as claimed:

- the budget excludes every edge event and the gate;
- internal seal support forces `s_i` and `t_i` to be selected together;
- an edge event activates exactly when at least one endpoint pair is selected;
- the gate activates after all edge events; and
- the gate then releases every unselected vertex pair.

Thus a seal of cost at most `2k` corresponds exactly to a vertex cover of size
at most `k`.

The coordinate-per-rooted-killer embedding is also sound.  In coordinate
`(K,b)`, capacity `|K|`, promotion coefficients on `K`, and tentative demand on
`K union {b}` make the root fail exactly when all of `K` precedes it.  A member
of `K` cannot be killed by this coordinate because its own promotion is omitted
from its predecessor set.  Pure-choice singletons are safe and the full atomic
promotion reaches capacity exactly.

**Verdict:** correct.  This proves weighted rank-two hardness, not unweighted
hardness and not an approximation lower bound.

## 3. Independent finite audit

The checks below were written independently from the Step 0006 diagnostic code.
They are falsification aids, not substitutes for proofs.

| Property checked | Search space | Result |
|---|---:|---|
| Singleton support over all supported downward-closed three-owner scalar source families | 14,352 safe, valid-batch states; 344,448 support queries | 0 mismatches |
| Deadline enabledness and successful atomic endpoint equality in the same exact-filter/cleanup model | 86,112 owner permutations; 73,716 successful | 0 mismatches |
| Peeling existence versus exhaustive permutation search | 8,400 random vector instances, up to 7 owners and 3 coordinates | 0 mismatches |
| Choice-independent terminal core | the same 8,400 instances, enumerating every eligible deletion branch | 0 nonunique cores |
| Final-seal criterion versus exhaustive serial-prefix search | 304,800 owner subsets | 0 mismatches |
| Knapsack construction versus minimum final-seal cost | 139,644 exhaustive small Knapsack instances | 0 mismatches |
| Scalar `O(nP^2)` DP versus exhaustive seal/order search | 226,578 instances | 0 mismatches |
| Rank-one SCC formula | all 4,165 loopless digraphs through 4 vertices; 66,066 seed checks | 0 mismatches |
| Rank-two Vertex Cover gadget | all 1,099 graphs through 5 vertices; 1,065,508 cheap seed subsets | 0 mismatches |
| Fiber expansion, scalar exhaustive | 136,936 expanded internal orders | 0 mismatches |
| Final-seal fiber lifting, scalar exhaustive | 115,841 lifted seals | 0 mismatches |
| Fiber expansion, random vector stress | 43,429 safe source refinements; 322,230 internal orders; 41,567 seal lifts | 0 mismatches |

One early multi-coordinate harness version accidentally consumed a generator
while summing coordinates and emitted a false peeling mismatch.  The summation
was corrected to materialize its input, the run was restarted, and only the
corrected counts above are reported.

## 4. Closest optimization work and novelty ceiling

### 4.1 Primary-source comparison

| Candidate result | Closest primary work | Overlap judgment | Paper consequence |
|---|---|---|---|
| AND/OR safe-order feasibility, greedy deletion, obstruction | Möhring, Skutella, and Stork, [Scheduling with AND/OR Precedence Constraints](https://doi.org/10.1137/S009753970037727X) | Exact abstract structure | Credit it; claim only authority-to-vector compilation and LTS connection. |
| Minimum-cost repair of AND/OR waiting | Jain, Hajiaghayi, and Talwar, [The Generalized Deadlock Resolution Problem](https://doi.org/10.1007/11523468_69) | Strongly adjacent; their repair kills transactions, while a seal preserves and coordinates effects | Hardness alone is weak novelty.  Compare against their small-AND/OR and approximation results. |
| Scalar deadline subset DP | Lawler and Moore, [A Functional Equation and its Application to Resource Allocation and Sequencing Problems](https://doi.org/10.1287/mnsc.16.1.77) | Strong mechanism overlap | Present the scalar DP as an authority specialization unless a full scheduling search finds an exact prior formulation. |
| Common-headroom scalar final seal | Bentz and Le Bodic, [FPTAS for the Minimum Knapsack Problem](https://arxiv.org/abs/1607.07950) | Exact reduction to a known problem | Reuse the known FPTAS; do not claim a new approximation scheme. |
| Covering plus pairwise forcing | Takazawa and Mizuno, [Minimum Knapsack with a Forcing Graph](https://doi.org/10.15807/jorsj.60.15) | Very close to pairwise seal constraints; includes Vertex Cover and gives a 2-approximation | A rank-two hardness theorem is only a boundary result. |
| Component schedule refinement | Shin and Lee, [Compositional Real-Time Scheduling Framework with Periodic Model](https://doi.org/10.1145/1347375.1347383), and Matic's [interface-refinement thesis](https://www2.eecs.berkeley.edu/Pubs/TechRpts/2008/EECS-2008-12.html) | Same high-level goal of preserving schedulability under component refinement, different timing model and no authority lifecycle | Fiber/slot refinement is not generic compositional-scheduling novelty; the authority transfer and cleanup instantiation must carry the claim. |

The generalized deadlock paper is especially close.  It already defines
minimum-cost removal so that the survivors admit some execution order, proves
hardness at least as strong as Set Cover/direct Steiner variants, gives
algorithms when one AND/OR class is small, and studies a permanent repair that
survives adversarial order.  Preserving effects in one final atomic seal is a
real semantic difference from killing transactions, but it does not make the
surrounding optimization landscape unoccupied.

### 4.2 What can safely enter the paper

The following are sound supporting results:

- singleton support compiles the paper's fixed-batch scheduling query to compact
  vector deadlines;
- peeling supplies an executable order or a compact coordinate obstruction;
- Boundary II is the exact all-orders corollary;
- final-seal feasibility has a simple verifier;
- rank one is linear-time and the general weighted problem is already hard in
  restricted cases; and
- a scalar exact DP is practical when the resource amount is moderate.

The following should not be sold as headline novelty:

- a new hypergraph cycle or antimatroid;
- a new AND/OR topological sort;
- novelty from NP-hardness alone;
- a new scalar Knapsack approximation; or
- a generic theorem that component refinement preserves a schedule.

## 5. Useful solvable special cases

### 5.1 General scalar authority: exact pseudo-polynomial DP

The `O(nP^2)` DP in Section 2.5 is the most useful new algorithmic observation
from this audit.  It handles unequal owner deadlines, not only the reduction's
common headroom.  It is appropriate when a runtime tracks a small integer
budget such as a bounded number of deployments, messages, approvals, or costly
tool calls.

This result should be treated as **potentially useful but novelty-unverified**.
Classical weighted-tardy-job and rejection scheduling is close enough that a
paper claim requires a dedicated scheduling-literature audit.

### 5.2 Common headroom: import existing Knapsack algorithms

If every owner has the same headroom `h`, a remainder `R` is serially feasible
whenever `p(R)<=h`, and that same inequality supports every sealed owner.
Minimum final sealing is therefore minimum-cost covering Knapsack.  In one
dimension, use the established FPTAS.  With a small fixed vector dimension and
moderate integer capacities, the ordinary product-table covering DP is a
reasonable exact engineering path.  Neither is a new theoretical contribution.

### 5.3 Explicit rank one: SCC fast path

The forced predecessor closure of cyclic SCCs is exact, linear-time, and easy to
certify.  This is a good runtime fast path when every owner has only singleton
killers, but it is classical graph structure.

### 5.4 Why “small dead core” is not yet a safe parameterization claim

Every feasible seal must disturb the no-seed obstruction, but it need not be
contained in the canonical dead core.  A peelable outside owner may still need
to join the final block so that its promotion does not precede and kill a core
owner.  Consequently, enumerating only subsets of `R*` is not a correct FPT
algorithm.  Any small-core result needs an additional bound on the external
coordination halo, killer rank/degree, or resource budget.

## 6. Fiber-expansion schedule theorem

### 6.1 Exact statement

Let `b_1,...,b_m` be a safe source order under available capacity
`g=G-d`:

\[
\sum_{j<i}p_{b_j}\le g-r_{b_i}.
\]

Replace every source owner `b` by a nonempty target fiber `F_b`.  Assume:

\[
\sum_{x\in F_b}r'_x\le r_b,
\qquad
\sum_{x\in F_b}p'_x\le p_b,
\qquad
p'_x\le r'_x.
\]

Keep fibers in source order and choose any internal permutation of each fiber.
Then the expanded target order is safe.

For target owner `x in F_b`, let `A_b` be all target promotion before its fiber
and `I_x` the promotion earlier inside its fiber.  Then

\[
A_b\le\sum_{a\prec b}p_a,
\qquad
I_x\le\sum_{y\in F_b\setminus\{x\}}r'_y\le r_b-r'_x.
\]

Adding these inequalities to source safety gives

\[
A_b+I_x\le g-r'_x,
\]

which is exactly target safety.

The fully exact per-instance condition is simply
`A_b+I_x <= g-r'_x` for every target owner.  The aggregate fiber inequalities
are compositional sufficient conditions, not necessary conditions for every
particular instance.

### 6.2 Load-bearing conditions and counterexamples

All examples below are scalar with `d=0`; tuples show `(r,p)`.

| Removed condition | Safe source | Target transformation/order | Failure |
|---|---|---|---|
| Promotion conservation `sum p'<=p_b` | `G=10`, `a=(5,1)`, `b=(9,1)`, order `a,b` | replace `a` by `a'=(5,5)` | `b` sees predecessor 5 but headroom 1 |
| Tentative-demand conservation `sum r'<=r_b` | `G=10`, `a=(5,2)` | replace by `a1=(1,1), a2=(10,1)` | `a2` sees predecessor 1 but headroom 0 |
| Child containment `p'_x<=r'_x` | `G=5`, `a=(5,5)` | `a1=(0,5), a2=(5,0)` | `a2` sees predecessor 5 but headroom 0 |
| Fiber contiguity/local block discipline | `G=10`, `a=(10,5)`, `b=(5,5)`, order `a,b` | `a1=(1,1), b, a2=(9,4)` | `a2` sees predecessor 6 but headroom 1 |
| No cross-owner coarsening | `G=10`, source `a=(3,3), b=(6,2), c=(5,1)`, order `a,b,c` | merge `b,c` into `x=(8,3)`, order `a,x` | `x` sees predecessor 3 but headroom 2 |

These are necessity examples for the **uniform local theorem**.  A specific
instance may violate an aggregate condition and still pass a direct global
deadline check because it has slack.

### 6.3 Lift of a final seal

Suppose the source has a feasible serial prefix `R` and final seal `H`.  Expand
the serial owners by the theorem and set

\[
H'=\bigcup_{b\in H}F_b.
\]

For `x in F_b` with `b in H`,

\[
p'(R')\le p(R)\le g-r_b\le g-r'_x.
\]

Thus every target sealed owner remains supported, and total target promotion is
no larger than the valid source batch.  The union `H'` is therefore a feasible
target final seal.

This preserves feasibility, not optimal coordination cost.  Splitting one
source owner into many descendants can make a per-owner seal-cost objective
larger unless costs are transported by a separate rule.

### 6.4 Connection to the actual lifecycle

The existing claim-transfer checker can imply `sum r'<=r_b` when every target
claim owned by a descendant maps to a tentative claim of source owner `b` and
fibers conserve demand.  It does **not automatically imply**
`sum p'<=p_b` for the scheduled batch.  Certificate transport also needs a
batch-refinement map proving that every target promoted claim refines one of the
source batch claims, with the same stable effect binding.

The theorem applies naturally to:

- replacing Restore with conservative claim transfer;
- live Restore or parallel Fork whose co-durable fragments conserve total
  tentative and promoted demand;
- a selected choice descendant after durable selection; and
- deletion, Abort, or Revoke projection, which only removes future load.

It does not permit copying the same promotion budget into several descendants
that may all commit.  Exclusive choice may share authority in the wider paper
semantics, but a schedule containing all descendants then needs the correlation
contract or a post-selection certificate; it cannot use a simple sum-conserving
fiber proof.

## 7. Persistent ordered slots across multiple lifecycle rounds

### 7.1 A valid residual-budget formulation

Give each source owner `b_i` a stable ordered slot `i` with initial envelopes

\[
R_i=r_{b_i},\qquad P_i=p_{b_i},
\qquad
\sum_{j<i}P_j\le g_0-R_i.
\]

After some slot-major owner groups have been prepared, let `E_i` be the total
promotion already prepared from the certified batch in slot `i`.  Under no
unmatched external durable effect,

\[
g_t=g_0-\sum_iE_i.
\]

Every current tentative owner has exactly one slot.  For the remaining fixed
batch, require

\[
\sum_{x:\,slot(x)=i}r_x\le R_i-E_i,
\qquad
\sum_{x:\,slot(x)=i}p_x\le P_i-E_i,
\qquad
p_x\le r_x.
\]

Terminalized or withdrawn claims may make the first two inequalities strict.
They do not create reusable authority: stable claim IDs, epochs, and the batch
map must still prevent revival under the unused numeric slack.

Execution is slot-major.  Only the earliest slot with remaining certified
promotion may Prepare; owners inside that slot may be chosen in any order.
Topology transformations may repeatedly split, delete, or conservatively merge
owners **within the same slot**, provided the lifecycle checker separately
establishes target well-formedness, support, epoch validity, and binding
preservation.

### 7.2 Why the multi-step induction works

Consider a remaining owner `x` in slot `i`.  Promotions still to execute in
earlier slots are bounded by

\[
\sum_{j<i}(P_j-E_j),
\]

and promotion earlier inside slot `i` is bounded by
`(R_i-E_i)-r_x`.  Because slot-major execution implies no `E_j>0` for a future
slot before the current cursor, their sum is at most

\[
\sum_{j<i}P_j-\sum_{j<i}E_j+R_i-E_i-r_x
\le g_0-\sum_{j\le i}E_j-r_x
\le g_t-r_x.
\]

This is the current support deadline.  A Prepare of amount `q` from the current
slot decreases `g_t`, the slot's tentative envelope, and its remaining batch
envelope by the same `q`.  Conservative within-slot transfer is transitive, so
any number of such rounds preserves the inequalities.

This induction covers partial **slot** completion: some complete owner groups
in the slot may Prepare before further same-slot refinement.  If one owner group
itself is split across several Prepare operations, the actual LTS needs an
additional same-owner grouping lemma; the current paper's Boundary II treats
one fixed `U_b` group per owner.

### 7.3 Same-slot Merge is conditional, not free

If owners `x,y` in one slot are replaced by `z` with

\[
r_z\le r_x+r_y,qquad p_z\le p_x+p_y,qquad p_z\le r_z,
\]

the slot envelopes and hence the schedule proof are preserved.  This permits
reuse of the schedule certificate **after** a checked same-slot Merge.

It does not make the Merge transition authority-safe by itself.  The existing
simulation/direct-admission rule must still prove the target contract,
correlations, active-owner support, claim provenance, and epoch changes.  A
numeric slot label cannot legalize merging mutually exclusive lineages or
rebinding an already prepared effect.

### 7.4 Invalidating events and counterexample boundaries

- **Cross-slot Merge/coarsening:** aggregate conservation across several source
  slots does not identify a safe target position.  The `a,b,c -> a,x`
  counterexample in Section 6.2 is already sufficient.
- **Cross-slot interleaving:** a later slot can consume headroom needed by a
  remaining fragment of an earlier slot; the `a1,b,a2` counterexample is
  sufficient.
- **Unmatched durable-load increase:** if `d` increases without removing the
  same certified amount from a slot's tentative/batch envelopes, every later
  deadline shrinks.  Revalidate or invalidate the certificate.
- **Capacity decrease:** likewise invalidating; a capacity increase is safe.
- **Batch growth or effect substitution:** a numerical `p` bound is not enough;
  new claims or effect IDs require a new batch version and admission.
- **Epoch, owner-lineage, or binding change:** invalid even when all vector
  inequalities happen to remain true.
- **Prepare from a future slot:** breaks the cancellation used in the induction.
- **Choice copying:** several exclusive descendants may share a conditional
  promise, but they cannot all be placed in one persistent sum-bounded slot as
  co-durable promotions unless their total is conserved or selection occurs
  first.

The certificate therefore needs at least batch ID/version, contract hash,
owner/claim epochs, stable slot lineage, residual `R/P` envelopes, the scheduled
claim map, and the order or final-seal set.  A compare-and-swap on this version
must linearize Prepare against lifecycle mutation.

## 8. Which direction should Step 0007 freeze?

| Criterion | Static minimum final seal | Versioned slot/fiber refinement |
|---|---|---|
| Closest-work risk | High: generalized deadlock repair, Knapsack, forcing graphs, scheduling with rejection | Medium: generic compositional scheduling exists, but not this authority transfer/cleanup instantiation |
| Agent-specificity | Moderate; a fixed batch could be any workflow | High; directly covers Fork, replacing/live Restore, descendant transfer, same-lineage Merge, epochs, and partial Prepare |
| Runtime value | Chooses how much coordination to buy after a dead core appears | Avoids global re-solving across ordinary lifecycle refinement and identifies exactly when revalidation is mandatory |
| Formal burden | Criterion and hardness are mostly done; exact optimization beyond special cases is large | Small vector lemma plus a nontrivial induction over actual lifecycle/Prepare rules |
| Evaluation burden | Needs meaningful natural seal costs and hard instances | Can reuse the existing dispatch-owning adapter and controlled lifecycle histories |
| Credible CSF contribution | Supporting algorithm/complexity boundary | Candidate main RQ when connected to actual LTS and mechanized |

**Recommendation:** freeze the versioned slot/fiber refinement direction.
Retain minimum final sealing as the fallback optimization problem and include
only the verifier, restricted hardness, and practical fast paths that fit.

## 9. Recommended Step 0007 RQ, hypothesis, and minimal evidence plan

### Research question

> **When can a serial-or-final-seal authority certificate be transported across
> Fork, Restore, partial Prepare, and Merge without global re-solving, and which
> lifecycle changes necessarily force revalidation?**

### Hypothesis

For a versioned fixed effect batch, an ordered-slot certificate is preserved by
deletion, conservative same-slot claim refinement, checked same-slot
coarsening, and slot-major owner-group Prepare.  The restricted serial order and
the union-lifted final seal remain safe in the actual exact-repair/cleanup LTS.
Cross-slot coarsening or interleaving, unmatched durable-load increase, batch
growth, and epoch/effect rebinding are not generally preservative; each class
has a finite counterexample and must trigger revalidation, rejection, or a new
atomic seal.

This should be stated as preservation for an explicit transition grammar plus
counterexamples outside it, not prematurely as the weakest possible condition
over every conceivable lifecycle transformation.

### Minimal mechanization

1. Define a versioned slot certificate over the existing lifecycle state and
   actual fixed promotion batch; do not introduce a disconnected abstract
   checker.
2. Prove the vector fiber-expansion lemma and source-order refinement.
3. Connect claim-level transfer/fiber conservation to owner-level `R` bounds,
   and add the missing batch-refinement relation needed for `P` bounds.
4. Prove final-seal lifting.
5. Prove one-step preservation for deletion, canonical Fork/Restore transfer,
   checked same-slot Merge, and current-slot `PrepareOK/prepareState`; compose
   these into a trace induction.
6. Mechanize concrete counterexamples for cross-slot coarsening, cross-slot
   interleaving, unmatched `d` increase, and promotion-budget copying.
7. Keep stable IDs, epochs, target WF/support, exact cleanup, and full-batch
   validity explicit in theorem statements and `#print axioms` output.

The smallest real preflight should be a two-slot source certificate that is
split twice, prepares one owner in slot one, performs a checked same-slot merge
of the remaining descendants, and kernel-proves the transported order and
lifted seal.  A negative sibling case should perform the same numeric merge
across slots and be rejected or require recomputation.

### Minimal real experiment

The theory remains headline evidence.  A small runtime experiment should test
only whether the premises are observable and useful:

- instrument the existing dispatch-owning Codex adapter with stable batch,
  epoch, effect-ID, and slot metadata;
- run controlled Fork, replacing/live Restore, deletion, same-slot refinement,
  same-slot Merge, cross-slot Merge, and crash-before/after-Prepare histories;
- compare transported certificates against one exact global re-solve oracle;
- use “invalidate on every lifecycle change” as the strongest current-practice
  baseline and “seal the full batch” as the conservative coordination baseline;
- report decision agreement, certificate reuse rate, global re-solves avoided,
  admitted serial batches, final-seal size/cost, stale-version rejections, and
  certificate-check latency; and
- use public agent traces only to motivate lifecycle and observability fields,
  not to label real executions unsafe when authority/receipt ground truth is
  absent.

Positive, negative, and mixed results all change the paper decision.  Exact
agreement plus substantial reuse supports the incremental-runtime claim.
Agreement with negligible reuse leaves only a formal compositionality result.
Any oracle disagreement refutes the implementation or theorem instantiation.
Missing native lifecycle/authority fields makes the runtime result
inconclusive, not positive evidence.

## 10. Bottom line

The Step 0006 report's static theorem chain survives hostile mathematical
checking, with two qualifications: the valid-full-batch premise must be made
explicit, and weak NP-completeness needs the scalar pseudo-polynomial upper
bound.  The reductions and fast paths are credible supporting material, but
primary work already owns most of the abstract scheduling and optimization
structure.

The more interesting advance is compositional lifecycle transport.  Fiber
expansion gives a clean local rule for nonduplicating Fork/Restore refinement;
final seals lift; persistent residual slots make the rule survive multiple
transfers and slot-major Prepare; and concrete counterexamples isolate Merge,
interleaving, durable-load, version, and binding boundaries.  Mechanized over
the actual authority LTS, this is both more agent-specific and more industrially
useful than another static hardness theorem.
