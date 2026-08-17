# Versioned authority schedule certificates

**Read-only theory design, 2026-08-01.** This report does not modify the
canonical story, paper, artifact, or Lean development. It was derived after a
complete read of the current idea history, paper, evaluation and runtime
contracts, the authoritative `Lifecycle`/`Topology`/`Merge`/`Step`/`Trace`
modules, `Transfer.lean`, and the Step 0006 killer-hypergraph audit.

## Executive verdict

The useful new object is not a static order carrying a compare-and-swap
version. It is an **ordered lineage-slot plan** whose authority budget survives
claim-preserving history transformations.

1. A source owner in a certified schedule becomes a stable *slot*. A canonical
   Fork or Restore may refine that slot into several target owners, and claim
   fragments inherit the slot. If the total full tentative load and total
   promoted load in every target slot are bounded by the corresponding source
   loads, then the source order lifts without peeling again. Each source slot
   is replaced by one contiguous target block; owners inside a block may run in
   any order, but blocks must retain the source order.
2. The load conditions are derivable from the existing claim-level
   `Transfer.fiber_demand` theorem plus canonical singleton projection, except
   that the current LTS lacks an immutable **batch/slot agreement** check. That
   check is the smallest required semantic extension.
3. The single-step theorem composes. Across any depth of slot-preserving,
   fiber-conservative Fork/Restore and same-slot Merge, plus explicit
   restriction, an ordered plan stays valid. A planned Prepare consumes a
   member of the head slot, atomically advances the plan phase and installs its
   durable ticket. This gives a credible trace-level theorem rather than a
   renamed monotonicity fact.
4. Merge structure and even the current simulation certificate do **not** imply
   schedule preservation. A simulation-admitted cross-slot coarsening can turn
   a safe four-owner order into a two-owner dead core while preserving
   authority continuity. Cross-slot Merge therefore needs re-planning or an
   atomic seal.
5. Plan version comparison belongs at `PreparePlanned`, in the same durable
   transition that moves claims to `D`, creates tickets, and advances the tail.
   Dispatch must not re-check the current plan version. Revoke, selection,
   restore, or merge after Prepare cannot erase the already sealed operation;
   Dispatch checks only the durable stable ticket.
6. Positive schedule certificates transport under relaxation. Negative core
   certificates transport in the opposite direction, under strengthening.
   These are useful verifier rules but are not themselves novel. The stronger
   contribution is that the actual agent lifecycle has a checked refinement
   class under which a plan remains executable and a precise boundary—cross-
   slot coarsening—where re-planning is necessary.

The recommended headline is:

> **Schedule-continuity theorem.** A safe authority schedule compiled into
> ordered lineage slots remains executable through arbitrary finite traces of
> slot-preserving, fiber-conservative history transformations and phase-ordered
> planned Prepare steps. Fork and live Restore may refine a slot into any
> number of descendants without re-running the scheduler; restriction deletes
> work; same-slot Merge may coarsen it. Cross-slot coarsening is not closed,
> even for simulation-certified Merge, and must be re-planned or sealed.

This is stronger and more agent-specific than the one-step fiber lemma. The
static peeling algorithm remains acknowledged AND/OR/antimatroid machinery.

## 1. Static authority instance

Fix a well-formed, authority-continuous source state and a fixed promotion
batch. Let `P` be its nonempty owner groups. For each owner `b`, define

\[
p_b=\sum_{c\in U_b}w(c),\qquad
r_b=\sum_{c\in Q_b}w(c),\qquad
K=G-d,\qquad h_b=K-r_b.
\]

All inequalities are componentwise over the finite coordinate set. The batch
assumptions imply `p_b <= r_b`. By downward closure and source support, the
singleton `{b}` is the cheapest support witness. Thus an order
`sigma=(b_1,...,b_n)` is executable exactly when

\[
\forall i.\quad \sum_{j<i}p_{b_j}\le h_{b_i}.
\tag{1}
\]

This is the Step 0006 vector start-deadline characterization. It is classical
as a static scheduling/AND-OR feasibility result; the purpose here is to make
it stable under the actual agent lifecycle.

