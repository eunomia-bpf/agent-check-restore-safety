# Computed Prepare invariant closure

## Verdict

PASS.  The independent module
`lean/AuthorityContinuity/PlanInvariantPrepare.lean` reconstructs the complete
target plan certificate for the executable pair
`(prepareState A (p.headGroup A) assignment,
  p.afterPrepareGroup A assignment)`.

Final source SHA-256:
`e7f72976e00b7d09d72a92db3467a367002f16ef561a0670aa37e835997a374b`.

## Kernel-checked results

- `afterPrepareGroup_remaining_subset`: target remaining leaves come from the
  source selected batch.
- `afterPrepareGroup_preserves_remaining_rooted`: every surviving leaf has its
  actual target tentative owner and its unchanged source root in the unchanged
  slot set.
- `afterPrepareGroup_preserves_owner_root_pure`: target tentative ownership
  implies the same source ownership via the actual `preparedStatus`; immutable
  roots therefore remain owner-pure.
- `afterPrepareGroup_preserves_E_outside_zero`: the sole changed exposure row
  is the computed source head, which is proved to belong to the schedule.
- `afterPrepareGroup_target_valid`: independently reconstructs all `Valid`
  fields.  It uses the source-to-target DurableEq, Envelope, BatchBound, and
  CursorPhase theorems from `PlanInvariant`, and proves the remaining structural
  and unchanged fields here.  Target `Valid` is the conclusion, never a premise.
- `afterPrepareGroup_preserves_headPhaseBound`: re-derives the target head
  phase bound from the reconstructed target `Valid`; it is not stored as a
  trusted certificate field.
- `current_group_prepare_preserves_all`: from source `LWF`, `AC`,
  `ActiveExact`, source plan `Valid`, a nonempty remaining batch, and the
  executable assignment checker, simultaneously derives target `LWF`, target
  `AC`, target `ActiveExact`, target plan `Valid`, and the repository's actual
  `Step A .tau target`.

The plan-only target theorem accepts any assignment because assignment changes
tickets, not the authority promotion or plan accounting.  The end-to-end
lifecycle theorem requires `checkAssignment = true` and constructs the actual
`PrepareOK` rather than assuming it.

## Validation

- `invocation-01.log`: retained duplicate-name failure after the shared
  `PlanInvariant` acquired a tentative-root helper during parallel work.
- `invocation-02.log`: retained missing-`.olean` failure after the shared
  dependency changed.
- `invocation-03-build-dependency.log`: rebuilt the latest `PlanInvariant`,
  exit 0.
- `invocation-04.log`: retained duplicate-name failure after the shared module
  acquired its own complete target-valid theorem during parallel work; the
  independent theorem was renamed.
- `invocation-05.log`: retained one extra solved-goal tactic failure.
- `invocation-06.log`: direct module elaboration, exit 0.
- `invocation-07.log`: final direct elaboration including the end-to-end gate,
  exit 0.
- `invocation-08-lake-build.log`: final package build, exit 0, 8,485 jobs.
- `static-scan.log`: no `sorry`, `admit`, custom axiom declaration, or
  `native_decide`.
- Embedded `#print axioms` checks report only the accepted allowlist
  `[propext, Classical.choice, Quot.sound]` for the three headline theorems.

## Claim boundary

This closes repeated computed Prepare, not every history-transforming rule.
The theorem assumes a source `Valid` plan and nonempty remaining batch; plan
initialization and preservation across checked transfer, restriction, Restore,
and Merge remain separate obligations.  It proves logical lifecycle safety and
durable ticket installation, not physical exactly-once external execution or
compensation after Dispatch.
