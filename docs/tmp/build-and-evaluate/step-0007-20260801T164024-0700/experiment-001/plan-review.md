# Independent hostile plan review: Step 0007 Experiment 001

Review date: 2026-08-01 (America/Vancouver)

Scope: pre-execution review of `experiment-001/plan.md`. I read the plan, the
complete closest-work, certificate-semantics, and seal-theory reports, the Step
0006 result review, and the actual definitions and preservation results in
`Transfer.lean`, `Lifecycle.lean`, `Topology.lean`, `Merge.lean`, `Step.lean`,
and `Trace.lean`. I did not run a Lean experiment and did not edit the plan,
paper, canonical documents, or existing Lean sources.

## Verdict

```text
verdict: REVISE
execution authorized: no
scientific direction: promising
current plan validity: blocked by semantic and executability defects
review round: 1
```

The direction is substantially better than the failed Step 0006 serialization
attempt: it tests lifecycle transport of an unconsumed authority plan and the
Prepare-to-ticket boundary, rather than relabeling known static peeling as the
headline. The abstract residual-budget induction is plausible, and the actual
LTS already has unusually good ingredients: computed canonical targets,
claim-fiber demand conservation, exact `prepareState`, monotone epochs and
terminal IDs, stable ticket bindings, and a real ticket-only attempt relation.

The present plan is nevertheless not executable as approved. Its most
important security statements currently depend on objects that the actual LTS
does not contain: an authoritative pre-Prepare effect assignment, an
unrollbackable plan head/version, and a non-forgeable root-slot assignment.
Without defining where those objects live and how target values are computed,
the desired theorem can be obtained by putting the answer in the certificate
or in the constructors of `PlannedStep`. In addition, the preflight is much too
broad for a maximum of three real build attempts, and the positive result would
still leave the closest-work audit's main novelty objection unanswered.

The defects below are repairable without abandoning the RQ, so `REVISE` is more
appropriate than `REJECT`. They are blockers, not optional requests for a wider
evaluation.

## What is already logically sound

### 1. The residual arithmetic has the right basic shape

Let `E_i` be the componentwise demand from the fixed batch already Prepared
from source slot `i`. Subject to no unmatched durable promotion or capacity
loss, the intended invariant can be written as

```text
current durable load = source durable load + sum_i E_i
remaining tentative load in slot i + E_i <= R_i
remaining fixed-batch load in slot i + E_i <= P_i.
```

This is the correct cancellation pattern for slot-major execution. A Prepare
of demand `q` moves `q` from both live sums into `E_i`, while the actual
durable load increases by the same `q`. Deletion can make the inequalities
strict. The source prefix inequality then proves the deadline for a remaining
owner after subtracting already consumed earlier-slot and same-slot demand.

The plan should retain this idea. It must, however, define `E_i` as a vector of
Prepared demand from the named fixed batch, not as an untyped scalar
`consumed_i`, and it must state the durable-load equation explicitly. The
current two inequalities alone do not rule out an unaccounted durable claim.

### 2. The claim-level `R` bridge is real

`Transfer.CoreValid.fiber_demand` is emitted by the Boolean transfer checker;
it is not a caller-supplied target invariant. For canonical operations,
`Valid.owner_projection` plus the exact singleton projection can associate a
target tentative claim with a unique source owner. Summing the checked claim
fibers can therefore derive owner/slot tentative-load bounds. The proposed
`canonical_transfer_slot_bounds` theorem has genuine content and is not merely
an invocation of target `AC`.

### 3. Prepare-to-ticket is a real boundary in the present LTS

`prepareState` moves the chosen `U` to the exact `preparedCore` and installs
prepared tickets in one abstract transition. `TicketStep.dispatch` checks only
`A.tickets e = some <c, prepared>`; it does not inspect a grant, branch epoch,
certificate, or plan version. Revoke and topology targets preserve durable
claims and ticket maps. `ticketStep_auth_eq`, `ticketStep_binding_eq`, and
`step_attempt_safe` therefore support the narrow statement:

