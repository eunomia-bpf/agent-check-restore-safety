# Formal closest-work map for Boundary II

Audit date: 2026-08-01 (America/Vancouver)

Scope: read-only theorem-level novelty audit of `Boundary II: order-independent promotion` in `docs/paper/sections/results.tex`. This report does not assess the whole paper's novelty. It asks whether the theorem is a direct instance of prior concurrency, partial-order-reduction, disruption, resource, authorization, or supervisory-control results; if not, it isolates the smallest paper-specific statement that survives.

## Executive decision

**Literal-instance verdict: no.** None of the inspected sources states the paper's exact equivalence

\[
  \text{all owner-group serializations remain enabled and equal the atomic seal}
  \quad\Longleftrightarrow\quad
  \text{every promoted owner has final repaired support}.
\]

**Theorem-shape verdict: mostly established.** The left-hand side is a familiar concurrency condition in three equivalent-looking presentations:

1. a local full Boolean/asynchronous cube of executions;
2. enabledness-preserving, commuting transitions on a restricted state cone; and
3. a batch-conditional independence/serializability context.

The generic fact that an event can disable future events, followed by a remainder/cleanup operation that removes them, is also established. Therefore Boundary II is **not defensible as a new notion of concurrency, order independence, conditional independence, asymmetric conflict, or disruption**.

**What survives:** the final-owner-support formula is a paper-specific, complete, one-final-policy characterization of when the authority-promotion transitions are conditionally independent under eager cleanup and when their arbitrary serialization agrees with one atomic batch. No inspected prior source gives that authority-specific closed form.

The strongest honest positioning is:

> For exact authority repair with eager support cleanup, final repaired support is the principal batch-indexed conditional-independence precondition: it is necessary and sufficient for the fixed-batch promotion cone to form a full asynchronous cube and for every scheduler serialization to refine the atomic seal.

Here “principal” should mean *semantically exact for this calculus*, not “polynomial-time,” “minimal in every predicate language,” or “a new definition of independence.” The reduction replaces universal reasoning over all prefixes/permutations with support checks in one final repaired policy; the cost of those symbolic support checks still depends on the contract representation and solver.

**Risk rating:** high if sold as a standalone new concurrency theorem; moderate and potentially defensible if sold as an exact weakest-precondition/compiler certificate for this authority semantics, accompanied by a formal translation and refinement theorem.

## 1. Candidate claim, stripped of paper terminology

Let $O$ be the finite set of owners whose nonempty groups are in a fixed batch. Let $p_b$ be the irreversible operation for owner $b\in O$. Each $p_b$:

1. transfers $b$'s selected demand from branch-conditional demand to globally durable demand;
2. intersects the set of allowed futures with the exact safe-future predicate induced by that transfer; and
3. immediately removes any still-pending owner that occurs in no remaining allowed future.

There is also one atomic operation $p_O$ that transfers all groups, repairs once, and cleans up once.

Boundary II says that, from a fixed valid source state and without lifecycle interference,

\[
\begin{split}
&\text{every permutation of }\{p_b\}_{b\in O}\text{ is executable and has}\\
&\text{the same normalized authority endpoint as }p_O
\end{split}
\]

if and only if every $b\in O$ occurs in some future allowed by the final exact repair for $O$.

This normalization makes clear that the target is not generic rollback or generic workspace consistency. It is an exact serializability condition for a fixed family of irreversible authority-promotion operations whose cleanup can disable a later operation.

## 2. The paper-specific algebra

For $S\subseteq O$, write $U_S=\bigcup_{b\in S}U_b$, $W_b=\sum_{c\in U_b}w(c)$, and let $F_S$ be the exact safe-future family after promoting the groups in $S$, before deleting unsupported owners. For an original future $C\in\Phi$, its load after $S$ is

\[
  \ell_S(C)
  = d+q(C)+\sum_{b\in S\setminus C}W_b.
\]

The identity follows because a claim in $U_b$ was charged only in futures containing $b$, whereas after promotion it is durable and charged in every future. Thus

\[
  F_S=\{C\in\Phi\mid \ell_S(C)\le G\}.
\]

