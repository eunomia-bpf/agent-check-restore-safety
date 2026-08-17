# Closest-work and novelty audit: lifecycle-transported authority schedule certificates

Date: 2026-08-01

Scope: primary-source audit of the proposed version-bound schedule/dead-core/seal
certificate for history-transforming agent authority, including the additional
owner/job-refinement theorem. This report does not modify the paper, Lean model,
canonical story, or implementation.

## 1. Bottom-line verdict

The proposal is **not novel at the level of any one of its generic ingredients**:

- proof-carrying authorization and proof-carrying plans are established;
- checking certificate dependencies or current state at use time is established;
- version/epoch invalidation of capabilities and authorization-cache entries is
  established;
- optimistic validation immediately before a state-changing commit is established;
- a feasible schedule versus a compact infeasibility obstruction is established;
- positive witnesses surviving relaxations and negative cores surviving
  strengthenings is a generic monotonicity pattern, made explicit in incremental
  SAT;
- schedulability-preserving task refinement and incremental reconfiguration are
  established;
- escrow, reservations, and prepared transactions already convert an earlier
  admission into a durable promise that may be completed later.

Therefore a paper whose claim is merely

> version a schedule certificate, invalidate it when the state changes, and
> recheck it before an external action

has very high same-claim risk. A reviewer can accurately summarize that design as
proof-carrying authorization plus selective cache invalidation plus OCC.

The strongest potentially new contribution is a narrower composite theorem:

> A certificate about **aggregate conditional authority over co-durable agent
> futures** has a semantic, polarity-sensitive transport calculus across
> Fork/Restore/Merge/Abort/Revoke. A live positive certificate is not merely
> checked; its next element is **atomically consumed at Prepare**, together with
> advancement of the certificate tail, installation of a durable claim, and
> issuance of a one-shot effect ticket. Later Dispatch consumes that sealed ticket
> and does not revalidate the old plan version. The calculus is exact enough to
> reuse certificates across safe nonidentical histories, yet rejects topology or
> lineage changes that leave all ordinary per-action credentials and object
> versions unchanged.

Even this contribution is publishable only if “semantic transport” is a proved
sound-and-complete or maximal-reuse result over the actual lifecycle transition
system, rather than a hand-written invalidation table. The static peeling
algorithm, certificate polarity, job splitting, version checks, and two-stage
reservation should all be presented as foundations or supporting lemmas, not as
independent novelty.

The newly proposed continuous-fiber expansion theorem appears correct and useful,
but it is not a convincing headline theorem. Closest work already proves broad
schedulability-preserving task refinement. The exact vector-start-deadline
specialization was not located verbatim, but its proof is a short load-conservation
argument. Its value is as the formal bridge from agent lineage refinement to
certificate reuse.

## 2. The semantic boundary must be stated correctly

There are three distinct stages:

1. **Unprepared certificate tail.** A schedule certificate describes which future
   Prepare operations remain safe and in what order. Fork/Restore/Merge/Abort/
   Revoke may preserve, transform, or invalidate this tail.
2. **Atomic Prepare.** One step validates or transports the current head, advances
   the tail, installs the matching durable claim, and creates a unique durable
   ticket. This is the authority-accounting linearization point.
3. **Dispatch and settlement.** Dispatch consumes the prepared ticket. It does not
   revalidate the old schedule certificate or current plan version. Crash recovery
   reconciles the ticket/receipt using stable effect identity.

The safety statement should therefore be:

> Every protected Dispatch consumes a unique durable ticket minted by an atomic
> Prepare whose certificate head was valid at that Prepare.

It should **not** be:

> Every Dispatch rechecks that the plan certificate is current.

The latter collapses into commit-time authorization or ordinary OCC and is also
too strong for the intended semantics. A Revoke or topology change after Prepare
does not retroactively revoke a sealed ticket. If cancellation of prepared effects
is desired, it must be a separate explicit ticket transition with its own race and
provider semantics; it cannot be silently inherited from grant revocation.

This boundary also clarifies terminology. “Certificate invalidation before
Dispatch” is imprecise. An unconsumed certificate must be rejected before it can
authorize a later Prepare; after consumption, the relevant object is the ticket,
not the certificate.

## 3. Claim-by-claim closest-work matrix

Risk scale: **very high** means the abstract problem and mechanism are already
present; **high** means a straightforward specialization/composition is present;
**medium** means no literal theorem was found but the surrounding abstraction is
established; **lower** means the exact claim survived this search, not that novelty
is proved.