## 2. Three certificate types

### 2.1 Common authenticated envelope

Every certificate has a common envelope

```text
CertEnvelope(
  plan_id, batch_id,
  authority_version, plan_head_hash,
  current_contract_hash, parent_certificate_hash,
  remaining_claim_ids,
  claim_epoch_bindings,
  owner_epoch_bindings,
  immutable_effect_bindings
)
```

The semantic roles are distinct.

- `authority_version` linearizes mutations relevant to the *remaining plan*.
  It need not advance for ticket-phase-only Dispatch/Crash/Retry/Settle.
- `plan_head_hash` commits to the canonical plan projection used by the next
  Prepare: capacity, durable demand, remaining claims, their owner and grant
  epochs, slot assignment, and phase.
- `current_contract_hash` authenticates the controller's exact canonical
  contract bytes. A topology transport creates a child certificate with a new
  hash; the mathematical theorem uses extensional contract/support facts, not
  syntactic equality of guard rows.
- `parent_certificate_hash` creates an auditable derivation chain. It is not an
  unresolved pointer: the transition and child body are retained in the replay
  bundle.
- branch and grant **epoch identities**, claim IDs, demand/binding metadata,
  and slot identities are immutable. Merely reusing a branch spelling cannot
  satisfy the certificate.

Cryptographic collision resistance and durable-head anti-truncation are
implementation assumptions. The formal model should use equality of canonical
records; hashes are its runtime representation.

### 2.2 Positive schedule certificate

A simple one-state certificate is

```text
ScheduleCert(envelope, owners, order, p, r, prefix_witnesses)
```

where `order` is a permutation and `prefix_witnesses` prove (1). Its stronger
compositional form is

```text
SlotScheduleCert(
  envelope,
  slots = [s1,...,sm],
  slot_of_claim,
  slot_promotion_budget P[s],
  slot_tentative_budget R[s],
  source_margins M[s],
  current_slot,
  prepared_members,
  remaining_groups,
  support/epoch witnesses
)
```

Initially each source owner occupies one slot, `P[s_b]=p_b`,
`R[s_b]=r_b`, and

\[
M[s_i]=K-R[s_i]-\sum_{j<i}P[s_j]\ge0.
\tag{2}
\]

After refinement, several current owners may occupy the same slot. Every
current owner must be **slot-pure**: all planned claims it owns have one slot,
and the owner's entire current tentative bundle is charged to that slot's
`R` bound. Claims fragmented by a transfer inherit the source claim's slot.

The certificate is an enforcement plan, not a scheduling hint. The controller
may choose any current owner in the head slot, but it may not Prepare a later
slot while the earlier slot has an unprepared, nonwithdrawn group.

### 2.3 Negative core certificate

```text
CoreCert(
  envelope,
  owner_set P,
  peeling_log,
  dead_core Rstar,
  p, h,
  overloaded_coordinate k[b] for b in Rstar
)
```

The checker replays each legal backward deletion, then checks

\[
\forall b\in R^\star.\quad
\sum_{a\in R^\star\setminus\{b\}}p_{a,k_b}>h_{b,k_b}.
\tag{3}
\]

The peeling log proves how noncore owners were removed; (3) proves no order of
the residual core exists. Choice-independent peeling makes the stuck residual
canonical, but a verifier needs only the log plus the final obstruction.

### 2.4 Final-seal certificate

```text
SealCert(
  envelope,
  serial_owners R,
  serial_order rho,
  atomic_final_owners H,
  prefix_witnesses,
  final_support_witnesses,
  atomic_base_witness,
  stable_effect_assignments,
  optional coordination_cost
)
```

For `P = R disjoint-union H`, this certificate is valid exactly when

1. `rho` satisfies (1) on `R`;
2. every `b in H` satisfies `p(R) <= h_b`; and
3. `d+p(P) <= G`, with every claim/epoch/binding premise required by the
   actual atomic Prepare rule.

The controller serially consumes `R`, then promotes all of `H` in one
`PreparePlanned` transition. A full atomic fallback is the special case
`R=empty, H=P`. Minimizing seal *count* is vacuous; cost or seal size must be
explicit if optimization is claimed.