Define support by

\[
  \mathsf{Supp}_b(F)\;\equiv\;\exists C\in F.\ b\in C.
\]

Two elementary properties do all of the theorem-specific work.

### 2.1 Monotone repair

If $S\subseteq R\subseteq O$, then

\[
  F_R\subseteq F_S,
\]

because every additional promoted group weakly increases load in futures that do not contain its owner. Final support is therefore a witness at every prefix:

\[
  \mathsf{Supp}_b(F_O)\Longrightarrow \mathsf{Supp}_b(F_S)
  \quad(S\subseteq O).
\]

### 2.2 Owner self-neutrality

For $b\notin S$, adding $b$'s own promotion does not change the load of any future containing $b$. Hence

\[
  \mathsf{Supp}_b(F_{S\cup\{b\}})
  \quad\Longleftrightarrow\quad
  \mathsf{Supp}_b(F_S).
\]

The sufficiency direction of Boundary II is monotonicity plus commutation of exact set intersections. The necessity direction orders $b$ last and applies self-neutrality:

\[
  \neg\mathsf{Supp}_b(F_O)
  \Longrightarrow
  \neg\mathsf{Supp}_b(F_{O\setminus\{b\}}),
\]

so eager cleanup removes $b$ while $U_b$ is still pending and disables the last operation.

This is the smallest identifiable paper-specific mathematical ingredient. It is a load-transfer identity and a last-owner witness lemma, not a new concurrency primitive.

## 3. Direct mapping to transition independence and POR

### 3.1 Flanagan and Godefroid, POPL 2005

Definition 1 on printed page 3 of *Dynamic Partial-Order Reduction for Model Checking Software* defines a valid dependency relation. Two transitions declared independent must satisfy, in every state:

1. executing either one preserves whether the other is enabled; and
2. when both are enabled, both two-step orders reach the same unique state.

The paper immediately summarizes this as: independent transitions neither enable nor disable one another, and enabled independent transitions commute. It also notes that its presentation assumes the dependency relation is not conditional, referring to Katz and Peled for conditional dependency.

Under the final-support condition, Boundary II's owner transitions have exactly these two properties **on the finite prefix cone for the fixed source and fixed batch**:

- final witnesses keep every unexecuted owner enabled at every prefix; and
- exact promotion filters commute and normalize to the same state after either adjacent order.

Adjacent swaps then generate all permutations. Conversely, failed final support produces an enabledness-preservation violation in the order with the unsupported owner last.

The differences from Definition 1 are important but narrow:

- DPOR's relation is normally a relation on transitions valid throughout the whole system state space. Boundary II proves a batch-local relation only on states reachable from one source by subsets of $O$.
- Boundary II additionally compares the serial endpoint with a distinguished atomic batch transition. Transition independence alone does not define that atomic transition; equality relies on this paper's exact-repair algebra.
- Boundary II gives a closed form for this local independence context rather than assuming or dynamically discovering an independence relation.

**Verdict:** not a literal instance of a theorem in Flanagan--Godefroid, but its operational target is precisely local transition independence. Final-owner support is best understood as an authority-specific complete certificate for Definition 1's obligations on the fixed-batch cone.

### 3.2 Katz and Peled, TCS 1992

Katz and Peled's *Defining Conditional Independence Using Collapses* explicitly extends trace semantics with conditional commutativity: predicates identify the global-state contexts in which operations commute, so the same operations may be dependent in one context and independent in another. This is the closest conceptual predecessor to using final support as an independence condition.

For the present model, define the batch-indexed predicate

\[
  K_O(A)\;\equiv\;\bigwedge_{b\in O}\mathsf{Supp}_b(F_O(A)).
\]

After enriching the operation context with the fixed sealed batch $O$, Boundary II says exactly that $K_O$ is the context in which all of the batch's owner-group promotions remain enabled, commute throughout their reachable cone, and agree with the atomic batch.

Two qualifications prevent a claim of literal subsumption:

