# Independent hostile plan review, round 2: Step 0007 Experiment 001

Review date: 2026-08-01 (America/Vancouver)

Scope: independent pre-execution review of the revised `plan.md`. I read the
entire revised plan, the round-1 review, all three Step 0007 reports, the Step
0006 result review, and the relevant actual definitions and theorems in
`Model.lean`, `Checker.lean`, `Lifecycle.lean`, `Transfer.lean`,
`Topology.lean`, `Merge.lean`, `Step.lean`, and `Trace.lean`. I did not run a
Lean experiment and did not edit the plan, paper, canonical files, or existing
Lean sources.

## Verdict

```text
verdict: ACCEPT
execution authorized: yes
review round: 2
scientific role if every frozen positive gate passes: decisive theory evidence
scientific role if the observation theorem fails: supporting theory evidence
remaining blockers: none
```

Revision 2 repairs every round-1 blocker without changing the research
question. The plan now specifies a noncircular extended controller state, a
computed transition grammar, an actual lifecycle projection, an honest
Prepare-to-ticket boundary, and a relative observation lower bound. It does not
put target safety into a certificate or confuse a successful run closure with
positive theorem support.

Acceptance authorizes only the frozen three-attempt preflight and, if that
preflight succeeds, the reviewed full run. It does not prejudge theorem truth,
novelty acceptance by CSF, or concurrent linearizability of the adapter.

## Round-1 must-fix audit

### 1. Computed root slots: repaired

The authoritative plan defines a partial root-slot map over every current
tentative claim. Every tentative claim of a scheduled source owner receives
that owner's root slot, including non-batch claims charged by `R_i`; unrelated
owners receive `none`. A target map is not supplied. It is computed by

```text
rootSlot'(c') = rootSlot(c)  if rho(c') = some c,
rootSlot'(c') = none         otherwise.
```

This composes through arbitrary transfer depth. Owner purity is checked from
the computed target claims: mixing two planned roots, or mixing a planned root
with `none`, rejects transport. Thus “same-slot Merge” is a derived property,
not a caller label or a free `SlotAgrees` premise.

This matches the actual transfer interface. `Transfer.rho` and `owner` are
finite data; `checkTransferCore` proves exact domains, source tentativeness,
provenance, grant agreement, and fiber demand. Canonical projection adds the
checked owner relation. No existing transfer checker emits a free target slot
map.

### 2. Exact remaining/prepared/withdrawn lineage: repaired

The child batch is computed from the current batch and checked transfer:

```text
U' = { c' | exists c in U, rho(c') = some c }.
```

The plan now includes two distinct forms of accounting:

- an authoritative discrete per-root lineage-leaf partition into `remaining`,
  `prepared`, and `withdrawn`; and
- componentwise demand ledgers `B`, `E`, and `W`.

The discrete partition is load-bearing: it keeps zero-demand claims visible,
allows a fragmented root to have leaves in different terminal phases, and
prevents an empty vector from being mistaken for an empty batch. The cursor and
next group are selected by nonempty remaining `Finset`s, not by `B_i != 0`.

The vector update is computed and noncircular. A checked transfer first derives
`B'_i <= B_i`; only then it defines, componentwise,

```text
delta_i = B_i - B'_i
W'_i = W_i + delta_i.
```

Because the inequality is already proved, natural subtraction gives
`B'_i + delta_i = B_i`, so the old equality
`B_i + E_i + W_i = P_i` derives the new equality
`B'_i + E_i + W'_i = P_i`. Neither `delta` nor `W'` is supplied by an adapter.
Restriction and Revoke use the same computed loss update. This fixes the
round-1 `U' = empty` loophole.

### 3. Pre-Prepare effect binding: honestly removed

The frozen hypothesis is now about a fixed **claim batch reserving authority for
future effects**, not a preassigned effect batch. Before Prepare, the theorem
preserves claims, grants, roots, slots, and batch lineage. It does not assert an
operation-to-claim intent that the current LTS cannot observe.

At `PreparePlanned`, a finite checker validates a fresh offered assignment and
derives exactly the actual `PrepareOK.assigned_mem`, `covered`,
`assignment_injective`, and `fresh` fields. The non-rebindable logical operation
identity begins only when actual `prepareState` installs its ticket. This is
faithful to `LifecycleState`, whose `opClaim` is derived solely from tickets and
receipts.