## 3. Fiber refinement theorem

### 3.1 Definition

Let `I=(P,p,r,K)` have a safe order `sigma`. Let the target owner set be `P'`
and let `f:P' -> P` assign each target owner to one source slot. Write
`F_b={x in P' | f(x)=b}`; an empty fiber deletes a source slot. Assume:

1. target owners are supported and open, and `p'_x <= r'_x`;
2. capacity and pre-batch durable base are unchanged (the theorem also works
   for a larger `K'`);
3. **full-load conservation** for every source slot and coordinate,
   `sum_{x in F_b} r'_x <= r_b`;
4. **batch-load conservation** for every source slot and coordinate,
   `sum_{x in F_b} p'_x <= p_b`; and
5. owner, grant epoch, claim lineage, demand, and binding metadata pass the
   transfer checker.

Expand `sigma` by replacing every source owner `b` with all members of `F_b`
in an arbitrary internal order, keeping each fiber contiguous.

### 3.2 Theorem and proof

**Theorem 1 (blockwise fiber transport).** Every such block expansion is a
safe target order. No peeling or guarded support query is needed.

**Proof.** Consider target owner `x in F_b`. Its predecessor promotion load is
the sum of completed source fibers before `b` plus earlier members of `F_b`.
The external part is at most the source predecessor load by batch-load
conservation. Source safety gives

\[
\sum_{a<_{\sigma}b}p_a\le K-r_b.
\]

For the internal part, `p'_y <= r'_y` and full-load conservation give

\[
r'_x+\sum_{y\in F_b\text{ before }x}p'_y
\le \sum_{y\in F_b}r'_y\le r_b.
\]

Adding the two inequalities yields target support for `x`. The argument is
independent of the internal fiber order. Empty fibers simply remove a block.
After all blocks execute, exact promotion filters and cleanup reach the same
denotational endpoint as atomic promotion of the retained target batch. ∎

### 3.3 Exact condition versus compositional condition

For a *particular* target and fixed source block order, the exact condition for
**every** internal order is

\[
\forall b\in P,\ \forall x\in F_b.\quad
\sum_{a<_{\sigma}b}\sum_{y\in F_a}p'_y
+\sum_{y\in F_b\setminus\{x\}}p'_y
\le K'-r'_x.
\tag{4}
\]

Thus the two aggregate conservation conditions are sufficient, not necessary
for a particular roomy target. They are the right **context-independent local
transport contract**: they derive (4) solely from the old certificate and are
tight in adversarial tight contexts.

The distinction should be explicit. Claiming the aggregate bounds as an exact
iff for a particular target would be false.

### 3.4 Connection to the existing `Transfer` checker

The current Lean transfer checker already provides most of the proof.

- `Transfer.CoreValid.fiber_demand` bounds all target claim fragments refining
  each source claim.
- `Valid.owner_projection`, together with the canonical projection of a target
  singleton, proves that every target descendant's claims originate in the
  corresponding source owner.
- Summing claim-fiber inequalities first by target owner and then by source
  owner derives full-load conservation.
- `targetCore_durableLoad` proves that Fork/Restore/Merge transfer does not
  change the durable base.

What is missing is a planned-batch predicate such as

```text
BatchRefines(U, U', rho) :=
  forall c' in U', exists c in U, rho(c') = some c
```

plus immutable slot agreement

```text
SlotAgrees(slot, rho) :=
  forall c' c, rho(c') = some c -> slot(c') = slot(c).
```

`fiber_demand` then yields batch-load conservation for `U'`. Without
`BatchRefines`, a target adapter could promote fragments of a source claim that
was not in the certified batch, so `sum p' <= p_b` would not follow. Without
`SlotAgrees`, a cross-slot Merge could satisfy authority simulation but destroy
the plan order.

Canonical Choice/Parallel Fork, replacing Restore, and live Restore have the
required functional singleton projection. Simulation Merge does not in
general: `project {x}` may contain several source owners.

## 4. Why contiguous stable slots are necessary

### 4.1 Interleaving blocks is unsound