> Once the actual Prepare transition has durably bound an operation to a
> durable claim, later admitted topology/revocation changes do not require the
> old unconsumed plan to authorize a ticket attempt.

This is the right semantic distinction from a Dispatch-time freshness check.

### 4. Cross-slot coarsening is a valid boundary witness

The `K=4` source instance with owners

```text
a:(p=1,r=1), b:(p=1,r=2), c:(p=1,r=2), d:(p=1,r=1)
```

has the safe order `a,b,c,d`. Coarsening `a,c` into `x` and `b,d` into `y`
gives `x,y:(p=2,r=3)`, so either second target owner sees predecessor load two
against headroom one. The reports also explain how a source contract containing
`{a,c}` and `{b,d}` can make the target choice Merge simulation-admitted. This
is a suitable demonstration that base `LWF`/`AC` preservation is weaker than
plan continuity.

## Blocking semantic defects

### Must fix 1: slot identity must be computed, not certified by the adapter

The reports propose a premise resembling

```text
SlotAgrees(slot, rho) :=
  forall c' c, rho c' = some c -> slot'(c') = slot(c).
```

As a free proposition on caller-supplied `slot'`, this is too weak a security
boundary. An adapter could relabel target claims into a convenient common slot
and then prove conservation relative to its own labels. The theorem would be
sound only because the certificate asserted the desired history semantics.

The child slot map must instead be a computed partial function:

```text
rootSlot'(c') = rootSlot(c) when rho(c') = some c.
```

It should be derived from the authoritative parent plan and the checked
`Transfer.rho`, with no independently supplied target slot value. Composition
must retain the immutable root slot through arbitrary depth. Every target
tentative claim has a source under `CoreValid`, so the implementation can then
check owner purity by inspecting all claims of a target owner. A target owner
carrying claims from two distinct `Some` root slots, or mixing a planned slot
with an unplanned `None` lineage, must be rejected. Same-slot Merge is a
consequence of this computed equality; it cannot be an operation label or
trusted Boolean.

The plan must also say whether `rootSlot` is defined for every tentative source
claim or only claims owned by a source batch owner. The clean formulation is a
partial map over every tentative claim: every claim of a scheduled source
owner receives that owner's slot because `R_i` includes the owner's *entire*
tentative bundle; unrelated owners receive `none`. This prevents an unrelated
tentative claim from being merged into a planned owner without being charged.

### Must fix 2: `BatchRefines` needs lineage accounting, not only target-to-source inclusion

The one-way condition

```text
forall c' in U', exists c in U, rho c' = some c
```

combined with `fiber_demand` is enough to derive a numerical upper bound on
target promotion load. It is not enough to justify the phrase “transport the
fixed batch.” In particular, `U' = empty` satisfies it and silently declares
all unconsumed work gone. It also does not distinguish intentional withdrawal
from accidental loss after restriction or Revoke.

The revised plan needs an explicit conservation/accounting judgment for every
source batch lineage. Each source batch claim must be exactly one of:

- already consumed into the per-slot `E` ledger;
- represented by its current target fragments;
- explicitly withdrawn/terminalized by a named drop transition; or
- still retained as the same current claim.

The numerical target sum may be lower because transfer is conservative or a
drop is explicit, but disappearance must be recorded in the transition, not
inferred from an arbitrary smaller `U'`. The child batch and its root lineage
map should be computed from `rho` plus the explicit withdrawal set. This is
also what prevents replaying an old restored batch fragment after its sibling
was consumed.

### Must fix 3: the actual model has no authoritative pre-Prepare effect binding

The hypothesis repeatedly assumes immutable effect bindings before Prepare.
`LifecycleState` has no such field. Before Prepare it contains claim status,
grant, branch/grant epochs, tickets, and receipts. `PrepareOK` accepts any fresh
function `assignment : Operation -> Option Claim` that covers `U` and is
injective on assigned claims. There is no pre-existing fact saying that claim
`c` was intended for operation `e`.

