# Literature node: one-use authority across history and coordination domains

Date: 2026-08-01 (America/Vancouver)

## Objective and declared coverage boundary

This node tests three name-free candidate claims prompted by a hostile review:

1. Multiple aliases of one one-use authorization can be safe when every alias
   redeems through one shared atomic service; claim-level cardinality one is
   therefore sufficient but not universally necessary.
2. If live aliases can redeem through independent one-shot services, the
   worst-case number of accepted redemptions is the number of nonempty service
   domains.  Global one-use safety then requires one domain, explicit escrow to
   one domain, or separately authorized tokens.
3. Agent Fork, Restore, and Merge are a useful specialization because they can
   change whether descendants retain one shared authority service or detached
   rollbackable copies.  A typed history adapter must expose that distinction.

The search covers same problem (rollback/fork reactivating security state),
same mechanism (online ratification, atomic redemption, escrow rights), same
theorem family (coordination necessity/sufficiency), and the agent-history
setting.  It does not attempt a universal survey of distributed mutual
exclusion, electronic cash, or all capability systems.

## Search log

| Query/source family | Purpose | Outcome |
|---|---|---|
| `HotOS 2005 execution tree rollback security state Garfinkel Rosenblum` | Earliest direct statement of tree-shaped execution and rollback-independent security | Primary USENIX HTML/PDF verified. |
| `Consumable Credentials ratification copied proof` | Test whether a shared online redeemer already permits copied authorization material | Primary NDSS page/PDF verified; it does. |
| `bounded counter CRDT escrow rights invariant replicas` | Test the detached-replica/escrow alternative | Primary arXiv author paper verified; rights are partitioned and explicitly transferred. |
| `invariant confluence coordination avoidance necessary sufficient` | Test generic novelty of an alias-or-coordinate theorem | Primary PVLDB paper verified; generic coordination necessity is established. |
| `fork linearizability rollback protection independent clients shared state` | Check adjacent history-integrity models | SUNDR/BFT2F/LCM family remains adjacent; it protects view consistency rather than typed one-use authority through intentional agent operators. |
| `Laws of Order expensive synchronization` | Check lower bounds on atomic coordination itself | Primary author/ACM metadata verified; it is a broad synchronization lower bound, not this lifecycle characterization. |

Searches were run on 2026-08-01.  Primary proceedings, author PDFs, and
official metadata were preferred; secondary pages were used only as leads.

## Primary-source findings

### Garfinkel and Rosenblum, HotOS 2005

The paper explicitly says VM execution changes from a line to a tree with
multiple simultaneously existing branches.  It documents rollback reuse of
accounts, passwords, keys, nonces, and attacker-visible history, and recommends
moving security-relevant state outside the guest or into storage independent
of rollback.  This owns the high-level observation that rollbackable execution
and monotone security history need different domains.

It does not define one-use authorization occurrences, distinguish aliases
behind one shared linearization point from detached redeemers, model
intentional Fork/Restore/Merge contracts, give an admission algorithm, or prove
a preservation/necessity theorem.

Local PDF:
`docs/reference/closest-work/2005-garfinkel-when-virtual-harder-real.pdf`
(SHA-256 `c28fc4435a39a2618f46264c0450d9b93ed2c6f86ac3a7b78fd88b077f0a47cc`).

### Bowers et al., NDSS 2007

Consumable Credentials begins from easily copied signed credentials and
enforces bounded use through a named online ratifier.  The ratifier tracks
consumption, binds ratification to the proof/goal/nonce, and prevents the same
authorization from being productively spent again.  It therefore directly
refutes any universal claim that multiple syntactic aliases or proof copies
are unsafe: aliases are safe behind one correct shared redeemer.

The paper does not model execution-history operators or classify when a fork
preserves that shared redeemer versus clones/detaches the redemption state.
Its ratifier is the principal mechanism baseline for the centralized profile.

### Bailis et al., PVLDB 2014/2015

Invariant confluence gives a generic necessary-and-sufficient condition for
safe coordination-free transaction execution.  It already owns the broad
claim that some invariants require coordination and others do not.  The new
paper must not present a generic coordination theorem as its novelty.

The useful specialization is closed-form and lifecycle typed: for one-use
authority, count distinct independently linearized redemption domains reached
by one token, then connect changes in that count to actual Fork/Restore/Merge
descriptors and durable ticket identity.