Consequently, this experiment must not later be described as preserving
natural-language effect intent through claim fragmentation. It proves
claim/resource-authority continuity until Prepare and stable logical binding
after Prepare. The plan already makes that narrower claim.

### 4. Authoritative head and atomic `PreparePlanned`: repaired

The formal state is explicitly
`ControllerState = (LifecycleState, authoritative plan)`. The plan is unique
durable controller state outside the reconstructable workspace and is not an
agent-supplied certificate. Checkpoint cannot restore it. Structural operations
compare the current head and compute a child head; they cannot install a saved
historical plan.

`PreparePlanned` is one abstract transition that checks the current head and
live assignment premises, constructs actual `PrepareOK`, projects on the
lifecycle component to `CoreStep.prepare` and exact `prepareState`, moves demand
to `E`, moves leaves to the prepared ledger, advances the cursor/head, and
installs prepared tickets. The constructor audit explicitly forbids target
`LWF`, `AC`, `ActiveExact`, `PrepareOK`, `PlanValid`, residual safety, and
next-owner readiness as premises.

The plan correctly limits this result to a sequential atomic specification.
The natural-number head does not prove SQLite linearizability; that remains a
separate implementation obligation in the post-proof adapter pilot.

### 5. Ticket retry semantics: repaired

The plan no longer infers one physical attempt or exactly-once external
execution. It claims one stable, non-rebindable logical operation identity,
durable-before-attempt, and no need to recheck the consumed plan at Dispatch.

This exactly matches the actual LTS. `TicketStep.dispatch` moves `prepared` to
`inflight`; `retry` may emit further attempts from `inflight` or `uncertain`;
crash changes `inflight` to `uncertain`; settle moves the same binding to a
receipt. `ticketStep_auth_eq`, `ticketStep_binding_eq`, and
`step_attempt_safe` support the narrow claim. Concrete resource safety still
requires complete mediation and the aggregate sink-outcome bound in
`Trace.lean`.

### 6. Complete typed residual invariant: repaired

For every coordinate and slot, the plan freezes

```text
d_t = d_0 + sum_i E_i
L_i + E_i <= R_i
B_i + E_i + W_i = P_i.
```

Here `L_i` includes all live tentative demand in the slot, including non-batch
claims; `B_i` is only the remaining fixed claim-batch demand; `E_i` is actual
prepared batch demand; and `W_i` is computed withdrawn demand. The discrete
leaf partition handles identity and zero-demand cases that these vector
equations cannot express.

The durable-load equality is justified for the frozen positive grammar:
canonical topology and Merge preserve durable load, restriction and Revoke do
not delete durable claims, ticket steps preserve `auth`, and planned Prepare is
the only admitted durable-load increase. Unplanned Prepare, capacity loss,
unmatched durable increase, and fresh Reserve into a planned slot are outside
the preserving relation and must invalidate or replan.

The source of each real `PrepareOK` field is now explicit: nonempty claim group
from the remaining batch `Finset`; tentative/open/grant facts from source
`LWF` plus plan validity; assignment properties from the finite assignment
checker; and `base` from the schedule arithmetic. No target readiness premise
is permitted.

### 7. Quantified observation novelty theorem: repaired and formalizable

The observation claim is now frozen narrowly enough to mechanize. `LocalAuthObs`
contains the offered old plan ID, capacity, durable load, and each scheduled
claim's ID, demand, grant, coarse lifecycle phase, and grant epoch. It
deliberately erases tentative owner, branch-correlation contract, transfer root,
and owner-slot grouping.

The required actual-model witness is substantive even though the final
decision-function lemma is elementary:

1. construct a plan-safe current history and a simulation-admitted cross-slot
   coarsening with equal `LocalAuthObs`;
2. prove that the old plan is valid only in the safe history;
3. quantify over every `f : LocalAuthObs -> Bool`; equality forces the same
   answer, so `f` either accepts the invalid history or rejects the valid one;
4. separately show that equality of a whole-controller version rejects a
   plan-preserving mutation confined to an unplanned `none`-slot owner; and
5. show that computed root/batch lineage plus the plan-relevant topology
   projection distinguishes both pairs.

