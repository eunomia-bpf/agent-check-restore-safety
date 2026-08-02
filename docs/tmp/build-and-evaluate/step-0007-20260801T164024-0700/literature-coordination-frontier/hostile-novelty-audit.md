# Hostile novelty audit: agent history and redemption domains

Date: 2026-08-02 (America/Vancouver)

Scope: read-only novelty/framing research.  This note does not edit the paper
or implementation.  It evaluates whether the proposed coordination-domain
result can carry a CSF paper and records the strongest primary-source
collisions.

## Bottom line

The high-level correction is right:

> Representation aliases are harmless when they rendezvous at one durable
> atomic redeemer; independently advancing redemption state is the scarce
> object that must not be duplicated.

However, neither half of that sentence is novel by itself.  Online
ratification, durable duplicate suppression, fencing, escrow rights, and the
generic necessary-and-sufficient coordination boundary are established.  The
current Lean `RedemptionDomainFrontier` is a useful regression lemma, but it is
not yet a coordination theorem: its admission predicate assumes per-domain
single use, and its conclusion is the resulting cardinality of an image.

A potentially CSF-level result must begin one level higher.  It should give an
operational and mechanized account of how intentional agent Fork, Restore, and
Merge change the equivalence relation "these attempts consult the same durable
admission state," and prove the exact admission/fencing/escrow obligations of
those transitions.  The safe novelty is the history-to-domain refinement, not
the discovery of atomic redemption or escrow.

## 1. Garfinkel--Rosenblum, HotOS 2005: source audit