Use one coordinate and `K=3`. The safe source order is `A` then `B`, with

```text
A: p=2, r=3
B: p=1, r=1.
```

Refine `A` conservatively into

```text
a1: p=1, r=1
a2: p=1, r=2.
```

Both aggregate equalities hold. Either internal order in the contiguous block
`[a1,a2]` is safe, followed by `B`. But the interleaving `[a1,B,a2]` fails:
when `a2` is reached, predecessor demand is two and its headroom is one.

Therefore a runtime must enforce block precedence. Saving an advisory order in
telemetry is insufficient.

### 4.2 Each aggregate premise has a tight counterexample

- Without full-load conservation, let `K=2`, source `b` have `p_b=r_b=2`, and
  refine it into `x:(p=1,r=1)` and `y:(p=1,r=2)`. Batch promotion is conserved,
  but order `[x,y]` fails because `1 > K-r_y=0`.
- Without batch-load conservation, let `K=3`, source order `A,B` have
  `A:(p=1,r=2)` and `B:(p=1,r=2)`. Refine `A` into two owners each with
  `(p=1,r=1)`. Full tentative load is conserved, but after the block the
  promotion prefix is two, exceeding `B`'s headroom one.

These show why both summaries are needed for a source-certificate-only
transformer. They do not contradict the exact target test (4).

### 4.3 Cross-slot coarsening breaks even simulation Merge

Let `K=4` and use four source owners in the safe order `a,b,c,d`:

```text
a: p=1, r=1       b: p=1, r=2
c: p=1, r=2       d: p=1, r=1.
```

The prefix inequalities are `0+1<=4`, `1+2<=4`, `2+2<=4`, and
`3+1<=4`. Now Merge `a,c` into target owner `x` and `b,d` into target owner
`y`, preserving all claim demand:

```text
x: p=2, r=3       y: p=2, r=3.
```

Let the target contract be choice between `x` and `y`. It is authority-
continuous. A simulation projection may map `{x}` to `{a,c}` and `{y}` to
`{b,d}`; a source contract containing those two pairs makes the current Merge
load simulation pass exactly. Nevertheless neither target order is safe:
after either first owner, promotion load two exceeds the second owner's
headroom one. Atomic promotion remains valid because total promoted load is
four.

Thus source AC, claim-level fiber conservation, and Merge simulation are not
enough. The schedule checker must reject an owner combining different stable
slots. This counterexample is a clean necessity witness for the new semantic
field.

Same-slot coarsening is different. Once several descendants already share one
slot, merging them into one slot-pure owner preserves the slot aggregate bounds
and may transport the plan.

## 5. Positive and negative transport rules

### 5.1 Positive relaxation

For the identity-owner case, if a source order is safe and

\[
p'_b\le p_b,\qquad h'_b\ge h_b
\tag{5}
\]

for every surviving owner, then restricting the order to survivors is safe.
More generally, the exact differential test for an unchanged order is