- the inspected publisher/author metadata and abstract establish state-predicate conditional commutativity, but the paywalled full TCS text was not available locally for line-by-line theorem matching; and
- $K_O$ is n-ary and batch-indexed, while ordinary conditional independence is often presented pairwise. Pairwise local independence follows here only after using the paper's exact-repair and normalization lemmas.

**Verdict:** the notion “operations are independent exactly in states satisfying a predicate” is prior art. The potentially new part is only the derivation that this authority semantics has the closed-form predicate $K_O$, plus its completeness for atomic-seal refinement.

### 3.3 van Glabbeek and Plotkin, TCS 2009

Definition 2.1 on printed page 4120 (PDF page 10) defines an asynchronous step $x\to y$ by $x\subseteq y$ and the requirement that **every intermediate set** $z$ with $x\subseteq z\subseteq y$ is a configuration. The accompanying text explains that concurrent events can be performed in any order. Proposition 2.2 relates this step notion to pure event structures.

Map an executed owner set $S\subseteq O$ to a configuration. Under final support, every subset is reachable, and algebraic commutation gives one normalized state for each subset. The interval $[\varnothing,O]$ is therefore a full Boolean/asynchronous cube. If final support fails, some intermediate subset/order is absent because cleanup has disabled a pending owner.

The same paper also warns, in Section 2.4 (printed page 4122), that configurations alone lose behavior in impure/order-sensitive cases and an explicit transition relation is needed. Its examples of asymmetric conflict already exhibit “one order exists, the reverse does not,” which is the generic shape of the paper's two-owner counterexample.

**Verdict:** “all intermediate subsets/orders exist” is established structure. Boundary II contributes, at most, a domain-specific exact test for when that structure arises from authority repair and eager cleanup.

## 4. Direct mapping to disabling and cleanup

Fecher and Majster-Cederbaum's *Event Structures for Arbitrary Disruption* (Fundamenta Informaticae 68, 2005) introduces precursor event structures with set-indexed disabling. Definition 4.6 (printed page 114; author-manuscript page 12) defines the remainder after an initial event by removing every event disabled by it and removing precursor information containing removed events. Proposition 4.1 equates executable event traces with iterated defined remainders.

This is very close to the operational role of immediate cleanup:

- a set/prefix of promoted groups changes the allowed-future family;
- loss of all support disables a still-pending owner-group event; and
- cleanup removes that event/owner from the remainder.

The paper's disabling cause is resource- and support-derived rather than declared as a primitive relation, but “execution deletes future events” and even set-based/higher-order disruption are not new. Pinna's disabling/enabling event structures and later dynamic/reversible event-structure variants create additional adjacent prior-art risk, although they were not needed to decide the current theorem.

**Verdict:** cleanup is a domain interpretation of established disruption semantics. The novel candidate is the compilation from final repaired support to the induced disabling relation, not the disabling operator itself.

## 5. Other close foundations

### 5.1 Configuration structures and higher-order conflict

van Glabbeek and Plotkin's Definition 1.1/1.2 treats arbitrary configuration families, and their early examples include ternary conflict (every pair permitted, the triple forbidden) and asymmetric/order-sensitive behavior. Theorem 2 (printed page 4114) maps every configuration structure to a pure event structure with the same configurations.

Therefore arbitrary downward-closed durability families, correlations beyond pairwise conflict, and the negative example's order asymmetry are not by themselves theorem-level novelties.

### 5.2 Resource-tracking concurrent games

The correct authors of *Resource-Tracking Concurrent Games* are **Aurore Alcolei, Pierre Clairambault, and Olivier Laurent**, not Castellan and Clairambault. The paper combines prime event structures with a resource bimonoid having sequential and parallel composition (Definitions 1 and 2; printed pages 32 and 34) and proves soundness/adequacy results (Theorems 1 and 2; printed pages 39 and 42).

Its abstract explicitly says tracked resources are modified during execution but do not affect control flow. It therefore does not contain support-triggered disabling, conditional-to-durable transfer, exact policy pruning, or the final-support iff. It establishes the surrounding resource/event machinery, not Boundary II.

### 5.3 Consumable credentials