Local PDF:
`docs/reference/foundations/2014-bailis-coordination-avoidance.pdf`
(SHA-256 `5ec38019fe24187b985d1db2f36ba7717d191c46c2abb2b792d49f8df6f85cad`).

### Balegas et al., SRDS 2015

Bounded Counter CRDTs adapt escrow transactions by representing remaining
capacity as rights partitioned among replicas.  A replica can act locally only
within its rights; rights are explicitly transferred, and operations otherwise
coordinate or fail.  For a one-unit resource, this already yields the
industrial alternative: one detached replica gets the right, or replicas must
coordinate.

The paper does not connect replicas to dynamic agent-history lineage or show
when a history operation changes the relevant coordination topology.

Local PDF:
`docs/reference/foundations/2015-balegas-bounded-counter.pdf`
(SHA-256 `2fdd8739f5c9033ba0620c20b09f3248d60296b6814bb1fe727fac43e9a3f49a`).

## Claim-oriented novelty map

| Candidate plain claim | Same-claim risk | Decision |
|---|---|---|
| Multiple aliases are safe behind one shared atomic redeemer. | High | Established by online ratification/centralized reference monitors; use as a required baseline and correction, not a contribution. |
| Independent one-shot domains can each accept once; worst-case multiplicity is the number of active domains. | High as generic mathematics | Useful exact lemma, but alone is a quotient/cardinality fact and not CSF-level novelty. |
| History operations must preserve or explicitly change the token-to-linearization-domain relation; detached Fork/Restore needs escrow while shared-gate aliases may remain. | Medium | Promising agent-specific boundary if mechanized over typed operations and connected to the runtime API. |
| Claim-level current-fiber linearity is necessary for all safe runtimes. | Falsified | It is necessary only for the independently-preparable/private-domain profile; the paper must state this scope. |
| Existing durable claim/token bindings survive arbitrary checked history transformations. | Medium | Still distinct and useful; retain as the monotone post-promotion half of the story. |

## Competing scientific positions and baseline implications

| Position | Representative source/mechanism | What it would mean if sufficient |
|---|---|---|
| Share all aliases behind one online atomic redeemer | Consumable Credentials; centralized CAS | Pre-promotion claim cardinality one is unnecessarily strict for connected descendants. |
| Partition/transfer rights to detached replicas | Escrow transactions; Bounded Counter | The independently-preparable profile should be explained as one-unit escrow, not a new linear-resource idea. |
| Analyze arbitrary operations/invariants for coordination freedom | Invariant confluence | The paper's value must come from the closed agent lifecycle and exact operator-level transport rule, not generic coordination necessity. |
| Keep security state outside rollbackable execution | HotOS 2005; Memoir/ROTE/LCM | Three state planes are an established architectural premise; formal authority/domain transport is the delta. |

No additional performance baseline is implied.  The decisive validation is a
two-profile semantic matrix: shared-gate aliases must be accepted, detached
duplicate domains must be rejected or escrowed, and history transitions must
preserve stable post-Prepare identity.  A real Codex callback can instantiate
the shared-gate seam; synthetic detached histories instantiate the other side.

## Larger claim and paper consequence

The larger defensible principle is not “authority occurrences may never be
copied.”  It is:

> A history may have many aliases of one planned action, but one-use authority
> may cross at most one independent linearization domain.  Forking a domain
> requires coordination, escrow transfer, or new policy-approved authority.

This subsumes two useful deployment profiles without attacking a strawman:

- connected descendants may share one non-rollbackable reference monitor and
  race on one atomic token redemption;
- detached/offline descendants must receive disjoint escrowed tokens/rights,
  or lose independent availability until they reconnect.

Fork/Restore/Merge are agent-specific because they dynamically change which
profile applies while copying executable intent.  The current token-linear
model is the detached/private-domain instantiation; the new theorem must state
that fact rather than advertise it as universally necessary.

## Remaining uncertainty and next node

The exact domain-count lemma is likely too elementary to carry novelty by
itself.  Acceptance depends on a mechanized composition theorem that maps each
typed history operator to preservation/change of the linearization-domain
quotient, plus an explicit strict example showing shared aliases are allowed
while independently preparable copies are not.  The runtime pilot should expose
domain identity as trusted metadata if the paper claims implementation of that
larger policy; otherwise it must say the pilot enforces the stricter escrow
profile.

Next: complete the Lean domain theorem, attack its assumptions independently,
then rewrite the abstract/introduction/model only after theorem names and
boundaries are frozen.
