# Gate-closure review: from one-shot accounting to multi-slot plan invariance

Date: 2026-08-01 (America/Vancouver)

Scope: static review of the accepted Revision-2 plan,
`lean/AuthorityContinuity/Plan.lean`, and the general-plan run report.  This
review did not run Lean and did not change the existing proof modules.

## Bottom line

The current `planned_trace_preserves` is a sound and useful theorem, but it is
not yet the frozen plan-continuity theorem.  It proves arbitrary-length closure
of a deliberately narrow relation under four properties:

1. actual lifecycle `LWF`;
2. actual lifecycle `AC`;
3. actual `ActiveExact`; and
4. the fixed-batch equation `B + E + W = P`.

It does **not** state or preserve a complete plan invariant, connect `R` to the
live lifecycle, account for durable-load growth, derive readiness, advance the
cursor, or cover the accepted restriction/same-slot-Merge grammar.  Since
`currentSlot` never changes and `headGroup` is the whole root-slot batch, an
ordinary valid run can perform at most one planned Prepare.  Thus “arbitrary
finite trace” currently means arbitrary length in the narrow relation, not an
arbitrary multi-slot/multi-Prepare promotion run.

The smallest noncircular closure is to make the schedule theorem a preserved
**source invariant**, not a certificate supplied at each edge.  In particular,
the Prepare constructor must not receive `hbatchP`, `hPfits`, target
`PlanValid`, or target readiness.  A single initial invariant and constructor
preservation must derive every later Prepare bound.

## Why the present root map is insufficient for `L`

The current `leafRoot` update is conditional on membership in the selected
batch.  Consequently it computes lineage for batch children but not for
non-batch tentative children of a scheduled owner.  Defining `L` from it would
silently omit precisely the non-batch demand that `R` is meant to reserve.

The plan needs one root map over **all live tentative authority**, with the
batch ledger as a separate refinement:

```text
rootSlot'(c') = rootSlot(c)  if rho(c') = some c.
```

Prepared/withdrawn historical IDs may retain their old root metadata, while
`L` filters on the target's actual tentative status.  For a valid transfer,
every target tentative ID is in the `rho` domain, so per-source fiber demand
conservation proves the per-root bound for all planned tentative authority,
not merely for the fixed batch.

## Minimal invariant

For a finite ordered set of slots, define from the real lifecycle:

```text
L(A,p,s,k) = sum demand(c,k)
             over actual tentative c with p.rootSlot(c)=some s

B(A,p,s,k) = sum demand(c,k)
             over actual remaining batch leaves rooted at s
```

The raw plan data needs at least:

- immutable source durable load `d0` and capacity `cap0`;
- a finite ordered slot set (a finite linear order is the smallest Lean
  representation; a checked rank is an equivalent runtime encoding);
- `rootSlot` for all tentative claims, not only batch leaves;
- `R`, `P`, `E`, and `W`; and
- the discrete remaining/prepared/withdrawn ledger.

The dynamic invariant is:

```text
DurableEq:  durableLoad(A,k) = d0(k) + sum_s E(s,k)
Envelope:   L(A,p,s,k) + E(s,k) <= R(s,k)
Exact:      B(A,p,s,k) + E(s,k) + W(s,k) = P(s,k)
```

It also needs:

- current remaining leaves are actual tentative claims with a planned root;
- every actual owner is root-pure (including rejection of `some`/`none`
  mixing);
- the source capacity still equals `cap0`;
- `P <= R` and the immutable slot deadline;
- all slots strictly after the first nonempty remaining slot have `E = 0`;
  and
- when there is no remaining slot, all planned Prepare work is exhausted.

The cursor should be **computed**, not accepted as target data: it is the least
ordered slot whose remaining batch `Finset` is nonempty.  This makes
zero-demand leaves visible and makes cursor advancement after Prepare a
definition rather than a target-readiness premise.

## Deriving readiness without a per-edge oracle

Freeze the source schedule condition

```text
Deadline(s,k): d0(k) + sum_{j<s} P(j,k) + R(s,k) <= cap0(k).
```

Let `s` be the computed first nonempty slot and `U` its current nonempty owner
group.  The derivation of the actual `PrepareOK.base` is:

1. `DurableEq` rewrites current durable load to `d0 + sum E`.
2. Cursor phase says every slot after `s` has `E=0`.
3. `Exact` gives `E(j,k) <= P(j,k)` for every earlier slot.
4. `U` is a subset of the actual tentative claims rooted at `s`, hence
   `batchLoad(U,k) <= L(s,k)`.
5. `Envelope` gives `E(s,k) + L(s,k) <= R(s,k)`.
6. `Deadline` and `capacity=cap0` close
   `durableLoad + batchLoad(U) <= capacity`.

This chain produces `promotedLoad <= capacity` and therefore real
`PrepareOK.base`.  No edge supplies `hPfits`, `hbatchP`, target validity, or
next readiness.

To avoid treating `PlanValid` as a per-edge oracle, use the following shape:

```text
PlannedStep.prepare = executable head/assignment/group checks + computed target

actual_step      : PlannedStep S eta S' -> ControllerInv S -> Step ...
preserves_inv    : PlannedStep S eta S' -> ControllerInv S -> ControllerInv S'
planned_trace    : PlannedTrace S S' -> ControllerInv S
                 -> ControllerInv S' and an actual lifecycle trace
```

Only the initial controller invariant is assumed.  The induction result feeds
the next edge.  It is acceptable for the simulation theorem to take the
current invariant; it is not acceptable for a constructor to take the target
invariant or a ready-made `PrepareOK`.

