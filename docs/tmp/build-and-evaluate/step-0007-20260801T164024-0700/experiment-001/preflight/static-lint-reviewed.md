# Static lint of the reviewed Attempt-1 candidate

Date: 2026-08-01 (America/Vancouver)

Reviewed snapshot:

```text
candidate-attempt-1-reviewed.lean.txt
sha256 b8161ba8df2a853df240a23c3fa78a30ea8a5b1cb95488e19583bbfce856689f
```

This was a static-only review.  I did **not** invoke Lean, Lake, an editor
elaborator, or any other proof command.  At the time of this review, the
candidate and `lean/AuthorityContinuity/PlanPreflight.lean` were byte-identical.

## Verdict

```text
GO for the next retained invocation (currently scheduled as Attempt 2)
known definite syntax/type blockers: none after the fixes below
kernel/elaboration success: not asserted by this static review
```

The reviewed candidate follows the accepted thin-preflight architecture.  In
particular, it removes the old candidate's disallowed
`decide (PrepareOK ...)` shortcut and constructs every `PrepareOK` field from
the current lifecycle, the atomized assignment checker, and explicit source
obligations.

## Definite blockers found and fixed before this verdict

The snapshot above already contains all four repairs:

1. ASCII `in` used as membership was replaced by Lean's `∈` notation.
2. ASCII `sum` was replaced by the actual big-operator notation `∑`.
3. `singleton_child_RP_bound` now receives
   `sourcePlan.R sourcePlan.currentSlot` and
   `sourcePlan.P sourcePlan.currentSlot`, each of type `Coord -> Nat`, rather
   than the ill-typed unspecialized `Slot -> Coord -> Nat` fields.
4. `native_decide` is no longer invoked after introducing a free coordinate.
   The two source bounds are closed quantified propositions, and
   `child_P_fits` presents `∀ k : Coord` to `native_decide` as a closed goal.
   This matters because Lean's decide tactic rejects free variables unless the
   `+revert` option is used.

## Elaboration and type audit

### Computed transfer and the R/P bridge

- `childBatch` and `childRootSlot` are functions of the checked transfer's
  `rho`; there is no caller-supplied child batch or target root map.
- `afterTransfer_root_of_member` derives root inheritance from membership in
  that computed batch.
- `singleton_child_RP_bound` uses
  `Transfer.CoreValid.fiber_demand source k` for both bounds.  The second bound
  is converted with `childBatch_singleton`; it is not discharged by a fixture
  Boolean.
- In `child_RP_bound`, the argument order of `checkCanonical_sound` and
  `singleton_child_RP_bound` matches their repository signatures.  After the
  current-slot specialization, the types align.
- The final `simpa` in `child_RP_bound` is broad but has a coherent reduction
  path: unfold the controller/source/plan projections, rewrite the transported
  singleton batch with `childBatch_singleton`, and rewrite target load with the
  preceding `[simp] canonicalTarget_batchLoad`.  I found no static type
  mismatch.  This remains the likeliest local simp repair point if the next
  invocation reports an elaboration failure.

### Assignment checking and `PrepareOK`

- `checkAssignment` is decomposed into assigned-member/freshness, coverage,
  and injectivity atoms.  `checkAssignment_sound` extracts each atom through
  the existing `finiteAll_eq_true`; it never decides the `AssignmentValid`
  record as a whole.
- `prepare_head_is_ok` builds the actual repository `PrepareOK` record:
  nonemptiness is explicit; tentative status is explicit; branch and grant
  openness come from source `LWF`; assignment fields come from checker
  soundness; and `base` follows from the batch-P bound and `P` fitting current
  capacity.
- The `promotedLoad = durableLoad + batchLoad` line is definitionally aligned
  with `Checker.promotedLoad` and the local `batchLoad`, so `rfl` is plausible.
  `Nat.add_le_add_left` has the required left-addition orientation.
- There is no `decide (PrepareOK ...)`, assumed `PrepareOK`, target `LWF`,
  target `AC`, target plan-validity premise, or desired-result Boolean.

### Atomic Prepare and constructor order

- `preparedController` pairs the repository's exact
  `prepareState S.lifecycle S.plan.batch assignment` with `S.plan.advance` in
  one computed target.
- `PreparePlanned.mk` takes the source obligations in the same order used by
  `prepare_head_is_ok`.  The fixture's seven proof arguments follow that order.
- `PreparePlanned.actual_step` constructs `hOK` and embeds
  `CoreStep.prepare hOK` through `Step.core`; after case elimination,
  `preparedController` supplies the expected definitional target.
- `PreparePlanned.head_advanced` only unfolds `preparedController` and
  `PlanHead.advance`; its version and empty-batch projections are
  definitionally the record-update fields.
- `PlannedStep.canonical`, `.prepare`, `.revokeDone`, and `.ticket` calls match
  the declared explicit-argument order.  Their projections use the actual
  repository `Step` constructors rather than a parallel lifecycle relation.

### Revoke and Dispatch definitional targets

- `revokeController` preserves the plan only under the relation constructor's
  explicit empty-batch premise.  The actual lifecycle target is exactly
  `revokeState`.
- `revoked_ticket` has a valid unfolding route: `revokeState` is a structure
  update over `restrictLifecycle`, and both definitions preserve `tickets`
  definitionally.  Its current `simpa` is a second plausible local simp repair
  point, but I found no mismatch in the target.
- `TicketStep.dispatch revoked_ticket` computes exactly the lifecycle used by
  `dispatchController`.  The target record produced by `PlannedStep.ticket` is
  definitionally the same controller as `afterDispatch`; the plan is unchanged.
- The Dispatch theorem has no offered version, plan certificate, or head-check
  premise.  The endpoint then applies the existing `step_attempt_safe` with
  post-Revoke `LWF`.

### `native_decide` audit

Every remaining `native_decide` occurrence is presented with a syntactically
closed target: head/checker equalities, concrete finite batch/root/ticket
facts, the closed quantified source bounds, the closed quantified
`child_P_fits`, or the closed tentative-batch proposition.  I found no
remaining free-variable invocation and no attempt to decide a custom
`PrepareOK` structure.

As expected, theorems depending on `native_decide` may report Lean's native
evaluation trust axiom in `#print axioms`.  That is distinct from a project
axiom, `sorry`, or `admit`; the retained output should nevertheless be
classified explicitly in the result review.

## Plan-compliance conclusion

The candidate demonstrates exactly the approved vertical slice: a checked
replacing Restore; computed batch/root transport; an R/P fiber bound derived
from checker soundness; an authoritative version and atomized assignment
check; construction of actual `PrepareOK`; exact atomic Prepare plus head
advance; empty-plan Revoke; ticket-only Dispatch; and the existing
durable-before-attempt endpoint.

It does not claim the full slot theorem, arbitrary traces, same-slot Merge,
the observation lower bound, or physical exactly-once execution.  Static lint
therefore finds no remaining plan-compliance blocker to spending the next
retained attempt.
