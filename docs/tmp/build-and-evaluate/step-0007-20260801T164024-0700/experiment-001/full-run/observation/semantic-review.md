# Semantic review of the observation lower bound

## Verdict

The current `PlanExamples.lean` supports a usable headline result, provided
the paper states the claim at exactly the mechanized scope:

> For one actual simulation-admitted cross-slot Merge and one fixed local
> observation footprint, every deterministic Boolean decision function must
> either reuse the old plan on the plan-invalid target or reject its
> plan-valid source counterpart.

This is a pair-specific information lower bound.  It is not a universal lower
bound for all versioning schemes, and it does not show that the Merge target
violates the repository's base authority invariants.

Invocation 05 exits successfully.  The printed dependencies of the audited
theorems are only `propext`, `Classical.choice`, and `Quot.sound`; there is no
`sorryAx`, `native_decide`, custom axiom, `sorry`, or `admit` in the module.

## 1. The negative history is an actual Merge witness

The example does not postulate an arbitrary target or accept a caller-provided
target-safety certificate:

- `merged` is definitionally `crossSlotMerge.target source`.
- `cross_slot_simulation_admitted` is a closed kernel computation proving the
  repository checker
  `MergeCheck.simulationAdmission source crossSlotMerge crossSlotProject = true`.
- `actual_cross_slot_merge` constructs the transition with the real
  `Step.simulationMerge` constructor.
- `merged_lwf_ac` applies the repository's
  `simulation_merge_preserves_wf_ac` theorem, so the target still satisfies
  `LWF`, `AC`, and `ActiveExact`.

Consequently, the counterexample is strong in the intended way: ordinary
Merge admission and base authority safety permit the transformation, while
reuse of the old promotion plan fails its additional semantic condition.
The paper must call the target **old-plan-transport-invalid**, not simply
"unsafe."  In the repository's base safety sense, the target is proved safe.

## 2. The continuity judgment is not a self-authenticated flag

`checkSlotDeadlines` and `checkOwnerPure` compute from lifecycle state, the
scheduled batch, and root-slot metadata.  The module proves
`checkSlotDeadlines_sound`, `checkOwnerPure_sound`, and
`PlanContinuity.sound`, and the lower-bound theorem is stated using the
semantic propositions `SlotDeadlines` and `OwnerPure`, rather than treating a
Boolean validity bit as truth.

The root map remains trusted plan metadata.  That is appropriate only under
the paper's controller model: the source plan authenticates its immutable
roots, and target roots are computed through checked `Transfer.rho`.
The concrete target follows this discipline through `mergedRootSlot`; the
Merge caller does not supply a replacement target-slot map.  This example by
itself does not prove that an arbitrary runtime always supplies the authentic
source root map, so that obligation must remain explicit in the general
controller theorem and implementation story.

## 3. The decision-function quantification is sound but narrow

`version_observation_lower_bound` genuinely quantifies over every
`f : LocalAuthObs -> Bool`.  Equality of `safeLocalObs` and `unsafeLocalObs`
forces the same result, and Boolean case analysis yields exactly the two
outcomes:

1. `f` returns `true` on the plan-invalid Merge target; or
2. `f` returns `false` on the plan-valid source.

There is no quantifier swap or hidden classifier premise.  The interpretation
does assume `true` means plan reuse/acceptance, and the scope is limited to
total deterministic classifiers whose only input is the frozen
`LocalAuthObs`.  It says nothing about a classifier with extra topology
metadata, private mutable state, or randomness, nor does it quantify over all
histories or all observation schemas.

The theorem name may retain "version" for continuity with the plan, but prose
should make clear that `LocalAuthObs` contains more than a scalar version: it
also contains capacity, durable load, and masked per-scheduled-claim metadata.

## 4. Which semantic field is decisive in this witness

For the source and merged histories, the inherited root of every retained
claim is unchanged because `crossSlotTransfer.rho` is the identity.  Thus the
`rootLineage` field is equal in this particular pair.  The proof of
`semantic_observation_distinguishes_cross_slot` distinguishes the histories
using the scheduled co-owner relation: claims `a` and `c` have distinct source
owners and the same target owner `x`.

Therefore this module supports the following statement:

> The frozen local footprint is insufficient; a topology-sensitive semantic
> dependency, interpreted against authenticated immutable roots, separates
> the actual cross-slot pair.

It does **not** separately prove that root lineage is an information-theoretic
necessary field, that every field in `SemanticObs` is minimal, or that owner
topology and root lineage are each independently necessary.  A separate
same-current-topology pair whose safety differs only by same-slot versus
cross-slot lineage would be needed for a lower bound on root lineage itself.

## 5. `SemanticObs` is not a globally complete decision interface

`SemanticObs.rootLineage` is masked outside `oldBatch`, and
`scheduledOwnerTopology` relates only scheduled claims.  In contrast,
`tentativeSlotLoad` and `OwnerPure` quantify over ambient tentative claims as
well; the padding claims in this fixture are examples of such ambient load.

Accordingly, the current theorem proves that `SemanticObs` separates the two
chosen pairs.  It does not prove that equality of `SemanticObs` preserves
`PlanContinuity` for arbitrary states, or that a complete transport checker
can always be implemented from these fields alone.  General completeness
would require observing an adequate aggregate of ambient slot load and
owner/root topology, or narrowing the semantic predicate with a separately
justified invariant.

## 6. Global invalidation is a modeled controller wrapper

`irrelevantMutation` is a real
`Step.core (CoreStep.restriction ...)` lifecycle transition and is proved to
leave the old plan valid.  The revision change from 40 to 41, however, is
manually represented by `VersionedController`; the base `Step` relation has
no controller-revision field and does not prove that increment itself.

Safe wording is:

> We model a global invalidator that increments its revision on this actual
> lifecycle mutation, and therefore rejects a mutation whose plan preservation
> is independently proved.

The stronger wording "the actual Step advances the global revision" is not
mechanized here.

## 7. Additional non-claims

- `merged_x_then_y_unsafe` and `merged_y_then_x_unsafe` refute the module's
  finite next-owner headroom predicate for the two possible owner orders.
  They are not yet theorems that every real `Prepare` trace is impossible.
- The self-contained `SlotDeadlines /\ OwnerPure` predicate is not yet the
  full authoritative `ControllerPlan` validity judgment.  The general plan
  module must supply that connection before the paper describes this as a
  full-trace preservation theorem.
- `semantic_observation_ignores_irrelevant` establishes precision for one
  actual irrelevant restriction, not for every unrelated state mutation.

Within these boundaries, the observation theorem is suitable as headline
evidence against dependency caches that observe immutable per-claim resource
and credential fields but erase plan-relevant owner topology.
