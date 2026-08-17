# Step 0007 observation and cross-slot Merge result

## Result

The observation/negative suite kernel-checks in
`lean/AuthorityContinuity/PlanExamples.lean` under Lean 4.30.0.  The final
standalone command was:

```text
PATH=/home/yunwei37/.elan/toolchains/leanprover--lean4---v4.30.0/bin:$PATH \
  lake env lean AuthorityContinuity/PlanExamples.lean
```

Invocation 05 exited 0.  The module contains no `sorry`, `admit`, custom
`axiom`, or `native_decide`.  Its printed dependencies are only `propext`,
`Classical.choice`, and `Quot.sound`; no `sorryAx` remains.

## Actual-model witness

The closed fixture uses capacity `K=4`, old slots `a,b,c,d`, scheduled demand
`p=(1,1,1,1)`, and full tentative slot load `r=(1,2,2,1)`.  The source
contract has maximal configurations `{a,c,u}` and `{b,d,u}`, where `u` is an
unplanned zero-demand owner whose root slot is `none`.

`crossSlotTransfer` retains all claim IDs and maps `a,c,cPad` to target owner
`x`, `b,d,bPad` to target owner `y`, and `u` to itself.  `crossSlotMerge` uses
the target choice contract with maximal configurations `{x,u}` and `{y,u}`.
`crossSlotProject` maps `x` back to `{a,c}`, `y` back to `{b,d}`, and preserves
`u`.

The following closed theorems connect the witness to the repository model:

- `source_lwf : source.LWF` and `source_ac : AC source.auth` have no premises.
- `cross_slot_simulation_admitted` proves the actual
  `MergeCheck.simulationAdmission` call returns `true`; it uses kernel
  `decide`, not `native_decide`.
- `actual_cross_slot_merge : Step source .tau merged` is constructed with
  `Step.simulationMerge`.
- `merged_lwf_ac` derives target `LWF`, `AC`, and `ActiveExact` from the
  repository's `simulation_merge_preserves_wf_ac` theorem.

Thus the negative state is not an arbitrary hand-written target: it is the
output of the admitted Merge relation and still satisfies the base safety
invariants.

## Plan-continuity boundary

The module defines an explicit semantic predicate with two parts:

1. `SlotDeadlines` checks the old slot-order headroom inequalities; and
2. `OwnerPure` requires all tentative claims of one current owner to inherit
   the same immutable root slot.

The executable admission functions inspect actual lifecycle fields.
`checkSlotDeadlines_sound`, `checkOwnerPure_sound`, and
`PlanContinuity.sound` connect their Boolean results to these propositions;
there is no caller-provided validity flag.

`source_plan_semantics` proves both semantic properties for the source.
`merged_not_owner_pure` exhibits claims `a` and `c`: both are tentative under
target owner `x`, but their computed roots remain slots `a` and `c`.
Consequently `cross_slot_merge_breaks_plan_semantics` proves the old plan is
invalid after the admitted Merge.  Separately, `merged_x_then_y_unsafe` and
`merged_y_then_x_unsafe` compute that neither target-owner order satisfies the
next-owner headroom test: each first batch contributes 2 and the second owner
has full tentative load 3, exceeding `K=4`.

## Observation theorem

`LocalAuthObs` is frozen to:

- the offered old plan ID;
- capacity and durable load; and
- for each scheduled claim ID, its demand, grant, coarse lifecycle phase, and
  grant epoch.

All claim metadata functions are masked outside the scheduled batch.  The
observation deliberately erases tentative owner, branch-correlation contract,
transfer root, and owner-slot grouping.

`local_observation_indistinguishable` proves equality between the valid source
history and the invalid admitted-Merge history.  The headline theorem has the
only explicit argument `f : LocalAuthObs -> Bool`:

```text
version_observation_lower_bound (f) :
  (f unsafeLocalObs = true /\ not unsafePlanSemantics) \/
  (f safeLocalObs = false /\ safePlanSemantics)
```

It therefore quantifies over every decision function on the frozen footprint:
the function either accepts the invalid cross-slot history or rejects the
valid source history.

## Global-versus-semantic pair

`irrelevantMutation` is the actual lifecycle restriction that removes only
the unplanned `none`-slot owner `u`; `irrelevant_mutation_actual_step`
constructs its real `Step.core (CoreStep.restriction ...)` transition.
`irrelevant_mutation_confined_to_none_slot` proves all scheduled statuses are
unchanged, while `u` moves from tentative to terminal.
`irrelevant_mutation_preserves_plan` proves the old plan remains admitted.

`GlobalObs` observes the whole-controller revision.  The actual irrelevant
mutation advances revision 40 to 41, so
`global_observation_rejects_irrelevant` proves global equality rejects it.

`SemanticObs` adds masked computed root lineage and scheduled co-owner
topology to `LocalAuthObs`:

- `semantic_observation_distinguishes_cross_slot` separates the source from
  the cross-slot Merge (claims `a` and `c` become co-owned); and
- `semantic_observation_ignores_irrelevant` remains equal across removal of
  `u`.

## Gates not claimed

- This module intentionally uses a self-contained finite old-plan predicate.
  It is not yet connected to the full authoritative `ControllerPlan` or the
  arbitrary `PlannedTrace` preservation theorem being developed elsewhere.
- The lower bound quantifies over all classifiers for this frozen observation
  type and fixed pair.  It is not a universal theorem about every per-object
  versioning scheme or every state size.
- The proposed semantic observation is proved sufficient to separate these
  two pairs.  The module does not claim its fields are globally minimal.
- `GlobalObs` wraps the real lifecycle state with a modeled controller
  revision because the base repository lifecycle has no global revision
  field.  The underlying irrelevant mutation itself is an actual repository
  `Step`.
- This subtask ran standalone module elaboration only, as requested.  It did
  not import the module into `Main.lean` or run a whole-library build; the root
  experiment should perform that integration serially.

## Invocation ledger

- `invocation-01.log`: failed; missing manual `LWF` proof, automatic Prop
  decidability, reserved field name, and observation extensionality.  The
  first shell also pointed `tee` at the wrong relative directory, so its
  captured output was retained manually in this log.
- `invocation-02.log`: failed; exposed the need to import `fin_cases`, raise
  the Merge-check computation bound, and prove function-valued observations
  fieldwise.
- `invocation-03.log`: failed; the Merge checker option did not cover
  declaration elaboration and structures lacked generated extensionality
  lemmas.
- `invocation-04.log`: succeeded for the initial theorem suite.
- `invocation-05.log`: succeeded after adding checker-soundness and switching
  the headline lower bound to the semantic `SlotDeadlines /\ OwnerPure`
  propositions.