## Smallest Lean decomposition

### 1. `RootLineageAndLoads`

Definitions:

- `tentativeRootClaims`, `L`, `B`, `totalE`;
- computed all-claim `transferRootSlot`;
- `remainingSlots`, computed `cursor`, current root group, and current owner
  group.

Core lemmas:

- owner group is nonempty when a cursor exists;
- current group is a subset of `tentativeRootClaims`;
- group load is bounded by `L`;
- checked transfer gives `L' <= L` independently for every root.

### 2. `ScheduleInvariant`

Definitions/properties:

- `DurableEq`, `Envelope`, `Exact`, `Deadline`, `CursorPhase`;
- capacity stability, remaining-leaf validity, and owner purity;
- combined `PlanInv`.

Core theorem:

- `current_group_promotedLoad_le_capacity : PlanInv A p -> ...` deriving the
  exact arithmetic needed by `PrepareOK.base`.

### 3. `ComputedPlanTransitions`

Each target plan is a function of source plan and actual lifecycle operation.
For Prepare, `afterPrepareGroup` must:

- mark the offered current owner group prepared;
- recompute which tail leaves survived actual `prepareState` cleanup;
- mark cleanup losses withdrawn and compute their `W` delta;
- add exactly the group demand to the current slot's `E`;
- increment the authoritative head; and
- recompute the first-nonempty cursor.

Prove `DurableEq`, `Envelope`, `Exact`, and phase preservation separately;
assemble `PlanInv` only after these source-to-target lemmas exist.  This avoids
one monolithic proof and exposes any genuine cleanup obstruction.

### 4. `PlannedSimulation`

- remove direct `hbatchP` and `hPfits` fields from the new Prepare relation;
- construct real `PrepareOK` using source `LWF`, assignment-check soundness,
  remaining/owner-group validity, and the schedule theorem;
- project to exact `prepareState`/`Step`;
- prove two successive Prepare steps on a two-slot fixture; and
- only then lift to reflexive-transitive closure.

## Durable-load preservation table

The required `DurableEq` step lemmas have direct support in the existing
actual model:

| Planned operation | Actual reason |
|---|---|
| checkpoint | identity |
| canonical Fork/Restore | `Transfer.targetCore_durableLoad` |
| restriction/Revoke | `restrictStateBy_durableLoad` / exact restriction |
| checked same-slot Merge | `MergeStructureValid.transfer` plus `Transfer.targetCore_durableLoad` |
| planned Prepare | `preparedCore_durableLoad` and `rawPromotion_durableLoad_eq_promotedLoad` |
| ticket phase | `ticketStep_auth_eq` |

Only planned Prepare increments `E`; all other positive rules retain it.

## Are restriction and same-slot Merge essential?

They are not logically necessary for the **smallest vertical demonstration**
of two canonical/Prepare rounds.  A canonical-transfer + Prepare-only grammar
can prove the arithmetic core.

They are, however, essential to claim closure of the accepted positive grammar:

- restriction/Revoke is the operation that tests computed withdrawal, tail
  deletion, and `W` rather than mere refinement;
- checked same-slot Merge supplies the positive counterpart to the cross-slot
  negative witness and is necessary for a paper whose headline includes
  transport across Merge.

Therefore the recommended staging is:

1. kernel-check the two-slot/two-Prepare invariant and actual-Step bridge;
2. add computed restriction/Revoke transport;
3. add checked owner-pure same-slot Merge;
4. only then call the full accepted grammar closed.

Omitting stages 2--3 is an honest partial result, not a positive-support gate-4
pass.

## Feasibility and proof risk

The first vertical stage is feasible with moderate Lean effort.  Durable-load
growth is already nearly a rewrite proof.  The main arithmetic proof is finite
sum decomposition around the current slot.  A finite linear order for slots
is materially simpler than a list-plus-cursor proof and is suitable for the
runtime encoding through checked integer ranks.

The highest-risk obligation is not durable arithmetic; it is exact treatment
of `prepareState` cleanup for remaining tail claims.  A faithful implementation
should compute survivors/withdrawals.  A Boolean “tail survives” atom can be a
temporary restricted admission check if its soundness is proved, but it must be
reported as narrowing the grammar and cannot be disguised as general
preservation.

The transfer `L` proof is moderate because it reuses the existing fiberwise
sum pattern.  Restriction is low-to-moderate risk.  Same-slot Merge is moderate:
the load proof reuses transfer conservation, while owner purity needs a finite
checker over the computed target root map.  Full arbitrary-depth discrete
leaf-history partitioning remains a separate higher-risk theorem.

## Classification of the current theorem

`planned_trace_preserves` currently proves:

> Every finite history made from checkpoint, head-checked canonical transfer,
> one-shot current-slot Prepare transitions whose readiness bounds are supplied
> locally, and ticket steps projects to the real lifecycle LTS and preserves
> lifecycle safety plus fixed-batch `B/E/W=P` accounting.

It does not prove:

- that `R` reserves all batch and non-batch tentative authority;
- `durableLoad = d0 + sum E`;
- `L + E <= R`;
- readiness derived from the source plan;
- first-nonempty cursor advancement or two planned Prepare rounds;
- semantic consistency of all `remaining` leaves after Prepare cleanup;
- restriction/Revoke or safe same-slot Merge transport; or
- the complete accepted `PlanValid`/stable-binding/next-readiness conclusion.

The appropriate scientific classification is **kernel-checked supporting
transport/accounting lemma**, not yet the decisive multi-round
plan-continuity theorem and not yet a positive-support gate-4 pass.