| Candidate claim | Closest primary work | Same problem? | Same mechanism? | Same claimed result? | Same-claim risk | Surviving delta, if any |
|---|---|---:|---:|---:|---:|---|
| Untrusted producer supplies a cheaply checked safety/authorization proof | Necula PCC; Appel--Felten PCA; PCFS | Yes | Yes | Yes | Very high | None; use as foundation. |
| Resource-aware AI plan carries a machine-checked proof of valid execution | Hill--Komendantskaya--Petrick, Proof-Carrying Plans | Yes | Yes | Broadly yes | Very high | PCP does not model changing branch authority, certificate tails, or Prepare-to-ticket conversion. |
| Workflow messages/actions carry recursively checkable evidence | Proof-Carrying Data; Cyberlogic evidential transactions | Yes | Yes | Broadly yes | High | No aggregate co-durability scheduler or lifecycle transport theorem. |
| Agent action has a portable action certificate/envelope | PCAA; certified-trace PCE architecture | Yes | Yes | Yes at architecture level | Very high | Avoid the names “proof-carrying agent action” and “no certificate, no execution” as novelty. |
| Fixed-batch safe order is exactly a vector start-deadline order | Classical deadline scheduling; Möhring--Skutella--Stork AND/OR scheduling | Yes | Substantially | The abstract feasibility result is subsumed | High | Authority-specific derivation of `p_b,h_b`, cleanup semantics, and Prepare refinement. |
| Greedy backward peeling returns an order or a canonical stuck core | Möhring--Skutella--Stork; Ardila--Maneva pruning/antimatroids | Yes | Yes | Yes abstractly | Very high | Coordinate arithmetic makes the obstruction compact and runtime-checkable, but is a specialization. |
| Positive certificate survives relaxation; negative core survives strengthening | Incremental SAT models/UNSAT proofs and assumptions | Yes | Yes | Yes abstractly | Very high | Need lineage/topology-specific semantic order and stable meaning of identifiers. |
| Maintain a schedule/cycle certificate incrementally as dependencies change | Incremental topological ordering; incremental schedulability analysis | Yes | Yes | Broadly yes | High | Aggregate authority semantics, not incremental maintenance itself. |
| Bind a certificate to dependencies and check current conditions before admitting an effect | PCFS procaps; cooperative authorization recycling; Zanzibar zookies | Yes | Yes | Yes | Very high | A local credential/object check cannot see changed co-durable future topology. |
| Use versions/epochs to revoke capabilities | FAST 2003 group counters; capability revocation systems such as Capstone | Yes | Yes | Yes | Very high | Global/per-object epochs are either unsafe for topology-only changes or overconservative for unrelated changes. |
| Validate optimistic work before a state-changing boundary | Kung--Robinson OCC; TL2 | Yes | Yes | Yes | Very high | Prepare validates an authority theorem over future topology, not transaction read/write serializability. |
| Durable effect is allowed only while its authority witness remains fresh, bound, causally prior, and eligible | Commit-Time Authorization | Yes | Yes | Yes for commit-boundary freshness | Very high | Intended semantics differs after atomic Prepare: the fresh witness is converted to a durable ticket, so later Dispatch need not retain plan/branch eligibility. |
| Convert a successful admission into a durable resource promise completed later | O'Neil escrow; MobiSnap reservations; reservation-based extended transactions; two-phase commit Prepare | Yes | Yes | Yes | Very high | Derivation of that promise from conditional, branching, cleanup-sensitive authority; consumable schedule tail. |
| Split/refine an abstract job into a resource-bounded group while preserving schedulability | HTL task refinement; Event-B event splitting; compositional real-time interfaces | Yes | Yes at abstraction | Broad preservation theorem exists | High | Exact owner-fiber/vector-deadline lemma tied to lineage identity and authority certificates. |
| Runtime refinement/patching reuses prior schedulability analysis | HTL incremental runtime patching; incremental hierarchical schedulability | Yes | Yes | Yes | Very high | Exact Fork/Restore/Merge authority projection and certificate-tail transport. |
| Dynamic events add/remove causality | Dynamic-causality event structures | Yes | Yes | Yes | Very high | Quantitative conditional authority and effect-ticket refinement. |
| Derive atomic groups/chops from conflicts or use compensation | Transaction chopping; sagas | Yes | Broadly | Broadly | High | Authority-specific serial-or-seal criterion and one-shot ticket semantics, if exact. |
| An exact operation table says which agent lifecycle mutations preserve certificates | No literal source found | Partly | Partly | Not found | Medium | Must be derived from semantic simulation/refinement, not trusted operation labels. |
| No checker observing only grant/object versions can be both sound and maximally reusable across topology mutations | No literal source found | No | No | Not found | Lower/medium | A promising necessity/lower-bound theorem, especially with indistinguishable Merge versus unrelated mutation histories. |

## 4. Primary-source findings

### 4.1 Proof-carrying authorization, plans, and workflows