Bowers et al.'s *Consumable Credentials in Logic-Based Access-Control Systems* (NDSS 2007) already addresses globally bounded authority and multi-party atomic ratification. Section 4.1 (PDF page 5) requires all-or-nothing ratification: all ratifiers record all credential uses and verification succeeds, or no ratifier records a use. The implementation uses multiparty contract signing and nonce/formula-bound ratification credentials; the paper also discusses extra-logical restoration after later proof rejection.

Thus irreversible authorization, atomic multi-owner sealing/ratification, replay-safe operation binding, and the need for coordination are established. The current paper differs in branch-conditioned co-durability, exact future repair, eager owner cleanup, and a condition under which atomic ratification can be replaced by arbitrary-order serial promotion.

### 5.4 Supervisory control

Feng, Wonham, and Thiagarajan's communicating-transaction-process work proves existence of a supremal controllable nonblocking language (Theorem 1, printed page 126) and shows that modular supervisors may conflict, requiring global nonblocking checks or coordination (Theorem 2, printed page 129). It compiles supervisory disablement into logical guards and message-sequence behavior. Ma and Wonham's state-tree-structure work gives predicate/state-feedback conditions for controllable, coreachable, nonblocking behavior in hierarchical concurrent state spaces.

A finite instance of the current fixed batch can be encoded as a plant whose events are owner promotions, whose uncontrollable choice is scheduler order, and whose bad states include cleanup-disabled pending owners. Generic supervisory control can then check whether all orders remain nonblocking and can synthesize restrictions.

What these sources do not provide is the paper's closed-form reduction from that reachability/nonblocking question to final support. For a fixed batch, however, “our full system is dynamic” does not evade the baseline: the theorem is a domain-specific shortcut/characterization inside an established transition-system control problem.

### 5.5 Partial observation and relative observability

Cieslak et al.'s partial-observation supervisory-control result and Cai et al.'s relative-observability result concern implementability of supervisors under incomplete observation and computation of controlled sublanguages. They are relevant to later work where a runtime observes only a projected agent trace, but they are not direct predecessors of the full-information, fixed-source Boundary II theorem.

## 6. Formal factorization of Boundary II

The current result factors into four layers:

| Layer | Statement | Prior-art status |
|---|---|---|
| Concurrency target | Every intermediate subset/order exists and adjacent independent actions commute | Established by trace/POR/configuration-structure theory |
| Conditionality | Independence may hold only in contexts described by state predicates | Established by Katz--Peled and later conditional POR |
| Operational asymmetry | Executed events can disable/remove pending events | Established by asymmetric/disruption event structures |
| Authority certificate | Exact durable promotion monotonically shrinks futures; an owner's own promotion is neutral on futures containing that owner; therefore final support exactly characterizes the full cube | No exact prior statement found |

This factorization answers the direct-instance question precisely:

- **Not a direct theorem substitution:** prior work does not instantiate a variable with `final support` and yield the exact atomic-vs-serial iff.
- **A direct semantic specialization:** once the authority load identity proves monotonicity and self-neutrality, the left side is standard conditional independence/full-cube behavior and the proof is short.
- **Likely contribution class:** a complete domain-specific independence/serializability certificate, not new concurrency theory.

## 7. Smallest genuinely new ingredient

### 7.1 Not new

The following should not be claimed as new:

- downward-closed or arbitrary configuration families;
- higher-order conflict or “all pairs fit but the set does not”;
- sequential/parallel resource aggregation;
- transition commutation, confluence, serializability, or all-order execution;
- state-conditional independence predicates;
- event disabling, asymmetric conflict, or removal from a remainder;
- consumable authority or atomic multi-party ratification; or
- nonblocking supervisory control under scheduler choices.

### 7.2 New assumption/identity candidate

The smallest paper-specific structure is the conjunction of:

1. **monotone exact repair:** $S\subseteq R\Rightarrow F_R\subseteq F_S$;
2. **owner self-neutrality:** adding $b$'s transfer cannot change support of $b$ itself;
3. **eager witness cleanup:** a still-pending $b$ is removed exactly when $\mathsf{Supp}_b$ is false; and
4. **commutative normalized repair:** absent cleanup, group transfers and their exact filters have one subset-indexed normalized endpoint.