\[
\forall b.\quad
\sum_{a<_{\sigma}b}(p'_a-p_a)\le h'_b-h_b,
\tag{6}
\]

interpreted without subtraction as the two resulting natural-number
inequalities. Equation (5) is the cheap sufficient rule; (6), or direct target
prefix checking, admits mixed changes.

Slot fiber transport is the structured generalization of (5). It allows owner
count and epochs to change while the slot budget relaxes.

### 5.2 Negative strengthening

Let `Rstar` and coordinates `k_b` satisfy (3). If every core owner survives
under an injection `j`, epochs/bindings are preserved, and

\[
p'_{j(a),k_b}\ge p_{a,k_b},\qquad
h'_{j(b),k_b}\le h_{b,k_b},
\tag{7}
\]

then the image of the same core and the same coordinate witnesses still proves
that no serial order exists. Extra owners do not invalidate the obstruction.

The direction is intentionally opposite to positive transport. Deleting a
core owner, reducing its promotion, or increasing its deadline may make an
order possible and invalidates the negative certificate. For example, under
`K=2`, two choice owners with `p=1,r=2` form a two-owner dead core; aborting
either owner leaves a trivially serializable batch.

Negative transport is useful for caching `must-seal` decisions, but ordinary
Fork/Restore transfer is demand-conservative and therefore often relaxes the
instance. A negative certificate should normally be recomputed unless an
explicit strengthening checker succeeds.

## 6. Prepare-tail advance and the correct linearization point

### 6.1 Single-owner tail theorem

Suppose `sigma = b :: tau` satisfies (1), and exact Prepare promotes `U_b`.
For any later owner `x`, an old witness has the form

\[
p_b+\sum_{a\in T}p_a\le G-d-r_x.
\]

After Prepare, durable demand is `d'=d+p_b`, so this is exactly

\[
\sum_{a\in T}p_a\le G-d'-r_x.
\]

Therefore the old proof advances to the tail by moving `p_b` from the prefix
into the durable base. No peeling is required. The same argument inside a slot
uses `p_y<=r_y` and the slot's aggregate `R` bound. A valid certificate also
proves that cleanup cannot tombstone any required tail owner; such a tombstone
would contradict its prefix support witness.

### 6.2 `PreparePlanned` rule

The extended LTS should have a rule with this shape:

```text
current PlanHead = cert.plan_head
cert.version = controller.authority_version
group owner is open and belongs to earliest nonempty slot
all batch claims/grant epochs/bindings still match
assignment is injective, covered, and fresh
existing PrepareOK premises hold
-------------------------------------------------------------
PreparePlanned(cert, group, assignment)
  atomically:
    applies prepareState,
    installs prepared tickets,
    advances/removes the slot member,
    increments authority_version,
    installs the derived tail certificate and new PlanHead
```

The schedule witness helps derive support and the durable-load premise; it does
not replace current checks for open epochs, exact claim membership, operation
binding, or assignment freshness.

### 6.3 Dispatch must not check the plan version

Once `PreparePlanned` commits, every assigned claim is in `D` and every stable
operation has a prepared ticket. The remaining plan may subsequently be
restricted, re-planned, revoked, forked, restored, or merged. None may erase
that durable claim or ticket under the current LTS.

Dispatch therefore uses the existing premise

```text
J(e) = (c, prepared) and c in D
```

and does **not** compare `cert.version` or the current plan hash. Retrying a
prepared effect after Revoke is intentionally safe. A stale-plan check at
Dispatch would turn a safety certificate into an availability bug and would
contradict the paper's sealed-operation-after-revocation semantics.

Version/CAS is consequently a race-control mechanism at Prepare, not the
scientific contribution and not a second authorization check at Dispatch.

## 7. Trace-level schedule-continuity theorem

Introduce a plan-annotated relation `PlannedStep (A,chi) eta (A',chi')` with
four classes:

1. **slot refinement:** an admitted canonical or Merge `Step`, unchanged
   capacity/durable base, immutable slot agreement, slot-pure target owners,
   and per-slot full/batch load conservation;
2. **explicit drop:** Select/Abort/Revoke restriction removes claims or entire
   groups and creates a child plan whose semantics explicitly records the
   withdrawal;
3. **planned Prepare:** `PreparePlanned` consumes a head-slot group and installs
   its tickets plus tail certificate atomically; and
4. **effect phase:** Dispatch/Crash/Retry/Settle uses the existing ticket LTS and
   leaves the plan authority projection unchanged.

**Theorem 2 (schedule continuity over lifecycle traces).** Starting from a
well-formed, authority-continuous state and a valid `SlotScheduleCert`, every
finite `PlannedStep` trace preserves:

1. lifecycle WF, AC, terminal monotonicity, epoch monotonicity, and stable
   effect binding;
2. validity of the current slot plan for every remaining group;
3. admission of any phase-ordered `PreparePlanned` by the actual `PrepareOK`
   rule;
4. impossibility of cleanup removing a required later group before its phase;
5. durable claim and ticket installation before each emitted attempt; and
6. the existing conditional concrete trace bound under complete mediation and
   the sink aggregate-outcome premise.

Moreover, at every structural state, *every* execution that respects slot
order (with arbitrary order inside the head slot) is safe. This quantification
is what makes the certificate an enforceable partial order rather than a saved
example schedule.

**Proof architecture.** Induct on the planned trace. Structural steps use
Theorem 1 or its slot-level same-slot coarsening form. Drops use positive
relaxation and current restriction preservation. Prepare uses the tail theorem
and the existing `prepare_preserves_wf_ac`/`prepare_preserves_active_exact`.
Ticket steps use `ticketStep_auth_eq` and `ticketStep_binding_eq`. The final
effect theorem reuses `step_attempt_safe` and `concrete_trace_authority_safety`.

This theorem does not allow unrelated durable promotion, capacity loss, fresh
Reserve into a planned owner, cross-slot Merge, or epoch rebinding. Such a step
must supply an exact transport proof, install a newly checked plan/seal, or be
rejected.

## 8. Operation-by-operation certificate semantics

`Preserve` below means the remaining plan projection is unchanged;
`Transport` creates a checked child certificate; `Invalidate` means the old
certificate cannot gate another Prepare; `Recompute` runs prefix checking or
peeling on the new instance. Exact-batch semantics never silently treats a
drop as success.

| Lifecycle operation | Positive schedule certificate | Negative core certificate | Seal certificate | Required rule |
|---|---|---|---|---|
| Checkpoint / reconstruct values | **Preserve** | **Preserve** | **Preserve** | The authority-plan projection is outside the snapshot domain. |
| Choice Fork | **Transport** when fragments inherit one slot, target owners are slot-pure, and both aggregate bounds hold; expand the slot into one contiguous block | Preserve only if the core footprint is untouched or an exact/strengthening rename is proved; otherwise recompute | Transport under the same slot conditions | Current canonical projection plus `Transfer` gives full-load conservation; add batch/slot agreement. |
| Parallel Fork | Same as Choice Fork; topology exclusivity is irrelevant to the singleton support proof after source validation | Same as Choice Fork | Same as Choice Fork | Demands, not the fork verb, control schedule transport. |
| Replacing Restore | **Transport** as a fresh-epoch rename/refinement; never preserve the old epoch binding byte-for-byte | Exact rename/strengthening may transport; conservative loss requires recompute | Transport if the replacement retains the slot and batch conditions | Old owner epoch closes; child certificate binds the fresh restored epoch. |
| Live Restore | **Transport** by refining the parent slot into old/restored descendants; enforce one contiguous block | Generally recompute because splitting can dissolve a dead core | Transport when all live descendants retain the same slot and aggregate bounds | OR lineage alone is not enough; batch and slot provenance are required. |
| Simulation Merge | Transport **only** with an additional slot-purity and per-slot conservation certificate | Transport only under explicit strengthening | Same-slot transport may be valid; cross-slot requires new admission | Existing load simulation is insufficient; the four-owner counterexample applies. |
| Direct Merge | Normally **invalidate and recompute**; it has no source projection. A separate slot-refinement proof may recover transport | Normally recompute | Re-admit target seal | Direct target AC says nothing about source schedule continuity. |
| Same-slot coarsening Merge | **Transport** if all merged owners already share a slot and slot aggregate bounds remain valid | Recompute unless strengthening holds | **Transport** within that slot | This is the safe coarsening boundary. |
| Cross-slot Merge/rebinding | **Invalidate; recompute or seal** | Recompute | Recompute/re-admit | A target owner cannot carry two ordered phases under the simple slot discipline. |
| Select | Transport by explicitly deleting losing groups/slots; invalidate if the API still promises the exact original batch | A core avoiding all deleted owners may preserve; otherwise recompute | Transport only for an explicitly reduced objective; otherwise invalidate | Selection cannot delete `D`, tickets, or receipts. |
| Abort | Same as Select | Same as Select | Same as Select | Dropping work is a visible semantic change, not hidden certificate repair. |
| Revoke | Remove affected *tentative* groups and transport the remainder as a relaxation, or invalidate an exact-batch promise | Usually recompute; preserve only if the certified core and witness weights are unaffected/strengthened | Recompute or explicitly shrink before use | Already prepared tickets remain dispatchable; no fresh Prepare under the closed grant. |
| Planned Prepare of a head-slot member | **Transport/advance** atomically to a new tail certificate | A core certificate does not authorize this action; consume/replan/seal | Serial prefix advances, or final atomic seal is consumed | Version/head check, state update, ticket install, and tail-head install are one durable step. |
| Unplanned or later-slot Prepare | **Reject**, or invalidate and recompute before any dispatch | Recompute | Recompute | Otherwise the saved plan is merely advisory. |
| Dispatch | **Preserve** remaining plan; certificate is not consulted | Preserve | Preserve/consumed ticket | Check only the prepared durable ticket. |
| Crash | **Preserve** | Preserve | Preserve | Only inflight tickets become uncertain. |
| Retry | **Preserve** | Preserve | Preserve | Reuse the same `(effect_id, claim_id)`; no plan-version check. |
| Settle | **Preserve** | Preserve | Preserve | Current semantics does not refund `D`; reclamation would be a new authority transition. |

Fresh Reserve is not in the requested list but is important: Reserve into a
planned owner changes its full `r` load. It may transport only if the claim is
assigned the same slot and remains within a deliberately reserved `R` budget;
otherwise it invalidates the plan. Unrelated Reserve is harmless to singleton
deadlines but still needs the normal AC check.

## 9. What is necessary, sufficient, and not proved

### Necessary for the proposed compositional theorem

- nonnegative demand and `p<=r`;
- source owner support and downward closure, so singleton support is exact;
- fixed immutable demand/binding for each claim lineage;
- stable slot inheritance across claim fragmentation;
- slot purity of every current planned owner;
- full-load and batch-load aggregate conservation per slot;
- enforced slot order, not merely recorded order;
- epoch freshness/monotonicity and no owner-name resurrection;
- an atomic Prepare linearization that installs tickets and advances the plan;
- complete mediation only for the final concrete effect theorem.

### Sufficient but not necessary for one concrete target

- componentwise `p'<=p` and `h'>=h`;
- the two per-slot aggregate bounds;
- requiring every topology change to preserve the entire contract hash.

A direct check of (4) can accept more transformations. A changed global
contract hash is not itself unsafe when the plan footprint is transported.

### Explicit nonclaims

The certificate does not prove natural-language intent, truthful weights,
correct semantic merge provenance, complete mediation, sink honesty,
exactly-once behavior for a non-idempotent nonqueryable sink, confidentiality,
or liveness. It proves that admitted planned Prepare steps retain enough
authority and that every dispatched protected operation was sealed first.

## 10. Lean feasibility and minimal mechanization plan

### 10.1 Reuse

The current development already supplies:

- `PrepareOK`, `prepareState`, exact cleanup, and Prepare/active preservation;
- canonical Fork/Restore builders and exact singleton projections;
- claim-level transfer provenance, grant agreement, and fiber demand;
- durable-load preservation for topology steps;
- separate simulation/direct Merge modes;
- stable ticket/receipt bindings and attempt safety; and
- full Step/Trace preservation.

The new proof should be a new module, not a modification of the failed Step
0006 serialization draft.

### 10.2 Suggested definitions

```lean
structure SlotPlan (Coord Claim Branch Slot : Type*) where
  slots       : List Slot
  nodup       : slots.Nodup
  batch       : Finset Claim
  slotOf      : Claim -> Option Slot
  pBudget     : Slot -> Coord -> Nat
  rBudget     : Slot -> Coord -> Nat
  phase       : Nat

def OwnerSlotPure (A : LifecycleState ...) (chi : SlotPlan ...) : Prop := ...
def SlotLoadsBounded (A : LifecycleState ...) (chi : SlotPlan ...) : Prop := ...
def PlanValid (A : LifecycleState ...) (chi : SlotPlan ...) : Prop := ...

structure SlotTransferOK (A : LifecycleState ...) (tr : Transfer ...)
    (chi chi' : SlotPlan ...) : Prop where
  batch_refines : ...
  slot_agrees   : forall c' c, tr.rho c' = some c ->
                    chi'.slotOf c' = chi.slotOf c
  owner_pure    : OwnerSlotPure (target ...) chi'
  p_bound       : ...
  r_bound       : ...
```

Hashes and CAS should not enter the mathematical core. Model a controller
`PlanHead` with equality; prove the checker updates it atomically; hash that
record in the adapter.

### 10.3 Theorem order

1. `singleton_support_iff_deadline` over the current `preparedCore` quantities;
2. `block_expansion_safe`, independent of lifecycle syntax;
3. `canonical_transfer_implies_slot_bounds`, using
   `Transfer.fiber_demand` and `BatchRefines`;
4. `prepare_head_advances_plan`, invoking the actual `PrepareOK` and cleanup;
5. `same_slot_merge_transports`; and
6. `planned_trace_preserves`, reusing `Step`/`Trace` for WF, AC, epochs,
   terminal IDs, and ticket safety.

The first two should be modest finite-sum proofs. The third is the main
reindexing proof and is likely the hardest: it must sum claim fibers by source
slot without double counting. The fourth must prove required tail owners are
not in `unsupportedOwners`; the previous failed draft showed this is proof
engineering, not a mathematical counterexample. The trace theorem is then a
routine induction over a deliberately small `PlannedStep` relation.

### 10.4 Feasibility assessment

This is feasible in Lean 4 with the current finite carriers. A focused
mechanization is roughly:

- 150--250 lines for the abstract block theorem and exact test;
- 250--450 lines for aggregation from `Transfer` and canonical operations;
- 250--450 lines for planned Prepare/tail and the annotated trace; and
- 100--200 lines of positive/negative counterexamples and named controls.

The main risk is not theorem truth but state duplication: recomputing owner and
slot sums through `targetStatus` may cause substantial `Finset` reindexing.
Define reusable slot-load lemmas before attempting the trace theorem. Do not
encode cryptographic hashes, real allocation, or arbitrary direct Merge in the
first proof gate.

## 11. Novelty and paper architecture

Version CAS, monotone deadlines, peeling, antimatroids, AND/OR precedence, and
dynamic dependency graphs are established ideas. The defensible delta is the
following closed package:

1. conditional-to-durable authority induces owner deadlines;
2. a checked schedule compiles owners into stable ordered lineage slots;
3. the existing authority transfer proof lifts to schedule preservation under
   arbitrary-depth Fork/Restore refinement;
4. Prepare atomically advances the plan and seals stable tickets;
5. same-slot versus cross-slot Merge is an exact runtime boundary, with a
   simulation-certified counterexample on the unsafe side; and
6. the resulting planned trace refines the real crash-aware effect gate.

This supports an industrial API:

```text
PlanSafe(schedule_certificate)
PlanImpossible(core_certificate, seal_options)
PlanWithFinalSeal(schedule_prefix, seal_certificate)
Transported(child_certificate, transition_certificate)
ReplanRequired(reason, counterexample_or_core)
```

The smallest compelling evaluation would exercise real native Fork plus
client-owned dispatch, retain slot/version/epoch fields, and demonstrate:

- several depths of conservative refinement without re-running peeling;
- rejection/re-planning of the cross-slot Merge counterexample;
- head Prepare and tail advancement across crashes;
- successful Dispatch after intervening Revoke from an already prepared
  ticket; and
- zero later-slot Prepare before its slot phase.

No broad agent benchmark is required. Real traces motivate the workload and
missing telemetry; the contribution is the theorem, checker, and narrow
dispatch-boundary refinement.

## Bottom line

The single-step fiber theorem is true, useful, and mostly supported by the
existing Lean transfer machinery. Its stronger form is the right Step 0007
target:

> Preserve a partial order over immutable authority lineages, not a list of
> mutable branch names. Fork and Restore refine one slot; restriction deletes
> a slot; same-slot Merge coarsens it; Prepare consumes the head phase and
> seals tickets. Cross-slot Merge changes the schedule problem and must be
> re-planned or sealed.

That theorem connects the previously static serial-or-seal algorithm to the
actual agent lifecycle and identifies a concrete extension to the current
`Transfer` checker. It is materially different from presenting versioning,
monotonicity, or peeling as new.