[Proof-Carrying Code](https://doi.org/10.1145/263699.263712) establishes the
producer-supplied proof/consumer-side checker architecture. [Proof-Carrying
Authentication](https://collaborate.princeton.edu/en/publications/proof-carrying-authentication/)
applies the pattern to authorization: a request carries an easily checked proof
rather than requiring the reference monitor to rediscover a derivation.

[A Proof-Carrying File System](https://www.cs.cmu.edu/~fp/papers/oakland10.pdf)
is the most important classical collision. PCFS verifies an expensive authorization
proof offline and emits a signed conditional capability (“procap”). The procap
contains the authorization conclusion, interpreted state predicates, time
constraints, and a signature. At file access, the backend checks the signature and
the predicates/constraints in the current state. Its correctness theorem proves
that offline proof verification plus access-time condition checking has the same
formal guarantee as checking the full proof at access. PCFS also explicitly
discusses revocation of already generated procaps: include the unique IDs of
certificates on which the proof depends and compare them with a revocation list, or
issue short-lived procaps. Thus “extract dependencies into a certificate and check
them later” is already an exact, proved design.

[Constraining Credential Usage in Logic-Based Access
Control](https://www.andrew.cmu.edu/user/liminjia/research/papers/csf2010-constraints.pdf)
goes further: proofs can serve as capabilities and credentials can attach general
well-behaved constraints on authorization proofs, including revocation and usage
restrictions. Generic side conditions on proof use are therefore not a novelty.

[Proof-Carrying Plans](https://pure.hw.ac.uk/ws/portalfiles/portal/41749339/main.pdf)
defines a resource logic for AI plans, proves it sound relative to standard possible-
world planning semantics, and mechanizes the logic and proof in Agda. Plans are
state-transforming functions and pre/postconditions are types. This blocks any broad
claim that resource-aware, proof-carrying plans for AI are new. It does not address
authority evidence changing between planning and execution, conditional claims over
alternative histories, or conversion of an unprepared proof into a one-shot ticket.

[Proof-Carrying Data](https://projects.csail.mit.edu/pcd/) attaches proofs to
messages so a verifier can check that the recursively represented computation
history preserves a property. [Evidential Transactions with
Cyberlogic](https://arxiv.org/abs/2304.00060) constructs checkable evidence for
distributed transactions, including authorization, delegation, revocation, time,
and freshness. These sources own generic history-aware certificate workflows.

Two contemporary agent papers make naming and framing especially important.
[Proof-Carrying Agent Actions](https://arxiv.org/abs/2606.04104) uses a portable
action certificate and five governance checkpoints; it has no Fork/Restore/Merge
schedule, dead-core, or lifecycle-preservation theorem. [No Certificate, No
Execution](https://arxiv.org/abs/2605.24462) proposes a proposal--certification--
execution architecture for certified agent traces. The present work must cite and
separate from both; “agent certificates” alone is already occupied.

### 4.2 Static scheduling, peeling, and negative cores

[Scheduling with AND/OR Precedence
Constraints](https://epubs.siam.org/doi/10.1137/S009753970037727X) is the closest
abstract result. Its waiting condition says a job may wait until at least one member
of a predecessor set completes. A greedy linear-realization algorithm succeeds iff
the instance is feasible. When it stops, the remaining jobs form a generalized
cycle: every remaining job has an unsatisfied waiting set contained in the
remainder. This is the same positive-order/negative-residual certificate shape as
backward peeling.

[Pruning Processes and a New Characterization of Convex
Geometries](https://arxiv.org/abs/0706.3750) proves that when removability is
monotone (“once removable, remains removable”), valid pruning sequences form an
antimatroid. This explains choice-independent peeling and the unique terminal
residual. Calling that residual an authority dead core is useful domain language,
not new combinatorics.

The current fixed-batch specialization remains valuable:

\[
  \mathsf{Supp}_b(F_S)
  \iff
  \sum_{a\in S\setminus\{b\}} p_a \le h_b,
  \qquad h_b=G-d-r_b.
\]

A positive certificate gives an order and prefix inequalities. A negative
certificate gives a nonempty residual `R` and, for each `b in R`, a coordinate
`k_b` witnessing

\[
  \sum_{a\in R\setminus\{b\}}p_{a,k_b}>h_{b,k_b}.
\]

These are short, independently checkable artifacts, but their abstract existence
and greedy construction should be credited to the scheduling/pruning literature.
The paper's contribution can be the derivation from conditional authority and the
refinement into real Prepare transitions.

### 4.3 Incremental certificates and dynamic scheduling

[Certifying Incremental SAT
Solving](https://kfazekas.github.io/papers/FazekasPollittFleuryBiere-LPAR24.pdf)
is a direct abstract analogy. For each incremental query, a satisfying assignment is
a positive certificate and an UNSAT proof/core is a negative certificate. The work
defines formats and checkers for sequences of queries under assumptions. In the
elementary monotone cases, deleting constraints preserves a positive model while
adding constraints preserves an UNSAT core, provided the referenced vocabulary and
clauses retain their meaning. This is exactly the proposed positive/negative
polarity at a generic constraint-system level.

[A New Approach to Incremental Topological
Ordering](https://people.csail.mit.edu/jfineman/topsort.pdf) and [A Dynamic
Algorithm for Topologically Sorting Directed Acyclic
Graphs](https://www.doc.ic.ac.uk/~phjk/Publications/DynTopoSortWEA2004.pdf)
maintain order/cycle information as edges change. [Incremental Schedulability
Analysis of Hierarchical Real-Time
Components](https://www.cs.york.ac.uk/rts/docs/CODES-EMSOFT-CASES-2006/emsoft/p272.pdf)
uses compositional resource interfaces so dynamically changing components do not
force whole-system reanalysis. Therefore “incrementally update a schedule
certificate” is not a novelty by itself.

The surviving requirement is stronger: define the semantic relation under which a
certificate statement remains the same authority statement even though the owner
set, topology, and history representation change. IDs, projection fibers, grant
epochs, effect bindings, cleanup behavior, and already consumed certificate prefix
must be part of that relation.

### 4.4 Dynamic causality and event refinement

[Dynamic Causality in Event
Structures](https://arxiv.org/abs/1801.02857) models events whose occurrence adds
or removes causal dependencies and gives trace/configuration semantics and
expressiveness comparisons. [Representing Dependencies in Event
Structures](https://arxiv.org/abs/1910.02521) similarly studies contextual
modifiers of causality. Thus “Fork/Restore/Merge changes the dependency graph” is
not new.

[The Behavioural Semantics of Event-B
Refinement](https://doi.org/10.1007/s00165-012-0265-0) covers one-to-many event
splitting, introduction of events, and proof obligations that relate concrete
traces to abstract behavior. [Shared Event Composition/Decomposition in
Event-B](https://eprints.soton.ac.uk/272178/) proves preservation of refinement
proofs under shared-event composition/decomposition. These are broad precedents
for proof transport across workflow/event refinement.

The authority-specific target must consequently quantify not only over causal
traces but over which alternative futures may be jointly durable and how their
conditional resource promises become durable external effects.

### 4.5 OCC and commit-time authorization

[On Optimistic Methods for Concurrency
Control](https://www.eecs.harvard.edu/~htk/publication/1981-tods-kung-robinson.pdf)
separates a private read phase, a validation phase, and a write phase. Work is
installed only if validation shows serial equivalence. This already owns “compute
optimistically, then validate atomically before the state-changing point.” A global
version comparison plus retry is ordinary OCC.

[Temporary Authority, Permanent Effects: Commit-Time Authorization for LLM
Agents](https://arxiv.org/abs/2607.10487) is a direct contemporary collision. It
requires freshness, causal priority, effect binding, and path eligibility at the
durability boundary, including branch cancellation, version changes, and approval
loss. It introduces a fail-closed boundary monitor and empirically shows that
endpoint success can hide unauthorized commits.

The intended certificate protocol should separate itself as follows:

- Commit-Time Authorization carries temporary authority through derived state and
  asks whether it is still live at the durable effect.
- The proposed protocol atomically **converts** temporary conditional authority
  into a durable claim/ticket at Prepare. Dispatch later exercises that already
  sealed right.
- Therefore a post-Prepare branch cancellation or grant revocation does not make
  Dispatch unauthorized in the proposed semantics. The relevant safety question is
  whether the ticket was minted exactly once under a valid certificate head and is
  consumed/reconciled exactly once.

This is a real semantic distinction, but it creates a proof obligation: show that
Prepare, rather than provider-side Dispatch, is a legitimate authority
linearization point. The runtime must durably reserve the full accounted resource
and bind a specific effect before acknowledging Prepare. Otherwise the design is an
unsafe early authorization, not a sealed right.

### 4.6 Escrow, reservations, and prepared promises

[The Escrow Transactional
Method](https://ics.uci.edu/~cs223/papers/p405-o_neil.pdf) is the strongest
mechanism-level precedent. An escrow journal represents a system guarantee that a
requested update may commit or abort later. It supports long-lived transactions and
partitionable aggregate quantities without blocking unrelated work. It also tracks
the remaining unused quantity as requests consume an escrow allocation.

[Reservations for Conflict Avoidance in a Mobile Database
System](https://www.usenix.org/legacy/publications/library/proceedings/mobisys03/tech/full_papers/preguica/preguica_html/index.html)
grants value, slot, and escrow reservations that promise later transaction behavior;
mobile execution can partially consume an escrow reservation; externally visible
notifications are deferred until definitive server execution. [A Reservation-Based
Extended Transaction Protocol](https://doi.org/10.1109/TPDS.2007.70727) splits each
task into a reservation subtask and a later confirmation/cancellation subtask, with
timed or untimed exclusive holds and durable logging for recovery.

Classical two-phase commit similarly makes a prepared participant durably promise
that it can later commit or roll back, surviving failures. Therefore these pieces
are not new:

- a durable Prepare record;
- capacity/resource reservation before a later action;
- later confirmation/dispatch without rerunning the original planning analysis;
- consuming an allocated quantity;
- crash recovery from a prepared record.

The possible novelty is the **source of the reservation right**: a consumable
certificate derived from aggregate conditional authority over branching histories,
with a proved transport calculus across lineage changes and a dead-core/seal choice
when serial reservation is impossible.

### 4.7 Authorization caches, version tokens, and revocation

[A Proof-Carrying File System](https://www.cs.cmu.edu/~fp/papers/oakland10.pdf)
already checks proof dependencies and state predicates at use. [Cooperative
Secondary Authorization
Recycling](https://people.ece.ubc.ca/qiangw/publications/hpdc07-paper.pdf)
includes evidence with cached authorization answers and handles policy changes by
global flush, TTL, or selective invalidation of decisions affected by a change. It
even notes that some additions need not invalidate cached decisions.

[Zanzibar](https://www.usenix.org/system/files/atc19-pang.pdf) uses a zookie as a
content-version consistency token so an authorization check is evaluated at a
snapshot at least as fresh as the causally related content mutation, avoiding the
“new enemy” anomaly. [Block-Level Security for Network-Attached
Disks](https://www.usenix.org/legacy/publications/library/proceedings/fast03/tech/full_papers/aguilera/aguilera_html/node5.html)
surveys object-version revocation and uses group IDs with counters; a capability is
valid only when the stored counter matches.

Consequences:

- “bind certificate to a version” is not new;
- “selectively invalidate only affected authorization artifacts” is not new;
- “topology epoch plus grant epoch” is a sensible engineering design, not a
  theorem;
- invalidating every certificate on any epoch change is safe but ordinary and
  overconservative.

The paper needs an exact semantic footprint or transport proof that accepts safe
nonidentical states. The key separating case is a topology mutation that changes
co-durability while leaving each individual credential, grant object, effect target,
and object version unchanged.

### 4.8 Capability revocation and lineage

[Capstone](https://www.usenix.org/system/files/usenixsecurity23-yu-jason.pdf)
uses linear capabilities, hierarchical revocation authority, and restricted
split/merge rules. Revocation can reclaim a region and invalidate overlapping
descendants; unrestricted merging is deliberately problematic. This is a useful
analogy for lineage fibers and the asymmetry between refinement/splitting and
coarsening/merge.

It is not the same problem: Capstone protects spatial memory authority, whereas the
proposed calculus protects aggregate conditional resource authority over alternative
future histories. Still, “linear capabilities plus split/merge/revoke” is occupied
conceptual space. The paper should prove its own projection/fiber rules rather than
relying on agent terminology to imply novelty.

### 4.9 Transaction chopping and atomic groups

[Transaction Chopping](https://doi.org/10.1145/211414.211427) derives safe pieces
from sibling/conflict structure and uses an SC-cycle criterion for serializability.
[Sagas](https://www.cs.cornell.edu/courses/cs530/2005sp/papers/sagas.pdf) handles
long-running work as committed subtransactions plus compensation. Atomic grouping,
chopping, and compensation are therefore established.

“Serial or seal” can survive only as an authority-specific decision:

- serialize the certificate tail when peeling succeeds;
- report a coordinate-certified residual when it fails;
- atomically reserve/seal an explicit subset when the runtime requires progress;
- refine either choice into durable claims and tickets.

Any minimum-seal complexity claim needs its own proof and a separate closest-work
search. It should not be inferred from transaction chopping.

## 5. Owner/job refinement audit

### 5.1 Candidate theorem

Let a source safe order be

\[
  \sigma=(b_1,\ldots,b_n),
  \qquad
  \sum_{a\prec_\sigma b}p_a \le G-d-r_b.
\]

Let each source owner `b` be replaced by a nonempty fiber `F_b`. For every target
job `x in F_b`, let `p'_x <= r'_x` componentwise. Assume

\[
  \sum_{x\in F_b}r'_x\le r_b,
  \qquad
  \sum_{x\in F_b}p'_x\le p_b,
\]

with the same or relaxed residual capacity (`G'-d' >= G-d`). Expand each `b` in
`sigma` into one contiguous block containing all jobs in `F_b`, in any internal
order. Then the expanded order is safe.

### 5.2 Short proof

Consider child `x` of source owner `b`. Its target predecessors consist of complete
fibers of source predecessors plus some earlier siblings `E_x` in `F_b`. Hence

\[
\begin{aligned}
  \sum_{y\prec x}p'_y
  &\le \sum_{a\prec_\sigma b}p_a + \sum_{y\in E_x}p'_y \\
  &\le G-d-r_b + \sum_{y\in E_x}p'_y.
\end{aligned}
\]

Because `p'_y <= r'_y` and the full fiber load is bounded,

\[
  \sum_{y\in E_x}p'_y+r'_x
  \le \sum_{y\in F_b}r'_y
  \le r_b.
\]

Therefore

\[
  \sum_{y\prec x}p'_y
  \le G-d-r'_x
  \le G'-d'-r'_x.
\]

This proves safety. Deleting/restricting source owners is the degenerate case with
empty fibers or fewer predecessor blocks, so it also preserves a positive order.

### 5.3 Closest work and novelty assessment

[Hierarchical Timing Language](https://www2.eecs.berkeley.edu/Pubs/TechRpts/2006/EECS-2006-79.html)
already makes an abstract task a conservative schedulability placeholder and lets
concrete tasks refine it under weaker timing/resource requirements. Ghosal's
[dissertation](https://www2.eecs.berkeley.edu/Pubs/TechRpts/2008/EECS-2008-10.html)
proves that a schedulable abstract implementation yields a schedulable valid
refinement and constructs the concrete scheduler from the abstract scheduler.
HTL supports sequential, conditional, and parallel task composition and task groups
with precedence. [Semantics-Preserving and Incremental Runtime Patching of Real-Time
Programs](https://www.cs.uni-salzburg.at/~ck/content/publications/conferences/APRES08-RuntimePatching.pdf)
then uses these ideas to update real-time programs while reusing system-wide
schedulability analysis.

This is a strong abstract collision. The exact fiber-sum/vector-deadline statement
was not found verbatim in the searched scheduling literature, and HTL's proof
obligations are not identical. Nevertheless, the proposed theorem is a short,
natural specialization of schedulability-preserving refinement. Same-claim risk is
**high if presented broadly**, and **medium if presented precisely as an
authority-lineage certificate-transport lemma**.

The genuinely agent-authority-specific content would be:

- `F_b` is a lineage/projection fiber created by Fork/Restore/Merge, not merely a
  scheduler implementation detail;
- `r_b` is the full conditional claim of an owner and `p_b` is the portion promoted
  by the certified batch;
- the topology simulation proves that the target children do not create additional
  jointly durable futures outside the source owner;
- grant/effect bindings and cleanup behavior are transported with the fiber;
- the schedule certificate tail is rewritten to the contiguous expansion and then
  consumed through atomic Prepare transitions;
- coarsening/merge does not receive a symmetric rule.

### 5.4 Why coarsening is not symmetric

Arbitrary owner merge can destroy order feasibility even when the source has a safe
order and each target singleton fits. In one coordinate let `G=10`, `d=0` and use:

| owner | `r` | `p` | `h=10-r` |
|---|---:|---:|---:|
| `a` | 2 | 1 | 8 |
| `c` | 8 | 3 | 2 |
| `b` | 6 | 3 | 4 |

The source order `(a,c,b)` is safe: prefix loads are `0 <= 8`, `1 <= 2`, and
`1+3 <= 4`. Coarsen the noncontiguous owners `a,b` into `x` with
`r_x=8,p_x=4,h_x=2`, leaving `c` unchanged. In target order `(x,c)`, `c` misses
its deadline because `4>2`; in `(c,x)`, `x` misses because `3>2`. Both target
singletons fit, but no target order exists.

This is a useful Merge counterexample: splitting/restriction can transport a
certificate under fiber conservation, but arbitrary coarsening cannot. It does not
show all merges are unsafe; it shows a Merge needs a fresh admission proof or a
stronger simulation theorem.

### 5.5 Persistent lineage phases: stronger than one split, but not novel by themselves

The strengthened candidate assigns each source owner in the original safe order an
immutable ordinal **lineage phase**. Every live descendant created by arbitrarily
deep Fork/Restore refinement inherits that phase; descendants within one phase may
be prepared in any order as long as their aggregate full and promoted claims stay
within the source owner's budgets. A same-phase Merge may preserve the certificate
when it is a conserving algebraic join. A cross-phase Merge, claim rebinding, or
other change of abstract owner meaning has no generic transport rule and requires a
fresh proof/seal. Prepare consumes nonempty phases in source order and mints the
durable ticket described in Section 2.

This is materially stronger than a one-step job-splitting lemma because its desired
statement is a trace invariant over an unbounded generated lifecycle, including
partial consumption and same-phase coarsening. However, its individual ingredients
have strong prior analogues:

- HTL refinement preserves an abstract task as a stable scheduling placeholder
  through nested refinements. Ghosal's dissertation explicitly gives a transitive
  refinement relation and schedules concrete tasks in the time slots of their
  respective parent tasks. Thus stable parent identity, arbitrary-depth refinement,
  budget conservation, and reuse of an abstract schedule are not new in the
  abstract.
- Iris's [authoritative resource
  algebra](https://plv.mpi-sws.org/coqdoc/iris/iris.algebra.auth.html), situated in
  the broader [Iris framework](https://iris-project.org/), has one authoritative
  resource and composable fragments. Fragments can be split and joined subject to
  validity against the authoritative element, and updates must be frame preserving.
  Consequently, “a tagged slot owns conserved fragments that may split/merge” is
  established algebraic machinery, not a contribution. A product or tagged
  authoritative algebra can encode independent phase budgets.
- [Linearly Refined Session Types](https://arxiv.org/abs/1211.4099) combine
  protocol order with refinements treated as linear resources.
  [Resource-Aware Session Types](https://arxiv.org/abs/1712.08310) carry potential
  through messages and processes while proving resource bounds. The CSF 2021
  [Nomos system](https://www.cs.cmu.edu/~fp/papers/csf21.pdf) combines protocol
  phases, linear assets, resource bounds, and transactional digital contracts.
  These works make “ordered phases plus exactly conserved/consumed resources” a
  high-risk generic claim.
- Multiparty-session projection uses partial merge operators: branch behaviors can
  be merged only when their local continuations are compatible. This is a close PL
  analogue of allowing a compatibility-checked same-phase Merge while rejecting a
  blind cross-phase rebind. It does not supply the proposed quantitative
  co-durability theorem, but it blocks novelty claims about partial merge alone.

The defensible new object is therefore not a “persistent slot.” It is a
**proof-relevant authority phase attached to a history lineage**, with two
authority-specific budgets (`r` and `p`), cleanup semantics, immutable grant/effect
bindings, and a transition from speculative phase fragments to a nonrollbackable
effect ticket. “Lineage phase” or “authority phase” is preferable to “slot,” which
reviewers are likely to read as an HTL or hierarchical real-time scheduling slot.

A useful formalization maintains, for every original owner `b` and every trace
prefix, a projection from each live descendant claim `x` to `b`, an immutable phase
`lambda(x)=pos_sigma(b)`, and conservation conditions

\[
 \sum_{x\in Live(b)}r_x + R^{prepared}_b \le r_b, \qquad
 \sum_{x\in Live(b)}p_x + P^{prepared}_b \le p_b.
\]

The exact ledger terms depend on whether Prepare moves conditional authority into a
separate durable-load domain; they must prevent a Restore or retry from recreating
already consumed budget. Same-phase Merge also needs preservation of bindings,
cleanup behavior, `p_x<=r_x`, and the ledger sums. Equality of phase labels alone is
not sufficient.

The strongest plausible theorem package is:

1. compile a safe source order into lineage phases;
2. prove the conservation/projection invariant inductive for every allowed
   lifecycle transition, at arbitrary refinement depth;
3. flatten all live descendants of each phase into a contiguous fiber and prove
   within-phase order independence from the aggregate bounds;
4. prove closure under binding-preserving, conserving same-phase Merge;
5. prove by counterexample that cross-phase coarsening is not generically closed,
   while carefully avoiding the false claim that every cross-phase Merge is unsafe;
6. prove that atomic Prepare consumes the least live phase fragment and transfers
   its authority to a unique ticket, including recovery and retry transitions.

If proved only by repeatedly invoking the one-step split lemma, this is useful but
incremental. If instead the paper presents a syntax-directed lifecycle calculus and
an arbitrary-trace preservation theorem with partial consumption, Merge boundaries,
and crash refinement, it is a substantially stronger compositional result. It is
still not sufficient as a headline in isolation because HTL, resource algebras, and
resource-aware session types collectively anticipate its generic structure. The
agent-specific novelty must come from conditional co-durable futures, history
topology, and the Prepare-to-ticket boundary.

## 6. Recommended formal object

A certificate should not be only `(version, order)`. A plausible object is

\[
\chi =
  (\mathit{batchId},\mathit{contractHash},\mathit{topologyRoot},
   \mathit{ownerEpochs},\mathit{grantEpochs},\mathit{effectBindings},
   P,p,r,h,\mathit{kind},\mathit{witness},\mathit{tail},\mathit{nonce}).
\]

The fields have distinct proof roles:

- `contractHash` fixes the semantics of capacity, cleanup, Prepare, and ticket
  settlement; otherwise an unchanged numeric version can change meaning.
- `topologyRoot` or a checked projection fixes the family of co-durable futures.
- owner/grant epochs prevent a surviving identifier from silently changing
  principal or authority.
- effect bindings prevent a valid resource claim from being redirected to another
  external action.
- `p,r,h` are the arithmetic statement checked by the static certificate.
- `kind` is positive order, negative core, or explicit seal.
- `witness` contains prefix inequalities, core coordinates, or seal obligations.
- `tail` makes the positive certificate a consumable linear resource, not a reusable
  cache entry.
- `nonce`/batch identity prevents replay across batches.

The checker must reconstruct these bindings from runtime state or verify a trusted
simulation descriptor. It must not accept a caller-supplied Boolean such as
“mutation is relaxing.”

## 7. Semantic preservation relations

Operation names are not sufficient classes. A choice Fork and a parallel Fork have
opposite effects on co-durability; replace Restore and live Restore differ; Abort can
remove support named by another owner's certificate; Merge can be a proved
projection or direct coarsening. Define semantic relations first and prove each
operation implements one.

### 7.1 Positive-tail relation

An old positive tail can be transported if a checked relation provides:

- stable contract, grant authority, effect identity, and already prepared prefix;
- a restriction/refinement mapping from target unprepared owners to old tail owners;
- for every source owner, a contiguous target fiber satisfying the full/promoted
  sum bounds above;
- no decrease in residual capacity;
- no new co-durable target configuration that escapes the source projection;
- cleanup simulation: target cleanup cannot terminalize a child before the
  expanded certificate schedules it.

The transported order is obtained by deleting missing source blocks and expanding
each surviving block into its fiber. This accepts many safe nonidentical states and
is strictly more informative than equality of a global epoch.

### 7.2 Negative-core relation

A negative certificate can be transported under a strengthening relation only if:

- every core owner and overloaded coordinate retains stable meaning;
- its promoted predecessor contribution does not decrease;
- its available headroom does not increase;
- topology/cleanup changes do not delete or reinterpret the core.

The checker can then replay each strict inequality. A negative core generally does
not survive owner deletion, capacity increase, or demand decrease. Splitting a core
owner can also destroy the obstruction, so a negative refinement theorem requires a
separate mapped-core proof; it is not the dual of the positive fiber theorem for
free.

### 7.3 Phase-sensitive lifecycle table

| Mutation | Before Prepare: positive tail | Before Prepare: negative core | After the relevant Prepare |
|---|---|---|---|
| Pure Checkpoint/snapshot | Preserve if security semantics and IDs are unchanged | Preserve | No effect on sealed ticket |
| Restrict/delete unprepared owner; replace Restore that prunes futures | Preserve by order restriction if named support/cleanup simulation holds | Usually invalidate | No effect on existing ticket |
| Fiber refinement/splitting under sum bounds and topology simulation | Preserve by contiguous expansion | Not automatic | No effect on existing ticket |
| Choice Fork that only refines exclusive alternatives | Preserve only after checked projection/fiber proof | Usually invalidate or reprove | No effect on existing ticket |
| Parallel Fork or live Restore adding jointly durable futures | Generally invalidate | May preserve if the same core inequalities remain | No effect on existing ticket |
| Simulation-certified Merge | Transform only under the proved mapping | Transform only with mapped core | No effect on existing ticket |
| Direct Merge/coarsening/lineage identification | Invalidate; the counterexample above rules out a generic rule | Reprove | No effect on existing ticket |
| Abort of unprepared losing branch | Restriction may preserve, but owner cleanup/support must be simulated | Usually invalidate | Does not retract sibling sealed ticket |
| Revoke/close grant for unprepared effect | Invalidate any positive head needing that grant | Strengthening may preserve | Does not retract already minted ticket under the intended semantics |
| Capacity increase / durable-load decrease / demand decrease | Preserve under stable meanings | Generally invalidate | No effect on existing ticket |
| Capacity decrease / durable-load increase / demand increase | Invalidate | May preserve | No effect on existing ticket |
| Owner, grant, target, cleanup-policy, or effect-binding change | Invalidate | Invalidate unless an explicit renaming equivalence is proved | Existing ticket remains bound to its original effect; it cannot be retargeted |

The final column is central. Once Prepare has atomically consumed the certificate
head and minted a ticket, later lifecycle mutations do not “preserve the
certificate”; that head no longer exists. They interact only with the ticket
lifecycle.

## 8. Recommended theorem suite

### Theorem A: authority-to-scheduling reduction

Under fixed batch/topology, downward closure, nonnegative demands, exact cleanup,
and source validity, prove the singleton-support equation and reduce Prepare-order
existence to vector start deadlines. This connects the authority semantics to known
scheduling theory.

### Theorem B: certified serial-or-core decision

Prove that the checker accepts exactly either:

- a safe order with all prefix inequalities, or
- a nonempty residual with one overloaded coordinate per owner showing no order
  exists.

Credit AND/OR scheduling and antimatroid pruning. The contribution is the
authority-specific reduction and executable certificate format.

### Theorem C: contiguous owner-refinement preservation

Formalize the fiber theorem in Section 5, including capacity relaxation, stable
bindings, topology simulation, and cleanup simulation. Prove restriction/deletion
as a corollary and give the noncontiguous coarsening counterexample.

This theorem should be a supporting bridge, not the paper title.

### Theorem D: exact lifecycle transport for unconsumed certificates

Define a semantic simulation/preorder on authority states. Prove:

1. soundness: transporting a positive tail along the relation yields a safe target
   tail; transporting a negative core along the strengthening relation yields a
   valid target obstruction;
2. operation adequacy: each concrete Fork/Restore/Merge/Abort/Revoke rule either
   constructs the required simulation or is rejected;
3. completeness/maximal reuse relative to the certificate observation: if the
   checker rejects two states with the same observed footprint, construct a target
   continuation that would make reuse unsafe, or explicitly state the conservative
   gap.

Part 3 is the ingredient most likely to lift the work above ordinary selective
invalidation. A merely sufficient table is much easier for a reviewer to dismiss.

### Theorem E: atomic Prepare consumes authority

Give an atomic rule schematically of the form

\[
(S,\chi[b::\tau])
\longrightarrow
(S',\chi[\tau],\mathsf{PreparedTicket}(e,b,\nu)),
\]

where one transition:

- validates or transports the head `b` against `S`;
- advances the tail so it cannot be replayed;
- promotes/installs the exact durable claim;
- performs specified cleanup;
- writes a unique ticket bound to effect `e` and nonce `nu`.

Prove crash atomicity: recovery observes either none of these changes or all of
them.

### Theorem F: post-Prepare ticket stability and Dispatch refinement

Prove that later Fork/Restore/Merge/Abort/Revoke transitions cannot remove the
durable accounting behind an existing ticket or change its effect binding. Dispatch
needs only a valid unspent ticket and atomically moves it through prepared/inflight/
settled-or-uncertain states. The theorem should give at-most-once accounting and,
under provider idempotence/reconciliation assumptions, exactly-once external
effect settlement.

This is not “fresh plan at Dispatch.” It is “fresh authority converted to a durable
one-shot right at Prepare.”

### Theorem G: observation lower bound

Prove that no checker observing only per-grant/object epochs, but not co-durability
topology and owner-cleanup identity, can be both sound and reuse-complete. Construct
two histories with identical observed versions:

- an unrelated mutation under which the old tail is safe; and
- a live Restore/Merge that makes formerly exclusive claims jointly durable and
  makes the same tail unsafe.

A checker must accept both or reject both. Accepting is unsound; rejecting is not
reuse-complete. This theorem directly answers the “ordinary cache invalidation +
OCC” objection.

## 9. Required separating histories and counterexamples

### 9.1 Per-action authorization is insufficient

Start with a choice fork: branch `x` and branch `y` are mutually exclusive. Each
holds an individually valid proof/capability to consume one unit from the same
bounded grant. A live Restore or Merge makes both branches co-durable without
changing either credential, target object, grant epoch, or per-action state
predicate. PCFS-style checking of each procap can still accept both actions, while
their aggregate durable consumption exceeds the grant. The authority schedule
certificate must depend on the co-durability topology and become nontransportable.

### 9.2 Global-version OCC is unnecessarily restrictive

Generate a safe order, then take a pure Checkpoint or abort an unrelated losing
branch outside the certificate footprint. A global epoch changes, so an equality-
based OCC check rejects and recomputes. The semantic transport checker reuses the
same tail. This shows a benefit, not merely safety.

### 9.3 Object-only selective invalidation is unsafe

Keep every grant/effect object unchanged but perform a topology-only live Restore
that enlarges the set of jointly durable futures. A dependency list containing only
credentials and resources sees no change and reuses the certificate unsafely. This
separates the design from ordinary authorization cache invalidation.

### 9.4 Operation labels do not determine polarity

- choice Fork may refine exclusive alternatives;
- parallel Fork strengthens co-durability;
- replace Restore prunes futures;
- live Restore adds a concurrent future;
- simulation Merge may be safe refinement;
- direct Merge may coarsen owners and destroy feasibility.

Therefore accepting a caller-supplied “relaxing mutation” bit is unsound. Each
operation must construct a proof of the semantic relation.

### 9.5 Check-then-Prepare race

Validate a certificate in state `S`, then perform a topology-strengthening mutation,
then mint the durable claim/ticket without rechecking or CAS. The certificate was
valid at check time but not at authority consumption. This is the actual OCC-like
race. The remedy is one atomic Prepare transition, not revalidation at a later
Dispatch.

### 9.6 Why Dispatch must not revalidate the plan certificate

Prepare an effect correctly and durably reserve its capacity. Then Revoke the
original grant or abort the planning branch before a delayed provider call. Under
the intended semantics, the ticket remains authorized and must be settleable. A
rule requiring the old branch/grant to remain current at Dispatch incorrectly
rejects a sealed operation and can strand durable accounting. This separates the
protocol from Commit-Time Authorization, but the paper must make the policy choice
explicit.

### 9.7 Fiber conservation is load-bearing

Split a source owner into children whose full loads or promoted loads sum to more
than the parent. Even if every child fits individually, a contiguous expansion may
miss a later child's deadline or overconsume the original conditional promise. This
is why per-child dominance is insufficient; the proof needs fiber-sum conservation.

### 9.8 Coarsening is not the inverse of splitting

Use the `(a,c,b)` example in Section 5.4. It supplies a two-job target in which both
possible coarsened orders fail, despite the source order being safe. This should be
a regression test for arbitrary Merge certificate reuse.

## 10. How to avoid the “cache invalidation + OCC” reject

The paper should make four explicit non-equivalence claims and prove each with a
small trace.

### Against authorization caches

Cached authorization answers concern current policy/credential facts. The proposed
certificate concerns an aggregate theorem over a family of possible durable
futures. A topology mutation can invalidate that theorem without changing any
credential or protected object. Conversely, an unrelated mutation can change a
global version without changing the theorem.

### Against OCC

OCC validates transaction read/write dependencies to establish serializability at
write commit. Here the checker validates whether conditional authority can be
converted into durable claims under branching-history cleanup. The linearization
point is an authority Prepare that reserves future external effects; later Dispatch
is not rollbackable database state.

### Against proof-carrying plans

Proof-Carrying Plans proves a plan transforms a specified initial state into a valid
goal state. The candidate certificate is a linear, partially consumed proof object
whose statement changes under lineage refinement, whose negative form explains
that no Prepare order exists, and whose successful head is converted into a durable
effect ticket.

### Against commit-time authorization

Commit-Time Authorization requires temporary evidence to remain fresh and eligible
at the durable effect. Here temporary authority is consumed earlier into a durable
ticket. The new theorem must justify why that conversion is safe and why subsequent
revocation affects unprepared authority but not the sealed ticket.

Without all four separations, the combined system may still be useful engineering,
but the theory contribution will look incremental.

## 11. Smallest plausible new ingredient

The smallest defensible addition is not “another version field.” It is the pair:

1. a **semantic certificate-transport judgment** over co-durability topology,
   lineage fibers, conditional/full versus promoted load, owner cleanup, stable
   effect binding, and consumed prefix; and
2. a **consumption refinement** that turns exactly one transported certificate head
   into a durable claim plus one-shot ticket at atomic Prepare.

The strongest version adds a maximal-reuse/observation theorem showing that this
judgment is both more permissive than global version equality and safer than
per-object dependency lists.

The fiber theorem is a particularly clean positive transport rule:

- restriction/delete: preserve by subsequence;
- owner refinement: preserve by contiguous fiber expansion and two fiber-sum bounds;
- arbitrary coarsening/Merge: no general preservation rule.

This yields a principled asymmetry matching agent history operations. But without
the topology/authority bridge and Prepare consumption, it remains ordinary
schedulability-preserving refinement.

## 12. Recommended paper contribution wording

Avoid:

> We introduce versioned schedule certificates and invalidate stale ones before
> agent actions.

Prefer a target claim of the following form, after it is proved:

> We give a certificate calculus for converting conditional authority over
> branching agent histories into durable external-effect rights. The calculus
> computes a safe Prepare order or a checkable no-order core; transports an
> unconsumed certificate exactly through restriction and lineage refinement,
> including a conserved-fiber schedule theorem; rejects topology strengthening and
> coarsening not justified by simulation; and atomically consumes each certificate
> head into a crash-stable one-shot ticket. A lower bound shows that neither global
> epochs nor per-object authorization dependencies can be both sound and maximally
> reusable across these history transformations.

“Exactly” and “maximally” should be removed if the formal development proves only
sufficiency.

## 13. Evaluation and mechanization implications

The theory, not a large benchmark, should carry the paper. A small evaluation is
still necessary to show the premises are observable in real runtimes.

Minimum mechanized surface:

- static singleton-support reduction;
- order/core checker soundness and completeness;
- fiber expansion and restriction preservation;
- coarsening counterexample;
- generated Fork/Restore/Merge/Abort/Revoke rules and their transport/refusal
  proofs;
- atomic Prepare/tail/ticket invariant;
- ticket crash/retry safety;
- the observation lower-bound pair, if formalized.

Minimum trace fields for a Codex/Claude-like adapter:

- stable batch, owner, branch/lineage, grant, effect, attempt, and ticket IDs;
- topology mutation and projection/fiber evidence;
- conditional full load `r`, promoted load `p`, capacity, and durable load;
- certificate digest, kind, head/tail index, and transport decision;
- one atomic durable record containing tail advancement, claim, cleanup result,
  and ticket;
- dispatch attempt and provider idempotency key;
- settled/uncertain receipt and recovery action;
- explicit record that post-Prepare revoke/topology mutation did not mutate the
  ticket.

Useful experiments are small and claim-directed:

1. compare global-version invalidation, per-object dependency invalidation, and
   semantic transport on matched safe/unsafe mutations;
2. measure checker and fiber-transform latency versus recomputing peeling;
3. inject crashes before, during, and after atomic Prepare and Dispatch;
4. replay the per-action-valid/topology-invalidating history;
5. replay the coarsening counterexample and a positive fiber refinement;
6. demonstrate post-Prepare Revoke followed by safe ticket settlement.

No experiment can prove truthful resource weights, complete mediation of all effect
sinks, provider idempotence, or absence of hidden authority-relevant state. These
remain explicit assumptions or adapter obligations.

## 14. Search log and coverage

The audit searched and read primary or author-hosted versions from the following
families:

- proof-carrying code, authentication, file systems, plans, data, and workflows;
- stateful authorization and constrained/consumable credentials;
- agent action certificates, certified traces, and commit-time authorization;
- AND/OR scheduling, pruning antimatroids, deadline scheduling, and incremental
  order maintenance;
- task/job splitting, HTL schedulability-preserving refinement, Event-B event
  splitting, and runtime patching;
- authoritative resource algebras, linear/refined and resource-aware session
  types, transactional session-typed contracts, and protocol projection/merge;
- dynamic-causality event structures;
- OCC and transaction validation;
- escrow, reservations, prepared transactions, sagas, and transaction chopping;
- capability revocation, counters/epochs, and split/merge capability systems;
- incremental SAT certificates and UNSAT cores;
- Zanzibar and distributed authorization recycling/caching.

Representative exact web queries included:

```text
proof carrying authorization state predicates revocation capability
proof carrying plans resource logic AI planning
certificate carrying workflow proof transaction authorization
dynamic causality event structures add remove dependencies
incremental SAT proof unsat core assumptions certificate
distributed authorization cache selective invalidation policy change
capability revocation version counter epoch
optimistic concurrency validation before write phase
transaction chopping atomic groups conflict graph
escrow transaction authorization reservation rights
reservation ticket prepare dispatch revocation capability paper
scheduling AND OR precedence greedy feasibility generalized cycle
incremental topological ordering cycle detection primary paper
scheduling job aggregation disaggregation preservation feasible schedule due dates
job splitting preserve schedulability theorem
task refinement schedulability preservation
workflow refinement proof preservation event splitting
resource-aware event refinement preservation scheduling
Hierarchical Timing Language task refinement schedulability WCET parent
semantics-preserving incremental runtime patching HTL
Commit-Time Authorization 2607.10487
Proof-Carrying Agent Actions 2606.04104
```

Repository-side searches also inspected the current static reduction, dead-core
report, lifecycle rules, ticket model, paper claims, and existing related-work notes
so that the comparison uses the project's actual `PrepareOK`/ticket boundary rather
than a generic rollback model.

## 15. Residual uncertainty

- No source located in this search states the exact continuous-fiber vector-
  deadline theorem with both full-load and promoted-load conservation. Because the
  proof is short and broad schedulability-preserving refinement is established,
  absence of a literal match should not be treated as strong novelty evidence.
- Persistent lineage phases exceed a one-step split only when formulated as an
  arbitrary-trace invariant with partial consumption and Merge boundaries. Stable
  parent scheduling positions, conserved split/join fragments, and linear protocol
  phases are separately anticipated by HTL, Iris, and resource-aware session types.
- No source located states the exact bidirectional certificate-transport calculus
  across agent Fork/Restore/Merge/Abort/Revoke with conditional authority and
  cleanup. This is the main surviving opportunity.
- No source located proves the proposed observation lower bound contrasting global
  epochs, per-object dependency lists, and topology-aware semantic reuse. This is a
  promising theoretical discriminator.
- The 2026 agent papers are contemporaneous preprints, not peer-reviewed anchors,
  but CSF reviewers can still use them as closest-work objections; they must be
  cited and distinguished.
- A separate focused audit is still needed before claiming novelty or hardness for
  minimum seal selection.
- “Post-Prepare revocation does not cancel a ticket” is a policy semantics, not a
  universal security truth. The paper must define what users are promised, expose
  any explicit cancellation operation, and prove races at the chosen linearization
  point.

## 16. Final recommendation

Proceed only with the following hierarchy:

1. **Established substrate:** static peeling/order/core, proof-carrying artifacts,
   versions/dependencies, reservation/ticket mechanisms, and generic monotonicity.
2. **Supporting new bridge:** contiguous lineage-fiber expansion and restriction
   preserve a positive authority schedule; arbitrary coarsening does not.
3. **Main theorem:** exact or maximal-reuse lifecycle transport of the unconsumed
   certificate tail under generated semantic Fork/Restore/Merge/Abort/Revoke rules.
4. **Main runtime refinement:** atomic Prepare consumes the live certificate head
   into durable accounting plus a one-shot ticket; Dispatch settles that ticket
   without rechecking the obsolete plan certificate.
5. **Novelty defense:** an observation lower bound and paired traces show why global
   OCC versions are too coarse and ordinary authorization dependencies are too
   narrow.

If items 3--5 cannot be proved, keep versioned certificates as an engineering
mechanism and do not make them the CSF headline. If they can be proved over the
closed lifecycle LTS and reflected in one real dispatch-owning adapter, the package
is materially more than ordinary cache invalidation or OCC and is plausibly a
theory-led CSF contribution.