No one of these is a novel generic operator. Their authority-specific derivation from conditional-to-durable demand is the candidate new lemma.

### 7.3 New conclusion candidate

Under those assumptions, the formula

\[
  K_O=\bigwedge_{b\in O}\mathsf{Supp}_b(F_O)
\]

is a complete certificate for all of the following, in this calculus:

1. no prefix cleanup disables a pending promotion;
2. every permutation is executable;
3. the promotion cone has the full Boolean interval of subsets;
4. adjacent group promotions are enabledness-preserving and commuting on that cone; and
5. every serial endpoint equals the atomic exact-repair endpoint.

Items 1 and 5 are the domain-specific bridges. Items 2--4 are established concurrency vocabulary.

## 8. Strongest honest theorem-level novelty statement

The paper should avoid “we discover when concurrent operations commute.” A defensible statement is:

> **Principal independence guard for eager authority promotion.** For a fixed batch of irreversible owner-group promotions over a downward-closed durability policy, suppose exact repair monotonically removes futures, each owner's transfer is neutral on futures containing that owner, cleanup eagerly removes unsupported pending owners, and repaired states have a canonical subset-indexed normalization. Then the batch's promotion cone is a full asynchronous cube and every scheduler serialization observationally refines the atomic batch if and only if every promoted owner has a witness in the final repaired policy. Consequently the universal prefix/permutation condition has the exact batch precondition $K_O$, checkable by support queries against one final repaired policy.

This statement is stronger and cleaner than the current threshold-only presentation while remaining honest about prior work. The exact capacity guard can then be an instantiation that proves the abstract assumptions using

\[
  \ell_S(C)=\ell_\varnothing(C)+\sum_{b\in S\setminus C}W_b.
\]

The paper may call $K_O$ a **batch-indexed conditional-independence guard**, **serial-refinement certificate**, or **weakest precondition under the stated semantics**. If using “weakest precondition,” it must define the state/batch predicate domain and prove semantic equivalence; it should not imply syntactic minimality in arbitrary logics.

## 9. What would make the contribution nontrivial enough

The current proof is essentially monotonicity plus self-neutrality. To turn it into a strong CSF contribution, add the following formal chain rather than only renaming the theorem.

### 9.1 A trace-preserving translation

Define an explicit translation from the Prepare/cleanup LTS for a sealed batch to either:

- a conditional independence structure with context predicate $K_O$; or
- a precursor/asymmetric event system whose disabling sets are induced by loss of owner support.

Prove preservation and reflection of executable owner-event traces. This prevents the paper from merely borrowing concurrency words informally.

### 9.2 An abstract theorem plus concrete instantiation

State the monotone/self-neutral theorem over an abstract family $F_S$, prove it once, and instantiate it with the exact resource guard. This reveals the actual principle and separates it from threshold arithmetic, which the paper already admits is not new.

### 9.3 A refinement theorem

Give an observation function and prove:

\[
  K_O(A)
  \Longrightarrow
  \text{SerialAnyOrder}(A,O)\ \sqsubseteq\ \text{AtomicSeal}(A,O).
\]

When $K_O$ fails, prove that an implementation exposing arbitrary scheduler order cannot guarantee the refinement because the explicit order $O\setminus\{b\};b$ fails for some $b$. Preserve the current caveat that a coordinated chosen order may still work.

### 9.4 A certificate and countercertificate format

For success, return one final support witness $C_b\in F_O$ per promoted owner. For failure, return an owner $b$ and the canonical last-owner order $O\setminus\{b\};b$. Prove both certificates check without enumerating permutations. This makes the theorem operationally useful to a real runtime.

Do not claim polynomial complexity unless support over the chosen guarded-contract representation is proved polynomial. The defensible complexity claim is a reduction from all-prefix/all-permutation exploration to $|O|$ support queries on one final repaired policy, plus construction of the exact repair.

### 9.5 A stronger scheduling result if needed

If Boundary II remains too close to conditional independence, go beyond the all-or-nothing certificate. When $K_O$ fails, compute the antichain of minimal promotion sets $S$ that eliminate support for pending $b$. These are authority-derived disabling hyperedges. A sound-and-complete algorithm could then synthesize:

- a safe precedence constraint;
- the minimum owners that must be atomically sealed together; or
- a smallest cleanup deferral/barrier plan.

That would be a more substantial algorithmic contribution than recognizing the fully independent case. It would also connect directly to industrial runtimes: the runtime either dispatches freely, installs a verified order, or seals a minimal atomic block.

## 10. Claim language to use and avoid

### Use

- “We derive an exact authority-specific conditional-independence precondition.”
- “Final support is necessary and sufficient for the fixed-batch promotion cone to be a full asynchronous cube under eager cleanup.”
- “The certificate collapses arbitrary-prefix/permutation validation to support in one final exact repair.”
- “We prove arbitrary scheduler serialization refines the atomic seal under this certificate.”
- “Failure yields a canonical last-owner counterserialization; it does not imply that every chosen order fails.”

### Avoid

- “We introduce order independence/commutation for agent operations.”
- “Existing event structures cannot model cleanup or one action disabling another.”
- “Configuration structures cannot express the durability policy.”
- “Resource-aware concurrency has not considered serial versus atomic execution.”
- “The iff is a new general concurrency theorem.”
- “The check is efficient/polynomial” without a representation-sensitive proof.
- “Failure means the batch cannot be serialized.” The theorem only refutes *all-order* serialization.

## 11. Closest-source matrix

| Source | Exact inspected anchor | What it already gives | What it does not give |
|---|---|---|---|
| Katz & Peled, TCS 101(2), 1992, pp. 337--359, DOI `10.1016/0304-3975(92)90054-J` | Publisher/Technion abstract; 1990 Springer chapter metadata | State-predicate contexts for conditional commutativity and conditional traces | Final-support formula, eager authority cleanup, atomic-seal equality |
| Flanagan & Godefroid, POPL 2005 | Definition 1, printed p. 3 | Independence = enabledness preservation + two-order commutation; adjacent-swap trace classes | A source/batch closed form for authority transitions; distinguished atomic operation |
| van Glabbeek & Plotkin, TCS 410(41), 2009, pp. 4111--4159, DOI `10.1016/j.tcs.2009.06.014` | Definitions 1.1/1.2; Theorem 2; Definition 2.1; Proposition 2.2; Section 2.4 | Arbitrary configuration families, higher-order conflict, asynchronous intervals, order-sensitive cases | Resource-derived support cleanup and its exact final-state test |
| Fecher & Majster-Cederbaum, Fundamenta Informaticae 68(1--2), 2005, pp. 103--130, DOI `10.3233/FUN-2005-681-204` | Definition 4.6; Proposition 4.1 | Set-based disabling and remainder semantics that deletes disabled future events | Authority/resource derivation of disabling; final-support iff |
| Alcolei, Clairambault & Laurent, FoSSaCS 2019, pp. 27--44, DOI `10.1007/978-3-030-17127-8_2` | Definitions 1/2; Theorems 1/2 | Event structures plus sequential/parallel resource algebra | Resources changing control flow, cleanup, serial/atomic criterion |
| Bowers et al., NDSS 2007 | Section 4.1, especially PDF pp. 5--7 | Consumable authority, ratifiers, all-or-nothing multiparty ratification, replay binding | Branch-conditioned co-durability and safe arbitrary-order ratification criterion |
| Feng, Wonham & Thiagarajan, Formal Methods in System Design 30, 2007, pp. 117--141, DOI `10.1007/s10703-006-0023-0` | Theorems 1/2; guard compilation sections | Supremal controllable nonblocking behavior, conflicting modular supervisors, coordination | Closed-form final-support reduction |
| Ma & Wonham, IEEE TAC 51(5), 2006, pp. 782--793, DOI `10.1109/TAC.2006.875030` | Theorems 1/2 in publisher/author web full text | Predicate/state-feedback nonblocking control of hierarchical concurrent state | Exact authority promotion criterion |

## 12. Evidence boundary and source inventory

Primary full texts were preferred. The following local PDFs were inspected; hashes make the audit reproducible.