Consequently, a certificate field called `effectBindings` would presently be
self-authenticating: the checker can compare it only with another field in the
same certificate. It cannot establish that an adapter did not substitute an
effect. This is a load-bearing gap, because the proposed novelty explicitly
includes stable effect identity across Fork/Restore/Merge.

The revision must choose one of two honest designs:

1. add an authoritative, durable, non-snapshot intent/assignment ledger to the
   extended controller state, define how it refines across claim fragmentation,
   and require the actual Prepare assignment to equal the current ledger; or
2. remove pre-Prepare effect-binding preservation from the hypothesis and
   claim only claim/grant/slot-plan continuity, with effect identity becoming
   stable at the existing Prepare transition.

The first design is stronger but nontrivial. Fragmentation creates an additional
question that the current plan ignores: one source claim can refine into several
target claims, while `PrepareOK` creates one ticket per promoted target claim.
Are those several claims fragments of one logical effect, several separately
authorized effects, or alternatives from which only one is selected? A checked
effect-refinement relation and an aggregate-effect policy are required before
“immutable effect binding” is meaningful. `SlotAgrees` and demand conservation
do not answer this question.

Whichever design is chosen, `prepare_head_is_ok` must list the exact source of
every non-arithmetic `PrepareOK` field: nonemptiness, member status and open
epochs, assignment coverage, injectivity, and operation freshness. It may
derive `base` from the schedule and `p<=r`; it cannot hide the other fields in
an opaque `PlanValid` proposition.

### Must fix 4: the plan head/version is not yet part of the durable LTS

The current `LifecycleState` and `Step` have no plan head or authority version.
A relation over pairs `(A, chi)` can model one, but only if `chi` is explicitly
the unique authoritative controller state. A pure certificate value can be
copied freely; calling it a “linear capability” does not establish linearity.

The revised plan must define an extended state containing at least the
authoritative root-slot plan, cursor, batch accounting, and monotone head/version.
`PreparePlanned` must be one constructor that:

- compares an offered certificate/head with the authoritative current head;
- derives the actual `PrepareOK` premises;
- projects to exactly `CoreStep.prepare`/`prepareState` on the lifecycle
  component;
- updates the `E` ledger and remaining plan exactly once; and
- installs the new authoritative head in the same abstract transition.

Structural transport steps must likewise compute a child head and invalidate
the old one. Ticket-only steps may stutter on it. No constructor may accept
`PlanValid A' chi'`, target slot bounds, or target next-Prepare readiness as a
premise; those are the induction conclusions.

This extended state must also state its crash/Restore ownership. If the plan
head can be restored from the same workspace snapshot as the agent, a stale
certificate can simply resurrect with it and the CAS story is assumed away.
The plan head must live in the durable authority controller outside the
rollback domain, or the theorem must explicitly model recovery of that head.
The existing `CoreStep.checkpoint` is identity and cannot by itself prove this
property. A sequential `PlannedStep` relation proves rejection of stale steps
only after these storage and atomicity semantics are fixed; it does not prove a
concurrent CAS implementation linearizable merely by mentioning a version.

### Must fix 5: “one-shot ticket” overstates what `TicketStep` proves

The ticket map gives one stable logical operation-to-claim binding, but the
actual LTS permits arbitrarily many `retry` attempt labels from `inflight` or
`uncertain`. `Trace.concrete_trace_authority_safety` therefore assumes an
aggregate sink-outcome bound per stable operation. The model does not prove one
physical external effect or exactly-once execution.

Replace “one-shot effect ticket” with “single logical effect identity and
non-rebindable durable ticket” unless the experiment adds and proves a stronger
provider/idempotency semantics. The positive theorem may prove
durable-before-every-attempt and stable binding. It may not infer at-most-once
external execution from ticket uniqueness. This correction is necessary in the
frozen hypothesis, paper-value story, theorem matrix, and target evidence.

### Must fix 6: make the residual invariant complete and typed

The residual invariant should explicitly quantify componentwise over all
coordinates and distinguish four sets:

- remaining fixed-batch fragments;
- other live tentative claims owned by a planned-slot descendant;
- explicitly withdrawn/terminalized batch fragments; and
- claims already Prepared into durable load.

`R_i` charges the first two sets; `P_i` charges only the first and consumed
fixed-batch claims. Owners with no remaining batch demand but with non-batch
tentative demand still matter to `R_i` and to transfer purity even though they
do not need a nonempty Prepare group. The definition must not accidentally
schedule a zero-`p` group, because actual `PrepareOK.nonempty` forbids an empty
Prepare.

The invariant also needs either the exact durable-load equation above or an
explicit componentwise bound connecting current durable load, source durable
load, and `E`. Merely saying that unrelated durable promotion “invalidates” the
plan is an implementation rule, not a theorem premise. The extended transition
checker must reject it or derive a new plan before it occurs.

## Blocking novelty and decision-value defect

### Must fix 7: the positive result does not yet meet the closest-work gate

The closest-work report concludes that proof-carrying plans, versioned
authorization, OCC, escrow/Prepare, task refinement, authoritative split/join
resources, and phase/resource protocols own every generic ingredient. It says
that the composite result survives as a headline only with an exact/maximal
semantic-transport result or a strong observation lower bound. The current
plan deliberately proves only a sufficient grammar and explicitly disclaims
weakest conditions. Its theorem matrix also omits the proposed observation
lower bound.

Thus Lean success under the current plan could still yield only “HTL-style
schedule refinement plus an actual authority-LTS instantiation.” That is useful
supporting mathematics, but it does not resolve the plan's own strongest
reviewer-reject argument. The RQ asks “when may” transport occur, while the
hypothesis establishes only one conservative class.

Before execution, make one of these decisions explicit:

- add the observation theorem to the required matrix: a checker observing only
  global equality is safely overconservative, while one observing only
  per-grant/object versions cannot distinguish an unrelated safe mutation from
  a topology-only co-durability mutation that invalidates the same plan; or
- give a relative-completeness/maximal-reuse theorem for a precisely frozen
  observation footprint; or
- downgrade this experiment from decisive/headline to supporting and state
  that a positive result cannot by itself center RQ2.

A pair of hand-constructed adapter histories is a useful control but is not a
substitute for the quantified observation theorem if the paper makes the
maximality claim.

## Blocking executability defects

### Must fix 8: the three-attempt preflight is unrealistically broad

The preflight currently requires, in one end-to-end gate:

- a general arbitrary-internal-order fiber result;
- an actual canonical refinement and both `R`/`P` aggregation;
- a real `PrepareOK`, exact `prepareState`, cursor advance, and ticket
  inspection;
- a second refinement or checked same-slot coarsening; and
- a fully instantiated simulation-admitted cross-slot Merge dead-core witness.

That is a substantial fraction of the full theorem, not a path preflight. It
is particularly unrealistic after Step 0006 exhausted three attempts on a much
smaller example and failed on constructive finite obligations. Instantiating
`LWF`, `ActiveExact`, both finite transfer checkers, exact Prepare assignments,
and the Merge structural/simulation checker is likely to require ordinary
iterative Lean debugging. A three-build budget makes the current gate more a
test of whether a large proof is written perfectly before elaboration than a
test of the hypothesis.

Keep the maximum of three *preflight* attempts, but reduce the real case to one
thin vertical path:

1. use an already checked minimal source fixture or construct one small
   `LWF`/`AC` state constructively;
2. run one actual canonical transfer and derive one target slot/batch bound;
3. execute one actual `CoreStep.prepare` using a decomposed `PrepareOK` and show
   the authoritative plan head advances while a prepared ticket appears; and
4. dispatch that ticket after one plan-stuttering Revoke or topology step.

The general block theorem, second refinement, same-slot Merge, and full
simulation-admitted cross-slot counterexample belong to the full run. A small
Boolean rejection check may remain in preflight only if it reuses a fixture and
does not require a second proof development. Define an attempt as one retained
terminal invocation of the approved end-to-end command against a frozen source
snapshot; do not hide additional Lean elaboration commands under another name.