Primary source:
[When Virtual Is Harder than Real](https://www.usenix.org/legacy/event/hotos05/prelim_papers/garfinkel/garfinkel_html/index.html).

### What the paper actually establishes

The paper is a position/architecture paper.  It directly states that
encapsulated VM state is copyable like a file, that a machine lifecycle changes
from a line to a tree with simultaneously existing branches, and that rollback
conflicts with security mechanisms that assume monotone progress.  Concrete
examples include re-enabled accounts/passwords, retired keys, one-time
passwords, randomness, and nonces.  It also makes the asymmetric-observer
point: the VM can be rolled back while an attacker cannot forget prior output.

Its architectural prescription is equally direct.  The proposed ubiquitous
virtualization layer includes secure distributed storage, controls VM
replication and identity/history, and moves security-relevant state outside the
guest or into storage that operates independently of rollback.  The paper calls
this benefit "Lifecycle Independence."

The authors explicitly say that, in the absence of published organizational VM
studies, they relied on experience and anecdotes.  This is evidence of the
paper's intended status, not a criticism: it identified the systems problem and
design direction early.

### What it does not establish

It does not define authority aliases or one-use grants; distinguish aliases of
one atomic state from detached copies of that state; define Fork/Restore/Merge
contracts; formalize redemption events, availability, or rollback domains;
state a necessary-and-sufficient condition; prove a theorem; implement an
authority monitor; or evaluate an agent runtime.

Consequently, this work owns the premise "tree-shaped rollbackable execution
needs rollback-independent security state."  It does not own an operational
history-to-redemption-domain theorem.  The new paper must cite it in the first
page and start its novelty after that premise.

## 2. Closest primary work by claim

| Source | What it already owns | Consequence for this paper | Remaining delta |
|---|---|---|---|
| [Bowers et al., Consumable Credentials, NDSS 2007](https://www.ndss-symposium.org/ndss2007/consumable-credentials-linear-logic-based-access-control-systems/) | Easily copied credentials, a global bounded-use condition, online ratifiers that record use, proof/goal/nonce binding that prevents productive reuse, and atomic multi-ratifier consumption. | "Copies are safe behind one atomic redeemer" and atomic consumption are established, not contributions. | It does not model intentional execution-history operations or determine when C/R preserves one ratifier versus clones/detaches its state. |
| [Bailis et al., Coordination Avoidance, PVLDB 2014/2015](https://www.vldb.org/pvldb/vol8/p185-bailis.pdf) | I-confluence is a generic iff boundary for invariant-preserving, available, convergent coordination-free execution.  Arbitrary uniqueness is not I-confluent; partitioned namespaces and commit-time allocation confine coordination. | A generic "independent branches must coordinate" iff theorem is pre-empted.  One-use is a uniqueness/bounded-counter instance. | A closed typed refinement from agent lifecycle operations to the generic invariant/coordination model may still be useful. |
| [O'Neil, Escrow Transactional Method, TODS 1986](https://doi.org/10.1145/7239.7265) and [Balegas et al., Bounded Counter, SRDS 2015](https://perso.lip6.fr/Marc.Shapiro/papers/2015/numeric-invariants-SRDS-2015.pdf) | Capacity is represented as rights; rights are partitioned across replicas, spent locally, and explicitly transferred.  If a replica lacks rights, the operation fails or obtains rights from elsewhere. | For capacity `k`, `sum_d q_d <= k` is escrow conservation, not a new theorem.  For `k=1`, only one isolated replica can hold the right. | Agent history can dynamically create, retire, and recombine the relevant replica/domain identities; the runtime adapter and operator rules are not supplied here. |
| [Lee et al., RIFL, SOSP 2015](https://web.stanford.edu/~ouster/cgi-bin/papers/rifl.pdf) | Exactly-once RPC uses stable request IDs, completion records durable atomically with effects, and retry rendezvous at one unambiguously chosen distinguished object whose metadata migrates with it. | Stable ticket identity, atomic receipt/effect recording, and "all retries find one record" are established mechanisms. | RIFL does not classify authority topology changes caused by intentional branch/restore/merge or bounded pre-commit authority. |
| [Burrows, Chubby, OSDI 2006](https://www.usenix.org/conference/osdi-06/chubby-lock-service-loosely-coupled-distributed-systems) | A stale lock holder is unsafe unless the protected resource checks a lock-generation sequencer; the resource, not merely the lock service, participates in fencing. | A domain cannot be defined by a service name alone.  Every effect sink must validate the shared epoch/fence, or it is outside that safety domain. | The paper can turn this into a concrete complete-mediation obligation for agent tool adapters and external effects. |
| [Apache Kafka transactional producer API](https://kafka.apache.org/43/javadoc/org/apache/kafka/clients/producer/KafkaProducer.html) | A `transactional.id` is recovered across producer sessions; broker-issued producer epochs fence older concurrent instances. | Epoch fencing of restored/duplicated clients is an existing industrial pattern. | Kafka has one broker transaction substrate, not a general contract for heterogeneous agent tools and dynamic history topology. |
| [Memoir, IEEE S&P 2011](https://www.microsoft.com/en-us/research/publication/memoir-practical-state-continuity-for-protected-modules/) | Protected, nonrollbackable request-history summaries, deterministic replay, and machine-checked state-continuity proofs. | Keeping monotone security state outside the checkpoint and proving rollback resistance are established. | Memoir enforces one linear protected-module continuity, not policy-approved alternative histories and their bounded authority. |
| [ROTE, USENIX Security 2017](https://www.usenix.org/conference/usenixsecurity17/technical-sessions/presentation/matetic) | Explicit adversarial restart and multiple enclave instances, including routing reads/writes to divergent instances; distributed monotone state; an all-or-nothing rollback property. | "Multiple instances with independent stale state are unsafe; use shared/distributed monotone state" is established. | ROTE targets freshness/continuity, not agent intent aliases, detached escrow, or Merge admission. |
| [SUNDR, OSDI 2004](https://www.usenix.org/conference/osdi-04/secure-untrusted-data-repository-sundr) | Fork consistency is the strongest integrity possible without online trusted parties in its model; stronger consistency follows with an online trusted consistency server. | The availability/online-coordination tradeoff for forked views is old. | Detection/view consistency differs from bounded productive use through intentional agent histories. |
| [Brooker et al., Restoring Uniqueness in MicroVM Snapshots, 2021](https://arxiv.org/abs/2102.12892) | Clone/restore generation changes, reseeding/uniqueness notifications, the TOCTOU gap between generating and using unique state, and the need for an external fence before side effects. | Restore notification or a new ID alone is not enough; admission must be tied to an external effect gate. | It does not characterize bounded authorization rights or Merge. |
| [Hawblitzel, Linear Types for Aliased Resources, 2005](https://www.microsoft.com/en-us/research/publication/linear-types-for-aliased-resources/) | Linear types can encode disciplined aliasing of state-dependent resources. | "Linearity means aliases are forbidden" is an overclaim. | The useful distinction is representation aliasing versus independent authoritative state machines. |

## 3. Audit of the current Lean frontier

The current module defines an accepted `Finset Occurrence` to be admissible
when it is inside the current set and `domainOf` is injective on the accepted
set.  It then proves that its cardinality is at most the cardinality of
`current.image domainOf`, and constructs one representative per image element
to make the bound tight.

That result is mathematically correct, but has six paper-level limitations.

1. **Per-domain safety is assumed.**  `singlePerDomain` is the property an
   atomic durable redeemer is supposed to establish.  The proof does not derive
   it from CAS, transactions, fencing, or a state-machine semantics.
2. **Tightness is definitional, not operational.**  Choosing one representative
   from every nonempty domain shows that such a set satisfies the predicate.  It
   does not show an execution in which isolated domains can all accept, nor a
   necessity result under availability.
3. **A set loses repeated uses.**  If one occurrence succeeds, its local state
   is rolled back, and the same occurrence succeeds again, a set of occurrences
   still has cardinality one.  The security property must count durable
   acceptance events/receipts, not distinct occurrence names.
4. **`domainOf` is an oracle.**  Two services with the same string ID but
   separately rollbackable state are different domains; two replicas of one
   linearizable state machine are one domain.  The module does not define or
   validate this semantic equivalence.
5. **No dynamic topology exists.**  Fork, Restore, Merge, domain retirement,
   epoch fencing, quota transfer, and receipt reconciliation do not occur.
6. **The budget generalization is not escrow.**  The natural-number theorem
   still gives every active domain unit capacity.  General capacities require
   per-domain quotas and a sum-of-rights invariant.

Thus the current theorem is valuable as (a) a strict counterexample to the old
claim that raw current-fiber cardinality is universally necessary and (b) a
small algebraic lemma used inside a larger proof.  Calling it an "exact
coordination frontier" without the operational assumptions will invite a
definitional-theorem rejection.

### Additional semantic counterexamples to raw active-domain counting

Even after replacing occurrences with domains, the slogan "maximum accepts is
the number of active domains" is false without more structure.

- Two domains can occur in mutually exclusive choice branches.  Both are
  active in a syntactic plan, but winner selection disables one before either
  can prepare.  Domain count is then only an upper bound.  Tightness requires a
  co-preparable frontier plus product independence/non-vacuity.
- A state can have only one active domain at every instant and still double
  spend over time: domain `d1` accepts and closes, then Restore creates `d2`
  from an old eligible checkpoint.  The property is cumulative and must track
  monotone receipts and logical domain lineage.
- Equal domain IDs do not imply a shared domain.  Two SQLite databases cloned
  from one snapshot may contain the same identifier while evolving
  independently.  Conversely, two physical servers backed by one linearizable
  register or quorum are one logical domain.
- Mere connectivity is also insufficient.  Pairwise coordination paths need
  not imply that every competing acceptance is jointly serialized.  Domain
  equivalence must be defined by a shared linearization object and verified
  fence semantics, not graph labels or connected components.
- Two controller domains can both accept while an external sink deduplicates
  their common operation ID.  This prevents duplicate physical effects but
  does not repair authority double spend.  The domain theorem should count
  controller `Prepare` receipts and retain external exactly-once as a separate
  obligation.
- Aliases of one domain are safe alternatives, but not necessarily safe members
  of an all-must-succeed batch.  A well-formed batch must choose at most one
  representative per `(grant, domain)` or explicitly define alias coalescing;
  the first CAS should bind the operation/effect digest so semantically
  different aliases cannot win under the same authority silently.

## 4. A theorem package that could cross the CSF boundary

### 4.1 Operational objects

For each logical grant `g` with capacity `kappa(g)`, model:

- durable success receipts (events, not an occurrence set);
- a set of independently advancing redemption domains;
- domain epochs and a semantic co-linearization relation: two aliases share a
  domain only if every successful attempt consults the same durable quota state
  before its external effect;
- per-domain unspent rights `q(g,d)` and spent receipts `s(g,d)`;
- an isolation/availability premise saying that a domain holding a right can
  accept while other domains are unreachable;
- complete mediation and sink-side fencing; and
- typed history transitions that may preserve, split, retire, or merge domains.

Let `F(S)` be the lifecycle-derived family of sets of controller handles that
can actually be prepared together, rather than treating every textual branch
as co-live.  For the unit-capacity functional case, a useful static risk metric
is

```
mu_g(S) = max_{F in F(S)} | boundLineages(g,S) union
                              openDomains(g,S,F) |.
```

This metric still needs the temporal conservation theorem below: a later
Restore must not create a fresh open lineage after an earlier lineage has
already produced a receipt.

The authoritative potential is

```
Phi(g) = durable_spent(g) + sum_d q(g,d).
```

The key point is that aliases do not appear in this sum.  Aliases only determine
which domains can be reached.

### 4.2 Three results, not one image-cardinality lemma

**Clone/restore separation (necessity).**  If all admission state is included in
a clonable/rollbackable checkpoint, Fork or Restore can produce two isolated
states that are locally indistinguishable from an eligible pre-use state.
Under isolated availability, each accepts; composing the two executions breaks
at-most-`k`.  Therefore safety requires a shared nonrollbackable redeemer,
pre-split escrow/fencing, or loss of isolated availability.  This proof must
state the fault and liveness assumptions explicitly.

**Domain conservation (sufficiency and matching necessity).**  If every domain
atomically enforces its local rights, success receipts are monotone, and every
split/transfer conserves `Phi(g) <= kappa(g)`, then arbitrary interleavings of
domain-local redemptions preserve global bounded use.  Conversely, under
isolated availability and independent scheduling, assigning total local rights
greater than `kappa(g)` yields a schedule with too many successes.  This is an
agent-specialized escrow theorem and must be credited as such.

**History-operator refinement.**  Prove necessary/sufficient admission rules
for the paper's actual operations:

- shared Fork may copy aliases while preserving one domain/epoch;
- detached Fork must atomically fence the source epoch and partition residual
  rights before children become runnable;
- Restore rewinds reconstructable state but must use the current external epoch,
  never the snapshotted admission state;
- Merge must first fence/quiesce child domains, retain the monotone union of
  receipts, and transfer only genuinely unspent rights into a fresh epoch;
- `Prepare` consumes a right and creates a stable ticket/receipt in one durable
  transaction; retries rendezvous on that identity.

The paper-level theorem should say that these rules refine the generic
domain-conservation invariant through arbitrary checked agent histories.  This
is the portion not supplied by escrow or I-confluence.

A useful representation corollary then recovers both extremes cleanly.  If the
trusted handle-to-linearizer mapping is injective on every co-preparable
frontier, domain risk reduces to current-occurrence linearity.  If that mapping
is constant and the shared cell is durable, arbitrarily many history aliases
are safe.  These two strict witnesses show that the new model is not a renamed
version of the old occurrence count.

### 4.3 Optional stronger exact characterization

If one alias may reach several domains and a trusted local controller allows an
alias to prepare at most once, raw active-domain cardinality is no longer exact.
The maximum simultaneously realizable redemptions is a capacitated bipartite
matching between eligible controller occurrences and domain quota slots.  A
matching/min-cut characterization would be genuinely less trivial and expose
why `image domainOf` is only the functional, unit-capacity special case.

This extension should be added only if it matches the runtime threat model.  If
a rollbackable controller can reuse the same occurrence repeatedly, it must
first be replaced by an event/receipt model; matching over occurrence names
would again undercount the attack.

## 5. Defensible novelty and story

### One-sentence novelty claim

> We do not introduce online ratification, escrow, fencing, or the general
> necessity of coordination; we give an operational, mechanized
> characterization of how intentional agent Fork, Restore, and Merge change
> which action aliases share durable admission state, and prove the
> operator-level conditions that refine established per-domain mechanisms into
> global bounded-use authority across arbitrary checked histories.

An exact theorem sentence, if the stronger semantics is actually proved:

> Under complete mediation, durable per-domain admission, and isolated-domain
> availability, a grant of capacity `k` remains globally bounded through the
> typed agent lifecycle exactly when every domain-changing transition preserves
> spent receipts plus distributed unspent rights at at most `k`.

### Abstract/intro spine

1. Agent runtimes intentionally turn execution into a tree and later restore or
   merge branches.  The old rollback problem is known; the new operational
   question is which copied plans remain aliases of one authority and which
   become independently redeemable.
2. Raw copy count is the wrong invariant.  Two Codex/Claude histories may carry
   the same planned tool action yet race safely through one durable monitor;
   one checkpoint restored with a private, stale monitor may execute twice even
   though there is only one textual occurrence.
3. Existing mechanisms solve fixed points in the design space: ratifiers/RIFL
   give shared redemption, escrow gives detached availability, fencing rejects
   stale incarnations, and rollback-protection systems externalize monotone
   state.  None of these facts says how an agent runtime should transport their
   assumptions through Fork/Restore/Merge.
4. Introduce history plus redemption topology.  A domain is semantic, not a
   name: all attempts in it jointly linearize against one rollback-independent
   quota state and every sink validates its epoch.
5. State the separation theorem, conservation theorem, and typed operator
   refinement.  Present strict examples: many aliases/one domain is safe; one
   restored local state/two independent domains is unsafe; detached branches
   are safe after one-unit escrow to only one branch.
6. Give the reference-monitor algorithm and one real runtime adapter.  The
   evaluation tests semantic coverage, rejection/acceptance boundaries, crash
   points, and overhead; it does not need to pretend that trace frequencies
   prove the theorem.

### Replacement principle

The current slogan "history may be copied; authority occurrences may not" is
too strong.  A safer and more useful principle is:

> Histories and authority representations may be copied; independently
> redeemable capacity may not be amplified.

Or, operationally:

> Share a redeemer, split rights, or stop: a history transformation that creates
> a new independently advancing effect domain must either preserve a common
> fence, transfer escrowed authority, or withhold autonomous execution.

## 6. Related-work delta to state explicitly

- **HotOS/Memoir/ROTE/SUNDR:** these establish the need for
  rollback-independent security history and the limits of forked views.  The
  delta is policy-approved non-linear agent histories plus bounded authority
  transport, not external monotone state itself.
- **Consumable Credentials/RIFL/Chubby/Kafka:** these instantiate one shared
  redemption domain through ratification, completion records, or epochs.  They
  are mechanism baselines.  The delta is the runtime rule deciding whether a
  history operation preserves that domain or creates/fences another.
- **Escrow/Bounded Counter/I-confluence:** these own rights partition and the
  generic availability-versus-coordination boundary.  The delta is a typed
  lifecycle refinement and exact Fork/Restore/Merge admission contract, not
  quota arithmetic.
- **Linear/capability systems:** these own linear use and disciplined aliasing.
  The delta is the cross-runtime, rollback-domain meaning of aliasing, not a
  claim that linearity forbids representation copies.
- **VM generation-ID work:** this owns clone/restore notification and warns that
  external fencing is still needed.  The delta is conservation of bounded
  authorization and receipt-aware Merge.

## 7. Claims to avoid

Do not claim any of the following:

- execution becomes a tree under checkpoint/restore;
- security state must live outside rollbackable state;
- multiple credential copies are inherently unsafe;
- one atomic CAS/ratifier makes retries or copies safe as a new idea;
- independent replicas need coordination for non-confluent invariants as a new
  general theorem;
- partitioning one unit of authority across detached replicas is new;
- stable request IDs, atomic completion records, epochs, or fencing are new;
- the present `Finset.image` theorem proves atomicity, durability, availability,
  rollback safety, or execution-level necessity;
- a shared service endpoint is automatically one domain without sink-side epoch
  validation and complete mediation;
- the formal result proves physical exactly-once execution at heterogeneous
  external services.

## 8. Evidence needed after the theory is repaired

The theory should carry the paper, but a small experiment is still necessary.
The most valuable matrix is semantic, not a broad benchmark:

1. shared-gate aliases: two live histories, one durable redeemer, exactly one
   accepted `Prepare`;
2. detached clone: private snapshotted admission state, counterexample with two
   durable receipts;
3. detached escrow: source fenced, one unit assigned to one child, invariant
   preserved during partition;
4. restore after success: stale epoch rejected at the effect adapter;
5. merge after partial use: receipts retained, only unspent rights returned;
6. crash cuts around `Prepare`: no state exposes a right and a ticket together;
7. one real Codex/Claude callback path proving the required domain/epoch metadata
   can be extracted and mediated.

The private paper-formation trace can establish that checkpoint/fork/retry and
tool boundaries occur in a real workflow and can test the adapter.  It cannot
establish prevalence in the population, security against unobserved sinks, or
novelty.  Heavy performance evaluation is secondary unless the paper claims a
low-latency production monitor.

## 9. Follow-up: the configuration-morphism novelty ceiling

The repaired complete model cannot globally sum every conditional right.
Instead it first quotients history handles by their semantic linearization
cell and then maps independent cells back to source authority atoms:

```text
handles --resolve--> cells --lineage--> authority atoms.
```

For a finite downward-closed source configuration family, the following
equivalence is correct: `lineage` preserves every nonnegative additive
authority bound exactly when it maps every target co-redeemability
configuration to a source configuration and is injective on that target
configuration.  Collision and forbidden-image directions need only two
indicator-weight counterexamples.

This equivalence is a useful completeness bridge but **not new concurrency
mathematics**.  Winskel's standard morphism between stable configuration
families is already a partial function that maps every configuration to a
configuration and is locally injective on each one; the accompanying text
explains that two consistent events cannot synchronize with one image event.
See Definition 2.5.1 and Proposition 2.5.2 in
[Event Structures](https://www.cl.cam.ac.uk/~gw104/Winskel1987_Chapter_EventStructures.pdf).
The same local-injectivity/configuration-preservation shape appears in later
configuration and ST-structure morphisms.  Consequently the paper must credit
this structure and must not advertise exclusive events sharing one abstract
event as a discovery.

The surviving novelty candidate is operational:

1. derive `resolve`, the target configurations, and `lineage` from typed agent
   Fork/Restore/Merge rather than choosing them to satisfy the theorem;
2. include durable Prepare commitments as a fixed prefix of every future, so a
   sequential restore cannot erase an earlier use;
3. prove that a rollback-local implementation with product-composable clone
   availability necessarily creates a lineage collision;
4. give a complete runtime action: preserve one shared cell, durably remove the
   joint configuration by fencing/selection, allocate distinct escrow atoms,
   or reject/reauthorize; and
5. prove receipt/epoch/digest/Prepare-before-Dispatch trace obligations that
   nonnegative resource bounds cannot express.

The scalar `charged + sum rights <= capacity` theorem remains exact only when
all detached domains can jointly advance.  Conditional choice remains governed
by the configuration-indexed invariant.  This correction restores the Initial
Narrative's co-durability principle while fixing its overly strict occurrence
representation.