| Local file | SHA-256 | Evidence note |
|---|---|---|
| `reference/foundations/2009-vanglabbeek-plotkin-configuration-structures.pdf` | `ce4feb6e88624fe3bb1f8ed034735b8ca74aee93092cb6293a877334a206710c` | Full 47-page journal paper |
| `reference/foundations/2019-alcolei-clairambault-laurent-resource-tracking-games.pdf` | `fcd984ecbe518de1e30c844b2b2554d7d24a3c340904ffe5c66dbaf23827d34f` | Full 18-page conference paper |
| `reference/foundations/dynamic-partial-order-reduction-popl2005.pdf` | `859bf80983113da9cd97f39611563111b1498c5c8100fde4014693640a74160d` | Full POPL paper; Definition 1 inspected |
| `reference/closest-work/consumable-credentials-ndss07.pdf` | `ead25e2571a7557b3e89c8a7cfd220cd7176798be6dd50882e89837d7e6a31d9` | Full 15-page paper |
| `reference/supervisory-control/2007-feng-wonham-thiagarajan-ctp.pdf` | `d8a2d23faf5a9988da1b88f0828b5e94ea250480251952bc71da51183578cc06` | Full 25-page journal paper |
| `reference/supervisory-control/2005-ma-wonham-state-tree-structures.pdf` | `cca942953ed1b8de1198efb7243d7cea62ec843c2c788b831b41cda3c1fee085` | Only four pages of Springer book front matter, **not** the TAC full text; theorem statements were checked in publisher/author web text |
| `reference/supervisory-control/cieslak1986-partial-observation.pdf` | `e929be2ec53f9b553bcf088993c291ee28fee2ababf07bb608b28d7eb1b93b3c` | Full/available manuscript inspected for scope |
| `reference/supervisory-control/cai2015-relative-observability.pdf` | `af3650874507ac1cca898d9469555fef07fba7fb0fe652a926c32918ebd48e07` | Full/available manuscript inspected for scope |

For Katz--Peled, the TCS DOI page, Technion publication record, and the Springer 1990 precursor chapter page/abstract were inspected. A full local copy was not available, so this report relies only on the verified high-level claim of predicate-defined conditional commutativity and does not attribute an unverified numbered theorem.

For Fecher--Majster-Cederbaum, the publisher metadata and publicly exposed author full-text rendering were inspected, including Definition 4.6 and Proposition 4.1. Attempts to fetch the public PDF endpoint failed because the host returned TLS/404 errors; no local file is claimed.

Representative search strings included:

- `transition independence enabledness preservation commutation`
- `conditional independence operations commute state predicate Katz Peled`
- `configuration structure asynchronous step every intermediate configuration`
- `event structures disabling remainder arbitrary disruption`
- `resource event structures sequential parallel consumption`
- `consumable credentials atomic ratification`
- `supervisory control nonblocking concurrent transaction guards`
- `state tree structures controllability coreachability nonblocking`

This was a claim-oriented audit, not an exhaustive survey of every dynamic, reversible, asymmetric, bundle, inhibitor, or priority event-structure formalism. Those larger literatures increase the risk of claiming the generic cleanup/disabling mechanism, but no inspected source supplied the exact final-owner-support certificate.

## 13. Factual correction required later

`docs/background-related-work.md` currently attributes *Resource-Tracking Concurrent Games* to “Castellan and Clairambault.” The paper's authors are **Aurore Alcolei, Pierre Clairambault, and Olivier Laurent**. This report does not edit the canonical background file, per task scope, but the citation must be corrected before submission.

## Bottom line

Boundary II is **not** a direct copy of a prior theorem, but its concurrency content is not new. Its honest new core is:

\[
  \boxed{
  \text{final repaired owner support}
  \text{ is the complete authority-specific guard for}
  \text{ local conditional independence + atomic refinement}
  }
\]

To make that a real contribution, formalize the translation, state the abstract monotone/self-neutral theorem, prove a scheduler-to-atomic refinement, and expose success/failure certificates. If the project cannot support those additions, Boundary II should be demoted to a useful systems corollary rather than presented as the paper's central theoretical novelty.