The cross-slot pair is faithful to the existing Merge model: retained claim
IDs may keep the same demand, grant, grant epoch, and coarse tentative phase
while `MergeDescriptor.transfer.owner`, branch epochs, and the explicit target
contract change. `MergeCheck.simulationAdmission` can accept such a target even
though the old slot order is no longer valid.

This is an information lower bound only for the frozen erased footprint. It
does not prove that every per-object version scheme ignores topology, and it is
not a universal cache lower bound. The plan says so explicitly. Within that
scope, the theorem directly answers the otherwise load-bearing “ordinary cache
invalidation plus OCC” objection. Requiring it for decisive classification is
scientifically appropriate.

### 8. Three-attempt preflight: repaired

The preflight is now a thin vertical lifecycle path, not most of the full
theorem. It requires one actual canonical transfer, one computed `R`/batch
bound, one authoritative-head `PreparePlanned` that constructs real
`PrepareOK` and exact `prepareState`, one plan-stuttering Revoke/topology step,
and one actual ticket Dispatch. The general block theorem, second refinement,
same-slot Merge, observation pair, and full cross-slot counterexample are
deferred to the full run.

This slice is still difficult, but each element is necessary to demonstrate
that the actual path exists; reducing it to a generic list lemma would no longer
preflight the admitted experiment. The plan defines one attempt as one retained
end-to-end Lean invocation against one frozen snapshot and counts hidden editor
or extra Lean elaboration invocations. The maximum of three is unambiguous.

### 9. Run completion versus positive support: repaired

Run closure now means terminal, retained, independently reviewed evidence,
including honest failure or unattempted rows. It is explicitly not positive
evidence.

Positive support separately requires every load-bearing bridge: computed root
and batch accounting, actual atomic Prepare/head/ticket projection, arbitrary
finite planned-trace preservation, the simulation-admitted cross-slot witness,
the post-Prepare ticket theorem, the quantified observation lower bound, clean
build/audit/kernel replay, and an independent circularity audit. A result
reviewer may classify a missing row but cannot waive it into positive support.
The adapter pilot is supporting feasibility evidence and cannot rescue a
missing formal bridge.

## Actual-model connection audit

The proposed theorem matrix has a credible path through the current code:

- `Transfer.CoreValid.fiber_demand` and canonical singleton projection supply
  the source-to-target `R` aggregation substrate.
- The computed child batch and per-root ledger add the missing `P`/identity
  layer rather than pretending the base transfer checker already has one.
- `canonicalTarget`, `MergeDescriptor.target`, `restrictLifecycle`, and
  `revokeState` are computed lifecycle targets, so the extended relation can
  project to actual `Step` constructors.
- `prepareState` performs promotion, exact guard/cleanup, branch closure, and
  ticket installation in one actual target; `PrepareOK` contains no target
  invariant.
- `Step` already proves preservation of lifecycle well-formedness, AC, active
  exactness, terminality, epochs, and existing bindings for its generated
  constructors.
- `TicketStep` and `Trace` already supply the correct retry-aware,
  durable-before-attempt conclusion.

The main proof risks are real rather than hidden: finite-sum reindexing from
claim fibers to roots/owners, cleanup survival for tail groups, the discrete
lineage-leaf update, and construction of a fully checked finite Merge witness.
Failure on these obligations must be reported as inconclusive or contradictory
under the frozen interpretation; it may not be repaired by adding target
invariants to constructors.

## Nonblocking cautions for result review

- The discrete leaf ledger must be a typed computed transition object, not a
  prose label or adapter-provided partition.
- `LocalAuthObs` equality should use a canonical finite representation so that
  ordering artifacts do not manufacture distinguishability.
- The observation theorem supports necessity of topology-sensitive dependency
  for its declared class, not maximal reuse among all possible checkers.
- A proved sequential controller theorem does not establish crash atomicity or
  concurrent CAS linearizability of SQLite without the planned implementation
  evidence.
- Claim refinement reserves resource authority for later fresh operation
  assignment; it does not preserve a preexisting semantic effect intent.

These cautions are already consistent with the frozen plan and do not require a
third plan revision.

## Final decision

The revised plan is scientifically decision-relevant, executable under its
strict attempt budget, connected to the actual lifecycle semantics, and
noncircular at every identified security boundary. It may proceed to the
three-attempt real Lean preflight.

**Verdict: ACCEPT.**