### Must fix 9: the completion rule permits success without the central theorem

Current completion item 3 allows the theorem matrix to be “mechanized or every
omitted row classified as failed, refuted, or out of scope.” That is an honest
way to close an experiment, but it is not a positive completion criterion. In
the extreme, every central row could be omitted and the run called technically
complete.

Separate these notions:

- **run completion:** all approved attempts and validations reach a recorded
  terminal result, including failures;
- **positive hypothesis support:** at minimum the computed slot/batch transfer
  bridge, actual plan-head Prepare/tail theorem, arbitrary finite planned-trace
  preservation, cross-slot boundary witness, and post-Prepare ticket theorem
  all kernel-check with the frozen noncircular assumptions;
- **mixed/inconclusive:** any central bridge is missing, or only the abstract
  fiber/list theorem succeeds.

The result reviewer can classify missing rows, but cannot waive a frozen
central row and thereby turn an incomplete theorem into positive support.

The adapter pilot should likewise be labeled supporting feasibility evidence.
Failure to represent native metadata can make the runtime portion
inconclusive, but it should not retroactively invalidate a successfully proved
formal theorem. Conversely, a toy adapter cannot rescue a missing lifecycle
bridge.

## Circularity audit required in the revision

The revised plan should freeze a constructor-by-constructor premise table. At
minimum, the independent result review must reject the formal result if any of
the following appears as a field or constructor premise:

- target `LWF`, target `AC`, target `ActiveExact`, or target `PrepareOK`;
- target `PlanValid`, residual schedule safety, or next-owner readiness;
- an independently chosen child slot/root-lineage map;
- an unaccounted target batch or a Boolean “this mutation is relaxing” flag;
- equality of the offered and authoritative plan head asserted rather than
  checked by the transition; or
- a pre-Prepare effect binding that is compared only with certificate data and
  not with authoritative controller state.

Permitted premises are source invariants, actual successful Boolean checker
outputs, immutable parent plan data, explicit withdrawal events, and primitive
operation facts whose soundness is separately proved. Runtime hashes may
represent equality but may not replace semantic equality in Lean.

## Required revision checklist

Execution may begin after one revised plan satisfies all of the following:

1. Define computed root-slot inheritance over every relevant tentative claim,
   including treatment of unplanned owners; remove free target `SlotAgrees`.
2. Replace one-way `BatchRefines` with computed lineage accounting that
   distinguishes remaining, consumed, and explicitly withdrawn batch work.
3. Either add an authoritative pre-Prepare intent/assignment ledger with
   fragmentation semantics, or remove pre-Prepare effect-binding claims.
4. Define the authoritative nonrollbackable plan-head/version state and an
   atomic `PreparePlanned` that projects to actual `prepareState`; state its
   crash/Restore ownership.
5. Correct “one-shot” to the guarantee actually proved by `TicketStep`, unless
   stronger sink/idempotency semantics are added.
6. State the complete vector residual invariant and the decomposition used to
   construct every `PrepareOK` field.
7. Add a novelty-bearing observation/maximality theorem or downgrade the
   planned scientific role.
8. Reduce the real preflight to a feasible thin vertical slice while retaining
   the maximum-three-attempt rule.
9. Separate terminal run completion from the mandatory theorem subset for a
   positive result.
10. Preserve the current negative controls and actual-LTS connection; do not
    replace them with an abstract list-only theorem.

## Final decision

Do not start Lean Experiment 001 from the current plan. The abstract scheduling
idea is credible, and the actual model is close enough that a focused revision
could produce valuable theory. But without computed slot/batch lineage,
authoritative pre-Prepare assignment and plan-head semantics, the theorem risks
being circular; without a smaller preflight it is unlikely to survive the
three-attempt gate; and without a lower-bound or relative-completeness result a
positive proof does not yet justify the declared decisive novelty role.

**Verdict: REVISE.**
